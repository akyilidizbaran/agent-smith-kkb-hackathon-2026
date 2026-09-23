# ADR-0109: Yüklenen dosyada haftalıktan aylığa: hafta başladığı aya yazılır

**Durum:** Kabul edildi · **Tarih:** 2026-09-23 · **İlgili:** ADR-0108, PR #26 (genel CSV/XLSX okuma ve zaman normalizasyonu)

## Bağlam
PR #26 (`feature/generic-temporal-enrichment`, Elif) yüklenen dosyalar için üç parça getirdi:
- CSV/XLSX okumasını sağlamlaştırma (`builder/tabular.py`);
- dönem biçimlerini normalize etme (`builder/temporal.py`);
- tabloyu değiştirmeden ay anahtarıyla ekleme (`workspace.enrich_table`).

PR, bizim son commit'imizi içermediği için birleştirilmedi. Üç commit'in değişikliği yerel çalışma alanına uygulandı.
Tek çakışma `workspace.py`'deydi (tablo kuşağı sayacı, ADR-0106); iki değişiklik de korundu.

Bir fon işlem hacmi dışa aktarımıyla yapılan denemede dosya aylık istendiği hâlde haftalık kaldı. Üç neden vardı:
1. Dosyanın sonundaki "Toplam" satırı dönem olarak çözülemiyordu; zaman ekseninin güveni düşüyor, dönüşüm hiç başlamıyordu.
2. Ay sınırını aşan haftalar (ör. 29.03–02.04) için dönüşüm tamamen reddediliyordu.
3. "Günlük Ortalama İşlem Hacmi" etiketindeki "hacim" yüzünden ortalama sütunu toplanabilir akış sayılıyordu.

## Karar
1. **Alt toplam satırı dönem değildir.** "Toplam / Genel Toplam / Total" satırları hem ekseni değerlendirirken hem dönüşümde
   dışarıda kalır; kaç satır çıkarıldığı uyarıya yazılır.
2. **Hafta, başladığı aya yazılır.** Değer günlere bölünmez; bölüştürme, kaynağın yayımlamadığı bir günlük dağılımı
   varsaymak olur. Kaynağın kendi aylık raporu da haftayı başladığı aya sayar; Ocak 2021 = Ocak'ta başlayan dört hafta.
   Ay sınırını aşan hafta sayısı uyarıya yazılır.
3. **Ortalama toplanmaz.** Etiketinde "ortalama / average / mean" geçen sütun iş günü ağırlıklı ortalamayla aylığa iner.
   Oranlar da aynı kuralla iner; stok ve endeks ayın son gözlemidir.
4. **Kapsamı eksik aylar söylenir.** Bir ayda kaynağın kapsadığı iş günü, ayın iş gününün %90'ından azsa o ay uyarıda
   listelenir (dosyanın başladığı ya da bittiği yarım aylar).
5. **"Ay" birleştirme kuralı açıkça seçilir.** `workspace_join key_policy='ay'` farklı ay yazımlarını eşler. Kural otomatik
   öneri listesinde yoktur, çünkü gün düzeyindeki tarihleri birleştirir.

## Sonuçlar
- Haftalık dışa aktarımlar aylık istendiğinde aylığa iner. Ay sınırını aşan haftalar yüzünden ay toplamı, günlere bölünmüş
  bir hesaptan farklıdır; kural cevapta açıkça yazar.
- PR #26'nın "ay sınırını aşan dönem reddedilir" testi bu kurala göre güncellendi.
- Aynı raporun farklı filtreli dışa aktarımları farklı sayılar verir. Beklenen çıktıyla karşılaştırmada dışa aktarım
  filtresi (ör. "Genel (TL)") aynı olmalıdır.

## Ek (23 Eylül akşam)
- **Kapsam uyarısı yalnız uçlarda:** Eksik kapsam uyarısı yalnız dosyanın ilk ve son ayı için verilir. Ortadaki ayların
  tatil kaynaklı düşük iş günü sayısı yanlış alarm üretiyordu.
- **Dizi hücreleri dönem değildir:** `parse_period` liste/dizi hücrelerini (Gold tablolarındaki kanıt listeleri) atlar;
  önceden dönem ayrıştırması bu hücrelerde çöküyordu.
- **Kaynağın aylık raporu doğrudan alınabilir:** Fon işlem hacmi raporu ay aralığıyla sorulduğunda kaynak zaten aylık döner
  (dönem `YYYY-MM`, altta "Toplam" satırı). Aylık değerlerin toplamı kaynağın "Toplam" satırıyla birebir tutuyor. Aynı
  raporun haftalık, filtreli dışa aktarımı ise ilk haftayı içermeyebilir; aylığa indirilen haftalık dosya bu yüzden
  kaynağın aylık raporundan farklı çıkabilir. Karşılaştırmada dışa aktarımın türü (aylık/haftalık) ve filtresi aynı olmalı.
- **main ile birleştirme (PR #26 ve 6626a77, Büşra):** PR #26 main'e birleşti; ardından gelen 6626a77'nin üç düzeltmesi
  bu dalın kurallarıyla birleştirildi:
  1. *Satır sırası:* Bu daldaki dönüşüm ayları zaten takvim sırasıyla kuruyor, stok değerini dönem sonuna göre seçiyor;
     azalan sıralı dosyada da aynı sonuç (Büşra'nın iki testi değişmeden geçiyor).
  2. *Niteleyicili akım kelimesi:* Kabul edildi. Bu daldaki "ortalama → iş günü ağırlıklı ortalama" kuralı yalnız zaman
     başına ortalamaya ("günlük / haftalık ortalama") daraltıldı; gün ağırlığı yalnız bu tanımda kesin. Zaman birimi
     olmayan "Ortalama Tutar" işlem başına olabilir; UNKNOWN olur ve ham tablo gösterilir.
  3. *Sayıya çevrilemeyen hücre:* Kabul edildi. Boş hücre artık o ayı sessizce boş bırakmıyor, VALUE_PARSE_FAILED ile
     ham tabloya düşüyor.
