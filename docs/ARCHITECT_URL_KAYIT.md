# Architect: web sayfasından kalıcı veri kaydı

## Değişen davranış

`ingest_from_url` artık doğrudan veri dosyalarının yanında HTML rapor sayfalarını
da kabul eder. Kullanıcının verdiği sayfanın seçili `#bölüm` kısmındaki gerçek
indirme bağlantıları listelenir. PDF uzantısı olmayan `/download/...` adresleri
içerik türü ve dosya imzasından tanınır. Metin içeren, çizgilerle ayrılmış PDF
tabloları `pdfplumber` ile okunur; uygun tablo bulunamazsa yapılandırılmış OCR
istemcisi kullanılır. Yerel PDF/görsel yüklemeleri mevcut OCR yolunu kullanmaya devam eder.

Model seçimi şu parametrelerle yapar:

| Parametre | İşlev |
|---|---|
| `locator` | Kullanıcının verdiği başlangıç adresi, sorgu ve bölüm bilgisi korunur |
| `resource_index` | Sayfadaki indirilebilir ek (0 tabanlı) |
| `pages` | PDF'nin fiziksel sayfaları: `4`, `4-5`; varsayılan ilk 5 sayfa |
| `table_index` | Bulunan tablolar arasında seçim (0 tabanlı) |
| `value_row` | Ölçümleri satırlarda gösteren aylık tabloda kaydedilecek satırın tam etiketi |
| `series_key` | Kaydedilecek ölçüm için ayrı seri anahtarı |

Tek dosya/tablo varsa otomatik seçilir; birden çok seçenek varsa araç liste
döndürür. Ajan, kullanıcının istediği rapor/ölçüm belliyse aynı araçla seçimi yapar.
`EKLENMEDİ` ara adımdır. Başarılı yazmada `EKLENDİ`, satır sayısı, işlem kimliği
ve kaynak kanıtları döner. Bir kullanıcı isteği açıkça belirli bir ölçüm içermiyorsa
ajan seçim sorusu sorabilir. Her rapordaki bütün ölçümler tek seride birleştirilmez.

## Risk Merkezi örneği

Kaynak:
https://www.riskmerkezi.org/istatistiki-raporlar-liste/2541?rapor_donemi[]=2602&ay[]=7#collapseContent-15181

Architect profilinde örnek kullanıcı mesajı:

> Bu URL'deki Temmuz 2026 Aylık Bülten raporundan kurumlara göre nakdi kredi
> tutarlarını veri havuzuna taslak olarak kaydet. Seri anahtarı
> riskmerkezi_nakdi_kredi_202607 olsun.

Bu kaynağın incelenen sürümünde:

1. `resource_index=1`: **RM Aylık Bülten - Temmuz 2026**.
2. `pages="4"`, `table_index=0`.
3. `value_row="Nakdi Krediler (2) (Milyar TL)"`.

Tablonun ilk başlığı `Temmuz 2026` olduğu için gözlemler aylık dönem sonu
`2026-07-31` tarihine bağlanır. Kurum başlıkları `entity_id` olur. Kaynağın Türkçe
sayı gösterimiyle `27.790` değeri **27790** olarak ayrıştırılır; ölçek değişmez,
birim `TRY_bn` (milyar TL) olarak kaydedilir. Toplam satırı ayrıca korunur;
kurumların toplamını alırken bu satır ikinci kez toplanmamalıdır.

Canlı araç → CLI → DuckDB denemesinde okunan kayıtlar:

| Kurum | Değer (milyar TL) |
|---|---:|
| Bankalar | 27790 |
| Finansman Şirketleri | 326 |
| Faktoring Şirketleri | 371 |
| Finansal Kiralama Şirketleri | 476 |
| Toplam | 28963 |

Bu deneme sohbet modelini çağırmadan gerçek Architect aracını çalıştırır;
modelin konuşma içindeki seçimleri ayrıca değerlendirilmelidir.

## Kaydın yeri ve kanıtı

- Gözlemler: `adhoc.fact_observation`.
- Katalog: `meta.series`, durum `draft`, güven `derived`.
- RAW/Bronze: çıkarılan CSV'nin standart lakehouse hattındaki kopyaları.
- Orijinal HTML/PDF: izinli yükleme klasöründeki `source_<sha256>.*` dosyaları.
- Kaynak zinciri: `source_manifest_<sha256>.json`; ayrıca katalog açıklamasında
  başlangıç sayfası, indirilen belge adresi, hash'ler, sayfa ve dönüşüm bilgisi.

Kaynak bu alanlarda açıklık sağlamıyorsa ölçüm tipi `unknown` kalabilir;
örneğin yukarıdaki testte insanın stok/akım beyanı verilmediğinden `unknown`
kaydedilmiştir. İnsan onayı olmadan Silver'a terfi ve Gold üretimi yapılmaz.

## Sınırlar

- İndirme keşfi seçilen bölüm ve aynı hosttaki gerçek dosya bağlantılarıyla sınırlıdır;
  JavaScript çalıştırılmaz, grafik API'leri otomatik keşfedilmez.
- PDF yerel okuma metin katmanında çizgilerle ayrılmış tablolar içindir; diğer
  PDF/görseller mevcut MIA OCR yapılandırmasına ihtiyaç duyabilir.
- Aylık satır/sütun dönüşümü, ilk sütun başlığında açık Türkçe ay ve yıl bulunan
  tablolar içindir. Başka tablolar tarih/değer kolonlarıyla mevcut profilciye gider.
- Tek tarihli veya düzensiz veri için frekans kaynaktan belirlenemiyorsa kullanıcıya
  sorulur; katalogun reddettiği `irregular` ile yazma komutu çalıştırılmaz.
- Excel formülleri ve dış dosya bağlantıları CSV'ye dönüştürülerek içeri alınmaz.

## Çalıştırma ve kontrol

İki pakette kendi bağımlılıklarını kurun (`agent-core`: `uv sync --extra dev`,
`lakehouse-core`: `uv sync --frozen`). Architect uygulaması bu kod sürümünden
başlatılmalıdır; farklı çalışma klasöründeki uygulama bu değişikliği kendiliğinden almaz.

`agent-core` içinde PowerShell ile izole canlı test:

```powershell
.venv/Scripts/python.exe scripts/verify_url_ingest.py `
  --url 'https://www.riskmerkezi.org/istatistiki-raporlar-liste/2541?rapor_donemi[]=2602&ay[]=7#collapseContent-15181' `
  --resource-index 1 --pages 4 --table-index 0 `
  --value-row 'Nakdi Krediler (2) (Milyar TL)' `
  --series-key riskmerkezi_nakdi_kredi_202607 `
  --output-root '../data/riskmerkezi-url-test'
```

Komut belirtilen test klasörüne DB, kaynak kopyaları ve `result.json` yazar;
uygulamanın `.env` dosyasındaki DB'yi kullanmaz.

```sql
SELECT observation_date, entity_id, value, unit
FROM adhoc.fact_observation
WHERE series_id = 'adhoc:riskmerkezi_nakdi_kredi_202607';
```
