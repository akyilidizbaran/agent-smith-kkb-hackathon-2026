from __future__ import annotations

import pandas as pd
import pytest

from kkb_agent.builder.temporal import (
    TemporalNormalizationError,
    canonical_month,
    enrich_frames,
    infer_measure_semantics,
    infer_temporal,
    normalize_frequency,
    persistence_intent,
    prefer_native_source,
    requested_months_from_text,
    validate_completion,
)
from kkb_agent.core.workspace import AnalysisWorkspace


def weekly_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Dönem": [
                "2021/01 (04.01.21-08.01.21)",
                "2021/02 (11.01.21-15.01.21)",
                "2021/03 (18.01.21-22.01.21)",
                "2021/04 (25.01.21-29.01.21)",
                "2021/05 (01.02.21-05.02.21)",
            ],
            "İşlem Hacmi": [10, 20, 30, 40, 50],
            "Mevduat Stoku": [100, 110, 120, 130, 140],
            "Faiz Oranı (%)": [10, 20, 30, 40, 50],
            "Günlük Ortalama Yardımcı": [1, 2, 3, 4, 5],
        }
    )


def test_a_weekly_flow_to_monthly_sums_without_cross_month_allocation():
    frame = weekly_frame()
    result = normalize_frequency(frame, requested="monthly", requested_columns=["İşlem Hacmi"])
    assert result.temporal.frequency == "weekly"
    assert result.frame["period_month"].tolist() == ["2021-01", "2021-02"]
    assert result.frame["İşlem Hacmi"].tolist() == [100, 50]
    assert result.metadata.aggregation_method == {"İşlem Hacmi": "sum"}


def test_b_weekly_stock_uses_period_end_value():
    result = normalize_frequency(weekly_frame(), requested="monthly", requested_columns=["Mevduat Stoku"])
    assert result.frame["Mevduat Stoku"].tolist() == [130, 140]
    assert result.metadata.aggregation_method["Mevduat Stoku"] == "last_period_end"


def test_c_rate_is_averaged_not_summed():
    result = normalize_frequency(weekly_frame(), requested="monthly", requested_columns=["Faiz Oranı (%)"])
    assert result.frame["Faiz Oranı (%)"].tolist() == [25.0, 50.0]
    # İş günü ağırlıklı ortalama: eşit uzunluklu haftalarda basit ortalamayla aynı sonucu verir.
    assert result.metadata.aggregation_method["Faiz Oranı (%)"] == "business_day_weighted_mean"


def test_d_unknown_semantics_fails_closed():
    frame = weekly_frame().rename(columns={"İşlem Hacmi": "Özel Gösterge"})
    with pytest.raises(TemporalNormalizationError) as error:
        normalize_frequency(frame, requested="monthly", requested_columns=["Özel Gösterge"])
    assert error.value.code == "MEASURE_SEMANTICS_AMBIGUOUS"


def test_e_cross_month_interval_goes_to_its_start_month_and_is_reported():
    """ADR-0108 ek (23 Eyl): ay sınırını aşan hafta başladığı aya yazılır; bölüştürülmez, uydurulmaz, uyarıda söylenir.
    Kaynağın kendi aylık raporu da haftayı başladığı aya sayar (kaynağın aylık raporuyla karşılaştırıldı)."""
    frame = pd.DataFrame({"period": ["2021/05 (29.01.21-02.02.21)", "2021/06 (05.02.21-09.02.21)", "Toplam"],
                          "volume": [10, 20, 30]})
    result = normalize_frequency(frame, requested="monthly", requested_columns=["volume"])
    assert result.frame["period_month"].tolist() == ["2021-01", "2021-02"]
    assert result.frame["volume"].tolist() == [10, 20]
    assert result.metadata.aggregation_method["volume"] == "sum_by_period_start_month"
    warnings = " ".join(result.metadata.warnings)
    assert "başladığı aya yazıldı" in warnings and "alt toplam" in warnings


def test_f_native_frequency_is_preferred():
    weekly = infer_temporal(weekly_frame())
    monthly = infer_temporal(pd.DataFrame({"month": ["2021-01", "2021-02"], "value": [1, 2]}))
    assert prefer_native_source([weekly, monthly], "monthly") == 1


def test_g_interval_period_is_weekly_not_monthly():
    parsed = infer_temporal(pd.DataFrame({"Dönem": ["2021/01 (04.01.21-08.01.21)"]}))
    assert parsed.frequency == "weekly"
    assert parsed.confidence == "high"
    assert parsed.parsed[0].period_code == "2021/01"
    assert str(parsed.parsed[0].start) == "2021-01-04"


def test_h_common_month_spellings_share_canonical_key():
    assert {canonical_month(value) for value in ("202101", "2021-01", "2021-01-31")} == {"2021-01"}


def test_h2_explicit_requested_month_range_is_inclusive():
    assert requested_months_from_text("202101–202103 aylık") == ["2021-01", "2021-02", "2021-03"]


