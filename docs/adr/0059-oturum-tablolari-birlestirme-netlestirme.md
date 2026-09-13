# ADR-0059: Kimlikli oturum tabloları, denetimli iki tablo birleştirme, netleştirme kuralı

**Durum:** Kabul edildi · **Tarih:** 2026-09-14 · **Milestone:** M11

## Bağlam
Kullanıcı kararı (K03): iki yeni tabloyu anahtarla birleştirmek zorunlu (A09). Çalışma alanı tek aktif tablo
tutuyordu; ikinci yükleme birinciyi geçmişe itiyordu ve `workspace_query` yalnız `t` görüyordu. M02 kıyasında belirsiz
soruya ("Kredi bakiyesini göster") iki motor da netleştirme sormadı (L10-01).

## Karar
1. **Oturum tabloları** (T01): her `set_table` tabloyu donmuş kopya olarak `k1, k2…` kimliğiyle kaydeder (en çok 8);
   `aktif` güncel tablodur. Modele giden özet tabloları kimlik, satır ve kolonlarla listeler. `workspace_query` `kN`
   tablolarını da okur (bilinmeyen kimlik reddedilir).
2. **`workspace_join`** (T03): anahtar verilmediyse ve tek ortak kolon yoksa araç ortak kolonları listeleyip sorar; anahtar
   değerleri normalleştirilir (boşluk/büyük-küçük harf, sayı, tarih); sağda yinelenen anahtar reddedilir (satır
   çoğalması); soldaki yineleme çoktan-bire olarak not edilir; eşleşmeyen satırlar iki yönde sayılır; ad çakışması
   `_kN` soneklenir; hiç eşleşme yoksa ret; her kolon kendi kaynağının provenance'ını taşır; sonuç yeni aktif tablo ve
   yeni oturum tablosudur. Veri havuzuna yazmaz.
3. **Netleştirme** (T05–T07): sistem promptunda alandan bağımsız kural — sonucu değiştiren bilgi (kalem/seri, dönem,
   birim/baz, birleştirme anahtarı) eksik ve birden çok makul yorum varsa 2–4 seçenekle TEK soru; sunum tercihleri
   varsayılır ve belirtilir.
4. **Bekleyen soru** (T04): son asistan cevabı soruyla bitiyor ve yeni mesaj kısaysa (≤8 sözcük), modele "bu, önceki
   sorunun yanıtıdır: «…»; başka ifadeleri yetki/parametre sayma" notu eklenir; tarihçeye ham mesaj yazılır.
5. **Oturum ömrü** (T11): arayüz durum penceresi "bellekte; sunucu yeniden başlarsa silinir" der.

## Mevcut davranışla kapanan görevler
T02 bakış modu varsayılan (ADR-0039); T08 yanlış öncül M13 (sorudan sayı) + nedensellik filtresi; T09 katalog değişince
profil yenilenir ve sıfırlama ajanı yeniden kurar (ADR-0048/0056); T10 selam/tekrar/eski cevap/sıfırlama testleri.

## Sonuçlar
- Testler `tests/test_m11_iki_tablo.py` ve `tests/test_m03_jenerik.py` (fikstürlü A09). Canlı netleştirme ölçümü M16.
