# Lakehouse Core

> Source Access branch'inde yapılan EVDS ve BDDK çalışmalarının toplantı özeti için
> [`SOURCE_ACCESS_TOPLANTI_OZETI.md`](SOURCE_ACCESS_TOPLANTI_OZETI.md) dosyasına bakın.

Python 3.12 tabanli, local-first ve generic bir data lakehouse temelidir.
Phase 1B ortak contract'lari, gercek kaynak connector/parser akisini, immutable RAW
artifact saklamayi, Bronze Parquet'i, metadata/provenance'i ve guvenli DuckDB sorgusunu
birlikte dogrular. Silver, Gold ve agent-facing son sorgu yuzeyi henuz uygulanmadi.

## Ortak komutlar

```text
uv sync
make test
make build
make demo-check
```

## Mevcut akis

```text
Source -> Connector -> RAW -> Parser -> ParsedBatch -> Bronze Parquet
       -> Metadata / Provenance -> DuckDB -> Safe Query
```

Mevcut kaynaklar: BDDK Monthly, BDDK Weekly ve TCMB EVDS.

## Klasor yapisi

- `src/lakehouse/`: Ortak Python namespace'i.
- `src/lakehouse/connectors/`: Dis kaynak erisimi ve ham response indirme.
- `src/lakehouse/parsers/`: RAW artifact -> pandas DataFrame donusumu.
- `src/lakehouse/ingestion/`: Connector, parser ve Bronze akisi orchestration'i.
- `src/lakehouse/storage/`: Content-addressed RAW storage yardimcilari.
- `src/lakehouse/contracts/`: Paylasilan dataclass, identifier ve type contract'lari.
- `src/lakehouse/catalog/`: Artifact ve semantic series metadata kayitlari.
- `src/lakehouse/db/`, `query/`, `security/`: DuckDB bootstrap, guvenli baglanti ve SQL siniri.
- `data/raw/`: Degismez ham artifact'lar.
- `data/bronze/`, `data/silver/`, `data/quarantine/`: Nihai mimarinin sonraki veri alanlari.
- `models/silver/`, `models/gold/`: Gelecekteki SQL modelleri.
- `schemas/`: Veri semasi contract'lari.
- `tests/fixtures/raw/`: Agsiz, kucuk ve secretsiz test fixture'lari.
- `docs/`: Takim ve contract dokumantasyonu.

Eski `src/connectors/`, `src/parsers/`, `src/storage/` ve `src/contracts/` yollarinda yalnizca
geriye donuk import shim'leri bulunur; asil kod `src/lakehouse/` altindadir.

## Tamamlananlar ve sonraki faz

Tamamlananlar: base contract'lar, BDDK/EVDS source access, RAW/Bronze, semantic catalog,
artifact/request provenance, safe query ve offline integration testleri.

Siradaki faz: canonical Silver `fact_observation`; sonrasinda Gold analytical view'lar.
Detayli kararlar [docs/](docs/) altindadir; [Phase 1B](docs/phase-1b-real-source-integration.md)
ve [catalog contract](docs/catalog-contract.md) ile baslanabilir.
