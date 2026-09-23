# Milestone uygulamalarının bağımsız kontrolü — 14 Eylül 2026

İncelenen commit: `196dcfe` (son uygulama değişikliği `cc793be`). Başlangıçta yalnız `.claude/` izlenmeyen kullanıcı dizini vardı; bu dizine dokunulmadı.

**Sonuç:** Uygulama belirgin biçimde ilerlemiş; ancak tüm milestone'lar kabul edilmiş/tamamlanmış sayılamaz. Aşağıdaki doğruluk ve sıfırlama sorunları kapatılmadan tam demo kabulü vermiyorum. Mevcut planın 192 asıl görevinden 152'si `[x]`, 27'si `[~]`, 13'ü `[ ]`; bu sayılar iş eforu veya tamamlanma yüzdesi değildir. Ek EK görevleri bu sayımın dışında.

## 1. Doğrulama kapsamı ve sınırları

- Güncel milestone planı, proje hafızası, M00 ve M16 kabul belgeleri incelendi; yeni çekirdek kodlar ve ilgili testler karşılaştırıldı.
- Agent testleri: **418 geçti**, 4,07 saniye; bir Starlette/AnyIO deprecation uyarısı. Testlerin yeşil olması aşağıdaki ek örneklerin doğru ele alındığı anlamına gelmiyor.
- Yerel salt okunur `--preflight`: demo adaptörü hazır; **2.214 katalog kaydı, 681 yüklü seri, 43.830 gözlem, 6 Gold tablosu, 3.468 artifact, 117 run**. Önceki seed/eksik lakehouse yolu sorunu mevcut ortamda giderilmiş.
- Join ve harness için kontrollü sentetik girdiler; sıfırlama/kurulum için yalnız yeni geçici dizinler kullanıldı. Asıl `data/` içeriği değiştirilmedi; gerçek promotion yapılmadı.
- Bu tur canlı MIA/Tavily/EVDS, yeni OCR veya Playwright provası yapılmadı. M16 belgesindeki canlı sonuçlar önceki çalışmanın kayıtlarıdır; bağımsız olarak yeniden çalıştırılmış gibi sunulmaz.
- Lakehouse hedefli test grubu: **176 geçti**, 213,20 saniye. Gold, toplu ingestion scripti, ad-hoc provenance ve ingestion observability kontrolleri çalıştırıldı; tam 1.086 testlik suite bu tur çalıştırılmadı.

## 2. Öncelikli bulgular

### R01 — P1: İki tabloda farklı kimlikler sessizce eşleşiyor

Kaynak: [workspace_join.py](../../agent-core/src/kkb_agent/tools/workspace_join.py), `_norm_key`, satır 33–45. Milestone: M03/M11, A09.

Sayısal anahtarlar ve sayıya benzeyen metinler `float64`'e dönüştürülüyor. Bu dönüşüm kimlikler için kayıpsız değil. Yeniden üretim:

| Sol anahtar | Sağ anahtar | Gözlenen sonuç |
|---|---|---|
| `9007199254740992` | `9007199254740993` | Eşleşti; sağdaki 99 sol satıra yazıldı |
| metin `001` | metin `1` | Eşleşti; biçim/kimlik eşdeğerliği sorulmadı |
| boş anahtar | boş anahtar | Eşleşti; bilinmeyen kimlikler aynı varlık sayıldı |

İlk örnek kesin hassasiyet kaybıdır. Diğer iki örnek destek sözleşmesinde açık politika gerektirir; her veri alanında kimlik eşdeğerliği varsayılamaz. Tarih normalizasyonu da saat bilgisini düşürüyor; zaman damgası anahtarlarında benzer kapsam kararı gerekir.

**Düzeltme:** tamsayı/metin kimliklerini kayıpsız koru; biçim normalizasyonunu açık semantik/eşleme kararıyla uygula. Eksik anahtarı varsayılan olarak eşleştirme veya görünür politika sun. Bu girdiler için beklenen eşleşme/ret testleri ekle. Sadece normal `il`/`yıl` örneklerinin geçmesi yeterli değil.

