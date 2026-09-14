# ADR-0013: Schema linking'i LLM turundan çıkarma

**Durum:** Planlandı · **Tarih:** 2026-09-09

## Bağlam
Adım profili (qwen3:8b, tek soru, ölçülmüş):

```
1. lakehouse_search          10,9 s  ┐
2. lakehouse_describe         2,1 s  │ 22,6 s — hepsi ARAMA,
3. lakehouse_distinct_values  6,0 s  │ hiçbiri karar değil
4. lakehouse_distinct_values  3,6 s  ┘
5. lakehouse_query           20,4 s
6. nihai cevap               34,1 s
                             77,0 s
```

İlk dört tur bir şey karar vermiyor, arıyor. Her arama için modele gidip dönüyoruz.

Ayrıca katalog büyüdükçe tam şema context'e sığmıyor (ölçüldü, 1 tablo = 1.519
token): 25 tabloda pencerenin %93'ü, 50 tabloda sığmıyor. Veri ekibi BDDK'nın üç
kaynağı + EVDS serilerini yüklediğinde bu eşik kolayca aşılır.

## Karar
Arama adımları LLM turu olmaktan çıkarılıp soru geldiğinde çalışan deterministik
bir **bağlam ön-yükleme** katmanına taşınacak: ilgili tablolar bulunur, şema
kartları ve aday kalemler doğrudan bağlama konur, dönem kapsamı kontrol edilir.
Hedef: 6 LLM turu → 2.

## Gerekçe (literatür)
- Modüler pipeline text-to-SQL'de yerleşik desen: DIN-SQL (4 modül), CHESS
  (3 aşamalı huni), LinkAlign (çok veritabanlı ölçek).
- Seçilmiş şema, tam şemaya karşı **%5,4–5,8** doğruluk kazandırıyor.
- Tool/şema retrieval ile seçim doğruluğu **%13,6 → %43,1**, prompt token'ları
  yarı yarıya azalıyor. Berkeley Function Calling: araç sayısı 4→51 olunca
  doğruluk %43 → %2.
- Uber QueryGPT üretimde aynı hattı kuruyor: Intent → Table → Column Prune.

Bilinçli olarak zayıf modelle çalıştığımız için bu kazançların bizde daha yüksek
olması bekleniyor — ama iddia olarak değil, ölçerek gösterilecek.

## Karşı görüş
[*"The Death of Schema Linking?"*](https://arxiv.org/pdf/2408.07702) güçlü akıl
yürüten modellerde bu adımın gereksizleştiğini savunuyor. Bizim senaryomuz için
geçerli değil.

## Ön koşul
Şu an tek tablomuz var; seçilecek bir şey olmadığı için kazanç ölçülemez.
Önce katalog büyütülecek (BDDK'nın diğer tabloları + EVDS serileri), sonra
uygulanıp golden set'te ölçülecek.

## Risk
Ön-yükleme yanlış tabloyu getirirse model artık "başka tabloya bakayım"
diyemez. Bu yüzden `search`/`describe`/`distinct_values` araçları **kayıtlı
kalır**, yalnızca varsayılan yol olmaktan çıkar. Retrieval geniş tutulur (recall
öncelikli), precision LLM'e bırakılır — bkz. ADR-0014.
