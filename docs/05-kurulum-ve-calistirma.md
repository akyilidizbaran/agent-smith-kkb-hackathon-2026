# 5. Kurulum ve çalıştırma

## 5.1 Gereksinimler

| Araç | Sürüm | Not |
|---|---|---|
| Python | agent-core ≥ 3.11, lakehouse-core 3.12 | `uv` doğru sürümü kendisi indirir |
| [uv](https://docs.astral.sh/uv/) | güncel | Bağımlılıklar `uv.lock` ile kilitli |
| Google Chrome | isteğe bağlı | Yalnız JavaScript ile yüklenen sayfaları okumak için; Playwright tarayıcı indirmez, sistem Chrome'unu kullanır |
| Kloudeks (MIA) anahtarı | — | Metin, embedding ve OCR modelleri için |
| TCMB EVDS anahtarı | — | EVDS serilerini çekmek için |

## 5.2 Beş adımda çalıştırma

```bash
# 1. Bağımlılıkları kur (iki paket)
make setup

# 2. Ortam dosyasını hazırla ve anahtarları gir
cp .env.example .env         # MIA_API_KEY, EVDS_API_KEY, (isteğe bağlı) TAVILY_API_KEY

# 3. Salt-okunur ön kontrol: anahtarlar, veri kökü, lakehouse, modeller
make preflight

# 4. Veri havuzunu kur (kaynaklardan çeker; uzun sürer)
make demo-data

# 5. Arayüzü başlat → http://127.0.0.1:8765
make serve
```

`make demo-data` şu sırayla çalışır: `bootstrap` → katalog güdümlü çekim (`scripts/run_catalog_ingestion.py`) →
`silver` → `gold`. Daha hızlı bir alt küme için:

```bash
cd agent-core && uv run python scripts/build_demo_data.py --set demo
```

## 5.3 Ortam değişkenleri

`.env` yalnız yerelde durur, git'e girmez. Anahtarların değerleri hiçbir çıktıda gösterilmez.

| Değişken | Anlamı |
|---|---|
| `MIA_API_KEY` | Kloudeks anahtarı; `LLM_API_KEY` bundan alınır |
| `LLM_BASE_URL`, `LLM_MODEL` | OpenAI uyumlu uç ve metin modeli (`deepseek-ai/DeepSeek-V4.1-Flash`) |
| `EMBEDDING_MODEL`, `VISION_MODEL` | Embedding ve OCR modelleri |
| `EVDS_API_KEY` | TCMB EVDS anahtarı |
| `TAVILY_API_KEY` | Web araması; yoksa `web_search` aracı kaydedilmez |
| `DATA_ROOT`, `LAKEHOUSE_PATH` | Veri kökü ve DuckDB dosyası (varsayılan `data/`, `data/lakehouse.duckdb`) |
| `INGEST_ALLOWED_ROOT` | Architect'in okuyabileceği tek yerel kök (varsayılan `data/incoming`) |
| `AGENT_PROFILE` | Başlangıç profili: `analyst` (varsayılan) ya da `architect` |
| `PROFILE_SWITCH` | Arayüzde profil geçişi: `token` (varsayılan, Architect'e geçiş `ARCHITECT_TOKEN` ister) ya da `open` (tek tık, yalnız güvenilen demo ortamı) |
| `ARCHITECT_TOKEN` | `token` kipinde Architect'e geçiş anahtarı |
| `DOMAIN_DESCRIPTION`, `DOMAIN_AUDIENCE` | Başka bir alanla çalışırken ajanın tonunu verir |
| `TOOL_GATE` | Soruya göre araç kapısı (`on`/`off`) |
| `RETRIEVAL_MODE` | Katalog araması kademesi (`auto`, `bm25`, `hybrid`, `preload_all`) |
| `WEB_BROWSER_FALLBACK`, `BROWSER_HEADLESS`, `BROWSER_EXECUTABLE_PATH` | İsteğe bağlı gerçek tarayıcı katmanı |
| `WEB_HOST`, `WEB_PORT` | Arayüz adresi (varsayılan `127.0.0.1:8765`) |

## 5.4 Arayüzü kullanma

- **Soru sor:** doğal dilde yazın; dosya eklemek için 📎 düğmesi ya da sürükle-bırak kullanın. Çalışma sırasında her
  araç adımı canlı görünür.
- **Profil:** üst çubuktaki **Analyst | Architect** düğmesiyle tek tıkla geçilir; sohbet ve tablolar korunur.
  Architect'te dosyayı havuza kaydetme, kataloğa alma ve tam sıfırlama açılır.
- **Kanıt zinciri:** sağ panel her sayıyı hücreye, sorguya, gözleme ve kaynak dosyaya bağlar. "Yolculuğu izle" halka
  halka canlandırır. Panel başlığından açılıp kapanır.
- **Dışa aktarım:** her cevabın tablosu CSV / XLSX, cevabın tamamı kanıtıyla HTML rapor olarak indirilebilir.
- **Sohbetler:** sol menüde kalır; uygulama yeniden açılınca kaldığı yerden sürer.

## 5.5 Komut satırı

```bash
cd agent-core
uv run python -m kkb_agent.cli --trace "2025'te konut kredisi nasıl değişti?"   # adım adım iz
uv run python -m kkb_agent.cli --evidence "…"                                    # kanıt zinciri
uv run python -m kkb_agent.cli --preflight --live                               # canlı model ön kontrolü
uv run python -m kkb_agent.cli --health
```

Lakehouse komut satırı (`lakehouse-core` içinde, `uv run python -m lakehouse …`):

| Komut | Ne yapar |
|---|---|
| `bootstrap [--catalog default\|none]` | Şema ve katalog; `none` başka alan için boş katalog |
| `ingest --source --dataset --start-date --end-date` | Bir kaynaktan çekim → RAW → Bronze |
| `silver`, `gold` | Silver ve Gold tablolarını kurma |
| `gold-run --function … --series …` | Salt-okunur Gold fonksiyon çağrısı |
| `ingest-file <dosya/adres> …` | Bilinmeyen dosyayı taslak seri olarak kaydetme |
| `promote-draft --series adhoc:<anahtar>` | Taslağı kataloğa alma |

Toplu çekim ve bakım betikleri (`lakehouse-core/scripts/`):
- `run_catalog_ingestion.py --only-file … --start --end`
- `check_breakdown_sums.py`: vade kovaları toplamı = Toplam denetimi
- `generate_bddk_monthly_catalog.py`, `evds_catalog_generator.py`: katalog üreticileri

## 5.6 Başka bir alanla çalıştırma

```bash
# ayrı bir veri kökünde boş kataloglu havuz
cd lakehouse-core
uv run python -m lakehouse bootstrap --database /yol/saglik/lakehouse.duckdb --data-root /yol/saglik --catalog none

# arayüzü o köke bağla, Architect profilinde dosya yükleyip havuza kaydet
cd ../agent-core
DATA_ROOT=/yol/saglik LAKEHOUSE_PATH=/yol/saglik/lakehouse.duckdb \
DOMAIN_DESCRIPTION="hastane verileri" AGENT_PROFILE=architect uv run python -m kkb_agent.serve
```

Ajanın alan profili katalogdan türetilir; finansa özgü bir kod yolu yoktur.

## 5.7 Testler

```bash
make test        # agent-core — 1168 test, ~8 sn
make test-data   # lakehouse-core — uzun (≈13 dk)
make ci          # ikisi birden, kilitli kurulumla
```

CI: `.github/workflows/tests-agent.yml` ve `.github/workflows/tests-lakehouse.yml` (8 paralel parça). İkisi de PR'da ve
`main`'e push'ta koşar.
