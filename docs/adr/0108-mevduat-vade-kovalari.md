# ADR-0108: Mevduat vade kovaları: ham aylık seri, çalışma anında gruplama

**Durum:** Kabul edildi · **Tarih:** 2026-09-23 · **İlgili:** ADR-0031, ADR-0106, ADR-0107

## Bağlam
Mevduatın açılış vadesine göre dağılımını isteyen sorular ("6 aya kadar vadeli TP mevduat", "1 yıldan uzun vadeli
DTH") cevaplanamıyordu. Ajan bu soruda aramaya bütçe harcıyor, tablo vermiyor ve bulduğu seriyi "eşleşmiyor" diye yanlış
raporluyordu.

Kök neden veridedir:
- BDDK Aylık Bülten'in "Mevduat Vade İtibarıyla" tablosunda 24 kalem var (kalem kimliği 520–543). 23 Eylül'de kaynağın
  `KalemSutunGetir` yanıtıyla doğrulandı: her kalem aynı 7 sütunu yayımlıyor.

  | `kalemSutun` eki | Kaynağın etiketi | Vade aralığı (ay) |
  |---|---|---|
  | `Vadesiz` | Vadesiz | [0, 0] |
  | `BirAyaKadar` | 1 Aya Kadar | (0, 1] |
  | `BirAyUcAy` | 1-3 Ay Arası | (1, 3] |
  | `UcAyAltiAy` | 3-6 Ay Arası | (3, 6] |
  | `AltiAyBirYil` | 6-12 Ay Arası | (6, 12] |
  | `BirYil` | 1 Yıl Üzeri | (12, ∞) |
  | `Toplam` | Toplam | tümü |

- Katalog (`lakehouse-core/catalog/series/bddk_monthly.yml`) `generate_bddk_monthly_catalog.py` ile her kalemin yalnız ana
  sütunu (`Toplam`) alınarak üretildi. 24 kalemin Toplam serisi havuzda; 144 vade kovası serisinin hiçbiri yok.
- Vade, gözlem sıklığıyla karıştırılmamalıdır. Aylık Toplam serisi "3 ay önceye göre değişim", "5 yıllık değişim",
  "çeyreklik" gibi **zaman ufuklarını** üretebilir. Ama toplamın vadelere nasıl dağıldığını hiçbir hesap üretemez; bu bilgi
  yalnız kaynağın vade sütunlarındadır.

## Karar
1. **Ham kova, aylık seri.** 24 kalemin 6 vade kovası katalogda ayrı aylık seri olur: `bddk_monthly:<kalem>_<ek>` (ör.
   `bddk_monthly:520_BirAyUcAy`), `native_code` kaynağın kendi `kalemSutun` değeri (`520?BirAyUcAy`). Birim, ölçü türü ve
   toplama kuralı Toplam serisiyle aynı: `TRY_mn`, `stock`, `last`. Havuza yalnız bu ham kovalar yazılır. Gruplar ("6 aya
   kadar", "1 yıldan fazla") hiçbir zaman seri olarak yazılmaz.
2. **Kova anlamı ilişki grafında.** Kova serisi, aynı kalemin Toplam serisinin `child_breakdown`'ıdır. Toplam
   `parent_total` ve `additive` olarak işaretlenir. Kovanın aralığı `dimension_path`'e makine okunur biçimde yazılır:
   `vade=<kaynak etiketi>` ve `vade_ay=<aralık>` (ör. `vade_ay=(1,3]`, `vade_ay=[0,0]`, `vade_ay=(12,inf)`).
   `meta.series` sözleşmesine alan eklenmez.
   - İlişki `lakehouse-core/src/lakehouse/catalog/relations.py` içinde, BDDK kalem ağacı kuralları gibi kaynak kimliğinden
     (`<kalem>?<ek>` + vade tablosu) üretilir. YAML yükleyicisi ilişki alanlarını kabul etmediği için "açık YAML ilişkisi"
     yolu bugün kullanılamaz; bu ADR onu açmaz.
3. **Gruplama deterministik ve çalışma anında.** Ajan vade ifadesini bir ay aralığına çevirir. Hangi kovaların toplanacağına
   ilişki grafındaki `vade_ay` aralıklarına bakarak model değil kod karar verir. Grup sütunu çalışma alanında hesaplanır,
   kanıtında toplanan kovalar adlarıyla yazılır ve takip turlarına taşınır.
   - Tamamlayıcı grup kovaların toplamıyla hesaplanır, Toplam'dan çıkarmayla değil. Toplam yalnız denetim içindir:
     kovaların toplamı Toplam'dan yuvarlama payından fazla saparsa uyarı verilir.
4. **Kovayı bölen istek en yakın kovaya gider ve söylenir.** Kaynağın sınırları {0, 1, 3, 6, 12} aydır. İstek bir kovanın
   içinde kalıyorsa, isteği kapsayan en dar kova kümesi kullanılır ve cevabın ilk cümlesinde yazılır:
   - "5 yıl vadeli" → 1 Yıl Üzeri (kaynak 1 yıldan uzun vadeyi ayrıca yayımlamıyor).
   - "2 aya kadar" → kaynak bu sınırı yayımlamadığı için isteği kapsayan en dar kova kümesi kullanılır.
   - "4 aydan fazla" → aynı kural; 4. ay sınırı da yayımlanmıyor.
   Hiçbir durumda bir kova oranlanarak bölünmez; kaynağın yayımlamadığı sayı üretilmez.
5. **Vade ile zaman ufku ayrı niyetlerdir.** "N aya kadar vadeli / vadesi N aydan uzun / vade kırılımı" vade isteğidir ve bu
   kovalarla karşılanır. "N aya göre değişim / N aylık toplam / N yıllık değişim" zaman ufkudur ve aylık seride pencere/LAG
   hesabıyla karşılanır. Ayrım `core/turn_intent.py`'de yapılır.
6. **Aylık hareket için bir önceki ay gerekir.** Stoktan aylık hareket (bu ay − önceki ay) istendiğinde dönemin ilk ayı
   için bir önceki ayın gözlemi kullanılır; yoksa hareket boş kalır, sıfır yazılmaz. 23 Eylül'de 520 ve 524'ün Toplam serisi
   havuzda 2021-01'den başlıyordu (aynı hattaki 1534 2016-01'den). Faz 1'de vade grubunun hem Toplam hem kova serileri,
   projenin ortak başlangıcıyla (2016-01) alınır; kaynağın 2021 öncesini bu kalem kimliğiyle verip vermediği canlı
   doğrulanır ve sonucu `docs/sources/bddk_monthly.md`'ye yazılır.
7. **Aktif tablo korunur.** Aktif tablo varken yeni bir kaynak "eklenmek" istendiğinde (ör. mevduat tablosuna TÜFE) önceki
   sütunlar düşürülmez, tablo yenisiyle değiştirilmez. Yeni seri mevcut tabloya ay anahtarıyla eklenir. Ay anahtarı
   biçimden bağımsızdır: `202403`, `2024-03`, `2024-03-31` aynı aydır. Benchmark'taki D08 hatası (`gold_align` aktif tabloyu
   ezdi) bu kuralın ihlalidir.