def test_i_projection_drops_unrequested_helpers():
    result = normalize_frequency(weekly_frame(), requested="monthly", requested_columns=["İşlem Hacmi"])
    assert list(result.frame.columns) == ["period_month", "İşlem Hacmi"]


def test_j_workspace_enrichment_preserves_existing_columns():
    workspace = AnalysisWorkspace()
    workspace.set_table(
        pd.DataFrame({"month": ["2021-01", "2021-02"], "existing": [1, 2]}),
        description="base",
    )
    metadata = workspace.enrich_table(
        pd.DataFrame({"period_month": ["2021-01", "2021-02"], "external": [10, 20]}),
        left_period="month",
        right_period="period_month",
        columns=["external"],
        description="enrich",
    )
    assert workspace.table is not None
    assert list(workspace.table.columns) == ["month", "existing", "external"]
    assert workspace.table["external"].tolist() == [10, 20]
    assert metadata["join_cardinality"] == "one_to_one"


def test_k_duplicate_join_key_fails_before_row_multiplication():
    with pytest.raises(TemporalNormalizationError) as error:
        enrich_frames(
            pd.DataFrame({"month": ["2021-01"]}),
            pd.DataFrame({"period_month": ["2021-01", "2021-01"], "value": [1, 2]}),
            left_period="month",
            right_period="period_month",
            columns=["value"],
        )
    assert error.value.code == "DUPLICATE_JOIN_KEY"


def test_l_session_only_is_not_persistence():
    assert persistence_intent("bu dosyayı sadece bu oturumda analiz et") == "SESSION_ONLY"


def test_m_persistence_request_is_visible_to_contract():
    assert persistence_intent("veriyi lakehouse'a ekle") == "PERSIST_TO_LAKEHOUSE"
    report = validate_completion(
        requested_frequency="monthly",
        result_frequency="monthly",
        persistence_requested=True,
        persistence_state="SESSION_ONLY",
    )
    assert report.status == "PARTIAL"
    assert "persistence requested" in report.failures[0]


def test_n_weekly_result_cannot_satisfy_monthly_contract():
    report = validate_completion(requested_frequency="monthly", result_frequency="weekly")
    assert report.status == "PARTIAL"


def test_o_non_finance_measure_semantics_are_generic():
    assert infer_measure_semantics("Passenger Count").measure_type == "COUNT"
    assert infer_measure_semantics("Energy Volume").measure_type == "FLOW"


def test_p_period_end_value_does_not_depend_on_row_order():
    """Dışa aktarımların çoğu yeniden eskiye sıralıdır; ay sonu değeri buna bağlı olamaz."""
    artan = normalize_frequency(weekly_frame(), requested="monthly", requested_columns=["Mevduat Stoku"])
    azalan = normalize_frequency(
        weekly_frame().iloc[::-1].reset_index(drop=True),
        requested="monthly",
        requested_columns=["Mevduat Stoku"],
    )
    assert azalan.frame["period_month"].tolist() == ["2021-01", "2021-02"]
    assert azalan.frame["Mevduat Stoku"].tolist() == artan.frame["Mevduat Stoku"].tolist() == [130, 140]


def test_p2_sum_and_mean_are_also_order_stable():
    azalan = weekly_frame().iloc[::-1].reset_index(drop=True)
    flow = normalize_frequency(azalan, requested="monthly", requested_columns=["İşlem Hacmi"])
    rate = normalize_frequency(azalan, requested="monthly", requested_columns=["Faiz Oranı (%)"])
    assert flow.frame["İşlem Hacmi"].tolist() == [100, 50]
    assert rate.frame["Faiz Oranı (%)"].tolist() == [25.0, 50.0]


def test_q_qualified_flow_keyword_is_not_summed():
    """'İşlem Fiyatı' akım kalıbına uyar ama toplanamaz: kapalı tarafa düşmeli."""
    assert infer_measure_semantics("İşlem Hacmi").measure_type == "FLOW"
    assert infer_measure_semantics("İşlem Fiyatı").measure_type == "UNKNOWN"
    assert infer_measure_semantics("Ortalama Tutar").measure_type == "UNKNOWN"
    assert infer_measure_semantics("Birim Satış Tutarı").measure_type == "UNKNOWN"

    frame = weekly_frame().rename(columns={"İşlem Hacmi": "İşlem Fiyatı"})
    with pytest.raises(TemporalNormalizationError) as error:
        normalize_frequency(frame, requested="monthly", requested_columns=["İşlem Fiyatı"])
    assert error.value.code == "MEASURE_SEMANTICS_AMBIGUOUS"


def test_r_unparseable_cell_is_a_temporal_error_not_a_bare_value_error():
    """Boş hücre aracı düşürmemeli: çağıran yalnız TemporalNormalizationError yakalıyor."""
    frame = weekly_frame()
    frame["İşlem Hacmi"] = ["10", "", "30", "40", "50"]
    with pytest.raises(TemporalNormalizationError) as error:
        normalize_frequency(frame, requested="monthly", requested_columns=["İşlem Hacmi"])
    assert error.value.code == "VALUE_PARSE_FAILED"
