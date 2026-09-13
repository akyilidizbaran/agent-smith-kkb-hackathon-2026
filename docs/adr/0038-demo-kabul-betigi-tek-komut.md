# ADR-0038: Demo kabul betiği — tek komutla sıfırdan lakehouse ve sekiz senaryo

**Durum:** Kabul edildi (D4) · **Tarih:** 2026-09-12 · **Sıradaki:** E kapanış (main'e birleştirme, dondurma)

## Bağlam
Bugüne kadar "sistem çalışıyor" iddiası golden koşularına dayanıyordu; onlar da elle
hazırlanmış bir demo veritabanına (`/tmp/kkb_demo`) bağlıydı. Demo günü sorusu başka:
**sıfırdan** bir makinede, gerçek kaynaklardan çekilen veriyle, tek komutla aynı sonuç
alınıyor mu? Yol haritası D4: bootstrap → ingest → silver → gold → 8 senaryo, commit'li,
tek komut.

## Karar
`agent-core/scripts/demo_acceptance.py`:

```
uv run python scripts/demo_acceptance.py --root /tmp/kkb_demo_acceptance --fresh
uv run python scripts/demo_acceptance.py --skip-ingest --reuse-db <yol>     # yalnız senaryolar
```

1. Veri ekibinin komutları ayrı süreçte, sırayla: `python -m lakehouse bootstrap`,
   `scripts/run_catalog_ingestion.py --only <5 seri>`, `python -m lakehouse silver`,
   `python -m lakehouse gold`. Agent paketi lakehouse-core'u import etmez (ADR-0024).
2. Demo serileri sabit ve beş: aylık ve haftalık konut stoku (BDDK), haftalık konut faizi
   (EVDS), İstanbul ve Ankara konut kredisi (FinTürk). Ölçüldü: canlı çekim **26 s**.
3. Jüri dosyası ve web fikstürleri (`konut_test.csv`, `tufe_*.html`) izinli köke kopyalanır;
   ortam değişkenleri (`LAKEHOUSE_PATH`, `LAKEHOUSE_CORE_DIR`, `INGEST_ALLOWED_ROOT`,
   `CHART_DIR`) kabul köküne işaret eder.
4. Sekiz senaryo golden koşucusunun **kendisiyle** koşar (aynı denetimler: tablo, araç yolu,
   kanıt zinciri, adım, token): G1 tek değer, G2 aylık seri, G14 tabloyu bozmadan Gold
   sütunu, G8 ingest, G9 Gold + red, G10 grafik, G11a web, G13 enjeksiyon.
5. JSON rapor (`acceptance_report.json`) ve çıkış kodu (0 yalnız 8/8).

**Güvenlik kilidi.** İlk deneme, veri ekibinin katalog betiğine `--only` seçeneği eklenmeden
koştu; betik seçeneği tanımadığı için 1.620 aktif serinin tamamını canlı çekmeye başladı ve
durduruldu (23 MB RAW/Bronze, silindi). Kabul betiği artık `--help` çıktısında `--only`
görmezse filtresiz ingest'i **çalıştırmayı reddeder**. Betiğe seçenekler eklendi
(`--database`, `--data-root`, `--only`; varsayılan davranış aynı) — `feature/lakehouse-
integration-r3` `c07f73a`.

**G6 yerine G14.** G6 ("taşıt kredisini sütun olarak ekle") seed'e özgü: taşıt serisi demo
veritabanında yüklü değil, agent doğru olarak "yüklenmemiş" deyip durdu ve vaka düştü.
Gerçek DB provası G14: aylık konut tablosuna Gold'un aylık ortalama faiz tablosundan sütun
ekleme — dönem sonu anahtarı birebir örtüşür, iki kaynaktan tek tablo, kanıt zinciri her
iki kaynağa iner. 3/3, 4 adım.

## Ölçüm (12 Eylül, sıfırdan)

| Adım | Süre | Sonuç |
|---|---|---|
| bootstrap | 1 s | 1.620 katalog serisi |
| ingest (canlı) | 26 s | 5/5 seri, 14 ekstra kalem Silver'da `not in meta.series` ile tutuldu |
| silver | 1 s | 684 satır, 5 seri |
| gold | 1 s | 3 tablo (22 çeyrek, 66 ay birleşim, 67 ay faiz), red 0 |
| 8 senaryo | ~55 s | **8/8**, kanıt zinciri 8/8 tam, 1–4 adım, 17–56 bin prompt token |

Birim testleri 250 → 252 (komut planı deterministik; senaryo kimlikleri golden'da).

## Açık kalan
- EVDS anahtarı `lakehouse-core/.env`'den okunuyor (veri ekibinin `_env` yükleyicisi);
  betik anahtarın varlığını önden denetlemiyor, yokluğu ingest adımında görünür.
- Ağ yoksa `--skip-ingest --reuse-db` ile yalnız senaryolar koşar; ağsız tam kurulum için
  fixture'lardan Bronze üretme yolu yazılmadı.

## İlgili
ADR-0007/0008 (golden ve kararlılık), ADR-0024, ADR-0030 (CLI sınırı), ADR-0037 (kararlılık ölçümü).