8. **Reel değer seri seri hesaplanır.** Reel = Nominal × TÜFE(baz ay) / TÜFE(t); baz ay kullanıcının istediği aydır.
   **Açık karar (onay bekliyor):** tablo aylık hareket tutuyorsa varsayılan, harekete doğrudan uygulamaktır
   (Δnominal_t × TÜFE(baz) / TÜFE(t)). Alternatif, önce reel stok hesaplayıp sonra farkını almaktır; iki yol farklı sayı
   verir. Uygulamada varsayılan kullanıldı (aşağıda "Uygulama"); değiştirilirse bu madde güncellenir.
9. **Uygulama sırası.**
   - **Faz 1 (veri):**
     - Katalog üretecine grup kapsamlı sütun seçimi ve 144 kova serisi.
     - İlişki kuralı.
     - 2016-01'den yükleme (2021 öncesi kaynaktan doğrulanarak).
     - Kova toplamı = Toplam kalite kapısı.
   - **Faz 2 (ajan):**
     - Vade ifadesi çözücü, kova çözücü, gruplama aracı ve niyet ayrımı.
     - Aylık hareket.
     - Aktif tablonun korunması ve ay anahtarı normalizasyonu.
     - Reel değer.
   - **Faz 3:** bir cevapta birden fazla tablo (ayrı ADR).

