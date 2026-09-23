from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from kkb_agent.contracts.catalog import ColumnRole, Frequency, SemanticType
from kkb_agent.contracts.lakehouse import QueryProvenance
from kkb_agent.core.source_summary import build_source_summary, is_source_question
from kkb_agent.core.agent import AnalyticsAgent
from kkb_agent.core.follow_up import FollowUpContext, resolve_follow_up
from kkb_agent.core.registry import ToolRegistry
from kkb_agent.core.workspace import AnalysisWorkspace


def _spec(dataset_id: str, name: str, *, source: str = "bddk_monthly", measure: str = "value"):
    return SimpleNamespace(
        dataset_id=dataset_id,
        name=name,
        source=source,
        frequency=Frequency.MONTHLY,
        columns=[SimpleNamespace(
            role=ColumnRole.MEASURE,
            name=measure,
            aliases=[name.split(",", 1)[0].strip()],
            unit="TRY_mn",
            semantic_type=SemanticType.STOCK,
        )],
        source_detail=None,
    )


def test_source_question_is_generic_and_structured() -> None:
    assert is_source_question("Bu verinin kaynağı tam olarak ne, hangi serilere dayanıyor?")
    assert is_source_question("What source is this data based on?")
    assert not is_source_question("2024 aylık değerleri getir")


def test_source_question_turkish_inflections_are_recognized() -> None:
    # PROJECT_MEMORY 2.137'deki asıl soru ve Türkçe çekimli biçimler (eski desen "kaynağı"yı tutmuyordu)
    for question in (
        "Verinin kaynağı ve dayandığı seriler nedir?",
        "Bu verinin kaynağı nedir?",
        "Bu tablonun kaynağı ne?",
        "Kaynak nedir?",
        "KAYNAĞI NEDİR?",
        "Kaynağını göster",
        "Veriler nereden geliyor?",
        "Bu veriyi hangi kaynaktan çektin?",
        "Bu hangi serilere dayanıyor?",
    ):
        assert is_source_question(question), question


def test_search_retrieval_and_interpretation_are_not_source_questions() -> None:
    # Yeni katalog araması, yeni veri isteği ve yorum sorusu aktif tablonun kaynak özetiyle cevaplanmaz.
    for question in (
        "Hangi seriler TÜFE'yi gösteriyor?",
        "Hangi kaynaktan enflasyon verisi alabiliriz?",
        "Bu artış neye dayanıyor?",
        "İstanbul için aynı veriyi getir, kaynağı BDDK olsun",
        "Başka bir kaynaktan aynı veriyi bul",
        "Elimizde hangi veri kaynakları var?",
    ):
        assert not is_source_question(question), question


def test_source_summary_separates_sources_series_and_derived_columns() -> None:
    raw_a = "bddk_monthly:1536_Toplam@bddk:10001::value"
    raw_b = "bddk_monthly:1539_Toplam@bddk:10001::value"
    change = raw_a + "_change"
    frame = pd.DataFrame({
        "period_end": pd.to_datetime(["2022-01-31", "2022-02-28"]),
        raw_a: [463.792, 467.902],
        raw_b: [214.776, 221.561],
        change: [None, 4.110],
    })
    workspace = AnalysisWorkspace()
    source_prov = QueryProvenance(
        sql="SELECT ...",
        dataset_ids=["bddk_monthly:1536_Toplam"],
        sources=["bddk_monthly — BDDK Aylık Bülten"],
    )
    derived_prov = QueryProvenance(
        sql=f"türetilmiş: {raw_a} - LAG({raw_a}) OVER (ORDER BY period_end)",
        dataset_ids=["bddk_monthly:1536_Toplam"],
    )
    workspace.set_table(
        frame,
        description="iki seri",
        column_provenance={raw_a: source_prov, raw_b: source_prov, change: derived_prov},
    )
    specs = [
        _spec("bddk_monthly:1536_Toplam", "Tüketici Kredileri - İhtiyaç, Toplam (Sektör)"),
        _spec("bddk_monthly:1539_Toplam", "Bireysel Kredi Kartları, Toplam (Sektör)"),
    ]

    text = build_source_summary(frame, workspace=workspace, specs=specs)

    assert text is not None
    assert "**Veri kaynağı**" in text
    assert "**Kaynak:**" in text
    assert "**Dayandığı seriler:**" in text
    assert "**Dönem:** 2022-01 – 2022-02." in text
    assert "**Frekans:** aylık." in text
    assert "**Birim:** milyon TL." in text
    assert "**Ölçüm türü:** dönem sonu bakiyesi (stok)." in text
    assert "**Hesaplanan kolonlar:**" in text
    assert "önceki döneme göre mutlak değişim" in text
    assert "bddk_monthly:" not in text
    assert "::value" not in text
    assert "tek paragraf" not in text


