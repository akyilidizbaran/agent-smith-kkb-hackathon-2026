# Branch özeti — `feature/lakehouse-integration`

**Sahiplik:** Data/Lakehouse ekibinin ortak entegrasyon dalı

**Amaç:** Altyapı, Source Access ve semantic catalog çalışmalarını tek bir
çalışan sistem üzerinde doğrulamak.

## Bu dalda birleşen çalışmalar

- Ortak Python/uv proje temeli
- DuckDB bootstrap ve güvenli bağlantı sınırı
- Değişmez RAW ve Parquet storage
- SHA-256 artifact kimliği
- Artifact ile request provenance ayrımı
- EVDS Connector + Parser
- BDDK Aylık Connector + Parser
- BDDK Haftalık Connector + Parser
- BDDK Haftalık pozisyonel chart-id sapma koruması
- BDDK TLS hata sınıflaması
- İkinci EVDS serisi (`TP.KFE.TR`) için genel connector/parser E2E kanıtı
- RAW → Parser → Bronze integration akışı
- `meta.series` semantic metadata catalog

## Güncel durum

```text
Kaynak → Connector → RAW → Parser → Bronze    ✅
Semantic Catalog                              ✅
Bronze + Catalog → Silver                     aktif çalışma
Silver → Gold                                 sıradaki aşama
Gold + izinli Meta → Agent                    sonraki aşama
```

Source Access hardening birleşmesi sonrasında:

- 357 test geçmektedir.
- Build başarılıdır.
- Offline demo-check başarılıdır.
- Catalog dört başlangıç serisini içermektedir.

## Neden agent henüz bağlanmıyor?

Bronze kaynağa sadıktır fakat ortak iş semantiğini henüz taşımaz. Agent'ın
Bronze'a doğrudan erişmesi stok/akım karışıklığına, yanlış toplama ve kaynak
ayrıntılarına bağımlılığa yol açabilir. Önce ortak Silver modeli ve analiz için
hazır Gold yüzeyi tamamlanacaktır.

## Sıradaki kabul kapısı

1. BDDK aylık kredi bakiyesi Silver'a dönüşecek.
2. EVDS haftalık faiz serisi Silver'a dönüşecek.
3. Haftalık faiz güvenli kuralla aylık frekansa indirilecek.
4. İki kaynak Gold katmanında ay üzerinden birleştirilecek.
5. Agent yalnız Gold ve izin verilen Meta tablolarını sorgulayacak.

Bu kapı geçmeden integration dalı agent-ready kabul edilmez.
