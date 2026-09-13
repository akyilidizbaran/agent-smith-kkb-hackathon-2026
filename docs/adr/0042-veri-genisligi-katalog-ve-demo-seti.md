# ADR-0042: Veri genişliği — 2.214 katalog serisi, 127 serilik demo seti, aynı çekimi bir kez

**Durum:** Kabul edildi · **Tarih:** 2026-09-13 · **Sıradaki:** D9 arayüz, E kapanış

## Bağlam
Demo veritabanında 5 seri yüklüydü; BDDK aylık ve haftalık kataloglarında birer seri (konut),
FinTürk'te 81 ilin yalnız konut kolonu vardı. Jüri "taşıt kredisi", "mevduat", "dolar kuru"
deyince cevap "var ama yüklenmemiş" ya da "yok" oluyordu; dürüst ama zayıf. Kullanıcı veri
ekibinin işini gerekirse bizim devralmamızı istedi; bu iş `feature/lakehouse-integration-r3`
üstüne yeni dalda (`feature/lakehouse-catalog-breadth`) yapıldı, veri ekibi üstüne düzenleyebilir.

## Karar
1. **BDDK Aylık: 1 → 20 kalem.** Kalem ağacı `/BultenAylik/tr/Home/Gelismis` sayfasının
   `<optgroup>/<option>` listesinden okundu (kararlı kalem kimliği ilk değer). 16 bakiye kalemi
   (tüketici kredileri toplamı, taşıt, ihtiyaç, bireysel kredi kartları, toplam hanehalkı,
   takipteki tüketici/konut/taşıt/ihtiyaç/kredi kartı, krediler, takipteki alacaklar, toplam
   aktifler, özkaynaklar, toplam mevduat, yurt içi mevduat) ve 3 rasyo (takipteki alacak oranı,
   kredi/mevduat, sermaye yeterliliği). **Her biri 2025-12 için canlı çağrıldı**; birim yanıtın
   kendi kolon başlığından ("(milyon TL)", "(%)"), rasyoların sütunu `KalemSutunGetir`'den
   (`544?Rasyo`). Hepsi `verified`/`source_docs`; kanıt tablosu `docs/sources/bddk_monthly.md`.
2. **FinTürk: 81 → 648 seri, ek istek yok.** `tabloNo=3` yanıtı 8 ölçüm sütunu taşır, parser
   hepsini Bronze'a yazar, Silver katalogsuz olanları tutuyordu. Diğer 7 sütun (taşıt, ihtiyaç,
   KMH, kredi kartı, üç takipteki) 81 il için kataloğa girdi; Silver yeniden kurulunca mevcut
   Bronze'dan yayımlanır.
3. **EVDS: 8 küratörlü seri + TÜFE.** Dolar ve euro alış kuru (günlük), TCMB politika faizi
   (aylık, BIS derlemesi), ağırlıklı ortalama fonlama maliyeti (iş günü), 3 aya kadar TL
   mevduat faizi (haftalık), kart harcama tutarı (haftalık akım), M2 ve M3 (haftalık stok);
   TÜFE genel endeksi üretilmiş girdiden küratörlü hâle getirildi. Kanıt EVDS'nin kendi
   `/datagroups` ve `/serieList` yanıtları (`docs/sources/evds.md`). Üretilmiş blok
   yeniden üretilmedi: dosya zaten elle birleştirilmiş (KTF12, KFE küratörlü), aynı yol izlendi.
4. **Aynı çekim bir kez.** `scripts/run_catalog_ingestion.py` aynı FetchSpec'i paylaşan
   serileri (bir ilin 8 sütunu) bir kez çeker; ölçüldü, 12 il × 8 sütun 96 seri → 12 çekim.
5. **Gold: 3 → 6 metrik.** Tüketici kredisi kırılımı (konut/taşıt/ihtiyaç/kart, aylık),
   takipteki kırılımı, kur + AOFM + konut faizi aylık ortalama (join).
6. **Demo seti 5 → 127 seri** (`scripts/demo_acceptance.py`): 20 aylık kalem, haftalık konut,
   10 EVDS, 12 ilin 8'er FinTürk sütunu; ~43 çekim grubu.
7. **Alınmayanlar, sebebiyle.** BDDK haftalık ek kalemleri (konumsal kimlik canlı gözlem
   ister, `docs/sources/bddk_weekly.md`), KOBİ kredileri (toplam sütunu doğrulanmadı), EVDS
   üretilmiş bloğun `unknown` serileri (Gold onları rızasız birleştirmez, doğru).

## Ölçüm (13 Eylül, sıfırdan kurulum, `demo_acceptance.py --fresh`)

| Adım | Süre | Sonuç |
|---|---|---|
| bootstrap | 2 s | 2.214 katalog serisi (BDDK aylık 20, haftalık 1, FinTürk 648, EVDS 1.545) |
| ingest (canlı) | **197 s** | 127/127 seri; artifact: aylık 20, haftalık 1, EVDS 10, FinTürk 264 (12 il × 22 çeyrek; 96 seri 12 çekimte) |
| silver | 2 s | **8.290 satır**, 8.290 yayımlandı, tutulan yok |
| gold | 1 s | 6 tablo, red 0 (kırılım 66 ay, takipteki kırılımı 66 ay, kur+faiz 67 ay, konut çeyreklik 22, aylık-haftalık 66, konut faizi 67) |

İki kaçak ölçülüp kapatıldı: (1) rasyoların "(%)" kolon birimi Silver'ın incelenmiş birim
tablosunda yoktu (`% → pct` eklendi, test); (2) bir ilin 8 serisi tek çekimte gelince Bronze
satırları o çekimin `dataset_id`'sini taşıyor, Silver katalogla birebir istiyor → 7 yeni
sütunun serileri ilin konut girdisiyle aynı `dataset_id`'yi aldı (ad tarihsel, `docs/sources/
bddk_finturk.md`).

**Senaryolar (genişletilmiş DB):** 11 kabul senaryosu ilk koşuda 10/11; düşen G17'de model kartın
uyarısına rağmen nedensellik dili kullandı ve panel "p < 0,05" eşiğini "tabloda yok" saydı. Üç
düzeltme (Unicode eksi "−0,54" ASCII'ye çevrilir; olumsuzlanmış nedensellik iddia sayılmaz,
iddia için ikinci geri gönderme; eşik 0,05 kart parametresi) sonrası G17 **3/3**, G9 3/3, G12
(Van iline taşındı: 12 il yüklü, Van yüklü değil) **2/2**. Adım sayıları arttı (G1 1 → 3,
G14 4 → 8, G10 2 → 6): 2.214 serilik katalogda model daha çok arıyor; araç kapısı ve ön-yükleme
ayarı sıradaki iş.

## Açık kalan
- 81 ilin tamamı için FinTürk çekimi (1.782 istek) yapılmadı; katalog hazır, `--only` ile
  istendiğinde çekilir.
- Katalog artık 2.214 seri: ön-yükleme kartları BM25 ile seçiliyor, "aylık soruya çeyreklik
  tablo" gibi yanlış ilk seçimler guard'larla dönüyor; araç kapısı (soruya göre araç alt kümesi)
  hâlâ bekliyor.
