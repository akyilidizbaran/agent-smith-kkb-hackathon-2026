# Branch özeti — `feature/agent-data-p0`

**Sahiplik:** Data/Lakehouse ekibi

**Taban teslim:** Silver V1 kabul ve veri güveni düzeltmeleri

**Kod kontrol noktası:** `f1e17adb63d7d3047533a53afa980999960ca6c8`

**Amaç:** Agent ekibinin Silver verisini güvenli biçimde kullanmasını engelleyen ilk üç
P0 ihtiyacını kapatmak.

## Neden yapıldı?

Agent, konut kredilerini enflasyondan arındırmak için TÜFE serisine, sorulan tarih
aralığının elde bulunup bulunmadığını denetlemek için seri kapsamına ve hesapları gerçek
Lakehouse dosyası üzerinde yapabilmek için güvenli bir sorgu yoluna ihtiyaç duyuyordu.
Bu branch bu üç ihtiyacı birbirinden bağımsız testlerle kanıtlar.

## Tamamlanan P0 teslimleri

### 1. TÜFE katalog ve Silver eşlemesi

- `evds:TP.FG.J0` katalog kaydı eklendi.
- EVDS adapter'ı katalogdan beslenen genel eşleme yoluyla seriyi Silver'a taşıyor.
- Seri bir **endeks seviyesidir**; aylık değişim oranı değildir.
- Kod ve sözleşme testi hazırdır fakat repodaki EVDS zarfı sentetiktir.
- Keyed EVDS yanıtı ve resmî baz-yıl kanıtı eklenene kadar güven seviyesi `derived` ve
  kaynak `manual` olarak kalır.

### 2. Seri kapsamının otomatik yenilenmesi

`silver.fact_observation` materyalizasyonu başarılı olduğunda `meta.series.first_obs` ve
`last_obs` aynı transaction içinde yeniden hesaplanır. Yeni snapshot'ta bulunmayan bir
serinin eski kapsamı temizlenir; boş snapshot bütün kapsamları temizler; Silver tablosunun
yokluğu ise hata üretir.

Bu sayede agent, istenen dönemin gerçekten mevcut olup olmadığını katalogdan denetleyebilir
ve veri olmayan yıllar için sonuç uydurmaz.

### 3. Güvenli Agent → Silver sorgu kanıtı

Entegrasyon testi gerçek, dosya tabanlı DuckDB üzerinde Silver snapshot oluşturur; ardından
veritabanını `connect_untrusted` ile açıp `QueryExecutor` üzerinden
`silver.fact_observation` sorgular. Güvenli tek-statement/yalnız-okuma sınırı korunurken
satırların okunabildiği doğrulanır.

## Birlikte gelen güven düzeltmesi

Parquet/Arrow dönüşünde kaynak `NULL` değerinin `NaN` gibi görünmesine yol açabilecek string
dtype farkı giderildi. Kaynak null değeri Silver'a kadar null olarak korunur ve
`quality_flag=missing_value` semantiği bozulmaz.

## Doğrulama sonucu

```text
Tüm test paketi              576 passed
Silver acceptance             37 passed
Yeni Agent/Data P0 testleri   35 passed
uv lock check                 passed
build                         passed
demo-check                    passed
diff-check                    passed
```

Canlı EVDS ağı bu testlerin parçası değildir. Dış sistem davranışı hakkında doğrulanmamış
bir iddia üretilmez.

## Bilinen dış kanıt eksiği

TÜFE kaydının `verified` yapılabilmesi için aşağıdakiler repoya alınmalıdır:

1. Gerçek keyed EVDS uç noktasından alınmış `TP.FG.J0` yanıt fixture'ı.
2. Credential içermeyen istek URL biçimi ve yakalama tarihi.
3. Baz yılını doğrulayan resmî TCMB veya TÜİK kaynağı.

Bu eksik uygulamayı engellemez; yalnızca semantik güven beyanını sınırlar.

## Kapsam dışı ve sıradaki işler

Bu branch Baran'ın veri ekibi talep belgesinin tamamı değildir. Kalan işler ayrı,
odaklı teslimlerde yürütülecektir:

1. Gold: `align_frequency`, `decompose_cumulative`, `join_on_period`.
2. Generic connector/parser, programatik `register_series`, `adhoc.fact_observation`.
3. `bootstrap`, `ingest`, `ingest-file` çalıştırılabilir girişleri ve EVDS windowing.
4. Katalog genişletme ve FinTürk.

Gold fonksiyonları `measure_type`, `default_agg` ve `week_anchor` değerlerini modelden
parametre olarak kabul etmemeli; çağrı anında `meta.series` kataloğundan okumalıdır.
`semantic_confidence` değeri `derived` veya `unknown` olan serilerde otomatik dönüşüm
fail-closed davranmalıdır.

## Birleştirme notu

Bu branch küçük ve test edilmiş bir teslim kontrol noktasıdır. Önce ortak integration
branch'ine PR ile alınmalı; Gold branch'i bu kabul edilmiş kontrol noktasından açılmalıdır.
Bu sayede sonraki teslimler bağımsız incelenebilir ve gerektiğinde ayrı geri alınabilir.
