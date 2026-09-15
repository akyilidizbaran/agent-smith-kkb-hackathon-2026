# ADR-0080 — PR #4 (kullanıcı hatası kapıları) entegrasyonu ve kimlik sorusu

**Tarih:** 15 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** kullanıcı kararı (PR #4'ü birleştirip eksiklerini biz düzeltelim),
kimlik deneyi (`docs/experiments/kimlik_alan_deneyi_2026-09-15_1546.json`)

## Bağlam

Büşra'nın PR #4'ü (`feature/user-error-gates`, 30 commit):
- uygunluk kapısı, soru ön koşulu, öncül aracı, netleştirme, iddia denetimi, önizleme ve kalite bayrakları;
- V3 motoru ve araştırma dokümanları.

Bu tarihte PR main'e çatışmasız biniyordu, ama agent-core CI'ı kırmızıydı. Bizim `feature/agent-engine` işimizle birleşik ağaçta
611 test geçti, 3'ü kırıldı. Kabul koşusu A06'yı ve kimlik deneyi iki sorunu daha gösterdi:

1. **PDF'ten tablo, `web_url` (test_vision).** OCR belgesi geniş tabloydu (Yıl | Ocak | Şubat). Uygunluk kapısı satır başına bir
   yıl gördüğü için tabloyu yıllık saydı ve "2025 Ocak" sorusunu granülarite gerekçesiyle reddetti.
2. **PDF'ten taslak seri, `ingest` (test_vision).** İlgi kapısı iki şeyi konu terimi saydı: pytest geçici yolunun dizin parçalarını
   (`folders`, `incoming`, kullanıcı adı) ve kullanıcının beyan cümlesini ("birim kg, ölçüm tipi dönemlik akım, aylık kural
   toplam"). Dosyayı ilgisiz saydı.
3. **V3 çalışma alanı adaptörü (tests/v3).** 14 Eylül'de bizim workspace araçlarımız boş tablo denetimini `run()` öncesine,
   `validate_refs`'e taşıdı. `run()` içinde yalnız `assert` kaldı. Adaptör ön denetimi çağırmadığı için boş tabloda
   `AssertionError` alıp `TOOL_FAILED` döndü; beklenen kod `WORKSPACE_EMPTY`.
4. **K02 A06.** Kabul sorusu: "Faiz oranlarının düştüğü halde kredi miktarının yükselmediği dönemler olmuş mu?"
   - Öncül kalıbı "düştüğü halde" ifadesini yön varsayımı saydı.
   - Ajan `check_premise` çağrılmadı diye cevabı geri gönderdi; betikli turlar kaydı ve kabul 21/22 kaldı.
   - Soru bir yön varsaymıyor, koşulu sağlayan dönemi arıyor.
5. **Kimlik sorusu.** Aktif tablo yokken ajan "Sen kimsin?" cevabını "veri çekilmeden cevap denendi" diye geri gönderiyordu.
   - Modelin ilk taslağı doğruydu. Yeniden yazılan cevap "önceki mesajın 'Sen kimsin?' idi…" diye bozuluyordu.
   - Tek kullanıcı serili DB'de model kendini tanıtmak yerine tablo döküyordu.
   - Arayüzde görülen iyi cevap yalnız aktif tablo varken geliyordu; o durumda kural çalışmıyor.
6. **Yalnız kullanıcı serisi olan katalog.** Üç ayrı sorun:
   - Alan tanımı iç kimlik olarak kalıyordu: "adhoc kaynaklı veriler".
   - Veri seti cevabı yarım cümleydi ("Kullanıcının eklediği 1 seri de var.") ve seriyi adıyla anmıyordu.
   - Onaylanan serinin kapsamı 1900 görünüyordu; `meta.series` first_obs/last_obs onaydan sonra da boş kalıyor.
7. **Yükleme ön eki.** Arayüzün dosyaya koyduğu 8 onaltılık ön ek, model `series_key` vermeyince seri anahtarına giriyordu
   (ADR-0068 eki bunu yalnız onay eşleşmesinde tolere ediyordu).

## Karar

- **PR #4 olduğu gibi alınır.** Merge commit kullanılır; Büşra'nın 30 commit'i yeniden yazılmaz, yazar ve kimlikler korunur.
  Düzeltmeler entegrasyon dalında (`integration/user-error-gates-main`) ayrı commit'lerle gelir. Büşra'nın dalına push yapılmaz.
  main'e önce PR #4, hemen ardından düzeltme PR'ı birleştirilir; ikisi de kullanıcı onayıyla.
- **Geniş ay kolonlu tablo aylıktır** (`core/fitness.py`). Yıl kolonu ve en az iki ay adı kolonu (Türkçe ya da İngilizce) varsa
  frekans `monthly` sayılır.
- **İlgi kapısında adres dosya adına indirgenir** (`tools/ingest.py`). Adres silinmez: kullanıcının dosyayı adıyla anması
  ("sicaklik.csv dosyasını ekle") ilgi işaretidir.
- **Beyan sözcükleri yalnız soru tarafında düşer** (`builder/relevance.py`). Örnekler: belge, birim, ölçüm, tipi, kural, dönemlik,
  akım. Tam sözcük olarak düşer, kök olarak değil; böylece `birimsiz.csv` dosya adı korunur. Durak listesine eklenmez: katalog
  alias'ında ("kalem türü") anlam taşırlar.
- **V3 adaptörü ön denetimi iletir** (`kkb_agent_v3/tools/workspace.py`). `validate_refs` ve `check_policy` iç araçtan gelir ve
  hata kodu eşlemesinden geçer.
- **"halde" kalıbı dönem aramasında öncül değildir** (`core/question_preflight.py`).
  - Soru "dönemler olmuş mu", "hangi aylar", "ne zaman" gibi bir arama içeriyorsa kalıp öncül sayılmaz.
  - "düştüğü için" ve "neden arttı" öncül kalır. Aynı nesne agent ve tool_gate tarafından `.search` ile kullanılır; öncül kalıbı
    tek yerde kalır.
- **Kimlik sorusu veri istemez.**
  - `is_identity_question` (`core/small_talk.py`) kısa, rakamsız ve ikinci tekil soruları tanır: kimsin, neler yapabilirsin,
    kendini tanıt.
  - Agent "veri çekilmeden cevap" geri göndermesini bu sorularda yapmaz.
  - Diğer kapılar aynen kalır: genel bilgi, araçsız sayı, işlem iddiası.
  - Cevabı model yazmaya devam eder; aktif tablo varsa ondan bahsedebilir.
  - "Faiz düşerse kredi ne yapabilir?" veri sorusu olarak kalır.
- **Kullanıcı serisi adıyla anılır** (`domain.py`, `core/small_talk.py`).
  - Yalnız türetilmiş katman varsa alan tanımı serilerin adıyla kurulur, ör. "kullanıcının eklediği acil basvuru verileri".
  - Veri seti cevabı kullanıcı serilerini adı ve kapsamıyla sayar.
  - Katalog adı deterministik kalır ("acil_basvuru — acil_basvuru_aylik.csv (taslak)"; aynı dosyanın ikinci ingest'i çakışmasın
    diye); okunur ad yalnız gösterimde kırpılır.
- **Kapsam gözlemlerden okunur** (`adapters/silver_lakehouse.py`). Seri sayımı sorgusu dönem aralığını da okur. `meta.series`
  first_obs/last_obs boşsa kapsam oradan gelir; 1900 yer tutucusu cevaba yazılmaz.
- **Yükleme ön eki seri anahtarına girmez** (`tools/ingest.py`).

## Sonuçlar

- Ajan testleri birleşik ağaçta 621 geçti (önce 611 + 3 kırık); yeni testler `tests/test_pr4_entegrasyon.py`.
- K02 finans kabulü entegrasyon dalında 22/22 (`docs/experiments/k02_finans_kabul_2026-09-15_1617.json`); A06 kapandı.
- K01-T07 arayüz kabulü 15/15 (`docs/experiments/k01_ui_kabul_2026-09-15_1618/`).
- K01 ilk koşusu 21/22 (`k01_kabul_2026-09-15_1618.json`). Tek kırmızı T06: beklenti alan tanımında iç kimlik "adhoc"
  arıyordu. Beklenti serinin okunur adına ("web ziyaret") ve sızıntı yokluğuna sıkılaştırıldı; yeniden koşu 22/22
  (`k01_kabul_2026-09-15_1620.json`).
- Kimlik deneyi yeniden koşuldu: aynı beş DB, gerçek model (`docs/experiments/kimlik_alan_deneyi_2026-09-15_1620.json`).
  "Sen kimsin?" 15 denemenin 15'inde kimlik anlatıyor; "önceki mesajın…" metni ve tablo dökümü yok.
  - Önce: finans 3/3 bozuk, boş 3/3 bozuk, sağlık 2/3 tablo dökümü, web 1/3 düzgün, finans + sağlık 3/3 bozuk.
  - Sağlık ve web DB'lerinde alan "kullanıcının eklediği acil basvuru / web ziyaret verileri" oldu.
  - Veri seti cevabı kullanıcı serisini adı ve kapsamıyla sayıyor.
  - Kalan: finans + sağlık DB'sinde kimlik cevabı yalnız birincil kaynakları anlatıyor, kullanıcı serisini anmıyor. Bilinçli: alan
    tanımı birincil kaynaktan kurulur, veri seti sorusu kullanıcı serisini sayar.
- `builder/relevance.py`, `core/fitness.py` ve `question_preflight.py` Büşra'nın modülleri. Değişiklikler dar tutuldu ve her biri
  ölçülmüş bir bulguya bağlandı; UEB benchmark'ı yeniden koşulmadı.
- Kalan bilinen durum: lakehouse-core onaydan sonra `meta.series` adını ve kapsamını güncellemiyor. Ajan tarafında telafi
  edildi; kaynağı veri ekibinin kodunda.
