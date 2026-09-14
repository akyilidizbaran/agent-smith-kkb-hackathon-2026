# Milestone planına gelen geri bildirimin değerlendirmesi

Tarih: 13 Eylül 2026. İncelenen yerel commit: `67cd6f9`.

Dayanak: [milestone planı](MILESTONE_PLANI_2026-09-13.md), [ADR-0039](adr/0039-architect-ikinci-kapi-ve-sohbette-kalan-analiz.md), kullanıcının bu tur eklediği dört maddelik arkadaş geri bildirimi.

Bu belge değerlendirme ve revizyon önerisidir; aşağıdaki ilk değerlendirme, bölüm 5'teki kullanıcı yanıtlarıyla birlikte okunmalıdır. Kullanıcı rol ve iki tablo kapsamını netleştirdi; bunlar ana plana işlendi. Motor ve 45 görevlik kapsam seçimi kararlaştırılmadı. Uygulama kodu değiştirilmedi; canlı model çağrısı, veri yayını veya merge yapılmadı.

## 1. M04 — Architect sınırı

**Karar: geri bildirime kısmen katılıyorum; mevcut planın gerekçe cümlesi düzeltilmeli ve uygulama kapsamı daraltılmalı.**

- Mevcut kod geçici analiz ve kalıcı yazma yollarını zaten ayırıyor. `workspace_query` bellek içindeki tabloyu işler; ingest/promotion ayrı CLI üzerinden çalışır. ADR-0039 bu ayrımı ve iki gerçek deneyi kaydeder. “Mevcut akış ayrımı sağlamıyor” ifadesi bunu yok sayacak kadar geniştir.
- Buna karşılık bu ayrım, “son kullanıcı kalıcı yayın yapamaz, yalnız ekip yapabilir” kuralıyla aynı değildir. `cli.py` Silver adaptörü ve kullanılabilir CLI olduğunda ingest ve promotion araçlarını aynı registry'ye kaydediyor; kullanıcı/ekip profili koşulu yok. `promote.py` onay ifadesini ve seri kimliğini arıyor; kişinin ekip üyesi olup olmadığını belirlemiyor.
- Bugünkü davranış ADR-0039'un sohbetten onayla yayın kararına uygundur. Yeni Analyst-only tercihi kabul edilirse gereken fark, bu yeteneğin jüri oturumunda kullanılmamasıdır. Henüz kabul edilmemiş yeni tercihi eski kodun hatası diye sunmamalıyız.
- Plan zaten kurumsal kimlik sistemini zorunlu saymıyordu. Arkadaşın bu maliyetten kaçınma önerisine katılıyorum. “2–3 gün” ölçülmüş tahmin değildir; seçilecek uygulamaya ve ekibin kapasitesine bağlıdır.

**Önerilen asgari çözüm:** Yerel başlatma ayarıyla Analyst/jüri ve operator çalışma profili; jüri profilinde ortak kataloğa yazan araçların registry'ye hiç eklenmemesi. Bu anahtarı sohbet metni veya tarayıcı isteği değiştirmemeli. Operator akışında ADR-0039'un taslak, beyan, onay, derived ve provenance kontrolleri korunmalı. Ayrı kullanıcı hesabı sistemi, yayın talebi paneli veya kurumsal rol altyapısı bu yerel demo için gerekmez.

**Israr edilmesi gerekenler:**

1. Sadece düğme gizleme veya modele gösterilen araç listesini azaltma yeterli değildir. Registry `schemas(only=...)` görünürlüğü filtreler; `execute()` kayıtlı aracı bulup çalıştırma doğrulamasına yollar. Jüri kısıtı kabul edilirse doğrudan araç çağrısı da engellenmeli.
2. Dosya/URL analizi çalışırken ortak DB ve katalog değişmemeli; bu, uygulama sonrası parmak iziyle sınanmalı.
3. Eski onay farklı veya artık reddedilmiş bir işleme otomatik onay sayılmamalı. Bu tur yalnız `check_policy` üzerinde yapılan deneyde geçmişte “sicaklik taslağını onaylıyorum” ve yeni turda “yalnız göster, yayınlama” olan metin `None` döndürdü: politika reddi yok. CLI çalıştırılmadı. Bu sonuç her gerçek sohbetin yazacağı anlamına gelmez; araç çağrılırsa mevcut politika kapısının bu çelişkiyi yakalamadığını gösterir.
4. Enjeksiyon testi yalnız yeni bir kötü URL'den ibaret olmamalı: daha önce izin verilmiş kaynak, geçmiş onay, açık ret ve kapalı araç adının doğrudan çağrılması da sınanmalı.

