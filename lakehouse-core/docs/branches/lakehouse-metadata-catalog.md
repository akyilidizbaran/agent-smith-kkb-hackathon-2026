# Branch özeti — `feature/lakehouse-metadata-catalog`

**Sahip:** Elif Güngen

**Amaç:** Ekonomik serilerin ne anlama geldiğini insan tarafından doğrulanan,
Git ile versiyonlanan bir semantic catalog içinde tutmak.

## Neden yapıldı?

Bir sayının stok, akım, faiz veya endeks olduğu yalnız değerlerine bakılarak
güvenli biçimde anlaşılamaz. Bu bilgi yanlış olursa aylıklaştırma ve toplama
işlemleri sessizce yanlış sonuç verir. `meta.series`, Silver dönüşümüne ve agent'ın
seri seçimine tek bir doğrulanmış anlam kaynağı sağlar.

## Operasyonel ve semantic metadata farkı

- `meta.artifact`, `meta.run`, `meta.dataset_version`: sistemin ne yaptığını
  otomatik kaydeder.
- `meta.series`: serinin ne ifade ettiğini insan tarafından yazılmış YAML
  kayıtlarından yükler.

## Neler yapıldı?

- `meta.series` DuckDB tablosu
- `catalog/series/*.yml` kaynak dosyaları
- YAML doğrulama ve transaction içinde idempotent yükleme
- Değişmeyen içerikte `updated_at` değerini koruyan içerik hash'i
- Yinelenen kimlik, yanlış namespace, eksik açıklama, yanlış frekans/ölçü tipi ve
  güvensiz aggregation kurallarını reddeden doğrulamalar
- Eksik katalog dizininde sessizce devam etmek yerine açık hata
- Unit ve integration testleri

## İlk dört seri

| Seri | Tür | Frekans | Birim | Güven |
|---|---|---|---|---|
| `evds:TP.KTF12` | rate | weekly/friday | pct | verified |
| `evds:TP.KFE.TR` | index | monthly | index | derived |
| `bddk_monthly:1534_Toplam` | stock | monthly | TRY_mn | verified |
| `bddk_weekly:5690_3` | stock | weekly/friday | TRY_mn | verified |

KFE'nin endeks olduğu bilinmektedir; ancak baz yılı doğrulanmadığı için güven
seviyesi `derived` tutulur. Bu durum farklı bazlı endekslerin sessizce
birleştirilmesini engelleyen bir uyarıdır.

## Silver ve agent nasıl kullanacak?

Silver, `series_id` üzerinden `meta.series` ile eşleşerek `unit`, `frequency`,
`measure_type`, `default_agg` ve `semantic_confidence` alanlarını alır. Agent ise
`name_tr`, `description`, `aliases` ve `tags` alanlarıyla doğru seriyi bulur.

## İlgili commitler

- `ab80f40` — semantic series catalog uygulaması
- `8ab6df2` — BDDK Haftalık ve provenance ile birleşmiş, 322 testli sürüm

Bu çalışma `feature/lakehouse-integration` dalına alınmıştır.
