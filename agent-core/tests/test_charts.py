"""Grafik katmanı: inşacı kuralı uygular, denetçi bağımsız sınar, dosya yalnız geçince yazılır.

Denetçi testleri belirtimi KASITLI bozar: inşacı doğru üretse de denetçinin yakalayıp
yakalamadığı ayrı bir sorudur. Aynı dosyada olsalardı inşacının hatası denetçinin de
hatası olurdu.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.charts import (  # noqa: E402
    ChartIntent, GeoAsset, build_spec, lint_spec, load_geo_asset, normalize_province,
    period_label, render_chart,
)
from kkb_agent.charts.spec import chart_title  # noqa: E402


def _monthly(n: int = 12, bad_at: int | None = 4) -> pd.DataFrame:
    rows = []
    for i in range(n):
        d = date(2025, i + 1, 28)
        rows.append({"donem": d, "bakiye": 500_000.0 + i * 10_000, "faiz": 40.0 - i * 0.5,
                     "quality_flag": "source_warning" if i == bad_at else "ok"})
    return pd.DataFrame(rows)


def _intent(**kw) -> ChartIntent:
    base = dict(kind="line", x="donem", y=("bakiye",), title="Konut kredisi bakiyesi",
                unit_labels={"bakiye": "milyon TL"}, period="2025-01-28 → 2025-12-28",
                level_columns=frozenset({"bakiye"}), quality_column="quality_flag")
    base.update(kw)
    return ChartIntent(**base)


def _square(x0: float, y0: float, name: str) -> dict:
    return {"type": "Feature", "properties": {"name": name},
            "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x0 + 1, y0], [x0 + 1, y0 + 1], [x0, y0 + 1], [x0, y0]]]}}


GEO = GeoAsset(features=(_square(32, 39, "Ankara"), _square(28, 41, "İstanbul"), _square(27, 38, "izmir")),
               name_property="name", source="sentetik")


# ------------------------------------------------------------------ inşacı


def test_stok_serisi_sifirdan_baslar_birim_ve_donem_baslikta_uyarili_gozlem_isaretli() -> None:
    frame = _monthly()
    intent = _intent()
    spec = build_spec(frame, intent)

    assert spec["title"]["text"] == "Konut kredisi bakiyesi · milyon TL · 2025-01-28 → 2025-12-28"
    main, bad = spec["layer"]
    assert main["encoding"]["y"]["scale"] == {"zero": True}
    assert "milyon TL" in main["encoding"]["y"]["title"]
    assert bad["mark"]["type"] == "point" and "quality_flag" in bad["transform"][0]["filter"]
    assert len(spec["data"]["values"]) == 12
    assert spec["data"]["values"][0]["donem"] == "2025-01-28"
    assert main["encoding"]["x"]["title"] == "dönem" and "timeUnit" not in main["encoding"]["x"]  # 28'i: ay sonu değil

    report = lint_spec(spec, frame, intent)
    assert report.ok, report.render()
    assert report.render().startswith("denetim: 6/6 kural geçti")


def test_temiz_veride_kalite_katmani_yok_ve_denetci_yine_gecer() -> None:
    frame = _monthly(bad_at=None)
    intent = _intent()
    spec = build_spec(frame, intent)
    assert "layer" not in spec and spec["mark"]["type"] == "line"
    assert lint_spec(spec, frame, intent).ok


def test_oran_serisi_sifir_tabani_zorunlu_degil() -> None:
    frame = _monthly(bad_at=None)
    intent = _intent(y=("faiz",), unit_labels={"faiz": "yüzde"}, level_columns=frozenset())
    spec = build_spec(frame, intent)
    assert spec["encoding"]["y"]["scale"] == {}
    assert lint_spec(spec, frame, intent).ok


def test_cok_seri_tek_eksen_katlanir_ve_farkli_birim_reddedilir() -> None:
    frame = _monthly(bad_at=None)
    same = _intent(y=("bakiye", "faiz"), unit_labels={"bakiye": "milyon TL", "faiz": "milyon TL"})
    spec = build_spec(frame, same)
    assert spec["transform"][0]["fold"] == ["bakiye", "faiz"] and spec["encoding"]["color"]["field"] == "seri"
    assert lint_spec(spec, frame, same).ok

    mixed = _intent(y=("bakiye", "faiz"), unit_labels={"bakiye": "milyon TL", "faiz": "yüzde"})
    report = lint_spec(build_spec(frame, mixed), frame, mixed)
    assert not report.ok and "single_unit_axis" in [r.rule for r in report.failures]


def test_cift_eksen_yalniz_istenince() -> None:
    frame = _monthly(bad_at=None)
    asked = _intent(y=("bakiye", "faiz"), unit_labels={"bakiye": "milyon TL", "faiz": "yüzde"}, dual_axis=True)
    spec = build_spec(frame, asked)
    assert spec["resolve"] == {"scale": {"y": "independent"}} and len(spec["layer"]) == 2
    assert spec["layer"][0]["encoding"]["y"]["scale"] == {"zero": True}   # stok yine sıfırdan
    assert spec["layer"][1]["encoding"]["y"]["axis"]["orient"] == "right"
    assert lint_spec(spec, frame, asked).ok

    not_asked = _intent(y=("bakiye", "faiz"), unit_labels={"bakiye": "milyon TL", "faiz": "yüzde"})
    report = lint_spec(spec, frame, not_asked)   # aynı belirtim, istek yok
    assert "dual_axis_asked" in [r.rule for r in report.failures]


def test_log_olcek_etiketli_ve_sifir_kurali_askiya_alinir() -> None:
    frame = _monthly(bad_at=None)
    intent = _intent(log_scale=True)
    spec = build_spec(frame, intent)
    assert spec["encoding"]["y"]["scale"] == {"type": "log"}
    assert "[log ölçek]" in spec["encoding"]["y"]["title"]
    assert lint_spec(spec, frame, intent).ok

    spec["encoding"]["y"]["title"] = "bakiye (milyon TL)"   # etiketi sil
    assert "log_labelled" in [r.rule for r in lint_spec(spec, frame, intent).failures]


def test_cubuk_sifirdan_baslar() -> None:
    frame = _monthly(bad_at=None)
    intent = _intent(kind="bar")
    spec = build_spec(frame, intent)
    assert spec["mark"]["type"] == "bar" and spec["encoding"]["y"]["scale"] == {"zero": True}
    assert lint_spec(spec, frame, intent).ok


# ------------------------------------------------------------------ denetçi, kasıtlı bozuk


def test_denetci_kesik_ekseni_yakalar() -> None:
    frame = _monthly(bad_at=None)
    intent = _intent()
    spec = build_spec(frame, intent)
    spec["encoding"]["y"]["scale"] = {"zero": False}
    report = lint_spec(spec, frame, intent)
    assert not report.ok and report.failures[0].rule == "level_zero"
    assert "✗ level_zero" in report.render()


def test_denetci_baslikta_birim_ve_donem_ister() -> None:
    frame = _monthly(bad_at=None)
    intent = _intent()
    spec = build_spec(frame, intent)
    spec["title"]["text"] = "Konut kredisi"
    failures = {r.rule: r.detail for r in lint_spec(spec, frame, intent).failures}
    assert "title_unit_period" in failures and "milyon TL" in failures["title_unit_period"]


def test_denetci_sessiz_alt_kumeyi_yakalar() -> None:
    frame = _monthly(bad_at=None)
    intent = _intent()
    spec = build_spec(frame, intent)
    spec["data"]["values"] = spec["data"]["values"][:6]
    failures = {r.rule: r.detail for r in lint_spec(spec, frame, intent).failures}
    assert failures == {"no_silent_subset": "tabloda 12 satır, grafikte 6"}


def test_denetci_isaretsiz_uyarili_gozlemi_yakalar() -> None:
    frame = _monthly(bad_at=3)
    intent = _intent()
    spec = build_spec(frame, intent)
    spec["layer"] = [spec["layer"][0]]   # kalite katmanını at
    assert "quality_marked" in [r.rule for r in lint_spec(spec, frame, intent).failures]


# ------------------------------------------------------------------ harita


def test_il_adi_normalizasyonu() -> None:
    assert normalize_province("İstanbul") == normalize_province("ISTANBUL") == normalize_province(" istanbul ") == "ISTANBUL"
    assert normalize_province("Şanlıurfa") == "SANLIURFA" and normalize_province("Çankırı") == "CANKIRI"
    assert normalize_province("Kahramanmaraş") == "KAHRAMANMARAS" and normalize_province("Iğdır") == "IGDIR"


def test_harita_iller_esleşir_ve_bilinmeyen_il_denetciyi_durdurur() -> None:
    frame = pd.DataFrame({"il": ["Ankara", "İSTANBUL", "İzmir"], "bakiye": [1.0, 5.0, 2.0], "quality_flag": ["ok", "ok", "ok"]})
    intent = ChartIntent(kind="map", x=None, y=("bakiye",), title="İl bazında konut kredisi",
                         unit_labels={"bakiye": "bin TL"}, period="2025-09-30", level_columns=frozenset({"bakiye"}),
                         quality_column="quality_flag", province_column="il", geo=GEO)
    spec = build_spec(frame, intent)
    assert spec["mark"]["type"] == "geoshape" and spec["transform"][0]["lookup"] == "properties.il"
    assert [f["properties"]["il"] for f in spec["data"]["values"]["features"]] == ["ANKARA", "ISTANBUL", "IZMIR"]
    assert {r["il"] for r in spec["transform"][0]["from"]["data"]["values"]} == {"ANKARA", "ISTANBUL", "IZMIR"}
    assert "bin TL" in spec["encoding"]["color"]["title"]
    report = lint_spec(spec, frame, intent)
    assert report.ok, report.render()

    frame2 = pd.concat([frame, pd.DataFrame({"il": ["Yalova"], "bakiye": [0.5], "quality_flag": ["ok"]})], ignore_index=True)
    report2 = lint_spec(build_spec(frame2, intent), frame2, intent)
    assert not report2.ok and "YALOVA" in report2.failures[0].detail


def test_geojson_yukleyici_dosya_yoksa_none(tmp_path: Path) -> None:
    assert load_geo_asset(tmp_path) is None and load_geo_asset(None) is None
    (tmp_path / "tr_provinces.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [_square(0, 0, "Ankara")]}), encoding="utf-8")
    asset = load_geo_asset(tmp_path)
    assert asset is not None and asset.name_property == "name" and asset.names() == ["ANKARA"]


# ------------------------------------------------------------------ çizim


def test_render_belirtim_ve_png_yazar_ad_deterministik(tmp_path: Path) -> None:
    frame = _monthly()
    intent = _intent()
    spec = build_spec(frame, intent)
    a = render_chart(spec, out_dir=tmp_path)
    b = render_chart(spec, out_dir=tmp_path)
    assert a.spec_path == b.spec_path and a.spec_path.name.startswith("konut_kredisi_bakiyesi")
    assert json.loads(a.spec_path.read_text(encoding="utf-8"))["title"]["text"] == chart_title(intent)
    assert a.png_path is not None and a.png_path.stat().st_size > 10_000
    assert a.svg_path is not None and "<svg" in a.svg_path.read_text(encoding="utf-8")[:200]
    assert a.render_error is None


def test_period_label_tarih_kolonundan() -> None:
    assert period_label(_monthly(), "donem") == "2025-01-28 → 2025-12-28"
    assert period_label(_monthly(), None) == ""


def test_ay_sonu_tarihleri_ay_kutusuna_girer() -> None:
    """Ölçüldü: 2025-01-31 düz eksende '2025-02' çizgisine düşüyordu; ay kutusu Ocak'a koyar."""
    import calendar
    frame = pd.DataFrame({"donem": [date(2025, m, calendar.monthrange(2025, m)[1]) for m in range(1, 13)],
                          "bakiye": [float(i) for i in range(12)]})
    intent = _intent(quality_column=None)
    spec = build_spec(frame, intent)
    assert spec["encoding"]["x"]["timeUnit"] == "yearmonth" and spec["encoding"]["x"]["title"] == "dönem"
    assert lint_spec(spec, frame, intent).ok


