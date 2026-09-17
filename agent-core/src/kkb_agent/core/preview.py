"""Araç kartı tablo önizlemesi — tek kural, dört kart (V3 §3.9 / rapor PART 41; Büşra, 15 Eyl).

Sorun (ölçüldü): kartlar "ilk 10 satır" gösteriyordu; 12 satırlık aylık sonuçta model 10 satırı tam sonuç sanıp
kalan iki ayı "sorguda yok" yazdı (UEB A15, A06, A24 — üçü de 12 satır) ya da kalanı görmek için aynı sorguyu
yineledi (V3 L4-01 döngüsü, 10 Eyl). Literatür belirli bir satır sayısı öngörmüyor; iki şey söylüyor:
kesme SESSİZSE model görmediği satırlar hakkında güvenle konuşur (araç-sonucu kesme yazıları, LangChain
top_k=10 şikâyetleri) ve tablo bozulması binlerce token'da başlar (TableRAG, NeurIPS 2024) — 24 satır ≈ 400
token bunun çok altında. Kesilecekse ortadan kesilir (Lost in the Middle: baş ve son iyi okunur; zaman
serisinde son satırlar en güncel aylardır) — pandas (60; baş 5 + son 5) ve DuckDB CLI (40) kalıbı.

Kural, soruya değil BOYUTA bağlıdır:
  ≤ FULL_ROWS  → tamamı
  > FULL_ROWS  → baş HEAD_ROWS + "… N satır GÖSTERİLMEDİ" + son TAIL_ROWS + toplam satır
"""

from __future__ import annotations

import re
from typing import Callable

import pandas as pd

FULL_ROWS = 24    # iki yıl aylık; tipik "listele" isteğinin üst sınırı
HEAD_ROWS = 10
TAIL_ROWS = 5


def preview_table(df: pd.DataFrame, *, render: Callable[[pd.DataFrame], str] | None = None,
                  where: str = "aktif analiz tablosunda") -> str:
    """Kart metni: küçük tablo tamamı; büyük tablo baş + açık kesme işareti + son + toplam.

    `render`: satırları metne çeviren fonksiyon (varsayılan pandas `to_string`; web kartı hizalı `_plain` verir).
    `where`: gösterilmeyen satırların nerede olduğu ("aktif analiz tablosunda", "bu sorgunun sonucunda")."""
    fmt = render or (lambda f: f.to_string(index=False))
    n = len(df)
    if n <= FULL_ROWS:
        return f"Satırlar ({n}, tamamı):\n{fmt(df)}"
    hidden = n - HEAD_ROWS - TAIL_ROWS
    return (
        f"İlk {HEAD_ROWS} satır:\n{fmt(df.head(HEAD_ROWS))}\n"
        f"… ({hidden} satır GÖSTERİLMEDİ; tamamı {where} — listeleme gerekiyorsa workspace_show ya da daraltan bir sorgu; "
        f"gösterilmeyen satırlar hakkında 'yok' deme)\n"
        f"Son {TAIL_ROWS} satır:\n{fmt(df.tail(TAIL_ROWS))}\n"
        f"Toplam {n} satır."
    )


# İlk → son değişimi harness hesaplar (16 Eyl, canlı ölçüm). Tekrarlayan geri gönderme sebebi: model sorguya yıllık
# toplamı koymayı unutuyor, anlatıda iki uç değerin farkını/oranını kendisi hesaplıyor ("166.711 arttı, %32,5";
# önceki kayıt "155.515 milyon TL arttı"), grounding guard bunu MISS sayıyor (+43 s) ve model ikinci yazımda sayıyı
# siliyor — "2025'te nasıl değişti" sorusunun asıl cevabı düşüyor. Sayı karta girince araç çıktısında var demektir:
# model hesap yapmaz, guard kabul eder. Yalnız tarihi tekil olan tablolar (satır = dönem); çok varlıklı uzun tabloda
# (il × ay) ilk-son anlamsızdır, atlanır. Oran/yüzde sütununda yüzde değişim yazılmaz (yüzdenin yüzdesi yanıltır).
_DATE_HINT = re.compile(r"date|tarih|period|d[oö]nem|time|zaman", re.I)
_RATIO_HINT = re.compile(r"y[uü]zde|pct|percent|oran|ratio|rasyo|share|pay", re.I)
SPAN_MAX_COLUMNS = 4


def _date_column(df: pd.DataFrame) -> str | None:
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            return str(c)
    for c in df.columns:
        if _DATE_HINT.search(str(c)) and not pd.api.types.is_numeric_dtype(df[c]):
            return str(c)
    return None


def _fmt(v: float) -> str:
    """Pandas'ın kart yazımıyla aynı okuma: düz nokta ondalık, binlik ayracı yok (grounding havuzu böyle okur)."""
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}"


def span_values(df: pd.DataFrame, *, max_columns: int = SPAN_MAX_COLUMNS) -> list[dict]:
    """Sütun başına ilk/son gözlem ve harness'ın türettiği sayılar: {column, d0, v0, d1, v1, diff, pct|None}.
    Kart metni (`span_summary`) ve kanıt paneli (core/evidence: "harness türetti" eşleşmesi) aynı listeyi okur."""
    if len(df) < 2:
        return []
    date_col = _date_column(df)
    if date_col is None:
        return []
    dates = pd.to_datetime(df[date_col], errors="coerce")
    if dates.isna().any() or not dates.is_unique:
        return []
    ordered = df.assign(__d=dates.values).sort_values("__d")
    out: list[dict] = []
    for c in df.columns:
        if str(c) == date_col or not pd.api.types.is_numeric_dtype(df[c]) or pd.api.types.is_bool_dtype(df[c]):
            continue
        sub = ordered[["__d", c]].dropna(subset=[c])
        if len(sub) < 2:
            continue
        v0, v1 = float(sub[c].iloc[0]), float(sub[c].iloc[-1])
        pct = (v1 / v0 - 1) * 100 if v0 != 0 and not _RATIO_HINT.search(str(c)) else None
        out.append({"column": str(c), "d0": sub["__d"].iloc[0].strftime("%Y-%m-%d"), "v0": v0,
                    "d1": sub["__d"].iloc[-1].strftime("%Y-%m-%d"), "v1": v1, "diff": v1 - v0, "pct": pct})
        if len(out) >= max_columns:
            break
    return out


def span_summary(df: pd.DataFrame, *, max_columns: int = SPAN_MAX_COLUMNS) -> str:
    """'Harness hesabı — ilk → son' satırları; uygun değilse boş metin."""
    lines: list[str] = []
    for s in span_values(df, max_columns=max_columns):
        line = (f"  {s['column']}: {s['d0']} {_fmt(s['v0'])} → {s['d1']} {_fmt(s['v1'])}"
                f" · fark {'+' if s['diff'] >= 0 else ''}{_fmt(s['diff'])}")
        if s["pct"] is not None:
            line += f" · değişim {'+' if s['pct'] >= 0 else ''}{s['pct']:.2f}%"
        lines.append(line)
    if not lines:
        return ""
    return "Harness hesabı — ilk → son (bu sayıları kendin hesaplama, buradan al):\n" + "\n".join(lines)


__all__ = ["FULL_ROWS", "HEAD_ROWS", "SPAN_MAX_COLUMNS", "TAIL_ROWS", "preview_table", "span_summary", "span_values"]
