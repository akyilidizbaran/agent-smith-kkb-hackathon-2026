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


# K03 ekran provası bulgusu: "kapsam 2026-06'ya kadar" yıl-ay yazımı da tarihtir (2026 sayı sanılıp "tabloda yok" deniyordu);
# ay 01–12 ile sınırlı, "2021-25 arası" gibi yıl aralığı maskelenmez.
_DATE_TOKEN = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:19|20)\d{2}-(?:0[1-9]|1[0-2])\b(?!-\d)"
                         # ADR-0078 canlı denemesi: "bülten no 2026/120" yıl/sıra kimliğidir, ölçüm değil ("120 tabloda yok" deniyordu).
                         r"|\b(?:19|20)\d{2}/\d{1,4}\b(?![.,]\d)")


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


def shown_decimals(raw: str) -> int:
    """Bir sayı yazımının GÖSTERDİĞİ ondalık hane sayısı — tolerans buradan türer.

    Ayraç ondalık mı binlik mi, `numbers_in` ile birebir aynı kuralla ayrılır (E-1 ikinci-göz düzeltmesi): virgül daima
    ondalıktır ("18,39" → 2); nokta ise binlik grubu (`\\d{1,3}(\\.\\d{3})+`, "678.970" → 0) DIŞINDA ondalıktır
    ("2.31" → 2, "0.263" → 3, "+0.003" → 3). `token_tolerance` yalnız virgülü saydığından noktalı ondalıklara yanlışlıkla
    tam sayı toleransı (0,5) veriyordu; araç 2.7 iken "%2.31" kabul ediliyordu."""
    if "," in raw:
        return len(raw.rsplit(",", 1)[1])
    if "." in raw:
        # numbers_in ile aynı ayrım: nokta binlik grubuysa ondalık hane yok, değilse noktadan sonrası ondalıktır.
        if raw.count(".") > 1 or (
            re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", raw) and not re.fullmatch(r"[-+]?0\.\d{3}", raw)
        ):
            return 0
        return len(raw.rsplit(".", 1)[1])
    return 0


def token_tolerance(raw: str) -> float:
    """Bir sayı yazımının eşleşme toleransı: cevapta GÖSTERİLEN hassasiyetin yarım birimi (E-1, ADR-0081).

    Göreli (büyüklükle büyüyen) tolerans YOK — bağlam senaryosu (15 Eyl) %0,5 göreli toleransla uydurma "677.970"i
    tablodaki 678.970'e eşleşmiş saydı. Ondalık gösterilmemişse (tam sayı ya da binlik-noktalı "678.970") yarım birim
    0,5; "17,9"/"2.31" → 0,05/0,005; "0,001"/"0.263" → 0,0005. Noktalı ve virgüllü ondalıklar birlikte ele alınır
    (`shown_decimals`). Yalnız kayan-nokta hatası için 1e-9 tabanı; büyüklükle büyümez. Bu, `agent.unverified_numbers`
    (araçsız/final-exit) ve `evidence.EvidenceBuilder._hits` (kanıt paneli) ile aynı kuraldır; üç yol ortak davranır.
    """
    return max(0.5 * 10 ** -shown_decimals(raw), 1e-9)


#: Yalnız yarım-birim sınırındaki İKİLİ KAYAN-NOKTA hatası için mutlak pay: 37,285 → %37,29 doğru yuvarlaması, 37,29−37,285
#: float'ta 0,005000000000002558 çıkıp toleransı (0,005) kıl payı aşıyordu (üçüncü-göz Açık 2). Değere göre DEĞİL sabit;
#: büyüklükle büyüyen göreli tolerans DEĞİL. Küçük ondalıklı iddialarda ULP ≪ 1e-9 olduğundan gerçek yanlış değeri geçirmez.
_MATCH_EPS = 1e-9


def within_tolerance(value: float, target: float, tol: float) -> bool:
    """`value`, `target`'a gösterim toleransı içinde mi (işaretli fark). Üç yolun ORTAK karşılaştırması: grounding,
    `evidence._hits` ve `agent.unverified_numbers` aynı sınır davranışını verir (üçüncü-göz: 'karşılaştırmayı da
    ortaklaştır'). Sınır float hatasına karşı `_MATCH_EPS` mutlak payı; göreli/büyüklükle büyüyen tolerans YOK."""
    return abs(value - target) <= tol + _MATCH_EPS