## Sonuçlar
- Vade kırılımı isteyen soru, Faz 1 ve 2'den sonra kaynağın kendi kovalarıyla, yeni türetilmiş veri yazmadan cevaplanır.
  Kova sınırına denk gelen her kesim (1, 3, 6, 12 ay) aynı 6 kovadan üretilir.
- Kaynağın yayımlamadığı bir sınır (2 ay, 5 yıl) üretilemez; ajan en yakın kapsayan kovayı açıkça belirterek verir.
- Havuz 144 aylık seri büyür (2016-01'den itibaren aylık, kalem başına 6 sütun). Bu, veri kapsamının bilinçli bir
  genişlemesidir; üretim adımları `docs/sources/bddk_monthly.md`'ye işlenir.
- Kalemler arasındaki toplam ilişkileri (ör. 1 = 1.1 + 1.2 + 1.3; 9 = 4 + 8) bu ADR'nin kapsamı dışındadır; ilişki grafına
  ayrıca eklenebilir.

## Uygulama (23 Eylül)
**Faz 1 (veri):**
- **Katalog:** `generate_bddk_monthly_catalog.py --group … --add-columns` ile 144 kova serisi eklendi; mevcut girişlerin hiçbiri
  değişmedi.
- **İlişki grafı:** `relations.py` kova ilişkisini kaynak kimliğinden kuruyor.
- **Yükleme:** 2016-01'den itibaren yapıldı.
- **Kalite kapısı:** `check_breakdown_sums.py` 24 toplam × 126 ayda uyumsuz ya da eksik ay bulmadı.
- **Diğer seriler:** Vade grubu dışındaki bütün seriler ve Gold tabloları yedekle birebir aynı.

**Faz 2 (ajan):**
- **`lakehouse_breakdown_panel`:**
  - Serileri ve kova gruplarını tek aylık eksende verir. Kova seçimi ilişki grafından yapılır; "X aya kadar" Vadesiz'i
    kapsar.
  - `value=monthly_change` bütün sütunlara uygulanır ve önceki ayı kendisi çeker.
  - Grupların toplamı toplamla denetlenir.
  - Haftalık ve günlük seriler katalogdaki `default_agg` kuralıyla aylığa iner.
  - `join_session`, `deflator_series_id` ve `index_base` ile oturum tablolarını ay üzerinden ekler, reel hâle getirir,
    tutarları endeksler.
- **Kurallar:**
  - SQL ile iki ya da daha fazla vade kovasını elle toplayan sorgu reddedilir ve panele yönlendirilir.
  - Soru "stok olmasın / o aydaki / aylık hareket" diyorsa panel `value=level` çağrısını reddeder.
  - Panel istenen tabloyu ürettiyse ve soru türev, grafik ya da yorum istemiyorsa tur deterministik teslim edilir.
- **Madde 7 (aktif tablo korunur):**
  - "Mevcut veri seti / reel / fiyatlarıyla" takibinde önceki turdan kalan tabloyu baştan kuran çağrılar (`gold_*`,
    panel, aktif tablo kipinde `lakehouse_query`) çalıştırılmaz.
  - Bu turda kurulan tablolar kapsam dışıdır (tablo kuşağı, ADR-0106).
  - Kaynak uyuşmazlığı reddi, aktif tablo varken "yeniden çekme, yeni seriyi ekle" diye yol gösterir.
- **Madde 8 (reel değer):** `workspace_real_value` birden çok tutar sütununu tek çağrıda çevirir (`value_columns`); endeks
  sütunu bir kez eklenir. Açık karar varsayılanla uygulandı: hareket tablosunda reel değer harekete doğrudan uygulanır.
- **Ay anahtarı:** `workspace_join` `key_policy='ay'` ile `202403`, `2024-03` ve `2024-03-31`'i aynı ay sayar. Bu kural
  otomatik öneri listesinde yoktur, çünkü gün düzeyindeki tarihleri birleştirir; yalnız aylık birleştirme istendiğinde
  açıkça seçilir.
- **Çok kaynaklı analiz:**
  - Soru iki ya da daha fazla kaynak adı ve birleştirme istiyorsa o tur için arama bütçesi ve adım sınırı +8 artar.
  - Oturumda iki ya da daha fazla hazır tablo varsa modele tablo listesi ve "önce bunları ay üzerinden birleştir" notu
    verilir.
  - `gold_join` reddi turu bitirmez; aynı seriler panele yönlendirilir.
  - "Kırılma … yorumla" isteğinde web araçları açılır.
- **Kaynak seçimi:** Genel "USD/TL / dolar kuru" isteği döviz satış kuruna gider (`evds:TP.DK.USD.S.YTL`, 2016'dan
  yüklendi); alış kuru yalnız "alış" dendiğinde kullanılır. Faiz serisinin ilk takma adı ve tablo etiketi "3 aya kadar
  vadeli TL mevduat faizi". Teslim özeti yalnız kullanıcıya görünen sütunları, arayüzle aynı etiketlerle listeler.

## Gerçek koşu düzeltmeleri (23 Eylül akşam)
Uygulama, demo senaryosunun birebir soru metinleriyle, aynı sohbette ve her tekrarda temiz ajanla gerçek uçtan uca koşuldu
(mock yok). Soru metinleri ve beklenen çıktılar repoya girmez. Koşularda görülen hatalar ve düzeltmeleri:
- **Grup toplamı kendiliğinden:** Grubu istenen toplam `series` alanında yoksa panel onu tabloya ekler (`tp_toplam`). Model
  toplamı unutunca tablo yalnız grupları taşıyordu.
- **Önceki tablo taşınır (madde 7'nin tamamlayıcısı):** Takipte yeni bir seri ekleniyorsa (reel isteği değilse) tabloyu
  yeniden kuran çağrı çalışır; önceki tur tablosunun sütunları ay anahtarıyla yeni tabloya taşınır. Kanıt sütunları
  (`::quality_flag`, `::observations` …) taşınmaz. Faiz/kur takibi mevduat tablosunu düşürüyordu; "mevcut mevduat veri seti"
  ifadesi koruma deseninde yoktu, desen genişletildi.
- **Reel değer yedeği:** Soru reel değer istiyor ve tur `workspace_real_value` (ya da panel) çağrılmadan kapanacaksa harness
  aracı bir kez kendisi uygular: doğrulanmış fiyat endeksi (TÜFE Genel önce), aktif tablodaki tutar sütunları, sorudaki baz ay
  ya da tablonun son ayı. Yeniden kurma reddi ya da kaynak uyuşmazlığından sonra sıradaki iterasyonda çalışır ve o
  iterasyonda terminal kapanış bekletilir. Üç tekrarda da model reel aracı hiç çağırmamıştı.
- **İstenen yetenek:** "reel" ve "kırılma … yorumla" (web araştırması) istenen yetenekler listesine girdi. Karşılanmamış
  yetenek kurtarma istemine de yazılır; kurtarma turu konuşmayı kısalttığı için yetenek denetimine sıra gelmiyordu.
- **Doğrulanmamış endeks reddi turu bitirmez:** Model türetilmiş bir endeks seçtiğinde, havuzda doğrulanmış bir endeks varsa
  ret "aynı çağrıyı doğrulanmış endeksle yinele" diye yol gösterir.
- **Birleştirmede kanıt sütunu yok:** `workspace_join` varsayılan sütun seçimi ve panelin oturum birleştirmesi kanıt
  sütunlarını almaz.
- **Uygunluk metni kısa:** Uygunluk gerekçelerindeki seri listeleri en fazla 6 okunur adla sınırlandı (`::` iç adları çıkar).

**Sonuç (3 tekrar, gerçek model):**
- İlk tur: aylık hareket, vade grupları ve kontrol ayları 12/12, 3/3 tekrar.
- İkinci tur: TÜFE 3/3, dört tutar sütununun reel karşılığı, baz ayda reel = nominal; 3/3 tekrar.
- Üçüncü tur: 3 aya kadar vadeli TL mevduat faizi ve USD/TL satış kuru 3/3, 3/3 tekrar.

**Açık (bu ADR'de çözülmedi):**
- Soru hem "enflasyondan arındır" hem çok kaynaklı birleştirme istediğinde tablo koruma kuralı paneli (`join_session`)
  engelliyor. Model bu durumda endeksi `workspace_compute_column` ile aylık hareket sütunlarında kuruyor; taban ayı negatif
  olan akım serisinin "endeksi" anlamsız çıkıyor. Endeks seviye (stok) serisi üzerinden kurulmalı.
- Yüklenen dosyayla zenginleştirme ve çok kaynaklı yorum turları bu PR'ın kapsamı dışında, ayrıca ele alınıyor.