def test_agent_source_fastpath_does_not_require_an_llm_turn() -> None:
    raw = "bddk_monthly:1536_Toplam@bddk:10001::value"
    frame = pd.DataFrame({"period_end": pd.to_datetime(["2022-01-31"]), raw: [463.792]})
    workspace = AnalysisWorkspace()
    provenance = QueryProvenance(
        sql="SELECT ...",
        dataset_ids=["bddk_monthly:1536_Toplam"],
        sources=["bddk_monthly"],
    )
    workspace.set_table(frame, description="fixture", provenance=provenance)
    spec = _spec("bddk_monthly:1536_Toplam", "Tüketici Kredileri - İhtiyaç")
    agent = AnalyticsAgent(llm=object(), registry=ToolRegistry(), workspace=workspace)
    agent._active_table_reuse_allowed = True
    agent._catalog_specs = lambda: [spec]

    answer = agent._try_verified_source_fastpath(
        "Bu verinin kaynağı nedir ve hangi seriye dayanıyor?"
    )

    assert answer is not None
    assert answer.availability_status == "FOUND"
    assert answer.usage["deterministic_source_summaries"] == 1
    assert "**Kaynak:**" in answer.text


def _adana_agent() -> AnalyticsAgent:
    raw = "bddk_monthly:1536_Toplam@bddk:10001::value"
    frame = pd.DataFrame({"period_end": pd.to_datetime(["2022-01-31"]), raw: [463.792]})
    workspace = AnalysisWorkspace()
    workspace.set_table(frame, description="fixture", provenance=QueryProvenance(
        sql="SELECT ...", dataset_ids=["bddk_monthly:1536_Toplam"], sources=["bddk_monthly"]))
    agent = AnalyticsAgent(llm=object(), registry=ToolRegistry(), workspace=workspace)
    agent._catalog_specs = lambda: [_spec("bddk_monthly:1536_Toplam", "Tüketici Kredileri - İhtiyaç")]
    agent._follow_up_context = FollowUpContext(source="bddk_monthly", metric="ihtiyaç kredisi",
                                               series="bddk_monthly:1536_Toplam", geography=("Adana",))
    return agent


def _reuse_allowed(agent: AnalyticsAgent, question: str) -> bool:
    """ask() içindeki kapının aynısı: kaynak sorusu da uyumluluk kontrolünden geçer, zorla açılmaz."""
    agent._follow_up_resolution = resolve_follow_up(question, agent._follow_up_context, [])
    agent._active_table_reuse_allowed = agent._active_table_is_compatible(question, source_read_only=is_source_question(question))
    return agent._active_table_reuse_allowed


