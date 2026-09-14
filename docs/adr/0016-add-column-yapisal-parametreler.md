# ADR-0016: workspace_add_column serbest SQL almaz

**Durum:** Kabul edildi · **Tarih:** 2026-09-09

## Bağlam
`workspace_add_column` ilk sürümünde modelden bir SQL alıyordu. Ölçümde şu hata
modu tekrarlandı: model, **eklemek istediği yeni sütunun adını** SELECT listesine
var olan bir kolon gibi yazdı.

```sql
SELECT donem, tasit_kredisi FROM bddk_aylik_krediler WHERE kalem = '...'
                ^^^^^^^^^^^^^ böyle bir kolon yok; bu, eklenecek sütunun adı
```

DuckDB'nin ham hatası ("Referenced column not found") modele yol göstermedi.
Model aynı çağrıyı tekrarladı, sonra `lakehouse_query`'ye kaçıp analiz tablosunu
yeniden kurdu — yani aracın var oluş sebebi olan "tabloyu bozmadan" garantisi
çöktü. Sonuç tablosunda eklenmesi istenen sütun hiç yoktu.

Önce hata mesajını yönlendirici yapmayı denedik (ham hatanın üstüne "bu senin
yeni sütununun adı, value_column'a gerçek bir kolon yaz" açıklaması). Bu, hatayı
düzeltilebilir kıldı ama modelin kaçış davranışını engellemedi.

## Karar
Araç artık SQL almıyor. Yapılandırılmış parametreler alıyor:
`dataset_id`, `key_column`, `value_column`, `filter_column`, `filter_value`,
`column_name`, `join_on`. SQL'i harness üretiyor.

Kolon adları **katalogla doğrulanıyor**: `value_column` o tabloda yoksa çağrı
reddediliyor ve mevcut kolonlar listeleniyor. Model var olmayan bir kolon
uyduramaz — yasak olduğu için değil, imkânsız olduğu için.

## Gerekçe
Bu, semantic layer literatüründeki gözlemin küçük ölçekli uygulaması:
deterministik sorgu üretimi, modelin sessizce yanlış sorgu kurmasını engelliyor.
Serbest SQL'in esnekliği bu araç için zaten gereksizdi — tek yaptığı bir kolonu
bir filtreyle çekip mevcut tabloya hizalamak.

## Bedeli
Araç şeması 3 parametreden 7'ye çıktı, yani her turda prompt'a giren metin uzadı.
Literatür araç şeması büyümesinin seçim doğruluğunu düşürdüğünü söylüyor; bu
bedelin karşılığı, aracın yanlış kullanılamaz hale gelmesi.

## Sonuç
G6 (`"bu tabloyu hiç bozmadan taşıt kredisini sütun olarak ekle"`) geçiyor.
