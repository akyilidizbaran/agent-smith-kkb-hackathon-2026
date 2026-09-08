# ADR-0010: Kapsam kontrolü ve veri olmadan cevap engeli

**Durum:** Kabul edildi · **Tarih:** 2026-09-09

## Bağlam
Kararlılık ölçümü iki tutarlı başarısızlık gösterdi (ADR-0008):
- **G4** (kapsam dışı dönem): her denemede 12 adım harcanıyordu.
- **G5**: model katalogu okuyup veriyi hiç çekmeden cevap yazıyordu.

## Karar
İki harness müdahalesi:

**1. Kapsam farkındalıklı boş sonuç.** Boş sonucun iki sebebi var ve modele
söylenecek şey taban tabana zıt:
- filtre yanlış → düzelt ve tekrar dene
- dönem kapsam dışı → **tekrar deneme**, kullanıcıya verinin olmadığını söyle

Sorgudaki yıllar katalog kapsamıyla karşılaştırılıyor; kapsam dışıysa kesin dil
kullanılıyor.

**2. Cevap guard'ı.** Veri getiren bir araç hiç çalışmadan model cevap yazmaya
kalkarsa, cevap bir kez geri gönderilip veriyi çekmesi sağlanıyor.

## Ölçüm
G4: **0/4 → 4/4 (KARARLI)**, 12 adım → 5, 124 s → 43 s.

## Yol boyunca çıkan iki kendi hatamız
1. Kapsam mesajı ilk sürümde modele *ne yapacağını* söylüyordu; model bunu "SQL
   hatası" sanıp kullanıcıya hata ayıklama tavsiyesi yazdı. Mesaj *ne
   söyleyeceğini* verecek şekilde yeniden yazıldı. Buradan çıkan kural:
   **araç çıktısı modelin okuyacağı bir arayüzdür, üslubu davranışı belirler.**
2. Guard'ın ilk sürümü hiç tetiklenmedi: "veri üretildi mi" kontrolü DataFrame
   varlığına bakıyordu, oysa `describe` ve `distinct_values` da DataFrame
   döndürüyor. Karar araç adına göre verilecek şekilde düzeltildi.

Bu iki hata `tests/test_lakehouse_tools.py`'nin yazılma sebebi: kapsam
kontrolünde `re` import'u unutulmuştu, araç sessizce hata döndürdü ve kusur
ancak dakikalar süren uçtan uca koşuda fark edildi.
