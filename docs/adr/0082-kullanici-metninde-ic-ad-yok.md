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
