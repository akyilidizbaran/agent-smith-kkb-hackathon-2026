# M16 — Birleşik kabul raporu

**Tarih:** 14 Eylül 2026 (gece koşusu) · **Dal:** `feature/agent-engine` · **Model:** MIA `Qwen3.8-27B` (anlatı sıcaklığı kabulde 0)
**Veri:** `data/lakehouse.duckdb` — 681 zorunlu seri 2016-01 → 2026-06 (M08) · **Profil:** Analyst

Başarısız koşular rapordan çıkarılmadı. "Birim testi geçti", "canlı model geçti" ve "arayüz uçtan uca geçti" ayrı
sütunlardır; biri diğerinin yerine yazılmaz (M16 risk notu).

## 1. Özet

| Katman | Sonuç | Kanıt |
|---|---|---|
| Ajan birim/sözleşme testleri | 416 geçti | `make test`, CI agent-core işi yeşil |
| Lakehouse testleri | 1.086 geçti (yerel, 12 dk) | GitHub'da tek düşen test düzeltildi (§6) |
| Kabul matrisi A01–A33 test eşlemesi | 14 tam · 19 kısmi · 0 yok | §3 |
| Canlı çok turlu kabul (14 tur × 4 koşu) | 10 → 11 → 11 → 12 | `docs/experiments/acceptance_m16_*.json` |
| Arayüz uçtan uca (Playwright) | 6/7 → 7/7 → 7/7 → 7/7 (son kod b33c03f) | `docs/experiments/ui_e2e_m16_*/rapor.json` + ekran görüntüleri |

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
| 02:06 | b33c03f | 7/7 | Soru adımı ve yüklenen dosya sorusu doğru; son kod |

## 5. Sınırlar ve kısmi kalanlar

- **M16-T02:** temiz makinede bootstrap → canlı ingest → UI tek zincir bu gece tekrar koşulmadı; 2016+ kurulum M08'de ayrı
  kökte ölçüldü (681/681, 1.659 s) ve `data/` ile yer değiştirdi.
- **M16-T04:** finans dışı motor bellek-içi adaptörle ve canlı ajanda dosyalarla sınandı; boş katalogla canlı prova Architect
  tam sıfırlaması gerektirir, demo verisini korumak için yapılmadı. Önerilen: ayrı `DATA_ROOT` ile prova.
- **M16-T07:** model kesintisi ve süre bütçesi birim testleriyle; canlı ağ kesintisi denemesi yapılmadı.
- **M16-T10/T11:** sayısal eşik ve başka ekip üyesinin tarifi izlemesi ekip işi.
- **Canlı teyit bekleyen:** finans 3. turun hassasiyet toleransıyla geçmesi (düzeltme 4. koşudan sonra yapıldı).

## 6. CI, bütünleştirme ve güvenlik (M17 hazırlığı)

- **CI:** agent-core işi `pillow`/`lxml` eksikliğiyle düşüyordu → bağımlılık; yeşil. Lakehouse işi GitHub'da 1.086 testin
  1'inde düştü: `::ffff:127.0.0.1` Python 3.12 yamasına göre "loopback" ya da "private" etiketleniyordu → adres önce açılıyor.
  İş GitHub'da 34 dk sürdü; 40 dk sınırı bir koşuyu iptal ettirdi → 60 dk. Art arda push'ta eski koşu iptal (`concurrency`);
  son commit'in lakehouse işi sessiz bir aralıkta tamamlanmalı.
- **Merge provası (ayrı çalışma ağacı, push yok):** `main` ← `feature/agent-engine` çatışmasız (main ata commit, 498 dosya).
  `feature/busra/agent-v3` → `feature/agent-engine` de çatışmasız (84 dosya; V3 motoru repo kökünde, ilgi kapısı, çapraz
  kontrol, birim tahmini). İkisi de ekip kararı.
- **Sır taraması (ca2bfe3):** `.env` gizli değerleri ağaçta ve tarihçede yok; izlenen `.env` yok. Tek eşleşmeler
  `.env.example`'daki değişken referansı (`LLM_API_KEY` → MIA anahtarına işaret) ve lakehouse redaksiyon testindeki sahte
  AKIA dizisi.
