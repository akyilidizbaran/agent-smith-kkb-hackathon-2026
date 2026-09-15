# ADR-0082 — Kullanıcıya dönük metinde iç kimlik ve veri mimarisi adı yok

**Tarih:** 15 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** kullanıcının arayüz denemesi ve kararı (15 Eylül akşam)

## Bağlam

Kullanıcı arayüzde "Elinde nasıl veriler var" diye sordu. Cevap:
- veri kaynaklarını sayarken "**4. Hazır Gold tabloları (aylık/çeyreklik karşılaştırma)**" başlığı açtı;
- "Toplamda 687+ seri" yazdı (doğrusu 681).

Kullanıcının itirazı: Gold, veri gölü mimarisinin iç katmanıdır (Silver'daki kaynak verisinden hesaplanmış tablo); kullanıcıya
kaynak gibi söylenmemeli.

İnceleme (oturumun kayıtlı adımları ve kod):
- **Soru deterministik yola girmedi.** "Hangi veri setlerine sahipsin" kalıbı (ADR-0078) yalnız "hangi / ne / neler" ile başlayan
  soruyu tanıyordu. Soru modele gitti; model 5 katalog aramasından sonra cevabı kendisi yazdı.
- **Model iç adı araç kartından ve istemden aldı.** Arama kartı tabloları `gold.konut_faizi_aylik` gibi kimliklerle gösteriyordu.
  Gold istem kuralı "Hazır Gold tabloları" diye konuşuyordu. Sistem istemi SQL, kolon adı ve araç adını yasaklıyordu, katman adını
  ve tablo/seri kimliğini yasaklamıyordu.
- **Grafik altyazısı ve HTML rapor iç etiket yazıyordu.** Kolon kaynağı etiketleri ("bddk_monthly — …", "gold — join_on_period")
  olduğu gibi yazılıyordu.
- **Tablosuz turda sayı denetimi yoktu.** Aktif tablo olmayan ve veri çekilmemiş turda (yalnız katalog araması) cevaptaki sayılar
  hiçbir kapıdan geçmiyordu; "687+" buradan çıktı.
- **Arayüz sayaçları.** Sol panel ve durum penceresi "Silver gözlemi / Gold tablosu" diyordu.

## Karar

- **İki ayrı yüzey.**
  - Kanıt zinciri (sağ panel, kanıt yolculuğu, izlenebilirlik kaydı) katman adlarını ve kimlikleri taşımaya devam eder; jürinin
    izlediği veri yolu budur (kullanıcı onayı).
  - Cevap metni, grafik başlığı ve altyazısı, HTML rapor "Kaynaklar" listesi ve sol panel sayaçları kullanıcının diliyle yazılır:
    kurumun adı, "hesaplanmış tablo", "kullanıcının eklediği seri".
- **Deterministik veri seti cevabı genişledi** (`core/small_talk.py`). "nasıl / ne tür / ne çeşit veriler var" ve "hangi verilerle
  çalışıyorsun" da katalogdan, model çağrılmadan cevaplanır.
- **İstem.**
  - Sistem istemi cevapta tablo/seri kimliğini ve katman adlarını (Gold, Silver, Bronze, RAW, lakehouse) yasaklar. Hesaplanmış
    tablo, hangi kaynağın verisinden ve hangi kuralla hesaplandığıyla anlatılır. Kural alan bağımsızdır; finans terimi taşımaz,
    alan bağımsızlık testleri geçer.
  - Gold istem kuralı da "Gold deme, hesaplanmış tablo de" der.
- **Arama kartı her tablonun kaynağını yazar** (`labels.spec_origin`). Örnek: "kaynak: hesaplanmış tablo (TCMB EVDS ve BDDK Aylık
  Bülten verisinden)". Kimlik SQL için kartta kalır.
- **Okunur kaynak etiketi tek yerde** (`labels.readable_source`). Grafik altyazısı ve rapor kaynakları bundan geçer:
  - "bddk_monthly — X" → "BDDK Aylık Bülten — X";
  - "gold — join_on_period" → "hesaplanmış tablo — dönem eşlemeli birleştirme";
  - kullanıcı serisi → "kullanıcının eklediği seri — …".
- **Son güvence** (`labels.humanize_internal`). Model yine de kimlik ya da katman adı yazarsa cevap kullanıcıya gitmeden
  deterministik çevrilir ve sohbet geçmişine sade metin girer:
  - kimlik katalogdaki okunur adla, bilinmiyorsa kurum adıyla ("TCMB EVDS serisi") yazılır;
  - "Gold tablosunda" → "hesaplanmış tabloda", "Silver katmanından" → "kaynak verisinden" gibi hâl eki korunur;
  - satır, madde ya da başlık başında büyük harf korunur.
  Adım izine "iç adlar kullanıcı diline çevrildi" yazılır.
- **Tablosuz ve veri çekilmemiş turda sayılar araç çıktısıyla doğrulanır** (`grounding_check`). Doğrulanamayan sayıyı taşıyan
  cümle D02 son çıkışıyla çıkarılır.
- **Sol panel ve durum penceresi:** "gözlem", "hesaplanmış tablo", "hesaplamaya hazır".

