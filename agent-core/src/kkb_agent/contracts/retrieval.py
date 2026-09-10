"""Retrieval katmanı sözleşmesi — arama/sıralama bileşenleri, ana LLM'den ayrı.

Mentör kararı (10 Eylül): sentence-transformer, reranker, BM25 gibi yardımcı
bileşenler retrieval/ranking tarafında serbest; "ana LLM MIA olarak kalacak
şekilde ayrı bir katmanda konumlandırın." ADR-0015'in kural engeli kalktı;
karar artık yalnız ölçümle verilir.

Üç bağımsız yetenek, üç ayrı Protocol — birini değiştirmek diğerlerine
dokunmaz. Embedder MIA'nın Qwen3-Embedding-8B'si de olabilir, yerel bir
model de; Reranker yerel cross-encoder da olabilir, LLM-as-reranker da.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, runtime_checkable


@dataclass
class Candidate:
    """Sıralanacak aday: bir tablo, bir seri, bir kalem — ne olduğu retrieval'ı ilgilendirmez."""

    id: str
    text: str                       # eşleşme için kullanılan metin (ad + açıklama + aliases)
    score: float = 0.0
    source: str = ""                # 'bm25' | 'embedding' | 'rrf' | 'reranker'
    meta: dict = field(default_factory=dict)


@runtime_checkable
class Embedder(Protocol):
    """Metin → vektör. Toplu çağrı zorunlu: katalog indeksleme yüzlerce metin demek."""

    model: str
    dimension: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@runtime_checkable
class LexicalIndex(Protocol):
    """BM25/FTS — kesin terimlerde embedding'i yener (ölçüldü, ADR-0015)."""

    def index(self, candidates: Sequence[Candidate]) -> None: ...
    def search(self, query: str, *, k: int = 10) -> list[Candidate]: ...


@runtime_checkable
class Reranker(Protocol):
    """Kısa aday listesini soruya göre yeniden sıralar. Yerel cross-encoder ya da LLM."""

    def rerank(self, query: str, candidates: Sequence[Candidate], *, k: int = 5) -> list[Candidate]: ...


def reciprocal_rank_fusion(
    *rankings: Sequence[Candidate], k: int = 60
) -> list[Candidate]:
    """Birden çok sıralamayı deterministik olarak birleştirir (RRF).

    Model gerektirmez; BM25 + embedding sıralamalarını tek listeye indirir.
    Literatürün "hibrit > saf semantik" bulgusunun en ucuz uygulaması.
    """
    scores: dict[str, float] = {}
    seen: dict[str, Candidate] = {}
    for ranking in rankings:
        for rank, cand in enumerate(ranking, start=1):
            scores[cand.id] = scores.get(cand.id, 0.0) + 1.0 / (k + rank)
            seen.setdefault(cand.id, cand)
    fused = []
    for cid, s in sorted(scores.items(), key=lambda x: -x[1]):
        c = seen[cid]
        fused.append(Candidate(id=c.id, text=c.text, score=s, source="rrf", meta=c.meta))
    return fused
