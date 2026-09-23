# ADR-0107: Seri kimliği tablo adı değildir

**Durum:** Kabul edildi · **Tarih:** 2026-09-23 · **İlgili:** ADR-0105, ADR-0106

## Bağlam
Canlı incelemede ajan EVDS serisi `TP.KKHARTUT.KT1`'i sorgularken DuckDB `Binder Error: Catalog "TP" does not exist`
verdi. ADR-0105 bu hatanın sonucunu yumuşatıyordu (cevap silinmiyor, dürüst not ekleniyor) ama nedenini kapatmıyordu.

Seri-merkezli lakehouse'ta (`adapters/silver_lakehouse.py`) her seri bir `DatasetSpec`'tir; fiziksel veri tek uzun tablodadır:
`silver.fact_observation WHERE series_id = '<id>'`. Kimlik FROM'a yazılınca DuckDB `TP.KKHARTUT.KT1`'i katalog.şema.tablo,
`evds:TP.KTF17`'yi şema.tablo sanır.

Koşu kayıtlarında (23 Eylül, 11 vaka, 33 hata) iki ayrı yol vardı:
1. **Araç hatası.** `lakehouse_distinct_values` kendisine verilen kimliği doğrudan FROM'a yazıyordu. Model doğru kimliği verse de
   `SELECT DISTINCT quality_flag FROM evds:TP.KTF17` çalıştı ve patladı (S06, L04 `bddk_finturk:ANKARA_ToplamMevduat`).
   Aynı hata `_toplam_deger_sayisi` ve `core/context.py` kırılım ön yüklemesinde de vardı; ikincisi sessizce yutuluyordu.
2. **Model hatası.** `lakehouse_query`'de model kimliği tablo adı olarak yazınca araç genel SQL_FAILED döndürüyor ve
   "kolon adlarını karşılaştır" diyordu; sorun kolonda değil tabloda olduğu için ipucu yanıltıcıydı.

## Karar
1. `SilverLakehouse.relation_sql(dataset_id)` kimliğin FROM ifadesini verir: seri için
   `(SELECT * FROM <ilişki> WHERE series_id = '<id>') AS _seri`, Gold tablosu için kimliğin kendisi. `lakehouse_distinct_values`,
   değer sayımı ve `core/context.dimension_values` bunu kullanır. Yöntemi olmayan adaptörlerde (eski DuckDB, testler) kimlik
   gerçek tablodur ve olduğu gibi kalır.
2. `lakehouse_query` SQL'i çalıştırmadan önce FROM/JOIN hedeflerine bakar. Hedef katalogdaki bir seri kimliğiyse (tırnaklı ya
   da `kaynak:kod` biçiminde) ya da çıplak bir EVDS kodu (`TP.…`) ise sorgu çalıştırılmaz. Tekrar denenebilir `INVALID_ARGS`
   döner: kimlik ADAY olarak verilir, doğru kalıp tam yazılır
   (`SELECT observation_date, value FROM silver.fact_observation WHERE series_id = '<id>' AND observation_date BETWEEN …`).

## Sonuçlar
- Kırılım aracı artık her seri kimliğiyle çalışır (canlı: `evds:TP.KKHARTUT.KT1`, `evds:TP.KTF17`,
  `bddk_finturk:ANKARA_ToplamMevduat`).
- Model kimliği tablo adı olarak yazarsa DuckDB'ye hiç gitmeden tek adımda onarılabilir bir yönlendirme alır.
- Gold tabloları (`gold.konut_faizi_aylik`) ve doğru yazılmış seri sorguları etkilenmez.
- Model başka bir biçimde yanlış tablo adı uydurursa (ör. `silver.series_catalog`) eski SQL_FAILED yolu sürer; bu karar yalnız
  katalog kimliklerini kapsar.
- Test: `tests/test_gold_tools.py::test_seri_kimligi_tablo_adi_olarak_kullanilmaz`.
