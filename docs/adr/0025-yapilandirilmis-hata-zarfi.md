# ADR-0025: Yapılandırılmış hata zarfı ve döngü kilidi

**Durum:** Kabul edildi · **Tarih:** 2026-09-11

## Bağlam
Hata, harness'ın modelle en çok konuştuğu şeydi: 21 ayrı noktada, her biri kendi
serbest metin cümlesiyle. Bu üç şeyi imkânsız kılıyordu:

1. **Saymak.** Golden çıktısında yalnız "4 araç hatası" yazıyordu; hangi sınıfın kaç kez
   bozulduğu görünmüyordu. Araç sayısı 7'den 12'ye çıkarken bu körlük kabul edilemez.
2. **Ayırmak.** "Filtreyi düzelt, tekrar dene" ile "bu veri yok, tekrar deneme" aynı
   biçimde dönüyordu. Modelin ikisini üsluptan ayırması bekleniyordu; ADR-0017'de
   ölçtük, ayıramıyor.
3. **Yönlendirmek.** Adaylar (mevcut kolonlar, benzer seriler) mesajın içine gömülüydü,
   yapısal olarak taşınmıyordu.

## Karar
`ToolError(error_code, message, hint, candidates, layer, retryable)` ve
`ToolResult.fail(...)`. 21 noktanın tamamı çevrildi; **mesaj metinleri korundu** —
ölçülerek yazıldılar (ADR-0010, 0016, 0017, 0019), değişen etraflarındaki zarf.

Modele giden biçim:

```
HATA[COLUMN_NOT_FOUND]: 'tasit_kredisi' bu seride yok.
ADAYLAR: observation_date, value, quality_flag, entity_id
YAPACAĞIN: value_column'a kaynakta var olan bir ölçüm kolonu yaz.
```

15 kod, beş katmanda: `schema` (INVALID_ARGS, UNKNOWN_TOOL), `reference`
(DATASET_NOT_FOUND, COLUMN_NOT_FOUND, VALUE_NOT_FOUND), `policy` (UNSAFE_SQL,
MISSING_PERIOD_FILTER), `data` (OUT_OF_COVERAGE, EMPTY_RESULT, JOIN_MISMATCH,
SQL_FAILED), `workspace` (NO_ACTIVE_TABLE, COLUMN_EXISTS), `harness`
(DUPLICATE_CALL, TOOL_FAILED).

### Onarılabilirlik açıkça söyleniyor
`NOT_RETRYABLE = {OUT_OF_COVERAGE, UNSAFE_SQL, UNKNOWN_TOOL}`. Bu üçünde mesajın
sonuna *"BU HATA TEKRAR DENEMEYLE ÇÖZÜLMEZ"* ekleniyor **ve** harness modele araç
vermeden son bir tur açıyor. Model aynı yolu farklı yazımlarla denemeye devam
edemiyor; ADR-0017'de adım limitini yakan davranış buydu.

### Döngü kilidi
`(araç adı, argümanlar)` imzası tekrarlanırsa araç çalıştırılmıyor, `DUPLICATE_CALL`
dönüyor. Ölçülmüş hata modu: aynı sorgunun art arda yedi kez çalıştırılması.
Sahte LLM ile doğrulandı — model dört kez istedi, araç **bir kez** çalıştı.

## Ölçüm
Golden **7/7** (Silver şeması, MIA). Birim testleri 60 → 69. Yeni görünürlük:

```
SONUÇ: 7/7 geçti | toplam araç hatası: 4
HATA SINIFLARI: SQL_FAILED×3, MISSING_PERIOD_FILTER×1
```

Bu satır daha önce üretilemiyordu. `SQL_FAILED×3` şimdiden bir sinyal: model SQL
yazarken üç kez hata yapıp düzeltiyor — sıradaki iyileştirmenin nereye bakacağını
söylüyor.

## Sonuç
Ölçekte hata görünürlüğü, araç sayısından bağımsız olarak sabit maliyetli hale geldi:
yeni bir araç eklemek yeni bir kod eklemek demek, yeni bir hata anlatım biçimi değil.
