# ADR-0079 — Canlı adım akışı, cevap yazım animasyonu ve kanıt akışı paneli

**Tarih:** 15 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** kullanıcının arayüz geri bildirimi (15 Eylül)

## Bağlam

Kullanıcı arayüzde üç sorun bildirdi:

1. Sağdaki kanıt akışı kötü görünüyor. Aynı SQL her kolon için ayrı ayrı, uzun tek parça metin olarak basılıyordu. sha256,
   run ve adres de düz metin dökümüydü; halkaların sırası ve nerede koptuğu bir bakışta okunmuyordu.
2. Mesaj gönderilince yalnız "Düşünüyor…" yazıyor, ajanın o anda ne yaptığı görünmüyor.
3. Cevap bir anda düşüyor; Claude'daki gibi hızlı hızlı yazılarak gelmeli.

Kısıtlar:

- Ajan döngüsü (`core/agent.py`) Büşra'nın açık PR #4'ünde değişiyor; bu iş oraya dokunmamalı.
- Nihai metin doğrulama kapılarından geçer (grounding MISS, nedensellik dili, genel bilgi, araçsız işlem iddiası; ADR-0066,
  ADR-0078). Kapı taslağı geri gönderip yeniden yazdırabilir, doğrulanamayan cümleyi çıkarabilir.

## Karar

- **Token akışı yok; canlı adım akışı var.** Taslağı token token ekrana yazmak, kapının reddedeceği sayıyı önce gösterip sonra
  geri almak olurdu. D02'nin "doğrulanamayan sayı yayımlanmaz" kuralını arayüzde delerdi. Onun yerine
  `POST /api/ask/stream` NDJSON satırları gönderir: önce adım olayları, en sonda `/api/ask` ile birebir aynı cevap yükü.
  `/api/ask` değişmedi; betikler ve testler onu kullanmaya devam eder. Arayüz akış ucu yoksa düz uca düşer.
- **Kanca web katmanında, örnek düzeyinde** (`kkb_agent/live_steps.py`). Soru süresince üç çağrı sarılır ve soru bitince
  (istisnada da) geri alınır:
  - `registry.execute`: araç satırı; Türkçe etiket, argüman özeti, süre ve hata kodu.
  - `llm.chat`: model turu ("Soru inceleniyor", "Sonuçlar değerlendiriliyor", "Cevap yeniden yazılıyor").
  - `evidence_builder.build`: "Kanıt zinciri kuruluyor".

  Araç çağırmayan model turundan sonra "Cevap denetleniyor" satırı açılır. Sonraki olay bu satırın sonucunu belirler:
  - yeni model turu gelirse: "Taslak geri gönderildi" (↺);
  - araç gelirse (metin içi çağrı): satır düşer;
  - kanıt paneli ya da soru sonu gelirse: geçti.

  Olay üretimi hata verirse (istemci koptu) ajan etkilenmez. Oturum kilidi içinde kurulduğu için eşzamanlı soru sarmalayıcıları
  karıştırmaz.
- **Olaylar metin taşımaz.** Adım olayında yalnız etiket, argüman özeti (amaç cümlesi, arama sorgusu, veri kümesi kimliği, adresin
  alan adı; yerel yol yalnız dosya adı ve yükleme ön eki olmadan) ve süre bulunur. Modelin serbest metni, araç çıktısı ve cevap
  sayıları gönderilmez; testte taslaktaki "999" ve cevaptaki sayı olaylarda aranır. Kalıcı adımlarda (`steps[].label/detail`)
  de aynı özet kullanılır. Geri gönderme gerekçesinde reddedilen sayı yazılmaz ("araç çıktısında olmayan sayı ya da neden-sonuç
  dili").
- **Yazım animasyonu istemcide, doğrulanmış metin üzerinde.** Cevap geldiğinde metin blok blok, harf harf açılır (kısa cevap
  ~140 harf/sn, uzun cevap en çok ~2,2 sn). Metnin tamamı DOM'da kalır, görünmeyen kısım saydam kuyruktadır. Bu yüzden
  kopyalama, ekran okuyucu ve kabul betiklerinin (`.busy` kalkınca metni okuyan K01/K03) davranışı değişmez. Tablo, grafik ve
  indirme bağlantıları metin bitince belirir. Cevaba tıklama, Esc ya da yeni soru animasyonu bitirir.
  `prefers-reduced-motion` açıksa animasyon yoktur. Cevabın üstünde kapalı "N adımda bulundu · süre" satırı kalır ve sayfa
  yenilense de adımlardan yeniden kurulur.
- **Kanıt akışı paneli.** Üstte üç durum şeridi (sayılar, sorgu izi, dosya zinciri), altında sırayla halkalar:
  cevap → tablo, tablo → sorgu, Silver gözlemi, Bronze ham dosya, RAW kaynak. Web ya da OCR cevabında son halkalar sayfa ya da
  belgedir.
  - Her halka tek başlık ve birkaç ölçü gösterir: eşleşen sayı oranı; kolon ve benzersiz sorgu sayısı ile okunan tablolar;
    gözlem ve seri sayısı, dönem aralığı, kalite bayrakları; artifact sayısı, kısa sha256 ve run; alan adı, HTTP durumu ve
    çekim zamanı.
  - Aynı SQL tek sorgu olarak gruplanır. SQL, kolon notları ve seri kimlikleri kapalı kutudadır.
  - İlk kopuk halka kesik amber çizgiyle işaretlenir, sonrası soluk gösterilir. Başlık cümlesi zincirin nerede koptuğunu söyler;
    teknik özet imleç ipucunda durur.
  - Cevap sayılarının listesi yine yoktur (ADR-0078). Bağlam, taranıp kullanılmayan ve danışılıp kullanılmayan kaynaklar
    "Diğer kaynaklar" altında toplanır; web araması bağlamı varsa açık gelir.

## Sonuçlar

- Kullanıcı beklerken hangi adımda olunduğunu ve adımların süresini görür. Canlı denemede bekleme süresinin büyük kısmının model
  turlarında geçtiği ekranda okundu (model turu 3,1–3,6 s, katalog/sorgu araçları ≤0,3 s; 24,5 s süren iki serili soru).
- Yeni araç eklenince etiket `TOOL_LABELS`'a eklenmezse satır "<araç> çalışıyor" olarak görünür; çalışma bozulmaz.
- Metin içi araç çağrısı yapan (yerel tool-calling olmayan) modelde model turu önce "denetleniyor" gibi açılıp düşebilir; kısa
  bir titreme, yanlış bilgi değil.
- Ajan testleri 504 geçti; `tests/test_canli_adim_akisi.py` akış sırasını, geri gönderme ve düşen satırı, hata olayını, kilidin
  bırakılmasını, sarmalayıcıların geri alınmasını ve olaylarda metin olmamasını denetler.
- K01-T07 arayüz kabulü (A09, A21; gerçek tarayıcı, betikli model) yeni akışla 15/15:
  `docs/experiments/k01_ui_kabul_2026-09-15_1533/`.
- Canlı sunucuda başsız Chromium ile yazım ortası ölçüldü: 358 harfin 295'i henüz saydamdı, tamamı DOM'daydı; yazım 1,8 s.
- Görünmeyen sekmede tarayıcı kare çizmez; animasyon o durumda atlanır, sekme gizlenirse yarıda bitirilir.
