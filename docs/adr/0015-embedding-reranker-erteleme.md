# ADR-0015: Embedding/reranker yatırımının ertelenmesi

**Durum:** Ertelendi · **Tarih:** 2026-09-09

## Bağlam
Retrieval'ı LLM yerine bi-encoder/cross-encoder ile yapmak gündeme geldi. Hız
farkı büyük görünüyordu.

## Ölçüm
`nomic-embed-text` ile BDDK'nın 63 kalemi üzerinde, gerçek sorularla:

| | Sonuç |
|---|---|
| Sorgu süresi | **12 ms** (LLM: ~6.000 ms) |
| Top-1 isabet | **2/7** |
| Top-3 isabet | 5/7 |

Kritik başarısızlık örneği:

```
'konut kredisi' →  0,902  Takipteki Konut Kredileri      ← YANLIŞ
                   0,900  Tüketici Kredileri - Konut     ← doğru olan
```

Fark 0,002. Bi-encoder "takipteki alacak" ile "canlı bakiye"yi ayırt edemiyor —
ki bu tam da G2/G5'te modelin düştüğü tuzak. `'mortgage bakiyesi'` tamamen
alakasız kalemlere gitti.

Buna karşılık mevcut `ILIKE '%konut%'` filtresi tam 3 doğru aday üretmişti.

## Karar
Embedding/reranker yatırımı **ertelendi**. Bağlam ön-yükleme (ADR-0013) önce
mevcut keyword aramasıyla yapılacak.

## Gerekçe
- Saf semantik arama, ölçüldüğünde mevcut keyword filtresinden **kötü** çıktı.
- Literatür bunu doğruluyor: hibrit retrieval saf semantikten üstün, çünkü şema
  ve araç dokümantasyonunda kesin terminoloji var ve keyword eşleşmesi orada
  embedding'i yeniyor.
- Ölçülemeyen iyileştirme yapılmaz: şu an tek tablomuz var, seçilecek bir şey yok.

## Yeniden değerlendirme tetikleyicileri
1. Katalog çok tablolu hale geldiğinde (veri ekibinin çıktısı),
2. Araç sayısı 15'i geçtiğinde (literatürdeki bozulma eşiği),
3. Kloudeks embedding + reranker modelleri erişilebilir olduğunda.

## Not
Ölçüm tek bir modelle yapıldı. `nomic-embed-text` ağırlıklı İngilizce eğitilmiş;
`bge-m3` veya `multilingual-e5` gibi çok dilli bir model Türkçe'de belirgin
şekilde daha iyi olabilir. "Embedding Türkçe'de çalışmaz" sonucu çıkarılmamalı —
çıkarılan sonuç: **test edilen model bu görevde çalışmadı.**

Uygulandığında hedeflenen tasarım hibrit olacak: BM25/FTS (kesin terim) +
bi-encoder (eşanlamlı) → cross-encoder reranker (nihai sıralama).
