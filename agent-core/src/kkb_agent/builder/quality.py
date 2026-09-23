"""Tablo kalitesi — veri analiz türünü taşıyor mu? (V3 §3.9; Büşra, 15 Eyl)

Uygunluk kapısı (core/fitness) "doğru veri mi" sorusuna bakar; bu modül "doğru veri, ama sağlam mı"
sorusuna: eksik dönem, mükerrer dönem, tarih olmayan satır (toplam/dipnot), kısmi yıl, küçük örneklem,
birim beyanı yokluğu, etiket-değer makullüğü, oran/yüzde belirsizliği. Hiçbirini engellemez: bayrak
üretir, kart "UYARI:" satırı yazar, model uyarıyı sayılardan ÖNCE söyler (agent kuralı).

Ölçüldü (14 Eyl UEB, çevrimdışı G2, docs/experiments/ueb_after_offline_2026-09-14.json): B04/B05/B07/
B08/B10/B12 vakalarında doğru bayrak, D kontrollerinde 0 yanlış pozitif — "tarih+değer kolonu bulunamadı"
yanlış pozitifleri (yıllık kolon, toplam satırı) toleranslı eşlemeyle kapatıldıktan sonra.

LLM yok, ağ yok: saf fonksiyon.
"""

from __future__ import annotations

import re
import warnings

import pandas as pd

from ..core.fitness import DataSignature, _YEAR

_TREND = re.compile(r"trend|yıllık|yillik|büyüme|buyume|değişim|degisim|seyir|nasıl", re.I)
_UNIT_ASK = re.compile(r"milyon|milyar|bin tl|birim|kaç tl|ne kadar", re.I)
_RATE_NAME = re.compile(r"faiz|oran|rate|yüzde|pct", re.I)
_RATIO_NAME = re.compile(r"oran|ratio", re.I)
_PCT_ASK = re.compile(r"yüzde|%", re.I)
#: Ölçek sözcükleri (soru ve veri adı/başlığı): "bin" ≠ "milyon" ise ×1000 hata riski. Ölçüldü (UEB B06, after3): dosya adı
#: "bin_tl", soru "milyon TL olarak" — model dosyayı TL sanıp 10⁶'ya böldü; "birim beyanı yok" haklı olarak susmuştu (ipucu var).
_SCALE_RE = re.compile(r"\b(bin|th|thousand|milyon|mn|million|milyar|bn|billion)\b", re.I)
_SCALE = {"bin": "bin", "th": "bin", "thousand": "bin", "milyon": "milyon", "mn": "milyon", "million": "milyon",
          "milyar": "milyar", "bn": "milyar", "billion": "milyar"}


def _scale_of(text: str) -> str | None:
    m = _SCALE_RE.search(text or "")
    return _SCALE[m.group(1).lower()] if m else None


def _to_dt(s: pd.Series) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(s, errors="coerce")
    if len(parsed) and parsed.isna().all():
        # Dönem + tarih aralığı hücreleri ("2021/01 (04.01.21-08.01.21)"): aralığın bitiş günü (23 Eyl, dış rapor haftalık).
        from ..builder.profile import range_end_date
        ends = s.map(lambda v: range_end_date(str(v)) if v is not None else None)
        if ends.notna().any():
            return pd.to_datetime(ends, errors="coerce")
    return parsed


def table_quality(frame: pd.DataFrame, sig: DataSignature, question: str = "") -> list[str]:
    """Bayrak listesi (boş liste = uyarı yok). Yıl kolonlu (yıllık) tabloda boşluk/mükerrer denetimi anlamsızdır."""
    flags: list[str] = []
    dcol = sig.date_column
    if dcol is None or dcol not in frame.columns:
        if sig.frequency != "yearly" and len(frame.columns) >= 2:
            flags.append("tarih+değer kolonu bulunamadı (okunamayan/yanlış sayfa ya da tarih biçimi)")
        return flags
    if sig.frequency == "yearly":
        return flags
    dates = _to_dt(frame[dcol])
    bad = frame[dates.isna()]
    if len(bad):
        vals = [str(v) for v in bad[dcol].head(3)]
        flags.append(f"tarih kolonunda tarih olmayan satır: {vals} (toplam/dipnot satırı olabilir; sayıya katılmamalı)")
    good = dates.dropna().sort_values()
    if len(good) >= 3:
        gaps = good.diff().dt.days.dropna()
        med = float(gaps.median()) if len(gaps) else 0.0
        if 0 < med <= 31 and (gaps > 45).any():
            missing = int(round(((gaps[gaps > 45] / 30.4).round() - 1).sum()))
            flags.append(f"eksik dönem: ardışık tarih farkı frekansı aşıyor ({missing} ay boşluk); değişim/ortalama hesabı boşluğu görmez")
        dup = good[good.duplicated()].dt.strftime("%Y-%m").unique().tolist()
        if dup:
            flags.append(f"mükerrer dönem: {dup}; toplam/ortalama iki kez sayar")
    yrs = {int(y) for y in _YEAR.findall(question or "")}
    if yrs and len(good) and sig.frequency == "monthly" and _TREND.search(question or ""):
        for y in sorted(yrs):
            n_y = int((good.dt.year == y).sum())
            if 0 < n_y < 12:
                flags.append(f"kısmi yıl: {y} için {n_y} ay var; yıllık büyüme değil {n_y} aylık değişim verilebilir")
    if len(frame) <= 6 and _TREND.search(question or ""):
        flags.append(f"küçük örneklem: {len(frame)} satır; trend/yıllık yorum için yetersiz")
    if not sig.unit_hint and _UNIT_ASK.search(question or ""):
        flags.append("birim beyanı yok: veri birimini söylemiyor (milyon/bin/adet?); sayı birimsiz aktarılır")
    elif sig.unit_hint:
        data_scale = _scale_of(" ".join(sig.headers) + " " + sig.name.replace("_", " "))
        q_scale = _scale_of(question)
        if data_scale and q_scale and data_scale != q_scale:
            flags.append(f"birim uyuşmazlığı: soru '{q_scale}' istiyor, veri adı/başlığı '{data_scale}' beyan ediyor; ham sayı {data_scale} "
                         "birimindedir — çeviriyorsan katsayıyı ve iki değeri açıkça yaz, dosyanın birimini TL sanma")
    for col, med_v in sig.numeric_median.items():
        if _RATE_NAME.search(col) and abs(med_v) > 1000:
            flags.append(f"etiket-değer uyuşmazlığı: '{col}' oran gibi adlandırılmış, medyan {med_v:,.0f}".replace(",", "."))
        elif _RATIO_NAME.search(col) and 0 < abs(med_v) < 0.05 and _PCT_ASK.search(question or ""):
            flags.append(f"oran/yüzde belirsizliği: '{col}' medyan {med_v:.4f} (oran olarak okunursa %{med_v * 100:.2f})")
    return flags


__all__ = ["table_quality"]
