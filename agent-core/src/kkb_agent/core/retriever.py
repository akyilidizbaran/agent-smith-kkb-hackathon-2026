"""Katalog retriever'ı: kademeli politika + yüz filtreleri + (isteğe bağlı) hibrit (ADR-0043).

Tek sınıf, üç kademe; adaptörler ve ölçüm koşucusu aynı nesneyi kullanır ki ölçülen şey
üretimde çalışan şey olsun:

* `preload_all`  — katalog bütçeye sığıyorsa arama yok, hepsi kart (küçük katalog).
* `bm25`         — BM25 + yüzler (il / frekans / kaynak). Aday havuzu `k`'nın 50 katı,
                   yüzler önce eler ve sıralar, sonra ilk `k`.
* `hybrid`       — BM25 ∪ embedding (kosinüs) → RRF → yüzler → ilk `k`. Embedder verilmemişse
                   bm25'e düşer ve bunu söyler.

Kademe seçimi: `RETRIEVAL_MODE=auto` → katalog boyutuna göre (`small_max`, `hybrid_min`
eşikleri); eşikler `scripts/retrieval_golden.py` ile ölçülerek konur, sezgiyle değil.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from ..contracts.retrieval import Candidate, Embedder, reciprocal_rank_fusion
from ..source_hints import load_source_hints
from .facets import (
    FREQUENCY_WORDS,
    Facets,
    extract_facets,
    frequency_rank,
    province_of,
    source_matches,
)
from .lexical import Bm25Index, candidate_text, fold, tokenize

MODES = ("auto", "preload_all", "bm25", "hybrid")
DEFAULT_SMALL_MAX = 60        # bu sayıya kadar katalog kart olarak sığar (≈ 6.000 token bütçesi)
DEFAULT_HYBRID_MIN = 5000     # bu sayıdan sonra BM25 tek başına yetmez (ölçülecek)
CANDIDATE_MULTIPLIER = 50     # yüz filtrelerinden önce aday havuzu; il serileri filtrelenmeden önce kaybolmasın
_QUERY_SPLIT = re.compile(r"\b(?:ve|ile|veya)\b|[,;]", re.IGNORECASE)
_BREAKDOWN_INTENT = re.compile(
    r"\b(?:alt\s+kalem(?:ler)?(?:i|ı)?|kırılım(?:lar)?(?:ı|i)?|kirilim(?:lar)?(?:i|ı)?|detay(?:lar)?(?:ı|i)?|"
    r"dağılım(?:ı|i)?|dagilim(?:i)?|bileşen(?:ler)?|bilesen(?:ler)?|"
    r"taksitli|taksitsiz|ayrıştır|ayristir)\b",
    re.IGNORECASE,
)
_MEASURE_INTENTS = (
    ("stock", re.compile(r"\b(?:stok\w*|bakiy\w*|balance|outstanding)\b|\bdonem\s+son\w*|\bay\s+son\w*|\byil\s+son\w*")),
    ("flow", re.compile(r"\b(?:akim\w*|flow|kullandirim\w*|harcama\w*|ciro\w*|donem\s+ici)\b")),
    ("rate", re.compile(r"\b(?:faiz\w*|interest\s+rate|yield|getiri\w*)\b")),
    ("ratio", re.compile(r"(?:%|\b(?:rasyo\w*|ratio|oran\w*|yuzde\w*|payda)\b)")),
    ("index", re.compile(r"\b(?:endeks\w*|index)\b")),
    ("count", re.compile(r"\b(?:adet\w*|sayi\w*|count)\b")),
)
_CHANGE_INTENT = re.compile(r"\b(?:degisim\w*|fark\w*|artis\w*|azalis\w*|growth|change|return)\b")
_RANKING_CONTEXT_TERMS = frozenset({
    "veri", "veriler", "dataset", "data", "seri", "seriler", "tablo", "tablosu", "kaynak",
    "bulten", "getir", "getirin", "listele", "goster", "gosterin", "bul", "find", "show",
    "ulusal", "national", "turkiye", "turkey", "turkish", "sektor", "genel", "geneli",
})


@dataclass(frozen=True)
class CatalogRecord:
    """Retriever'ın gördüğü kadarıyla bir seri: kimlik, metin ve yüzler."""
    id: str
    name: str
    description: str = ""
    aliases: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    frequency: str | None = None
    source: str | None = None
    province: str | None = None    # None → ulusal/il-dışı
    concept_id: str | None = None
    parent_series_id: str | None = None
    relation_type: str = "standalone"
    dimension_path: tuple[str, ...] = ()
    additivity: str = "unknown"
    relation_confidence: str | None = None
    relation_source: str | None = None
    semantic_confidence: str | None = None
    measure_type: str | None = None
    measure_types: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        return candidate_text(name=self.name, description=self.description, tags=self.tags,
                              aliases=self.aliases, dataset_id=self.id)


