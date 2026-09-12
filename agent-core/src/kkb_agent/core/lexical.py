"""BM25 sözlük dizini — retrieval sözleşmesinin (`LexicalIndex`) ilk gerçek uygulaması (D2).

Mentör: BM25/embedding/reranker yardımcı bileşenler serbest, ana LLM MIA kalır (ADR-0021).
Kesin terimlerde BM25 embedding'i yener (ADR-0015 ölçümü); katalogdaki seri adları ve
takma adlar tam da böyle terimlerdir. Dış bağımlılık yok: 1.620 seri için saf Python
yeterli ve deterministik.

Türkçe için iki küçük karar:
- Katlama: `İ/ı/ş/ğ/ü/ö/ç` ASCII'ye katlanır ve küçük harfe indirilir; "İhtiyaç" ile
  "ihtiyac" aynı belirteç. Kaynak metinler ve sorular her iki yazımla geliyor.
- Kök yaklaşımı: ekli sözcükler ("kredisi", "kredileri") için belirtecin 5+ karakterlik
  ön ekleri de dizine girer; "kredi" sorgusu "kredisi"yi bulur. Gerçek bir kök ayırıcı
  değil, ölçülebilir ucuz bir yaklaşım; yanlış pozitifleri BM25 ağırlığı bastırır.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Sequence

from ..contracts.retrieval import Candidate

_TR = str.maketrans({"ı": "i", "İ": "i", "I": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
                     "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c"})
_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = frozenset({"ve", "ile", "icin", "olan", "olarak", "bir", "bu", "su", "the", "and", "of",
                   "da", "de", "mi", "mu", "ne", "kadar", "goster", "gosterir", "hesapla", "soyle"})
MIN_PREFIX = 5
PREFIX_WEIGHT = 0.5
"""Ön ek eşleşmesi tam sözcüğün yarısı kadar sayılır: geri çağırmayı artırır, sırayı belirlemez."""


def fold(text: str) -> str:
    text = str(text).translate(_TR).lower()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def tokenize(text: str, *, prefixes: bool = True) -> list[str]:
    """Katlanmış belirteçler + (isteğe bağlı) 5+ karakterlik ön ekler."""
    out: list[str] = []
    for tok in _TOKEN.findall(fold(text)):
        if len(tok) < 2 or tok in _STOP:
            continue
        out.append(tok)
        if prefixes and len(tok) > MIN_PREFIX:
            out.extend(tok[:n] for n in range(MIN_PREFIX, len(tok)))
    return out


class Bm25Index:
    """Okazaki BM25; `index()` sonrası `search()` deterministik (skor, sonra kimlik)."""

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._docs: list[Candidate] = []
        self._tf: list[Counter[str]] = []
        self._len: list[int] = []
        self._df: Counter[str] = Counter()
        self._full_tokens: list[set[str]] = []
        self._avg_len = 0.0

    def index(self, candidates: Sequence[Candidate]) -> None:
        self._docs = list(candidates)
        self._tf, self._len, self._df = [], [], Counter()
        self._full_tokens: list[set[str]] = []
        for cand in self._docs:
            toks = tokenize(cand.text)
            tf = Counter(toks)
            self._tf.append(tf)
            self._len.append(len(toks))
            self._df.update(tf.keys())
            self._full_tokens.append(set(tokenize(cand.text, prefixes=False)))
        self._avg_len = (sum(self._len) / len(self._len)) if self._len else 0.0

    def __len__(self) -> int:
        return len(self._docs)

    def _idf(self, term: str) -> float:
        n, df = len(self._docs), self._df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def search(self, query: str, *, k: int = 10, require_full_match: bool = True) -> list[Candidate]:
        """Skora göre ilk k. `require_full_match`: yalnız ön ek üzerinden eşleşen belge elenir.

        Ölçüldü: "ihtiyaç kredileri" sorgusu yalnız "kredi" ön eki yüzünden konut serisini
        döndürüyordu; ön ek geri çağırmayı artırır ama tek başına isabet sayılmaz. En az
        bir TAM sözcük eşleşmesi şart; `meta["matched"]` / `meta["unmatched"]` hangi
        sözcüklerin eşleştiğini taşır ki araç kartı "taşıt eşleşmedi" diyebilsin.
        """
        if not self._docs:
            return []
        q_full = [t for t in tokenize(query, prefixes=False)]
        q_full_set = set(q_full)
        q_terms = set(tokenize(query))
        if not q_terms:
            return []
        scored: list[tuple[float, str, int, list[str], list[str]]] = []
        for i, tf in enumerate(self._tf):
            score = 0.0
            dl = self._len[i] or 1
            for term in q_terms:
                f = tf.get(term)
                if not f:
                    continue
                idf = self._idf(term)
                weight = 1.0 if term in q_full_set else PREFIX_WEIGHT   # ön ek yarım sayılır
                score += weight * idf * (f * (self.k1 + 1)) / (f + self.k1 * (1 - self.b + self.b * dl / self._avg_len))
            if score <= 0:
                continue
            full = self._full_tokens[i]
            matched = [t for t in q_full if t in full]
            unmatched = [t for t in q_full if t not in full]
            if require_full_match and not matched:
                continue
            scored.append((score, self._docs[i].id, i, matched, unmatched))
        scored.sort(key=lambda t: (-t[0], t[1]))
        out: list[Candidate] = []
        for score, _, i, matched, unmatched in scored[:k]:
            d = self._docs[i]
            out.append(Candidate(id=d.id, text=d.text, score=score, source="bm25",
                                 meta={**d.meta, "matched": matched, "unmatched": unmatched}))
        return out


def candidate_text(*, name: str, description: str, tags: Sequence[str], aliases: Sequence[str],
                   dataset_id: str, alias_weight: int = 3) -> str:
    """Katalog kaydından dizin metni: takma adlar `alias_weight` kez tekrarlanır (ADR-0003:
    kullanıcının söyleyeceği ifadeler en güçlü sinyal)."""
    parts = [dataset_id.replace(":", " ").replace("_", " "), name, description, " ".join(tags)]
    parts += [" ".join(aliases)] * alias_weight
    return " ".join(p for p in parts if p)


__all__ = ["Bm25Index", "MIN_PREFIX", "PREFIX_WEIGHT", "candidate_text", "fold", "tokenize"]
