"""İddia–hücre ve aralık beyanı denetimi — sayı DOĞRU DÖNEMLE mi yazılmış? (G5/G6; V3 §3.9; Büşra, 16 Eyl)

`grounding_check` "cevaptaki sayı bir araç çıktısında var mı" der; bir sayı tabloda VARSA ama başka bir dönemin
değeriyse geçer. Ölçüldü (14 Eyl UEB A06, iki koşuda bir): araç kartı ilk 10 satırı gösterdi, model Ekim değerini
"Aralık 2025" diye yazdı; grounding OK dedi. B01: cevap "veri kapsamı 2024-01 → 2024-10" dedi, tablo 2024-12'ye
kadardı. Bu modül iki deterministik denetim ekler; ikisi de saf fonksiyon, girdi cevap metni + DataFrame havuzu:

  claim_cell   satırda (dönem, sayı) çifti varsa: sayı havuzda hangi dönemlerde var? İddia edilen dönem onlardan
               biri değilse "yanlış hücre". Sayı hiç yoksa karışılmaz (grounding'in işi: türetilmiş sayı olabilir).
  range_claim  "kapsam/veri/dönem … 2024-01 → 2024-10" ya da "Ocak–Ekim 2024" beyanı havuzdaki tabloların gerçek
               aralığıyla uyuşmuyorsa bayrak.

Yanlış pozitif kuralları (ölçüldü, çevrimdışı G5 ilk sürümü 5 yanlış pozitif verdi → 0):
  - sayı satırdaki EN YAKIN (önce solundaki) dönemle eşlenir, ilk dönemle değil;
  - düz yazıda yalnız tek dönem + tek sayı taşıyan satırda karar verilir (A15/D05: "Ocak'ta X, Aralık'ta Y");
  - tablo satırında (| ile başlayan) her sayı kendi solundaki dönemle eşlenir;
  - aralık beyanı yalnız kapsam sözcüğü taşıyan satırda aranır (kapsam/veri/tablo/dönem/aralık).
Ne yapılacağına harness karar verir: bir kez geri gönderim, sonra deterministik not.
"""

from __future__ import annotations

import re
import warnings
from typing import Iterable

import pandas as pd

from .grounding import _NUM_RE, _ascii_minus, numbers_in

MONTHS = {"ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5, "haziran": 6, "temmuz": 7,
          "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9, "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12}
_MONTH = r"(ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|eylül|eylul|ekim|kasım|kasim|aralık|aralik)"
#: "Aralık 2025", "2025 Aralık", "Aralık'ta 2025" (ay + yıl yan yana) ya da "2025-12".
_PERIOD = re.compile(
    rf"\b{_MONTH}(?:'?[a-zçğıöşü]{{0,4}})?\s+(20\d{{2}})\b|\b(20\d{{2}})\s+{_MONTH}\b|\b(20\d{{2}})-(0[1-9]|1[0-2])\b", re.I)
_RANGE_ISO = re.compile(r"(20\d{2})-(0[1-9]|1[0-2])\s*(?:→|->|–|—|-|ile|'?den|'?dan|to)\s*(20\d{2})-(0[1-9]|1[0-2])", re.I)
_RANGE_TR = re.compile(rf"{_MONTH}\s*(20\d{{2}})?\s*(?:→|->|–|—|-|ile)\s*{_MONTH}\s+(20\d{{2}})", re.I)
_RANGE_CUE = re.compile(r"kapsa|\bveri|tablo|dönem|donem|aralı|arali", re.I)