def record_from_spec(spec) -> CatalogRecord:
    aliases = tuple(a for c in spec.columns for a in c.aliases)
    freq = getattr(spec.frequency, "value", spec.frequency)
    measure_types = tuple(sorted({
        str(getattr(column.semantic_type, "value", column.semantic_type))
        for column in spec.measures()
        if getattr(column, "semantic_type", None)
    }))
    return CatalogRecord(id=spec.dataset_id, name=spec.name, description=spec.description, aliases=aliases,
                         tags=tuple(spec.tags), frequency=str(freq) if freq else None, source=spec.source,
                         province=province_of(f"{spec.dataset_id} {spec.name}"),
                         concept_id=getattr(spec, "concept_id", None),
                         parent_series_id=getattr(spec, "parent_series_id", None),
                         relation_type=getattr(spec, "relation_type", "standalone"),
                         dimension_path=tuple(getattr(spec, "dimension_path", ()) or ()),
                         additivity=getattr(spec, "additivity", "unknown"),
                         relation_confidence=getattr(spec, "relation_confidence", None),
                         relation_source=getattr(spec, "relation_source", None),
                         semantic_confidence=getattr(spec, "semantic_confidence", None),
                         measure_type=getattr(spec, "measure_type", None) or (measure_types[0] if len(measure_types) == 1 else None),
                         measure_types=measure_types)


def _query_measure_intents(query: str) -> frozenset[str]:
    """Return only explicit measurement semantics, never infer from a metric name."""
    folded = fold(query)
    found = {kind for kind, pattern in _MEASURE_INTENTS if pattern.search(folded)}
    # A percent/fraction produced by a requested change calculation describes
    # the output, not necessarily the source series' measurement type.
    if "ratio" in found and _CHANGE_INTENT.search(folded):
        found.remove("ratio")
    # In Turkish, "faiz oranı" is a rate, not a generic ratio.
    if "rate" in found:
        found.discard("ratio")
    return frozenset(found)


def _query_topic_terms(query: str, facets: Facets) -> tuple[str, ...]:
    """Remove retrieval context (source, frequency, geography, request verbs).

    What remains are the terms that distinguish one requested concept from
    another. Their order is retained so exact name/alias coverage is stable.
    """
    ignored = set(_RANKING_CONTEXT_TERMS)
    ignored.update(token for values in FREQUENCY_WORDS.values() for phrase in values
                   for token in tokenize(phrase, prefixes=False))
    for source, words in load_source_hints().get("source_words", {}).items():
        ignored.update(tokenize(source, prefixes=False))
        ignored.update(token for phrase in words for token in tokenize(phrase, prefixes=False))
    ignored.update(token for province in facets.provinces for token in tokenize(province, prefixes=False))
    if facets.national:
        ignored.update({"ulusal", "national", "turkiye", "turkey", "genel", "geneli", "sektor"})

    terms: list[str] = []
    for token in tokenize(query, prefixes=False):
        if token.isdigit() or token in ignored or token in terms:
            continue
        terms.append(token)
    return tuple(terms)


def _measure_types(record: CatalogRecord | None) -> tuple[str, ...]:
    if record is None:
        return ()
    values = record.measure_types or ((record.measure_type,) if record.measure_type else ())
    return tuple(sorted({str(getattr(value, "value", value)).casefold() for value in values if value}))


