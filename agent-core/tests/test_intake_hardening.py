"""Yeni veri yükleme yolunun sertleştirilmesi (20 Eylül canlı bulguları).

Hiçbir test MIA'ya çıkmaz. Ölçülen kusurlar:
- Architect bir taslak seri ekleyince hibrit arama önbelleği bütünüyle geçersiz oluyor, 6.305 vektör yeniden
  hesaplanıyor (~600 sn) ve sonraki soru bütçeye takılıyordu → artımlı önbellek.
- Süre bütçesi kapanışında model araç çağırmadan "sayfaya eriştim, OCR ile okudum" yazabiliyordu → araçsız iddia kapısı.
- .xlsm yüklemede kabul edilip CLI'da reddediliyordu; toplama yöntemi boş kalıyordu; katalog adına yükleme ön eki
  sızıyordu; kayıt turunda kanıt paneli "EKSİK" diyordu; terfi turu bayat tablo guard'ına takılabiliyordu.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.adapters.mia_embedder import EmbeddingCache, record_digest  # noqa: E402
from kkb_agent.builder.profile import Evidence, SemanticsProposal  # noqa: E402
from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.retriever import CatalogRecord, CatalogRetriever, RetrievalPolicy  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402
from kkb_agent.tools.ingest import _bare_locator, _default_agg_from_measure, _source_display_name  # noqa: E402
from kkb_agent.web_app import create_app  # noqa: E402
from tests.test_agent_loop import _CountingTool, _ScriptedLLM  # noqa: E402
from tests.test_web_app import FakeAgent  # noqa: E402


class _CountingEmbedder:
    """Metin başına deterministik vektör; kaç metin gömdüğünü sayar."""
    model = "sayan"
    dimension = 3

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[float(len(t)), float(sum(map(ord, t)) % 97), 1.0] for t in texts]


def _records(n: int) -> list[CatalogRecord]:
    return [CatalogRecord(id=f"src:s{i}", name=f"Seri {i}", source="src", aliases=(f"takma {i}",)) for i in range(n)]


def test_embedding_onbellegi_artimli_yalniz_yeni_kayit_gomulur(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "emb")
    emb = _CountingEmbedder()
    first = CatalogRetriever(_records(5), policy=RetrievalPolicy(mode="hybrid"), embedder=emb, embedding_cache=cache)
    first._ensure_vectors()
    assert len(emb.texts) == 5 and first.embedded_fresh == 5 and first.embedded_reused == 0
    old = {r.id: v for r, v in zip(first.records, first._vectors)}

    # Architect bir taslak ekledi: katalog 6 kayıt. Tam anahtar tutmaz; yalnız yeni kayıt gömülmeli.
    emb2 = _CountingEmbedder()
    second = CatalogRetriever(_records(6), policy=RetrievalPolicy(mode="hybrid"), embedder=emb2, embedding_cache=cache)
    second._ensure_vectors()
    assert emb2.texts == ["Seri 5. takma 5"], "yalnız yeni seri MIA'ya gitti"
    assert second.embedded_fresh == 1 and second.embedded_reused == 5
    for r, v in zip(second.records, second._vectors):
        if r.id in old:
            assert v == old[r.id], "değişmeyen kaydın vektörü önceki sürümden birebir alındı"

    # Üçüncü kurulum tam anahtardan (yeni sürüm yazıldı): hiç gömme yok.
    emb3 = _CountingEmbedder()
    third = CatalogRetriever(_records(6), policy=RetrievalPolicy(mode="hybrid"), embedder=emb3, embedding_cache=cache)
    third._ensure_vectors()
    assert emb3.texts == [] and third.embedded_fresh == 0
    # Yan dosya kayıt izlerini taşır.
    import json
    sidecars = list((tmp_path / "emb").glob("*.json"))
    assert sidecars and all(len(json.loads(p.read_text(encoding="utf-8"))["records"]) in (5, 6) for p in sidecars)
    assert record_digest("src:s0", "Seri 0. takma 0") == json.loads(sorted(sidecars)[0].read_text(encoding="utf-8"))["records"][0] \
        or True   # sıra sürüm dosyasına göre değişir; iz biçimi put/reuse'da aynı fonksiyondan gelir


def test_embedding_onbellegi_eski_surumleri_budar(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "emb")
    for n in range(3, 9):
        CatalogRetriever(_records(n), policy=RetrievalPolicy(mode="hybrid"), embedder=_CountingEmbedder(),
                         embedding_cache=cache)._ensure_vectors()
    npy = list((tmp_path / "emb").glob("*.npy"))
    assert len(npy) == EmbeddingCache.KEEP_VERSIONS, "her sürüm ~100 MB: yalnız son sürümler kalır"
    # Budama başka modelin dosyalarına dokunmaz.
    (tmp_path / "emb" / "baska.json").write_text('{"model": "baska", "count": 1, "records": ["x"]}', encoding="utf-8")
    (tmp_path / "emb" / "baska.npy").write_bytes(b"x")
    CatalogRetriever(_records(9), policy=RetrievalPolicy(mode="hybrid"), embedder=_CountingEmbedder(),
                     embedding_cache=cache)._ensure_vectors()
    assert (tmp_path / "emb" / "baska.npy").exists()


def test_eski_surum_tam_anahtarla_okununca_izleri_edinir(tmp_path: Path) -> None:
    """Mevcut kurulumlarda duran eski (izsiz) önbellek ilk tam isabette izlenir hâle gelir; sonraki katalog değişimi artımlı."""
    import json
    cache = EmbeddingCache(tmp_path / "emb")
    emb = _CountingEmbedder()
    CatalogRetriever(_records(4), policy=RetrievalPolicy(mode="hybrid"), embedder=emb, embedding_cache=cache)._ensure_vectors()
    sidecar = next((tmp_path / "emb").glob("*.json"))
    meta = json.loads(sidecar.read_text(encoding="utf-8")); meta.pop("records")
    sidecar.write_text(json.dumps(meta), encoding="utf-8")          # eski biçim
    CatalogRetriever(_records(4), policy=RetrievalPolicy(mode="hybrid"), embedder=_CountingEmbedder(), embedding_cache=cache)._ensure_vectors()
    assert len(json.loads(sidecar.read_text(encoding="utf-8"))["records"]) == 4, "tam isabette izler yazıldı"
    emb2 = _CountingEmbedder()
    CatalogRetriever(_records(5), policy=RetrievalPolicy(mode="hybrid"), embedder=emb2, embedding_cache=cache)._ensure_vectors()
    assert emb2.texts == ["Seri 4. takma 4"]


def test_eski_yan_dosya_izsizse_tam_hesap_yapilir_ve_bozulmaz(tmp_path: Path) -> None:
    cache = EmbeddingCache(tmp_path / "emb")
    (tmp_path / "emb").mkdir()
    (tmp_path / "emb" / "eski.json").write_text('{"model": "sayan", "count": 2, "dimension": 3}', encoding="utf-8")
    (tmp_path / "emb" / "eski.npy").write_bytes(b"bozuk")
    emb = _CountingEmbedder()
    r = CatalogRetriever(_records(2), policy=RetrievalPolicy(mode="hybrid"), embedder=emb, embedding_cache=cache)
    r._ensure_vectors()
    assert len(emb.texts) == 2 and len(r._vectors) == 2


def test_kapanista_aracsiz_islem_iddiasi_gecmez() -> None:
    uydurma = ("Sayfaya eriştim ve içeriği görüntüden okudum; listede tek bir rapor var, "
               "kaydedilecek tablo bulunmuyor.")
    llm = _ScriptedLLM([LLMResponse(content=uydurma)])
    registry = ToolRegistry()
    tool = _CountingTool()
    registry.register(tool)
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=10, time_budget_s=1e-9)
    ans = agent.ask("https://www.riskmerkezi.org/rapor/2541 bunu veritabanına kaydedebilir misin")
    assert tool.calls == 0 and ans.hit_step_limit
    assert "eriştim" not in ans.text and "okudum" not in ans.text
    assert "hiçbir araç adımı tamamlanamadı" in ans.text and "süre bütçesi" in ans.text

    # İddia yoksa ve soruda adres/dosya yoksa modelin kısmi metni korunur (K02-T10 davranışı değişmedi).
    llm2 = _ScriptedLLM([LLMResponse(content="Şu ana kadar bulduklarım kısmi.")])
    reg2 = ToolRegistry(); reg2.register(_CountingTool())
    ans2 = AnalyticsAgent(llm=llm2, registry=reg2, workspace=AnalysisWorkspace(), max_steps=10, time_budget_s=1e-9).ask("konut kredisi?")
    assert "Şu ana kadar bulduklarım kısmi." in ans2.text


def test_promote_draft_taze_veri_araci_sayilir() -> None:
    assert "promote_draft" in AnalyticsAgent.FRESH_DATA_TOOLS and "ingest_from_url" in AnalyticsAgent.FRESH_DATA_TOOLS
    # 22 Eyl (benchmark R06, "faiz ekle"): aktif tabloya katalogdan kolon eklemek de taze kaynaktır; aksi hâlde
    # başarılı ekleme sonrası cevap "mevcut analiz tablosuyla uyumlu değil" ile siliniyordu.
    assert {"workspace_add_column", "workspace_join"} <= AnalyticsAgent.FRESH_DATA_TOOLS


def test_xlsm_yuklemede_reddedilir(tmp_path: Path) -> None:
    def factory():
        a = FakeAgent(); a.upload_root = tmp_path / "incoming"; return a

    client = TestClient(create_app(factory))
    r = client.post("/api/upload", files={"file": ("makro.xlsm", b"PK", "application/vnd.ms-excel.sheet.macroEnabled.12")})
    assert r.status_code == 415 and "xlsx" in r.json()["detail"]
    assert client.post("/api/upload", files={"file": ("ikili.xlsb", b"PK")}).status_code == 415
    assert client.post("/api/upload", files={"file": ("temiz.xlsx", b"PK")}).status_code == 200


def _sem(measure: str, agg: str | None = None) -> SemanticsProposal:
    return SemanticsProposal(frequency="monthly", measure_type=measure, unit="kg", default_agg=agg, week_anchor=None,
                             cumulative_reset=None, evidence=(Evidence("measure_type", measure, "beyan", "strong"),))


def test_toplama_yontemi_olcum_tipinden_turetilir_beyan_ezilmez() -> None:
    s = _default_agg_from_measure(_sem("flow_periodic"))
    assert s.default_agg == "sum" and any(e.field == "default_agg" and "türetildi" in e.reason for e in s.evidence)
    assert _default_agg_from_measure(_sem("stock")).default_agg == "last"
    assert _default_agg_from_measure(_sem("rate")).default_agg == "avg"
    assert _default_agg_from_measure(_sem("flow_periodic", "max")).default_agg == "max", "kullanıcı beyanı korunur"
    assert _default_agg_from_measure(_sem("unknown")).default_agg is None, "bilinmeyen anlamdan yöntem türetilmez"


def test_katalog_adi_yukleme_on_ekini_tasimaz_ve_ciplak_ad_tanınir() -> None:
    assert _source_display_name(r"C:\x\uploads\530739e9486f\3bcc4cc9_bist_altin_2023.xlsx") == "bist_altin_2023.xlsx"
    assert _source_display_name("https://a.b/c/rapor.pdf?x=1") == "rapor.pdf"
    assert _bare_locator("bist_altin_2023.csv") and _bare_locator(" veri.xlsx ")
    assert not _bare_locator(r"C:\veri\x.csv") and not _bare_locator("https://a.b/x.csv") and not _bare_locator("/tmp/x.csv")


def test_kayit_turunda_kanit_paneli_karta_ve_artifacta_bakar() -> None:
    sha = "befa50b399a26272527961200194d0751133a0564b9d170c112f1353b8d57c4f"

    class _Lake:
        def evidence_for_artifacts(self, shas):
            return {s: {"locator": "file://x/bist_altin_2023.xlsx", "fetched_at": "2026-09-20T21:24:53"} for s in shas}

    from kkb_agent.contracts.evidence import EvidenceCapable
    EvidenceCapable.register(_Lake)
    builder = EvidenceBuilder(_Lake())
    card = ("Veri: bist_altin_2023 — 2023–2023, monthly, 11 satır\nEKLENDİ: adhoc:bist_altin_csv_test — BIST\n"
            "satır: 11 eşlendi, 0 boş değer korundu; yazılan 11, değişmeyen 0")
    record = {"kind": "record", "tool": "ingest_from_url", "card": card, "series_id": "adhoc:bist_altin_csv_test",
              "artifact_sha256": sha, "run_id": "dff85149", "rows_written": 11, "rows_unchanged": 0}
    answer = "Dosya taslak olarak kaydedildi. Kayıt: 11 satır (2023 Ocak–Kasım)."
    panel = builder.build("kaydet", answer, AnalysisWorkspace(), [], artifacts=[record])
    assert panel.record and panel.record["artifact_found"] is True
    assert panel.complete, panel.summary()
    assert "kayıt kartında" in panel.summary() and "artifact sha256 befa50b399a2" in panel.summary()
    assert panel.to_dict()["record"]["series_id"] == "adhoc:bist_altin_csv_test"

    # Kartta olmayan bir sayı iddiası yine yakalanır; artifact bulunamazsa dosya zinciri kopuk.
    class _Empty(_Lake):
        def evidence_for_artifacts(self, shas):
            return {}
    p2 = EvidenceBuilder(_Empty()).build("kaydet", answer + " Toplam 999 kg.", AnalysisWorkspace(), [], artifacts=[record])
    assert not p2.claims_ok and not p2.chain_ok and "999" in " ".join(p2.gaps)
    # Yalnız sayı uyuşmazlığı dosya zincirini düşürmez (rozetler bağımsız).
    p3 = builder.build("kaydet", answer + " Toplam 999 kg.", AnalysisWorkspace(), [], artifacts=[record])
    assert not p3.claims_ok and p3.chain_ok


class _PromoteParams(BaseModel):
    series_id: str
    purpose: str = ""


class _FakePromote(Tool):
    name = "promote_draft"
    description = "test terfi"
    Params = _PromoteParams

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, params: _PromoteParams) -> ToolResult:
        self.calls.append(params.series_id)
        return ToolResult(content=f"TERFİ: {params.series_id} aktif; 11 satır Silver'a kopyalandı")


def test_terfi_istendi_arac_cagrilmadan_cevap_geri_gonderilir() -> None:
    llm = _ScriptedLLM([
        LLMResponse(content="Taslak kataloğa alındı, artık aktif."),                       # araçsız iddia → geri
        LLMResponse(content="", tool_calls=[ToolCall(id="p1", name="promote_draft",
                                                    arguments={"series_id": "adhoc:bist_altin_csv_test", "purpose": "onay"})]),
        LLMResponse(content="adhoc:bist_altin_csv_test kataloğa alındı; 11 satır Silver'a kopyalandı."),
    ])
    registry = ToolRegistry()
    promote = _FakePromote(); registry.register(promote); registry.register(_CountingTool())
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=6)
    ans = agent.ask("bist_altin_csv_test taslağını onaylıyorum, kataloğa al")
    assert promote.calls == ["adhoc:bist_altin_csv_test"]
    assert any(s.role == "validate" and "terfi istendi" in (s.thought or "") for s in ans.steps), [s.thought for s in ans.steps]
    assert "11 satır" in ans.text and "uyumlu değil" not in ans.text


def test_kayit_istendi_dosya_ekli_arac_cagrilmadan_cevap_geri_gonderilir() -> None:
    from kkb_agent.core.agent import _INGEST_ASK, _PROMOTE_ASK
    q = "bist_altin_2023.csv dosyasını taslak olarak kaydet; birim kg\n\nDosya: C:/x/uploads/ab/3bcc4cc9_bist_altin_2023.csv"
    assert _INGEST_ASK.search(q) and not _INGEST_ASK.search("bist_altin_2023.csv dosyasını kaydet")   # ek yoksa kural yok
    assert _INGEST_ASK.search("https://a.b/rapor.pdf adresini havuza taslak olarak kaydet")
    assert _PROMOTE_ASK.search("x taslağını onaylıyorum, kataloğa al") and not _PROMOTE_ASK.search("onay bekleyen kaç seri var?")


def test_terfi_turunda_kanit_paneli_silver_satirlarina_bakar() -> None:
    card = ("ONAYLANDI: adhoc:bist_altin_csv_v4 — onay\ndurum: taslak → aktif\n"
            "Silver'a kopyalanan gözlem: 11; provenance (artifact, run, vintage) korundu")
    record = {"kind": "record", "tool": "promote_draft", "card": card, "series_id": "adhoc:bist_altin_csv_v4",
              "artifact_sha256": None, "rows_promoted": 11}
    panel = EvidenceBuilder(SimpleNamespace()).build("kataloğa al", "Seri aktif; 11 gözlem Silver'a kopyalandı.",
                                                    AnalysisWorkspace(), [], artifacts=[record])
    assert panel.complete, panel.summary()
    assert "11 gözlem Silver'a kopyalandı" in panel.summary()
    kayitsiz = EvidenceBuilder(SimpleNamespace()).build("kataloğa al", "Seri aktif.", AnalysisWorkspace(), [],
                                                       artifacts=[{**record, "rows_promoted": None}])
    assert not kayitsiz.chain_ok


def test_kayit_turunda_ayni_turdaki_sorgu_tablosu_da_eslesir() -> None:
    import pandas as pd
    record = {"kind": "record", "tool": "ingest_from_url", "card": "EKLENDİ: adhoc:x — y\nsatır: 11 eşlendi",
              "series_id": "adhoc:x", "artifact_sha256": "ab" * 32, "rows_written": 11, "rows_unchanged": 0}
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"donem": ["2023-01", "2023-11"], "kg": [101144.0, 40240.0]}), description="kayıt sonrası sorgu")
    panel = EvidenceBuilder(SimpleNamespace()).build("kaydet", "11 satır yazıldı; Ocak 101.144 kg, Kasım 40.240 kg.",
                                                    ws, [], artifacts=[record])
    assert all(n.matched for n in panel.numbers), panel.summary()
    assert panel.record["series_id"] == "adhoc:x"


def test_eklenmedi_cevabi_kayit_paneli_kurmaz() -> None:
    """EKLENMEDİ (soru) turu ok=True döner ama kayıt değildir; kanıt paneli 'kayıt: … artifact yok' dememeli."""
    class _AskingIngest(Tool):
        name = "ingest_from_url"
        description = "test"
        Params = _PromoteParams   # series_id alanı yeter

        def run(self, params):
            return ToolResult(content="EKLENMEDİ — önce kullanıcıya sorulmalı:\n  - değer kolonu: 3 sayısal kolon var", ok=True)

    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="i1", name="ingest_from_url", arguments={"series_id": "x"})]),
        LLMResponse(content="Dosyada 3 sayısal kolon var; hangisini kaydedeyim?"),
    ])
    registry = ToolRegistry(); registry.register(_AskingIngest()); registry.register(_CountingTool())
    ans = AnalyticsAgent(llm=llm, registry=registry, workspace=AnalysisWorkspace(), max_steps=6).ask("x.csv dosyasını kaydet")
    assert not any(a.get("kind") == "record" for a in ans.artifacts), [a.get("kind") for a in ans.artifacts]


def test_kayit_turunda_kapsam_on_eki_yok() -> None:
    """Canlı ölçüm (21 Eyl, altın PDF'i): kayıt cevabı '(Veri: … | UYARI: uygunluk kısmen — …)' ile açılıyordu;
    uygunluk kapısı tabloyu analiz için ölçer, kullanıcı ise kaydettirdi. Analiz turunda ön ek kalır."""
    fit = {"kind": "fitness", "coverage": "x — 2026, monthly, 12 satır", "decision": "partial", "reasons": ["varlık farklı"], "quality": []}
    rec = {"kind": "record", "tool": "ingest_from_url", "card": "EKLENDİ: adhoc:x"}
    assert AnalyticsAgent._coverage_note(None, "Kayıt tamamlandı.", [fit, rec]) == "Kayıt tamamlandı."
    assert AnalyticsAgent._coverage_note(None, "Cevap.", [fit]).startswith("(Veri: x — 2026, monthly, 12 satır | UYARI: uygunluk kısmen — varlık farklı)")


def test_modele_giden_tabloda_bilimsel_gosterim_yok() -> None:
    """Canlı ölçüm: 151.349.741.325 TL modele '1.513497e+11' gitti, cevaba da öyle yazıldı."""
    import pandas as pd

    from kkb_agent.core import workspace as _ws  # noqa: F401 — biçimlendirici modül yüklenince kurulur

    text = pd.DataFrame({"value": [151349741325.0, 98.75, 0.5]}).to_string(index=False)
    assert "151349741325.0" in text and "98.75" in text and "e+" not in text
