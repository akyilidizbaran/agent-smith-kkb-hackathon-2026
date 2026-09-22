# ADR-0097: Faz duyarlı, kısa narration promptu

- Durum: Kabul edildi
- Tarih: 20 Eylül 2026

## Bağlam

`AnalyticsAgent` her LLM çağrısında aynı ilk system mesajını kullanıyordu. Yeni tabloyla başlayan isteklerde bu mesaj `COMPACT_PLANNING_PROMPT` olarak kalıyor, doğrulanmış araç çıktısından sonra da son yanıt için yeterli sunum talimatını içermiyordu. Web araştırmasında ise kaynak okunduktan sonraki model kararı süre/token bütçesi nedeniyle `tool` fazında kalabiliyor; araç bütçesi ile yanıtın rolü aynı eksen değildi.

## Karar

1. Genel veri/araç keşfi promptları değiştirilmeden `NARRATION_PROMPT` adlı kısa, alan profilinden render edilen yanıt sözleşmesi eklenir.
2. Harness `narration` fazı beklediğinde system mesajının prompt katmanını bu sözleşmeyle değiştirir. Web kaynağı başarıyla okunduktan sonraki çağrıda da kısa yanıt talimatı kullanılır; web çağrısının `tool` token bütçesi, deadline'ı ve araç şemaları aynı kalır.
3. System mesajı tek ve ilk mesaj olmaya devam eder. JSON protokolü, araç tanımları, aktif tablo/çalışma durumu, takip/dönem notları gibi çağrı bağlamı prompt değişiminden sonra korunur.
4. Grounding, hücre/dönem doğrulaması, nedensellik kontrolü ve son çıkış filtreleri harness'te kalır. Prompt; doğrulamanın yerine geçmez.
5. Benchmark soruları, finans serileri veya belirli kullanıcı promptları yeni prompta gömülmez.

## Gerekçe

Son yanıtın kullanıcıya ne söyleyeceği ile hangi aracı seçeceği ayrılır. Kısa yanıt sözleşmesi; kaynak, dönem, kapsam ve birimi korumayı, eksik kanıtı açıklamayı, UI'daki tabloyu yeniden dökmemeyi ve yanıtı kısa tutmayı tarif eder. Araç çıktısı/aktif tablo dinamik bağlam olarak kalır. Prompt metni, genel `SYSTEM_PROMPT` çekirdeğine göre karakter sayısında %60'tan fazla kısadır; sağlayıcı tokenizer'ındaki gerçek token ve latency farkı henüz canlı ölçülmemiştir.

## Riskler ve sınırlar

- Web sayfası okunduktan sonra model daha fazla araştırma isteyebilir. Araçlar açık kalır ve kısa prompt bu durumda eksik kanıt varsa uygun aracı kullanmasını söyler; `tool` deadline/bütçesi korunur.
- Standart prompttan türeyen kapsam/araç kuralları final narration'da kullanılmaz; bu faz, harness'ın gereken araçların çalıştığını varsaydığı fazdır. İstenen işlem tamamlanmadıysa araç gereksinimleri/validasyon kapıları bunu yakalamalıdır.
- Recovery promptu ve planning/tool promptları bu adımda yeniden tasarlanmadı.
- Bu değişiklik MIA/Tavily canlı çağrısıyla ölçülmedi; manuel demo karşılaştırması sonraki doğrulamadır.

## Doğrulama

- Araçsız cevap ve web-kaynak-sentezi senaryolarında faza göre system prompt seçimi sahte LLM ile doğrulandı.
- Aktif tablo/çalışma bağlamının korunması ve özel system prompt'un silinmemesi test edildi.
- `uv run pytest -q`: 906 geçti; tek mevcut Starlette/AnyIO deprecation uyarısı.