**Plan revizyonu:** M04 gerekçesine “geçici/kalıcı işlem ayrımı mevcut; ekip/jüri profil sınırı henüz yok” yazılmalı. M04-T01/T02/T03/T09/T10 tek profil ve kabul paketi altında toplanabilir. M04-T05 yayın talebi arayüzü koşula bağlı olmalı. ADR-0039 silinmemeli; karar çıkarsa profil kapsamını anlatan ek karar yazılmalı. Onay kontrolü M04-T07 kapsamında korunmalı.

## 2. M03 — Genel veri şekilleri

**Karar: Silver'ı genel ilişkisel veri deposuna çevirmeme önerisine katılıyorum. Bu, planla esasen çelişmiyor.**

- M03-T02 zaten hangi şeklin Silver'a, hangisinin workspace'e gireceğinin belirlenmesini ve sahte tarih/ölçüm türü uydurulmamasını istiyor. Silver'ın her tabloyu taşıması şartı yok.
- Önerilen açık sözleşme: kalıcı seri yayını mevcut zaman serisi Silver sözleşmesine uyar; tarihsiz/işlemsel tablolar oturum alanında analiz edilir ve otomatik ortak yayına girmez. Kaynağın finans dışı olması tek başına Silver'a girmesini engellemez: sıcaklık zaman serisi buna uygun olabilir.
- Bu tur tarihsiz `category/amount` tablosunu workspace'e verip gruplama yaptım: A=30, B=7 döndü. Tek tablo üzerinde temel tarihsiz analiz zaten çalışıyor; sıfırdan yapılacak iş değildir.
- Ancak mevcut `workspace_query` her sorguda yalnız aktif tabloyu `t` adıyla DuckDB'ye kaydediyor. Genel çok tablolı oturum veritabanı yok. “İlişkisel veriyi destekliyoruz” ifadesi iki yeni dosyayı bağımsız tablolar olarak birleştirme vaadine dönüşmemeli.

**Israr edilmesi gerekenler:** Jeneriklik yalnız “finans dışı soruya cevap yazdı” diye kabul edilmemeli. Tarihsiz veri için bilinen doğru filtre/gruplama/hesap, tablo ve kaynak korunması, çıktı alma, ortak DB'nin değişmemesi gösterilmeli. Başka alanın verisine finans varsayımı veya sahte tarih eklenmemeli.

**Plan revizyonu:** M03-T02 ve K03'e bu iki depolama yolunu yaz; A09'u tarihsiz tek tablo için hesaplanmış beklenen sonuçla güçlendir. İki dosyanın anahtarla birleştirilmesi zorunlu olacaksa ayrıca vaka ekle; mevcut tek tablo deneyi bunu kanıtlamaz. REST/DB/stream için her adaptörü veya kapsamlı bir çatı oluşturmak koşula bağlı kalsın; destek sınırını belgelemek yeterli olabilir.

## 3. M02 — Beş tekrar ve canlı koşu maliyeti

**Karar: bütün vakalarda baştan beş tekrar istemekten vazgeçilmesine katılıyorum. “Üç tekrar yeterlidir” ve yakın sonuçta “fark yoktur” hükümlerine katılmıyorum.**

- Arkadaşın 16 soru × 2 motor × 5 tekrar = 160 senaryo koşusu hesabı doğru. Üç tekrar 96 koşudur; 64 koşu, yani %40 azalma. Bunlar model çağrısı sayısı değildir: her senaryo birden fazla LLM çağrısı yapabilir. Planın kendisi 16 soruyu sabitlememişti; bu hesap önerilen soru seti varsayımına dayanıyor.
- Beş tekrar benim başlangıç önerimdi, resmî eşik veya istatistiksel garanti değildi. Sabit bir sayı bütün vaka türleri için doğru değildir.
- Eski [motor kıyas raporu](MOTOR_KARSILASTIRMA_YANIT.md) aynı kodda 0/3 → 3/3 değişimi kaydeder. Bu eski ölçüm bugünkü iki motorun sonucunu söylemez; küçük örneklemle kesin üstünlük ilan etmemeyi gerektirir.
- Yakın sonuç “eşitlik kanıtı” değildir. Doğru ifade: “Bu koşul ve örneklemde karar verecek kadar belirgin üstünlük gösterilemedi.” Ekip yine de mevcut entegrasyon, yetenek kapsamı ve taşıma maliyetine göre pratik baseline kararı alabilir.

**Önerilen protokol:**

