# ADR-0070 — Kanıt zinciri gerçek dosya durumuyla: canlı halka durumu

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** bağımsız kontrol R06 → düzeltme D06 (M13-T09, A23) ·
**Değiştirdiği:** ADR-0033/ADR-0063'teki `file_present` anlamı

## Bağlam

`file_present`, dolu `bronze_path` varsa diske bakmadan `True` dönüyordu. RAW yokken Bronze tek başına zinciri "tam"
gösteriyordu; panel kurulduktan sonra Bronze silinse de aynı nesne yeşil kalıyordu.

## Karar

- **Yol metni ile durum ayrı.** `raw_path`/`bronze_path` kayıttan; `raw_present` (dosya + okunabilir) ve `bronze_present` her
  okumada diskten canlı; RAW sha256 denetimi kurulumda yapılır (`raw_digest_ok`) ve `checked_at` ile taşınır; önbellek
  anahtarı (yol, boyut, mtime).
- **Halka durumu (`chain_state`):** `tam` (RAW var, okunur, özet tutar, Bronze var) · `ham kaynak (RAW) eksik, işlenmiş veri
  (Bronze) var` · `ham kaynak var, işlenmiş dosya (Bronze) eksik` · `RAW baytları kayıtlı özetle uyuşmuyor` · `RAW var ama
  özeti denetlenmedi` · `RAW ve Bronze dosyası yok`. `file_present` yalnız `tam`.
- **Kaynak türüne göre:** Silver/adhoc gözlemi bu halkaları ister; web/belge tablosu zinciri sayfa baytının URL + sha256 + zamanı
  ile biter (değişmedi).
- **Rozetler bağımsız:** dosya zinciri rozeti yalnız bu durumlara ve kayıt eksikliğine bakar; sayısal doğruluk ve sorgu izi
  etkilenmez. Panel özeti ve boşluk listesi eksik halkayı adıyla yazar; arayüz yükü gözlem başına durumu ve dağılımı taşır;
  HTML rapor boşluk listesinden aynı cümleyi alır.

## Sonuç

`tests/test_d06_zincir.py`: altı durum, panel kurulduktan sonra silinen dosya, RAW silinmiş gerçek adaptör vakasında boşluk,
arayüz yükü ve metin. Kanıt fikstürü gerçek sha256'lı RAW dosyasına geçti.