### R02 — P1: Yanlış sayı iki yeniden yazımdan sonra hâlâ nihai cevaba giriyor

Kaynak: [agent.py](../../agent-core/src/kkb_agent/core/agent.py), satır 641–691. Milestone: M13/M16.

Sahte araç 2025 Ocak=100, Aralık=110 döndürdü. Sahte model her yeniden yazımda “Aralık bakiyesi 999 milyon TL.” dedi. Gerçek harness sonucu:

```text
grounding: MISS:999
Aralık bakiyesi 999 milyon TL.

(Not: anlatımdaki şu değerler araç çıktısında birebir doğrulanamadı: 999.
Kesin değerler için tabloya bakın.)
```

İki geri gönderme başarı olasılığını artırıyor; son çıkışın doğruluğunu garanti etmiyor. Kullanıcının “eksik kanıt uyarıyla gösterilebilir” tercihi, bilinen doğru Aralık değeri 110 iken 999'un cevap olarak tutulmasını gerektirmez. Bu, beşinci canlı koşuda görülen sınıfın deterministik olarak hâlâ üretilebildiğini gösterir.

**Düzeltme:** yeniden yazımlar bitince doğrulanamayan sayısal cümleyi kaldır; araçtan gelen tablo/hesapla sınırlı deterministik cevap üret veya ilgili iddiayı veremediğini açık söyle. Son çarenin de hatalı sayı üretmesini test et. Mevcut testin “uyarı eklendi” beklentisi bu daha güçlü kabul şartını karşılamıyor.

### R03 — P1: Architect eski onayı kullanarak güncel reddi aşabiliyor

Kaynak: [promote.py](../../agent-core/src/kkb_agent/tools/promote.py), satır 53–55 ve 70–85. Milestone: M04-T07/T09, A21b.

`_user_text()` önce birikmiş bütün kullanıcı metnini alıyor. Şu kontrollü politika çağrısında ret üretilmedi:

```text
Geçmiş: sicaklik taslağını onaylıyorum
Şimdi:  Şimdi sicaklik yayınlama.
Hedef:  adhoc:sicaklik
check_policy sonucu: None (ret yok)
```

Bu tur sadece politika fonksiyonu çalıştırıldı; CLI ve gerçek DB yazımı yapılmadı. Analyst registry ayrımı faydalı ve uygulanmış; bu bulgu Architect profilindeki işlem onayının kapsamıyla ilgilidir.

**Düzeltme:** onayı güncel bekleyen işlem/seri/özetle ilişkilendir; güncel ret ve iptali işle. Geçmişten onay ifadesiyle daha yeni seri adını bir araya getirme. M04-T09 `[x]` işareti, bu zorunlu varyant geçmeden tam kabul anlamına gelmemeli.

### R04 — P1: Tam sıfırlama boş katalog bırakmıyor

Kaynaklar: [web_app.py](../../agent-core/src/kkb_agent/web_app.py), `build_default_app` satır 629–632; [bootstrap.py](../../lakehouse-core/src/lakehouse/db/bootstrap.py), `bootstrap_database`; [application.py](../../lakehouse-core/src/lakehouse/application.py), `run_bootstrap`. Milestone: M03/M04/M16, A21c.

UI resetinin ardından çağrılan `lakehouse bootstrap`, varsayılan finans kataloğunu tekrar yüklüyor. Aynı uygulama fonksiyonunu yeni geçici DB üzerinde çalıştırdım: **`catalog_series_count=2214`**.

Bu, gözlemleri sıfırlama ile boş katalogdan yeni alan kurma arasındaki farktır. Kullanıcının istediği ve M00/A21c'de yazan “boş katalog → başka alan” akışı mevcut reset callback'iyle karşılanmıyor.

