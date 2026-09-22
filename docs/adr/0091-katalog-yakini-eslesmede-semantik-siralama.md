# ADR-0091 — Yakın katalog adaylarında semantik sıralama

- **Durum:** Kabul edildi
- **Tarih:** 2026-09-20
- **İlgili çalışma:** MIA benchmark sonrasında retrieval doğruluğu

## Bağlam

BM25; kaynak, frekans ve katalog açıklamalarındaki ortak kelimeler nedeniyle aranan kavramı daha zayıf eşleşen bir seriyi üst sıraya çıkarabiliyor. `verified` etiketi tek başına kullanılırsa da alakasız doğrulanmış seriler doğru ama `derived` işaretli serileri geçebilir. Ölçüm türü (`stock`, `flow`, `ratio` vb.) veri kataloğunda zaten mevcut; ranking bunu kullanmıyordu.

## Karar

1. Önce mevcut BM25/hybrid sıralaması korunur. Semantik sıralama yalnız ilk adayın skorunun %85'i içinde kalan yakın aday kümesinde çalışır.
2. Açık ölçüm niyeti, katalog kolonlarının `semantic_type` bilgisinden türetilen türlerle karşılaştırılır. Sorgudaki yüzde değişimi gibi türetilmiş çıktı talepleri, kaynak ölçüm türü sanılmaz.
3. Kaynak/frekans/coğrafya ve istek fiilleri gibi bağlam terimleri çıkarıldıktan sonra kalan kavram terimlerinin aday adı ve alias'larındaki doğrudan karşılığı kullanılır.
4. `verified` yalnız aynı kavram eşleşmesine ve aynı ölçüm türüne sahip adaylarda son tie-break'tir. Kavram eşleşmesi yoksa verification sıralamayı değiştirmez. Belirsiz sorgularda mevcut BM25 sırası korunur.
5. Katalog seri kimliği, metrik adı veya benchmark cümlesine özel kural eklenmez.

## Sonuçlar

- Yakın, aynı adlı stok serilerinde doğrulanmış anlam seçilebilir; vade kırılımı açıkça istenince o alt seri lexical ilgisini korur.
- Semantik sinyaller yalnız yakın aday havuzuna uygulanır; uzak adayların ilk sıraya sıçraması engellenir.
- Kullanıcı ifadesindeki ölçüm türü açık değilse retriever tür uydurmaz ve mevcut sıralamayı korur.

## Doğrulama

- Retrieval birim testleri, gerçek Silver katalog smoke testi ve agent-core tam test paketi.
- Gerçek katalogda genel mevduat/stok sorgusu `bddk_monthly:1357_Toplam` ile başlar; vade ifadesi olan sorgu `bddk_monthly:543_Toplam` ile başlar.