## Sonuçlar

- Ajan testleri 638 geçti (`tests/test_ic_adlar.py`). Testler şunları kapsar:
  - nasıl / ne tür soruları;
  - kaynak etiketi çevirisi ve Gold tablosunun kaynağı;
  - kullanıcının gördüğü gerçek cevaptaki başlığın çevrilmesi ve hâl ekleri;
  - ajanın son cevabı ve geçmişi;
  - tablosuz turda doğrulanmamış sayının çıkması;
  - istem kuralı ve arayüz etiketleri.

  `test_chart_tool` altyazı beklentisi kurum adına güncellendi.
- K01 22/22, K02 22/22, K01-T07 arayüz 15/15 (`docs/experiments/k0{1,2}_…_2026-09-15_1848.json`,
  `k01_ui_kabul_2026-09-15_1848/`). Sol panel etiket değişikliği arayüz kabulünü bozmadı.
- Canlı ölçüm: `scripts/baglam_senaryolari.py`, 7 senaryo × 3, gerçek model (`docs/experiments/baglam_senaryolari_2026-09-15_185124_x3.json`).
  - Kayıtlı sonuç 57/60. Üç kırmızının üçü de S6 "Elinde nasıl veriler var" turu ve üçü de denetim kalıbının hatası: kalıp
    büyük/küçük harf duyarsız `evds:` aradığı için okunur "TCMB EVDS: 12 seri" ifadesini iç kimlik saydı. Cevap doğruydu: model
    çağrılmadı, katalogdan geldi, iç ad yoktu.
  - Kalıp kimlikteki iki noktadan sonra boşluksuz kod arayacak şekilde düzeltildi; kayıtlı 60 cevap yeniden tarandı, hiçbirinde
    iç ad yok. Grafik başlığı ve rapor kaynakları canlı koşuda eski (daha geniş) kalıpla geçmişti.
  - Elle okuma:
    - "Konut kredisi faiz oranını aylık ortalama olarak göster" cevabı kaynağı "TCMB EVDS haftalık konut kredisi faiz oranının
      takvim aylarına indirgenmiş hâli" diye anlatıyor.
    - "Bu tablo nereden geliyor?" 3 tekrarda da kurum adı ve hesaplama kuralıyla (ay ortalaması, ay sonu) cevaplandı.
    - "Gold" ya da tablo kimliği hiçbir cevapta yok.
  - Önceki senaryolar (S1–S5) aynı koşuda 45/45; fark cevaplarında uydurma tutar yok.
- Bilinen sınır: son güvence sözcük tabanlıdır; "altın" (gold) anlamındaki İngilizce "Gold" da çevrilir. Türkçe cevapta
  beklenmez.

## Ek (15 Eylül akşam): veri seti cevabında konu başlıkları ve yeni kaynağın okunur adı

**Bağlam.** Kullanıcı "elimizde hangi veriler var" cevabının tamamen deterministik olmasının veri değişince ne olacağını sordu.
- İçerik zaten her soruda canlı katalogdan okunuyordu: kimlik deneyinde beş DB beş farklı cevap verdi. Uygulama içi ekleme ve
  onay kataloğu `reload()` ile hemen yeniliyor.
- İki gerçek sınır vardı:
  - cevap yalnız kaynak, seri sayısı ve dönem veriyordu, konu yoktu;
  - `source_hints.json`'da adı olmayan yeni kaynak ham kimlikle ("tuik: 5 seri") görünürdü.

Kullanıcı konu başlıklı öneriyi kabul etti.

**Karar** (`labels.topics_summary`, `labels.source_display_name`):
- **Konu.** Her serinin ölçüm kolonunun ilk takma adı alınır; katalog bunu kısa okunur ad olarak tutuyor ("konut kredisi",
  "politika faizi").
  - Adında tamamı büyük harf bir varlık parçası varsa ("Konut Kredisi, ADANA (…)") varlık adı konudan atılır; harf ve aksan
    farkı gözetilmez (İSTANBUL ~ istanbul).
  - Kısaltmalar serinin tam adındaki yazımla döner ("tüfe" → "TÜFE", "m3" → "M3").
  - Aynı konu bir kez yazılır, en çok 6 konu gösterilir, kalanı "ve N konu daha".
  - Varlıklı kaynakta özet "81 il × 8 konu: …" biçimindedir ("il" etiketi yoksa "varlık").
- **Kaynak adı sırası:**
  1. `source_hints.source_names`;
  2. kaynağın adresindeki ya da kimliğindeki bir parçayla eşleşen kurum adı (`source_hints.institutions`; "data.tuik.gov.tr" →
     "TÜİK");
  3. adresin alan adı;
  4. kimlik.

  Aynı sıra alan tanımında, arama kartında ve okunur kaynak etiketinde kullanılır. `meta.source` tablosu DB'de var ama boş ve
  serbest açıklama taşıyor; ad kaynağı olarak kullanılmadı.
- **Biçim.** Cevap kaynak başına bir madde. Kullanıcı serileri ve boş katalog cümleleri değişmedi.

