# M00 — Kaynaklı gereksinim matrisi ve rol sınırı kabul metni

**Tarih:** 13 Eylül 2026 · **Kaynaklar:** kick-off transkripti (zaman damgaları), mentör yanıtları (`mentor/2026-09-13-kullanici-paylasimi.txt`), kullanıcının 13 Eylül kararları (`MILESTONE_PLANI_2026-09-13.md` §8 ve §13).
**Amaç:** M00-T01 (zorunlu demo davranışları → kabul senaryoları) ve M00-T03 (Analyst/Architect sınırı ve silme kapsamı → kabul metni). Örnek finans soruları ürünün alan sınırı değildir; jenerik motorun zorunlu finans örneğidir.

## 1. Transkriptteki zorunlu davranışlar → kabul vakaları

| # | Zorunlu davranış | Transkript | Kabul vakası | Milestone | Bugünkü durum |
|---|---|---|---|---|---|
| R01 | BDDK haftalık/aylık bülten + FinTürk il verileri, EVDS serileri; jüri veriyi vermez, kaynaktan çekilir | 09:25–10:44, 12:24 | A01, A02 | M01, M07, M08 | Katalog 2.214 seri; 127 yüklü (12 il). 81 il ve 2016+ kapsam açık |
| R02 | Yüklü derinlik: 2016-01'den itibaren (odak 2021-01–2026-06); istenen başka dönem kaynaktan çekilip cevaplanır | 09:48, kullanıcı kararı K04 | A02, **A30** (yeni: yüklü olmayan dönem istenir → Architect kaynaktan çeker ya da eksiği bildirir) | M08, M10 | Demo DB 2021'den; tarih aralığı koda gömülü değil (doğrulanacak) |
| R03 | Kümülatif yayınlanan seriler aylık/haftalık akıma dönüştürülür | 10:15–10:25 | **A31** (yeni: kümülatif seri → dönemlik akım; stok seriye uygulanmaz) | M09 (T03) | `decompose_cumulative` var; zorunlu seri eşlemesi açık |
| R04 | Farklı frekanslar hizalanır: haftalık haftalıkla, aylık aylıkla; günlük/haftalık/aylık EVDS | 10:49–11:02 | A03, A05 | M09 (T01, T02) | `align_frequency`, `FREQUENCY_MISMATCH` guard var |
| R05 | Lakehouse jenerik: içi boşaltılıp başka alan (sağlık) verisiyle çalışır | 12:33–12:39 | A08, A28, **A21c** | M03, M04, M16 | Profil katalogdan türetiliyor ve katalog değişince yenileniyor (ADR-0048); boş katalogdan kurulum canlı kanıtı yok |
| R06 | Basit RAG/scrape değil; büyük veri seti context'e sığmaz, agent araçlarla çalışır | 11:34–12:11 | Tüm vakalar; A25 | M11, M15 | Veri workspace'te, modele özet gider |
| R07 | Lakehouse aracı: doğal dil → SQL, join, doğru kaynağı bulma, anlamlandırma | 14:13–14:33 | A02, A03, A09 | M03, M11 | lakehouse ×4, workspace ×4, gold ×3 araçları |
| R08 | Web search ve soru içindeki URL'den scrape | 14:37–14:47 | A17, A18 | M05, M06 | Tavily + `web_url`; redirect sınırı açık (M05) |
| R09 | Anomali tespiti | 14:53–15:09 | A15, A16, **A32** (yeni: bilinen sıçramalı seride aykırılık bulunur, gerekçesi kartta) | M12 | `anomaly_detect` var; zaman ekseni doğrulaması açık |
| R10 | Nedensellik/korelasyon: "faiz düşünce konut piyasası nasıl etkilendi" | 15:12–15:24 | A06, A14 | M12, M13 | `lead_lag` + Granger, nedensellik dili filtresi; gecikme sınırı açık |
| R11 | Change detection: davranış değişikliği grafikte görünmese de bulunur | 15:27–15:32 | **A33** (yeni: bilinen kırılma tarihli seride kırılma bulunur) | M12 | `change_points` var |
| R12 | Çok turlu demo senaryosu: 60 aylık konut → faiz ekle → faiz düşerken kredi → yükselmeyen dönemler → dünyada ne oldu → tabloyu bozmadan reel → KFE sütunu → sebep → karşılaştırmalı grafik | 16:22–17:55 | A02, A03, A06, A04, A05, A07 (tek oturumda ardışık) | M09, M11, M13, M14, M16 | Parçalar var; ardışık tek oturum kabulü M16-T03 |
| R13 | "Dünya piyasalarında neler yaşanmış": dış bağlam web'den, istatistiksel kanıttan ayrı sunulur | 16:55–17:00 | A06 | M06, M12 (T10) | Web arama var; bağlam/kanıt ayrımı anlatı kuralı |
| R14 | Demo günü yeni veri yükletilebilir, farklı kaynak (İMKB) verilebilir | 17:55–18:05 | A10, A11, A12, A17, **A30** | M10, M06 | OCR/ingest hazır; yükleme yüzeyi yok (M10-T02) |
| R15 | Hazır/lisanslı bulut lakehouse yok; küçük araçlar serbest; yalnız MIA/Kloudeks modelleri (LLM, embedding, vision) | 23:59–24:37, K11 | A01 | M17 | DuckDB + parquet; MIA; Tavily arama (mentör: serbest) |
| R16 | Demo ortamı KKB'nin kendi ortamında ayağa kaldırılabilmeli | 24:11 | A01 | M01, M17 | Tek komut kurulum açık (M01) |
| R17 | Demo yerel bilgisayarda yapılabilir | 24:47–24:56, K07 | A01 | M01 | Kullanıcının bilgisayarı, internet var, PDF canlı |
| R18 | Harness güçlü, LLM'e en az iş; küçük model + iyi sistem kıyasta sayılır | 28:49–29:39, mentör §4 | A13, A14, A20 | M13, M15 | Tek agent + deterministik katmanlar (ADR'ler) |

