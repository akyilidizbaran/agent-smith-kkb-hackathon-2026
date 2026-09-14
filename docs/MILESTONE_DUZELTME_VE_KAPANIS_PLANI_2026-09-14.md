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
- [x] **K01-T07:** UI üzerinden her iki akışı göster; otomatik Playwright adımları model sonucu yanında dosya, tablo ve durum değişimini de kontrol etsin. — **14 Eyl:** `scripts/k01_ui_kabul.py` 15/15, commit 9eaf60e (`docs/experiments/k01_ui_kabul_2026-09-14_1319/rapor.json` + ekran görüntüleri): gerçek tarayıcı (Chromium) ve süreç içi HTTP sunucusu, model betikli; iki dosya arayüzden yüklendi, kural sorusu ekranda, birleşim ve hesap tablosu ekranda 4 satır, arayüzden indirilen CSV/XLSX beklenen değerlerle aynı, ortak katalog parmak izi aynı; profil penceresinden Architect, taslak, iki geçersiz onay reddi (DB özeti aynı), geçerli yayın (Silver 12), sıfırlama penceresinde onay kodu → 'tamamlandı', DB'de seri 0 ve kip none, kök dışı dosya ve demo DB aynı, yeni alan yalnız adhoc:web_ziyaret ve durum sayaçları 1, sayfa yenilemede cevaplar geri geldi. Bulunan ve düzeltilen: onaylanan adhoc seri katalog sayacında görünmüyordu (ADR-0076).

**Kabul:** gerçek CLI ve son uygulama sürümüyle A09/A21a–c sonuçları tam; test dışı dosyalar korunmuş; raporda model/commit/veri manifesti ve tekrar bilgileri mevcut. Kaydedilmiş sonucu canlı çıktı gibi sunma.

## 11. K02 — Kısmi kabul senaryolarındaki eksikleri tamamla

Dayanak: [M16 kabul raporu](M16_KABUL_RAPORU.md). Aşağıdakiler her biri yeni özellik yazılması gereken işler değildir; bazıları mevcut davranışa eksik kabul kanıtı ekler. Uygulama bozuk çıkarsa ilgili milestone yeniden açılır.