Gerçek demo DB'de cevap:

    Veri havuzunda şu kaynaklardan yüklü seriler var:
    - BDDK FinTürk (il bazında): 648 seri (2016-03 → 2026-06); 81 il × 8 konu: kredi kartı, ihtiyaç kredisi, konut kredisi, kredili mevduat hesabı, takipteki ihtiyaç kredisi, takipteki konut kredisi ve 2 konu daha
    - BDDK Aylık Bülten: 20 seri (2016-01 → 2026-06); konular: toplam krediler, yurt içi yerleşik mevduat, toplam mevduat, tüketici kredileri, konut kredisi, taşıt kredisi ve 14 konu daha
    - TCMB EVDS: 12 seri (2016-01 → 2026-07); konular: ağırlıklı ortalama fonlama maliyeti, politika faizi, euro kuru, dolar kuru, TÜFE, para arzı ve 5 konu daha
    - BDDK Haftalık Bülten: 1 seri (2016-01 → 2026-06); konu: haftalık konut kredisi

**Sonuçlar:**
- Ajan testleri 642 (`tests/test_veri_seti_cevabi.py`). Testler şunları kapsar:
  - il × konu özeti, 3 harfli il ve İ/i farkı;
  - kısaltma yazımı ve tekrarın tekilleşmesi;
  - konu sınırı;
  - yeni kaynağın kurum adı, alan adı ve kimlik sırası;
  - cevabın satır satır biçimi.
- Canlı ölçüm: senaryo S8. Konu sırası katalog sırasıdır (seri kimliği); en genel konu her zaman önde değildir.

## Ek 2 (15 Eylül akşam): tablosuz sayı denetiminin havuzu — kendi gerilememiz

**Bulgu.** 8 senaryo × 3 koşusunda (`baglam_senaryolari_2026-09-15_190737_x3.json`) S8 takip sorusu "Bunlardan konut kredisiyle
ilgili hangileri var?" 3 tekrarın 3'ünde bozuk çıktı.
- "BDDK FinTürk (il bazında …)" başlığının altı boştu ve "doğrulanamayan 2 ifade çıkarıldı; doğrulanmış değerler tabloda" notu
  vardı.
- Sebep bu kararla eklenen tablosuz sayı denetimiydi. Model "81 il" bilgisini bir önceki deterministik cevaptan ("81 il × 8 konu")
  tekrarladı. Havuz yalnız bu turun araç çıktılarıydı; "81" orada olmadığı için doğru maddeler silindi. Not da tablo yokken
  "tabloda" diyordu.
- Senaryo denetimi ("geri gönderilmez") bu kusuru değil olağan geri göndermeyi kırmızı saymıştı; kusur elle okumada bulundu.

**Karar:**
- **Havuz genişledi:** bu turun araç çıktıları + ön-yükleme kartları + sohbetteki önceki cevaplar. Önceki cevaplar ya doğrulanmış
  ya da katalogdan deterministik üretilmiştir.
- **Not metni:** tablo yoksa "doğrulanmış değerler tabloda" yazılmaz.
- **Denetim araçsız tura da uygulanır.** Yeniden koşuda bir tekrarda model araç çağırmadan "konut kredisiyle ilgili 166 seri"
  yazdı; denetim yalnız araç çalışan turdaydı. Havuz boşsa (ilk tur, kart yok) doğrulanacak kaynak da yoktur, denetim atlanır.
- **Senaryo denetimi:** S8'de "geri gönderilmez" yerine "boş kalan başlık yok" aranır.

**Ölçüm:**
- S8 × 3 havuz düzeltmesinden sonra 6/6 (`…_191141_S8_x3.json`); FinTürk maddeleri geri geldi, boş başlık yok.
- Araçsız tur genişletmesinden sonra:
  - Ajan testleri 644. K01 22/22, K02 22/22 (`…_1913.json`, `…_1914.json`); arayüz 15/15 (`k01_ui_kabul_2026-09-15_1902/`).
  - 8 senaryo × 3, gerçek model: 66/66 (`baglam_senaryolari_2026-09-15_191752_x3.json`). Elle ve kalıpla tarandı: iç ad 0, boş
    başlık 0, son çıkışta silinen ifade 0. "Bir önceki aya göre fark" 3/3 doğru, uydurma tutar yok. S8 takip cevaplarında FinTürk
    maddeleri yerinde; araçsız hesaplanmış sayı yok.
  - Kimlik deneyi (finans ve sağlık DB, gerçek model, `kimlik_alan_deneyi_2026-09-15_1913.json`): son çıkışta silinen ifade 0;
    "Sen kimsin?" cevapları bütün. Veri seti cevabı finansta kaynak başına konularla, sağlıkta kullanıcı serisinin adıyla.
- **Açık (bu kararda değiştirilmedi), model cevaplarında elle görülen iki küçük kusur:**
  - Sağlık DB'sinde "Neler yapabilirsin?" iç kolon adını (`entity_id`) yazdı ve olmayan bir kurum kırılımından söz etti. Son
    güvence kolon adlarını kapsamaz.
  - Finans DB'sinde "banka kırılımında karşılaştırma" dedi; veride banka kırılımı yok (sektör toplamı ve il).
