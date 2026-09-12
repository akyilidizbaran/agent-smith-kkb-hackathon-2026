# ADR-0033: Kanıt paneli — cevaptaki sayıdan kaynak baytlarına, tahminsiz

**Durum:** Kabul edildi (C2) · **Tarih:** 2026-09-12 · **Sıradaki:** C3 web erişimi

## Bağlam
Yarışmanın güven katmanı slaytı üç şey istiyor: kaynak gösterimi, izlenebilirlik, doğruluk
kontrolü. Bugüne kadar bunlar parça parça vardı: `QueryProvenance` sorgunun SQL'ini ve
serilerini taşıyordu, Silver satırı `artifact_sha256`'yı, `meta.artifact` URL'yi ve çekiliş
zamanını, Bronze parquet adında sha'yı. Ama jürinin sorusu "bu rakam nereden geliyor?"
tek bir zincir ister ve o zinciri kimse kurmuyordu. Cevaptaki "623.765" ile
`https://www.bddk.org.tr/...` arasındaki yol vardı, görünür değildi.

Mentörün de vurgusu: taranıp kullanılmayan kaynaklar cevaba değil kanıt paneline yazılır.

## Karar 1 — Zincir dört halkadır ve her halka kendi katmanından okunur
```
cevaptaki sayı → tablo hücresi → SQL (provenance) → Silver/adhoc satırı
  → artifact_sha256 → Bronze parquet → RAW dosyası → kaynak URL + fetched_at + HTTP durumu
```
- **sayı → hücre:** anlatı doğrulamanın sayı ayrıştırıcısı (`grounding.numbers_in`, tek
  kopya) cevaptaki her sayıyı tabloda arar; eşleşen hücrenin kolonu ve dönem anahtarı
  yazılır. Yıl gibi tarih parçaları dönem kolonunun yılıyla eşleşir; 1–31 arası kısa
  sayılar (gün, sıra) sayılmaz — anlatı doğrulamayla aynı eşik.
- **hücre → SQL:** kolonun workspace provenance'ı: SQL, seri kimlikleri, kaynak, uyarılar,
  çalıştırılma zamanı. Türetilmiş kolonun provenance'ı türetme ifadesidir.
- **satır → gözlem:** tablo satırının dönem değeri + provenance'taki seri ile Silver/adhoc
  gözlemi; gözlem `artifact_sha256`, `vintage_id`, `run_id` taşır. **Gold çerçeveleri**
  satırlarında zaten `artifact_sha256_list` ve `source_observation_dates` taşır; oradan
  okunur. **Gold tabloları** (`gold.*`) için adaptör istenen dönem sonlarındaki satırların
  kaynak gözlem tarihlerini alır ve katkıda bulunan Silver gözlemlerine iner — ölçüldü,
  G9'un çeyreklik tablosu üç aylık BDDK gözlemine ve tek artifact'e çözüldü.
- **gözlem → bayt:** `meta.artifact` (locator, fetched_at, http_status, raw_path) ve diskte
  `bronze/**/artifact_sha256=<sha>.parquet`. Yol diskte yoksa `None`, uydurulmaz.

Sözleşme: `contracts/evidence.py` — `EvidenceCapable` (`evidence_for_observations`,
`evidence_for_artifacts`), `LakehouseClient`'tan ayrı. Seed adaptörü sunmaz; zincir SQL'de
biter ve panel bunu "eksik halka" olarak yazar. Sunan adaptör `SilverLakehouse`.

## Karar 2 — Panel cevaptan sonra kurulur ve cevabı asla düşürmez
`core/evidence.EvidenceBuilder` cevap metni kesinleştikten sonra çalışır: soru, metin,
workspace, adımlar, grafik artefaktları → `EvidencePanel`. İnşacı patlarsa uyarı loglanır,
cevap yine döner. Panel `AgentAnswer.evidence`'ta; CLI her cevabın altında tek satır özet
basar (`[kanıt] kanıt zinciri tam: 2/2 sayı tabloda · 2 kolon → SQL · 1 gözlem → 1
artifact · çekiliş 2026-09-12`), `--evidence` tam paneli açar.

**"Tam" tanımı ölçülebilir:** her sayı bir hücrede; her kolonun SQL'i var; adaptör artifact
izi sunuyorsa her gözlem `locator + fetched_at` taşıyor; kopuk halka yok. Eksikse `gaps`
neresinin eksik olduğunu söyler: "tabloda bulunmayan sayılar: 999", "2 gözlemin
artifact/locator/fetched_at izi eksik", "adaptör artifact izi sunmuyor (seed)".

**Danışılıp kullanılmayan:** `lakehouse_describe` / `lakehouse_distinct_values` ile bakılan
ama tabloya girmeyen seriler panelde ayrı satırda. C3 ile taranan sayfalar da buraya
gelecek; cevaba değil.

## Karar 3 — Golden her vakada zinciri ölçer
Koşucu vaka satırına `evidence` durumu ekler ve sonda `KANIT ZİNCİRİ: n/m tam` basar.
Adaptör artifact izi sunuyorsa eksik zincir vakayı **düşürür**; seed'de düşürmez (artifact
yoktur), yalnız raporlanır.

## Ölçüm
- Birim testleri 201 → **208**: adaptör gözlem→artifact→RAW/Bronze (eksik artifact kaydı
  kopuk sayılır), panel sayı→hücre→SQL→gözlem, tam zincir ve tabloda olmayan sayı, Gold
  çerçevesi sha listesinden, seed'de SQL'de biten zincir, tablo yokken, agent döngüsünde
  panelin iliştirilmesi ve inşacı hatasının cevabı düşürmemesi.
- Gerçek veritabanı, CLI `--evidence`: "2025 Eylül konut kredisi" → 623.765 → `value @
  2025-09-30` → SQL → `bddk_monthly:1534_Toplam @ 2025-09-30 [bddk:10001]` → artifact
  `035c4b81…` çekildi 2026-09-12 12:36 HTTP 200 → `https://www.bddk.org.tr/BultenAylik/
  tr/Home/GelismisRaporGetir` → RAW `.json` → Bronze `.parquet`. Zincir tam.
- Golden gerçek DB: G1, G8 (adhoc taslak), G9 (Gold tablosu), G10 (grafik) — **4/4 geçti,
  KANIT ZİNCİRİ 4/4 tam**.

## Açık kalan
- Panel metin; demo arayüzü (varsa) `EvidencePanel.to_dict()`'i tıklanabilir gösterebilir.
- Grafik noktaları panele bağlı değil; her nokta kaynak gözlem tarihi taşıyor, tooltip'e
  girmedi (ADR-0032'de de not).
- `workspace_compute_column` ile türetilmiş kolonun zinciri türetme ifadesinde biter; ifade
  hangi kolonlardan türediğini söylüyor, panel onları ayrıca izlemiyor.

## İlgili
ADR-0027 (anlatı doğrulama: aynı sayı ayrıştırıcı), ADR-0031 (Gold satır provenance'ı),
ADR-0032 (grafik artefaktları). Veri ekibi: `meta.artifact`, `meta.run_artifact`, Bronze yerleşimi.
