"""BM25 sözlük dizini: Türkçe katlama, ön ek eşleşmesi, takma ad ağırlığı, deterministik sıra (ADR-0036)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.contracts.retrieval import Candidate, LexicalIndex  # noqa: E402
from kkb_agent.core.lexical import Bm25Index, candidate_text, fold, tokenize  # noqa: E402


def _index(*docs: tuple[str, str]) -> Bm25Index:
    idx = Bm25Index()
    idx.index([Candidate(id=i, text=t) for i, t in docs])
    return idx


def test_protokolu_karsilar_ve_turkce_katlar() -> None:
    assert isinstance(Bm25Index(), LexicalIndex)
    assert fold("İhtiyaç Kredisi ŞUBAT") == "ihtiyac kredisi subat"
    assert "kredi" in tokenize("kredisi") and "kredis" in tokenize("kredisi")   # ön ekler
    assert tokenize("ve ile") == []


def test_ekli_sozcuk_kok_sorguyla_bulunur() -> None:
    idx = _index(("konut", "Tüketici Kredileri - Konut, konut kredisi bakiyesi"),
                 ("tasit", "Tüketici Kredileri - Taşıt, taşıt kredisi bakiyesi"),
                 ("faiz", "Konut Kredisi Faiz Oranı"))
    # 'ihtiyaç' hiçbir belgede yok: isabetler 'kredileri' üzerinden gelir ve eşleşmeyen sözcük yazılır
    hits = idx.search("ihtiyaç kredileri")
    assert hits and all(h.meta["unmatched"] == ["ihtiyac"] for h in hits)
    # yalnız ön ek eşleşmesi ('kredi' → 'kredisi') isabet değildir; geri çağırma modunda sayılır
    assert idx.search("kredi") == [] and [h.id for h in idx.search("kredi", require_full_match=False)]
    top = idx.search("taşıt kredisi")
    assert top[0].id == "tasit" and top[0].meta["matched"] == ["tasit", "kredisi"]
    konut_for_tasit = next(h for h in top if h.id == "konut")
    assert konut_for_tasit.meta["unmatched"] == ["tasit"]  # araç kartı bunu yazar
    assert [h.id for h in idx.search("konut kredileri bakiyesi")][0] == "konut"


def test_takma_ad_agirligi_ve_deterministik_sira() -> None:
    a = candidate_text(name="A", description="uzun açıklama", tags=(), aliases=["mortgage"], dataset_id="x:a")
    b = candidate_text(name="B", description="mortgage geçen açıklama", tags=(), aliases=[], dataset_id="x:b")
    idx = _index(("x:a", a), ("x:b", b))
    hits = idx.search("mortgage")
    assert [h.id for h in hits] == ["x:a", "x:b"] and hits[0].source == "bm25"
    # eşit skor: kimlik sırası
    idx2 = _index(("x:b", "aynı metin"), ("x:a", "aynı metin"))
    assert [h.id for h in idx2.search("aynı metin")] == ["x:a", "x:b"]


def test_eslesme_yoksa_bos() -> None:
    idx = _index(("k", "konut kredisi"))
    assert idx.search("enflasyon") == [] and idx.search("") == []
    assert Bm25Index().search("x") == []
