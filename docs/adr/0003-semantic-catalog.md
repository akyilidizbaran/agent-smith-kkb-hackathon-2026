# ADR-0003: Semantic catalog'un zorunlu anlam alanları

**Durum:** Kabul edildi · **Tarih:** 2026-09-08

## Bağlam
Ham şema (tablo + kolon adı) bir dil modeli için yetersiz. Bir sayının stok mu
akım mı olduğunu, hangi çarpanla saklandığını, kümülatif olup olmadığını bilmeden
doğru SQL üretilemez.

## Karar
Her veri seti kendini `DatasetSpec` ile tanıtır. Ölçüm kolonlarında şu alanlar
zorunlu: `semantic_type` (stock/flow/rate/index/ratio/count), `cumulative`
(none/ytd/since_inception), `unit` + `unit_multiplier`, ve Türkçe `aliases`.

## Gerekçe
- **`semantic_type`** frekans dönüşümünün girdisi. Yanlışsa aylık→çeyreklik
  dönüşümler *sessizce* yanlış sonuç verir: stok serisi toplanmaz, akım serisi
  son değeriyle alınmaz.
- **`cumulative`** BDDK slaytındaki uyarının karşılığı: *"bazı veriler paylaşım
  başlangıcından itibaren kümülatif giderken, bazıları yıllık bazda kümülatif
  gitmektedir."* İki rejim, iki farklı ayrıştırma.
- **`unit_multiplier`** varsayımsal değil, ölçülmüş bir ihtiyaç: BDDK aylık
  bülteninde Tablo 3/4 "milyon TL", Tablo 5 "bin TL" yayınlıyor.
- **`aliases`** agent'ın kolon/kalem seçimindeki isabetini en çok etkileyen alan.
  Kullanıcı "mortgage", "ev kredisi", "konut kredisi" diyebilir.

## Ölçüm (literatür)
Bu yatırımın getirisi bağımsız çalışmalarda ölçülmüş: yalnız şema verilen bir
modelde doğruluk **%8,3**; iş bağlamı dokümanı eklendiğinde **%78,3**. Frontier
modellerde 4 KB'lık bir semantic layer dokümanı **+17–23 puan** kazandırıyor
(dbt 2026 benchmark). Yani buradaki kazanç kod değil, **metin** yazarak elde
ediliyor.

## Sonuçlar
Katalog kalitesi doğrudan agent kalitesi demek. Veri ekibinden istenen kritik
katkı budur.
