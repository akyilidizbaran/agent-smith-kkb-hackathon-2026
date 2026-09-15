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


__all__ = ["FULL_ROWS", "HEAD_ROWS", "TAIL_ROWS", "preview_table"]
