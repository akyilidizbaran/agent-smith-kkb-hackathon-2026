# M16 — Birleşik kabul raporu

**Tarih:** 14 Eylül 2026 (gece koşusu) · **Dal:** `feature/agent-engine` · **Model:** MIA `Qwen3.8-27B` (anlatı sıcaklığı kabulde 0)
**Veri:** `data/lakehouse.duckdb` — 681 zorunlu seri 2016-01 → 2026-06 (M08) · **Profil:** Analyst

Başarısız koşular rapordan çıkarılmadı. "Birim testi geçti", "canlı model geçti" ve "arayüz uçtan uca geçti" ayrı
sütunlardır; biri diğerinin yerine yazılmaz (M16 risk notu).

## 1. Özet

| Katman | Sonuç | Kanıt |
|---|---|---|
| Ajan birim/sözleşme testleri | 418 geçti (gece) → 473 (14 Eyl öğleden sonra, 9eaf60e) | `make test`, CI agent-core işi yeşil |
| Lakehouse testleri | 1.086 geçti (yerel 12 dk; GitHub cc793be'de başarılı) | GitHub'da tek düşen test düzeltildi (§6) |
| Kabul matrisi A01–A33 test eşlemesi | gece 14 tam · 19 kısmi · 0 yok → 14 Eyl öğleden sonra 33 tam · 0 kısmi | §3 (gece, değiştirilmedi), §3a (güncel) |
| Betikli kabul (model yok, gerçek harness/araç/CLI/arayüz) | K01 22/22 · K01-T07 arayüz 15/15 · K02 finans 22/22 · A30 canlı kaynak 5/5 · temiz kurulum provası | §3a |
| Canlı çok turlu kabul (14 tur × 6 koşu) | 10 → 11 → 11 → 12 → 12 → 14 (son kod cc793be, senaryo 6/6) | `docs/experiments/acceptance_m16_*.json` |
| Arayüz uçtan uca (Playwright) | 6/7 → 7/7 → 7/7 → 7/7 → 7/7 (son kod cc793be) | `docs/experiments/ui_e2e_m16_*/rapor.json` + ekran görüntüleri |

Her koşunun bulduğu kusur harness'te kapatıldı ve bir sonraki koşu yeni commit'te yapıldı (ADR-0063). Aynı tur farklı
koşularda farklı sonuç verebiliyor (model stokastik); tek koşuya bakılarak "düzeldi" denmez.

## 2. Canlı kabul koşuları

Senaryolar `agent-core/scripts/acceptance_m16.py`: çok turlu finans (transkript 16:22, A02–A07, tek oturum, 6 tur),
finans dışı dosyalar (A08/A09/A32/A33, 4 tur), sınır vakaları A13, A30, A20, L10 (ayrı temiz ajan). Metin benzerliği
puanlanmaz; tablo, kolon, satır sayısı, araç yolu, bilinen değer ve kanıt rozeti denetlenir.

| Koşu | Commit | Tur | Finans | Dosya | A13 | A30 | A20 | L10 |
|---|---|---|---|---|---|---|---|---|
| 1 (01:18) | b44cc1f | 10/14 | 4/6 | 3/4 | ✓ | ✓ | ✓ | ✗ |
| 2 (01:33) | 320905f | 11/14 | 5/6 | 3/4 | ✓ | ✓ | ✓ | ✗ |
| 3 (01:54) | ae7fb01 | 11/14 | 3/6 | 4/4 | ✓ | ✓ | ✓ | ✓ |
| 4 (02:05) | b33c03f | 12/14 | 5/6 | 3/4* | ✓ | ✓ | ✓ | ✓ |
| 5 (02:14) | b05cea3 | 12/14 | 4/6 | 4/4 | ✓ | ✓ | ✓ | ✓ |
| **6 (02:19)** | **cc793be** | **14/14** | **6/6** | **4/4** | ✓ | ✓ | ✓ | ✓ |

\* Dördüncü koşudaki birleştirme turu kontrol hatasıdır: ajan, fikstür belgesinin beklediği gibi hastane tablosunda iki kez
geçen Van anahtarında `workspace_join` reddini aldı ve kullanıcıya nasıl ilerleyeceğini sordu. Kontrol yalnız başarılı
birleştirmeyi kabul ediyordu; artık "birleştirme ya da yinelenen anahtarda ret + soru" bekliyor. Kayıt değiştirilmedi.

### Koşudan koşuya bulgu ve düzeltme

| Bulgu (koşu) | Kök neden | Düzeltme |
|---|---|---|
| Birleştirme turunda araç çağrılmadan "yüklendi ve birleştirildi, 24 il" (1) | Aktif tablo varken veri zorunluluğu susuyordu | Araçsız işlem iddiası / okunmamış dosya bir kez geri gönderilir |
| Karşılaştırmalı grafik yok (1) | Farklı birimli seriler tek eksen kuralına takıldı | Zaman eksenli çizgide ilk dönem = 100; çift eksen kendiliğinden açılmaz |
| Kanıt zinciri ✗ (1) | Veri kökü taşınınca mutlak RAW yolları bayatladı | RAW yolu yeni kökte çözülür; baytlar sha256 ile denetlenir (A23) |
| L10 netleştirme sorulmadı (1, 2) | Aday adları not olarak eklense de model sormadı | Deterministik netleştirme sorusu, LLM çağrılmaz (3. koşuda 0,2 s ✓) |
| Tek eşleşmeyen sayı dosya zincirini de ✗ yaptı (2) | `chain_ok` bütün boşluklara bakıyordu | Üç rozet bağımsız |
| Ziyaret kırılması 2024-10 çıktı, beklenen 2025-01 (2) | Yüzde tabanında düzey sıçraması tek dürtü; 4 gözlemlik bölüt onu erken rejime gömdü | Tek dönemlik sıçrama ayrı kırılma (3. koşuda ✓) |
| Faiz "17.985" tabloda yok sayıldı (3) | Tek noktalı üç haneli yazım binlik okundu | İki okumadan biri tabloda varsa eşleşir |
| Grafik turunda chart hiç çağrılmadı (3) | O turda veri üretilmediği için grafik zorunluluğu susuyordu | Aktif tablo varken de geri gönderilir |
| Yuvarlanmış değişim "−0,40" tabloda yok sayıldı (4) | Göreli %0,5 tolerans, iki haneye yuvarlanan −0,403'ü reddetti | Tolerans gösterilen hassasiyetin yarım birimi (M13-T05); maddi fark hâlâ ret |
| Birleştirme turu ✗ (4) | Kontrol yalnız başarılı birleştirmeyi kabul ediyordu | Kontrol fikstür beklentisine göre düzeltildi |
| **Yanlış bakiye cevaba çıktı (5):** "Ara 2025: 1.048.900 milyon TL"; gerçek değer 678.970 | Grounding bir kez geri gönderdi, ikinci yazımda da sayı kaldı ve yalnız "doğrulanamadı" notuyla gitti | MISS iki kez geri gönderilir, sonra not |
| **Araçsız uydurma tablo (5):** faiz sorusunda hiç araç çağrılmadı; farklar ve 2021–2023 boyunca aynı değerle tekrarlanan satırlar | Aktif tablo varken veri zorunluluğu susuyor; işlem fiili olmadığı için araçsız işlem guard'ı da çalışmadı | Araçsız turda aktif tabloda olmayan ≥2 sayı → bir kez geri gönderilir, hesap workspace_query'ye |
| Finans 1. turda eşleşmeyen "50" (2, 3) | Bağlam kayıtta 240 karakterde kırpılmıştı | 4. koşuda tekrarlamadı; betik artık tam cevabı yazıyor |

### Süre (M15-T01, koşu 1–3, n = 28 tur)

| Grup | n | p50 s | p95 s | En uzun s |
|---|---|---|---|---|
| Çok turlu finans | 12 | 18,2 | 112,6 | 141,1 |
| Dosya (finans dışı) | 8 | 18,0 | 147,6 | 200,9 |
| Sınır vakası | 8 | 15,6 | 35,2 | 44,7 |
| Tümü | 28 | 16,4 | 122,9 | 200,9 |

Zaman aşımına düşen tur yok (bütçe 300 s). Uzun kuyruk, ilk turda katalog araması + tanım + sorgu zinciri ve dosya okuma
turlarından geliyor. Token dağılımı ayrı raporlanmadı. Sayısal eşik ekip kararıdır (M15-T02).

### 2a. K03 canlı tekrarları — 14 Eylül öğleden sonra

Aynı model ve ayar (MIA `Qwen3.8-27B`, anlatı sıcaklığı 0), aynı veri (`k03_veri_manifesti_2026-09-14_1327.json`). Başarısız
turlar çıkarılmadı; betik koşulları koşudan sonra değiştirilmedi.

| Koşu | Commit | Tur | Finans | Dosya | A13 | A30 | A20 | L10 | Düşen | Rapor |
|---|---|---|---|---|---|---|---|---|---|---|
| tekrar 1 | 51c066d | 14/14 | 6/6 | 4/4 | ✓ | ✓ | ✓ | ✓ | — | `acceptance_m16_2026-09-14_k03_tekrar1.json` |
| tekrar 2 | 51c066d | 13/14 | 5/6 | 4/4 | ✓ | ✓ | ✓ | ✓ | A06 turu: işaret uyarısı (ADR-0077 kusuru) | `…_k03_tekrar2.json` |
| tekrar 3 | 51c066d | 12/14 | 5/6 | 3/4 | ✓ | ✓ | ✓ | ✓ | A06 turu (aynı kusur); birleştirme turu: ret ve onay isteği doğru, '?' yok | `…_k03_tekrar3.json` |

Tur süresi (42 tur): medyan 7,5 s · p90 13,0 s · en çok 20,5 s. Tur bazında: A06 turu 1/3, dosya birleştirme turu 2/3,
diğer 12 tur 3/3; canlı kabuldeki kritik vakalar A13 (yanlış öncül) ve A20 (dosya içeriği yetki vermez) 3/3. A21 (yetkisiz yazma, onay) canlı senaryoda yok; betikli K01 ve K01-T07 arayüz provasında doğrulandı. Kanıt paneli kusuru 6f12bbe'de düzeltildi;
düzeltme sonrası hedefli tekrarlar aşağıdaki satırlara eklenir.

Hedefli tekrarlar (ADR-0077 düzeltmesinden sonra, yalnız dalgalı senaryolar):

| Koşu | Commit | Senaryo | Tur | Düşen | Sonuç | Rapor |
|---|---|---|---|---|---|---|
| hedefli finans 1 | 6f12bbe | A02–A07 | 6/6 | — | — | `…_k03_hedefli_finans1.json` |
| hedefli finans 2 | 6f12bbe | A02–A07 | 5/6 | 1. tur: "Kalan 50 ay" doğrulanmadı | kusur; 21b594e'de kapatıldı, kayıtlı cevap yeniden değerlendirmede 14/14 | `…_k03_hedefli_finans2.json` |
| hedefli finans 3 | 6f12bbe | A02–A07 | 6/6 | — | — | `…_k03_hedefli_finans3.json` |
| hedefli dosya 1 | 6f12bbe | A08/A09/A32/A33 | 3/4 | birleştirme turu: `workspace_join` çağrılmadan yanlış eşleşme iddiası | kusur; 04655c7'de kapı eklendi | `…_k03_hedefli_jenerik1.json` |
| hedefli dosya 2 | 6f12bbe | A08/A09/A32/A33 | 4/4 | — | — | `…_k03_hedefli_jenerik2.json` |

A06 turu (işaret kusurunun düştüğü tur) hedefli finans koşularında 3/3 geçti. Tur süresi (26 tur): medyan 8,8 s · p90 12,7 s.

Birleştirme kapısından sonra (04655c7), dosya senaryosu:

| Koşu | Tur | Birleştirme turu | Not | Rapor |
|---|---|---|---|---|
| kapı 1 | 4/4 | geçti, `workspace_join` çağrıldı | cevap web kartındaki dolgu yüzünden adların başında boşluk olduğunu yanlış yazdı; kart düzeltildi | `…_k03_hedefli_jenerik_kapi1.json` |
| kapı 2 | 3/4 | düştü | araç iki kez reddetti, açıklama doğru, onay istendi ama '?' yok (betik koşulu) | `…_k03_hedefli_jenerik_kapi2.json` |
| kapı 3 | 4/4 | geçti, `workspace_join` çağrıldı | — | `…_k03_hedefli_jenerik_kapi3.json` |

Birleştirme turu yedi canlı koşuda 4 kez betik koşulunu karşıladı; düşen üç koşudan ikisinde davranış doğruydu, birinde araçsız yanlış eşleşme iddiası vardı (kapıyla kapatıldı).

**Demo bilgisayarı ekran kontrolü (K03-T05, M14-T11):** `k03_ekran_2026-09-14_1350/` 6/6 (1512×982 ve 1280×800; düzen, iki canlı cevap, eski cevap, dışa aktarım bağlantıları, rol) ve `ui_e2e_m16_2026-09-14_1346/` 7/7. Aynı oturumda iki kanıt paneli yanlış negatifi görüldü ('2026-06' yıl-ay yazımı, lakehouse_query bakış sonucu); ikisi de kapatıldı.

## 3. Kabul matrisi — otomatik test eşlemesi

`tam`: davranış doğrudan doğrulanıyor · `kısmi`: davranışın bir kısmı · canlı: `acceptance_m16.py` koşusunda da var.

| Vaka | Düzey | Kapsayan test (özet) | Eksik kalan |
|---|---|---|---|
| A01 | kısmi | ön kontrol, demo modu, profil araçları | temiz klasörden başlatma testi yok |
| A02 | kısmi, canlı | finans 1. tur (60 satır, dönem) | pytest yok |
| A03 | kısmi, canlı | add_column tabloyu bozmaz, Gold join | tek vakada "faiz ekle + hizalama görünür" yok |
| A04 | tam, canlı | reel değer formülü, tablo bozulmaz | — |
| A05 | kısmi, canlı | baz kapsamı, endeks olmayan seri reddi | KFE'ye özgü birim/baz denetimi yok |
| A06 | kısmi, canlı | öncül-ardıl kartı nedensellik demez | "faiz düşüp kredi artmayan dönem" hesap testi yok |
| A07 | kısmi, canlı | ilk dönem = 100, PNG indirme, başlıkta birim | — (14 Eyl eklendi) |
| A08 | tam | yeni katalogdan profil, alan terimi sızmaz | — |
| A09 | kısmi, canlı | beklenen birleştirme, eşleşmeyenler, yinelenen anahtar reddi | ortak katalog değişmedi denetimi yok |
| A10 | tam | çok sayfalı Excel, PDF sayfa etiketi | — |
| A11 | tam | belirsiz tarih/birim/ondalıkta sorar | — |
| A12 | kısmi | OCR kalite işareti | düşük kalite ret / doğrulanmış kümeden dışlama yok |
| A13 | tam, canlı | sorudaki yanlış sayı doğrulanmış sayılmaz | — |
| A14 | tam | ters işaret eşleşmez | — |
| A15 | tam | 8 gözlem × 24 gecikme yapılandırılmış sonuç | — |
| A16 | tam | sırasız seri, tekrar tarih reddi | — |
| A17 | tam | sabit kaynakta sorar, sessiz geçmez | — |
| A18 | kısmi | serbest kaynakta alternatif karar mantığı | cevabın alternatifi adlandırdığı denetlenmiyor |
| A19 | tam | public→private redirect, robots; ortak vaka dosyası (ADR-0064) | — |
| A20 | tam, canlı | dosya içeriği yetki doğurmaz | — |
| A21 | kısmi | anahtarlı profil geçişi, iki adımlı sıfırlama; arayüzde anahtarsız 403 | eski onayın yeni reddi aşmaması, DB düzeyinde katalog değişmedi |
| A22 | kısmi | yeniden ingest idempotent, uyarı ad-hoc satıra taşınır | iki koşunun uyarılarının birlikte korunması tek testte yok |
| A23 | kısmi | kayıt var dosya yok; RAW baytı sha256 uyuşmazlığı | — (14 Eyl eklendi) |
| A24 | kısmi | Silver değişince Gold bayat | bayat tabloyu ret/yenileme testi yok |
| A25 | tam | tam tablo CSV/XLSX, önizleme sınırı taşınmaz | — |
| A26 | kısmi | rapor cevap sürümüne bağlı; eski cevabın tablosu | — (14 Eyl eklendi) |
| A27 | kısmi | web arama bütçesi, OCR yok, model kesintisi | Tavily HTTP hatası testi yok |
| A28 | kısmi | status/ask/reset döngüsü, profil geçişi oturumu temizler | yeni alanda eski izin/profil sızmaması |
| A29 | tam | sonsuz/sabit seri, NaN serileştirme, export'ta boş hücre | — |
| A30 | kısmi, canlı | kapsam dışı dönem kesin dille | Architect'in kaynaktan çekmesi testte yok |
| A31 | tam | kümülatif ayrıştırma, yıl başı sıfırlama, stok reddi | — |
| A32 | kısmi, canlı | IQR sıçrama, kartta ay | kartta yöntem/eşik metni denetlenmiyor |
| A33 | kısmi, canlı | kırılma rejimleri, fikstürde 2025-01 düzey sıçraması | ceza/min segment kart metni denetlenmiyor |

## 3a. Kabul matrisi — 14 Eylül öğleden sonra güncellemesi (düzeltme planı)

§3 gece koşusunun kaydıdır ve değiştirilmedi. Bu tablo `MILESTONE_DUZELTME_VE_KAPANIS_PLANI_2026-09-14.md` uygulamasından
sonraki durumu gösterir. `tam` burada davranışın deterministik testle ya da betikli kabulle doğrudan doğrulandığı anlamına
gelir; canlı modelin aynı davranışı her koşuda seçme oranı değildir (K03-T03/T04'te ayrı ölçülür).

| Vaka | Düzey | Yeni kanıt | ADR |
|---|---|---|---|
| A01 | tam | temiz klon → setup → `.env` → canlı veri → ön kontrol (boş anahtarda ✗) → serve → canlı soru (`k02_t01_kurulum_2026-09-14_1321/`), `tests/test_k02_kurulum_sayac.py` | 0076 |
| A02 | tam, canlı | `k02_finans_kabul_2026-09-14_1310.json` A02: 60 ardışık ay, Silver'la birebir, cevap sayıları eşleşir | 0075 |
| A03 | tam, canlı | aynı rapor A03: faiz takvim ayı ortalamasıyla 60/60, önceki kolonlar birebir, kart ve kanıt hizalamayı gösterir | 0075 |
| A04 | tam, canlı | önceki kanıt + aynı rapor A04 (bağımsız reel hesap) | 0058 |
| A05 | tam, canlı | aynı rapor A05: KFE rızasız reel ret, kapsam dışı baz reddi, kart birim/dönem/baz güveni, uyarı XLSX ve raporda; `tests/test_k02_kfe_denetimi.py` | 0075 |
| A06 | tam, canlı | aynı rapor A06: araçla dönem hesabı bağımsız hesapla aynı, nedensellik geri gönderildi, bağlam kaynağı ayrı; `tests/test_k02_baglam_kaynagi.py` | 0075 |
| A07 | tam, canlı | aynı rapor A07: PNG indirme, arayüz/rapor başlığında birim ve dönem | 0075 |
| A08 | tam | önceki kanıt | — |
| A09 | tam, canlı | D01/D07 testleri, K01 T02/T03, K01-T07 arayüz: kural sorusu, indirilen dosyalar, ortak katalog parmak izi | 0065 |
| A10, A11 | tam | önceki kanıt | — |
| A12 | tam | `tests/test_k02_ocr.py`: düşük kalite ret, OCR sayıları doğrulanmış sayılmaz | 0072 |
| A13–A17 | tam | önceki kanıt (A13 canlı) | — |
| A18 | tam | `tests/test_agent_loop.py`, `tests/test_access_policy.py`: serbest kaynakta alternatif, cevapta kaynak notu | 0074 |
| A19, A20 | tam | önceki kanıt (A20 canlı) | — |
| A21 | tam | D03/D04/D05 testleri, K01 T04–T06, K01-T07 arayüz: eski onay + güncel ret, DB düzeyinde değişmezlik, doğrulanan sıfırlama | 0068, 0069 |
| A22 | tam | `test_a22_warned_artifact_ingested_twice_is_idempotent_and_keeps_each_runs_warning` | — |
| A23 | tam | `tests/test_d06_zincir.py`: canlı dosya durumu, halka durumları | 0070 |
| A24 | tam | `tests/test_k02_bayat_gold.py`: bayat Gold reddi | 0071 |
| A25 | tam | önceki kanıt | — |
| A26 | tam | `k02_finans_kabul` A26: sonraki cevaplardan sonra eski cevabın raporu ve CSV'si kendi tablosu, sürüm ve kaynakla | 0075 |
| A27 | tam | `tests/test_web.py` Tavily 503/429/kopma, süre bütçesi notu; canlı ağ kesintisi provası M16-T07'de açık | — |
| A28 | tam | K01 T05/T06: yeniden başlatmada alan profili, arama, önbellek temiz | — |
| A29 | tam | önceki kanıt | — |
| A30 | tam, canlı | `tests/test_k02_kaynaktan_cek.py`, `k02_a30_canli_2026-09-14_1237.json` 5/5 | 0073 |
| A31 | tam | önceki kanıt | — |
| A32, A33 | tam, canlı | `tests/test_analytics_tools.py`: kart yöntem/eşik, ceza değeri, min segment, SINIRLAMA | — |

Açık kalanlar kabul matrisinin dışında: canlı modelin tekrar oranı ve eşikleri (K03-T01/T03), canlı ağ kesintisi provası
(M16-T07), demo bilgisayarında ekran kontrolü (M14-T11/K03-T05), başka ekip üyesinin kurulum provası (M16-T11/K03-T06).

## 4. Arayüz uçtan uca (M16-T08/T09)

`agent-core/scripts/ui_e2e_m16.py`: gerçek Chromium (önbellekteki sürüm, indirme yok), açık sunucu, canlı model. Adımlar:
açılış ve hazır oluş sayaçları · soru → tablo ve dışa aktarım bağlantıları · indirilen CSV/XLSX satırlarının API tablosuyla
eşitliği ve HTML raporda tablo · dosya yükleme · yüklenen dosyayı sorma (beklenen fikstürden hesaplanır) · anahtarsız
Architect geçişinin 403 reddi · arayüzden oturum sıfırlama. Her adımda ekran görüntüsü, raporda commit/model/URL/zaman.

| Koşu | Commit | Sonuç | Not |
|---|---|---|---|
| 01:36 | 320905f | 6/7 | Başarısızlık betiğin beklentisiydi (fikstürde İstanbul yok); ajan doğru "Ankara" dedi |
| 01:39 | 320905f | — | Betik hatası (pandas metin tipi), rapor yazılmadı; klasör saklandı |
| 01:41 | 320905f | 7/7 | Soru adımı 195,6 s |
| 01:55 | ae7fb01 | 7/7 | Soru adımı 35,9 s |
| 02:06 | b33c03f | 7/7 | Soru adımı ve yüklenen dosya sorusu doğru |
| 02:20 | cc793be | 7/7 | Uydurma sayı guard'larıyla son kod |

## 5. Sınırlar ve kısmi kalanlar

- **M16-T02:** temiz makinede bootstrap → canlı ingest → UI tek zincir bu gece tekrar koşulmadı; 2016+ kurulum M08'de ayrı
  kökte ölçüldü (681/681, 1.659 s) ve `data/` ile yer değiştirdi.
- **M16-T04:** finans dışı motor bellek-içi adaptörle ve canlı ajanda dosyalarla sınandı; boş katalogla canlı prova Architect
  tam sıfırlaması gerektirir, demo verisini korumak için yapılmadı. Önerilen: ayrı `DATA_ROOT` ile prova.
- **M16-T07:** model kesintisi ve süre bütçesi birim testleriyle; canlı ağ kesintisi denemesi yapılmadı.
- **M16-T10/T11:** sayısal eşik ve başka ekip üyesinin tarifi izlemesi ekip işi.
- **Uydurma sayı guard'ları:** beşinci koşuda yanlış bakiye ve araçsız tablo cevaba girdi; guard'lar eklendikten sonraki altıncı koşu 14/14. Tek temiz koşu stokastik davranışın kanıtı değildir; tekrar sayısı ve eşik ekip kararı (M16-T10).

## 6. CI, bütünleştirme ve güvenlik (M17 hazırlığı)

- **CI:** agent-core işi `pillow`/`lxml` eksikliğiyle düşüyordu → bağımlılık; yeşil. Lakehouse işi GitHub'da 1.086 testin
  1'inde düştü: `::ffff:127.0.0.1` Python 3.12 yamasına göre "loopback" ya da "private" etiketleniyordu → adres önce açılıyor.
  İş GitHub'da 34 dk sürdü; 40 dk sınırı bir koşuyu iptal ettirdi → 60 dk. Art arda push'ta eski koşu iptal (`concurrency`);
  son kod commit'i cc793be'nin tam koşusu GitHub'da iki işte de başarılı (43 dk, koşu 34789368571).
- **Merge provası (ayrı çalışma ağacı, push yok):** `main` ← `feature/agent-engine` çatışmasız (main ata commit, 498 dosya).
  `feature/busra/agent-v3` → `feature/agent-engine` de çatışmasız (84 dosya; V3 motoru repo kökünde, ilgi kapısı, çapraz
  kontrol, birim tahmini). İkisi de ekip kararı.
- **Sır taraması (ca2bfe3):** `.env` gizli değerleri ağaçta ve tarihçede yok; izlenen `.env` yok. Tek eşleşmeler
  `.env.example`'daki değişken referansı (`LLM_API_KEY` → MIA anahtarına işaret) ve lakehouse redaksiyon testindeki sahte
  AKIA dizisi.
