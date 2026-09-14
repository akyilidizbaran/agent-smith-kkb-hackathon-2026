# Branch özeti — `feature/lakehouse-cli-catalog-fallback`

**Sahip:** Zümra Yılmaz (Claude Code ile) · **Taban:** `feature/lakehouse-catalog-breadth` (`cf3e878`)

**Amaç:** Demo senaryosunun (brief s.11) veri tarafını gerçekten cevaplanabilir hale getirmek ve
"tak-çıkar" ilkesini bozan kalan yerleri kapatmak. Hepsi kopya DB üzerinde gerçek veriyle
uçtan uca doğrulandı; orijinal `data/lakehouse.duckdb`'ye dokunulmadı.

## Neler yapıldı?

**1. CLI `ingest` artık kataloğu tanıyor** (`src/lakehouse/application.py`)
`python -m lakehouse ingest --source evds --dataset <x>` yalnız `KNOWN_SOURCES` sözlüğüne
(tek giriş: `evds_cpi`) bakıyordu; katalogda olan her başka dataset "unknown dataset" ile
reddediliyordu. Şimdi sözlükte bulunmayan dataset `catalog/series/*.yml`'den çözülür
(`native_code` + `frequency`; aynı dataset'teki seriler tek istekte `-` ile birleşir, karışık
frekans reddedilir). Sözlük "elle doğrulanmış özel durum" olarak kalır; pencereleme,
run-tracking ve uzlaştırma aynen çalışır. Katalog dosyadan okunur ki bilinmeyen dataset DB
yaratılmadan reddedilsin (mevcut test sözleşmesi). Testler: `tests/cli/test_cli.py` (+2).

**2. Senaryo verisi çekildi** (pencerelemeli CLI, `meta.run` dolu)
`evds_fx_usd` (dolar kuru, günlük, 6 pencere, 2.007 gözlem), `evds_wafc` (politika faizi,
iş günü, 1.433), `evds_cpi` (TÜFE, 61). `kur_ve_faiz_aylik` Gold metriği doldu (67 ay).

**3. 1.533 EVDS serisine anlam atandı** (`scripts/apply_evds_group_semantics.py`)
Otomatik üretilen EVDS serileri `measure_type: unknown` olduğu için Silver'a giremiyordu.
EVDS veri grubu başına bir kez incelenmiş tablo (grup → `measure_type`/`unit`/`default_agg`)
uygulandı: TÜFE alt kalemleri ve KFE'ler → `index`; konut/iş yeri satış adetleri (664) →
`flow_periodic`/`adet`; birim fiyat ve kira (152) → `stock`/`TRY_per_m2`; faiz oranları →
`rate`/`pct`. Üç "(Arşiv)" grubu (309 seri; kaynak artık üretmiyor, boş/özdeş yanıt)
`status: deprecated`. İpotekli satış payı (jüri grafiğinin 4. çizgisi) artık hesaplanabiliyor:
2021-01 %15,3 → 2026-06 %20,0.

**4. EVDS çeyreklik tarih kuralı** (`silver/adapters/_evds_time.py`, `catalog_driven.py`)
Silver, gerçek payload'la doğrulanmamış frekansı reddediyor; çeyreklik (152 seri) için kural
yoktu. Bronze'daki gerçek satırlardan okundu: `Tarih` = `YYYY-Qn`, `UNIXTIME` = çeyrek başı.
`evds_quarter_bounds` eklendi, `UNIXTIME` çeyrekle çelişirse reddeder. Testler:
`tests/silver/test_evds_quarterly_dates.py` (+3); "doğrulanmamış frekans" testi örneğini
`semiannual`'a taşıdı.

**5. Kümülatif seriler — brief'in özel notu** (`catalog/series/bddk_monthly.yml`)
Kar Zarar tablosundan iki kalem canlı ölçüldü ve **yıl içi kümülatif** olduğu kanıtlandı
(Ocak'ta sıfırlanır): Dönem Net Kârı (`194`), Toplam Faiz Gelirleri (`158`). Katalog
`flow_ytd` + `cumulative_reset: yearly`. Yeni Gold metriği `net_kar_aylik`
(`decompose_cumulative`) gerçek veride ilk kez çalıştı; 2025'in 12 aylık akımının toplamı
940.183 = kaynağın Aralık kümülatifi. Kanıt: `docs/sources/bddk_monthly.md`, "Kümülatif kalemler".

**6. Tek komutluk build** (`scripts/build_lakehouse.py`)
bootstrap → katalog runner → günlük EVDS dataset'leri için pencerelemeli CLI (frekans
kataloğdan, liste kodda değil) → silver → gold; her adım süresiyle. `--only` ile küçük demo
kurulumu ve tam kurulum aynı script. Sıfır dizinden 3 seriyle (biri günlük → pencereli yol)
ölçüm: 46 s toplam (bootstrap 10, runner 12, pencereli ingest 13, silver 6, gold 5). Tam
kurulum (1.907 seri) henüz bu script'le ölçülmedi; parça parça çekimlerden tahmin ~1 saat.

**Windows notu:** `tests/adhoc/test_end_to_end.py::test_local_csv_reaches_the_agent…` ve
`tests/contract/test_contracts.py::test_raw_path_is_deterministic…` Windows'ta bu daldan
bağımsız kırmızı (CRLF ve `\` ayırıcı); ikisine de dokunulmadı.

## Doğrulama durumu (kopya DB, 2026-09-14)

| Katman | Önce | Sonra |
|---|---|---|
| Katalog aktif seri | 2.214 | 2.216 − 309 deprecated = 1.907 |
| Silver seri / gözlem | 672 / 16.282 | **1.901 / 95.7k** |
| `measure_type: unknown` | 1.533 | **0** |
| Gold tabloları | 5/6 | **7/7** |
| Bronze `run_id` dolu | 0 | yeni çekimlerde dolu (eski 3.244 dosya hâlâ boş) |

Mantık kontrolleri: tüketici kredisi kırılımı toplamı = resmi toplam (3.401.614); kümülatif
ayrıştırma toplamı = kaynak; çeyreklik dönem sınırları gerçek `UNIXTIME` ile uyumlu.

## Bilinen eksikler

- Eski Bronze dosyalarında `run_id` boş (run-tracking öncesi çekim) — yeniden ingest ile dolar.
- BDDK haftalık bültenden ek kalem yok (konumsal kimlik, her biri canlı doğrulama ister).
- Otomatik EVDS serilerinin `aliases`/`tags` hâlâ şablon — agent retrieval'ı için zayıf.
- `_WEEKLY_VERIFIED_POSITIONS` ve `DEFAULT_START/END` hâlâ kodda.
- Reel dönüşüm (TÜFE ile arındırma) için Gold fonksiyonu yok; agent tarafında hesaplanıyor.
- Hangi DB dosyasının deploy'a gideceği (tam çekim / 127'lik demo seti) takım kararı.