def test_long_source_question_reuses_table_new_search_does_not() -> None:
    agent = _adana_agent()
    long_question = "Bu verinin kaynağı tam olarak ne, hangi serilere dayanıyor?"
    assert not resolve_follow_up(long_question, agent._follow_up_context, []).is_follow_up, "çözücü uzun soruyu yeni soru sayar"
    assert _reuse_allowed(agent, long_question), "yeni bir şey adlandırılmadığı için aynı tablo kullanılabilir"
    assert agent._try_verified_source_fastpath(long_question) is not None

    for question in ("Hangi seriler TÜFE'yi gösteriyor?", "Hangi kaynaktan enflasyon verisi alabiliriz?"):
        agent = _adana_agent()
        assert not _reuse_allowed(agent, question), question
        assert agent._try_verified_source_fastpath(question) is None, "önceki tablonun kaynak özeti yeni soruya cevap olmaz"


def test_source_question_naming_another_province_does_not_reuse_table() -> None:
    agent = _adana_agent()
    agent._catalog_specs = lambda: [_spec("bddk_finturk:ADANA_KonutKredisi", "Konut Kredisi, ADANA", source="bddk_finturk")]
    agent.workspace.set_table(
        pd.DataFrame({"period_end": pd.to_datetime(["2022-01-31"]), "value": [1.0]}), description="Adana",
        provenance=QueryProvenance(sql="SELECT ...", dataset_ids=["bddk_finturk:ADANA_KonutKredisi"]))
    assert agent._active_table_provinces(), "fikstür il serisi"
    assert _reuse_allowed(agent, "Bu verinin kaynağı nedir?")
    assert not _reuse_allowed(agent, "İstanbul verisinin kaynağı nedir?"), "il değişirse kaynak sorusu eski tabloyu kullanmaz"


def test_benchmark_turns_that_mention_source_as_a_constraint_keep_their_normal_path() -> None:
    # DeepSeek 76 vakalık koşu (23 Eyl): bu turlar kaynak sormuyordu, ama cevapları kaynak özetiyle değiştirildi.
    from kkb_agent.core.agent import _is_read_only_source_question
    for question in (
        "Takip: Yalnızca 2022-01–2023-12 dönemini göster. Önceki aktif tablonun aynı seri kimliklerini/ölçüm türlerini koru; yeniden kaynak arama.",
        "Takip: Kullanıcı tablosunda period, üç bakiye, her serinin aylık mutlak farkı ve her serinin aylık yüzde değişimi olsun. "
        "Kanıt/provenance kolonlarını kullanıcı projection’ına katma; ilk satır farkını önceki ay tabanı varsa hesapla.",
        "Takip: Kullanıcı projection’ını CSV ve XLSX olarak dışa aktar; provenance alanlarını dışa aktarılan analiz tablosuna ekleme.",
        "Takip: Aylık farkı hesapla. 2020-01 için 2019-12 kaynak gözlemi varsa LAG tabanı olarak kullan.",
        "Her değeri milyon TL’ye normalize et, birim dönüşümünü satır bazında provenance ile yaz.",
        "2024 takvim yılı konut kredisi bakiye tablosunu göster; ayrı kanıt panelinde kaynak URL ve dönüşüm adımları göster. "
        "Eksik provenance alanını uydurma değil açık eksik olarak işaretle.",
    ):
        assert not _is_read_only_source_question(question), question[:60]
    assert _is_read_only_source_question("Bu verinin kaynağı nedir?")


def test_source_fastpath_records_the_turn_in_history() -> None:
    """ADR-0104: kısayol konuşma hafızasına yazmazsa ask()'teki sonradan düzenlemeler önceki turun cevabını ezer."""
    agent = _adana_agent()
    from kkb_agent.llm.base import ChatMessage
    agent._history = [ChatMessage(role="user", content="önceki soru"), ChatMessage(role="assistant", content="önceki cevap")]
    agent._active_table_reuse_allowed = True
    answer = agent._try_verified_source_fastpath("Bu verinin kaynağı nedir?")
    assert answer is not None
    assert [m.content for m in agent._history[:2]] == ["önceki soru", "önceki cevap"]
    assert agent._history[-2].content == "Bu verinin kaynağı nedir?" and agent._history[-1].content == answer.text
