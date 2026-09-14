# ADR-0011: Prompt'a kural ekleyerek davranış düzeltme

**Durum:** REDDEDİLDİ · **Tarih:** 2026-09-09

## Bağlam
G5'te model "A ile B'yi karşılaştır" sorusunda yalnız A'yı getirip cevaba
geçiyordu. İlk refleks: system prompt'a "sorudaki her unsuru karşıla" kuralı
eklemek.

## Denenen
System prompt'a şu blok eklendi: sorudaki her kalemin ayrı ayrı doğrulanması,
dönem filtresinin zorunluluğu, kırılımın kontrolü.

## Ölçüm

| | Öncesi | Kural eklendikten sonra |
|---|---|---|
| G5 geçme oranı | 0/4 | 0/4 |
| Adım sayısı | 4 | **11** |
| Süre | 58 s | **174 s** |

Kural sorunu çözmedi, üstelik modeli daha çok denemeye itip süreyi üçe katladı.
Değişiklik geri alındı.

## Gerekçe
System prompt zaten uzun. 8B'lik bir model ek kuralı taşıyamıyor; kural sayısı
arttıkça hepsine birden uyma kapasitesi düşüyor ve model kayboluyor.

**Genel ilke:** bir davranış sorunu prompt'a kural ekleyerek çözülmüyorsa, sorun
mimaridedir. Kalan çözüm ya araç imkânlarını kısıtlamak (ADR-0006'daki gibi) ya
da bir plan/doğrulama katmanı eklemektir.

## Not
Bu kayıt özellikle tutuldu: ölçüm olmasaydı bu değişiklik "iyileştirme" sanılıp
bırakılacaktı. Aynı fikir tekrar gündeme geldiğinde tartışma sıfırdan
başlamasın.
