"""Tablo + niyet → Vega-Lite belirtimi. Kurallar burada inşa edilir, `lint.py`'da sınanır.

Model bu dosyaya hiç dokunmaz: hangi kolonların çizileceğini ve başlığı söyler, eksenin
sıfırdan başlayıp başlamayacağını, birimin nereye yazılacağını, uyarılı gözlemin nasıl
işaretleneceğini söyleyemez. Bunlar veri türünden (katalog) ve veriden (quality_flag)
çıkar; bir tercih değil, bir kuraldır.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal

import pandas as pd

VEGA_LITE_SCHEMA = "https://vega.github.io/schema/vega-lite/v5.json"
QUALITY_OK = "ok"
FOLD_SERIES, FOLD_VALUE = "seri", "deger"

_TR_MAP = str.maketrans({"ı": "I", "İ": "I", "ş": "S", "Ş": "S", "ğ": "G", "Ğ": "G",
                         "ü": "U", "Ü": "U", "ö": "O", "Ö": "O", "ç": "C", "Ç": "C",
                         "â": "A", "î": "I", "û": "U"})


def normalize_province(name: str) -> str:
    """'İstanbul' / 'ISTANBUL' / 'Istanbul ' → 'ISTANBUL'. Harita eşlemesinin tek anahtarı."""
    text = str(name).strip().translate(_TR_MAP).upper()
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


@dataclass(frozen=True)
class GeoAsset:
    """İl sınırları: GeoJSON FeatureCollection ve ad taşıyan özellik."""

    features: tuple[dict[str, Any], ...]
    name_property: str
    source: str  # dosya yolu ya da açıklama; karta yazılır

    def names(self) -> list[str]:
        return [normalize_province(f.get("properties", {}).get(self.name_property, "")) for f in self.features]


@dataclass(frozen=True)
class ChartIntent:
    """Grafiğin NE olduğu. Nasıl çizileceği bu dosyanın kuralı."""

    kind: Literal["line", "bar", "map"]
    x: str | None
    y: tuple[str, ...]
    title: str
    unit_labels: dict[str, str] = field(default_factory=dict)   # y kolonu → "milyon TL"
    labels: dict[str, str] = field(default_factory=dict)        # y kolonu → eksen etiketi (katalog adı)
    period: str = ""                                             # "2025-01-31 → 2025-12-31"
    level_columns: frozenset[str] = frozenset()                  # stok/akım/adet → y sıfırdan başlar
    quality_column: str | None = None
    dual_axis: bool = False       # yalnız kullanıcı açıkça istediyse
    log_scale: bool = False       # yalnız kullanıcı açıkça istediyse
    province_column: str | None = None
    geo: GeoAsset | None = None
    source_note: str = ""         # "Kaynak: BDDK Aylık Bülten" — altyazı

    @property
    def units_in_title(self) -> list[str]:
        return sorted({u for u in self.unit_labels.values() if u})


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()[:10] if not isinstance(value, datetime) or value.time() == datetime.min.time() else value.isoformat()
    if isinstance(value, float):
        return None if math.isnan(value) else value
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, (list, tuple, dict, set)):
        return None  # liste kolonları grafiğe girmez
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value if isinstance(value, (bool, int, str)) else str(value)


_FIELD_UNSAFE = re.compile(r"[.\[\]\\]")


def safe_field(name: str) -> str:
    """Vega alan adında '.' ve '[' iç içe erişim demek: 'evds:TP.KTF12::value' →
    datum['evds:TP']['KTF12::value'] → hep boş. Ölçüldü: çift eksenli grafikte faiz çizgisi
    hiç çizilmedi, sağ eksen yalnız 0 gösterdi. Gömülü veride ve encoding'de güvenli ad,
    başlıkta ve `usermeta.fields`'te asıl ad."""
    return _FIELD_UNSAFE.sub("_", str(name))


