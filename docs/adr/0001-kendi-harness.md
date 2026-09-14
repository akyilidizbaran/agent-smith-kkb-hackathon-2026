# ADR-0001: Agent orkestrasyonu için kendi harness'ımız

**Durum:** Kabul edildi · **Tarih:** 2026-09-08

## Bağlam
Agentic motorun planla → araç çağır → gözlemle döngüsü ya hazır bir çerçeveden
(LangGraph vb.) alınacak ya da sıfırdan yazılacaktı. Açık kaynak çerçeve
kullanmak şartnameye aykırı değil.

## Karar
Planner/executor döngüsü, araç soyutlaması ve durum yönetimi sıfırdan yazıldı.
Yalnızca `openai` (protokol istemcisi) ve `pydantic` bağımlılığı var.

## Gerekçe
- Açılış toplantısındaki yönlendirme: *"harness yapısını daha güçlü yapın,
  LLM'e en az işi bırakın."* Değerlendirmede harness'ın nasıl kurgulandığına
  bakılacağı açıkça söylendi.
- Bilinçli olarak zayıf modelle çalışıyoruz. Tool-calling'in tıkandığı yerde
  onarım, JSON'a düşme, adım limiti gibi davranışları satır satır kontrol
  edebilmek gerekiyor; çerçevenin soyutlamaları bunu zorlaştırırdı.
- Şartname modüler yapıyı katılımcının implement etmesini bekliyor.

## Değerlendirilen alternatifler
- **LangGraph:** daha hızlı başlangıç, ancak küçük modelde hata ayıklama zor ve
  kendi katkımız daha az görünür.
- **Hibrit:** çekirdek bizim, yardımcı parçalar kütüphaneden. Ek bağımlılığın
  getirisi net olmadığı için seçilmedi.

## Sonuçlar
Daha fazla kod yazıldı, karşılığında döngünün her adımı ölçülebilir ve
değiştirilebilir oldu. ADR-0005, ADR-0010 ve ADR-0011'deki müdahalelerin hepsi
bu kontrol sayesinde mümkün oldu.
