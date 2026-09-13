"""M12 (ADR-0052): analitik araçlar zaman eksenini doğrular; kısa/sırasız/tekrarlı/boşluklu/sonsuz/sabit
seriler kontrollü (A15, A16, A29). Satır sırası zaman sayılmaz."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from pydantic import ValidationError
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.analytics import (  # noqa: E402
    AnomalyDetectTool, AnomalyParams, ChangePointsParams, ChangePointsTool, LeadLagParams, LeadLagTool,
    lag_cap, validate_time_axis,
)


def _ws(frame: pd.DataFrame) -> AnalysisWorkspace:
    ws = AnalysisWorkspace(); ws.set_table(frame, description="t"); return ws


def _monthly(n: int, start=date(2024, 1, 31)) -> list[date]:
    return [date(start.year + (start.month - 1 + i) // 12, (start.month - 1 + i) % 12 + 1, 28) for i in range(n)]


def test_a15_8_gozlem_24_gecikme_yapilandirilmis_sonuc_exception_yok() -> None:
    frame = pd.DataFrame({"donem": _monthly(8), "a": [1, 2, 3, 5, 8, 13, 21, 34.0], "b": [2, 3, 5, 8, 13, 21, 34, 55.0]})
    tool = LeadLagTool(_ws(frame))
    params = LeadLagParams(column_a="a", column_b="b", max_lag=24, purpose="test")
    res = tool.run(params)
    assert res.ok or res.error is not None
    if res.ok:
        assert "max_lag 24 → 2" in res.content and "±2 ay" in res.content
    assert lag_cap(8, 24) == (2, "max_lag 24 → 2 (n=8: her gecikmede en az 5 çift, n/3 sınırı)")
    assert lag_cap(120, 6) == (6, None)
    with pytest.raises(ValidationError):
        LeadLagParams(column_a="a", column_b="b", max_lag=0, purpose="x")


def test_a16_sirasiz_seri_zamana_gore_siralanir_ve_kolonlar_hizalanir() -> None:
    dates = _monthly(12)
    vals = [10.0] * 11 + [100.0]                      # son ay sıçrama
    frame = pd.DataFrame({"donem": dates, "v": vals}).iloc[::-1].reset_index(drop=True)   # ters sıra
    axis = validate_time_axis(frame)
    assert axis.reordered and axis.frequency == "aylık" and axis.duplicates == 0 and axis.gaps == 0
    assert list(axis.frame["donem"]) == dates and list(axis.frame.index) == list(range(11, -1, -1))
    ws = _ws(frame)
    out = AnomalyDetectTool(ws).run(AnomalyParams(column="v", purpose="test"))
    assert out.ok and "zamana göre yeniden sıralandı" in out.content and "aylık" in out.content
    t = ws.table
    assert t.loc[t["donem"] == dates[-1], "v_anomali"].iloc[0] == "aykırı", "sonuç orijinal satıra hizalı"
    assert list(t["donem"]) == list(frame["donem"]), "aktif tablonun sırası bozulmadı"


def test_tekrar_tarih_reddedilir_bosluk_ve_duzensizlik_kartta() -> None:
    dates = _monthly(10)
    dup = pd.DataFrame({"donem": dates + [dates[3]], "v": list(range(11))})
    out = ChangePointsTool(_ws(dup)).run(ChangePointsParams(column="v", purpose="test"))
    assert not out.ok and out.error.error_code == "INVALID_ARGS" and "birden çok satır" in out.error.message
    gap_dates = dates[:5] + dates[8:] + _monthly(4, date(2025, 1, 31))
    axis = validate_time_axis(pd.DataFrame({"donem": gap_dates, "v": range(len(gap_dates))}))
    assert axis.gaps >= 1 and any("boşluk" in n for n in axis.notes)
    irregular = [date(2024, 1, 1) + timedelta(days=d) for d in (0, 3, 40, 41, 100, 130, 131, 200, 260, 300)]
    axis2 = validate_time_axis(pd.DataFrame({"donem": irregular, "v": range(10)}))
    assert axis2.frequency == "düzensiz"
    nodate = validate_time_axis(pd.DataFrame({"v": range(10)}))
    assert nodate.column is None and "doğrulanmadı" in nodate.notes[0]


def test_a29_sonsuz_ve_sabit_seri_kontrollu() -> None:
    dates = _monthly(10)
    inf = pd.DataFrame({"donem": dates, "v": [1.0, 2.0, np.inf, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 50.0]})
    out = AnomalyDetectTool(_ws(inf)).run(AnomalyParams(column="v", purpose="test"))
    assert out.ok and "1 sonsuz değer boş sayıldı" in out.content
    const = pd.DataFrame({"donem": dates, "v": [5.0] * 10})
    out2 = AnomalyDetectTool(_ws(const)).run(AnomalyParams(column="v", purpose="test"))
    assert not out2.ok and "sabit" in out2.error.message
    out3 = ChangePointsTool(_ws(const)).run(ChangePointsParams(column="v", purpose="test"))
    assert not out3.ok