@dataclass
class RetrievalPolicy:
    mode: str = "auto"
    small_max: int = DEFAULT_SMALL_MAX
    hybrid_min: int = DEFAULT_HYBRID_MIN

    def resolve(self, n_records: int, *, embedder_available: bool) -> str:
        if self.mode != "auto":
            if self.mode == "hybrid" and not embedder_available:
                return "bm25"
            return self.mode
        if n_records <= self.small_max:
            return "preload_all"
        if n_records >= self.hybrid_min and embedder_available:
            return "hybrid"
        return "bm25"


def apply_facets(records: Sequence[CatalogRecord], ranked: Sequence[Candidate], facets: Facets, *, k: int) -> list[Candidate]:
    """Yüzler: il varsa yalnız o il (yoksa il-dışı seriler öne); frekans varsa önce o frekans
    (sonra daha ince olanlar: Gold kaba yapabilir; kaba olanlar en sona); kaynak ipucu varsa öne."""
    by_id = {r.id: r for r in records}
    kept: list[tuple[tuple, Candidate]] = []
    for pos, cand in enumerate(ranked):
        rec = by_id.get(cand.id)
        if rec is None:
            continue
        if facets.provinces:
            if rec.province is None or rec.province not in facets.provinces:
                # il soruldu: başka ilin serisi elenir; ulusal seri geride kalır ama düşmez
                if rec.province is not None:
                    continue
                prov_key = 1
            else:
                prov_key = 0
        else:
            # No province asked (including an explicit national request):
            # provincial series rank behind national ones but are not dropped,
            # so a catalog without a national parent still returns candidates.
            prov_key = 1 if rec.province is not None else 0
        wanted_frequency = facets.frequency or facets.window_frequency
        if wanted_frequency:
            want, have = frequency_rank(wanted_frequency), frequency_rank(rec.frequency)
            if want is None or have is None:
                freq_key = 1
            elif have == want:
                freq_key = 0
            elif have < want:
                freq_key = 1       # daha ince: Gold ile istenen frekansa indirgenebilir
            else:
                freq_key = 2       # daha kaba: istenen frekans üretilemez
        else:
            freq_key = 0
        src_key = 0 if (not facets.sources or source_matches(rec.source, facets.sources)) else 1
        kept.append(((prov_key, freq_key, src_key, pos), cand))
    kept.sort(key=lambda t: t[0])
    out = []
    for key, cand in kept[:k]:
        meta = {**cand.meta, "facet_rank": key[:3]}
        out.append(Candidate(id=cand.id, text=cand.text, score=cand.score, source=cand.source, meta=meta))
    return out