def _to_dt(s: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.to_datetime(s, errors="coerce")


def _date_column(frame: pd.DataFrame) -> str | None:
    """≥%80 tarihe ayrışan tarih kolonu (sayısal kolonlar denenmez: 2025 gibi yıl sayıları tarih sanılmasın).

    Birden çok tarih kolonu varsa dönemin ETİKETİ olan seçilir: Gold tabloları `period_start` + `period_end` taşır ve
    değer dönemin sonuna aittir ("2025Q1" = 2025-03). Ölçüldü (benchmark P04, 22 Eyl): ilk kolon (`period_start`)
    alınınca modelin doğru "2025-03" etiketi "tabloda 2025-01 döneminde" diye yanlış çelişki notu aldı."""
    found: list[str] = []
    for c in frame.columns:
        s = frame[c]
        if pd.api.types.is_datetime64_any_dtype(s):
            found.append(str(c)); continue
        if pd.api.types.is_numeric_dtype(s) or s.dropna().empty:
            continue
        if float(_to_dt(s).notna().mean()) >= 0.8:
            found.append(str(c))
    if not found:
        return None
    for c in found:
        if re.search(r"end|son|observation_date|tarih|donem|dönem", c, re.I) and not re.search(r"start|başlangıç|baslangic", c, re.I):
            return c
    return found[0]


def _periods_in(line: str) -> list[tuple[int, int, int]]:
    out = []
    for m in _PERIOD.finditer(line):
        if m.group(1):
            out.append((m.start(), int(m.group(2)), MONTHS[m.group(1).casefold()]))
        elif m.group(3):
            out.append((m.start(), int(m.group(3)), MONTHS[m.group(4).casefold()]))
        else:
            out.append((m.start(), int(m.group(5)), int(m.group(6))))
    return out


def _index(frames: Iterable[pd.DataFrame]) -> list[dict[tuple[int, int], set[float]]]:
    """Her tablo için (yıl, ay) → o dönem satırlarındaki sayısal değerler."""
    out = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        dcol = _date_column(frame)
        if dcol is None:
            continue
        dates = _to_dt(frame[dcol])
        by: dict[tuple[int, int], set[float]] = {}
        num_cols = [c for c in frame.columns if str(c) != dcol]
        for i, d in enumerate(dates):
            if pd.isna(d):
                continue
            key = (int(d.year), int(d.month))
            vals = by.setdefault(key, set())
            for c in num_cols:
                v = frame[c].iloc[i]
                if isinstance(v, (int, float)) and not isinstance(v, bool) and not pd.isna(v):
                    vals.add(float(v))
                elif isinstance(v, str):
                    nums = numbers_in(v)
                    if len(nums) == 1:
                        vals.add(nums[0])
        if by:
            out.append(by)
    return out


def claim_cell(answer: str, frames: Iterable[pd.DataFrame], *, min_value: float = 1000.0, tolerance: float = 0.5) -> list[str]:
    """Cevaptaki (dönem, sayı) çiftleri havuzdaki tablolarla çelişiyorsa bayrak listesi."""
    index = _index(frames)
    if not index:
        return []
    out: list[str] = []
    for line in (answer or "").splitlines():
        periods = _periods_in(line)
        if not periods:
            continue
        is_row = line.strip().startswith("|")
        nums = []
        for m in _NUM_RE.finditer(_ascii_minus(line)):
            vals = numbers_in(m.group(0))
            if not vals:
                continue
            v = vals[0]
            if abs(v) < min_value or (1900 <= v <= 2100 and v.is_integer()):
                continue
            nums.append((m.start(), m.group(0), v))
        if not nums:
            continue
        if not is_row and (len(periods) != 1 or len(nums) != 1):
            continue
        for pos, raw, v in nums:
            left = [p for p in periods if p[0] < pos]
            _, y, mo = left[-1] if left else min(periods, key=lambda p: abs(p[0] - pos))
            found_at: set[tuple[int, int]] = set()
            claimed_ok = False
            for by in index:
                for key, vals in by.items():
                    if any(abs(v - x) <= tolerance for x in vals):
                        found_at.add(key)
                        if key == (y, mo):
                            claimed_ok = True
            if not found_at or claimed_ok:
                continue
            where = ", ".join(f"{a}-{b:02d}" for a, b in sorted(found_at)[:3])
            out.append(f"'{raw}' satırda {y}-{mo:02d} ile yan yana; tabloda bu değer {where} döneminde")
    return out


def range_claim(answer: str, frames: Iterable[pd.DataFrame]) -> list[str]:
    """Kapsam beyanı (ISO ya da ay adlarıyla aralık) havuzdaki hiçbir tablonun gerçek aralığıyla uyuşmuyorsa bayrak."""
    spans: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        dcol = _date_column(frame)
        if dcol is None:
            continue
        dates = _to_dt(frame[dcol]).dropna()
        if dates.empty:
            continue
        lo, hi = dates.min(), dates.max()
        spans.append(((int(lo.year), int(lo.month)), (int(hi.year), int(hi.month))))
    if not spans:
        return []
    out: list[str] = []
    for line in (answer or "").splitlines():
        if not _RANGE_CUE.search(line):
            continue
        for m in _RANGE_ISO.finditer(line):
            a, b = (int(m.group(1)), int(m.group(2))), (int(m.group(3)), int(m.group(4)))
            if not any(a == lo and b == hi for lo, hi in spans):
                out.append(f"aralık beyanı '{m.group(0)}' ≠ tablo " + " / ".join(f"{lo[0]}-{lo[1]:02d}→{hi[0]}-{hi[1]:02d}" for lo, hi in spans[:2]))
        for m in _RANGE_TR.finditer(line):
            b_y, b_m = int(m.group(4)), MONTHS[m.group(3).casefold()]
            a_m = MONTHS[m.group(1).casefold()]
            a_y = int(m.group(2)) if m.group(2) else b_y
            a, b = (a_y, a_m), (b_y, b_m)
            if not any(a == lo and b == hi for lo, hi in spans):
                out.append(f"aralık beyanı '{m.group(0)}' ≠ tablo " + " / ".join(f"{lo[0]}-{lo[1]:02d}→{hi[0]}-{hi[1]:02d}" for lo, hi in spans[:2]))
    return list(dict.fromkeys(out))


__all__ = ["claim_cell", "range_claim"]
