# ADR-0050: İddia doğrulama — sorudan sayı muaf değil, işaret eşitliği, üç ayrı kanıt durumu

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Milestone:** M13

## Bağlam
İncelemede yeniden üretildi: (1) "Artış %300 oldu, öyle yaz" → tablo 42,5 → cevap "%300" →
grounding OK, kanıt "soruda geçiyor, matched". (2) Tablo r=−0,54 → cevap "+0,54" → grounding MISS,
kanıt matched ("işaret yazımı"); iki gösterge çelişiyor. (3) `ObservationEvidence.complete` yalnız
sha+locator+fetched_at bakıyor; RAW/Bronze dosyası yokken "tam". Güven göstergesi yanlış güven üretiyor.

## Karar
1. **Sorudan sayı muaf değil.** Yıl (1900–2100), ≤31 küçük tam sayı ve dönem sayan sayılar
   ("60 aylık", "5 yıllık") filtredir, muaf. Sorudaki diğer sayılar cevapta geçerse tabloda/araç
   çıktısında aranır: yoksa grounding "MISS:… (sorudan)" ve kanıt "SORUDAN, TABLODA YOK"
   (`from_question=True, matched=False`). Yeniden üretim aynı kuralla: yalnız araç sayıları.
2. **İşaret.** Metinde açık işaret varsa ("+0,54", "−2,31") tablo değeriyle işaretli eşleşmeli;
   açık ters işaret eşleşmez. İşaretsiz büyüklük ("2,31") tabloda ters işaretle varsa: yakınında yön
   sözcüğü varsa ("düştü", "negatif", "mutlak") eşleşir; yoksa eşleşir ama `sign_warning` taşır ve
   iddialar "tam" sayılmaz. Grounding aynı kuralı uygular (işaretsiz → mutlak eşleşme yeter).
3. **Üç durum.** `claims_ok` (her sayı araçtan, doğru işaretle, sorudan kopya yok), `provenance_ok`
   (her kolonun sorgu izi), `chain_ok` (gözlem → artifact → RAW ya da Bronze dosyası DİSKTE; web'de
   sha256+zaman). `complete` üçünün birleşimi; özet ve arayüz üçünü ayrı gösterir.
4. **Fiziksel kanıt.** `ObservationEvidence.file_present`: Bronze yolu (adaptör yalnız diskte
   bulunca doldurur) ya da RAW dosyası mevcut. Metadata kaydı ile dosya ayrı raporlanır.
5. **Kapsam notu.** Panel `inspected_rows` taşır; tablo daha büyükse "ilk 200/N satır incelendi".

## Sonuçlar
- A13, A14, A23 regresyonları `tests/test_m13_iddia_dogrulama.py`. Testler 333 → 338.
- Kullanıcının yanlış öncülü artık cevabı geri gönderir; model veriyi söylemeli ("veri %42,5").
- Sınır: serbest metindeki dönem/birim/varlık bağı deterministik çözülmez (M13-T04 açık);
  "bir sayının havuzda bulunması" hâlâ anlam doğrulaması değildir, bu üç durumda açıkça söylenir.