| Görev | Vaka/kapsam | Yapılacak doğrulama ve kapanış |
|---|---|---|
| K02-T01 | A01 / M16-T02 | **Kapandı 14 Eyl (ADR-0076):** commit 9eaf60e, `docs/experiments/k02_t01_kurulum_2026-09-14_1321/`: yerel depodan temiz klon → `make setup` → belgelenen `.env` → verisiz ön kontrol HAZIR DEĞİL (veri kökü, DB, izinli kök) → `build_demo_data.py --only` ile geçici kökte canlı BDDK+EVDS (11 s, 2 seri, Silver 675, Gold 2) → model anahtarı boşken ön kontrol model ✗ → `.env` ile hazır → `make serve` durum 200, sayfa 200 → canlı soru 7,7 s, 12 satır, kanıt 13/13 ve üç rozet yeşil, ekran görüntüsü. Bulunan ve düzeltilen: anahtar boşken ön kontrol 'hazır' deyip sunucu çöküyordu. Sınır: aynı makinede uv önbelleğiyle (kurulum 1 s); başka ekip üyesi provası K03-T06 |
| K02-T02 | A02/A03 | **Kapandı 14 Eyl (ADR-0075):** `scripts/k02_finans_kabul.py` tek oturumda, commit 15f8593, 22/22 (`docs/experiments/k02_finans_kabul_2026-09-14_1310.json`): 60 satır 2021-01-31 → 2025-12-31 ardışık ve Silver'la birebir, cevaptaki bakiyeler eşleşir; faiz eklenince 60 satır ve önceki kolonlar birebir, her ay değeri haftalık Silver gözlemlerinin takvim ayı ortalamasıyla aynı (60/60), kart dönem eşleşmesini yazar, kanıt kolonu hizalı Gold tablosuna (weekly → monthly, avg) bağlı. Bulunan ve düzeltilen: üç ondalıklı Gold faizi grounding'de binlik okunuyordu |
| K02-T03 | A05 | **Kapandı 14 Eyl (ADR-0075):** KFE (`semantic_confidence=derived`) reel dönüşümde rızasız `UNVERIFIED_SEMANTICS`, aday doğrulanmış TÜFE; rızayla bile kapsam dışı baz 2015-06 `OUT_OF_COVERAGE` (kapsam 2016-01 → 2026-06); sütun eklemede önceki dört kolon birebir, KFE 60/60 Silver'la aynı, kart birim/ölçüm tipi/frekans/dönem eşleşmesi ve 'baz yılı DOĞRULANMAMIŞ' yazar, uyarı kanıt kolonu, XLSX ve raporda; `tests/test_k02_kfe_denetimi.py`, `docs/experiments/k02_finans_kabul_2026-09-14_1310.json` |
| K02-T04 | A06 | **Kapandı 14 Eyl (ADR-0075):** dönemler `workspace_query` bakış moduyla hesaplandı (tablo değişmedi), bağımsız pandas hesabıyla aynı 4 ay: 2021-02, 2021-05, 2023-12, 2024-01; 'neden oldu' cümlesi geri gönderildi, giden cevap eşzamanlılık der; web araması sonucu kanıtta ve raporda `context_sources` 'bağlam, veri değil' olarak veri kaynaklarından ayrı (sahte arama oturumu, ağ yok); `tests/test_k02_baglam_kaynagi.py`, `docs/experiments/k02_finans_kabul_2026-09-14_1310.json` |
| K02-T05 | A07/A26 | **Kapandı 14 Eyl (ADR-0075):** grafik PNG indirilir; arayüz/rapor başlığı PNG ile aynı (konu · endeks, ilk dönem = 100 · 2021-01-31 → 2025-12-31), denetçi geçti, farklı birim notu kartta; sonraki sekiz cevaptan sonra 1. cevabın raporu ve CSV'si hâlâ 60 satır 2 kolon, sürüm commit'i ve kaynak yazılı; KFE ve grafik cevaplarının raporları kendi tablosu, uyarısı ve grafiğiyle; `docs/experiments/k02_finans_kabul_2026-09-14_1310.json`. Bulunan ve düzeltilen: arayüz ve rapor grafik başlığında birim ve dönem yoktu |
| K02-T06 | A12 | **Kapandı 14 Eyl (ADR-0072):** düşük/belirsiz kaliteli OCR tablosu `LOW_QUALITY_SOURCE` ile yüklenmez, açık kabulle bütün DİKKAT notlarıyla yüklenir; OCR kaynaklı sayılar panelde doğrulanmış sayılmaz; `tests/test_k02_ocr.py` |
| K02-T07 | A18 | **Kapandı 14 Eyl (ADR-0074):** serbest kaynakta erişim hatası turu bitirmez (`ToolError.terminal=False`), başka kaynaktan veri kullanılır ve cevap kaynağı anmıyorsa deterministik 'Kaynak notu' eklenir; sabit kaynakta tur biter ve sorulur; `tests/test_agent_loop.py`, `tests/test_access_policy.py` |
| K02-T08 | A22 | **Kapandı 14 Eyl:** `lakehouse-core/tests/scripts/test_run_catalog_ingestion.py::test_a22_warned_artifact_ingested_twice_is_idempotent_and_keeps_each_runs_warning` — tek artifact, iki koşu bağı, koşu başına uyarı satırı, Bronze dosyası ve özeti değişmez |
| K02-T09 | A24 | **Kapandı 14 Eyl (ADR-0071):** bayat gold.* tablosuna sorgu `GOLD_STALE` ile reddedilir, eski değer dönmez; canlı Silver'dan gold_align/gold_join ile yeniden hesap; `tests/test_k02_bayat_gold.py` |
| K02-T10 | A27 | **Kapandı 14 Eyl:** Tavily 503/429/bağlantı kopması `ACCESS_BLOCKED` ve sebep (`tests/test_web.py`); süre bütçesi dolunca deterministik sınır notu (`tests/test_agent_loop.py`); model kesintisi ve OCR yokluğu önceki testlerde |
| K02-T11 | A28 | **Kapandı 14 Eyl (K01):** sıfırlama ve yeni alan sonrası yeniden başlatmada alan profili yalnız yeni katalogdan, arama eski finans serisi döndürmedi, önbellek yok, oturum/cevap/tablo temiz; profil geçişi oturumu temizler (`scripts/k01_kabul.py` T05/T06, `docs/experiments/k01_kabul_2026-09-14_1227.json`) |
| K02-T12 | A30 | **Kapandı 14 Eyl (ADR-0073):** Architect `ingest_source` (run kayıtlı toplu betik + Silver), erişilemezse sebep ve Silver yenilenmez (`tests/test_k02_kaynaktan_cek.py`); canlı prova `scripts/k02_a30_canli.py` 5/5: geçici kökte 2015-12 konut kredisi gerçek BDDK'dan çekildi (143.248, run kayıtlı), demo DB değişmedi (`docs/experiments/k02_a30_canli_2026-09-14_1237.json`) |
| K02-T13 | A32/A33 | **Kapandı 14 Eyl:** anomali kartı yöntem ve eşiği (Tukey k=1.5 / \|z\|>3), taban ve SINIRLAMA; kırılma kartı ceza formülü ve sayısal değeri, min segment, en çok kırılma ve SINIRLAMA; `tests/test_analytics_tools.py` metin denetimleri |
| K02-T14 | M13-T04/T07 | **Kapandı 14 Eyl (ADR-0074):** sayı cevabın yanında yazdığı dönemde değilse `period_warning`, 'sayılar' rozeti yeşil olmaz; önceki tablo eşleşmesi kaynak kimliği, kaynak ve SQL ile; `tests/test_k02_donem_bagi.py` |

