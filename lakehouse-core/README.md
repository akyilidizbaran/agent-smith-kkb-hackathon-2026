# kkb-agentic-analytics

Python 3.12 tabanli, local-first ve generic bir data lakehouse temelidir.
Phase 0.5 ortak contract'lari; dis kaynak erisimi, immutable RAW artifact saklama ve
offline parser akisini tanimlar. Gercek kaynak connector'lari, Silver/Gold donusumleri
ve agent katmani bu phase'in disindadir.

## Ortak komutlar

```text
uv sync
make test
make build
make demo-check
```

## Klasor yapisi

- `src/lakehouse/`: Ortak Python namespace'i.
- `src/lakehouse/connectors/`: Dis kaynak erisim contract'lari.
- `src/lakehouse/parsers/`: RAW artifact -> pandas DataFrame contract'lari.
- `src/lakehouse/storage/`: Content-addressed RAW storage yardimcilari.
- `src/lakehouse/contracts/`: Paylasilan dataclass, identifier ve type contract'lari.
- `src/lakehouse/quality/`, `catalog/`, `provenance/`, `semantics/`, `tools/`: Gelecek fazlar icin bos sinirlar.
- `data/raw/`: Degismez ham artifact'lar.
- `data/bronze/`, `data/silver/`, `data/quarantine/`: Nihai mimarinin sonraki veri alanlari.
- `models/silver/`, `models/gold/`: Gelecekteki SQL modelleri.
- `schemas/`: Veri semasi contract'lari.
- `tests/fixtures/raw/`: Agsiz, kucuk ve secretsiz test fixture'lari.
- `docs/`: Takim ve contract dokumantasyonu.

Eski `src/connectors/`, `src/parsers/`, `src/storage/` ve `src/contracts/` yollarinda yalnizca
geriye donuk import shim'leri bulunur; asil kod `src/lakehouse/` altindadir.
