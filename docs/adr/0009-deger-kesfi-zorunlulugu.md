# ADR-0009: Filtre yazmadan önce gerçek değerleri görme

**Durum:** Kabul edildi · **Tarih:** 2026-09-08

## Bağlam
İlk uçtan uca ölçümde model, filtreleyeceği kalem adını **tahmin etti**. İki
sorgu boş döndü, ardından `LIKE '%Konut%'` ile üç ayrı kalemi birden çekip
mükerrer topladı ve sonucu "hata verisi olabilir" diye geçiştirdi.

## Karar
`lakehouse_distinct_values` aracı eklendi ve system prompt'a zorunlu iş sırası
kondu: `search → describe → distinct_values → query`. Araç, kaynağın kendi
sinyalinden türetilen `is_alt_toplam` bayrağıyla alt toplam satırlarını
işaretler ve "yalnızca birini seç" uyarısı verir.

## Gerekçe
Modele "uydurma" demek yetmiyor; **uydurmasına gerek bırakmamak** gerekiyor.
Gerçek değerleri gördüğünde tahmin etmiyor.

Alt toplam bilgisi kaynakta zaten vardı ama kullanılmıyordu: BDDK alt toplam
satırlarını `bold` font ile işaretliyor. Bu sinyal seed'de `is_alt_toplam`
kolonuna çevrildi.

## Ölçüm
- "2025 Aralık konut kredisi" sorusu artık **678.970 milyon TL** — kaynakla birebir.
- G2 (aylık seri) mükerrer sayım yapmayı bıraktı: 36 satır → 12 satır.
- Uyarı metni ilk sürümde yetersizdi; model üç kalemi `IN (...)` ile birlikte
  aldı. "Benzer isimli kalemler farklı şeyleri ölçebilir: 'Takipteki…' takipteki
  alacaktır" ifadesi eklenince düzeldi.
