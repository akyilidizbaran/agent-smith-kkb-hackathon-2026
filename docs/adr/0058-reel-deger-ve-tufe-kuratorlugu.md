# ADR-0058: Reel değer deterministik araçta; TÜFE 2025=100 küratörlüğü; baz birleştirme yok

**Durum:** Kabul edildi · **Tarih:** 2026-09-14 · **Milestone:** M09

## Bağlam
Transkript 17:04: "tabloyu bozmadan konut kredisi tutarlarını enflasyondan arındır". Bugüne kadar model bunu
`workspace_compute_column` ile elle formül yazarak yapmak zorundaydı (baz, endeks hizası, sıfır/boş denetimi yok).
Canlı prova (14 Eylül): arama yüklü TÜFE serisini bulamadı; seri katalogda "Genel Endeks" adıyla, takma adsız ve
yanlış etiketle (`konut`) duruyordu; model yüklü olmayan eski TÜFE'yi seçip "yüklenmemiş" dedi.

## Karar
1. **`workspace_real_value`** (Analyst yeteneği, kalıcı yazma yok, T11): `reel_t = nominal_t × endeks(baz) / endeks(t)`.
   Endeks serisi katalogda ölçüm tipi INDEX olmalı; baz dönem (`YYYY-MM`) endeks kapsamında olmalı (değilse
   `OUT_OF_COVERAGE` + kapsam); endeks aylık olmalı; aktif tabloda aynı aya düşen birden çok satır varsa önce aylık
   hizalama istenir; sıfır/boş endeks satırı boş kalır ve sayılır (T05, T06, T08).
2. **Girdi görünür:** endeks değerleri ayrı kolon olarak eklenir (gerçek SQL provenance'ı); reel kolon formül, baz değeri,
   endeks ve nominal kolonun dataset kimliklerini taşır (M13-T06 lineage).
3. **Adaylar anlamdan:** seri bulunamazsa aday listesi metin aramasından değil, yüklü ve ölçüm tipi INDEX olan serilerden
   gelir (alan bilgisi yok).
4. **Katalog:** `evds:TP.TUKFIY2025.GENEL` adı, açıklaması (2025=100, 2021-01 = 16,13, TP.FG.J0 ile aynı bazda değil,
   birleştirilmez), takma adları ve etiketleri düzeltildi; veri ve anlam alanları (birim, ölçüm tipi, frekans) değişmedi.
5. **Farklı bazlı endeksler birleştirilmez** (T06): tek endeks serisi; kapsam dışı dönem boş kalır.

## Mevcut davranışla kapanan görevler
- T01–T04: `align_frequency` (stokta dönem sonu, akımda toplam, oranda ortalama; kabadan inceye üretim yok,
  `FREQUENCY_MISMATCH`), `decompose_cumulative` (stok seride ret), `join_on_period` (dış birleştirme, kapsam farkı görünür).
- T09–T10: Gold defteri (`meta.gold_build`) Silver parmak izi taşır, adaptör bayat tabloyu işaretler; reddedilen metrik
  önceki tabloyu **düşürür** ve ret nedenini kaydeder, katalogdan çıkan metriğin tablosu silinir (`gold/build.py`).

## Sonuçlar
- Testler `tests/test_m09_reel_deger.py` (A04). Canlı doğrulama 2016 kurulumu üzerinde (M16).
