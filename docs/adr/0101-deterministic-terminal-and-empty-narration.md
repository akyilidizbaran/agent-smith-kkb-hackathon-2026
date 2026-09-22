# ADR-0101 — Deterministik terminal kapanış ve boş anlatım koruması

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-20
- **İlgili çalışma:** V2 ilk 10 vaka ve kısmi MIA tanı koşusunda modelin boş final metni, terminal arama döngüsü ve uzun kurtarma çağrıları

## Bağlam

Sınırlı katalog orkestrasyonu ve kompakt recovery, büyük istem bağlamını ve bazı arama döngülerini azalttı. Ancak canlı koşuda bütçe/tekrar terminalinden farklı olarak on iki adıma kadar süren bir tur 284,5 saniye sonra boş metin ve sonuç tablosu olmadan tamamlandı. Ayrı bir denemede arama bütçesi veya yinelenen çağrı terminal olsa bile, araçsız son recovery çağrısı yeni kanıt üretmeden zaman aşımına uğrayabiliyordu. Boş metin başarı yanıtı gibi kullanıcıya aktarılmamalı; retrieval hatası veri yokluğu veya doğrulanmış sonuç gibi sunulmamalı.

## Karar

1. Geçerli final model yanıtı reasoning temizlendikten sonra boşsa harness ikinci bir anlatım çağrısı yapmaz. Aynı turda doğrulanmış aktif tablo varsa tabloyu ve indirmeleri korur, `NarrationFacts` veya deterministik tablo özetiyle anlatımın eksik kaldığını bildirir.
2. Boş yanıt ve doğrulanmış tablo yoksa `CONFIRMED_ABSENT`, `ACCESS_BLOCKED`, `RETRIEVAL_FAILED` durumları birbirinden ayrılır. `UNKNOWN` veya sırf başarılı metadata sorgusu bulunması, istenen sonucun bulunduğunu kanıtlamaz. Yanıtın boş olması da kaynağın boş olduğu iddiasına çevrilmez.
3. `DUPLICATE_CALL` veya `CATALOG_SEARCH_BUDGET` terminal olduğunda, bu turda üretilmiş doğrulanmış tablo yoksa son MIA recovery çağrısı atlanır. Harness kanıt durumunu kısa deterministik bir yanıtla kapatır ve katalog adaylarının araç adımlarında bulunduğunu ancak gerçekten katalog çıktısı varsa belirtir.
4. Doğrudan tablo teslimi, daha önce var olan kısa yolunu kullanmaya devam eder. Yeni durumlar prompta, benchmark vaka kimliğine, veri seti/seri adına veya tek bir kullanıcı isteğine bağlanmaz.

## Gerekçe ve sınırlar

- Araç ve yanıt metni boşken LLM'den yeniden anlatım istemek veri/kanıt eklemez; yalnızca sağlayıcı gecikmesi ve boş/uydurulmuş yanıt riskini büyütür.
- Beş katalog arama sınırı R04 benzeri çok varlıklı isteklerde semantik doğrulama aşamasına erişmeyi engelleyebilir. Sınırı körlemesine artırmak yerine sonraki çalışma, arama başına yeni ve ilgili aday verimini ölçen genel bir progress/yield bütçesi olmalıdır.
- Bu korumalar non-empty fakat yanlış anlatımı doğrulamaz; grounding ve artifact oracle testleri hâlâ gereklidir.

## Doğrulama

- Recovery/agent-loop hedefli testler: **73 geçti**; tam agent-core suite: **922 geçti**, bir mevcut Starlette/AnyIO deprecation uyarısı.
- Benchmark sözleşme validator'ı 120 vaka, 76 oracle ve 31 artefaktı geçti; değişen Python dosyaları Ruff `--select F` ve `git diff --check` temiz.
- İlk 10 vaka MIA A/B koşusunda toplam 795,26 → 640,53 sn ve prompt tokenı 384.662 → 245.440 ölçüldü; bu ölçüm boş-final koruması eklenmeden önceki sürümdür. Ayrı tanı koşusu P05'te 284,5 sn sonra boş metin verdi; R02 başında HTTPS/TLS handshake beklemesi nedeniyle durduruldu. Ham sonuçlar `docs/experiments/v2_mia_first10_recovery_arch_20260920_score.md` ve `docs/experiments/v2_mia_first10_terminal_recovery_20260920.jsonl` dosyalarındadır.
- Son boş-yanıt koruması için canlı MIA latency doğrulaması yapılmadı; yerel testler güvenli yanıt davranışını kapsar, sağlayıcı performansını kapsamaz.
