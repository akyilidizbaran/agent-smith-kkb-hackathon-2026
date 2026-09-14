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

# Sayı bir tanımlayıcının parçasıysa (bddk_weekly:5690_3, TP.KTF12) sayı değildir: iki yanda da
# sözcük karakteri olamaz (ölçüldü, G17: seri kimliğindeki 5690 "tabloda yok" sayıldı).
_NUM_RE = re.compile(
    r"(?<![\w.,])[-+]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\w)"   # Türkçe binlik (+ opsiyonel ondalık)
    r"|(?<![\w.,])[-+]?\d+(?:[.,]\d+)?(?!\w)"              # düz sayı; ayraç ondalıktır
)


_DATE_TOKEN = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def _ascii_minus(text: str) -> str:
    """Model "−0,54" (U+2212) yazar, araç "-0.54" (ASCII); işaret düşünce eşleşmez (ölçüldü, G17:
    dört korelasyon katsayısı "araç çıktısında yok" sayıldı). Yalnız gerçek eksi işareti çevrilir;
    aralık tiresi (2024–2026) dokunulmaz. Tarih yazımları ("27.07.2026", "2026-06-30") sayı değildir:
    ölçüldü (G18c), belgenin güncelleme tarihi "27,07" diye "tabloda yok" sayıldı; maskelenir."""
    return _DATE_TOKEN.sub(" ", (text or "").replace("\u2212", "-"))


def numbers_in(text: str, *, both_readings: bool = False) -> list[float]:
    """Metindeki sayılar. `both_readings`: araç çıktısı havuzu için — "18.388" tek nokta + üç hane hem pandas
    ondalığı (18,388) hem Türkçe binlik (18388) olabilir; ikisi de havuza girer (K02 bulgusu, 14 Eyl: Gold aylık faiz
    18.388 binlik okundu, modelin doğru yazdığı "%18,39" MISS sayıldı). Cevap metni tek (Türkçe) okumayla ayrışır."""
    out: list[float] = []
    for m in _NUM_RE.finditer(_ascii_minus(text)):
        raw = m.group(0)
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(".") > 1 or (
            re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", raw) and not re.fullmatch(r"[-+]?0\.\d{3}", raw)
        ):
            # "0.263" binlik değil ondalıktır (korelasyon katsayısı; ölçüldü, G17).
            if both_readings and raw.count(".") == 1:
                try:
                    out.append(float(raw))
                except ValueError:
                    pass
            raw = raw.replace(".", "")
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


_PERIOD_NUM = re.compile(r"(?<![\w.,])(\d{1,3})\s*(?:ay|hafta|yıl|yil|gün|gun|çeyrek|ceyrek|dönem|donem)\w*", re.I)


def period_numbers(text: str) -> set[float]:
    """Soruda dönem sayan sayılar ("60 aylık", "5 yıllık"): filtre, iddia değil."""
    return {float(m.group(1)) for m in _PERIOD_NUM.finditer(_ascii_minus(text or ""))}


def _unsigned(token: str) -> bool:
    return not token.lstrip().startswith(("-", "+"))


def grounding_check(question: str, answer: str, tool_texts: list[str], tolerance: float = 0.005) -> str:
    """'OK' ya da 'MISS:<sayılar>'.

    Kontrol dışı: yıllar (1900–2100), ≤31 küçük tam sayılar (ay/gün/sıra), soruda dönem sayan
    sayılar ("60 aylık"). Soruda geçen DİĞER sayılar muaf DEĞİLDİR (M13-T01, ADR-0050): kullanıcı
    "%300 arttı, öyle yaz" dediyse ve araç çıktısında yoksa MISS'tir; "(sorudan)" etiketi taşır.
    İşaret: metindeki sayı işaretliyse ("+0,54", "−2,31") havuzdaki değerle işaretli eşleşmeli;
    işaretsiz yazılmışsa ("2,31 düştü") mutlak değer eşleşmesi yeter. Tolerans %0,5.
    """
    pool: set[float] = set()
    for t in tool_texts:
        pool.update(numbers_in(t, both_readings=True))
    asked = set(numbers_in(question))
    periods = period_numbers(question)
    missing: list[str] = []
    for m in _NUM_RE.finditer(_ascii_minus(answer)):
        token = m.group(0)
        vals = numbers_in(token)
        if not vals:
            continue
        v = vals[0]
        if (1900 <= v <= 2100 and v.is_integer()) or (abs(v) <= 31 and v.is_integer()) or v in periods:
            continue
        tol = max(abs(v) * tolerance, tolerance)
        if any(abs(v - p) <= tol for p in pool):
            continue
        if _unsigned(token) and any(abs(abs(v) - abs(p)) <= tol for p in pool):
            continue  # büyüklük yazılmış, yön sözcükle: "2,31 düştü"
        missing.append(token + (" (sorudan)" if v in asked else ""))
    return "OK" if not missing else "MISS:" + ", ".join(dict.fromkeys(missing))


# Ölçüldü (Deney 2): "Suriyeli sığınmacıların etkisiyle artış hızlanmış" veride olmayan bir
# sebep; "etkisiyle" ve "nedeniyle" listede yoktu, cümle geçti. Sonuç bağlacı olan
# "dolayısıyla" bilerek dışarıda (toplam/sonuç anlatımında meşru).
_CAUSAL = re.compile(r"\b(neden old\w*|yol aç\w*|sebep old\w*|kaynaklan\w*|sayesinde|yüzünden|etkisiyle|nedeniyle)\b", re.I)
# Olumsuzlanmış nedensellik iddia değildir: "neden olduğu söylenemez / anlamına gelmez / kanıtlamaz"
# (ölçüldü, G17: model kartın istediği çekinceyi yazdı, filtre onu iddia sandı ve geri gönderdi).
_CAUSAL_NEGATED = re.compile(
    r"\b(neden old\w*|yol aç\w*|sebep old\w*|kaynaklan\w*)\b[^.\n]{0,40}?"
    r"(söylenemez|anlamına gelme\w*|kanıtla\w*maz|gösterme\w*|değil\w*|iddia edilemez|çıkarılamaz)", re.I,
)


def causal_language(answer: str) -> list[str]:
    """Nedensellik dili filtresi (edge-case 8): yakalanan ifadeler; olumsuzlanmış olanlar sayılmaz."""
    text = answer or ""
    negated = [(m.start(), m.end()) for m in _CAUSAL_NEGATED.finditer(text)]
    found: set[str] = set()
    for m in _CAUSAL.finditer(text):
        if any(a <= m.start() < b for a, b in negated):
            continue
        found.add(m.group(0).lower())
    return sorted(found)
