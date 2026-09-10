# Araştırma denetimi: deney dosyaları

Ana rapor: [KKB_RESEARCH_AUDIT.md](../KKB_RESEARCH_AUDIT.md).

Bu klasör production agent çıktısı değildir. Gerçek KKB/BDDK/EVDS gözlem verisi içermez.

| Dosya | Durum |
|---|---|
| `mia_observations.json` | Yeni MIA bağlantı denemeleri `ConnectError`; başarılı inference sonucu yok. Sandbox dışı çalıştırma isteği reddedildi. |
| `retrieval_results.json` | 20 sentetik metadata kaydı, 36 soru, 32 puanlanan sorgu; yalnız BM25 çalıştı. |
| `synthetic_embeddings.json` | Ancak yetkili başarılı MIA koşusundan sonra oluşur; şu an yok. |

Mevcut `docs/mia_capability_matrix.md` eski bir yerel ölçüm kaydıdır. Rapor bu kaydı bu oturumda tekrar doğrulanmış sonuç diye sunmaz. Başarısız ağ denemesinin script hash'i, o anda çalıştırılan sürüme aittir; sonraki offline test/fixture-hash iyileştirmeleriyle betik değişmiştir.

Çevrimdışı doğrulama:

```powershell
python -m unittest discover -s tests -p test_research_audit.py
python scripts/retrieval_evidence_audit.py
```

Canlı test betiği, ağ erişimi mevcut ve kullanım yetkili olduğunda kullanıcı tarafından çalıştırılabilir:

```powershell
python scripts/mia_evidence_audit.py
python scripts/retrieval_evidence_audit.py
```

Betik yalnız `https://mia.csp.kloudeks.com/v1` hedefine, `.env`/environment içindeki `MIA_API_KEY` veya `LLM_API_KEY` ile gider; anahtarı yazdırmaz. Environment aynı isimdeki `.env` değerini geçersiz kılar. `httpx`, `python-dotenv`, `jsonschema` ve Pillow gerektirir; mevcut ortamda offline testler bu paketlerle çalıştı. Yanlış/eksik credential veya baseline hatasında devam etmez. Büyük context/yük testi değildir. Native tool önerileri yalnız sabit sentetik `lookup` sonucuyla eşleştirilir, modelin istediği arbitrary tool çalıştırılmaz.

Canlı betik bu klasördeki kendi sonuçlarını yeniden yazar. Önceki deney korunacaksa koşudan önce klasörün ayrı bir kopyası alınmalıdır. Başarılı embedding dosyası fixture hash'i taşır; evaluator stale fixture vektörlerini reddeder. Reranker ve yerel sentence-transformer bu iki betikte uygulanmış değildir; ana rapordaki bake-off tasarımının açık deney kollarıdır.

Metrik ayrımı: Recall@k relevant belgelerin bulunan payı; Precision@k ilk k içindeki relevant pay; MRR ilk doğru sonucun ters sırası; nDCG@5 sıralama kalitesi. Eksik/belirsiz/adversarial sorular için agent abstention testi yapılmadığından bu sorular IR özetine sokulmaz. CPU ranking süresi ağ/model/index build/peak RSS ölçümü değildir.
