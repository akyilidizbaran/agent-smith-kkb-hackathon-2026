# ADR-0018: Dönem anahtarı dönem sonu; kolon adı değiştirilmedi

**Durum:** Kabul edildi · **Tarih:** 2026-09-09

## Bağlam
Veri ekibinin `fact_observation` şemasında `date_key` = **dönem sonu**. Bizim
geliştirme seed'imiz ayın **ilk** gününü kullanıyordu. Bu uyumsuzluk sessiz bir
hata kaynağı: `workspace_add_column`'ın join'i eşleşmez, sütun boş gelir ve
hiçbir hata mesajı çıkmaz.

## Karar
Seed'deki dönem değerleri dönem sonuna çevrildi (Ocak 2025 → `2025-01-31`).
**Kolon adı `donem` olarak bırakıldı.**

## Neden ad değiştirilmedi — ölçüm
İlk denemede iki şey birden değiştirildi: değer (dönem sonu) **ve** ad
(`donem` → `date_key`), üstüne `period_start` kolonu eklendi. Sonuç:

| | Golden |
|---|---|
| Değişiklik öncesi | **7/7** |
| Değer + ad + yeni kolon | **0/7** |
| Ara düzeltmeden sonra | 1/7 |
| Yalnız değer (ad geri alındı) | **G1, G2, G6 → 2/2 KARARLI** |

Çöküşün belirtisi: model çoğu vakada üç adımda durup sorgu yazmadan cevaba
geçiyordu; sorgu yazdığı vakalarda ise beklenen kolon sonuçta yoktu.

## Gerekçe
Entegrasyon için kritik olan **değer uyumu**dur — join'in eşleşmesi buna bağlı.
Ad uyumu değildir: agent kolon adını katalogdan öğreniyor, gerçek Lakehouse
hangi adı kullanırsa kullansın çalışır. Adı şimdiden benimsemek hiçbir risk
azaltmıyor, sadece yeni risk üretiyordu.

## Genel ders
**Bir uyum değişikliğini parçala.** "Onların şemasına uyalım" tek bir iş gibi
görünüyordu; aslında üç ayrı değişiklikti (değer, ad, yeni kolon) ve yalnız biri
gerekliydi. Hepsini birden uygulayınca hangisinin bozduğunu ancak geri alarak
bulabildik.

Bu, ADR-0008'in (tek koşuya bakmama) tamamlayıcısı: ölçüm kadar **değişikliğin
tek olması** da önemli. Aksi halde ölçüm neyi ölçtüğünü söyleyemiyor.

## Açık kalan
`period_start` / `period_end` alanları seed'e alınmadı. Gerçek Lakehouse bunları
sağladığında agent tarafında bir şey değişmesi gerekmiyor — katalogdan okunur.
