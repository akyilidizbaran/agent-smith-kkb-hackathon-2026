"""Grounding guard — cevaptaki her sayı bir araç çıktısında var mı?

Yazarı Büşra (V3 §3.1 adım 4, E5); ortak katmana buraya taşındı ki tek kopya olsun.
İki motorun da ihtiyacı olan, hiçbirine ait olmayan bir modül: saf fonksiyon, yalnız
`re` kullanıyor, ne harness'ı ne adaptörü tanıyor. V3 kendi kopyası yerine bunu
import edebilir.

Ölçüm [EMP]: gölge modda modelin anlatıda kendi aritmetiğini yaptığı görüldü
("155.515 milyon TL arttı" — tabloda olmayan fark). Enforce modunda 14/14 temiz,
bedeli +2 tur. Bu modül yalnız ölçer ve eksikleri listeler; ne yapılacağına
harness karar verir (bir kez yeniden üretim, sonra tablo + caveat).

Türkçe sayı biçimi: binlik "." ve ondalık ","; boşluk binlik ayracı SAYILMAZ.

İki biçim aynı metin havuzunda: araç çıktıları (pandas) İngiliz ondalığı yazar
("1.357539"), model Türkçe yazar ("1,36" / "678.970"). Binlik alternatifi yalnız
3'erli gruplar RAKAMLA DEVAM ETMİYORSA eşleşir; aksi hâlde "1.357539" → 1.357 (=1357)
okunuyordu ve %1,36 havuzda bulunamıyordu — Blok C gölge kayıtlarındaki
"MISS:2,21, 2,50…" yanlış pozitiflerinin kaynağı buydu (10 Eylül, 2. oturum).
"""

from __future__ import annotations

import re

_NUM_RE = re.compile(
    r"(?<![\w.,])[-+]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\d)"   # Türkçe binlik (+ opsiyonel ondalık)
    r"|(?<![\w.,])[-+]?\d+(?:[.,]\d+)?"                   # düz sayı; ayraç ondalıktır
)


def numbers_in(text: str) -> list[float]:
    out: list[float] = []
    for m in _NUM_RE.finditer(text or ""):
        raw = m.group(0)
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(".") > 1 or re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", raw):
            raw = raw.replace(".", "")
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def grounding_check(question: str, answer: str, tool_texts: list[str], tolerance: float = 0.005) -> str:
    """'OK' ya da 'MISS:<sayılar>'.

    Kontrol dışı: yıllar (1900–2100), ≤31 küçük tam sayılar (ay/gün/sıra), soruda
    zaten geçen sayılar. Tolerans %0,5: yuvarlama geçer, uydurma geçmez.
    """
    pool: set[float] = set()
    for t in tool_texts:
        pool.update(numbers_in(t))
    asked = set(numbers_in(question))
    missing: list[str] = []
    for m in _NUM_RE.finditer(answer or ""):
        vals = numbers_in(m.group(0))
        if not vals:
            continue
        v = vals[0]
        if v in asked or (1900 <= v <= 2100 and v.is_integer()) or (abs(v) <= 31 and v.is_integer()):
            continue
        tol = max(abs(v) * tolerance, tolerance)
        if not any(abs(v - p) <= tol for p in pool):
            missing.append(m.group(0))
    return "OK" if not missing else "MISS:" + ", ".join(dict.fromkeys(missing))


# Ölçüldü (Deney 2): "Suriyeli sığınmacıların etkisiyle artış hızlanmış" veride olmayan bir
# sebep; "etkisiyle" ve "nedeniyle" listede yoktu, cümle geçti. Sonuç bağlacı olan
# "dolayısıyla" bilerek dışarıda (toplam/sonuç anlatımında meşru).
_CAUSAL = re.compile(r"\b(neden oldu|yol açtı|sebep oldu|kaynaklandı|sayesinde|yüzünden|etkisiyle|nedeniyle)\b", re.I)


def causal_language(answer: str) -> list[str]:
    """Nedensellik dili filtresi (edge-case 8): yakalanan ifadeler."""
    return sorted({m.group(0).lower() for m in _CAUSAL.finditer(answer or "")})
