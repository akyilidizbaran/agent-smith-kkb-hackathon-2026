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
| [0015](0015-embedding-reranker-erteleme.md) | Embedding/reranker yatırımının ertelenmesi | Ertelendi |
| [0016](0016-add-column-yapisal-parametreler.md) | workspace_add_column serbest SQL almaz | Kabul edildi |
| [0017](0017-donem-filtresi-zorunlulugu.md) | Soruda geçen dönem sorguda yoksa ret | Kabul edildi |
| [0018](0018-donem-anahtari-uyumu.md) | Dönem anahtarı dönem sonu; kolon adı korundu | Kabul edildi |
| [0019](0019-arac-ciktisi-boyut-siniri.md) | Araç çıktısı modelin taşıyabileceği boyutta | Kabul edildi |
| [0020](0020-adaptor-sertlestirme-ve-tls.md) | Adaptörde savunma derinliği; TLS doğrulaması kapatılmaz | Kabul edildi |
