# Milestone düzeltme ve kapanış planı

**Tarih:** 14 Eylül 2026  
**Durum:** Yapılacak işler; henüz uygulanmış veya doğrulanmış değildir.  
**Dayanak:** `196dcfe` sürümündeki [bağımsız kontrol](MILESTONE_DOGRULAMA_2026-09-14.md).  
**Ana plan:** [Milestone planı](MILESTONE_PLANI_2026-09-13.md). Bu belge ana planın yerine geçmez; incelemede bulunan eksiklerin uygulama ve kabul listesidir.

## 1. Kullanım ve kapsam

- D01–D07 doğrudan yeniden üretilen R01–R07 bulgularını kapatır. K01–K04 bunların ürün akışına bağlanmasını ve kalan demo kabulünü tamamlar.
- Her görev benzersiz kimlik taşır. Sorumlu ve gözden geçiren ekipçe atanır; burada kişi veya kesin iş süresi varsayılmaz.
- Bir görev ancak belirtilen beklenen sonuç ve kanıtla tamamlanır. Kodun varlığı, HTTP 200, dosya oluşması veya toplam test sayısı tek başına kabul değildir.
- Yeni mimari tercihler öneridir; desteklenen veri davranışı sözleşmeye yazılmalıdır. Mevcut doğru davranışlar ve önceki kararların tarihçesi korunur.
- Bu belge mevcut demo verisini silme veya branch/merge/push işlemi yapma talimatı değildir. Sıfırlama kabulü yalnız ayrı geçici veri kökünde yapılır.
- İnceleme sırasında agent 418, hedefli lakehouse 176 test geçti. Bunlar başlangıç kanıtıdır; aşağıdaki açıkların kapandığını göstermez. Yeni sonuçlar yeni commit ve test girdileriyle kaydedilir.
- Öncelik P1/P2, inceleme raporundaki önem derecesidir. P2, zorunlu kabulü sağlayan bir düzeltmenin otomatik ertelenebileceği anlamına gelmez.

## 2. İş paketleri ve bağımlılıklar

| Paket | Sonuç | Kaynak | Bağımlılık | Öncelik |
|---|---|---|---|---|
| D01 | Kayıpsız ve açık kurallı anahtar eşleme | R01 / M03, M11 / A09 | Yok | P1 |
| D02 | Yanlış sayıyı nihai cevapta tutmayan çıkış | R02 / M13, M16 | Yok; K02 ile bütünleşir | P1 |
| D03 | İşlem kapsamına bağlı güncel onay | R03 / M04 / A21b | Yok | P1 |
| D04 | Boş katalogdan yeniden kurulabilen veri ortamı | R04 / M03, M04, M16 / A21c | D03/D05 ile bütünleşir | P1 |
| D05 | Eksiksiz ve doğrulanabilir sıfırlama | R05 / M04 / A21c | D03/D04 ile bütünleşir | P2 |
| D06 | Fiziksel kanıt halkalarının doğru durumu | R06 / M13 / A23 | D05 ile bütünleşir | P2 |
| D07 | Join sırasında kolon ve değer korunması | R07 / M11 / A09 | D01 ile birlikte doğrulanır | P1 |
| K01 | Gerçek iki tablo ve sıfırlama kabulü | M03, M04, M10, M11, M16 | D01–D07 | Zorunlu kabul |
| K02 | Kısmi kabul senaryolarının kapanması | M08–M16 | İlgili düzeltmeler | Zorunlu kabul |
| K03 | Son sürüm, bütçeli prova ve tekrar kurulabilirlik | M01, M15–M17 | K01/K02 | Teslim kapısı |
| K04 | Plan ve kanıt kayıtlarının tutarlı kapanışı | Tüm ilgili milestone'lar | Her paket sonunda | Süreç |

Numaralar katı seri geliştirme sırası değildir. Aynı dosyada D01/D07 ve D04/D05 değişiklikleri birlikte tasarlanmalıdır; tek tek çelişen çözümler üretilmemelidir.

## 3. D01 — Join anahtarlarında veri kaybını kaldır

**Neden:** `_norm_key` anahtarları float64'e çeviriyor. `9007199254740992` ve `9007199254740993` eşleşiyor; metin `001` ile `1` de örtük olarak aynı kabul ediliyor. Bu hata başarılı görünen yanlış analiz üretir.

**İlgili kod:** [workspace_join.py](../agent-core/src/kkb_agent/tools/workspace_join.py).