**Diğer eşlemeler:** A09 → D01/D07/K01; A21 → D03/D04/D05/K01; A23 → D06. Önceden tam kabul edilmiş diğer vakalar ilgili kod değişikliğinden etkileniyorsa regresyonda korunur. Her eksik için yeni canlı çağrı gerekmez; ağ/LLM davranışı gerektirmeyen kontroller deterministik yapılır.

**Kapanış:** A01–A33 için mevcut test, yeni test ve kalan boşluğu gösteren matris günceldir. “Kısmi ama tamamlandı” yazılmaz; zorunlu boşluk kapatılır veya açık kapsam kararı olarak kalır.

## 12. K03 — Son sürüm provası ve teslim hazırlığı

- [ ] **K03-T01:** Normal analiz, çok turlu analiz, web ve OCR için ölçülecek süre/token/başarı ölçütlerini kararlaştır; uydurma SLA yazma. — **14 Eyl:** ölçülen taban ve öneri aşağıda; eşik kararı kullanıcıda (K06), bu yüzden kutu işaretlenmedi.
- [x] **K03-T02:** Son aday commit ve veri manifestini sabitle; ilgili offline testleri, gerekiyorsa paketlerin tam testlerini ve kurulum kontrollerini çalıştır. — **14 Eyl:** aday kod commit'i 6f12bbe idi; canlı tekrar ve ekran provası bulguları kapatılınca aday e212e96 oldu (sonraki commit'ler yalnız belge/kanıt). Veri manifesti `docs/experiments/k03_veri_manifesti_2026-09-14_1327.json` (DB sha256 c2cf0aec…, 2.214 katalog / 681 yüklü seri, 43.830 gözlem, 2016-01-01 → 2026-07-03, 6 Gold tablo, 117 run, 3.468 artifact; DB'de `meta.lakehouse_setting` yok — D04 öncesi kuruldu, okuma varsayılan kip). Ajan testleri 477 geçti (6f12bbe) → 485 (e212e96). Lakehouse tam suite 1.112 geçti, 12 dk 15 s (9eaf60e'de; lakehouse-core o tarihten sonra değişmedi). Kurulum kontrolü K02-T01 temiz klon provası (9eaf60e; sonraki ajan değişiklikleri kanıt paneli, birleştirme kapısı, web kartı biçimi ve lakehouse_query bakış kaydı — kurulum yolunu değiştirmez).
- [x] **K03-T03:** Canlı provada üç dengeli ilk tekrar yaklaşımını bütçeyle değerlendir; kritik/dalgalı vakaya hedefli ek tekrar yap. Başarısızlık ve timeout'ları sonuçtan çıkarma. — **14 Eyl:** 51c066d'de üç tam tekrar (14/14, 13/14, 12/14); dalgalı turlarda hedefli ek tekrar: 6f12bbe finans ×3 (6/6, 5/6, 6/6) ve dosya ×2 (3/4, 4/4), 04655c7 dosya ×3 (4/4, 3/4, 4/4). Timeout yok; düşen turlar kayıtta. Tekrarların bulduğu ürün kusurları kapatıldı: işaretsiz büyüklük ve yön sözcüğü (ADR-0077), tabloyla tutarlı kalan satır sayısı, birleştirmede araçsız eşleşme iddiası (ADR-0077 eki). Kalan dalgalanma: dosya senaryosunun birleştirme turu 3 koşuda betik koşulunu karşılamadı; ikisinde davranış doğruydu (araç reddi, doğru açıklama, onay isteği) ama cevapta '?' yoktu; betik koşulu sonuç lehine değiştirilmedi. Raporlar `docs/experiments/acceptance_m16_2026-09-14_k03_*.json`, M16 raporu §2a.
- [x] **K03-T04:** Doğruluk kontrolü başarısını canlı başarı yüzdesiyle karıştırma. Tek temiz koşuyu bütün stokastik davranışın garantisi sayma. — **14 Eyl:** M16 raporunda iki ayrı katman: doğruluk kanıtı (§3a matris, betikli K01/K01-T07/K02, ajan testleri 484) ve canlı tur başarısı (§2a: tur bazında oranlar, ör. A06 turu düzeltme öncesi 1/3, sonrası 3/3; birleştirme turu 7 koşuda 4). Yüzdeler birbirine eklenmedi; 14/14 koşusu garanti diye yazılmadı.
- [x] **K03-T05:** Demo bilgisayarında gerçek ekran düzeni, yükleme, eski cevap, export ve rol gösterimini kontrol et; M14-T11'i kanıtla kapat. — **14 Eyl:** bu Mac (2560×1664 Retina) üzerinde gerçek sunucu ve canlı modelle `scripts/k03_ekran_kontrol.py` 6/6 (`docs/experiments/k03_ekran_2026-09-14_1350/`): 1512×982 ve 1280×800 görünüm alanında yatay kaydırma yok, soru kutusu/gönder/kanıt paneli/oturum listesi ekranda, iki canlı cevap, sol listeden eski cevap açılınca odak ve CSV/XLSX/HTML bağlantıları, rol rozeti 'Analyst'. Ayrıca `ui_e2e_m16.py` canlı 7/7 (`ui_e2e_m16_2026-09-14_1346`): yükleme, dışa aktarım, anahtarsız Architect 403, sıfırlama. Provanın bulduğu üç kusur kapatıldı: web kartında metin dolgusu modelin yanlış 'baştaki boşluk' iddiasına yol açtı; '2026-06' yıl-ay yazımı sayı sanıldı; lakehouse_query bakış sonucu kanıt havuzuna girmiyordu (ADR-0077 eki).
- [ ] **K03-T06:** Başka ekip üyesi yalnız belgelenmiş adımlarla kurulumu ve kabul akışını tekrarlasın; gizli yerel yol/terminal/env override bağımlılığı bulunmasın.
- [x] **K03-T07:** Pasifleştirme, ek animasyon, yardımcı motor katkıları ve ek çıktı biçimleri için açık kararları sınıflandır; zorunlu işlerle karışmasın. Erteleme gerekçesi ve kabul etkisi yazılsın. — **14 Eyl:** aşağıdaki sınıflandırma tablosu.
- [x] **K03-T08:** Teslim commit/etiket/veri manifesti/test raporunu kaydet; gerekli ek teslim beklentilerini teyit et. Merge/push/branch temizliği ayrı kullanıcı/ekip kararını izlesin. — **14 Eyl teslim adayı kaydı:** dal `feature/agent-engine`, aday kod commit'i e212e96 (origin'e itildi; main'e birleştirilmedi, etiket konmadı). Veri: `k03_veri_manifesti_2026-09-14_1327.json`. Testler: ajan 485 (e212e96), lakehouse 1.112 (lakehouse-core değişmedi). Kabul raporları: K01 CLI 22/22, K01-T07 arayüz 15/15, K02 finans 22/22, A30 canlı 5/5, temiz kurulum provası, canlı M16 tekrarları ve hedefli tekrarlar (M16 raporu §2a), ekran kontrolü 6/6, canlı arayüz 7/7. Teslim kuralları denetimi (izlenen dosyalar): `.env` izlenmiyor ve gitignore'da, izlenen dosyada `.env` anahtar değeri 0, token kalıbı 0; kodda OpenAI/Anthropic/OpenRouter adresi 0, bulut lakehouse istemcisi 0; model uç noktası Kloudeks (ön kontrol). **Kullanıcı/ekip kararı bekleyenler:** main'e birleştirme ve itme, freeze etiketi (geliştirme bitişi 20 Eylül), reponun private kalması ve KKB kullanıcılarının collaborator eklenmesi, başka ekip üyesi provası (K03-T06), eşikler (K03-T01).

