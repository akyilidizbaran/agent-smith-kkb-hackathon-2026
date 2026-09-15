"""Çapraz kontrol — gelen dosya, katalogdaki aynı seriyle örtüşen dönemlerde uyuşuyor mu?
(V3 §3.9-E, 14 Eylül; Büşra)

Dışarıdan gelen bir sayının doğru olup olmadığını sistem bilemez; ama katalogda aynı
kavramın küratörlü bir serisi varsa iki kaynağı örtüşen tarihlerde YAN YANA koyabilir.
Sonuç cevaba tek satır olarak girer, hiçbir şeyi engellemez:

  "örtüşüyor"            oran ≈ 1 ve noktaların çoğu %1 içinde
  "birim farkı (×1000)"  oran ≈ 10^k ve noktalar ölçekten sonra %1 içinde → birim ipucu
  "ÇELİŞİYOR"            noktalar ölçekten sonra bile dağınık → kullanıcıya söylenir

Yalnız TEK bir katalog adayı varsa ve frekanslar aynıysa karşılaştırılır; aksi hâlde
"karşılaştırılamadı: <sebep>" yazılır. Yanlış alarm, hiç alarm vermemekten kötüdür
(haftalık ↔ aylık, bin ↔ milyon, takipteki ↔ toplam: hepsi "çelişki" gibi görünür).
LLM yok; bir SQL okuması (adaptörün `series_sql`'i, salt okunur).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any, Iterable

import pandas as pd

from .profile import MappingProposal, SemanticsProposal, _parse_number, parse_date

TOLERANCE = 0.01          # %1: yayın revizyonları ve yuvarlama bunun altında kalır
_SCALES = (1e-6, 1e-3, 1.0, 1e3, 1e6)


@dataclass(frozen=True)
class CrossCheck:
    dataset_id: str
    name: str
    ref_unit: str | None
    overlap: int
    ratio: float | None            # medyan(katalog / dosya), örtüşen noktalarda
    scale: float | None            # ratio'ya en yakın 10^k (1, 1000, 0.001 …)
    agree_share: float | None      # ölçekten sonra %1 içinde kalan nokta payı
    verdict: str                   # "örtüşüyor" | "birim farkı" | "ÇELİŞİYOR" | "karşılaştırılamadı"
    detail: str
    worst: tuple[tuple[str, float, float], ...] = ()   # (tarih, dosya, katalog) en büyük 3 sapma

    @property
    def same_unit(self) -> bool:
        return self.verdict == "örtüşüyor"

    def lines(self) -> list[str]:
        head = f"çapraz kontrol ({self.name}): {self.verdict} — {self.detail}"
        if self.worst and self.verdict == "ÇELİŞİYOR":
            head += " | en büyük sapmalar: " + "; ".join(f"{d}: dosya {f:g}, katalog {r:g}" for d, f, r in self.worst)
        return [head]


def file_points(frame: pd.DataFrame, mapping: MappingProposal) -> dict[date, float]:
    """Dosyanın (tarih → değer) noktaları, önerinin dilbilgisiyle; okunamayan satır atlanır."""
    out: dict[date, float] = {}
    dcol, vcol = mapping.observation_date_column, mapping.value_column
    if dcol not in frame.columns or vcol not in frame.columns:
        return out
    for raw_d, raw_v in zip(frame[dcol].astype(str), frame[vcol].astype(str)):
        try:
            d = parse_date(raw_d, mapping.date_format)
            v = _parse_number(raw_v, mapping.decimal_separator, mapping.thousands_separator)
        except (ValueError, TypeError):
            continue
        if v is not None:
            out[d] = v
    return out


def reference_points(lakehouse: Any, spec: Any) -> tuple[dict[date, float], str | None]:
    """Katalog serisinin noktaları ve birim etiketi; okunamazsa (boş, None)."""
    columns = list(getattr(spec, "columns", ()) or ())
    measure = next((c for c in columns if str(getattr(getattr(c, "role", ""), "value", getattr(c, "role", ""))) == "measure"), None)
    if measure is None:
        return {}, None
    key = getattr(spec, "time_column", None) or "observation_date"
    try:
        sql = lakehouse.series_sql(spec.dataset_id, key_column=key, value_column=measure.name)
        result = lakehouse.execute_sql(sql, max_rows=5000)
        data = result.data
    except Exception:  # adaptör hatası çapraz kontrolü düşürür, ingest'i değil
        return {}, getattr(measure, "unit", None)
    out: dict[date, float] = {}
    if data is None or data.empty or len(data.columns) < 2:
        return out, getattr(measure, "unit", None)
    dates = pd.to_datetime(data.iloc[:, 0], errors="coerce")
    values = pd.to_numeric(data.iloc[:, 1], errors="coerce")
    for d, v in zip(dates, values):
        if pd.isna(d) or pd.isna(v):
            continue
        out[d.date()] = float(v)
    return out, getattr(measure, "unit", None)


def _period_key(d: date, frequency: str) -> tuple:
    if frequency == "monthly":
        return (d.year, d.month)
    if frequency == "quarterly":
        return (d.year, (d.month - 1) // 3)
    if frequency == "yearly":
        return (d.year,)
    return (d,)  # günlük/haftalık: tam tarih


def compare(
    file_pts: dict[date, float], ref_pts: dict[date, float], *, frequency: str,
    dataset_id: str, name: str, ref_unit: str | None, tolerance: float = TOLERANCE,
) -> CrossCheck:
    """Örtüşen dönemleri (ay/çeyrek/yıl anahtarıyla) eşle, ölçek bul, uyuşmayı ölç."""
    f_by = {_period_key(d, frequency): (d, v) for d, v in file_pts.items()}
    r_by = {_period_key(d, frequency): v for d, v in ref_pts.items()}
    keys = sorted(set(f_by) & set(r_by))
    pairs = [(f_by[k][0], f_by[k][1], r_by[k]) for k in keys if f_by[k][1] not in (0, 0.0)]
    if not pairs:
        return CrossCheck(dataset_id, name, ref_unit, 0, None, None, None, "karşılaştırılamadı",
                          "örtüşen dönem yok")
    ratios = [r / f for _, f, r in pairs]
    ratio = median(ratios)
    if ratio <= 0 or not math.isfinite(ratio):
        return CrossCheck(dataset_id, name, ref_unit, len(pairs), ratio, None, None, "karşılaştırılamadı",
                          "işaretler uyuşmuyor")
    scale = min(_SCALES, key=lambda s: abs(math.log10(ratio) - math.log10(s)))
    agree = sum(1 for rr in ratios if abs(rr / scale - 1) <= tolerance) / len(pairs)
    worst = sorted(pairs, key=lambda p: -abs(p[2] / (p[1] * scale) - 1))[:3]
    worst_t = tuple((d.isoformat(), f, r) for d, f, r in worst)
    n = len(pairs)
    if agree >= 0.8 and abs(scale - 1.0) < 1e-9 and abs(ratio - 1) <= tolerance:
        return CrossCheck(dataset_id, name, ref_unit, n, ratio, scale, agree, "örtüşüyor",
                          f"{n} örtüşen dönemin %{agree * 100:.0f}'i %{tolerance * 100:.0f} içinde", worst_t)
    if agree >= 0.8:
        return CrossCheck(dataset_id, name, ref_unit, n, ratio, scale, agree, "birim farkı",
                          f"değerler ×{scale:g} ölçekle örtüşüyor (%{agree * 100:.0f}); katalog birimi "
                          f"{ref_unit or 'bilinmiyor'} ise dosya {'daha büyük' if scale < 1 else 'daha küçük'} birimde", worst_t)
    return CrossCheck(dataset_id, name, ref_unit, n, ratio, scale, agree, "ÇELİŞİYOR",
                      f"{n} örtüşen dönemin yalnız %{agree * 100:.0f}'i ölçekten sonra %{tolerance * 100:.0f} içinde",
                      worst_t)


def cross_check(
    lakehouse: Any, specs: Iterable[Any], candidate_ids: Iterable[str],
    frame: pd.DataFrame, mapping: MappingProposal | None, semantics: SemanticsProposal | None,
) -> CrossCheck | None:
    """Tek katalog adayı + aynı frekans → karşılaştır; aksi hâlde sebebiyle 'karşılaştırılamadı'."""
    ids = [i for i in dict.fromkeys(candidate_ids) if i]
    if not ids or mapping is None or semantics is None:
        return None
    if len(ids) > 1:
        return CrossCheck(ids[0], ", ".join(ids[:3]), None, 0, None, None, None, "karşılaştırılamadı",
                          f"katalogda {len(ids)} aday var, hangisiyle karşılaştırılacağı belirsiz")
    spec = next((s for s in specs if getattr(s, "dataset_id", None) == ids[0]), None)
    if spec is None:
        return None
    ref_freq = str(getattr(getattr(spec, "frequency", ""), "value", getattr(spec, "frequency", "")))
    if ref_freq and semantics.frequency and ref_freq != semantics.frequency:
        return CrossCheck(spec.dataset_id, spec.name, None, 0, None, None, None, "karşılaştırılamadı",
                          f"frekans farklı: dosya {semantics.frequency}, katalog {ref_freq}")
    ref_pts, ref_unit = reference_points(lakehouse, spec)
    if not ref_pts:
        return CrossCheck(spec.dataset_id, spec.name, ref_unit, 0, None, None, None, "karşılaştırılamadı",
                          "katalog serisi okunamadı ya da boş")
    return compare(file_points(frame, mapping), ref_pts, frequency=semantics.frequency,
                   dataset_id=spec.dataset_id, name=spec.name, ref_unit=ref_unit)


__all__ = ["CrossCheck", "compare", "cross_check", "file_points", "reference_points"]
