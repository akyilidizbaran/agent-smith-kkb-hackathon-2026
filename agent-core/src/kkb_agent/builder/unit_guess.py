"""Birim tahmini — belgede birim yazmıyorsa "sor" yerine "şu olabilir, doğru mu?" (14 Eylül; Büşra)

ADR-0030 doğru bir yerden başlıyor: birim veriden çıkarılamaz, tahminle yazılmaz. Ama
"birim nedir?" diye boş soru sormak kullanıcıyı da bilmediği bir şeyle baş başa bırakır.
Bu modül yazmaz; yalnız kanıtlı bir aday üretir, kullanıcı onaylar. Üç ipucu, güçlüden zayıfa:

  1. metin   — kolon adları, dosya adı, belge notu: "(bin TL)", "milyar", "%", "kg", "adet"
  2. katalog — çapraz kontrol ölçeği: katalogdaki aynı seri "milyon TL" ve oran ≈ 1000
               ise dosya "milyar TL" (ya da tersi)
  3. aralık  — 0–100 arası ondalıklı → yüzde; küçük tam sayılar → adet (zayıf)

LLM yok. Her tahmin `Evidence` kalıbıyla (değer, sebep, güven) döner.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable

from .crosscheck import CrossCheck

_TEXT_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"milyar\s*tl|bn\s*tl|try_bn", re.I), "milyar TL"),
    (re.compile(r"milyon\s*tl|mn\s*tl|try_mn", re.I), "milyon TL"),
    (re.compile(r"\bbin\s*tl|thousand\s*tl|try_th|\(\s*000\s*\)|\b000\s*tl", re.I), "bin TL"),
    (re.compile(r"milyon\s*(usd|\$|dolar)", re.I), "milyon USD"),
    (re.compile(r"\b(usd|\$|dolar)\b", re.I), "USD"),
    (re.compile(r"\b(eur|€|euro)\b", re.I), "EUR"),
    (re.compile(r"%|yüzde|yuzde|pct|percent|\boran\b|\bfaiz", re.I), "yüzde"),
    (re.compile(r"endeks|index", re.I), "endeks"),
    (re.compile(r"\badet\b|count|sayısı|sayisi", re.I), "adet"),
    (re.compile(r"\bkg\b|kilogram", re.I), "kg"),
    (re.compile(r"\bton\b", re.I), "ton"),
    (re.compile(r"\bgram\b|\bgr\b", re.I), "gram"),
    (re.compile(r"\btl\b|\btry\b|türk lirası|turk lirasi", re.I), "TL"),     # en son: "milyon TL" yukarıda yakalanır
)

_TL_LADDER = ("TL", "bin TL", "milyon TL", "milyar TL")


@dataclass(frozen=True)
class UnitGuess:
    unit: str
    confidence: str      # "strong" | "weak"
    reason: str

    def line(self) -> str:
        return f"birim TAHMİNİ: '{self.unit}' [{self.confidence}] — {self.reason}"


def _from_text(texts: Iterable[str]) -> UnitGuess | None:
    blob = " ".join(t for t in texts if t)
    for pat, unit in _TEXT_HINTS:
        m = pat.search(blob)
        if m:
            return UnitGuess(unit, "strong", f"metinde '{m.group(0)}' geçiyor")
    return None


def _from_crosscheck(cc: CrossCheck | None) -> UnitGuess | None:
    if cc is None or cc.scale is None or cc.agree_share is None or cc.agree_share < 0.8 or not cc.ref_unit:
        return None
    if abs(cc.scale - 1.0) < 1e-9:
        return UnitGuess(cc.ref_unit, "strong", f"katalogdaki {cc.name} serisiyle aynı büyüklükte (oran ≈ 1)")
    if cc.ref_unit in _TL_LADDER:
        idx = _TL_LADDER.index(cc.ref_unit)
        step = round(math.log10(cc.scale) / 3)   # katalog/dosya = 1000 → dosya bir basamak BÜYÜK birimde
        target = idx + step
        if 0 <= target < len(_TL_LADDER):
            return UnitGuess(_TL_LADDER[target], "weak",
                             f"katalogdaki {cc.name} serisi '{cc.ref_unit}', değerler ×{cc.scale:g} ölçekle örtüşüyor")
    return UnitGuess(f"{cc.ref_unit} × {1 / cc.scale:g}", "weak",
                     f"katalogdaki {cc.name} serisiyle ölçek farkı ×{cc.scale:g}")


def _from_range(values: Iterable[float]) -> UnitGuess | None:
    vals = [v for v in values if v is not None and math.isfinite(v)]
    if len(vals) < 3:
        return None
    lo, hi = min(vals), max(vals)
    if 0 <= lo and hi <= 100 and any(v != int(v) for v in vals):
        return UnitGuess("yüzde", "weak", f"tüm değerler 0–100 arasında ve ondalıklı ({lo:g}–{hi:g})")
    if all(v == int(v) for v in vals) and hi < 100_000:
        return UnitGuess("adet", "weak", f"tüm değerler tam sayı ve küçük (en çok {hi:g})")
    return None


def guess_unit(
    *, texts: Iterable[str], crosscheck: CrossCheck | None, values: Iterable[float],
) -> UnitGuess | None:
    """Sırayla: metin → katalog ölçeği → değer aralığı. İlk bulunan döner."""
    return _from_text(texts) or _from_crosscheck(crosscheck) or _from_range(values)


__all__ = ["UnitGuess", "guess_unit"]
