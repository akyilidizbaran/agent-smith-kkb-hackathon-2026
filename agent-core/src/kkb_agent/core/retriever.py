"""Katalog retriever'ı: kademeli politika + yüz filtreleri + (isteğe bağlı) hibrit (ADR-0043).

Tek sınıf, üç kademe; adaptörler ve ölçüm koşucusu aynı nesneyi kullanır ki ölçülen şey
üretimde çalışan şey olsun:

* `preload_all`  — katalog bütçeye sığıyorsa arama yok, hepsi kart (küçük katalog).
* `bm25`         — BM25 + yüzler (il / frekans / kaynak). Aday havuzu `k`'nın 10 katı,
                   yüzler önce eler ve sıralar, sonra ilk `k`.
* `hybrid`       — BM25 ∪ embedding (kosinüs) → RRF → yüzler → ilk `k`. Embedder verilmemişse
                   bm25'e düşer ve bunu söyler.

Kademe seçimi: `RETRIEVAL_MODE=auto` → katalog boyutuna göre (`small_max`, `hybrid_min`
eşikleri); eşikler `scripts/retrieval_golden.py` ile ölçülerek konur, sezgiyle değil.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from typing import Iterable, Sequence

from ..adapters.mia_embedder import record_digest as _record_digest
from ..contracts.retrieval import Candidate, Embedder, reciprocal_rank_fusion
from .facets import Facets, extract_facets, frequency_rank, province_of
from .lexical import Bm25Index, candidate_text

MODES = ("auto", "preload_all", "bm25", "hybrid")
DEFAULT_SMALL_MAX = 60        # bu sayıya kadar katalog kart olarak sığar (≈ 6.000 token bütçesi)
DEFAULT_HYBRID_MIN = 5000     # bu sayıdan sonra BM25 tek başına yetmez (ölçülecek)
CANDIDATE_MULTIPLIER = 10     # yüz filtrelerinden önce aday havuzu k × bu


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

    @property
    def text(self) -> str:
        return candidate_text(name=self.name, description=self.description, tags=self.tags,
                              aliases=self.aliases, dataset_id=self.id)


def record_from_spec(spec) -> CatalogRecord:
    aliases = tuple(a for c in spec.columns for a in c.aliases)
    freq = getattr(spec.frequency, "value", spec.frequency)
    return CatalogRecord(id=spec.dataset_id, name=spec.name, description=spec.description, aliases=aliases,
                         tags=tuple(spec.tags), frequency=str(freq) if freq else None, source=spec.source,
                         province=province_of(f"{spec.dataset_id} {spec.name}"))


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
            prov_key = 1 if rec.province is not None else 0
        if facets.frequency:
            want, have = frequency_rank(facets.frequency), frequency_rank(rec.frequency)
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
        src_key = 0 if (not facets.sources or rec.source in facets.sources) else 1
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
        self.embedded_fresh = 0      # son vektör kurulumunda MIA'ya gönderilen kayıt sayısı (ölçüm/iz için)
        self.embedded_reused = 0     # önceki önbellek sürümünden alınan kayıt sayısı
        self.mode = self.policy.resolve(len(self.records), embedder_available=embedder is not None)
        self.last_facets: Facets = Facets()
        self.last_error: str | None = None

    # ---------- yoğun vektörler (yalnız hybrid) ----------
    def _ensure_vectors(self) -> None:
        if self._vectors is not None or self.embedder is None:
            return
        texts = [f"{r.name}. {' '.join(r.aliases)}".strip() for r in self.records]
        ids = [r.id for r in self.records]
        cached = self._cache.get(self.embedder.model, ids, texts) if self._cache else None
        if cached is None:
            # Artımlı yol: katalog değiştiyse (Architect bir taslak ekledi, alias düzeltildi) yalnız parmak izi
            # tutmayan kayıtlar gömülür; gerisi en yeni önceki sürümden okunur. Sonuç tam hesapla birebir aynıdır.
            reused: dict[str, list[float]] = {}
            if self._cache and hasattr(self._cache, "reuse"):
                try:
                    reused = self._cache.reuse(self.embedder.model, ids, texts)
                except Exception:  # noqa: BLE001 — önbellek hızlandırıcıdır; okunamazsa tam hesap
                    reused = {}
            digests = [_record_digest(i, t) for i, t in zip(ids, texts)] if reused else [None] * len(ids)
            missing = [k for k, d in enumerate(digests) if d not in reused]
            fresh: dict[int, list[float]] = {}
            for i in range(0, len(missing), 64):
                chunk = missing[i:i + 64]
                for k, vec in zip(chunk, self.embedder.embed([texts[k] for k in chunk])):
                    fresh[k] = vec
            vectors = [fresh[k] if k in fresh else reused[digests[k]] for k in range(len(ids))]
            self.embedded_fresh = len(missing)
            self.embedded_reused = len(ids) - len(missing)
            if self._cache:
                self._cache.put(self.embedder.model, ids, texts, vectors)
            cached = vectors
        self._vectors = cached

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

    # ---------- arama ----------
    def search(self, query: str, *, k: int = 8, mode: str | None = None, use_facets: bool = True,
               query_vector: Sequence[float] | None = None) -> list[Candidate]:
        mode = mode or self.mode
        facets = extract_facets(query) if use_facets else Facets()
        self.last_facets = facets
        pool = max(k * CANDIDATE_MULTIPLIER, 50)
        lexical = self._bm25.search(query, k=pool)
        if mode == "hybrid" and self.embedder is not None:
            try:
                dense = self._dense(query, k=pool, query_vector=query_vector)
            except Exception as exc:  # noqa: BLE001 — embedding ucu düşerse BM25 ile devam, sessiz değil
                self.last_error = f"embedding: {exc}"
                dense = []
            # Sözlük eşleşmesi olmayan yoğun adaylar da havuza girer; RRF ikisini birleştirir.
            ranked = reciprocal_rank_fusion(lexical, dense) if dense else list(lexical)
        else:
            ranked = list(lexical)
        return apply_facets(self.records, ranked, facets, k=k)

    def __len__(self) -> int:
        return len(self.records)


__all__ = ["CANDIDATE_MULTIPLIER", "CatalogRecord", "CatalogRetriever", "DEFAULT_HYBRID_MIN", "DEFAULT_SMALL_MAX",
           "MODES", "RetrievalPolicy", "apply_facets", "record_from_spec"]
