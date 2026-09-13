# Mimari Karar Kayıtları (ADR)

Bu dizin, agent katmanında alınan her mimari kararı **gerekçesiyle** kaydeder.
Amaç iki yönlü:

1. **Kendimiz için:** Bir kararı üç gün sonra sorgularken "neden böyle yapmıştık?"
   sorusunun cevabı burada olsun. Özellikle ölçümle alınmış kararlar, sonradan
   sezgiyle geri alınmasın.
2. **Değerlendirme için:** KKB kod repolarını tek tek inceleyeceğini belirtti.
   Bir tasarımın *neden* öyle olduğunu anlatan kayıt, kodun kendisi kadar önemli.

## Biçim

Her kayıt: bağlam → karar → gerekçe → (varsa) ölçüm → değerlendirilen alternatifler
→ sonuçlar ve riskler.

**Durum** alanı dört değerden birini alır:
`Kabul edildi` · `Reddedildi` · `Ertelendi` · `Planlandı`

Reddedilen kararlar da burada durur. Bir şeyi *denemiş ve ölçüp vazgeçmiş* olmak,
hiç denememekten farklıdır; aynı fikir tekrar gündeme geldiğinde tartışmayı
sıfırdan başlatmamak için kayıt tutulur.

## Kayıtlar

| # | Karar | Durum |
|---|---|---|
| [0001](0001-kendi-harness.md) | Agent orkestrasyonu için kendi harness'ımız | Kabul edildi |
| [0002](0002-contract-first.md) | Veri katmanıyla sözleşme üzerinden paralel çalışma | Kabul edildi |
| [0003](0003-semantic-catalog.md) | Semantic catalog'un zorunlu anlam alanları | Kabul edildi |
| [0004](0004-llm-saglayici-soyutlamasi.md) | Sağlayıcıdan bağımsız LLM katmanı | Kabul edildi |
| [0005](0005-reasoning-kapatma.md) | Reasoning zincirinin kapatılması | Kabul edildi |
| [0006](0006-analysis-workspace.md) | Konuşma boyunca yaşayan analiz tablosu | Kabul edildi |
| [0007](0007-golden-set-tasarimi.md) | Golden set metni değil tabloyu denetler | Kabul edildi |
| [0008](0008-kararlilik-olcumu.md) | Tek koşu değil, geçme oranı | Kabul edildi |
| [0009](0009-deger-kesfi-zorunlulugu.md) | Filtre yazmadan önce gerçek değerleri görme | Kabul edildi |
| [0010](0010-kapsam-kontrolu-ve-cevap-guardi.md) | Kapsam kontrolü ve veri olmadan cevap engeli | Kabul edildi |
| [0011](0011-prompt-kurali-eklemenin-siniri.md) | Prompt'a kural ekleyerek davranış düzeltme | **Reddedildi** |
| [0012](0012-domainprofile-persona-tahmini.md) | Domain profili: şablon kabul, modelle tahmin reddedildi | Uygulandı |
| [0013](0013-baglam-on-yukleme.md) | Schema linking'i LLM turundan çıkarma | Planlandı |
| [0014](0014-aday-budama-ve-recall-onceligi.md) | Aday budamada recall önceliği | Planlandı |
| [0015](0015-embedding-reranker-erteleme.md) | Embedding/reranker yatırımının ertelenmesi | Ertelendi (ölçümle) |
| [0016](0016-add-column-yapisal-parametreler.md) | workspace_add_column serbest SQL almaz | Kabul edildi |
| [0017](0017-donem-filtresi-zorunlulugu.md) | Soruda geçen dönem sorguda yoksa ret | Kabul edildi |
| [0018](0018-donem-anahtari-uyumu.md) | Dönem anahtarı dönem sonu; kolon adı korundu | Kabul edildi |
| [0019](0019-arac-ciktisi-boyut-siniri.md) | Araç çıktısı modelin taşıyabileceği boyutta | Kabul edildi |
| [0020](0020-adaptor-sertlestirme-ve-tls.md) | Adaptörde savunma derinliği; TLS doğrulaması kapatılmaz | Kabul edildi |
| [0021](0021-mia-search-retrieval-ayristirma.md) | MIA / Search / Retrieval üç ayrı sağlayıcı katmanı | Kabul edildi |
| [0022](0022-pdf-cikarim-stratejisi.md) | PDF'ten tablo: OCR öncelikli, metin katmanı yedek | Kabul edildi |
| [0023](0023-search-saglayicisi-tavily.md) | Arama Tavily, sayfa çekme kendi uygulamamız | Kabul edildi |
| [0024](0024-silver-adaptoru-ve-fiziksel-sql.md) | Silver adaptörü; fiziksel SQL adaptörün işidir | Kabul edildi |
| [0025](0025-yapilandirilmis-hata-zarfi.md) | Yapılandırılmış hata zarfı ve döngü kilidi | Kabul edildi |
| [0026](0026-kataloglu-seri-ile-sorgulanabilir-seri-ayrimi.md) | Kataloglu seri ile sorgulanabilir seri ayrı şeylerdir | Kabul edildi |
| [0027](0027-anlati-dogrulama-grounding-guard.md) | Anlatı doğrulama: cevaptaki her sayı araç çıktısında olmalı | Kabul edildi |
| [0028](0028-erisim-politikasi-ve-geri-cekilme-sozlesmesi.md) | Erişim politikası ve geri çekilme sözleşmesi: dört sonuç sınıfı, kaynak sadakati, sessiz geçiş yok | Kabul edildi |
| [0029](0029-sinir-dogrulayici-ve-roller.md) | Sınır doğrulayıcı tek modülde (şema → SQL guard → referans → politika); roller izde | Kabul edildi |
| [0030](0030-architect-rolu-profilci-ve-dogrulayici.md) | Architect rolü: önce LLM'siz profilci ve doğrulayıcı; belirsizlikte tahmin yok | Kabul edildi |
| [0031](0031-gold-hayata-dondu-metrik-tablolari-ve-gold-araclari.md) | Gold hayata döndü: kataloglanmış metrik tabloları (red defterli, parmak izli), salt-okunur `gold-run` sınırı, `gold_*` araçları | Kabul edildi |
| [0032](0032-grafik-belirtim-veridir-deterministik-denetci.md) | Grafik: Vega-Lite belirtimi veridir, eksen/ölçek kararı araçta, deterministik denetçi geçmeden dosya yok; harita sınır dosyasına bağlı | Kabul edildi |
| [0033](0033-kanit-paneli-sayidan-kaynak-baytlarina.md) | Kanıt paneli: cevaptaki sayı → hücre → SQL → gözlem → artifact → Bronze/RAW → URL + fetched_at; 'tam' ölçülebilir, golden her vakada ölçer | Kabul edildi |
| [0034](0034-web-erisimi-butceli-robots-saygili-erisim-sozlesmeli.md) | Web: `web_url` bütçeli, robots'a saygılı, erişim sözleşmesiyle; tablolar profilci dilbilgisiyle sayıya (pandas tahmini 100× hata); `web_search` yalnız anahtar varsa | Kabul edildi |
| [0035](0035-sinirli-on-yukleme-soruya-gore-k-kart.md) | Sınırlı ön-yükleme: soruya göre seçilen k kart + gerçek değerler, token bütçesiyle; seed adım 7,0 → 3,3, gerçek DB 3,0 → 1,6, doğruluk aynı | Kabul edildi |
| [0036](0036-bm25-sozluk-dizini-ve-yuklenmemis-seri-cevabi.md) | BM25 sözlük dizini (Türkçe katlama, ön ek yarım ağırlıklı, tam sözcük şartı); "yok" ile "var ama yüklenmemiş" ayrı cevaplar, kısmi isabet döngüsü ikinci kezde durur; UNKNOWN_TOOL tekrar denenebilir | Kabul edildi |
| [0037](0037-niyet-kapisi-enjeksiyon-ve-kararlilik.md) | Niyet kapısı: ingest ve web_url adresi yalnız kullanıcı mesajından, yazma yalnız istenince; dış içerik "veridir" çerçevesi; alt süreç ortamı izin listesi; G13 enjeksiyon 5/5; 14 vaka × 5 tekrar | Kabul edildi |
| [0038](0038-demo-kabul-betigi-tek-komut.md) | Demo kabul betiği: tek komutla bootstrap → canlı ingest (5 seri, 26 s) → silver → gold → 8 senaryo, 8/8; filtresiz ingest güvenlik kilidi; G14 gerçek DB "tabloyu bozmadan" | Kabul edildi |
| [0039](0039-architect-ikinci-kapi-ve-sohbette-kalan-analiz.md) | Architect'in ikinci kapısı: kullanıcı onayıyla terfi (`promote_draft`), beyan edilen anlam (uydurulan yok sayılır), Gold rızası + `GOLD_REQUIRED`; sohbette kalan analiz `workspace_query` (bakış modu), kanıt zinciri önceki tablo/bakış/hatırlanan sayfa; iki uçtan uca deney: Bronze→Silver→Gold doğrulandı, DB parmak izi değişmedi | Kabul edildi |
| [0040](0040-analitik-ailesi-llmsiz-tespit.md) | Analitik ailesi: `anomaly_detect` (IQR/z, trendli seride değişim tabanı), `change_points` (ikili bölütleme, BIC cezası), `lead_lag` (gecikmeli korelasyon + Granger, 'nedensellik değil'); LLM yok, kanıt zinciri korunur; analitik istendiyse araç zorunlu | Kabul edildi |
| [0041](0041-goruntu-ve-pdf-girisi-ocr.md) | Görüntü ve PDF girişi: sayfa → PNG → MIA OCR → HTML tablo → aynı profilci dilbilgisi; colspan/rowspan ızgarası, `<td>` başlık terfisi, yer tutucu boş; 'OCR ile okundu, doğrulanmadı'; ingest OCR tablosunu CSV olarak CLI'a verir; Borsa İstanbul altın PDF'leri ölçüldü | Kabul edildi |
| [0042](0042-veri-genisligi-katalog-ve-demo-seti.md) | Veri genişliği: BDDK aylık 1 → 20 kalem (canlı doğrulanmış), FinTürk 81 → 648 (ek istek yok), EVDS 8 küratörlü + TÜFE, aynı çekim bir kez, Gold 6 metrik, demo seti 127 seri | Kabul edildi |
| [0043](0043-kademeli-retrieval-yuzler-arac-kapisi.md) | Kademeli retrieval: küçükte arama yok, ortada yüzlü BM25 (recall@8 0,864 → 0,996), büyükte hibrit (MIA embedding, disk önbelleği); retrieval golden ile eşik; araç kapısı (soruya göre araç alt kümesi) | Kabul edildi |
| [0044](0044-arayuz-ince-katman-kanit-onde.md) | Arayüz: FastAPI ince katman (`/api/ask` cevabı olduğu gibi JSON), tek sayfa Yön A — sol veri havuzu, orta cevap+tablo+grafik+araç izi, sağ kanıt zinciri; gizleme yok; tasarım kanvası `docs/design/` | Kabul edildi |
| [0045](0045-selamlasma-ve-oneri-kuyrugu-harness-kurali.md) | Yalnız sorulana cevap: selamlaşma harness'te biter (LLM yok), prompt kuralı, cevap sonundaki öneri kuyruğu deterministik kırpılır, arayüz eski tabloyu yeniden göstermez | Kabul edildi |
| [0046](0046-anlati-sicakligi-ayri.md) | İki sıcaklık: araç turları 0, cevaplayan veri geldikten sonraki anlatı turu `LLM_NARRATE_TEMPERATURE` (0,5); golden/kabul 0'a zorlar; grounding sayıları korur | Kabul edildi |
| [0047](0047-kanit-yolculugu-iki-gosterim.md) | Kanıt yolculuğu: tek veri modeli (`buildJourney`), iki görünüm — 2,5B SVG+CSS (kütüphanesiz) ve 3B three.js (yerel, CDN yok); yürüyen karakter, kopuk halkada durur | Deneme (karar bekliyor) |