**Düzeltme:** yalnız şema kuran bootstrap seçeneğini CLI/reset yoluna taşı; finans başlangıç kataloğunu yeniden yüklemeyi ayrı seçim yap. Alt katmanda `catalog_root=None` zaten var. Silver yeniden kurma ve promotion gibi sonraki işlemlerin de istemeden varsayılan finans kataloğunu geri getirmediği sınanmalı; yalnız ilk reset anını düzeltmek yeterli değildir.

### R05 — P2: Tam sıfırlamada eski grafikler kalıyor, silme başarısı denetlenmiyor

Kaynak: [web_app.py](../../agent-core/src/kkb_agent/web_app.py), satır 321 ve 344–357. Milestone: M04-T06/T08, A21c.

`CHART_DIR` varsayılanı `DATA_ROOT/charts`, fakat bu dizin reset listesinde yok. Geçici kökte `charts/old.png` oluşturup mevcut plan/execute resetini çalıştırdım: dosya kaldı. Ayrıca `rmtree(ignore_errors=True)` başarısız silmeyi bastırıyor, hedef yine `removed` listesine ekleniyor.

**Düzeltme:** hedefleri konfigürasyondan ve veri yaşam döngüsünden türet; eski üretilmiş çıktıları kapsa. Silme sonrası yokluk kontrolü yap, başarısız hedefi başarı diye raporlama. Eski bağlantıları kapatma/yeniden kurma ve bootstrap başarısızlığında kullanıcıya dürüst durum gösterme kabulü eklenmeli. Yalnız sabit dizin listesinin varlığı tam reset kanıtı değil.

### R06 — P2: Eksik RAW/Bronze zinciri hâlâ tam gösterilebiliyor

Kaynak: [evidence.py sözleşmesi](../../agent-core/src/kkb_agent/contracts/evidence.py), satır 53–60 ve `EvidencePanel.chain_ok`. Milestone: M13-T09, A23.

`file_present`, dolu `bronze_path` varsa diske bakmadan `True` döndürüyor. RAW yokken Bronze tek başına da tam zinciri geçiriyor. Geçici dosyalı deney:

```text
RAW yok, Bronze mevcut: chain_ok=True
Bronze da silindi; aynı kanıt nesnesi: chain_ok=True
```

Adaptörün nesneyi oluştururken Bronze yolunu doğrulaması, daha sonra dosya silinmesini veya RAW halkasının eksikliğini karşılamıyor. Tam kaynak zinciri ile yalnız elde kalan işlenmiş dosyayı ayırmak gerekir.

**Düzeltme:** gerekli halkaları ve hangi anda doğrulandığını açık sözleşmeye bağla; RAW/uygun hash ve Bronze durumlarını ayrı kontrol et. Sadece Bronze kalmışsa “işlenmiş veri var, ham kaynak eksik” göster. Yolları dolu olan ama silinmiş dosyalar da regresyon vakası olsun.

### R07 — P1: Join kullanıcının `__k` kolonunu sessizce siliyor

Kaynak: [workspace_join.py](../../agent-core/src/kkb_agent/tools/workspace_join.py), satır 99–100 ve 127. Milestone: M03/M11, A09.

Araç geçici anahtar için sabit `__k` kolonunu kullanıp sonunda düşürüyor. Sol tablo `id=a, __k=preserve-me`, sağ tablo `id=a, value=99` olduğunda başarılı sonuç yalnız `id=a, value=99` içeriyor; kullanıcının kolonu kayboluyor. `_merge` gibi diğer yardımcı adlar da kullanıcı kolonlarıyla çakışabilir.

**Düzeltme:** her iki tabloda bulunmayan geçici adlar üret veya kolon eklemeden anahtar serileriyle birleştir; kullanıcı kolonlarını ve kaynaklarını aynen koru. Ayrılmış kolon adları desteklenmiyorsa veri kaybetmeden açıkça reddet. Kolon sayısı/adları ve değer koruması kabul testine girmeli.