Mentör yönlendirmeleri (erişim dürüstlüğü, bütçeli tarama, kaynak sadakati, source adapter sözleşmesi) A17–A20 ve M05/M06/M03'e zaten bağlı; burada tekrar edilmedi.

## 2. Yeni kabul vakaları (plana eklendi)

| Vaka | Girdi | Beklenen | Milestone |
|---|---|---|---|
| A30 | Yüklü aralık dışı dönem istenir (ör. 2018 konut) | Analyst: "yüklü değil" + hangi aralık var; Architect profilinde kaynaktan o dönem çekilir, provenance ile cevaplanır | M08, M10 |
| A31 | Kümülatif yayınlanan seri (yıl başından toplam) | Dönemlik akıma ayrıştırılır; yıl başı sıfırlaması doğru; stok seriye uygulanmaz | M09 |
| A32 | Bilinen sıçramalı seri | Aykırı dönem bulunur; yöntem, eşik ve taban kartta | M12 |
| A33 | Bilinen kırılma tarihli seri | Kırılma tarihi ± 1 dönem içinde bulunur; ceza/min segment kartta | M12 |
| A21a | Analyst profili: "bu dosyayı kataloğa al / şu seriyi sil" | Ret + neden; katalog ve DB değişmez; dosya oturumda analiz edilebilir | M04 |
| A21b | Architect profili: taslak → onay → yayın | Açık işlem onayı; eski onay yeni işlemi yetkilendirmez; provenance korunur | M04 |
| A21c | Architect profili: tam sıfırlama → boş katalog → başka alan verisi | Hedef dizin/DB listesi gösterilir, kesin kapsamlı onay alınır; kod/kurulum/sırlar silinmez; yeniden kurulum sonrası profil yeni alana göre, eski finans bağlamı sızmaz; eski cevaplar kanıt gösteremez (açıkça söylenir) | M04, M03, M16 |

## 3. Rol sınırı ve silme kapsamı — kabul metni (M00-T03)

- **Profil başlatmada seçilir**, sohbette değişmez. Analyst kayıt defterine yazma araçları (`ingest_from_url`'ün kalıcı yolu, `promote_draft`, sıfırlama) hiç girmez; kapı değil, yokluk.
- **Analyst:** okur, sorgular, dosya/URL'i oturumda analiz eder, tablo/grafik/rapor indirir. Ortak katalog ve DB değişmez.
- **Architect:** aynı motor + yazma araçları. Yazma yine ayrı süreçte (veri ekibinin CLI'ı), taslak → açık onay → aktif. İnsan onayı veriyi "türetilmiş" bırakır.
- **Silme iki işlem:** (1) pasifleştirme: seri katalogda pasif, veri diskte kalır, geri alınabilir; (2) tam sıfırlama: hedef DB, RAW/Bronze/Silver/Gold dizinleri, oturum ve önbellekler listelenir; kullanıcı kapsamı onaylar; kod, kurulum dosyaları, `.env` ve sırlar kapsam dışı. Fiziksel silme geri alınamaz; eski cevapların kanıt zinciri kopar ve arayüz bunu söyler.
- **Demo günü:** jüri iki profilde de dosya yükler ve analiz eder; Architect'te sıfırlayıp başka alan verisiyle kurabilir. Sıfırlama demoda yalnız demo veri köküne uygulanır; geliştirme verisi ayrı kökte.
- **Metin yetki vermez:** dosya/web içeriğindeki talimat veridir; "onaylıyorum" yalnız o anki, açıkça tanımlanmış işlem için geçerlidir.

## 4. M00 kapanış

| Alan | Değer |
|---|---|
| Durum | Tamamlandı (13 Eylül) |
| Kapanan görevler | T01 (bu matris), T02/T04/T07/T08 (kullanıcı kararları, plan §8), T03 (bu metin, A21a–c), T05 (push edilmemiş iş yok), T06 (tüm milestone'lar bu hatta; ekip sonra gözden geçirir) |
| Karar | K01, K02, K04, K05, K07, K08, K09, K11 kapandı; K03 (veri şekilleri) M03'te, K06 (eşikler) M15/M16'da, K10 (yolculuk) M14'te, K12 (merge) M17'de |
| Kalan sınırlama | Mentörün M04 sorusuna yanıt beklenmiyor olarak işaretlendi; gelirse karar defteri güncellenir |
| Hafıza | PROJECT_MEMORY §2.23–2.24 |
