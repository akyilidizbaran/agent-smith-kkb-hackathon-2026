# ADR-0073 — Architect yüklü aralık dışını kayıtlı kaynağından çeker (`ingest_source`)

**Tarih:** 14 Eylül 2026 · **Durum:** Kabul edildi · **Kaynak:** düzeltme planı K02-T12 (A30)

## Bağlam

A30 kabulü iki davranış ister: Analyst yüklü aralık dışında "yüklü değil + mevcut aralık" der; Architect gerekli dönemi
desteklenen kaynaktan çeker ve erişilemezse sebebi dürüstçe gösterir. Ajanda kayıtlı kaynaktan (BDDK, EVDS) dönem çeken bir
araç yoktu; erişim politikası "Architect ingest'iyle" diye bir yol öneriyordu ama bu yol yoktu.

## Karar

- Yalnız Architect kayıt defterinde `ingest_source` (seri kimliği, başlangıç, bitiş). Kapsam: katalogdaki (yüklü ya da
  yüklenmemiş) kayıtlı kaynaklı seri; adhoc ve Gold serisi kaynaktan çekilmez. Politika: geçerli tarih aralığı ve bu turun
  mesajında çekme isteği.
- Yazma veri ekibinin yüzeyinden, ayrı süreçte: `scripts/run_catalog_ingestion.py --only <seri> --start --end --report`
  (run kaydı, artifact bağı ve uyarılar korunur, ADR-0057), ardından `python -m lakehouse silver`. Okuyucu önce kapanır,
  sonunda yeniden açılır.
- Kaynak erişilemezse ya da koşu başarısızsa betiğin redakte edilmiş sebebi `ACCESS_BLOCKED` (erişim katmanı) ile döner;
  Silver yenilenmez, sahte başarı yok.
- `lakehouse_query` kapsam dışı reddi, araç kayıtlıysa "kullanıcı isterse ingest_source ile çek" ipucunu ekler.

## Sonuç

`tests/test_k02_kaynaktan_cek.py` (başarı: iki komut ve yeniden yükleme; başarısızlık: sebep, Silver yok; politika; Analyst'te
araç yok). Canlı prova `scripts/k02_a30_canli.py` ile geçici kökte.
