# Branch özeti — `feature/source-access-hardening`

**Sahip:** Elif Güngen

**Amaç:** Çalışan Source Access ilk sürümünü, sessizce yanlış seri alma ve güvenlik
hatalarına karşı sağlamlaştırmak; bunu yaparken Bronze/Silver sözleşmesini gereksiz yere
genişletmemek.

## Neler yapıldı?

- `TP.KFE.TR` konut fiyat endeksi mevcut genel `EvdsConnector` ve `EvdsParser` ile
  ikinci bir uçtan uca senaryoda RAW'dan Bronze'a taşındı. Kaynağa özel yeni sınıf
  yazılmadı.
- BDDK Haftalık'ın pozisyonel `id=1.0.4` adresi, cevap başlığındaki seri adı, para
  birimi ve sütunla doğrulanır hâle getirildi. Bülten sırası değişirse yanlış seri
  sessizce kabul edilmiyor.
- BDDK Aylık ve Haftalık connector'larında TLS doğrulama hatası kalıcı ve güvenli
  biçimde sınıflandırıldı; aynı istek boşuna tekrar edilmiyor ve TLS doğrulaması hiçbir
  koşulda kapatılmıyor.
- BDDK Aylık gelişmiş endpoint'inin `BasitFont`/`parent` taşımadığı, basit rapor
  endpoint'inin ise `BasitFont` gösterim sinyalini taşıdığı gerçek cevap fixture'larıyla
  kaydedildi.
- BDDK'nın yayımlanmış değerleri revize edebilmesi kaynak gerçeği olarak belgelendi;
  dataset version/revision yaşam döngüsü Source Access'e gizlice eklenmeyip ortak
  altyapı işi olarak bırakıldı.

## Bilinçli mimari kararlar

### Grafik adresi seri kimliği değildir

`1.0.4` bültendeki konuma bağlıdır. Kalıcı seri kimliği `kalem_id=5690` üzerinden
`bddk_weekly:5690_3` olarak üretilir. Beklenen başlık alanları HTTP isteğine gönderilmez;
yalnız request metadata'sında tutulur ve parser'ın kaynak cevabını doğrulamasını sağlar.

### `bold` otomatik olarak `subtotal` değildir

İçe aldığımız gelişmiş aylık endpoint stil alanı üretmiyor. Bu yüzden V1 Bronze şemasına
daima `NULL` kalacak spekülatif kolonlar eklenmedi ve `is_subtotal` türetilmedi. İleride
basit rapor transport'u seçilirse kaynak stilinin korunması açık bir parser/schema V2;
finansal subtotal yorumu ise Silver kararı olmalıdır.

### TLS kapatılmaz

BDDK alan adının eksik ara sertifika zinciri OpenSSL ile yeniden doğrulandı. Connector
`SSLError` durumunda güvenli, secretsız ve `retryable=False` hata üretir. Dağıtımda uygun
CA bundle sağlamak Infrastructure sorumluluğudur; `verify=False` kabul edilmez.

## Doğrulama kapısı

- Tüm test paketi: **357 passed**
- `uv sync --frozen`: başarılı
- `uv lock --check`: başarılı
- `make build`: başarılı
- `make demo-check`: başarılı
- Testler dış ağ bağlantısı olmadan çalışır; KFE testi canlı EVDS doğrulaması değildir.

## Ortak ekipte kalan işler

- BDDK CA bundle'ını çalışma ortamına güvenli biçimde eklemek
- `dataset_version` / revision yaşam döngüsünü tasarlamak
- Haftalık tatil günleri, birim ve frekans dönüşümlerini Silver'da uygulamak
- EVDS anahtarı geldiğinde resmî endpoint'e dar canlı smoke test yapmak

Bu çalışma `feature/lakehouse-integration` dalına alınmıştır.
