"""Kullanıcı geri bildirimi (14 Eyl, ADR-0078): kişi sorusunda genel bilgiden uydurma, yetenek ve veri seti soruları, dolgu cümlesi,
TCMB XML'i ve resmi adresler, belge metninin yarıda kesilmesi, alan tanımında Gold, arayüzde sayı listesi ve bekleme bandı."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency, SemanticType  # noqa: E402
from kkb_agent.core.agent import NO_INFO_TEXT  # noqa: E402
from kkb_agent.core.small_talk import capability_reply, data_sets_reply, strip_filler_opening  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.domain import DomainProfile  # noqa: E402
from kkb_agent.llm.base import LLMResponse  # noqa: E402
from kkb_agent.source_hints import load_source_hints  # noqa: E402
from kkb_agent.tools.web import TEXT_WINDOW, WebUrlParams, WebUrlTool  # noqa: E402
from kkb_agent.web.html import extract_page  # noqa: E402
from test_agent_loop import _agent, _ScriptedLLM  # noqa: E402

TCMB_XML = ('<?xml version="1.0" encoding="ISO-8859-9"?>\n<?xml-stylesheet type="text/xsl" href="isokur.xsl"?>\n'
            '<Tarih_Date Tarih="02.01.2015" Date="01/02/2015" Bulten_No="2015/1">'
            '<Currency CrossOrder="0" Kod="USD" CurrencyCode="USD"><Unit>1</Unit><Isim>ABD DOLARI</Isim><ForexBuying>2.3449</ForexBuying>'
            '<ForexSelling>2.3491</ForexSelling></Currency>'
            '<Currency CrossOrder="3" Kod="CHF" CurrencyCode="CHF"><Unit>1</Unit><Isim>İSVİÇRE FRANGI</Isim><ForexBuying>2.3372</ForexBuying>'
            '<ForexSelling>2.3494</ForexSelling></Currency></Tarih_Date>').encode("iso-8859-9")


def _spec(sid: str, source: str, start: date, end: date) -> DatasetSpec:
    return DatasetSpec(dataset_id=sid, name=sid, description="d", source=source, frequency=Frequency.MONTHLY, time_column="observation_date",
                       grain=["observation_date"], coverage=Coverage(start=start, end=end, row_count=1),
                       columns=[ColumnSpec(name="observation_date", role=ColumnRole.TIME, dtype="DATE", description="dönem"),
                                ColumnSpec(name="value", role=ColumnRole.MEASURE, dtype="DOUBLE", description="değer",
                                           semantic_type=SemanticType.STOCK, unit="TL")])


def test_tcmb_kur_xml_tabloya_doner_tarih_notta() -> None:
    page = extract_page(TCMB_XML, "text/xml", "https://www.tcmb.gov.tr/kurlar/201501/02012015.xml")
    assert page.tables, page.text
    t = page.tables[0]
    usd = t[t["Kod"] == "USD"].iloc[0]
    assert float(usd["ForexBuying"]) == 2.3449 and usd["Isim"] == "ABD DOLARI"
    assert "İSVİÇRE FRANGI" in set(t["Isim"]), "ISO-8859-9 Türkçe karakter korunur"
    assert any("Tarih=02.01.2015" in n for n in page.notes) and "Currency" in page.title


def test_resmi_kamu_adresi_kullanici_yazmasa_da_acilir_baskasi_acilmaz() -> None:
    tool = WebUrlTool(AnalysisWorkspace(), registry=SimpleNamespace(user_text="1 temmuz 2026 dolar kurunu araştır", active_question="",
                                                                   sanctioned_locators=set()))
    ok = lambda u: tool.check_policy(WebUrlParams(url=u, purpose="kur")) is None  # noqa: E731
    assert ok("https://www.tcmb.gov.tr/kurlar/202607/01072026.xml") and ok("https://evds3.tcmb.gov.tr/x")
    assert not ok("http://www.tcmb.gov.tr/kurlar/today.xml"), "yalnız https"
    assert not ok("https://tcmb.gov.tr.evil.example/x") and not ok("https://evil.example/tcmb.gov.tr")
    assert "tcmb.gov.tr" in load_source_hints()["official_hosts"]


def test_uzun_belge_metni_pencereyle_ve_devam_notuyla_okunur(tmp_path) -> None:
    body = "".join(f"Satır {i}: proje ve yetkinlik bilgisi.\n" for i in range(600))
    f = tmp_path / "ozgecmis.txt"
    f.write_text(body, encoding="utf-8")
    tool = WebUrlTool(AnalysisWorkspace(), allowed_local_root=tmp_path,
                      registry=SimpleNamespace(user_text=f"Dosya: {f}", active_question=f"Dosya: {f}", sanctioned_locators=set()))
    first = tool.validate_and_run({"url": str(f), "purpose": "özgeçmiş"})
    import re
    total = int(re.search(rf"karakter 0–{TEXT_WINDOW} / (\d+)", first.content).group(1))
    assert first.ok and total > 20000 and f"text_from={TEXT_WINDOW}" in first.content, "20.000 karakterlik eski kırpma yok"
    second = tool.validate_and_run({"url": str(f), "purpose": "özgeçmiş", "text_from": TEXT_WINDOW})
    assert f"karakter {TEXT_WINDOW}–{2 * TEXT_WINDOW} / {total}" in second.content
    last = tool.validate_and_run({"url": str(f), "purpose": "özgeçmiş", "text_from": 2 * TEXT_WINDOW})
    assert f"karakter {2 * TEXT_WINDOW}–{total} / {total}" in last.content and "Satır 599" in last.content
    assert "METİN DEVAM EDİYOR" not in last.content


def test_alan_tanimi_birincil_kaynak_adlariyla_gold_yok() -> None:
    d0, d1 = date(2016, 1, 31), date(2026, 6, 30)
    p = DomainProfile.from_catalog([_spec("a", "bddk_monthly", d0, d1), _spec("b", "evds", d0, d1), _spec("gold.x", "gold", d0, d1)])
    assert p.domain == "BDDK Aylık Bülten ve TCMB EVDS kaynaklı veriler"
    assert DomainProfile.from_catalog([_spec("adhoc:x", "adhoc", d0, d1)]).domain == "adhoc kaynaklı veriler", "yalnız yükleme varsa kimliği"


def test_yetenek_ve_veri_seti_sorulari_deterministik() -> None:
    web = capability_reply("İnternetten araştırma yapabiliyo musun", tools={"web_search", "web_url"}, datasets=lambda: [])
    assert web.startswith("Evet.") and "tcmb.gov.tr" in web
    assert capability_reply("internetten arama yapabilir misin?", tools={"web_url"}, datasets=lambda: []).startswith("Kısmen.")
    d0, d1 = date(2016, 1, 31), date(2026, 6, 30)
    specs = [_spec("a", "bddk_monthly", d0, d1), _spec("b", "bddk_monthly", date(2018, 1, 31), d1), _spec("c", "evds", d0, date(2026, 7, 3)),
             _spec("gold.x", "gold", d0, d1), _spec("adhoc:y", "adhoc", d0, d1)]
    reply = capability_reply("hangi veri setlerine sahipsin", tools=set(), datasets=lambda: specs)
    assert "BDDK Aylık Bülten: 2 seri (2016-01 → 2026-06)" in reply and "TCMB EVDS: 1 seri (2016-01 → 2026-07)" in reply
    assert "gold" not in reply.lower() and "Kullanıcının eklediği 1 seri" in reply
    assert data_sets_reply([], load_source_hints()) == "Veri havuzunda şu an yüklü seri yok."
    for q in ("2025'te hangi veriler arttı?", "Hangi seriler konut kredisini gösteriyor?", "Elif Sena Önsöz kimdir?", "konut kredisini internetten bul"):
        assert capability_reply(q, tools={"web_search", "web_url"}, datasets=lambda: specs) is None, q


def test_dolgu_acilisi_kirpilir() -> None:
    assert strip_filler_opening("Anladım, not aldım. Ama şu an elimde veri sorusu yok.") == ("Şu an elimde veri sorusu yok.", True)
    assert strip_filler_opening("Özür dilerim! 2025 bakiyesi 678.970 milyon TL.") == ("2025 bakiyesi 678.970 milyon TL.", True)
    assert strip_filler_opening("Anladığım kadarıyla veri yok.") == ("Anladığım kadarıyla veri yok.", False)


BIO = ("Elif Sena Önsöz hakkında veri havuzumda bir kayıt yok.\n\nKısaca, genel bilgimden: 1990 doğumlu bir oyuncu.\n\n"
       "Bu bilgiler veri havuzumdan değil, genel bilgimden geliyor.")


def test_genel_bilgiden_cevap_geri_gonderilir_surerse_yayimlanmaz() -> None:
    agent, _ = _agent(_ScriptedLLM([LLMResponse(content=BIO), LLMResponse(content=BIO)]))
    ans = agent.ask("Elif Sena Önsöz kimdir?")
    assert ans.text == NO_INFO_TEXT
    assert any(s.role == "validate" and "genel bilgiden" in (s.thought or "") for s in ans.steps)
    agent2, _ = _agent(_ScriptedLLM([LLMResponse(content=BIO), LLMResponse(content="Bu konuda elimde bilgi yok.")]))
    assert agent2.ask("Elif Sena Önsöz kimdir?").text == "Bu konuda elimde bilgi yok."


def test_ajan_yetenek_sorusunu_modele_gondermez() -> None:
    llm = _ScriptedLLM([LLMResponse(content="Anladım, not aldım. Ama elimde veri sorusu yok.")])
    agent, _ = _agent(llm)
    ans = agent.ask("İnternetten araştırma yapabiliyor musun?")
    assert ans.steps[0].thought == "yetenek sorusu — LLM çağrılmadı" and ans.text.startswith(("Evet.", "Kısmen.", "Hayır."))
    assert "not aldım" not in ans.text


def test_arayuz_sayi_listesi_yok_mesaj_hemen_ve_dusunuyor() -> None:
    html = (Path(__file__).resolve().parents[1] / "src" / "kkb_agent" / "static" / "index.html").read_text(encoding="utf-8")
    assert "Cevaptaki sayılar" not in html
    assert "Düşünüyor…" in html and "pq.remove()" in html


def test_yil_sira_kimligi_sayi_sayilmaz() -> None:
    from kkb_agent.core.grounding import numbers_in

    assert numbers_in("TCMB günlük kurları (bülten no 2026/120)") == []
    assert numbers_in("bülten 2015/1") == []
    assert numbers_in("oran 46,59 TL") == [46.59], "ölçüm sayısı etkilenmez"