- [x] **D01-T01** (ADR-0065 ve modül belgesi: tamsayı/metin/tarih/zaman/boş/farklı tip davranışı): Anahtar tipleri için destek sözleşmesi yaz: tam sayı, metin, tarih, zaman damgası, eksik değer ve iki tarafta farklı tip.
- [x] **D01-T02** (tamsayı Python int; ondalık okunmuş ≥2^53 kimlik reddedilir; test büyük ardışık ve float kimlik): Tam sayı kimliklerini float64 üzerinden dönüştürme; kaynakta mevcut hassasiyeti koru. Kaynak okuyucu kimliği önceden bozmuşsa sonradan doğruluk iddia etme.
- [x] **D01-T03** (metin olduğu gibi; metin_normal/sayi yalnız açık seçim, sonucu değiştirirse sorulur; test 001/1): Metin kimliklerinde baştaki sıfırları koru. Sayıya çevirme, büyük/küçük harf katlama ve boşluk temizleme gibi eşdeğerlikleri açık politika yap; sonucu değiştirecek belirsizlikte kullanıcıya sor.
- [x] **D01-T04** (boş anahtar eşleşmez, sayısı karta yazılır; test): Eksik anahtarların birbirini eşleştirmesini varsayılan olarak engelle veya açık alternatif politika sun. Null anahtar sayısını ve sonuç üzerindeki etkisini göster.
- [x] **D01-T05** (zaman damgası saatiyle; tarih↔zaman farkı tarih_gun sorar; ham saat kaynakta kalır; test): Tarih ile zaman damgasını ayır; saat/saat dilimi bilgisi kaybolmasın. Gün düzeyine indirme gerekiyorsa belirtilmiş eşleme kuralı olsun.
- [x] **D01-T06** (yineleme kural sonrası denetlenir, kural kaynaklı yineleme ayrıca söylenir; çoktan-bire ve eşleşmeyenler iki yönde; test): Normalizasyon sonrası yeni çakışma oluşursa sessiz devam etme. Sağ anahtar tekrarları, çoktan-bire ilişkiler ve eşleşmeyen satırları aynı kurala göre say.
- [x] **D01-T07** (kartta 'Anahtar kuralı' satırı, sağ kolon provenance SQL'inde kural; ham değerler korunur; test): Anahtarın hangi dönüşümle eşleştirildiğini kartta ve provenance kaydında göster; kaynak tabloların ham değerlerini koru.

**Kabul örnekleri:**

| Girdi | Beklenen |
|---|---|
| Farklı ardışık büyük tamsayılar | Asla yanlış eşleşmez; beklenen eşleşmeyen sonuç veya kontrollü ret |
| `001` ve `1` metin kimlikleri | Açık eşdeğerlik kararı yoksa farklı kalır |
| Boş kimlikler | Sessizce aynı varlık sayılmaz |
| Aynı gün iki farklı saat | Zaman damgası anahtarında ayrı kalır |
| Bildirilmiş metin/tamsayı eşleme | Doğru eşleşir; kullanılan kural görünür |
| Yinelenen sağ anahtar | Satırları fark ettirmeden çoğaltmaz |

**Kapanış kanıtı:** beklenen birleşim tablosu, satır/kolon sayımı ve kaynak değerlerinin değişmediğini doğrulayan regresyonlar; D07 testleri birlikte geçer.

## 4. D02 — Model ısrar etse de yanlış sayısal cevabı yayımlama

**Neden:** İki yeniden yazımdan sonra 999 iddiası, doğru Aralık değeri 110 olmasına rağmen uyarıyla nihai cevapta kalıyor. Tek temiz canlı koşu bu çıkış yolunu kapatmaz.

**İlgili kod:** [agent.py](../agent-core/src/kkb_agent/core/agent.py), [grounding.py](../agent-core/src/kkb_agent/core/grounding.py), [agent döngüsü testleri](../agent-core/tests/test_agent_loop.py).

- [x] **D02-T01** (MISS = desteklenmeyen iddia → çıkar; kaynak zinciri eksik ama tabloda olan sayı rozetle uyarılı kalır (ADR-0066)): Eksik kaynak kanıtı ile yanlış/hesapla desteklenmeyen sayısal iddiayı ayır. Doğru hesap, eksik kaynak uyarısıyla sunulabilir; yanlış değer aynı şekilde korunamaz.
- [x] **D02-T02** (_final_exit: birim çıkarma, anlam kalmazsa tablo özeti + 'güvenilir açıklama üretemedim'; tablo yoksa sınır cümlesi): Yeniden yazma bütçesi bittiğinde uygulanacak deterministik çıkışı tanımla: doğrulanmış tablo/hesap ve sınırlama mesajı veya ilgili iddiayı verememe.
- [x] **D02-T03** (not yanlış sayıyı tekrar etmez; çıkarılanlar rejected_claims'te, izde yalnız etiketli MISS kaydı): Uyuşmayan sayısal cümleleri kullanıcıya doğru cevap gibi taşıma. “999 yanlış olabilir” gibi aynı yanlış anlatıyı koruyan uyarı tek çözüm olmasın; reddedilen iddia gerekirse ayrı iz kaydı olarak gösterilsin.
- [x] **D02-T04** (döngü kilidi, adım sınırı ve süre bütçesi yolları _checked_final; model hatası yolu sayı üretmez (ADR-0061); test adım sınırı): Son çıkışı yalnız normal döngüde değil adım limiti, zaman aşımı, araçsız son tur ve model hatası yollarında da uygula.
- [x] **D02-T05** (araçsız turda aktif/önceki tablo ve bakışlarla denetim, eşik 1 sayı; test): Tabloyla önceki sohbetten dönen yanıtı da kontrol et; araç çağırmamak doğrulama kapısını atlatmasın. Kontrol yalnız iki veya daha fazla yanlış sayı olduğunda etkinleşmesin.
- [x] **D02-T06** (kanıt paneli, sohbet geçmişi, arayüz yükü ve HTML rapor aynı son metinden kurulur; test: geçmiş temiz): Son metin, evidence rozetleri, kaydedilen sohbet ve dışa aktarılan rapor aynı sonuç durumunu taşısın; kullanıcıya kaldırılmış sayı export'ta geri gelmesin.
- [x] **D02-T07** (her tur 999 diyen model testi; doğru/yuvarlanmış cevap değişmez; eski 'uyarı eklendi' testi güncellendi): Sürekli yanlış cevap veren kontrollü model testini ekle; mevcut “uyarı eklendi” beklentisini doğruluk kabulüne göre güncelle. Doğru ve makul yuvarlanmış cevaplar da çalışmaya devam etsin.

**Kabul:** araç Ocak=100/Aralık=110 verirken model her tur 999 dese bile nihai sonuç Aralık=999 iddiası taşımaz. Kullanıcı doğru tabloya ulaşır; sistem güvenilir bir açıklama üretemediğini gerektiğinde söyler. Son çözüm yeni model çağrılarının sonsuz döngüsüne dayanmaz.

## 5. D03 — Onayı bekleyen işleme bağla

**Neden:** Birikmiş metindeki eski onay, güncel “yayınlama” isteğini aşabiliyor. Analyst araç kaydının kapalı olması Architect'in yanlış işlem yapmasını önlemiyor.

**İlgili kod:** [promote.py](../agent-core/src/kkb_agent/tools/promote.py), [registry.py](../agent-core/src/kkb_agent/core/registry.py), [agent.py](../agent-core/src/kkb_agent/core/agent.py), [web_app.py](../agent-core/src/kkb_agent/web_app.py).

- [x] **D03-T01** (PendingOp: seri, işlem, kapsam özeti, gösterildiği tur (core/approvals.py, ADR-0068)): Bekleyen işlem için hedef seri/katalog, işlem türü ve gösterilmiş kapsamı taşıyan durum tanımla. İşlem kimliği veya kapsam özeti yaklaşımı seçilebilir.
- [x] **D03-T02** (registry.current_message ve tur sayacı; onay yalnız güncel mesajdan): Güncel kullanıcı mesajını geçmiş açıklama bağlamından ayır. Eski onay + yeni seri adı birleştirilerek yetki üretilmesin.
- [x] **D03-T03** (güncel ret/iptal kazanır ve bekleyeni kapatır; başka hedef adı ret/netleştirme; test): Güncel ret, iptal ve hedef değişikliğini işle; kapsam değiştiğinde önceki onay geçersizleşsin.
- [x] **D03-T04** (kısa evet yalnız önceki turda gösterilmiş tek bekleyende; çok bekleyende sorulur; test): Belirli bir işlem için verilmiş kısa “evet/onaylıyorum” yanıtını destekle; her tur seri adını tekrar ettirmek zorunlu olmasın. Birden fazla bekleyen hedef varsa sor.
- [x] **D03-T05** (onay denemede tüketilir; başarısız işlem yeniden onay; tekrar çağrı ikinci işlem üretmez; test): Onayın tüketilmesi, aynı isteğin tekrarı ve başarısız işlemin yeniden denenmesi için açık davranış belirle. İdempotent sonuç başka bir işleme onay sayılmasın.
- [x] **D03-T06** (Gold hesap rızası ile yayın onayı sözcükleri ayrıldı; test): Derived veriyi hesapta kullanma rızası ile kalıcı yayın/silme yetkisini ayır; birini diğerinin yerine kullanma.
- [x] **D03-T07** (reset/profil ajanı ve kayıt defterini yeniden kurar, bekleyen düşer; dış içerik mesaj değildir; test): Oturum/profil değişiminde bekleyen onayı temizle. Dış dosya/web talimatı onay durumunu değiştiremesin.
- [x] **D03-T08** (tests/test_d03_onay.py gerçek ToolRegistry yolu, retlerde CLI çağrısı 0; Analyst'te UNKNOWN_TOOL): Sadece politika fonksiyonunu değil gerçek registry yolunu da sınayan test ekle; reddedilen durumda CLI çağrısı ve veri değişikliği olmamalı.

**Kabul matrisi:** eski onay + güncel ret → ret; A serisine onay + B hedefi → ret/netleştirme; açık güncel doğru hedef → yalnız o işlem; reset/profil değişimi → eski onay geçersiz; tekrar çağrı → ikinci farklı işlem yok. Analyst'te kapalı araç hâlâ çalıştırılamaz.

## 6. D04 — Gerçek boş katalog ve yeni alanla yeniden kurulum

**Neden:** Mevcut reset callback'i bootstrap ile 2.214 finans serisini geri getiriyor. Kullanıcı “veriyi boşaltıp yeni alanı kurma” hedefini açıkça belirledi.

**İlgili kod:** [web_app.py](../agent-core/src/kkb_agent/web_app.py), [bootstrap.py](../lakehouse-core/src/lakehouse/db/bootstrap.py), [application.py](../lakehouse-core/src/lakehouse/application.py), [CLI](../lakehouse-core/src/lakehouse/cli.py).

- [x] **D04-T01** (meta.lakehouse_setting + bootstrap_database(catalog_mode) + run_bootstrap/CLI `bootstrap --catalog none|default` (ADR-0069); lakehouse tests/catalog/test_catalog_mode.py): Şema kurma ve başlangıç veri kataloğunu yükleme işlemlerini CLI/uygulama sözleşmesinde ayır. Mevcut `catalog_root=None` yeteneğini uygun giriş yoluna taşı.
- [x] **D04-T02** (arayüz sıfırlaması varsayılan `--catalog none`; başlangıç kataloğu ayrı açık seçim (ResetRequest.catalog); doğrulama seri 0 + kip none): Tam veri sıfırlaması sonrasında şema mevcut, kullanıcı/veri kataloğu boş durumda başlat. Finans kataloğu yüklemek ayrı açık seçim olsun.
- [x] **D04-T03** (silver, gold, promote, ingest bileşimi ve yeniden bootstrap kayıtlı kipe uyar; toplu finans ingest betiği boş kipte durur; test): Ingest, promotion, Silver/Gold build, yeniden açılış ve diğer bootstrap çağrılarını incele; sonraki işlem finans kataloğunu kendiliğinden geri getirmesin.
- [x] **D04-T04** (kip DB'de kalıcı; bayraksız sonraki bootstrap kipi korur; test 'restart' vakası): Seçilen katalog çalışma biçimini yeniden başlatmada koru. Tek seferlik reset bayrağı sonraki süreçte kaybolmasın.
- [x] **D04-T05** (K01 T05/T06: sıfırlama sonrası ajan boş DB ile kuruldu; yeniden başlatmada profil 'adhoc kaynaklı veriler', arama finans serisi döndürmedi, önbellek yok; bootstrap boş Silver ilişkisi kurar (K01 bulgusu)): Boş adaptörle agent kurulabilsin; “veri yok” durumu kontrollü olsun. Profil, retrieval, alias, eski SQL bağlamı ve cache önceki finans alanını taşımamalı.
- [x] **D04-T06** (K01 T04/T05: gerçek CLI ile finans dışı taslak → beyan → onay → Silver → Gold çeyreklik toplam beklenenle aynı (flow_periodic; count tipinde Gold reddi tasarlanmış)): Finans dışı yeni seri için taslak → beyan → açık onay → Silver → uygun Gold hesabı akışını gerçek CLI ile göster.
- [x] **D04-T07** (K01 T02/T03: iki genel tablo oturumda birleştirildi ve hesaplandı; ortak katalog sayı+içerik parmak izi değişmedi): Aynı ortamda iki genel tabloyu oturumda analiz et; bunlar istemeden ortak zaman serisi kataloğuna yayımlanmasın.

**Kabul:** ayrı geçici kökte reset sonrası `meta.series` veri kaydı sayısı sıfır; şema sağlam; yeni finans dışı veri yüklenip yayımlandıktan ve süreç yeniden açıldıktan sonra eski finans seri kimlikleri geri gelmez. Yeni alanın hesabı modelden bağımsız beklenen sonuçla eşleşir. Kod, kurulum ve asıl demo veri kökü korunur.

## 7. D05 — Tam sıfırlamada kapsamı ve başarıyı doğrula

**Neden:** `charts/` kapsam dışında kalıyor; `ignore_errors=True` başarısız silmeyi gizleyebiliyor. Onaylanan hedefleri listelemek ile gerçekten temizlemek ayrı işlerdir.

**İlgili kod:** [web_app.py](../agent-core/src/kkb_agent/web_app.py), [config.py](../agent-core/src/kkb_agent/config.py).

- [x] **D05-T01** (ResetPaths.from_settings: DB+WAL, raw/bronze/silver/quarantine, INGEST_ALLOWED_ROOT/uploads, CHART_DIR, önbellek kökü): DB/WAL, RAW/Bronze/Silver/Gold materyalleri, yüklemeler, grafikler, üretilmiş raporlar ve cache için mevcut konfigürasyon yollarını çıkar; var olmayan depolama katmanı icat etme.
- [x] **D05-T02** (veri kökü dışı ayar önizlemede listelenir, sıfırlama reddedilir; test): Yönetilen veri kökü dışına ayarlanmış hedefleri sessizce atlayıp “tam sıfırlandı” deme. Korunan/kapsam dışı yolu açık göster veya reseti kontrollü reddet.
- [x] **D05-T03** (önizleme hedefleri/korunanları gösterir; onay kodu hedef+kök dışı+katalog seçimine bağlı, kapsam değişirse 409; test ve arayüz penceresi): Önizlemede silinecek veri kapsamını ve korunan kod/kurulum/sırları göster; onayı bu hedefe bağla. Önizlemeden sonra kapsam değişirse yeniden inceleme gereksinimini belirle.
- [x] **D05-T04** (oturum kilidi içinde, önce ajanın DuckDB okuyucuları kapanır; test): Silmeden önce ilgili agent/DB okuyucularını kapat, eşzamanlı yazma/yükleme ile çakışmayı engelle; D03 onay kontrolünü işlem sınırında uygula.
- [x] **D05-T05** (hedef başına silindi/zaten yok/silinemedi/korunuyor; silinemeyen removed'a girmez; test): Her hedef için gerçek sonucu kaydet: silindi, zaten yok, silinemedi, korunuyor. Silinemeyen dosyayı `removed` listesine ekleme.
- [x] **D05-T06** (silme sonrası yokluk; bootstrap hatası ve yeni DB'nin beklenen durumu (seri 0, kip none) doğrulanır, aksi 'kısmi'; test): Silme sonrası yokluk kontrollerini yap; DB yeniden kurulmuşsa boş/yeni durumu ayrı kontrol et. Bootstrap hatasını başarılı reset gibi sunma.
- [x] **D05-T07** (geçmiş, cevaplar, tablolar, yüklemeler temizlenir; oturum kimliği değişir; ajan yeniden kurulur, kurulamazsa raporda): Eski sohbet, tablo, grafik bağlantısı ve cache referanslarını temizle veya açıkça geçersiz işaretle. Yanlış veriyle otomatik devam etme.
- [x] **D05-T08** (tests/test_d05_sifirlama.py geçici kökte: izin hatası, bootstrap hatası, dolu katalog, kök dışı hedef, uçtan uca; asıl data/ korunur): Geçici kökte izin/IO hatası, bootstrap hatası, eksik dosya, dış hedef ve tekrar çağrı testleri ekle; asıl veri dizinine dokunulmadığını doğrula.

**Kabul:** `charts/old.png` dahil onaylanan eski çıktılar kalmaz; kısmi başarısızlık doğru raporlanır. Kod ve gizli yapılandırma korunur. Yeniden kurulum D04'ün boş katalog davranışını sağlar. Pasifleştirme işinin durumu ayrı tutulur; tam resetin varlığı tek seri pasifleştirmeyi tamamlanmış yapmaz.

## 8. D06 — Kanıt zincirini gerçek dosya durumuyla eşleştir

**Neden:** Bronze yolu doluysa `file_present=True`; dosya silinse bile mevcut kanıt nesnesi tam kalabiliyor. RAW yokken Bronze var olması tam ham kaynak zinciri değildir.

**İlgili kod:** [evidence sözleşmesi](../agent-core/src/kkb_agent/contracts/evidence.py), [Silver adaptörü](../agent-core/src/kkb_agent/adapters/silver_lakehouse.py), [evidence oluşturucu](../agent-core/src/kkb_agent/core/evidence.py).

- [x] **D06-T01** (Silver/adhoc gözlemi RAW+Bronze+özet; web/belge URL+sha256+zaman (ADR-0070)): Kaynak türüne göre gerekli halkaları yaz: Silver gözlemi için metadata/RAW/Bronze; web/belge için kendi kaynak baytı sözleşmesi. Her kaynağa yanlışlıkla aynı zorunluluk dayatma.
- [x] **D06-T02** (yol metni, canlı varlık/okunabilirlik, raw_digest_ok ve checked_at ayrı alanlar): Yol metni, dosyanın varlığı, okunabilirliği, hash doğruluğu ve denetim zamanını ayrı bilgiler olarak taşı.
- [x] **D06-T03** (altı halka durumu; yalnız Bronze kalması 'ham kaynak eksik' kısmi; denetlenmemiş özet tam sayılmaz): RAW/Bronze için gerekli kontrolleri yap; “Bronze mevcut, RAW eksik” durumunu kısmi göster. Hash denetlenmediyse denetlenmiş gibi sunma.
- [x] **D06-T04** (varlık canlı okunur; özet önbelleği (yol, boyut, mtime) — silinen dosya yeşil kalmaz; test): Dosya kontrolü önbelleği kullanılırsa geçersizleştirme kuralı belirle. Reset/silme sonrası eski yeşil durum korunmasın; geçmiş doğrulama ile mevcut erişilebilirlik ayrı ifade edilsin.
- [x] **D06-T05** (dosya zinciri rozeti ayrı; sayılar ve sorgu izi etkilenmez; test): Sayısal doğruluk, semantik güven, sorgu izi ve fiziksel zincir durumlarını birbirinin yerine kullanma. Kaynağı eksik doğru tablo gereksizce yanlış sayılmasın.
- [x] **D06-T06** (panel özeti/boşluk ve render '(YOK)', arayüz yükünde chain_state ve dağılım; HTML rapor boşluklardan aynı cümle): UI ve rapor dışa aktarımında eksik halkayı anlaşılır göster; kaynak taşınmışsa güvenli yol çözümleme davranışını koru.
- [x] **D06-T07** (tests/test_d06_zincir.py altı vaka + sonradan silme + gerçek adaptörde RAW silinmiş; fikstür gerçek sha256): RAW yok/Bronze var, RAW var/Bronze yok, ikisi yok, bozuk RAW hash'i, sonradan silinmiş dosya ve eksiksiz zincir vakalarını ekle.

**Kabul:** eksik halka varken “tam kaynak zinciri” yok; tamamı mevcut ve doğrulanmış örnek doğru biçimde tamdır. Yeniden denetimden sonra silinmiş kaynak tam görünmez. Sınırlama, indirilen raporda da bulunur.

## 9. D07 — Join yardımcı kolonlarını kullanıcı verisinden ayır

**Neden:** Kullanıcının `__k` alanı geçici anahtarla ezilip sonuçtan düşüyor. Genel veri agent'ı kolon adından dolayı sessiz veri kaybedemez.

**İlgili kod:** [workspace_join.py](../agent-core/src/kkb_agent/tools/workspace_join.py).

- [x] **D07-T01** (yardımcı adlar (__k, _merge, sonekler) çakışma listesi ADR-0065): `__k`, `_merge`, otomatik sağ sonekleri ve diğer yardımcı adların her iki tablodaki kolonlarla çakışabileceğini listele.
- [x] **D07-T02** (yardımcı kolon hiç kullanılmıyor: anahtar sözlüğüyle eşleme): Çakışmayan geçici adlar üret veya yardımcı kolonsuz eşleme kullan; sadece tek rezerv adı başka sabit adla değiştirme.
- [x] **D07-T03** (kaynak tablolar assert_frame_equal ile değişmemiş; yalnız sonuç kurulur): Kullanıcının mevcut kolonlarını ve kaynak tablo kopyalarını koru; yalnız aracın oluşturduğu geçici alanları kaldır.
- [x] **D07-T04** (sonek doluysa sayı soneki (value_k2_2); sonuç kolonları benzersiz; test): Sağ kolon soneki zaten mevcutsa ikinci çakışmayı yönet; sonuçta yinelenen veya belirsiz kolon adı üretme.
- [x] **D07-T05** (yeniden adlandırma kartta ve provenance'ta aynı ad; test): Kolon yeniden adlandırma kararını kartta ve provenance'da aynı şekilde uygula.
- [x] **D07-T06** (tests/test_d01_d07_join.py: __k=preserve-me, _merge, hazır value_k2, aynı adlar, açık columns, outer/inner): `__k=preserve-me`, `_merge`, hazır `value_k2`, aynı adlı sol/sağ kolonlar ve açık `columns` seçimi için değer/kolon koruma testleri ekle.

**Kabul:** incelemedeki `id=a, __k=preserve-me` girdisinin alanı ve değeri sonuçta korunur. Sağdan seçilen değer eklenir; kaynak tablolar değişmez. Desteklenmeyen durum varsa veri kaybından önce açık ret verilir.

## 10. K01 — İki kritik akışı gerçek bileşenlerle kapat

**Neden:** Tek fonksiyon veya sahte bootstrap testinin geçmesi gerçek demo akışını kanıtlamaz. Düzeltmeler özellikle A09 ve A21c ile birleşmelidir.

- [x] **K01-T01** (geçici kök ve DB; kök dışı kontrol dosyası; asıl demo DB sha256 önce/sonra aynı): Teste özel kök/DB ve dışarıda korunacak kontrol dosyaları oluştur; kapsamın asıl demo dizininden bağımsızlığını kontrol et.
- [x] **K01-T02** (Analyst iki dosya yükleme, ayrı kaynak kimlikleri, kural sorusu, açık kuralla birleştirme, takip hesabı, CSV/XLSX/HTML indirme): Analyst ile iki ayrı yeni dosya yükle; ayrı kaynak kimliklerini koru; belirtilen anahtarla birleştir, takip hesabı yap ve tam tablo/raporu indir.
- [x] **K01-T03** (beklenen değerler (16,371…/18,029…/16,360…/Trabzon boş), kolon kaynakları ve anahtar kuralı provenance'ta, ortak katalog parmak izi aynı): Sonucu beklenen satır/değerlerle karşılaştır; her kolonun kaynağını ve yükleme öncesi/sonrası ortak DB/katalog fingerprint'inin aynı olduğunu doğrula.
- [x] **K01-T04** (Architect gerçek CLI: taslak; onaysız ve 'yayınlama' turlarında ret, DB (durum, Silver sayısı, dosya özeti) aynı; güncel onayla yayın): Architect'te gerçek taslak/yayın ve geçersiz onay senaryolarını CLI üzerinden çalıştır. Ret durumunda dosya/DB değişikliği olmadığını göster.
- [x] **K01-T05** (önizleme → kod → fiziksel sıfırlama (tamamlandı, seri 0, kip none) → yeni alan taslak/yayın → kırılma analizi 2025-01-31): Önizleme → kapsamlı onay → fiziksel reset → şema-only kurulum → farklı alan verisi → analiz akışını gerçek bileşenlerle çalıştır.
- [x] **K01-T06** (yeniden başlatma: bayraksız bootstrap boş kipi korudu, profil/arama sızıntısız, Analyst'te yazma araçları yok): Yeniden başlat ve alan profilini kontrol et; eski katalog/cache/izin/çıktı geri gelmesin. Ardından Analyst'te kalıcı yazmanın hâlâ kapalı olduğunu sınayarak profillerin görevlerini doğrula.
- [ ] **K01-T07:** UI üzerinden her iki akışı göster; otomatik Playwright adımları model sonucu yanında dosya, tablo ve durum değişimini de kontrol etsin.

**Kabul:** gerçek CLI ve son uygulama sürümüyle A09/A21a–c sonuçları tam; test dışı dosyalar korunmuş; raporda model/commit/veri manifesti ve tekrar bilgileri mevcut. Kaydedilmiş sonucu canlı çıktı gibi sunma.

## 11. K02 — Kısmi kabul senaryolarındaki eksikleri tamamla

Dayanak: [M16 kabul raporu](M16_KABUL_RAPORU.md). Aşağıdakiler her biri yeni özellik yazılması gereken işler değildir; bazıları mevcut davranışa eksik kabul kanıtı ekler. Uygulama bozuk çıkarsa ilgili milestone yeniden açılır.

| Görev | Vaka/kapsam | Yapılacak doğrulama ve kapanış |
|---|---|---|
| K02-T01 | A01 / M16-T02 | Temiz ortamdan kurulum → gerekli veri → API/UI zincirini aynı sürümle göster |
| K02-T02 | A02/A03 | 60 aylık istek ve faiz ekleme/hizalamayı tek oturumda, tam dönem/satır beklentisiyle doğrula |
| K02-T03 | A05 | KFE eklenmesinde birim, baz ve dönem denetimi; kaynak sütunlar korunur |
| K02-T04 | A06 | Faiz düşerken kredi artmayan dönemleri araçla hesapla; dış bağlamı ayrıca kaynaklandır, nedensellik diye sunma |
| K02-T05 | A07/A26 | Grafik ve eski cevap raporundaki dönem/birim/kaynak/uyarı ve sürüm tutarlılığı; önceki ek testler tam kapsamı karşılıyorsa statüyü kanıtla düzelt |
| K02-T06 | A12 | Düşük kaliteli OCR örneğinde uyarı/kontrollü ret ve doğrulanmamış değerin kesin sonuç sayılmaması |
| K02-T07 | A18 | Alternatif kaynak kullanıldığında gerçek cevabın kullanılan kaynağı adlandırması |
| K02-T08 | A22 | Aynı artifactin iki ingest koşusunda veri idempotent; her koşunun run/warning izi korunur |
| K02-T09 | A24 | Silver değişiminden sonra bayat Gold'u yalnız etiketlemekle kalma; ret/yenileme davranışını ve yanlış eski sonuç verilmediğini göster |
| K02-T10 | A27 | Tavily HTTP hatası, model/OCR yokluğu ve bütçe dolumu için kontrollü sonuç; sınırlamayı kullanıcı görür |
| K02-T11 | A28 | Yeni alan/profil/oturumda eski izin, tablo ve alan bağlamı sızmaz; K01 ile birlikte kapatılabilir |
| K02-T12 | A30 | Architect yüklü aralık dışındaki gerekli veriyi desteklenen kaynaktan çeker; kaynak erişilemezse nedeni dürüstçe gösterir |
| K02-T13 | A32/A33 | Analitik kartlarında yalnız sonuç tarihi değil yöntem/eşik/ceza/min segment ve sınırlama metinleri de denetlenir |
| K02-T14 | M13-T04/T07 | Aynı sayının yanlış dönem/kolon/varlıkta bulunması doğrulama sayılmaz; eski tablo eşleşmesi doğru sürüm/kaynakla sunulur |

**Diğer eşlemeler:** A09 → D01/D07/K01; A21 → D03/D04/D05/K01; A23 → D06. Önceden tam kabul edilmiş diğer vakalar ilgili kod değişikliğinden etkileniyorsa regresyonda korunur. Her eksik için yeni canlı çağrı gerekmez; ağ/LLM davranışı gerektirmeyen kontroller deterministik yapılır.

**Kapanış:** A01–A33 için mevcut test, yeni test ve kalan boşluğu gösteren matris günceldir. “Kısmi ama tamamlandı” yazılmaz; zorunlu boşluk kapatılır veya açık kapsam kararı olarak kalır.

## 12. K03 — Son sürüm provası ve teslim hazırlığı

- [ ] **K03-T01:** Normal analiz, çok turlu analiz, web ve OCR için ölçülecek süre/token/başarı ölçütlerini kararlaştır; uydurma SLA yazma.
- [ ] **K03-T02:** Son aday commit ve veri manifestini sabitle; ilgili offline testleri, gerekiyorsa paketlerin tam testlerini ve kurulum kontrollerini çalıştır.
- [ ] **K03-T03:** Canlı provada üç dengeli ilk tekrar yaklaşımını bütçeyle değerlendir; kritik/dalgalı vakaya hedefli ek tekrar yap. Başarısızlık ve timeout'ları sonuçtan çıkarma.
- [ ] **K03-T04:** Doğruluk kontrolü başarısını canlı başarı yüzdesiyle karıştırma. Tek temiz koşuyu bütün stokastik davranışın garantisi sayma.
- [ ] **K03-T05:** Demo bilgisayarında gerçek ekran düzeni, yükleme, eski cevap, export ve rol gösterimini kontrol et; M14-T11'i kanıtla kapat.
- [ ] **K03-T06:** Başka ekip üyesi yalnız belgelenmiş adımlarla kurulumu ve kabul akışını tekrarlasın; gizli yerel yol/terminal/env override bağımlılığı bulunmasın.
- [ ] **K03-T07:** Pasifleştirme, ek animasyon, yardımcı motor katkıları ve ek çıktı biçimleri için açık kararları sınıflandır; zorunlu işlerle karışmasın. Erteleme gerekçesi ve kabul etkisi yazılsın.
- [ ] **K03-T08:** Teslim commit/etiket/veri manifesti/test raporunu kaydet; gerekli ek teslim beklentilerini teyit et. Merge/push/branch temizliği ayrı kullanıcı/ekip kararını izlesin.

**Kabul:** son kodla gerekli senaryoları başka ekip üyesi tekrar çalıştırabiliyor; tüm kritik düzeltmeler kapalı, performans ölçütleri açık, kalan koşullu işler gerekçeli. 20 Eylül freeze kaydı ayrıca tamamlanır.

## 13. K04 — Durum ve kanıt kaydını düzelt

- [ ] **K04-T01:** Ana planda M04-T09 ve M13-T09'u ilgili yeni regresyonlar geçene kadar yeniden açık/kısmi göster; geçmişteki başarılı kanıtı silme.
- [ ] **K04-T02:** D01/D07 için M03/M11, D02 için M13, D04/D05 için M04/M16 kapanışlarını yeniden değerlendir. Milestone haritası ile alt görev durumları aynı anlamı taşısın.
- [ ] **K04-T03:** Her düzeltmeye ilgili R/D/M/A kimliklerini bağla. Aynı kabul senaryosu birden fazla görevi kapatıyorsa kanıtı tekrar üretmeden bağlantı ver.
- [ ] **K04-T04:** Değişen sözleşmeleri ADR/README/operasyon tarifinde güncelle; `PROJECT_MEMORY.md` karar ve ölçüm kaydını append-only tut.
- [ ] **K04-T05:** Bu dosyada ancak uygulama ve kabul kanıtı sonrası görev kutusunu işaretle. Yeni commit sonrası eski test raporunu güncel rapor gibi gösterme.

### Her paket için kapanış kaydı

| Alan | Kaydedilecek bilgi |
|---|---|
| Paket | Dxx/Kxx ve ilgili Rxx/Mxx/Axx |
| Değişiklik | Hangi davranış önce nasıldı, sonra nasıl oldu |
| Sürüm | Kod commitleri, model/ayarlar, veri manifesti |
| Doğrulama | Komut/vaka, beklenen ve gözlenen sonuç, hata/tekrar sayısı |
| Artefakt | Test raporu, tablo/çıktı, gerekiyorsa ekran görüntüsü ve URL/zaman |
| Etki | Mevcut davranışın korunması, kalan sınırlama, geri alma yaklaşımı |
| Karar | Tamamlandı / kısmi / açık karar; sorumlu ve gözden geçiren |

## 14. Son kapanış koşulu

D01–D07 ve zorunlu K01/K02 kabulü tamamlanmadan bu incelemenin açıkları kapandı denmez. K03 teslim provası ve K04 durum eşlemesi tamamlanmadan tüm milestone'lar bitmiş sayılmaz. Bu belgeyi yazmak uygulama veya testlerin tamamlandığı anlamına gelmez.

### İlerleme kaydı

- **2026-09-14:** Kullanıcı isteğiyle bağımsız kontrolün yedi bulgusu, düzeltme görevleri ve demo kapanış kapsamına dönüştürüldü. Bu tur uygulama kodu ve veri değiştirilmedi.
- **2026-09-14 (uygulama):** D01, D07 ve D02 uygulandı ve testlendi (ADR-0065, ADR-0066); ajan testleri 432 geçti.
- **2026-09-14 (uygulama):** D03 uygulandı ve testlendi (ADR-0068); ajan testleri 440 geçti.
- **2026-09-14 (uygulama):** D04 (lakehouse kip + sıfırlama bağlantısı), D05 ve D06 uygulandı ve testlendi (ADR-0069, ADR-0070); ajan 448, lakehouse tam suite 1.111 geçti. D04-T05…T07 gerçek CLI akışı K01'de.
- **2026-09-14 (K01):** `scripts/k01_kabul.py` gerçek bileşenlerle 22/22; bulgu: bootstrap sonrası Silver ilişkisi yoktu → düzeltildi (ADR-0069 eki). K01-T07 arayüz provası ayrı.
