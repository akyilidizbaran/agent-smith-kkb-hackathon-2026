"""Tamamlanma sözleşmesi ve arama defteri (22 Eyl): P02/P04 (kapsam, türetim), P05/R02/R04 (arama verimi, aday listesi).

Soruya özel kural yok: beklenti tarih dilbilgisinden, türetim sözcüklerinden ve katalog kimliği biçiminden türetilir;
arama defteri yeni aday üretimine ve istenen yüzlere bakar. LLM sahte (senaryo), araçlar sahte, ağ yok.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.core.agent import AnalyticsAgent  # noqa: E402
from kkb_agent.core.completion import check_completion, derive_expectation  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.search_ledger import SearchLedger  # noqa: E402
from kkb_agent.core.tool import Tool, ToolResult  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.llm.base import LLMResponse, ToolCall  # noqa: E402
from kkb_agent.tools.lakehouse import LakehouseSearchTool  # noqa: E402
from tests.test_agent_loop import _ScriptedLLM  # noqa: E402


# ================================================================ beklenti: tarih dilbilgisi

@pytest.mark.parametrize("question, start, end, freq, n", [
    ("KOBİ kredileri aylık stok serisini 2023-01–2024-12 döneminde göster", date(2023, 1, 1), date(2024, 12, 31), "monthly", 24),      # P02
    ("202301-202412 arası aylık", date(2023, 1, 1), date(2024, 12, 31), "monthly", 24),
    ("toplam mevduat ve toplam kredi stoklarını 2021Q3–2025Q2 çeyrek sonlarında karşılaştır", date(2021, 7, 1), date(2025, 6, 30), "quarterly", 16),  # P04
    ("2021 3. çeyrek ile 2025 2. çeyrek arası çeyreklik", date(2021, 7, 1), date(2025, 6, 30), "quarterly", 16),
    ("Ocak 2023 - Aralık 2024 aylık bakiye", date(2023, 1, 1), date(2024, 12, 31), "monthly", 24),
    ("2024 takvim yılında ay sonu bakiye değerlerini getir", date(2024, 1, 1), date(2024, 12, 31), "monthly", 12),                       # P01
    ("2021-2025 arasındaki aylık konut kredisi faiz oranı", date(2021, 1, 1), date(2025, 12, 31), "monthly", 60),
    ("2022–2024 arasındaki çeyreklik gözlemlerin yıllık ortalaması il ve yıl bazında", date(2022, 1, 1), date(2024, 12, 31), None, None),  # R04: iki frekans → sayı zorlanmaz
])
def test_beklenti_donem_penceresi_ve_frekans(question, start, end, freq, n) -> None:
    e = derive_expectation(question)
    assert (e.start, e.end, e.frequency) == (start, end, freq), e
    assert (len(e.expected_periods) if e.expected_periods is not None else None) == n


def test_beklenti_turetim_kimlik_ve_liste() -> None:
    e = derive_expectation("Her ay için önceki aya göre mutlak farkı da aynı tabloda hesapla")
    assert e.derivations == ("diff",)
    assert derive_expectation("aylık yüzde değişimini ver").derivations == ("pct",)
    e = derive_expectation("BDDK 1357_Toplam toplam mevduat ve 1160_Toplam toplam kredi; EVDS TP.KTF12 faizi")
    assert e.series_ids == ("1357_Toplam", "1160_Toplam", "TP.KTF12")
    assert derive_expectation("Katalogda 'toplam kredi' ile eşleşen aktif serileri listele").listing
    assert not derive_expectation("konut kredisi bakiyesi nedir").enforceable
    assert derive_expectation("2023 yılında 1 haftalık repo faizi").frequency is None    # sayıyla gelen 'haftalık' vade, frekans değil


# ================================================================ denetim: kapsam, türetim, kimlik

def _months(n: int, start=(2023, 1)) -> list[date]:
    out, y, m = [], *start
    for _ in range(n):
        out.append(date(y, m, 28)); y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def test_p02_tam_kapsam_ve_fark_kolonu_gecer_eksik_ay_ve_yanlis_fark_yakalanir() -> None:
    e = derive_expectation("KOBİ kredileri aylık stok serisini 2023-01–2024-12 döneminde göster; önceki aya göre mutlak farkı da hesapla")
    vals = [100.0 + i * 3 for i in range(24)]
    full = pd.DataFrame({"observation_date": _months(24), "bakiye": vals})
    full["fark"] = full["bakiye"].diff()
    r = check_completion(e, full)
    assert r.ok and r.expected_periods == 24 and r.found_periods == 24, r.gaps
    assert {"dönem kapsamı", "türetim:diff"} <= set(r.checked)

    missing = full.drop(index=[4]).reset_index(drop=True)                     # 2023-05 yok
    r = check_completion(e, missing)
    assert r.expected_periods == 24 and r.found_periods == 23 and r.missing_periods == ["2023-05"]
    assert any("24 dönemin 1 tanesi tabloda yok (2023-05)" in g for g in r.gaps), r.gaps

    wrong = full.copy(); wrong["fark"] = wrong["bakiye"] * 0.5              # fark değil
    r = check_completion(e, wrong)
    assert any("fark kolonu" in g for g in r.gaps), r.gaps

    raw_only = full[["observation_date", "bakiye"]]
    assert any("fark kolonu" in g for g in check_completion(e, raw_only).gaps)


def test_p04_ceyrek_kapsami_ve_seri_kimlikleri() -> None:
    e = derive_expectation("BDDK 1357_Toplam toplam mevduat ve 1160_Toplam toplam kredi stoklarını 2021Q3–2025Q2 çeyrek sonlarında karşılaştır")
    quarters = [date(2021, 9, 30), date(2021, 12, 31)] + [date(y, m, 28) for y in (2022, 2023, 2024) for m in (3, 6, 9, 12)] + [date(2025, 3, 31), date(2025, 6, 30)]
    table = pd.DataFrame({"period_end": quarters, "mevduat": range(16), "kredi": range(16)})
    r = check_completion(e, table, provenance_ids={"bddk_monthly:1357_Toplam", "bddk_monthly:1160_Toplam"})
    assert r.ok and r.expected_periods == 16, r.gaps
    r = check_completion(e, table, provenance_ids={"bddk_monthly:1357_Toplam"}, sql_texts=["select ... where series_id='bddk_monthly:1357_Toplam'"])
    assert r.gaps == ["istenen seri 1160_Toplam tabloya girmedi"]
    r = check_completion(e, table.iloc[:12], provenance_ids={"bddk_monthly:1357_Toplam", "bddk_monthly:1160_Toplam"})
    assert r.found_periods == 12 and r.missing_periods[0] == "2024-09"


def test_yuzde_degisim_oran_ya_da_yuzde_olcegiyle_kabul_edilir_ve_tablosuz_istek_bosluktur() -> None:
    e = derive_expectation("2024 takvim yılında aylık yüzde değişimini ver")
    t = pd.DataFrame({"tarih": _months(12, (2024, 1)), "v": [100.0, 110.0, 99.0, 120.0, 130.0, 125.0, 140.0, 150.0, 149.0, 160.0, 170.0, 165.0]})
    t["pct"] = t["v"].pct_change() * 100
    assert check_completion(e, t).ok
    t["pct"] = t["v"].pct_change()
    assert check_completion(e, t).ok
    assert check_completion(e, None).gaps == ["istenen veri için tablo yok"]
    assert check_completion(derive_expectation("selam"), None).ok       # beklenti yoksa sessiz


# ================================================================ ajan döngüsü: geri gönderme, sonra not

class _Q(BaseModel):
    months: int = 23


class _MonthsTool(Tool):
    """Sorgu aracı sahtesi: istenen kadar ay getirir (ilk çağrı eksik, ikincisi tam)."""

    name = "lakehouse_query"
    description = "test"
    Params = _Q

    def __init__(self, ws) -> None:
        self.ws = ws
        self.calls: list[int] = []

    def run(self, params: _Q) -> ToolResult:
        self.calls.append(params.months)
        frame = pd.DataFrame({"observation_date": _months(params.months), "bakiye": [100.0 + i for i in range(params.months)]})
        self.ws.set_table(frame, description="bakiye")
        return ToolResult(content=f"Sorgu başarılı: {params.months} satır", data=frame)


def _agent(turns, ws):
    llm = _ScriptedLLM(turns)
    registry = ToolRegistry(); tool = _MonthsTool(ws); registry.register(tool)
    return AnalyticsAgent(llm=llm, registry=registry, workspace=ws, max_steps=8), tool, llm


def test_eksik_donem_bir_kez_geri_gonderilir_tamamlanirsa_not_yok() -> None:
    ws = AnalysisWorkspace()
    agent, tool, llm = _agent([
        LLMResponse(content="", tool_calls=[ToolCall(id="a", name="lakehouse_query", arguments={"months": 23})]),
        LLMResponse(content="2023-01–2024-12 arası bakiye tabloda."),                                     # 23 ay → geri
        LLMResponse(content="", tool_calls=[ToolCall(id="b", name="lakehouse_query", arguments={"months": 24})]),
        LLMResponse(content="2023-01–2024-12 arası 24 aylık bakiye tabloda."),
    ], ws)
    ans = agent.ask("KOBİ kredileri aylık stok serisini 2023-01–2024-12 döneminde göster")
    assert tool.calls == [23, 24]
    nudges = [s for s in ans.steps if s.role == "validate" and (s.thought or "").startswith("tamamlanma")]
    assert len(nudges) == 1 and "2024-12" in nudges[0].thought, [s.thought for s in ans.steps]
    assert "Kapsam kontrolü" not in ans.text
    assert ans.completion["expected_periods"] == 24 and ans.completion["found_periods"] == 24 and ans.completion["gaps"] == []


def test_ikinci_kez_de_eksikse_cevap_deterministik_notla_kapanir() -> None:
    ws = AnalysisWorkspace()
    agent, tool, llm = _agent([
        LLMResponse(content="", tool_calls=[ToolCall(id="a", name="lakehouse_query", arguments={"months": 23})]),
        LLMResponse(content="Bakiye tabloda, 23 ay."),
        LLMResponse(content="Bakiye tabloda, 23 ay; Aralık 2024 kaynakta yok."),
    ], ws)
    ans = agent.ask("KOBİ kredileri aylık stok serisini 2023-01–2024-12 döneminde göster")
    assert tool.calls == [23]
    assert "(Kapsam kontrolü: istenen 24 dönemin 1 tanesi tabloda yok (2024-12).)" in ans.text, ans.text
    assert ans.completion["missing_periods"] == ["2024-12"]


def test_durust_ret_geri_gonderilmez_ve_not_eklenmez() -> None:
    """Q01/Q02/P05 türü: veri yok deniyor; sözleşme boş bir tekrar turu ve tekrar notu üretmez."""
    ws = AnalysisWorkspace()
    agent, tool, llm = _agent([LLMResponse(content="Temmuz 2026 ve Ağustos 2026 için bu seride veri yok; son gözlem Haziran 2026.")], ws)
    ans = agent.ask("2026-07–2026-08 için aylık toplam kredi bakiyesini getir")
    assert tool.calls == [] and "Kapsam kontrolü" not in ans.text
    assert not any((s.thought or "").startswith("tamamlanma") for s in ans.steps)


# ================================================================ arama defteri

def _spec(sid, name, freq="monthly", source="bddk_monthly"):
    return SimpleNamespace(dataset_id=sid, name=name, frequency=SimpleNamespace(value=freq), source=source, description="", columns=[],
                           coverage=SimpleNamespace(start="2021-01-31", end="2026-06-30"), measure_type="stock", unit="TRY_mn", tags=[])


def test_defter_yeni_aday_uretmeyen_aramalarda_doyar_cagri_sayisiyla_degil() -> None:
    ledger = SearchLedger(); ledger.begin_turn("haftalık takipteki alacak oranı")
    a = ledger.record("takipteki alacak oranı", [_spec("bddk_monthly:1", "Takipteki alacaklar oranı"), _spec("bddk_monthly:2", "Takipteki alacak tutarı")])
    assert a.new_ids == ["bddk_monthly:1", "bddk_monthly:2"] and not a.saturated
    b = ledger.record("takipteki alacak oranı yüzde", [_spec("bddk_monthly:1", "x")])
    assert b.new_ids == [] and not b.saturated                       # henüz üç arama yok
    c = ledger.record("takipteki alacak rasyo", [_spec("bddk_monthly:2", "y")])
    assert c.saturated and c.total_unique == 2
    assert "istenen frekansta (weekly) aday yok" in c.facet_note and "monthly ×2" in c.facet_note
    d = SearchLedger(); d.begin_turn("konut kredisi")
    for i in range(5):                                                # her arama yeni aday: doymaz
        assert not d.record(f"q{i}", [_spec(f"s{i}", "x")]).saturated


class _Lake:
    def __init__(self, specs): self.specs = specs; self.calls = []
    def search_datasets(self, query, limit=5):
        self.calls.append((query, limit)); return self.specs[:limit]
    def get_dataset(self, dataset_id): raise KeyError(dataset_id)


def test_arama_araci_limit_alir_adaylari_tasir_ve_doyunca_tam_listeyi_verir() -> None:
    specs = [_spec(f"bddk_monthly:{i}_Toplam", f"Toplam kredi {i}") for i in range(12)]
    tool = LakehouseSearchTool(_Lake(specs))
    tool.begin_turn(1); tool.ledger.begin_turn("toplam kredi ile eşleşen serileri listele")
    r = tool.run(tool.Params(query="toplam kredi", limit=40))
    assert r.ok and len(r.artifacts["candidates"]) == 12 and "toplam 12 tekil aday" in r.content
    assert tool.lakehouse.calls == [("toplam kredi", 40)]
    tool.run(tool.Params(query="toplam krediler")); r3 = tool.run(tool.Params(query="kredi toplamı"))
    assert r3.ok and "SEARCH_SATURATED" in r3.content and "Tüm adaylar:" in r3.content and r3.artifacts["search_ledger"]["saturated"]


def test_liste_isteginde_ajan_limiti_yukseltir_ve_aday_tablosu_indirilebilir_olur() -> None:
    specs = [_spec(f"bddk_monthly:{i}_Toplam", f"Toplam kredi {i}") for i in range(9)]
    ws = AnalysisWorkspace()
    registry = ToolRegistry(); tool = LakehouseSearchTool(_Lake(specs)); registry.register(tool)
    llm = _ScriptedLLM([
        LLMResponse(content="", tool_calls=[ToolCall(id="s", name="lakehouse_search", arguments={"query": "toplam kredi"})]),
        LLMResponse(content="Toplam kredi ile eşleşen 5 seri var; ulusal seri bddk_monthly:0_Toplam uygundur."),
    ])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=ws, max_steps=6)
    ans = agent.ask("Katalogda 'toplam kredi' ile eşleşen aktif serileri listele; kaynak, frekans ve birimi göster")
    assert tool.lakehouse.calls == [("toplam kredi", 40)], tool.lakehouse.calls          # liste isteği: tam küme
    assert ws.has_table and len(ws.table) == 9 and list(ws.table.columns)[:3] == ["series_id", "name", "source"]
    assert "(Aday listesi: 9 seri; tam liste tabloda, indirilebilir.)" in ans.text
    assert any(a.get("kind") == "candidates" and a["count"] == 9 for a in ans.artifacts)
    assert ans.completion["gaps"] == []


def test_doymus_aramada_israr_araclari_geri_alir_ve_aday_sayisiyla_kapanir() -> None:
    specs = [_spec("bddk_monthly:1", "Takipteki alacaklar oranı"), _spec("bddk_monthly:2", "Takipteki alacak tutarı")]
    ws = AnalysisWorkspace()
    registry = ToolRegistry(); tool = LakehouseSearchTool(_Lake(specs)); registry.register(tool)
    calls = [LLMResponse(content="", tool_calls=[ToolCall(id=f"s{i}", name="lakehouse_search", arguments={"query": f"takipteki alacak {i}"})]) for i in range(5)]
    llm = _ScriptedLLM(calls + [LLMResponse(content="Haftalık doğrulanmış oran serisi yok; 2 aday aylık: bddk_monthly:1, bddk_monthly:2.")])
    agent = AnalyticsAgent(llm=llm, registry=registry, workspace=ws, max_steps=10)
    ans = agent.ask("Haftalık bültende 2024-01–2024-06 için takipteki alacak oranı serisini ara; haftalık oran yoksa adayları bildir")
    executed = [q for q, _ in tool.lakehouse.calls]
    assert len(executed) == 3, executed                       # 3. aramada doydu; sonrakiler çalıştırılmadı
    assert any(s.error_code == "SEARCH_SATURATED" or "SEARCH_SATURATED" in (s.result_summary or "") for s in ans.steps)
    assert "2 aday" in ans.text or "bddk_monthly:1" in ans.text
    assert "Kapsam kontrolü" not in ans.text                  # dürüst kapanış; boş tekrar notu yok


# ================================================================ ikinci canlı turdan gelen düzeltmeler (22 Eyl)

def test_ceyrek_ve_ay_adi_yaziminda_ayrac_bosluk_olabilir() -> None:
    e = derive_expectation("2021 3. çeyrekten 2025 2. çeyreğe kadar çeyrek sonlarında toplam mevduat ile toplam kredi")
    assert (e.start, e.end, e.frequency, len(e.expected_periods)) == (date(2021, 7, 1), date(2025, 6, 30), "quarterly", 16)
    e = derive_expectation("Temmuz 2026 ve Ağustos 2026 için aylık toplam kredi bakiyesi")
    assert (e.start, e.end, len(e.expected_periods)) == (date(2026, 7, 1), date(2026, 8, 31), 2)
    assert derive_expectation("2021 2025 arası").start is None            # yıl çifti ayraçsız kabul edilmez


def test_konu_belirten_liste_sorusu_envanter_cevabina_kacmaz() -> None:
    from kkb_agent.core.small_talk import capability_reply
    # Konu sözcükleri kodda değil katalogda: "konut"/"kredi" bir seri adında geçtiği için soru konu belirtir.
    specs = lambda: [SimpleNamespace(name="Tüketici Kredileri - Konut, Toplam (Sektör)", source="bddk_monthly", columns=[],
                                     coverage=SimpleNamespace(start="2021-01-31", end="2026-06-30"))]
    assert capability_reply("Havuzda konut kredisiyle ilgili hangi seriler var, hepsini listele.", tools=set(), datasets=specs) is None
    assert capability_reply("Elinde hangi veriler var?", tools=set(), datasets=specs) is not None
    assert capability_reply("Elinde ne tür veriler var", tools=set(), datasets=specs) is not None


def test_yokluk_ifadeleri_ret_fiillerini_de_kapsar() -> None:
    from kkb_agent.core.completion import CompletionReport
    agent = AnalyticsAgent(llm=_ScriptedLLM([LLMResponse(content="x")]), registry=ToolRegistry(), workspace=AnalysisWorkspace())
    rep = CompletionReport(expectation=derive_expectation("2021Q3–2025Q2 çeyrek"), gaps=["istenen veri için tablo yok"])
    assert agent._absence_stated("İki seriyi çeyrek sonlarında yan yana koyamıyorum: dönüşüm reddedildi.", rep)
    assert not agent._absence_stated("İşte tablo.", rep)


def test_yariyil_ve_sifatli_liste_istegi_ve_donem_sonu_tarih_kolonu() -> None:
    e = derive_expectation("Haftalık bültende 2024 ilk yarısı için tüketici kredisi takip oranı var mı; yoksa hangi haftalık seriler var söyle.")
    assert (e.start, e.end, e.frequency, e.listing) == (date(2024, 1, 1), date(2024, 6, 30), "weekly", True)
    assert derive_expectation("2023 ikinci yarısında aylık").start == date(2023, 7, 1)
    from kkb_agent.core.claim_check import _date_column
    gold_like = pd.DataFrame({"period_start": [date(2025, 1, 1), date(2025, 4, 1)], "period_end": [date(2025, 3, 31), date(2025, 6, 30)], "v": [1.0, 2.0]})
    assert _date_column(gold_like) == "period_end"          # Gold satırının etiketi dönem sonudur (P04 yanlış çelişki notu)
    assert _date_column(pd.DataFrame({"observation_date": [date(2025, 1, 31)], "v": [1.0]})) == "observation_date"


def test_kayit_turunda_sozlesme_sessizdir() -> None:
    """Ölçüldü (22 Eyl): 'tablo 2026 yılına ait' beyanı dönem beklentisi üretti, kayıt turuna sahte 'tablo yok' notu düştü."""
    class P(BaseModel):
        locator: str = ""
        name: str = ""

    class FakeIngest(Tool):
        name = "ingest_from_url"; description = "t"; Params = P

        def run(self, params):
            out = SimpleNamespace(artifact_sha256="ab", run_id="r", rows_written=12, rows_unchanged=0)
            return ToolResult(content="EKLENDİ: adhoc:altin_tl — Altın\nsatır: 12 eşlendi", artifacts={"ingest": out})

    reg = ToolRegistry(); reg.register(FakeIngest())
    llm = _ScriptedLLM([LLMResponse(content="", tool_calls=[ToolCall(id="1", name="ingest_from_url", arguments={"locator": "kmp_au.pdf", "name": "Altın"})]),
                        LLMResponse(content="Kayıt tamamlandı: 12 satır yazıldı.")])
    ans = AnalyticsAgent(llm=llm, registry=reg, workspace=AnalysisWorkspace(), max_steps=6).ask(
        "kmp_au.pdf dosyasındaki TL Hacim kolonunu aylık taslak olarak kaydet; tablo 2026 yılına ait, dönem 2026")
    assert "Kapsam kontrolü" not in ans.text and ans.completion == {}
    assert not any((s.thought or "").startswith("tamamlanma") for s in ans.steps)
