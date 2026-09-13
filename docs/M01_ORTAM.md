# M01 — Tek ve tekrar kurulabilir yerel çalışma ortamı

**Tarih:** 13 Eylül 2026 · **ADR:** 0049 · **Durum:** kurulum tarifi ve ön kontrol hazır; canlı veri kurulumu ve arkadaş provası bu belgenin sonunda kaydedilir.

## 1. Sabitlenen sürümler (T01)

| Parça | Kaynak | Sürüm |
|---|---|---|
| Agent | `feature/agent-engine` (bu dal) | bu belgeyi taşıyan commit |
| Veri kodu | `origin/feature/lakehouse-catalog-breadth` → `lakehouse-core/` (ağaç anlık görüntüsü, tarihçe veri dalında) | `cf3e878` |
| Motor | MIA `kkbhackathon2026/Qwen3.8-27B` (LLM), `Qwen3-Embedding-8B`, `Unlimited-OCR` | .env |

catalog-breadth bu hattın başlangıç veri tabanıdır; takımın son ortak kararı olduğu iddia edilmez. Veri dalı ilerlerse `agent-core/scripts/sync_lakehouse_core.sh` ile yeniden alınır ve sha burada güncellenir.

## 2. Dizin düzeni (T02, T04)

```
KKB/                      repo kökü — .env burada (gizli değerler yalnız burada)
├─ agent-core/            ajan (uv, Python ≥3.11)
├─ lakehouse-core/        veri ekibi kodu (uv, Python 3.12) — anlık görüntü
├─ data/                  DATA_ROOT (gitignore): lakehouse.duckdb, raw/, bronze/, incoming/, charts/, cache/
└─ docs/, Makefile
```

Yol değişkenleri (.env.example'da): `DATA_ROOT`, `LAKEHOUSE_PATH`, `LAKEHOUSE_MODE`, `LAKEHOUSE_CORE_DIR`, `LAKEHOUSE_CLI`, `INGEST_ALLOWED_ROOT`, `CHART_DIR`, `GEO_DIR`. Göreli yollar **repo köküne** göre çözülür (önceden agent-core'a göreydi; `LAKEHOUSE_PATH=data/lakehouse.duckdb` artık `KKB/data/…` demektir). Varsayılanların hepsi DATA_ROOT altında; hiçbir yol geçici dizine bakmaz.

## 3. Modlar (T05)

| `LAKEHOUSE_MODE` | Davranış |
|---|---|
| `demo` (varsayılan) | Silver şeması şart. DB yoksa ya da dosya seed ise açık nedenle **durur**, seed'e düşmez. |
| `seed` | Geliştirme seed'i (`scripts/dev_seed.py`). Arayüz başlığında görünür. |
| `auto` | Silver'ı dene, yoksa seed. Yalnız testler ve eski davranış için. |

## 4. Komutlar (T03, T06, T07)

```bash
make setup        # iki ortamı kilit dosyalarıyla kur
make preflight    # SALT-OKUNUR ön kontrol; hiçbir şey indirmez/yazmaz
make demo-data    # VERİ DEĞİŞTİRİR: bootstrap → canlı ingest (demo serileri) → silver → gold → fikstürler
make serve        # arayüz
make test         # agent testleri
```

Ön kontrol (`python -m kkb_agent.cli --preflight [--live]`) şunları söyler: mod; veri kökü; DB dosyası; şema (meta.series, silver.fact_observation); katalog/yüklü seri, gözlem sayısı ve tarih aralığı; gold tabloları; provenance kayıtları (artifact/run); RAW/Bronze dizinleri; lakehouse-core ve CLI'ın gerçekten çalıştığı; izinli dosya kökü; grafik dizini; model ve anahtarların yalnız var/yok durumu. `--live` MIA'ya beş token'lık bir deneme çağrısı yapar. Zorunlu bir kontrol düşerse çıkış kodu 1.

`make demo-data` mevcut DB'yi ancak `--fresh --yes` ile siler ve silinecekleri önce listeler; `--only` ile seri listesi daraltılır. Bütün kataloğu (2.214 seri) canlı çekmek bu komutun işi değildir.

## 5. Temiz kurulum provası (T08)

Adımlar: `git clone` → `make setup` → `.env` (örnekten) → `make preflight` (DB yok: "HAZIR DEĞİL — veritabanı" beklenir) → `make demo-data` → `make preflight` (hazır) → `make serve`.

Bilinen terminal bağımlılıkları: yok. Gizli override: yok; tüm yollar .env'de.

**Kayıt:** (arkadaş provası tarih/sonuç buraya yazılır)
