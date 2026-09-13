# ADR-0063 — M16 kabul bulguları: araçsız işlem iddiası, kısa belirsiz soru, farklı birimli karşılaştırma grafiği

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Milestone:** M16 (A07, A09, L10), M13

## Bağlam

İlk çok turlu canlı kabul koşusu (`scripts/acceptance_m16.py`, commit b44cc1f+, 10/14 tur) birim testlerinin görmediği
dört kusur buldu. Rapor rapordan çıkarılmadı: `docs/experiments/acceptance_m16_2026-09-14_0118.json`.

1. **Uydurulmuş işlem.** Finans dışı birleştirme turunda model hiç araç çağırmadan "dosya yüklendi ve birleştirildi, 24 il
   eşleşti" yazdı. Veri üreten araç zorunluluğu aktif tablo varken susuyordu (önceki turdan tablo vardı); grounding ise
   yalnız sayıları denetler, "24" önceki tur çıktısında geçtiği için yakalanmadı.
2. **Belirsiz kısa soru.** "Kredi bakiyesini göster." katalogda birbirinden farklı çok sayıda seriye eşleşirken model
   netleştirme sormadan birini seçti; NETLEŞTİRME KURALI (ADR-0059) istem metninde olduğu hâlde uygulanmadı.
3. **Karşılaştırmalı grafik yok.** Milyon TL ve endeks serileri tek eksende L9 `single_unit_axis` kuralına takıldı; model
   özür yazdı. Çift eksen yanıltıcı olduğu için yalnız açık istekte açılır (ADR-0032 `dual_axis_asked`).
4. **Kanıt zinciri ✗.** Veri kökü yer değiştirince (ADR-0062) artifact kayıtlarındaki mutlak RAW yolları bayatladı.

## Karar

- **İşlem iddiası guard'ı (harness):** bu turda başarılı araç adımı yokken cevap bir işlem fiili içeriyorsa
  ("yüklendi, birleştirdim, hesaplandı, eklendi, getirdim…") ya da soruda `Dosya:`/URL varsa cevap bir kez modele geri
  gönderilir: "Bu turda hiçbir araç çalışmadı; önce web_url / workspace_join çağır." İzde `validate` adımı olarak görünür.
  Tek geri gönderim; ikinci cevap olduğu gibi kabul edilir (döngü yok).
- **Kısa belirsiz soru kapısı (deterministik):** ≤2 içerik sözcüğü, sayı/dönem sözcüğü yok, dosya/adres yok, aktif tablo
  yok ve katalog aramasında ≥3 farklı ad (parantez ve virgül sonrası atılarak) varsa kullanıcı mesajına aday adlarıyla
  "tahmin etme, tek soruda sor" notu eklenir. Alan sözlüğü yoktur; kapı ad sayar, bu yüzden finans dışı katalogda da aynıdır.