1. Ortak yetenek seti ile ürün kapsamı kontrolünü ayır; çalışmayan kurulum ve eksik araçları önce offline/contract kontrolünde bul.
2. Aynı veri, model ayarı ve sürümlerle üç dengeli tekrar ilk tarama olsun; bütün hata ve timeout'lar kaydedilsin.
3. Ek tekrarları sonucu değiştirebilecek, dalgalanan veya kritik vakalara ayır; her vakayı otomatik beşe tamamlama.
4. Ek bütçe yoksa belirsizliği raporla. Sayısal hata veya kontrol ihlalini iyi ortalama skorla örtme.
5. Motor seçimini ve son demo adayının M16 kabul provasını ayrı tut. İlk kıyasın üç tekrarı nihai teslim doğrulamasının yerine geçmez.

**Plan revizyonu:** M02-T05 “üç tekrar ilk tarama; kritik/belirsiz vakaya bütçeli ek tekrar; belirgin üstünlük yoksa belirsizlik kaydı” biçimine getirilebilir. Kesin süre/token bütçesi kaynak ve ekip kararı bekler.

## 4. Görev sayısını yaklaşık 45'e indirmek

**Karar: daha küçük bir demo çalışma listesine katılıyorum; 45 sayısını kabul kapsamını kesmenin gerekçesi yapmaya katılmıyorum.**

- Güncel belge yaklaşık 150 değil, 192 alt görev, 18 milestone ve 29 kabul vakası içeriyor. Arkadaşın başka sürüm incelemiş olması mümkündür.
- Ayrıntı düzeyi kullanıcının bütün işleri nedenleriyle kaydetme isteğine uygundu; fakat her kontrol satırını bağımsız geliştirme işi gibi sunmak günlük yönetimi zorlaştırır. Planımın bu yönünü sadeleştirmeliyiz.
- Her görev aynı maliyette değildir: bir karar, mevcut testi koşma, yeni dosya akışı ve motor taşıma aynı “bir görev” sayılmaz. 45 görev teslim süresi hesabı değildir.
- Ayrıntılı katalog korunup demo için yaklaşık 35–45 sonuç odaklı iş paketi çıkarılabilir. Her paket eski Mxx-Tyy kimliklerine ve kabul vakalarına bağlanır. Böylece gerekli kontroller kaybolmadan ekip daha kısa listeyle çalışır.
- Her eski satırın durumu açık olmalı: demo paketine dahil, mevcut ve doğrulanacak, koşula bağlı, freeze sonrası veya açık karara bağlı. Hiçbir satır sessizce kaybolmamalı.

**Korunacak demo sonuçları:** tekrar kurulabilir gerçek ortam; zorunlu BDDK/EVDS kapsamı ve doğru semantik; dosya/URL/PDF girişleri; jenerik yeni veri analizi; çok turlu tablo korunması; gerekli analitik önkoşullar; sayısal iddia/kanıt düzeltmeleri; güvenli erişim ve anlaşılır fallback; tam tablo/grafik/rapor indirme; son sürümle birleşik prova. Analyst-only profili ise kullanıcı/ekip kararı çıkarsa bu kapsama girer.

**Koşula bağlanabilecek somut örnekler:** M04-T05 yayın talebi arayüzü; M06-T09 genel browser yeteneği (zorunlu kaynak gerektirirse açılır); M02-T08 ve M15-T08 bağımsız araç paralelliği (ölçülmüş kazanç varsa); M15-T11 test süresini optimize etme; M14-T12 yeni görsel yolculuk geliştirmeleri; çoklu export uzantıları (tablo/grafik/raporun kendisi zorunlu kalır); M03-T06 bütün kaynak tipleri için çatı/adaptör geliştirmeleri. Bazı satırlar zaten koşullu yazılmıştır; kısa listede görünür biçimde ayrılmalıdır.

**Ertelenmemesi gereken somut açıklar:** yanlış %300'ün onaylanması, korelasyon işaretinin yanlış kanıtlanması, eksik RAW/Bronze için tam kanıt etiketi, private redirect kontrolü, kısa/sırasız seride hatalı analiz, Infinity'nin yanıtı bozması, toplu ingestion'da run/warning izinin kaybı. İlgili kapsam kullanılacaksa bu hataları görev sayısı uğruna gizlemek doğru değildir.

## 5. Kullanıcı yanıtları ve değerlendirmeye etkisi

