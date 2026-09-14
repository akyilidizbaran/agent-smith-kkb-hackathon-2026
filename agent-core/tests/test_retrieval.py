"""Kademeli retrieval (ADR-0043): yüzler, politika, retriever, önbellek, ön-yükleme kademesi, araç kapısı."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.adapters.mia_embedder import EmbeddingCache  # noqa: E402
from kkb_agent.contracts.retrieval import Candidate  # noqa: E402
from kkb_agent.core import tool_gate  # noqa: E402
from kkb_agent.core.facets import extract_facets, province_of  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.retriever import CatalogRecord, CatalogRetriever, RetrievalPolicy, apply_facets  # noqa: E402


def _rec(id, name, freq="monthly", source="bddk_monthly", aliases=(), province=None):
    return CatalogRecord(id=id, name=name, frequency=freq, source=source, aliases=tuple(aliases), province=province)


CATALOG = [
    _rec("bddk_monthly:1534_Toplam", "Tüketici Kredileri - Konut, Toplam (Sektör)", aliases=("konut kredisi", "konut kredisi bakiyesi")),
    _rec("bddk_monthly:1535_Toplam", "Tüketici Kredileri - Taşıt, Toplam (Sektör)", aliases=("taşıt kredisi",)),
    _rec("bddk_weekly:5690_3", "Konut Kredileri, Toplam (Sektör) - Haftalık", freq="weekly", source="bddk_weekly", aliases=("haftalık konut kredisi",)),
    _rec("gold.konut_kredisi_ceyreklik", "Konut kredisi bakiyesi, çeyreklik", freq="quarterly", source="gold", aliases=("çeyreklik konut kredisi",)),
    _rec("bddk_finturk:IZMIR_KonutKredisi", "Konut Kredisi, İZMİR (Bireysel Bankacılık, Sektör)", freq="quarterly", source="bddk_finturk", aliases=("izmir konut kredisi",), province="İzmir"),
    _rec("bddk_finturk:ANKARA_KonutKredisi", "Konut Kredisi, ANKARA (Bireysel Bankacılık, Sektör)", freq="quarterly", source="bddk_finturk", aliases=("ankara konut kredisi",), province="Ankara"),
    _rec("bddk_finturk:IZMIR_TasitKredisi", "Taşıt Kredisi, İZMİR (Bireysel Bankacılık, Sektör)", freq="quarterly", source="bddk_finturk", aliases=("izmir taşıt kredisi",), province="İzmir"),
    _rec("evds:TP.DK.USD.A.YTL", "ABD Doları Döviz Alış Kuru (TL)", freq="daily", source="evds", aliases=("dolar kuru", "usd/try")),
]


def test_yuzler_il_frekans_kaynak_ve_ekler() -> None:
    f = extract_facets("İzmir'deki aylık taşıt kredisi bakiyesi TCMB")
    assert f.provinces == ("İzmir",) and f.frequency == "monthly" and f.sources == ("evds",)
    assert extract_facets("haftalık faizi aylık göster").frequency is None       # iki frekans: karar yok
    assert extract_facets("Ankara ve İstanbul karşılaştır").provinces == ("Ankara", "İstanbul")
    assert province_of("bddk_finturk:VAN_KonutKredisi Konut Kredisi, VAN") == "Van"
    assert province_of("Tüketici Kredileri - Taşıt, Toplam (Sektör)") is None


def test_il_sorulmadiysa_ulusal_seri_one_il_sorulduysa_yalniz_o_il() -> None:
    r = CatalogRetriever(CATALOG, policy=RetrievalPolicy(mode="bm25"))
    national = [h.id for h in r.search("konut kredisi bakiyesi", k=4)]
    assert national[0] == "bddk_monthly:1534_Toplam" and not national[0].startswith("bddk_finturk")
    izmir = [h.id for h in r.search("İzmir'de konut kredisi", k=4)]
    assert izmir[0] == "bddk_finturk:IZMIR_KonutKredisi" and "bddk_finturk:ANKARA_KonutKredisi" not in izmir
    # yüzsüz arama (ölçülen açık): "izmir" tek sözcük, "konut kredisi" takma adlarda 3× — ulusal
    # seriler İzmir'inkinin önüne geçer; yüz filtresi il sözcüğünü puan değil eleme yapar.
    plain = [h.id for h in r.search("İzmir'de konut kredisi", k=4, use_facets=False)]
    assert plain[0] != "bddk_finturk:IZMIR_KonutKredisi"


def test_frekans_yuzu_ayni_frekansi_one_ince_olani_ortaya_kabayi_sona_koyar() -> None:
    r = CatalogRetriever(CATALOG, policy=RetrievalPolicy(mode="bm25"))
    hits = [h.id for h in r.search("aylık konut kredisi", k=4)]
    assert hits[0] == "bddk_monthly:1534_Toplam"
    assert hits.index("bddk_weekly:5690_3") < hits.index("gold.konut_kredisi_ceyreklik")   # haftalık (ince) çeyreklikten (kaba) önce


def test_politika_kademeleri() -> None:
    p = RetrievalPolicy()
    assert p.resolve(40, embedder_available=False) == "preload_all"
    assert p.resolve(2214, embedder_available=True) == "bm25"
    assert p.resolve(6000, embedder_available=True) == "hybrid"
    assert p.resolve(6000, embedder_available=False) == "bm25"
    assert RetrievalPolicy(mode="hybrid").resolve(10, embedder_available=False) == "bm25"
    assert RetrievalPolicy(mode="preload_all").resolve(10000, embedder_available=True) == "preload_all"


class _FakeEmbedder:
    """Deterministik vektör: belge metnindeki sözcüklerin kaba çantası; 'dolar' ile 'usd' aynı yönde."""
    model = "fake"
    dimension = 4
    SYN = {"dolar": 0, "usd": 0, "kur": 0, "konut": 1, "kredi": 2, "tasit": 3}

    def embed(self, texts):
        from kkb_agent.core.lexical import tokenize
        out = []
        for t in texts:
            v = [0.0] * 4
            for tok in tokenize(t, prefixes=False):
                if tok in self.SYN:
                    v[self.SYN[tok]] += 1.0
            out.append(v if any(v) else [1e-6] * 4)
        return out


def test_hybrid_sozluk_eslesmesi_olmayan_es_anlamliyi_bulur(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "emb")
    r = CatalogRetriever(CATALOG, policy=RetrievalPolicy(mode="hybrid"), embedder=_FakeEmbedder(), embedding_cache=cache)
    assert r.mode == "hybrid"
    hits = [h.id for h in r.search("kur", k=3)]           # "kur" sözcüğü takma adlarda yok, yoğun vektörde var
    assert hits[0] == "evds:TP.DK.USD.A.YTL"
    assert any(p.suffix == ".npy" for p in (tmp_path / "emb").iterdir())   # önbelleğe yazıldı
    r2 = CatalogRetriever(CATALOG, policy=RetrievalPolicy(mode="hybrid"), embedder=_FakeEmbedder(), embedding_cache=cache)
    r2._ensure_vectors()
    assert r2._vectors is not None and len(r2._vectors) == len(CATALOG)       # ikinci kez diskten


def test_on_yukleme_kucuk_katalogda_hepsini_kart_yapar() -> None:
    from kkb_agent.core.context import build_question_context
    from datetime import date
    from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency

    def spec(i):
        return DatasetSpec(dataset_id=f"s{i}", name=f"Seri {i}", description="d", source="x", frequency=Frequency.MONTHLY,
                           time_column="d", grain=["d"], columns=[ColumnSpec(name="d", role=ColumnRole.TIME, dtype="DATE", description="d"),
                                                                    ColumnSpec(name="v", role=ColumnRole.MEASURE, dtype="DOUBLE", description="v")],
                           coverage=Coverage(start=date(2021, 1, 1), end=date(2026, 6, 30)))
    specs = [spec(i) for i in range(20)]
    lake = SimpleNamespace(list_datasets=lambda: specs, search_datasets=lambda q, limit=8: specs[:limit],
                           describe_dataset=lambda i: next(s for s in specs if s.dataset_id == i))
    ctx = build_question_context(lake, "seri 17", k=8, retrieval_mode="auto", small_max=60)
    assert len(ctx.preloaded_ids) == 20 and ctx.indexed == 0
    ctx2 = build_question_context(lake, "seri 17", k=8, retrieval_mode="bm25", small_max=60)
    assert len(ctx2.preloaded_ids) == 8 and ctx2.indexed == 12


def test_arac_kapisi_sinyalle_acar_yetkiyi_daraltmaz() -> None:
    registered = tool_gate.ALWAYS | tool_gate.CHART | tool_gate.ANALYTICS | tool_gate.WEB | tool_gate.ARCHITECT
    d = tool_gate.decide("2025 konut kredisi bakiyesini aylık göster", registered)
    assert d.allowed == tool_gate.ALWAYS and set(d.closed) == {"grafik", "analitik", "web", "architect"}
    d = tool_gate.decide("bunun grafiğini çiz", registered)
    assert "chart" in d.allowed and "anomaly_detect" not in d.allowed
    d = tool_gate.decide("aykırı aylar hangileri?", registered)
    assert tool_gate.ANALYTICS <= d.allowed
    d = tool_gate.decide("şu sayfadan TÜFE'yi söyle: https://x/y.html", registered)
    assert "web_url" in d.allowed and "ingest_from_url" not in d.allowed
    d = tool_gate.decide("şu dosyayı taslak seri olarak ekle: /tmp/a.csv", registered)
    assert tool_gate.ARCHITECT <= d.allowed and "web_url" in d.allowed
    off = tool_gate.decide("x", registered, enabled=False)
    assert off.allowed == registered and off.closed == ()


def test_kayit_defteri_alt_kume_semasi_verir() -> None:
    from tests.test_agent_loop import _CountingTool, _FakeChart
    reg = ToolRegistry(); reg.register(_CountingTool()); reg.register(_FakeChart())
    assert len(reg.schemas()) == 2 and len(reg.schemas(only={"lakehouse_query"})) == 1
    assert "chart" not in reg.describe(only={"lakehouse_query"})


def test_sayili_vade_frekans_yuzu_degildir_ve_embedding_dusunce_bm25_kalir() -> None:
    assert extract_facets("mevduat faizi 3 aylık").frequency is None
    assert extract_facets("1 haftalık repo faizi").frequency is None
    assert extract_facets("aylık mevduat faizi").frequency == "monthly"

    class Broken:
        model = "broken"; dimension = 4
        def embed(self, texts): raise RuntimeError("uç kapalı")
    r = CatalogRetriever(CATALOG, policy=RetrievalPolicy(mode="hybrid"), embedder=Broken())
    hits = [h.id for h in r.search("konut kredisi bakiyesi", k=3)]
    assert hits[0] == "bddk_monthly:1534_Toplam" and r.last_error and "uç kapalı" in r.last_error
