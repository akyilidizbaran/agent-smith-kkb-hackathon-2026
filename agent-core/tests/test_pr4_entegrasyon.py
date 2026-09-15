"""PR #4 (Büşra, kullanıcı hatası kapıları) entegrasyonunda bulunan eksikler ve kimlik deneyi bulguları (15 Eyl, ADR-0080)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency, SemanticType  # noqa: E402
from kkb_agent.core.fitness import Lexicon, assess, signature_of  # noqa: E402
from kkb_agent.core.question_preflight import _PREMISE  # noqa: E402
from kkb_agent.core.small_talk import data_sets_reply, is_identity_question  # noqa: E402
from kkb_agent.domain import DomainProfile, series_label  # noqa: E402
from kkb_agent.llm.base import LLMResponse  # noqa: E402
from kkb_agent.source_hints import load_source_hints  # noqa: E402
from kkb_agent.tools.ingest import _UPLOAD_PREFIX, _locator_names, _slug  # noqa: E402
from test_agent_loop import _agent, _ScriptedLLM  # noqa: E402


def _spec(sid: str, name: str, source: str, start: date, end: date) -> DatasetSpec:
    return DatasetSpec(dataset_id=sid, name=name, description="d", source=source, frequency=Frequency.MONTHLY, time_column="observation_date",
                       grain=["observation_date"], coverage=Coverage(start=start, end=end, row_count=12),
                       columns=[ColumnSpec(name="observation_date", role=ColumnRole.TIME, dtype="DATE", description="dönem"),
                                ColumnSpec(name="value", role=ColumnRole.MEASURE, dtype="DOUBLE", description="değer",
                                           semantic_type=SemanticType.STOCK, unit="kişi")])


def test_genis_ay_kolonlu_tablo_aylik_sayilir_ay_sorusu_reddedilmez() -> None:
    wide = pd.DataFrame({"Yıl": [2024, 2025], "Ocak": ["12.345,6", "15.000,0"], "Şubat": ["9.876,5", "8.100,25"]})
    sig = signature_of(wide, "https://site.example/ith_au.pdf")
    assert sig.frequency == "monthly" and sig.years == (2024, 2025)
    assert assess("2025 Ocak altın ithalatı", sig, Lexicon.empty()).decision != "reject"
    yearly = signature_of(pd.DataFrame({"Yıl": [2023, 2024, 2025], "toplam": [1, 2, 3]}), "yillik.csv")
    assert yearly.frequency == "yearly", "ay kolonu yoksa yıllık kalır"


def test_kosullu_donem_aramasi_oncul_degil_yon_varsayimi_oncul_kalir() -> None:
    assert _PREMISE.search("Faiz oranlarının düştüğü halde kredi miktarının yükselmediği dönemler olmuş mu?") is None, "K02 A06"
    assert _PREMISE.search("Faiz düştüğü halde kredinin artmadığı aylar hangileri? Hangi aylarda böyle oldu?") is None
    assert _PREMISE.search("2025'te konut kredileri düştüğü için taşıt kredileri arttı mı?") is not None
    assert _PREMISE.search("2025'te taşıt kredisi neden arttı?") is not None
    assert _PREMISE.search("Faiz düştüğü halde kredi neden artmadı?") is not None, "dönem araması yoksa 'halde' öncül kalır"


def test_kimlik_sorusu_tanimi() -> None:
    for q in ("Sen kimsin?", "sen kimsin", "Neler yapabilirsin?", "Kendini tanıtır mısın?", "Ne işe yararsın?", "Kimsiniz?"):
        assert is_identity_question(q), q
    for q in ("Faiz düşerse kredi ne yapabilir?", "2025 konut kredisi kimsin", "Konut kredisi bakiyesini göster",
              "Sen kimsin ve 2025 Aralık konut kredisi bakiyesi ne kadar, aylık değişimi nasıl, grafiğini de çiz?"):
        assert not is_identity_question(q), q


def test_tablo_yokken_kimlik_cevabi_veri_cekilmedi_diye_geri_gonderilmez() -> None:
    draft = "Veri havuzundaki kaynaklar üzerinde çalışan bir veri analisti ajansıyım; soruları sorgu ve kanıtla cevaplarım."
    agent, _ = _agent(_ScriptedLLM([LLMResponse(content=draft), LLMResponse(content="Şu an elimde cevaplanacak bir soru yok.")]))
    assert not agent.workspace.has_table
    ans = agent.ask("Sen kimsin?")
    assert ans.text == draft, "ilk taslak yayımlanır (önce ikinci, bozuk metin gidiyordu)"
    assert not any("veri çekilmeden" in (s.thought or "") for s in ans.steps)
    other, _ = _agent(_ScriptedLLM([LLMResponse(content="Bakiye yükseldi."), LLMResponse(content="Veriyi çekmeden cevap veremem.")]))
    data_q = other.ask("2025 Aralık ayında konut kredisi bakiyesi bir önceki aya göre nasıl değişti?")
    assert any("veri çekilmeden" in (s.thought or "") for s in data_q.steps), "veri sorusunda geri gönderme sürer"


def test_yukleme_on_eki_seri_anahtarina_ve_ilgi_terimlerine_girmez() -> None:
    assert _slug(_UPLOAD_PREFIX.sub("", Path("/srv/uploads/ab12cd34/cb6d79f3_hastane_il.csv").stem)) == "hastane_il"
    assert _slug(_UPLOAD_PREFIX.sub("", "deadbeefx_rapor")) == "deadbeefx_rapor", "8 onaltılık + alt çizgi değilse dokunulmaz"
    text = _locator_names("/private/var/folders/bg/T/pytest-of-baran/incoming/cb6d79f3_sicaklik.csv dosyasını taslak seri olarak ekle")
    assert "sicaklik" in text and "cb6d79f3" not in text and "folders" not in text and "baran" not in text


def test_yalniz_kullanici_serisi_varsa_alan_ve_veri_seti_cevabi_seri_adiyla() -> None:
    acil = _spec("adhoc:acil_basvuru", "acil_basvuru — acil_basvuru_aylik.csv (taslak)", "adhoc", date(2025, 1, 31), date(2025, 12, 31))
    assert series_label(acil) == "acil basvuru"
    assert DomainProfile.from_catalog([acil]).domain == "kullanıcının eklediği acil basvuru verileri"
    many = [_spec(f"adhoc:s{i}", f"s{i} — s{i}.csv (taslak)", "adhoc", date(2025, 1, 31), date(2025, 12, 31)) for i in range(5)]
    assert DomainProfile.from_catalog(many).domain == "kullanıcının eklediği s0, s1, s2 ve 2 seri daha verileri"
    hints = load_source_hints()
    assert data_sets_reply([acil], hints) == "Veri havuzunda kullanıcının eklediği seriler var: acil basvuru (2025-01 → 2025-12)."
    unknown = _spec("adhoc:web", "web — web.csv (taslak)", "adhoc", date(1900, 1, 1), date(1900, 1, 1))
    assert data_sets_reply([unknown], hints) == "Veri havuzunda kullanıcının eklediği seriler var: web.", "1900 yer tutucusu kapsam yazılmaz"
    gold = _spec("gold.konut_faizi", "Konut kredisi faiz oranı — aylık ortalama", "gold", date(2016, 1, 31), date(2026, 6, 30))
    assert series_label(gold) == "Konut kredisi faiz oranı — aylık ortalama", "kullanıcı serisi dışındaki ad kırpılmaz"