def test_noktali_kolon_adi_vega_icin_guvenli_hale_gelir() -> None:
    """Ölçüldü: 'evds:TP.KTF12::value' Vega'da iç içe erişim sayıldı, çizgi hiç çizilmedi."""
    frame = _monthly(bad_at=None).rename(columns={"faiz": "evds:TP.KTF12::value"})
    intent = _intent(y=("evds:TP.KTF12::value",), unit_labels={"evds:TP.KTF12::value": "yüzde"},
                     level_columns=frozenset(), quality_column=None)
    spec = build_spec(frame, intent)
    assert spec["encoding"]["y"]["field"] == "evds:TP_KTF12::value"
    assert spec["data"]["values"][0]["evds:TP_KTF12::value"] == 40.0
    assert spec["usermeta"]["fields"]["evds:TP_KTF12::value"] == "evds:TP.KTF12::value"
    assert "yüzde" in spec["encoding"]["y"]["title"]
    assert lint_spec(spec, frame, intent).ok


def test_donem_etiketi_tam_sayili_float_yili_tam_sayi_yazar() -> None:
    from kkb_agent.charts.spec import period_label
    assert period_label(pd.DataFrame({"year": [2000.0, 2023.0]}), "year") == "2000 → 2023"
    assert period_label(pd.DataFrame({"v": [1.5, 2.5]}), "v") == "1.5 → 2.5"