1. **Kesin kullanıcı kararı:** jüri demosunda iki akış da gösterilebilir; normal kullanıcı ortak kataloğa yazamaz. Yalnız Architect kalıcı yazma/silme ve veri mimarisi değişikliklerini yapar. Sonuç: jüriyi yalnız Analyst'e kilitleyen tek profil yeterli değildir; demo kurulumunda Analyst ve Architect gösterim yolları bulunmalı, normal kullanıcı kendi yetkisini sohbetten yükseltememeli. Kimlik sistemi eklemek hâlâ otomatik gereksinim değildir. Silme için hedefin açık gösterilmesi ve kontrollü işlem kabulü gerekir; bu karar şimdi veri silme talimatı değildir.
2. **Kesin kullanıcı kararı:** iki yeni tabloyu birleştirmek zorunlu. Sonuç: workspace'te birden fazla kaynak tablonun kimliğinin korunması, anahtar eşleme, yinelenen anahtar/kardinalite, eşleşmeyen satırlar ve kolon kaynak zinciri kabul kapsamına girer. Silver'ı genel ilişki deposuna dönüştürmek yine gerekli değildir. Bu iş koşullu listeye taşınamaz.
3. Mentörden Architect onay akışı hakkında yeni cevap yok. 45 görev önerisinin somut listesi veya ek kodu yok. Sonuç: bu sayı ölçülmüş veya uygulanabilirliği doğrulanmış kapsam olarak alınamaz; önce görev-kabul eşlemesi yapılmalı.

Ana planın rol ve genel tablo maddeleri bu kullanıcı kararlarıyla güncellendi. Üç tekrarlı ilk tarama ve hedefli ek ölçüm önerisi de beş tekrar önerisinin yerine yazıldı; kesin bütçe açık kaldı. Asıl planın görevleri topluca koşulluya taşınmadı. Architect silmesinin katalogdan kaldırma mı fiziksel RAW/Bronze silme mi olacağı uygulama öncesinde netleşmeli; mevcut karardan fiziksel kanıt silme veya kod değişikliği yetkisi çıkarılmamalı.

## 6. Bu tur doğrulama

- `agent-core/.venv/bin/python -m pytest -q tests/test_intent.py tests/test_promote_tool.py tests/test_workspace_query.py`: 15 geçti, 0,41 saniye.
- Tarihsiz workspace sorgusu: A=30, B=7; başarılı.
- Geçmiş onay + güncel yayınlama reddi için yalnız promotion politika çağrısı: ret üretmedi; gerçek CLI/DB yazımı yapılmadı.
- Kod kaynakları: `agent-core/src/kkb_agent/cli.py`, `core/registry.py`, `core/agent.py`, `tools/promote.py`, `tools/workspace_query.py`.
- Sequential Thinking aracı etkin araç listesinde aranıp bulunamadı; karşılaştırma yerel doküman/kod ve offline doğrulamayla yapıldı. Bu görevde web/SDK veya arayüz davranışı hakkında yeni dış doğrulama iddiası yoktur.

## 7. Tam sıfırlama hakkındaki son kullanıcı yanıtı

Kullanıcı her türlü silmeyi ve ortamın tamamen boşaltılıp yeniden kurulmasını hedeflediğini açıkladı, görüş istedi. Önerim **iki ayrı işlem**: günlük pasifleştirme/katalogdan kaldırma ve Architect'e özel fiziksel tam veri sıfırlama.

- Tam sıfırlama katalog, RAW/Bronze/Silver/Gold, oturum verisi ve ilişkili önbellekleri birlikte ele alır; yalnız DB dosyasını silmek yeterli değildir.
- Kod, bağımlılık kilitleri, kurulum tarifleri ve credential yapılandırması veri sıfırlamasına dahil edilmez. “Mimariyi sıfırlama” burada veri ortamının boşaltılıp yeniden kurulması olarak yorumlanmıştır; agent'ın kendi kaynak kodunu silmesi/değiştirmesi değildir.
- Fiziksel silmenin ardından eski kaynak kanıtı mevcutmuş gibi gösterilemez. Yedek alınmışsa “bütün kopyalar yok edildi” denemez; yedek tercihi işlem kapsamının parçasıdır.
- Hedef ortam ve silinecek kaynaklar işlem öncesinde listelenir; onay o hedef/kapsama bağlıdır, eski sohbet onayı kullanılamaz. İşletim profili Architect olmalıdır.
- Kabul deneyi ayrı geçici veri kökünde yapılır: oluştur → analiz et → sıfırla → boşluğu doğrula → farklı veriyle yeniden kur → analiz et. Test dışı dizinlere dokunulmadığı doğrulanır.
- Bu yeni hedef M04'ü sadece bir profil anahtarından daha geniş kılar; reset yaşam döngüsü ve kabul testi artık gerçek iş kalemidir. Yine kurumsal kimlik altyapısı veya genel Silver şeması gerektirmez.

Bu konuşmada sıfırlama işlemi yapılmadı. Somut silinecek ortam henüz seçilmiş değildir.