### Ölçülen taban (K03-T01; SLA değil)

| Ölçüt | Ölçülen | Kaynak | Sınır |
|---|---|---|---|
| Canlı çok turlu kabulde tur süresi | medyan 13,9 s · p90 58,4 s · en çok 200,9 s (84 tur, 6 koşu) | `docs/experiments/acceptance_m16_2026-09-14_0118…0219.json` | aynı model ve ayar; koşular arasında kod değişti |
| Son iki gece koşusunun toplamı | 123 s ve 127 s (14 tur) | `…_0214.json`, `…_0219.json` | tek koşu garanti değil |
| K03 canlı tekrarlarında tur süresi | medyan 7,5 s · p90 13,0 s · en çok 20,5 s (42 tur, 3 koşu, 51c066d); koşu toplamı 111–122 s | `acceptance_m16_2026-09-14_k03_tekrar1…3.json` | aynı commit; tur başarısı 14, 13, 12 / 14 |
| Canlı tur başarısı | 10 → 11 → 11 → 12 → 12 → 14 / 14 | aynı dosyalar | her koşu yeni commit'te |
| Temiz kurulumdan ilk canlı cevap | `make setup` 1 s (uv önbelleğiyle), iki seri canlı veri 11 s, ön kontrol 1 s, ilk canlı soru 7,7 s | `k02_t01_kurulum_2026-09-14_1321/kurulum.log` | aynı makine; önbelleksiz kurulum ölçülmedi |
| Tam zorunlu veri kurulumu | ~30 dk (681 seri, FinTürk 3.402 istek ~26 dk) | `M08_KAPSAM_RAPORU.md`, `OPERASYON_TARIFI.md` | ağ hızına bağlı |
| Web araması ve OCR süresi | ayrı ölçüm yok | — | canlı kabul senaryoları OCR turu içermiyor |
| Token | koşu raporları token saymıyor | — | ölçmek için kabul betiğine kullanım alanı eklenmesi gerekir |

