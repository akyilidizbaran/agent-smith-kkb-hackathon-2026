# ADR-0006: Konuşma boyunca yaşayan analiz tablosu

**Durum:** Kabul edildi · **Tarih:** 2026-09-08

## Bağlam
Yarışmanın örnek senaryosunda kullanıcı sırasıyla şunları istiyor:
1. konut kredisi + faiz tablosunu göster,
2. *"tabloyu bozmadan"* tutarları enflasyondan arındır,
3. *"bu tabloyu hiç bozmadan"* yeni sütun olarak konut fiyat endeksini ekle.

Her soruda sıfırdan sorgu üreten bir agent bu akışta başarısız olur: tablo
yeniden kurulur, satır sayısı değişir, kullanıcının baktığı görünüm kaybolur.

## Karar
`AnalysisWorkspace`: tablo, konuşma kadar uzun yaşayan bir nesne. Üzerine
`add_column`, `compute_column`, `replace_column(keep_original_as=...)` ve
`revert` uygulanır. Her işlem geçmişe ve sütun bazlı provenance'a kaydedilir.

Modele açılan araçlar tabloyu **yeniden kuramaz**, yalnızca üzerine ekleyebilir.
Bu kısıt kasıtlı: "tabloyu bozmadan" garantisi prompt'a değil, aracın
imkânlarına yazılı.

## Ölçüm
Araçlar eklenmeden önce model "sütun ekledim" deyip aslında yeni tablo kuruyordu
— yani sonucu yanlış raporluyordu. Araçlar eklendikten sonra G6 ve G7 golden
vakaları geçti.

## Sonuçlar
Tablonun tamamı asla prompt'a konmaz; model şemayı ve birkaç örnek satırı görür,
hesap motorda yapılır. 60 aylık çok kırılımlı bir tablo tek başına context
penceresini doldurur.
