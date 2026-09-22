# ADR-0098: Takip dönüşümünde dönem anahtarı ve bozuk türetim onarımı

- Durum: Kabul edildi
- Tarih: 20 Eylül 2026

## Bağlam

Aktif çalışma tablosu hem gerçek tarih kolonu hem de aynı ayları `YYYY-MM` biçiminde tekrarlayan metin bir dönem kolonu taşıyabilir. Bu metin kolonu panel boyutu sanılıp `LAG` için `PARTITION BY` alanı yapılırsa her satır ayrı gruba düşer ve türetilen değişimlerin tamamı `NULL` olur. Yalnızca kolon adlarına, provenance'a ve tablo şekline bakan bir doğrulama bu bozuk sonucu yanlışlıkla başarılı sayabilir. Sonraki aynı takip isteği ise türetilmiş kolonlar zaten var olduğu için güvenli dönüşüm planını kuramayabilir.

## Karar

- Aylık metin anahtarı ancak satır satır ana tarih kolonu ile aynı ayı gösteriyorsa redundant dönem etiketi sayılır ve panel gruplamasından çıkarılır. Gerçek boyutlar (il, ürün, kategori gibi) gruplama anahtarı olarak korunur.
- Var olan türetilmiş değişim kolonları yalnızca ad/provenance kontrolüyle kabul edilmez. Tarih ekseni, kaynak kimliği ve gözlenen değerler deterministik LAG aritmetiğiyle doğrulanır; bütün değerlerin `NULL` olması veya beklenen farklarla uyuşmaması dönüşümü geçersiz kılar.
- Son workspace adımı uygulamanın ürettiği bir dönüşüm olarak tanınabiliyor, fakat sonucu geçersiz bulunuyorsa düzeltme yalnızca hemen önceki doğrulanmış snapshot'tan yapılır. Kaynak/provenance kanıtı veya güvenli önceki snapshot yoksa otomatik onarım yapılmaz; normal agent yolu kullanılabilir.
- Aynı istek tekrarlandığında doğrulanmış dönüşüm yeniden kullanılır; yeni katalog araması ya da LLM çağrısı yapılmaz. Aktif tablo başlığı da son dönüşümün dönem ve kapsamını izler.

## Sonuç ve doğrulama

- Düzenleme genel workspace LAG davranışına uygulanır; belirli soru metnine, kaynak seri kimliğine veya belirli finans kalemine bağlı değildir.
- Regresyon testi redundant aylık etiketin partition anahtarı yapılmadığını, hatalı persisted dönüşümün kaynak snapshot'tan düzeltildiğini, önceki ay tabanının korunduğunu ve tekrarlanan takipte doğrulanmış tablonun LLM'siz yeniden kullanıldığını denetler. Sentetik test aralığı benchmark sorularından farklıdır.
- Agent-core tam test paketi: **907 geçti**; yalnızca mevcut Starlette/AnyIO deprecation uyarısı.
- Canlı MIA A/B ölçümünde aynı model, çalışma tablosu, 21 araç şeması ve 2.800 completion-token tavanıyla SYSTEM_PROMPT için başarılı örnek 52,70 sn / 14.461 prompt token; NARRATION_PROMPT için başarılı 120 sn tanı çağrısı 77,61 sn / 10.995 prompt token döndürdü. Başarılı örneklerde giriş token farkı %24 azalma gösterdi; latency hızlanması göstermedi. 60 sn bütçeli çağrılarda SYSTEM_PROMPT bir başarılı/ bir timeout, NARRATION_PROMPT iki timeout verdi. Küçük örneklem ve servis değişkenliği nedeniyle hız/başarı oranı kazanımı iddia edilmez; kısa prompt'un 60 sn narration SLO'sunda ayrıca benchmark edilmesi gerekir.
- Bu ölçümde soru/tablo içeriği kod veya benchmark dosyasına eklenmedi; koşu anlık MIA istekleriyle yapıldı.

## Etkilenen alanlar

- `agent-core/src/kkb_agent/core/workspace_fastpath.py`
- `agent-core/src/kkb_agent/core/agent.py`
- `agent-core/src/kkb_agent/core/workspace.py`
- `agent-core/tests/test_workspace_fastpath.py`