## 3. Milestone kapanış değerlendirmesi

| Alan | Değerlendirme |
|---|---|
| M01 yerel kurulum | Mevcut bilgisayarda preflight başarılı; başka ekip üyesinin temiz kurulumu hâlâ ayrı kabul |
| M02 motor kıyası | Rapor/karar mevcut; bu tur canlı kıyas yeniden yapılmadı |
| M03/M11 jeneriklik ve join | Yeni yetenek var; R01 ve boş katalog kabulü nedeniyle tam kapanış verilmez |
| M04 profil/reset | Registry ayrımı var; R03/R04/R05 ve pasifleştirme kapsamı nedeniyle kısmi |
| M05/M06 erişim | Agent regresyonları yeşil; yeni canlı kaynak/auth/crawl provası bu tur yapılmadı |
| M07/M08/M09 veri ve Gold | Gerçek veriler ve run kayıtları var; 176 hedefli lakehouse testi geçti, tüm alan kabulü yeniden koşulmadı |
| M10 dosya/OCR | Kod ve testler var; rapordaki düşük kaliteli OCR kabulü kısmi |
| M12 analitik | Agent regresyonları yeşil; raporda yöntem/önkoşul ve bazı senaryoların kapsamı kısmi |
| M13 iddia/kanıt | Eski hatalar için yeni korumalar var; R02/R06 ve açık bağlamsal eşleme görevleri sürüyor |
| M14 arayüz/export | Yeni uçlar mevcut ve agent suite içinde test edildi; önceki Playwright 7/7 kaydı bu tur yeniden üretilmedi |
| M15 performans | Süre/başarı eşikleri hâlâ açık; preflight başarısı performans kabulü değildir |
| M16 birleşik kabul | Kendi raporu 14 tam / 19 kısmi / 0 yok diyor; tek son temiz canlı koşu bütün 33 vakayı kapatmıyor |
| M17 teslim | Başka kişi kurulum provası, teslim sürümü ve freeze/ek teslim kararları tamamlanmadan kapanmaz |

Özellikle `[x] M04-T09` içindeki eski onay/güncel ret varyantı ile `[x] M13-T09` fiziksel zincir koşulu yeniden açılmalı. Milestone haritasındaki “tamamlandı” ile altındaki “kısmi” ifadeleri ayrı durumlara dönüştürülmeli. Bu incelemede kullanıcının işaretleri doğrudan değiştirilmedi.

## 4. Önerilen düzeltme sırası

1. R01/R07 kayıpsız join, R02 güvenilir son cevap, R03 işlem kapsamlı onay.
2. R04 şema-only boş reset ve yeni alanla yeniden kurulum; R05 tam temizleme/doğrulama.
3. R06 eksik dosya zinciri ve M13'te açık dönem/kolon/varlık bağlamı.
4. A09/A21c'yi ayrı geçici veri kökünde gerçek CLI + agent üzerinden tamamla; ana DB değişmediğini fingerprint ile göster.
5. Kısmi kabul vakalarını kapat; son kodla bütçeli canlı tekrar ve başka ekip üyesi kurulumu yap. En son teslim etiketi/freeze.

## 5. Doğrulama kaydı

Çalıştırılan test komutları (ilgili paket dizininde):

```bash
# agent-core
.venv/bin/python -m pytest -q
.venv/bin/python -m kkb_agent.cli --preflight

# lakehouse-core
.venv/bin/python -m pytest -q tests/gold tests/scripts/test_run_catalog_ingestion.py tests/adhoc/test_run_artifact_provenance.py tests/ingestion/test_pipeline_observability.py
```

Bu tur uygulama düzeltmesi, merge/push, ana veri sıfırlaması veya credential değişikliği yapılmadı. Doküman ve hafıza kaydı dışında çalışma ağacı korunmuştur. Mevcut testlerden geçen davranışlar ve yukarıdaki ek örneklerden kalan açıklar birlikte değerlendirilmelidir.
