"""Deterministik grafik denetçisi: belirtim veridir, kurallar ölçülür (ADR-0032).

İnşacı (`spec.py`) kuralları uygular; denetçi aynı belirtimi bağımsız okuyup sınar.
İkisi aynı dosyada olsaydı inşacının hatası denetçinin de hatası olurdu. Denetçi
geçmezse grafik diske yazılmaz: kesik eksenli bir stok grafiği, yanlış bir sayı kadar
yanıltıcıdır ve jüri onu tabloda değil grafikte görür.

Kurallar:
  L1 level_zero        stok/akım/adet serisi lineer eksende sıfırdan başlar
  L2 bar_zero          çubuk her zaman sıfırdan başlar
  L3 dual_axis_asked   ikinci y ekseni yalnız kullanıcı istediyse
  L4 log_labelled      log ölçek eksen başlığında yazılı
  L5 title_unit_period başlıkta birim(ler) ve dönem var
  L6 quality_marked    quality_flag ≠ ok gözlem varsa işaretli bir katman var
  L7 no_silent_subset  belirtimdeki satır sayısı tablodaki satır sayısına eşit
                       (haritada: her veri satırı bir il sınırına eşleşti)
  L8 axis_unit         y ekseni başlığında birim var (birim biliniyorsa)
  L9 single_unit_axis  tek eksende birden çok seri varsa birimleri aynı
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .spec import FOLD_VALUE, QUALITY_OK, ChartIntent, normalize_province, safe_field


@dataclass(frozen=True)
class RuleResult:
    rule: str
    passed: bool
    detail: str
    applicable: bool = True


@dataclass
class LintReport:
    results: list[RuleResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.passed for r in self.results if r.applicable)

    @property
    def failures(self) -> list[RuleResult]:
        return [r for r in self.results if r.applicable and not r.passed]

    def render(self) -> str:
        applicable = [r for r in self.results if r.applicable]
        passed = sum(1 for r in applicable if r.passed)
        head = f"denetim: {passed}/{len(applicable)} kural geçti"
        lines = [head] + [
            f"  {'✓' if r.passed else '✗'} {r.rule}: {r.detail}" for r in applicable
        ]
        skipped = [r.rule for r in self.results if not r.applicable]
        if skipped:
            lines.append(f"  – uygulanmadı: {', '.join(skipped)}")
        return "\n".join(lines)


def _units(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Katmanlı ya da tek belirtimdeki tüm mark+encoding birimleri."""
    if "layer" in spec:
        return [u for layer in spec["layer"] for u in _units(layer)]
    return [spec] if "encoding" in spec else []


