"""Search ve Retrieval sözleşmelerinin şekli — sağlayıcı olmadan doğrulanır."""

from __future__ import annotations

from kkb_agent.contracts.retrieval import Candidate, Embedder, LexicalIndex, Reranker, reciprocal_rank_fusion
from kkb_agent.contracts.search import PageContent, SearchClient, SearchHit


class _StubSearch:
    def search(self, query, *, max_results=5): return [SearchHit("t", "https://x", "s")]
    def fetch(self, url, *, max_chars=20_000): return PageContent(url=url, title=None, text="x")


class _StubEmbedder:
    model = "stub"; dimension = 2
    def embed(self, texts): return [[0.0, 1.0] for _ in texts]


class _StubLexical:
    def index(self, candidates): self._c = list(candidates)
    def search(self, query, *, k=10): return self._c[:k]


class _StubReranker:
    def rerank(self, query, candidates, *, k=5): return list(candidates)[:k]


def test_stublar_protokolleri_karsilar() -> None:
    """Yapısal tipleme: Protocol'ü miras almadan aynı imza yeterli (veri ekibiyle aynı desen)."""
    assert isinstance(_StubSearch(), SearchClient)
    assert isinstance(_StubEmbedder(), Embedder)
    assert isinstance(_StubLexical(), LexicalIndex)
    assert isinstance(_StubReranker(), Reranker)


def test_rrf_iki_siralamayi_birlestirir() -> None:
    a = [Candidate("konut", "konut"), Candidate("tasit", "taşıt")]
    b = [Candidate("tasit", "taşıt"), Candidate("ihtiyac", "ihtiyaç")]
    fused = reciprocal_rank_fusion(a, b)
    assert fused[0].id == "tasit", "iki listede de görünen aday öne çıkmalı"
    assert {c.id for c in fused} == {"konut", "tasit", "ihtiyac"}
    assert all(c.source == "rrf" for c in fused)
