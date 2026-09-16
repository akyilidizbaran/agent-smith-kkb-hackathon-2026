# E7 — metin katmanı vs OCR

```text
==========================================================================
E7 — metin katmanı mı, OCR mı?
==========================================================================
  belge : data/adhoc/altin.pdf (1 sayfa) · sayfa 1 · model kkbhackathon2026/Unlimited-OCR

--------------------------------------------------------------------------
YOL A — METİN KATMANI
--------------------------------------------------------------------------
  süre 59 ms · karakter 1148 · rakam 416 · tablo satırı 0
  metin:
    │ AY/MONTH
    │ TOPLAM / TOTAL
    │ Hacim/Volume (TL)
    │ Miktar/Amount 
    │ (KG)
    │ İşlem Sayısı/ 
    │ Number of Trans.
    │ Hacim/Volume (USD)
    │ Miktar/Amount 
    │ (KG)
    │ İşlem Sayısı/ 
    │ Number of Trans.
    │ Hacim/Volume 
    │ (EUR)
    │ Miktar/Amount 
    │ (KG)
    │ İşlem Sayısı/ 
    │ Number of Trans.
    │ … (105 satır daha)

--------------------------------------------------------------------------
YOL B — OCR (Unlimited-OCR)
--------------------------------------------------------------------------
  görsel 2339x1654px · 299 KB · 200 dpi · gönderiliyor…
  süre 2.3 s · ham karakter 2906 · temiz karakter 2663 · rakam (temiz) 421
  yerleşim etiketleri: 0 ref · 6 det · token {'prompt': 1507, 'completion': 938}
  metin (temiz):
    │ ovi
    │ BORSA
    │ ISTANBUL
    │ KIYMETLİ MADENLER PİYASASI ALTIN İŞLEM VERİLERİ (2026)
    │ PRECIOUS METALS MARKET GOLD TRADING DATA (2026)
    │ <table><tr><td rowspan="2">AY/MONTH</td><td colspan="3">TL</td><td colspan="3">USD</td><td colspan="3">EUR</td

--------------------------------------------------------------------------
EK TEST — çağrı başına görsel sınırı
--------------------------------------------------------------------------
  1 görsel: ✓ kabul · 1.5 s · 2663 temiz karakter

==========================================================================
KARAR
==========================================================================
  Metin katmanı DOLU: 59 ms vs OCR 2.3 s; OCR rakam/metin rakam = 1.01
  → METİN KATMANI BİRİNCİL, OCR yalnızca metin katmanı boş dönerse (fallback).
```

## Analiz ve karar (10 Eylül 2026) `[EMP]`

Belge: Borsa İstanbul Kıymetli Madenler Piyasası "Altın İşlemleri" PDF'i (`/dosyalar/kmtp/veriler/kmp_au.pdf`, 1 sayfa, 228 KB, sha256 2c0c822e…).

| Yol | Süre | Ne verdi | Eksik |
|---|---|---|---|
| A. Metin katmanı `get_text()` | 59 ms | 1.148 karakter, 416 rakam; değerler tam | Tablo yapısı yok; `find_tables()` varsayılan (`lines`) 0 tablo |
| A'. `find_tables(strategy="text")` | ~100 ms | 29×11 tablo; veri satırları doğru | Başlık hücreleri parçalı ("H", "acim/Volume"), boş satırlar; birleşik başlıklar kayıp |
| A''. `get_text("words")` + y-kümeleme | ~50 ms | 19 satır; veri satırları temiz | Çok satırlı başlıklar dağınık, sütun eşlemesi elle |
| B. Unlimited-OCR (200 dpi, base64, rehber formatı) | 2.3–2.4 s | `<table>` HTML, `rowspan/colspan` doğru; `pandas.read_html` → **15×11 DataFrame**, 421 rakam | 6 `<\|det\|>` etiketi (temizlendi); 938 çıktı token |

Rakam sayıları (416 vs 421) neredeyse eşit: OCR değer uydurmamış, metin katmanı değer kaçırmamış.

**Karar (edge-case 15 güncellendi):** Tablo içeren PDF'te iki yol **paralel** koşar. Yapı OCR'ın HTML tablosundan alınır; her sayısal hücre metin katmanında aranarak doğrulanır (OCR-değer doğrulama guard'ı). Metin katmanı boşsa (taranmış belge) yalnızca OCR; OCR başarısızsa yalnızca metin katmanı + `find_tables(strategy="text")` ve kullanıcıya "başlıklar doğrulanamadı" uyarısı. Maliyet: tablo başına ~2.5 s, LLM turu yok.

Not: Belge tek sayfa olduğundan 3/4 görsel sınır testi koşmadı; çok sayfalı bir bültenle tekrarlanmalı (`aylik-piyasa-raporu-*.pdf`).