def table_values(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    """Belirtime gömülecek satırlar: yalnız gerekli kolonlar, JSON-güvenli, satır sayısı korunur."""
    rows: list[dict[str, Any]] = []
    keys = [safe_field(c) for c in columns]
    for record in frame[columns].itertuples(index=False, name=None):
        rows.append({key: _json_safe(val) for key, val in zip(keys, record)})
    return rows


def period_label(frame: pd.DataFrame, x: str | None) -> str:
    if not x or x not in frame.columns or frame[x].dropna().empty:
        return ""
    xs = frame[x].dropna()
    lo, hi = xs.min(), xs.max()

    def _fmt(v):
        # Yıl kolonu web tablosundan float gelir (2000.0); başlıkta 2000 yazılır.
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return _json_safe(v)

    return f"{_fmt(lo)} → {_fmt(hi)}"


def chart_title(intent: ChartIntent) -> str:
    """Başlık = konu · birim(ler) · dönem. Denetçi üçünü de arar."""
    parts = [intent.title.strip()]
    if intent.units_in_title:
        parts.append(" / ".join(intent.units_in_title))
    if intent.period:
        parts.append(intent.period)
    return " · ".join(parts)


def _x_type(frame: pd.DataFrame, x: str) -> str:
    values = frame[x].dropna()
    if values.empty:
        return "nominal"
    sample = values.iloc[0]
    if isinstance(sample, (date, datetime, pd.Timestamp)) or pd.api.types.is_datetime64_any_dtype(frame[x]):
        return "temporal"
    if pd.api.types.is_numeric_dtype(frame[x]):
        return "ordinal"
    return "nominal"


def _all_month_ends(frame: pd.DataFrame, x: str) -> bool:
    """Her tarih ayın son günü mü? Dönem sonu etiketli seri (Silver kuralı) ay kutusuna girer.

    Ölçüldü: 2025-01-31 düz zaman ekseninde '2025-02' çizgisinin üstüne düşüyor ve Ocak
    verisi Şubat gibi okunuyordu. Ay kutusu (timeUnit yearmonth) onu Ocak'a koyar. Haftalık
    ya da günlük seride kutu kullanılmaz; noktalar kendi gününde kalır.
    """
    values = frame[x].dropna()
    if values.empty:
        return False
    for v in values:
        d = v.date() if isinstance(v, (datetime, pd.Timestamp)) else v
        if not isinstance(d, date):
            return False
        nxt = d + timedelta(days=1)
        if nxt.month == d.month:
            return False
    return True


def _x_encoding(frame: pd.DataFrame, x: str) -> tuple[dict[str, Any], str]:
    x_type = _x_type(frame, x)
    enc: dict[str, Any] = {"field": safe_field(x), "type": x_type, "title": "dönem" if x_type == "temporal" else x}
    if x_type == "temporal":
        if _all_month_ends(frame, x):
            enc["timeUnit"] = "yearmonth"
            enc["axis"] = {"format": "%Y-%m", "labelAngle": 0}
        else:
            enc["axis"] = {"format": "%Y-%m-%d", "labelAngle": -30}
    return enc, x_type


def _y_axis_title(column: str, intent: ChartIntent) -> str:
    unit = intent.unit_labels.get(column)
    label = intent.labels.get(column, column)
    title = f"{label} ({unit})" if unit else label
    if intent.log_scale:
        title += " [log ölçek]"
    return title


def _y_scale(column: str, intent: ChartIntent) -> dict[str, Any]:
    scale: dict[str, Any] = {}
    if intent.log_scale:
        scale["type"] = "log"      # log'da sıfır tanımsız; etiketle söylenir
    elif column in intent.level_columns:
        scale["zero"] = True       # stok/akım/adet: kesik eksen büyümeyi abartır
    return scale


def _quality_layer(intent: ChartIntent, x_type: str, y_field: str, series_field: str | None,
                   *, x_bin_month: bool = False) -> dict[str, Any]:
    """quality_flag ≠ ok olan gözlemler içi boş kırmızı halka ile işaretlenir."""
    enc: dict[str, Any] = {
        "x": {"field": safe_field(intent.x or ""), "type": x_type, **({"timeUnit": "yearmonth"} if x_bin_month else {})},
        "y": {"field": safe_field(y_field), "type": "quantitative"},
        "tooltip": [{"field": safe_field(intent.quality_column or ""), "type": "nominal", "title": "kalite"}],
    }
    if series_field:
        enc["detail"] = {"field": series_field}
    return {
        "transform": [{"filter": f"datum['{safe_field(intent.quality_column or '')}'] != '{QUALITY_OK}'"}],
        "mark": {"type": "point", "shape": "circle", "size": 120, "color": "#d62728", "filled": False, "strokeWidth": 2},
        "encoding": enc,
    }


def _series_spec(frame: pd.DataFrame, intent: ChartIntent, mark: str) -> dict[str, Any]:
    assert intent.x is not None
    x_enc, x_type = _x_encoding(frame, intent.x)
    columns = [intent.x, *intent.y] + ([intent.quality_column] if intent.quality_column else [])
    data = {"values": table_values(frame, columns)}
    has_bad_quality = bool(intent.quality_column) and bool(
        (frame[intent.quality_column].astype(str) != QUALITY_OK).any()
    )

    spec: dict[str, Any] = {
        "$schema": VEGA_LITE_SCHEMA,
        "title": {"text": chart_title(intent), "subtitle": intent.source_note or None, "anchor": "start"},
        "width": 720,
        "height": 360,
        "data": data,
        "usermeta": {"fields": {safe_field(c): c for c in columns}},
    }
    if not spec["title"]["subtitle"]:
        del spec["title"]["subtitle"]

    if intent.dual_axis and len(intent.y) == 2:
        left, right = intent.y
        layers = []
        for col, color, side in ((left, "#1f77b4", "left"), (right, "#ff7f0e", "right")):
            layers.append({
                "mark": {"type": mark, "color": color, "point": mark == "line"},
                "encoding": {
                    "x": x_enc,
                    "y": {"field": safe_field(col), "type": "quantitative",
                          "title": _y_axis_title(col, intent), "scale": _y_scale(col, intent),
                          "axis": {"orient": side, "titleColor": color}},
                },
            })
        if has_bad_quality:
            layers.append(_quality_layer(intent, x_type, left, None, x_bin_month="timeUnit" in x_enc))
        spec["layer"] = layers
        spec["resolve"] = {"scale": {"y": "independent"}}
        return spec

    if len(intent.y) == 1:
        col = intent.y[0]
        main = {
            "mark": {"type": mark, "point": True} if mark == "line" else {"type": mark},
            "encoding": {
                "x": x_enc,
                "y": {"field": safe_field(col), "type": "quantitative",
                      "title": _y_axis_title(col, intent), "scale": _y_scale(col, intent)},
                "tooltip": [{"field": safe_field(intent.x), "type": x_type, "title": "dönem"},
                            {"field": safe_field(col), "type": "quantitative", "title": intent.labels.get(col, col)}],
            },
        }
        if has_bad_quality:
            spec["layer"] = [main, _quality_layer(intent, x_type, col, None, x_bin_month="timeUnit" in x_enc)]
        else:
            spec.update(main)
        return spec

    # Birden çok seri, tek eksen: uzun biçime katla; birim aynı olmak zorunda (denetçi bakar).
    level = any(c in intent.level_columns for c in intent.y)
    unit = next((intent.unit_labels[c] for c in intent.y if intent.unit_labels.get(c)), None)
    y_title = (f"{FOLD_VALUE} ({unit})" if unit else FOLD_VALUE) + (" [log ölçek]" if intent.log_scale else "")
    scale = {"type": "log"} if intent.log_scale else ({"zero": True} if level else {})
    fold = {"fold": [safe_field(c) for c in intent.y], "as": [FOLD_SERIES, FOLD_VALUE]}
    main = {
        "transform": [fold],
        "mark": {"type": mark, "point": True} if mark == "line" else {"type": mark},
        "encoding": {
            "x": x_enc,
            "y": {"field": FOLD_VALUE, "type": "quantitative", "title": y_title, "scale": scale},
            "color": {"field": FOLD_SERIES, "type": "nominal", "title": "seri"},
            **({"xOffset": {"field": FOLD_SERIES}} if mark == "bar" else {}),
            "tooltip": [{"field": safe_field(intent.x), "type": x_type, "title": "dönem"}, {"field": FOLD_SERIES}, {"field": FOLD_VALUE, "type": "quantitative"}],
        },
    }
    if has_bad_quality:
        bad = _quality_layer(intent, x_type, FOLD_VALUE, FOLD_SERIES, x_bin_month="timeUnit" in x_enc)
        bad["transform"] = [fold, *bad["transform"]]
        spec["layer"] = [main, bad]
    else:
        spec.update(main)
    return spec


def _map_spec(frame: pd.DataFrame, intent: ChartIntent) -> dict[str, Any]:
    """İl haritası: sınırlar belirtime gömülür, değerler normalize il adıyla eşlenir."""
    assert intent.geo is not None and intent.province_column is not None
    (value_col,) = intent.y
    cols = [intent.province_column, value_col] + ([intent.quality_column] if intent.quality_column else [])
    rows = []
    for record in frame[cols].itertuples(index=False, name=None):
        row = {"il": normalize_province(record[0]), "deger": _json_safe(record[1])}
        if intent.quality_column:
            row["kalite"] = _json_safe(record[2])
        rows.append(row)
    features = []
    for f in intent.geo.features:
        props = dict(f.get("properties", {}))
        props["il"] = normalize_province(props.get(intent.geo.name_property, ""))
        features.append({"type": "Feature", "geometry": f.get("geometry"), "properties": props})
    unit = intent.unit_labels.get(value_col)
    legend_title = f"{value_col} ({unit})" if unit else value_col
    fields = ["deger"] + (["kalite"] if intent.quality_column else [])
    tooltip = [{"field": "properties.il", "type": "nominal", "title": "il"},
               {"field": "deger", "type": "quantitative", "title": legend_title}]
    if intent.quality_column:
        tooltip.append({"field": "kalite", "type": "nominal"})
    title: dict[str, Any] = {"text": chart_title(intent), "anchor": "start"}
    if intent.source_note:
        title["subtitle"] = intent.source_note
    return {
        "$schema": VEGA_LITE_SCHEMA,
        "title": title,
        "width": 820,
        "height": 420,
        "data": {"values": {"type": "FeatureCollection", "features": features},
                 "format": {"type": "json", "property": "features"}},
        "transform": [{"lookup": "properties.il",
                       "from": {"data": {"values": rows}, "key": "il", "fields": fields}}],
        "projection": {"type": "mercator"},
        "mark": {"type": "geoshape", "stroke": "#ffffff", "strokeWidth": 0.6},
        "encoding": {
            "color": {"field": "deger", "type": "quantitative", "title": legend_title,
                      "scale": {"scheme": "blues"},
                      "condition": {"test": "!isValid(datum.deger)", "value": "#e0e0e0"}},
            "tooltip": tooltip,
        },
    }


def build_spec(frame: pd.DataFrame, intent: ChartIntent) -> dict[str, Any]:
    """Niyeti belirtime çevirir. Hata değil kural ihlali varsa ValueError: denetçiye kalmasın."""
    if not intent.y:
        raise ValueError("en az bir y kolonu gerekli")
    missing = [c for c in (intent.x, *intent.y, intent.quality_column, intent.province_column) if c and c not in frame.columns]
    if missing:
        raise ValueError(f"tabloda olmayan kolon: {', '.join(missing)}")
    if intent.kind == "map":
        if intent.geo is None or not intent.province_column:
            raise ValueError("harita için il sınırları ve il kolonu gerekli")
        if len(intent.y) != 1:
            raise ValueError("harita tek bir değer kolonu alır")
        return _map_spec(frame, intent)
    if not intent.x:
        raise ValueError("çizgi/çubuk grafik için x kolonu gerekli")
    if intent.dual_axis and len(intent.y) != 2:
        raise ValueError("çift eksen tam iki y kolonu ister")
    return _series_spec(frame, intent, "line" if intent.kind == "line" else "bar")


def spec_json(spec: dict[str, Any]) -> str:
    return json.dumps(spec, ensure_ascii=False, indent=1)


__all__ = ["ChartIntent", "GeoAsset", "build_spec", "chart_title", "normalize_province",
           "period_label", "safe_field", "spec_json", "table_values"]
