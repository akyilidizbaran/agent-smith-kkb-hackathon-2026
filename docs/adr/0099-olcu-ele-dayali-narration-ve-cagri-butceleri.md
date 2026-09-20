# ADR-0099: Ölçülebilir, kompakt ve araçsız son anlatım

- Durum: Kabul edildi
- Tarih: 20 Eylül 2026

## Bağlam

Doğrulanmış tablolar üretilmesine rağmen son anlatım çağrısı tekrar araç şemalarını, araç konuşmalarını ve gereğinden büyük girdiyi taşıyabiliyor; model gecikmesi tablo teslimini de başarısız gibi gösterebiliyordu. Büyük CSV/tablo artifact'leri, kendi başına uzun bir açıklama gerektirmiyor. Gecikmenin provider kuyruğu, girdi işleme, çıktı üretimi veya araç çalıştırmasından hangisinde oluştuğu da tek bir toplam süreyle ayırt edilemiyordu.

## Karar

İyileştirme aşağıdaki sırayla uygulanır:

1. Her LLM çağrısı faz, süre, ilk görünür token süresi, giriş/çıkış tokenı, retry/bekleme, istek kimliği, mesaj/şema boyutu ve başarı durumuyla ölçülür. Araç süresi, mesaj/katalog hazırlığı, narration fact hazırlığı ve tüm tur süresi ayrı sayaçlardır. Ham prompt ve cevap telemetriye yazılmaz. Stream kullanılmayan sağlayıcı çağrılarında ilk token süresi `null` kalır; ölçülmüş gibi sıfır yazılmaz.
2. Tamamlanmış ve doğrulanmış veri işi için narration girdisi `NarrationFacts` adlı sınırlı bir pakettir: kaynak, dönem, ölçüm etiketi/birimi, tablo boyutu, eksiklik ve gözlenen uçlar ile doğrulanmış araç bulguları. Bu yardımcı paket analiz veya nedensellik hesaplamaz; istenen hesaplar SQL/analiz aracında doğrulanmış olmalıdır. Tam tablo ve indirme artifact'i değişmeden kalır.
3. Son anlatımda araç şemaları ancak başarılı veri çıktısı, istenen tanınmış yeteneklerin tamamlanması, mevcut turda çözümlenmemiş araç/sayı/nedensellik onarımı olmaması ve web araştırma akışının dışında olma koşullarında kaldırılır. Koşullardan biri sağlanmazsa kompakt anlatım yolu kullanılmaz ve araç bağlamı korunur.
4. Doğrulanmış tablo narration zaman aşımından bağımsız teslim edilir. LLM yanıt vermezse harness, aynı doğrulanmış tablodan deterministik ve açıkça yerel özet olduğu belirtilen fallback'i üretir; bu fallback yeni yorum/hesap iddiası değildir.
5. Çıktı token tavanı artifact satır/sütun sayısıyla otomatik büyütülmez. Basit sonuç kısa bütçe, açık analiz veya çoklu kaynak anlatımı geniş bütçe alır; global tavan korunur. Bütçe değişikliğinin doğruluk, truncation, süre ve fallback oranı benchmark'ta ölçülür.

Genel `SYSTEM_PROMPT`, aynı güvenlik ve kaynak kurallarını koruyup tekrarlı talimatları birleştirerek 5.373 karakterden 2.679 karaktere indirildi. Bu **%50,1 karakter azalmasıdır**; sağlayıcı tokenizer'ında aynı oranda token düşüşü veya daha düşük latency olduğu sonucu çıkarılmaz. Özel sistem promptları korunur. Nihai compact narration, genel agent promptundaki tool/işletim eki talimatlarını tekrar taşımaz.

MIA/Kloudeks akış endpoint'i önceden doğrulanmadığından `LLM_STREAM_NARRATION` varsayılanı kapalıdır. Açıldığında yalnız araçsız narration akışında TTFT ölçer ve final usage chunk'ı varsa token sayısını alır. Sağlayıcının stream/usage desteği ayrı canary ile doğrulanmadan varsayılan açılmaz.

## Sonuç ve doğrulama

- Yeni testler narration olgu paketinin sınırlı ve kanıta bağlı olmasını, başarılı son anlatımda araç şemasının kaldırılmasını, bekleyen analitik yetenekte araçların korunmasını, stream TTFT/usage ölçümünü ve system prompt'un kritik kurallarının kısaltmadan sonra durmasını denetler.
- Agent-core tam test paketi: **915 geçti**, bir mevcut Starlette/AnyIO deprecation uyarısı.
- İlgili modüllerde Ruff `F` ve depo genelinde `git diff --check` temiz. Depo geneli Ruff taraması, bu değişikliklerin dışındaki önceki dirty çalışma ağacında 25 mevcut uyarı bildirdi; bunlar bu iş kapsamında değiştirilmedi.
- Canlı MIA canary/tekrarlı latency benchmark'ı yapılmadı. Bu nedenle MIA TTFT, stream uyumu, giriş token tasarrufu ve hız kazanımı iddia edilmez; `LLM_STREAM_NARRATION=false` ile manuel test sonrası ölçülür.
- Benchmark promptlarına soru örneği eklenmedi; değişiklik veri sorularına özel değildir.

## Etkilenen alanlar

- `agent-core/src/kkb_agent/core/agent.py`
- `agent-core/src/kkb_agent/core/narration_facts.py`
- `agent-core/src/kkb_agent/core/token_budget.py`
- `agent-core/src/kkb_agent/llm/openai_compat.py`
- `agent-core/src/kkb_agent/config.py`
- `agent-core/src/kkb_agent/cli.py`
- `agent-core/tests/test_agent_loop.py`
- `agent-core/tests/test_harness_performance.py`
- `agent-core/tests/test_narration_facts.py`
- `agent-core/tests/test_token_budget.py`