def _y_encodings(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return [u["encoding"]["y"] for u in _units(spec) if "y" in u.get("encoding", {})]


def _mark_type(unit: dict[str, Any]) -> str:
    mark = unit.get("mark")
    return mark["type"] if isinstance(mark, dict) else str(mark)


def _title_text(spec: dict[str, Any]) -> str:
    title = spec.get("title")
    return title["text"] if isinstance(title, dict) else str(title or "")


def _y_columns_of(unit: dict[str, Any], intent: ChartIntent, fields: dict[str, str]) -> list[str]:
    y = unit.get("encoding", {}).get("y", {})
    field_name = y.get("field")
    if field_name == FOLD_VALUE:
        return list(intent.y)
    if not field_name:
        return []
    return [fields.get(field_name, field_name)]   # güvenli ad → tablodaki asıl ad


def lint_spec(spec: dict[str, Any], frame: pd.DataFrame, intent: ChartIntent) -> LintReport:
    report = LintReport()
    add = report.results.append
    units = _units(spec)
    fields: dict[str, str] = spec.get("usermeta", {}).get("fields", {})
    title = _title_text(spec)
    is_map = intent.kind == "map"

    # L1 level_zero
    if is_map:
        add(RuleResult("level_zero", True, "harita", applicable=False))
    else:
        problems = []
        for unit in units:
            if _mark_type(unit) == "point":
                continue  # kalite katmanı
            y = unit["encoding"].get("y", {})
            for col in _y_columns_of(unit, intent, fields):
                if col in intent.level_columns and y.get("scale", {}).get("type") != "log":
                    if y.get("scale", {}).get("zero") is not True:
                        problems.append(col)
        add(RuleResult("level_zero", not problems,
                       "stok/akım serileri sıfırdan başlıyor" if not problems else f"kesik eksen: {', '.join(problems)}"))

    # L2 bar_zero
    bars = [u for u in units if _mark_type(u) == "bar"]
    if bars:
        bad = [u for u in bars if u["encoding"].get("y", {}).get("scale", {}).get("zero") is not True
               and u["encoding"].get("y", {}).get("scale", {}).get("type") != "log"]
        add(RuleResult("bar_zero", not bad, "çubuklar sıfırdan başlıyor" if not bad else "çubuk ekseni kesik"))
    else:
        add(RuleResult("bar_zero", True, "çubuk yok", applicable=False))

    # L3 dual_axis_asked
    independent = spec.get("resolve", {}).get("scale", {}).get("y") == "independent"
    add(RuleResult("dual_axis_asked", (not independent) or intent.dual_axis,
                   "ikinci eksen yok" if not independent else
                   ("ikinci eksen kullanıcı isteğiyle" if intent.dual_axis else "ikinci eksen istenmeden eklenmiş")))

    # L4 log_labelled
    logs = [y for y in _y_encodings(spec) if y.get("scale", {}).get("type") == "log"]
    if logs:
        unlabelled = [y for y in logs if "log" not in str(y.get("title", "")).lower()]
        add(RuleResult("log_labelled", not unlabelled, "log ölçek eksen başlığında yazılı" if not unlabelled else "log ölçek etiketsiz"))
    else:
        add(RuleResult("log_labelled", True, "log ölçek yok", applicable=False))

    # L5 title_unit_period
    missing = [u for u in intent.units_in_title if u not in title]
    if intent.period and intent.period not in title:
        missing.append(f"dönem {intent.period}")
    if not intent.units_in_title:
        missing.append("birim bilinmiyor")
    add(RuleResult("title_unit_period", not missing,
                   f"başlık: {title}" if not missing else f"başlıkta eksik: {', '.join(missing)}"))

    # L6 quality_marked
    if intent.quality_column and intent.quality_column in frame.columns:
        n_bad = int((frame[intent.quality_column].astype(str) != QUALITY_OK).sum())
        if n_bad:
            if is_map:
                marked = any("kalite" in str(t) for t in spec.get("encoding", {}).get("tooltip", []))
            else:
                safe_q = safe_field(intent.quality_column)
                marked = any(
                    any(safe_q in str(t.get("filter", "")) for t in u.get("transform", []))
                    for u in units
                )
            add(RuleResult("quality_marked", marked,
                           f"{n_bad} uyarılı/eksik gözlem işaretli" if marked else f"{n_bad} uyarılı gözlem işaretsiz"))
        else:
            add(RuleResult("quality_marked", True, "tüm gözlemler ok"))
    else:
        add(RuleResult("quality_marked", True, "kalite kolonu yok", applicable=False))

    # L7 no_silent_subset
    if is_map:
        geo_names = set(intent.geo.names()) if intent.geo else set()
        rows = frame[intent.province_column].map(normalize_province) if intent.province_column else pd.Series(dtype=str)
        unmatched = sorted(set(rows) - geo_names)
        dupes = sorted(rows[rows.duplicated()].unique().tolist())
        ok = not unmatched and not dupes
        detail = f"{len(rows)} il eşleşti" if ok else (
            (f"sınırı bulunamayan il: {', '.join(unmatched[:8])}" if unmatched else "") +
            (f"; aynı il birden çok satırda: {', '.join(dupes[:8])}" if dupes else ""))
        add(RuleResult("no_silent_subset", ok, detail.strip("; ")))
    else:
        n = len(spec.get("data", {}).get("values", []))
        add(RuleResult("no_silent_subset", n == len(frame),
                       f"{n} satırın {n}'i çizildi" if n == len(frame) else f"tabloda {len(frame)} satır, grafikte {n}"))

    # L8 axis_unit
    if is_map:
        legend = str(spec.get("encoding", {}).get("color", {}).get("title", ""))
        unit = intent.unit_labels.get(intent.y[0]) if intent.y else None
        add(RuleResult("axis_unit", (unit is None) or (unit in legend),
                       f"lejant: {legend}" if unit is None or unit in legend else "lejantta birim yok"))
    else:
        bad = []
        for unit in units:
            if _mark_type(unit) == "point":
                continue
            y = unit["encoding"].get("y", {})
            for col in _y_columns_of(unit, intent, fields):
                u = intent.unit_labels.get(col)
                if u and u not in str(y.get("title", "")):
                    bad.append(col)
        add(RuleResult("axis_unit", not bad, "y ekseninde birim var" if not bad else f"eksende birim yok: {', '.join(bad)}"))

    # L9 single_unit_axis
    if not is_map and len(intent.y) > 1 and not intent.dual_axis:
        labels = {intent.unit_labels.get(c) for c in intent.y}
        add(RuleResult("single_unit_axis", len(labels) == 1,
                       "seriler aynı birimde" if len(labels) == 1 else f"aynı eksende farklı birimler: {sorted(str(l) for l in labels)}"))
    else:
        add(RuleResult("single_unit_axis", True, "tek seri ya da ayrı eksen", applicable=False))

    return report


__all__ = ["LintReport", "RuleResult", "lint_spec"]
