# Branch özeti — `feature/source-access-bddk-weekly`

**Sahip:** Elif Güngen

**Amaç:** BDDK Haftalık Bülten'deki konut kredisi bakiyesini doğrulanmış ve
tekrar üretilebilir bir Source Access akışıyla lakehouse'a almak.

## Neden ayrı geliştirildi?

BDDK Haftalık endpoint'i BDDK Aylık endpoint'inden farklı form alanları, tarih
biçimi ve cevap zarfı kullanır. Aylık connector'ın davranışını haftalığa
kopyalamak kaynağı yanlış yorumlamak olurdu. Bu nedenle endpoint bağımsız olarak
araştırılmış ve ayrı connector/parser yazılmıştır.

## Neler yapıldı?

- `BddkWeeklyConnector`
- `BddkWeeklyParser`
- Başarılı, boş aralık ve bilinmeyen kalem fixture'ları
- Connector, parser ve uçtan uca Bronze integration testleri
- Canlı kaynaktan dar ve tam-aralık smoke doğrulaması
- Sabit kalem kimliği ile pozisyonel grafik adresinin ayrılması

## Seçilen seri

```text
series_id: bddk_weekly:5690_3
dataset_id: bddk_weekly_housing_loans
kalem_id: 5690
sütun: 3 (Toplam)
birim: milyon TL
measure_type: stock
```

`5690` sabit kaynak kalemidir. `1.0.4` ise yalnız endpoint'in pozisyonel grafik
adresidir; bülten sırası değişirse farklı satırı gösterebilir ve seri kimliği
olarak kullanılmaz.

## Önemli kaynak davranışları

- Tarih ve değerler iki paralel dizi hâlinde gelir.
- Başarısız cevap HTTP 200 dönebilir.
- Haftalık gözlemler tatil haftalarında Perşembe gibi farklı güne kayabilir.
- JSON içinde ölçek birimi yoktur; `milyon TL` bilgisi resmî tablo başlığından
  doğrulanmıştır ve semantic catalog/Silver katmanında uygulanır.
- BDDK sunucusunun eksik TLS ara sertifika zinciri deployment seviyesinde ayrıca
  ele alınmalıdır; TLS doğrulamasını kapatmak çözüm değildir.

## İlgili commitler

- `e591809` — doğrulanmış BDDK Haftalık ingestion
- `eeda78b` — güncel provenance altyapısıyla birleşmiş sürüm

Bu çalışma daha sonra `feature/lakehouse-integration` dalına alınmıştır.