class CatalogRetriever:
    def __init__(self, records: Iterable[CatalogRecord], *, policy: RetrievalPolicy | None = None,
                 embedder: Embedder | None = None, embedding_cache=None) -> None:
        self.records = list(records)
        self.policy = policy or RetrievalPolicy()
        self.embedder = embedder
        self._by_id = {r.id: r for r in self.records}
        self._bm25 = Bm25Index()
        self._bm25.index([Candidate(id=r.id, text=r.text) for r in self.records])
        self._vectors: list[list[float]] | None = None
        self._cache = embedding_cache
        self.mode = self.policy.resolve(len(self.records), embedder_available=embedder is not None)
        self.last_facets: Facets = Facets()
        self.last_error: str | None = None

    # ---------- yoğun vektörler (yalnız hybrid) ----------
    def _ensure_vectors(self) -> None:
        if self._vectors is not None or self.embedder is None:
            return
        texts = [f"{r.name}. {' '.join(r.aliases)}".strip() for r in self.records]
        cached = self._cache.get(self.embedder.model, [r.id for r in self.records], texts) if self._cache else None
        if cached is None:
            vectors = []
            for i in range(0, len(texts), 64):
                vectors.extend(self.embedder.embed(texts[i:i + 64]))
            if self._cache:
                self._cache.put(self.embedder.model, [r.id for r in self.records], texts, vectors)
            cached = vectors
        self._vectors = cached

    def _load_cached_vectors(self) -> bool:
        """Load a complete catalog vector cache without making a network call.

        A catalog refresh must never turn the first user question into an
        unbounded embedding migration. Large catalogs can be queried with the
        deterministic lexical index while a cache warmer is run separately.
        The explicit ``_ensure_vectors`` path remains available for warm-up.
        """
        if self._vectors is not None:
            return True
        if self.embedder is None or self._cache is None:
            return False
        texts = [f"{r.name}. {' '.join(r.aliases)}".strip() for r in self.records]
        cached = self._cache.get(self.embedder.model, [r.id for r in self.records], texts)
        if cached is None:
            return False
        self._vectors = cached
        return True

    def embed_queries(self, queries: Sequence[str]) -> list[list[float]]:
        """Ölçüm koşucusu için: binlerce sorgunun vektörü tek tek değil 64'lük dilimlerle."""
        assert self.embedder is not None
        out: list[list[float]] = []
        for i in range(0, len(queries), 64):
            out.extend(self.embedder.embed(list(queries[i:i + 64])))
        return out

    def _dense(self, query: str, *, k: int, query_vector: Sequence[float] | None = None) -> list[Candidate]:
        """Kosinüs benzerliği numpy ile: 2.214 × 4096 için sorgu başına milisaniye (saf Python
        döngüsü sorgu başına saniyeler alıyordu — ölçüldü, ölçüm koşusu bitmedi)."""
        self._ensure_vectors()
        assert self._vectors is not None and self.embedder is not None
        if getattr(self, "_matrix", None) is None:
            m = np.asarray(self._vectors, dtype=np.float32)
            norms = np.linalg.norm(m, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            self._matrix = m / norms
        q = np.asarray(list(query_vector) if query_vector is not None else self.embedder.embed([query])[0], dtype=np.float32)
        q = q / (np.linalg.norm(q) or 1.0)
        sims = self._matrix @ q
        top = np.argsort(-sims, kind="stable")[:k]
        return [Candidate(id=self.records[i].id, text=self.records[i].text, score=float(sims[i]), source="embedding")
                for i in top]

    def _relation_adjust(self, query: str, ranked: Sequence[Candidate]) -> list[Candidate]:
        """Apply the canonical relation graph before the final top-k cut.

        A broad concept resolves to its verified/derived parent total.  A query that asks
        for a breakdown or names a child explicitly keeps the children and expands a parent
        hit to its direct children.  This is source-independent; BDDK/FinTürk/EVDS only
        provide the metadata graph.
        """

        by_id = self._by_id
        if not any(record.relation_type != "standalone" for record in self.records):
            return list(ranked)
        explicit_breakdown = bool(_BREAKDOWN_INTENT.search(query or ""))
        children: dict[str, list[CatalogRecord]] = {}
        for record in self.records:
            if record.parent_series_id and record.parent_series_id in by_id:
                children.setdefault(record.parent_series_id, []).append(record)

        by_candidate = {candidate.id: candidate for candidate in ranked}
        output: dict[str, Candidate] = dict(by_candidate)
        query_tokens = set(tokenize(query or "", prefixes=False))
        for candidate in ranked:
            record = by_id.get(candidate.id)
            if record is None:
                continue
            if record.relation_type == "child_breakdown" and record.parent_series_id in by_id:
                parent = by_id[record.parent_series_id]
                if not explicit_breakdown:
                    # A child found by a shared token must not hide the parent total.  Keep
                    # the child available for explicit follow-up/breakdown queries, but rank
                    # it below the parent for a broad concept.
                    parent_candidate = output.get(parent.id)
                    parent_score = max(candidate.score + 0.001, parent_candidate.score if parent_candidate else float("-inf"))
                    output[parent.id] = Candidate(
                        id=parent.id, text=parent.text, score=parent_score,
                        source=parent.source,
                        meta={"relation_promoted_from": candidate.id, "relation_type": parent.relation_type},
                    )
                continue
            if explicit_breakdown and record.relation_type == "parent_total":
                siblings = children.get(record.id, [])
                # If the user names one child dimension (for example ``taksitli``),
                # keep the parent as context but demote unrelated siblings.  A generic
                # token comparison avoids a source-specific list of child labels.
                # ``record.text`` also carries inherited catalog aliases, which may
                # contain the child labels themselves (for example ``taksitli`` and
                # ``taksitsiz`` on the card parent).  Use the canonical parent name
                # here so an explicitly named dimension remains distinguishable.
                parent_tokens = set(tokenize(record.name, prefixes=False))
                specific_tokens = query_tokens - parent_tokens
                targeted = [
                    child for child in siblings
                    if specific_tokens.intersection(set(tokenize(child.text, prefixes=False)))
                ]
                # If a child dimension is named explicitly, expand only that child.
                # This avoids re-introducing an unrelated sibling merely because the
                # parent was selected first.  With no named dimension ("alt kalemler"
                # / "kırılım"), retain the complete direct breakdown.
                expansion_children = targeted or siblings
                for sibling in siblings:
                    if targeted and sibling not in targeted and sibling.id in output:
                        current = output[sibling.id]
                        output[sibling.id] = Candidate(
                            id=current.id, text=current.text, score=current.score - 0.25,
                            source=current.source, meta={**current.meta, "relation_sibling_demoted": record.id},
                        )
                for child in expansion_children:
                    expanded_score = candidate.score - 0.002
                    existing = output.get(child.id)
                    if existing is None or existing.score < expanded_score:
                        output[child.id] = Candidate(
                            id=child.id, text=child.text,
                            # Keep parent relevance as a tie-breaker; lexical ranking inside
                            # the child is still performed by the caller on a later query.
                            score=expanded_score,
                            source=child.source,
                            meta={"relation_expanded_from": record.id, "relation_type": child.relation_type},
                        )
        return sorted(output.values(), key=lambda value: (-value.score, value.id))

    def _semantic_tie_break(self, query: str, ranked: Sequence[Candidate], facets: Facets) -> list[Candidate]:
        """Refine only close lexical cohorts with explicit semantic evidence.

        BM25 can over-rank shared source/frequency words over the requested
        concept. Inside a 15% score cohort, explicit measure intent and direct
        name/alias coverage resolve that ambiguity. Verification is used only
        for candidates with the same matched concept terms and measure type.
        """
        if len(ranked) < 2:
            return list(ranked)
        topic_terms = _query_topic_terms(query, facets)
        measure_intents = _query_measure_intents(query)
        output: list[Candidate] = []
        cursor = 0
        while cursor < len(ranked):
            leader = ranked[cursor]
            floor = leader.score * 0.85
            cohort = [leader]
            cursor += 1
            while cursor < len(ranked) and ranked[cursor].score >= floor:
                cohort.append(ranked[cursor])
                cursor += 1
            if len(cohort) > 1:
                decorated: list[tuple[Candidate, tuple[int, tuple[int, ...]], tuple[str, ...]]] = []
                for candidate in cohort:
                    record = self._by_id.get(candidate.id)
                    candidate_types = _measure_types(record)
                    if not measure_intents or (candidate_types and measure_intents.intersection(candidate_types)):
                        intent_rank = 0
                    elif candidate_types:
                        intent_rank = 2
                    else:
                        intent_rank = 1
                    name_tokens = set(tokenize(
                        " ".join((record.name, *record.aliases)) if record else candidate.text,
                        prefixes=False,
                    ))
                    topic_signature = tuple(int(term in name_tokens) for term in topic_terms)
                    decorated.append((candidate, (intent_rank, topic_signature), candidate_types))

                # Stable sort keeps BM25 order when explicit semantic evidence
                # is equal. The booleans use descending order for term coverage.
                decorated.sort(key=lambda item: (item[1][0], tuple(-hit for hit in item[1][1])))

                # Verification only breaks ties between the same topic match
                # and measurement kind; it cannot promote an unrelated series.
                start = 0
                while start < len(decorated):
                    end = start + 1
                    group_key = (decorated[start][1], decorated[start][2])
                    while end < len(decorated) and (decorated[end][1], decorated[end][2]) == group_key:
                        end += 1
                    same_semantics = decorated[start:end]
                    if any(group_key[0][1]):
                        same_semantics.sort(key=lambda item: (
                            0 if getattr(self._by_id.get(item[0].id), "semantic_confidence", None) == "verified" else 1
                        ))
                    decorated[start:end] = same_semantics
                    start = end
                output.extend(item[0] for item in decorated)
            else:
                output.extend(cohort)
        return output

    def _with_semantic_metadata(self, candidates: Sequence[Candidate]) -> list[Candidate]:
        out: list[Candidate] = []
        for candidate in candidates:
            record = self._by_id.get(candidate.id)
            meta = dict(candidate.meta)
            if record is not None:
                if record.semantic_confidence:
                    meta["semantic_confidence"] = record.semantic_confidence
                if record.measure_type:
                    meta["measure_type"] = record.measure_type
                if record.measure_types:
                    meta["measure_types"] = record.measure_types
            out.append(Candidate(candidate.id, candidate.text, candidate.score, candidate.source, meta))
        return out

    # ---------- arama ----------
    def search(self, query: str, *, k: int = 8, mode: str | None = None, use_facets: bool = True,
               query_vector: Sequence[float] | None = None) -> list[Candidate]:
        mode = mode or self.mode
        facets = extract_facets(query) if use_facets else Facets()
        self.last_facets = facets
        pool = max(k * CANDIDATE_MULTIPLIER, 50)
        # A question can contain several requested concepts joined by "ve".
        # Ranking the complete sentence lets the first concept fill the whole
        # pool (for example, provincial child series hide a national parent).
        # Search each clause as well and union the hits before applying the
        # source/geography/frequency facets. This is domain independent.
        variants = [query]
        variants.extend(part.strip() for part in _QUERY_SPLIT.split(query)
                        if len(part.strip().split()) >= 2)
        lexical_by_id: dict[str, Candidate] = {}
        for variant in dict.fromkeys(variants):
            # Apply the user's hard facets before taking the clause pool. A
            # large family of provincial children must not consume all 400
            # lexical slots and hide the national parent that the next clause
            # identifies.
            # Repeated variants (e.g. 81 provinces) can still occupy the
            # lexical top-k before filtering. With any hard facet, scanning
            # the in-memory BM25 result set is cheaper and safer than losing
            # the only national/target-frequency candidate.
            raw_k = len(self.records) if use_facets and not facets.empty else pool
            clause_hits = self._bm25.search(variant, k=raw_k)
            if use_facets:
                clause_hits = apply_facets(self.records, clause_hits, facets, k=pool)
            for cand in clause_hits:
                previous = lexical_by_id.get(cand.id)
                if previous is None or cand.score > previous.score:
                    lexical_by_id[cand.id] = cand
        lexical = sorted(lexical_by_id.values(), key=lambda c: (-c.score, c.id))
        if mode == "hybrid" and self.embedder is not None:
            try:
                # A cold full-catalog embedding pass is expensive (6k+ series
                # means roughly a hundred remote batches). It is not allowed
                # on the interactive request path for large catalogs. A warm
                # cache remains fully hybrid; small seed/test catalogs retain
                # the eager behaviour used by the retrieval tests.
                if len(self.records) > 1000 and not self._load_cached_vectors():
                    self.last_error = "embedding cache cold-start; BM25 fallback"
                    dense = []
                else:
                    dense = self._dense(query, k=pool, query_vector=query_vector)
            except Exception as exc:  # noqa: BLE001 — embedding ucu düşerse BM25 ile devam, sessiz değil
                self.last_error = f"embedding: {exc}"
                dense = []
            # Sözlük eşleşmesi olmayan yoğun adaylar da havuza girer; RRF ikisini birleştirir.
            ranked = reciprocal_rank_fusion(lexical, dense) if dense else list(lexical)
        else:
            ranked = list(lexical)
        ranked = self._relation_adjust(query, ranked)
        ranked = self._with_semantic_metadata(ranked)
        ranked = self._semantic_tie_break(query, ranked, facets)
        return apply_facets(self.records, ranked, facets, k=k)

    def __len__(self) -> int:
        return len(self.records)


__all__ = [
    "CANDIDATE_MULTIPLIER",
    "DEFAULT_HYBRID_MIN",
    "DEFAULT_SMALL_MAX",
    "MODES",
    "CatalogRecord",
    "CatalogRetriever",
    "RetrievalPolicy",
    "apply_facets",
    "record_from_spec",
]
