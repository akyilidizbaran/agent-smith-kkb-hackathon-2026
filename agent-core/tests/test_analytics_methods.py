"""Analitik yöntemler sentetik seriyle: LLM yok, sonuç deterministik (ADR-0040)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.analytics.methods import (  # noqa: E402
    binary_segmentation, choose_basis, cross_correlation, detect_anomalies, detect_change_points,
    detect_seasonal_anomalies, granger_test, lead_lag, pct_changes,
)


def test_iqr_duzeyde_tek_sicramayi_bulur() -> None:
    rng = np.random.default_rng(1)
    x = 100 + rng.normal(0, 1, 60)
    x[30] = 112.0
    r = detect_anomalies(x, basis="level")
    assert r.method == "iqr" and r.basis == "level"
    # Tukey çiti normal gürültüde tek tük noktayı da işaretleyebilir (%0,7); sıçrama en yüksek skor olmalı.
    assert r.flags[30] and r.count <= 2 and np.nanargmax(r.scores) == 30 and r.scores[30] > 1.5


def test_trendli_seride_otomatik_degisim_tabani_ve_uclar_aykiri_degil() -> None:
    """Ölçüldü: yükselen stok seride düzey IQR'ı iki ucu 'aykırı' sayar; değişim tabanı saymaz."""
    rng = np.random.default_rng(5)
    growth = 1 + (2.0 + rng.normal(0, 0.3, 48)) / 100     # ~%2/ay, hafif gürültülü
    x = 100 * np.cumprod(growth)
    x[24:] = x[24:] * 1.15                                  # 24. ayda %15 sıçrama, kalıcı
    basis, rho = choose_basis(x)
    assert basis == "change" and rho > 0.99
    r = detect_anomalies(x)
    assert r.basis == "change" and r.flags[24] and not r.flags[0] and not r.flags[-1]
    assert np.isnan(r.scores[0])      # ilk değişim tanımsız


def test_zskoru_esigi() -> None:
    rng = np.random.default_rng(2)
    x = rng.normal(0, 1, 200)
    x[50] = 6.0
    r = detect_anomalies(x, method="zscore", basis="level")
    assert r.flags[50] and r.count == 1 and abs(r.scores[50]) > 3


def test_ikili_bolutleme_sicramayi_bulur_gurultude_bulmaz() -> None:
    rng = np.random.default_rng(3)
    noise = rng.normal(0, 1, 100)
    step = np.concatenate([np.zeros(50), np.full(50, 3.0)]) + noise
    breaks, pen = binary_segmentation(step)
    assert len(breaks) == 1 and abs(breaks[0] - 50) <= 2 and pen > 0
    assert binary_segmentation(noise)[0] == []


def test_kirilma_trendli_seride_buyume_rejimini_bulur() -> None:
    """Yıllık %0,5 büyüyen seri 36. aydan sonra %3 büyümeye geçiyor."""
    g = np.array([0.5] * 36 + [3.0] * 36) / 100
    x = 100 * np.cumprod(1 + g)
    r = detect_change_points(x)
    assert r.basis == "change"
    assert len(r.breaks) >= 1 and abs(r.breaks[0] - 36) <= 2
    assert r.segments[0].mean < 1.0 < r.segments[-1].mean


def test_oncul_ardil_gecikmeyi_ve_granger_yonunu_bulur() -> None:
    rng = np.random.default_rng(4)
    a = rng.normal(0, 1, 300)
    b = np.zeros(300)
    for t in range(2, 300):
        b[t] = 0.9 * a[t - 2] + 0.2 * rng.normal()   # A, B'den 2 dönem önce
    lags, rs = cross_correlation(a, b, 4)
    assert lags[rs.index(max(rs))] == 2
    r = lead_lag(a, b, max_lag=4, basis="level")
    assert r.best_lag == 2 and r.best_r > 0.9 and r.n == 300
    g = {x.direction: x for x in r.granger}
    assert g["A→B"].p_value < 0.001 and g["B→A"].p_value > 0.05


def test_granger_yetersiz_veride_none() -> None:
    assert granger_test(np.arange(10.0), np.arange(10.0), 4) is None


def test_yuzde_degisim_sifira_bolme_nan() -> None:
    assert np.isnan(pct_changes(np.array([0.0, 1.0]))[1]) and pct_changes(np.array([2.0, 3.0]))[1] == 50.0


def test_iqr_sifirsa_zskoruna_duser() -> None:
    x = 100 * np.cumprod(np.full(48, 1.02))
    x[24:] = x[24:] * 1.15
    r = detect_anomalies(x)
    assert r.method.startswith("zscore") and r.flags[24] and r.count == 1


def test_seasonal_mad_ayni_takvim_ayini_yillar_arasinda_karsilastirir() -> None:
    months = np.tile(np.arange(1, 13), 5)
    values = np.tile(np.arange(1, 13, dtype=float) * 10, 5)
    january_indices = np.flatnonzero(months == 1)
    values[january_indices[-1]] = 110.0

    result = detect_seasonal_anomalies(values, months, threshold=3, min_periods=4)

    assert result.method == "seasonal_mad" and result.basis == "level"
    assert result.flags[january_indices[-1]]
    assert not result.flags[january_indices[0]]
    assert result.count == 1
    assert not np.isnan(result.scores[0])


def test_seasonal_mad_yetersiz_takvim_ayi_gozlemlerini_puanlamaz() -> None:
    result = detect_seasonal_anomalies(
        np.array([10.0, 11.0, 12.0, 40.0]), np.array([1, 2, 3, 4]), min_periods=4,
    )
    assert np.isnan(result.scores).all()
    assert not result.flags.any()


def test_a33_trendli_seride_duzey_sicramasi_yuzde_tabaninda_dogru_ayda() -> None:
    """M16 (14 Eyl): fikstürde 2025-01 düzey kırılması yüzde tabanında Ekim 2024'e kayıyordu (min segment gömmesi)."""
    import pandas as pd
    from pathlib import Path
    from kkb_agent.analytics.methods import detect_change_points, level_jumps

    df = pd.read_csv(Path(__file__).parent / "fixtures" / "generic" / "web_ziyaret_kirilma.csv", sep=";")
    res = detect_change_points(df["gunluk_ziyaret"].to_numpy(dtype=float), basis="auto")
    jan = int(df.index[df["donem"] == "2025-01-31"][0])
    assert res.basis == "change" and jan in res.jumps and jan in res.breaks
    assert all(abs(b - jan) >= 4 for b in res.breaks if b != jan), "aynı olay ikinci kez sayılmadı"
    rng = np.random.default_rng(7)
    assert level_jumps(rng.normal(1.0, 0.3, 200)) == [], "saf gürültüde sıçrama yok"