- **İlk dönem = 100 geri dönüşü (grafik aracı):** zaman eksenli çizgi grafikte kusurlar yalnız `single_unit_axis` (ve
  birimi bilinmeyen serinin `axis_unit`'i) ise ve her serinin ilk değeri pozitifse araç her seriyi kendi ilk döneminde
  100'e çevirir, birim "endeks (ilk dönem = 100)" olur, denetçi yeniden koşar. Kart ve artifact `rebased_to_100` taşır;
  model bunu tek cümleyle söyler. Çift eksen hâlâ kendiliğinden açılmaz. İlk değer sıfır/negatifse ret + ipucu.
- **RAW yolu çözümü (adaptör):** kayıttaki yol yoksa aynı `raw/…` kuyruğu güncel DB kökünde aranır; bulunamazsa eski yol
  döner ve zincir dürüstçe eksik görünür (sahte yeşil yok).
- **RAW özet denetimi (A23):** RAW içerik adreslidir (gerçek veride örneklenen 6/6 dosyada sha256 = artifact kimliği).
  Adaptör çözülen RAW dosyasının sha256'sını (yol, boyut, mtime önbellekli) kayıtla karşılaştırır; uyuşmazsa gözlemin
  `raw_digest_ok=False` olur, Bronze bulunsa da `file_present` yanlıştır ve panel "baytları kayıtlı özetle uyuşmuyor" boşluğu yazar.

### İkinci koşu sonrası düzeltmeler (aynı gece, 11/14 tur)

- **Kısa belirsiz soru: not yerine deterministik soru.** Aday adları modele not olarak eklendiğinde de model iki koşuda
  sormadan birini seçti. Kapı artık LLM'i hiç çağırmadan aday listeli netleştirme sorusunu kendisi döner; aktif tablo
  varken ya da kullanıcı bizim soruya kısa yanıt veriyorsa (bekleyen soru) çalışmaz.
- **Rozetler bağımsız.** `chain_ok` panelin bütün boşluklarına bakıyordu; tek eşleşmeyen sayı, dosyaları diskte duran
  zinciri de ✗ gösterdi (finans ilk turu, 13/14 sayı). Dosya zinciri artık yalnız zincir boşluklarına bakar.
- **Yüzde tabanında düzey sıçraması.** Trendli seride tek aylık düzey kırılması yüzde tabanında tek bir dürtüye dönüşüyor,
  en az 4 gözlemlik bölüt kuralı onu üç ay önce başlayan "rejime" gömüyordu (fikstürde 2025-01 yerine 2024-10). Dürtü:
  değer önceki ve sonraki 3 gözlemin medyanından sağlam z > 8 ve ≥ 1 puan uzak, iki yerel medyan birbirine yakın.
  Sıçrama ayrı kırılmadır, bölütlemeye medyanla girer, kartta "düzey sıçraması" yazar. Büyüme hızının kalıcı değişimi
  dürtü sayılmaz (mevcut test korunur).
- **Ekip notu (Büşra, 13 Eyl):** `FILE_IRRELEVANT` hata kodu listede ve tekrar denenemez; okuyucu tek harfli URL şemasını
  Windows sürücü harfi sayar (izinli kök kuralı aynen uygulanır).

### Üçüncü koşu sonrası (11/14, senaryo 5/6)

- **Grafik zorunluluğu tablo varken de çalışır.** Model "karşılaştırmalı grafik" turunda chart'ı hiç çağırmadan "farklı
  birimler, çizilemez" yazdı; o turda veri üretilmediği için zorunluluk susuyordu. Artık aktif tablo varsa da bir kez geri
  gönderilir; grafik kuralı farklı birimde de aracı çağırmasını, ilk dönem = 100 geri dönüşünü söyler.
- **Noktalı üç haneli sayı iki okumayla aranır.** "17.985" Türkçe binlik (17985) okunuyordu; faiz tablosunda 17,985 olduğu
  için "tabloda yok" dendi. Tek noktalı üç haneli yazımda iki okumadan biri tabloda varsa sayı eşleşir.
- **Açık:** finans ilk turunda eşleşmeyen tek sayı "50"; bağlam kayıtta kırpılmıştı, betik artık tam cevabı yazıyor.

### Dördüncü koşu sonrası (12/14)

- **Tolerans gösterilen hassasiyete bakar (M13-T05).** Faiz değişimi −0,403 cevapta "−0,40" yazıldı; göreli %0,5 (0,002)
  yuvarlamayı "tabloda yok" saydı. Virgüllü yazımda tolerans, göreli %0,5 ile son gösterilen hanenin yarım biriminden büyük
  olanıdır; "100,6" ↔ 100 ve "255" ↔ 250 hâlâ eşleşmez. Noktalı yazımda (binlik olabilir) hane sayılmaz.
- **Kabul kontrolü düzeltmesi.** Birleştirme turunda ajan, fikstür belgesinin beklediği gibi yinelenen Van anahtarında
  reddedip sordu; kontrol yalnız başarılı birleştirmeyi kabul ediyordu. Koşu kaydı değiştirilmedi.

## Reddedilenler

- **İşlem iddiasında cevabı doğrudan reddetmek:** "eklendi" gibi fiiller önceki turdaki gerçek işi anlatırken de geçer;
  tek geri gönderim yanlış pozitifin maliyetini bir LLM turuyla sınırlar.
- **Belirsizliği embedding benzerliğiyle ölçmek:** eşik alan ve modele bağlı olurdu; ad sayımı açıklanabilir ve test edilebilir.
- **Farklı birimde otomatik çift eksen:** iki ölçeğin keyfi hizası yanlış kesişim algısı üretir (ADR-0032).

## Sonuç

Ajan birim testleri 377 → 391 (guard, kapı ×2, grafik ×2, RAW yolu, RAW özeti, rozet bağımsızlığı, düzey sıçraması, sürücü harfi; A26/A07 indirme ve A27 model kesintisi). Canlı etki M16 ikinci koşusunda ölçülür
(`docs/M16_KABUL_RAPORU.md`).