**Öneri (kullanıcı onayı bekler):** canlı kabuldeki kritik vakalar (A13 yanlış öncül, A20 dosya içeriği yetki vermez) canlı
tekrarların hepsinde geçmeli; A21 (yetkisiz yazma, onay) canlı senaryoda yok, her aday commit'te betikli K01 ve K01-T07 ile tam geçmeli; diğer turlar için başarı oranı ve p90 süre raporlanır, eşik ayrıca yazılır. Betikli kabul
(K01/K02) doğruluk kanıtıdır ve canlı başarı yüzdesiyle toplanmaz (K03-T04).

### Açık kararların sınıflandırması (K03-T07)

Bu işler zorunlu düzeltmelerden ayrıdır; hiçbiri A01–A33 kabul matrisinde (M16 raporu §3a) bir vakanın tam sayılmasını engellemez.

| Konu | Tür | Bugünkü durum | Erteleme gerekçesi | Kabul etkisi | Karar sahibi |
|---|---|---|---|---|---|
| Seri/kaynak pasifleştirme (M04) | koşula bağlı özellik | uygulanmadı; taslak → onay → aktif ve doğrulanan tam sıfırlama var | A21 ve demo akışı mevcut yayın/sıfırlama ile kapanıyor; pasifleştirme ek yönetim işlemi | yok | ekip |
| Kanıt yolculuğu 2,5B/3B görünümü (K10, M14-T12) | görünüm | iki deneme duruyor, seçim yapılmadı | kanıt düzeltmeleri önceydi; kanıt paneli metin ve üç rozetle tam | yok | kullanıcı |
| Yardımcı motor katkıları (EK-08: Büşra'nın ilgi kapısı, çapraz kontrol, birim tahmini; G12a–d) | katkı aktarımı | bu dala alınmadı. 14 Eyl birleştirme denemesinde metin çatışması yok; birleşik ağaçta 8 test düştü: 6'sı yeni testlerin sahte okuyucusu bizim `read_table_for_profiling(sheet=…)` imzasını tanımıyor, 2'si (`test_vision`, v3 doğrulayıcı) ayrıca düştü, nedeni incelenmedi | yanlış/alakasız dosya ve birimsiz ekleme riskini azaltır; ama bizim ingest imzasına uyarlanması ve golden vakaların yeniden koşulması ayrı iş | zorunlu vaka yok; A10/A11 davranışını güçlendirir | ekip (Büşra + Baran) |
| Ek çıktı biçimleri (K05 dışı: PDF rapor, PPTX) | kapsam dışı | K05 kararı CSV, XLSX, PNG, HTML; hepsi kabulde | karar verilmiş | yok | kullanıcı |
| Performans ve başarı eşikleri (K06, M16-T10) | ölçüm kararı | K03-T01'de ölçülen taban öneri olarak yazıldı, SLA değil | eşiği kullanıcı belirleyecek | M16-T10 açık | kullanıcı |
| Canlı ağ/MIA kesintisi provası (M16-T07) | prova | birim testleri var (Tavily 503/429/kopma, model kesintisi, süre bütçesi) | demo makinesinde ağ kesmek riskli; test düzeyi kanıt var | A27 test düzeyinde tam | ekip |
| Başka ekip üyesinin kurulum provası (M16-T11, K03-T06) | prova | aynı makinede temiz klon provası yapıldı (K02-T01) | başka kişi ve başka makine gerekir | teslim kabulü | kullanıcı/ekip |
| Nihai merge, main'e push, freeze etiketi (K12, M17) | teslim | yapılmadı; çalışma yalnız `feature/agent-engine` | kullanıcı talimatı: main'e push yok | freeze kaydı | kullanıcı |

**Kabul:** son kodla gerekli senaryoları başka ekip üyesi tekrar çalıştırabiliyor; tüm kritik düzeltmeler kapalı, performans ölçütleri açık, kalan koşullu işler gerekçeli. 20 Eylül freeze kaydı ayrıca tamamlanır.

## 13. K04 — Durum ve kanıt kaydını düzelt

- [x] **K04-T01:** Ana planda M04-T09 ve M13-T09'u ilgili yeni regresyonlar geçene kadar yeniden açık/kısmi göster; geçmişteki başarılı kanıtı silme. — **14 Eyl:** ana planda iki görev 'yeniden açıldı → D03/K01/K01-T07 ve D06 ile kapandı' notuyla, eski kanıt korunarak güncellendi.
- [x] **K04-T02:** D01/D07 için M03/M11, D02 için M13, D04/D05 için M04/M16 kapanışlarını yeniden değerlendir. Milestone haritası ile alt görev durumları aynı anlamı taşısın. — **14 Eyl:** ana plan haritasında M03, M04, M11, M13, M16 satırlarına yeniden değerlendirme notu; M13-T04/T07 ve M16-T02/T04 kanıtla kapandı, M13-T11/T12, M16-T07/T10/T11 açık kaldı.
- [x] **K04-T03:** Her düzeltmeye ilgili R/D/M/A kimliklerini bağla. Aynı kabul senaryosu birden fazla görevi kapatıyorsa kanıtı tekrar üretmeden bağlantı ver. — **14 Eyl:** aşağıdaki eşleme tablosu.
- [x] **K04-T04:** Değişen sözleşmeleri ADR/README/operasyon tarifinde güncelle; `PROJECT_MEMORY.md` karar ve ölçüm kaydını append-only tut. — **14 Eyl:** ADR-0065…0076 ve dizin; `OPERASYON_TARIFI.md` (`.env` okuma, Architect kaynaktan çekme, sıfırlamada katalog seçimi, §6 kabul betikleri, sorun giderme); README bağlantısı; PROJECT_MEMORY §14 ekleri; M16 raporu §3a.
- [x] **K04-T05:** Bu dosyada ancak uygulama ve kabul kanıtı sonrası görev kutusunu işaretle. Yeni commit sonrası eski test raporunu güncel rapor gibi gösterme. — **14 Eyl:** kutular yalnız commit'li kanıt dosyasıyla işaretlendi; kirli ağaçta alınan ara koşu raporları silindi, kanıt koşuları temiz commit'te tekrarlandı (15f8593, 9eaf60e); M16 gece matrisi değiştirilmedi, güncel durum §3a'da.

### Eşleme (K04-T03)

| Bulgu | Düzeltme | Ana plan | Kabul vakası | ADR | Kanıt |
|---|---|---|---|---|---|
| R01 | D01 | M03, M11 | A09 | 0065 | `tests/test_d01_d07_join.py`, K01 T02/T03, K01-T07 |
| R02 | D02 | M13-T12 | A13 | 0066 | `tests/test_agent_loop.py` (999 diyen model) |
| R03 | D03 | M04-T09 | A21 | 0068 | `tests/test_d03_onay.py`, K01 T04, K01-T07 |
| R04 | D04 | M04, M16-T04 | A21, A28 | 0069 | `tests/catalog/test_catalog_mode.py`, K01 T05/T06, K01-T07 |
| R05 | D05 | M04 | A21 | 0069 | `tests/test_d05_sifirlama.py`, K01 T05, K01-T07 |
| R06 | D06 | M13-T09 | A23 | 0070 | `tests/test_d06_zincir.py` |
| R07 | D07 | M03, M11 | A09 | 0065 | `tests/test_d01_d07_join.py` |
| — | K02-T01 | M01, M16-T02 | A01 | 0076 | `k02_t01_kurulum_2026-09-14_1321/` |
| — | K02-T02…T05 | M09, M11, M13, M14 | A02–A07, A26 | 0075 | `k02_finans_kabul_2026-09-14_1310.json` |
| — | K02-T06 | M10 | A12 | 0072 | `tests/test_k02_ocr.py` |
| — | K02-T07, K02-T14 | M06, M13-T04/T07 | A18 | 0074 | `tests/test_agent_loop.py`, `tests/test_k02_donem_bagi.py` |
| — | K02-T08 | M07 | A22 | — | lakehouse `test_run_catalog_ingestion.py` |
| — | K02-T09 | M09 | A24 | 0071 | `tests/test_k02_bayat_gold.py` |
| — | K02-T10 | M06, M15 | A27 | — | `tests/test_web.py`, `tests/test_agent_loop.py` |
| — | K02-T11 | M04, M16 | A28 | — | K01 T05/T06 |
| — | K02-T12 | M07, M08 | A30 | 0073 | `tests/test_k02_kaynaktan_cek.py`, `k02_a30_canli_2026-09-14_1237.json` |
| — | K02-T13 | M12 | A32, A33 | — | `tests/test_analytics_tools.py` |

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
- **2026-09-14 (K02):** T06–T14 testlerle ve A30 canlı provasıyla kapandı (ADR-0071…0074). T02–T05 `scripts/k02_finans_kabul.py` 22/22, commit 15f8593; dört ürün kusuru bulunup kapatıldı (ADR-0075).
- **2026-09-14 (K03):** manifest, tam testler, üç canlı tekrar ve hedefli tekrarlar, ekran kontrolü; tekrarlar ve prova altı ürün kusuru daha buldu, hepsi kapatıldı (ADR-0077 ve eki); teslim adayı e212e96. K03-T01 eşik kararı ve K03-T06 başka üye provası kullanıcıda.
- **2026-09-14 (K01-T07):** `scripts/k01_ui_kabul.py` arayüzden 15/15, commit 9eaf60e; onaylanan adhoc seri sayaç bulgusu kapatıldı. K02-T01 kurulum provasında ön kontrol boş model anahtarında 'hazır' dedi → düzeltildi (ADR-0076).
