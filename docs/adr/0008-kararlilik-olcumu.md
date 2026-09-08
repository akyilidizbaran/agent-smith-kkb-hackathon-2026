# ADR-0008: Tek koşu değil, geçme oranı

**Durum:** Kabul edildi · **Tarih:** 2026-09-09

## Bağlam
Üç ardışık tam golden koşusunda üç farklı sonuç alındı (4/6, 4/6, 5/7) ve her
seferinde farklı vakalar kaldı. Tek koşuya bakarak "düzeldi" demek yanıltıcıydı.

## Karar
Koşucuya `--repeat N` modu eklendi. Her vaka N kez koşulur; çıktı geçme oranı,
adım sayısı dağılımı, hata sebeplerinin frekansı ve **izlenen farklı araç
yolları**dır. Üç sonuç durumu: `KARARLI` (N/N), `KARARSIZ` (arada), `BAŞARISIZ` (0/N).

## Gerekçe
Demo günü jüri önünde tek deneme hakkımız olacak. %60 geçen bir vaka geçmiş
sayılmaz.

## Ölçüm — ve teşhisi değiştiren bulgu
İlk baseline beklenen tabloyu vermedi:

```
G4: 0/4 — adımlar [12, 12, 12, 12]
G5: 0/4 — adımlar [3, 3, 3, 3]
```

Adım sayıları birebir aynı. Yani bu vakalar **kararsız değil, tutarlı şekilde
başarısızdı**: workspace araçlarının eklenmesiyle (4 araçtan 7'ye) oluşan bir
regresyondu. "Kararsızlık" teşhisi ölçümle çürütüldü.

## Sonuçlar
Ölçüm olmasaydı yanlış problemi çözmeye çalışacaktık. ADR-0010'daki düzeltmeler
ve ADR-0011'deki geri alma kararı bu moda dayanıyor.
