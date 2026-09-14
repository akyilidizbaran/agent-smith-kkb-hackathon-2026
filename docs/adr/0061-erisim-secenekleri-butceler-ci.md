# ADR-0061: Erişim engelinde dürüst seçenekler; LLM bütçeleri ve kesinti; CI

**Durum:** Kabul edildi · **Tarih:** 2026-09-14 · **Milestones:** M06, M15

## Bağlam
M06: erişim sınıflandırması (404/429/401/login/bot/CAPTCHA/paywall/robots/erişilemez), sabit kaynakta sorma ve serbest
kaynakta açıklayarak alternatif (ADR-0034) zaten vardı. Eksikler: JavaScript kabuğu ayrı sebep değildi; ortamda
`KKB_CREDENTIAL_<HOST>` varsa "ekip hesabıyla devam edeyim" sunuluyordu, oysa ajanın hiçbir isteği anahtar göndermiyor
(sahte vaat); seçenekler arayüzde eyleme bağlı değildi. M15: OpenAI istemcisi kendi 2 tekrar denemesini bizim 3 denemelik
döngümüzün içinde yapıyordu (çağrı başına 180 s zaman aşımıyla en kötü ~27 dk); 400 hataları da tekrar deneniyordu;
çıktı sınırı yoktu; soru başına süre bütçesi yoktu; model servisi kesilince arayüz 500 veriyordu; CI yoktu.

## Karar
**M06**
1. `js_required` sebebi (içerik JavaScript'le yükleniyor; tarayıcı yeteneği yok) → dosya yükle / başka kaynak.
2. "Ekip hesabı" seçeneği yalnız host `source_hints.json`'da anahtarı kullanan bir bağlayıcıya eşliyse ve anahtar ortamda
   varsa; etiket "Ekip hesabı (tanımlı bağlayıcı) çekilebilir" — veri Architect ingest'iyle o yoldan gelir. Anahtar varlığı
   kanıtta görünmeye devam eder, değeri hiçbir yerde görünmez.
3. Adım kaydı hata zarfının adaylarını taşır; cevap yükü `access_options` içerir; arayüz düğmeleri: dosya yükle (dosya
   seçici), başka kaynakta ara (kaynak değişikliği açıklanarak), tekrar dene, ekip hesabı. Düğme yetki vermez, yeni soru üretir.

**M15**
4. SDK tekrar denemesi kapalı (`max_retries=0`); tekrar yalnız bağlantı/zaman aşımı/408/409/429/5xx'te; 4xx istek hatası
   hemen yükselir. Ayarlar: `LLM_TIMEOUT` (90 s), `LLM_MAX_TOKENS` (1500), `AGENT_TIME_BUDGET_S` (300 s).
5. Süre bütçesi dolunca araç turu durur, "şu ana kadar toplananla en iyi cevap + neyin tamamlanmadığı" turu çalışır.
   Çıktı uzunluk sınırında kesilirse cevaba not düşülür.
6. Model servisi kesintisi (bağlantı, zaman aşımı, tükenmiş 5xx/429) cevap olarak döner: "ulaşılamıyor, sayı üretmedim",
   ekrandaki tablo varsa bu soru için yorumlanmadığı söylenir. İstek hataları ve kod hataları yutulmaz.
7. CI: `.github/workflows/tests.yml` iki paketi kilitli kurulumla test eder (canlı ağ/MIA yok). `make ci` aynı işi yerelde
   yapar. Lakehouse Makefile hedefleri gerçek işleriyle adlandırıldı (`test-fast`, `bootstrap`, `silver`, `gold`).

## Mevcut davranışla kapanan görevler
M06-T01 arama sonucu veri değil (prompt kuralı); T02 sağlayıcı ayrımı (`web/search.py`); T03 veri bağlantısı önceliği
(`link_score` +10); T04 aynı alan adı, robots, sayfa ≤5 / derinlik ≤1 / süre ≤60 s bütçe; T06 sabit kaynakta sor, serbestte
açıkla; T11 kullanılan kaynak sha256+zaman, kullanılmayan adaylar kanıtta; T12 arama bütçesi kalanı karta yazılır, kısmi
tarama bütçe notuyla. M15-T05 araç kapısı yetki değil (ADR-0043/0056).

## Açık
M06-T07 demo kaynak erişim matrisi (M17 operasyon tarifinde), T09 tarayıcı yeteneği uygulanmadı (K08 opsiyonel).
M15-T01/T02 süre dağılımı ve eşikler M16 kabul koşularından; T06/T07 retrieval ölçümünün genişletilmesi; T08 paralellik; T11
lakehouse test süresi profili.