#: Oran/değişim bağlamı, sayı belirtecine DOĞRUDAN BİTİŞİK olarak aranır (yakınlık penceresi değil): sayının hemen
#: solundaki birim ("%2", "% 2", "yüzde 2", "oranı 2", "oranı: 2") ya da hemen sağındaki birim ("2%", "2 %", "2 puan",
#: "2 puanlık", "2 baz puanlık", "2 oranında"). Türkçe ekler serbest (`puan\w*`: puanlık/puandan). Solda birimle sayı
#: arasında yalnız boşluk ya da tek iki-nokta olabilir. '%' sağda: bitişik ("2%") her zaman; boşluklu ("2 %") yalnız
#: ardından başka bir sayı GELMİYORSA ("100 %2" → % sonraki sayıya aittir, 100'e değil; üçüncü-göz Açık 1).
_RATE_BEFORE = re.compile(r"(?:%|‰|yüzde|yuzde|oran\w*)\s*:?\s*$", re.I)
_RATE_AFTER_PCT = re.compile(r"^(?:[%‰]|\s+[%‰](?!\s*\d))")
_RATE_AFTER_WORD = re.compile(r"^\s*(?:baz\s+puan\w*|puan\w*|bps\b|oran\w*)", re.I)


def in_rate_context(text: str, start: int, end: int) -> bool:
    """Sayı belirteci (start:end) DOĞRUDAN bir oran/puan birimine mi bağlı (E-4, ADR-0081 uyarı 6).

    Yakınlık penceresi değil, bitişiklik: '12 ayda %2 arttı' cümlesinde '%' yalnız '2'ye bağlanır, '12' dönem sayısı
    olarak muaf kalır. Solda '%'/'‰'/'yüzde'/'oran…' birimi doğrudan sayıdan önce (arada yalnız boşluk ya da ':');
    sağda ya '%'/'‰' (bitişik; ya da boşluklu ama ardından sayı yoksa) ya da 'puan…'/'baz puan…'/'bps'/'oran…' sözcüğü.
    Türkçe ekler serbest ('puanlık', 'puandan'). 'oran' de E-4 bağlamıdır: '%' olmadan 'Artış oranı 2' de doğrulanır."""
    if _RATE_BEFORE.search(text[:start]):
        return True
    after = text[end:]
    return bool(_RATE_AFTER_PCT.match(after) or _RATE_AFTER_WORD.match(after))


def grounding_check(question: str, answer: str, tool_texts: list[str], tolerance: float = 0.005) -> str:
    """'OK' ya da 'MISS:<sayılar>'.

    Kontrol dışı: yıllar (1900–2100), ≤31 küçük tam sayılar (ay/gün/sıra) — ANCAK oran/puan bağlamında değilse (E-4),
    soruda dönem sayan sayılar ("60 aylık"). Soruda geçen DİĞER sayılar muaf DEĞİLDİR (M13-T01, ADR-0050): kullanıcı
    "%300 arttı, öyle yaz" dediyse ve araç çıktısında yoksa MISS'tir; "(sorudan)" etiketi taşır.
    İşaret: metindeki sayı işaretliyse ("+0,54", "−2,31") havuzdaki değerle işaretli eşleşmeli;
    işaretsiz yazılmışsa ("2,31 düştü") mutlak değer eşleşmesi yeter. Tolerans: gösterilen hassasiyetin yarım birimi
    (`token_tolerance`); göreli %0,5 YOK. `tolerance` parametresi geriye dönük uyum için tutuluyor, kullanılmıyor.
    """
    pool: set[float] = set()
    for t in tool_texts:
        pool.update(numbers_in(t, both_readings=True))
    asked = set(numbers_in(question))
    periods = period_numbers(question)
    masked = _ascii_minus(answer)
    missing: list[str] = []
    for m in _NUM_RE.finditer(masked):
        token = m.group(0)
        vals = numbers_in(token)
        if not vals:
            continue
        v = vals[0]
        # Oran/puan bağlamı ("%12", "2 puan", "Artış oranı 2") tüm muafiyetleri geçersiz kılar: yıl, soruda dönem sayan
        # ya da ≤31 küçük bir sayı bile doğrudan oran iddiası olarak yazıldıysa araç çıktısında doğrulanmalıdır
        # (ikinci-göz Açık 2/3). Bağlam yoksa yıl/dönem/küçük-sayı muafiyetleri her zamanki gibi geçerli.
        if not in_rate_context(masked, m.start(), m.end()):
            if (1900 <= v <= 2100 and v.is_integer()) or v in periods:
                continue
            if abs(v) <= 31 and v.is_integer():
                continue
        tol = token_tolerance(token)
        if any(within_tolerance(v, p, tol) for p in pool):
            continue
        if _unsigned(token) and any(within_tolerance(abs(v), abs(p), tol) for p in pool):
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
