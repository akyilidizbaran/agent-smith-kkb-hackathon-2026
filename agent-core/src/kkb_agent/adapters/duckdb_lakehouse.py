"""Geliştirme adaptörü: LakehouseClient'ın DuckDB üzerinde uygulaması.

Veri ekibi kendi Lakehouse'unu (Parquet/Iceberg katmanları, kendi katalog
üretimi) bitirdiğinde bu dosyanın yerine kendi adaptörleri gelir; agent
katmanında TEK SATIR değişmez. Contract'ın varlık sebebi budur.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from ..contracts.catalog import DatasetSpec
from ..contracts.lakehouse import LakehouseError, QueryProvenance, QueryResult

# Salt-okunur güvence: agent'ın ürettiği SQL veriyi değiştiremez.
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|ATTACH|COPY|EXPORT|INSTALL|LOAD|PRAGMA)\b",
    re.IGNORECASE,
)


class DuckDBLakehouse:
    """Tek dosyalık DuckDB + JSON katalog."""

    def __init__(self, db_path: str | Path, catalog_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.catalog_path = Path(catalog_path) if catalog_path else self.db_path.parent / "catalog.json"
        if not self.db_path.exists():
            raise LakehouseError(
                f"Lakehouse bulunamadı: {self.db_path}. Önce `python scripts/dev_seed.py` çalıştırın."
            )
        self._con = duckdb.connect(str(self.db_path), read_only=True)
        self._catalog: dict[str, DatasetSpec] = self._load_catalog()

    def _load_catalog(self) -> dict[str, DatasetSpec]:
        if not self.catalog_path.exists():
            return {}
        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        specs = [DatasetSpec.model_validate(item) for item in raw]
        return {s.dataset_id: s for s in specs}

    # ---------- Katalog ----------
    def list_datasets(self) -> list[DatasetSpec]:
        return list(self._catalog.values())

    def get_dataset(self, dataset_id: str) -> DatasetSpec:
        spec = self._catalog.get(dataset_id)
        if spec is None:
            raise LakehouseError(
                f"'{dataset_id}' bulunamadı. Mevcut tablolar: {', '.join(self._catalog)}"
            )
        return spec

    def search_datasets(self, query: str, limit: int = 5) -> list[DatasetSpec]:
        """Anahtar kelime tabanlı skorlama.

        Bilinçli olarak basit tutuldu: Kloudeks'in embedding + reranker
        modelleri geldiğinde bu metot semantik aramaya geçecek, arayüz aynı
        kalacağı için agent etkilenmeyecek.
        """
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
        scored: list[tuple[int, DatasetSpec]] = []
        for spec in self._catalog.values():
            haystack = " ".join(
                [spec.name, spec.description, " ".join(spec.tags)]
                + [f"{c.name} {c.description} {' '.join(c.aliases)}" for c in spec.columns]
                + [v for c in spec.columns for v in c.example_values]
            ).lower()
            score = sum(haystack.count(t) for t in terms)
            if score:
                scored.append((score, spec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]] or list(self._catalog.values())[:limit]

    # ---------- Sorgulama ----------
    def execute_sql(self, sql: str, *, max_rows: int = 10_000) -> QueryResult:
        if _FORBIDDEN.search(sql):
            raise LakehouseError(
                "Sadece okuma sorgularına izin verilir (SELECT/WITH). "
                "Veriyi değiştiren ifadeler reddedilir."
            )
        started = time.perf_counter()
        try:
            df = self._con.execute(sql).fetch_df()
        except Exception as exc:
            raise LakehouseError(f"SQL çalıştırılamadı: {exc}") from exc
        duration = (time.perf_counter() - started) * 1000

        warnings: list[str] = []
        if len(df) > max_rows:
            warnings.append(f"Sonuç {len(df)} satırdı, ilk {max_rows} satıra kırpıldı.")
            df = df.head(max_rows)

        used = [ds_id for ds_id in self._catalog if ds_id in sql]
        specs = [self._catalog[i] for i in used]
        return QueryResult(
            data=df,
            provenance=QueryProvenance(
                sql=sql.strip(),
                dataset_ids=used,
                sources=[f"{s.source} — {s.source_detail or s.name}" for s in specs],
                source_urls=[s.source_url for s in specs if s.source_url],
                row_count=len(df),
                duration_ms=duration,
                warnings=warnings + [n for s in specs for n in s.notes],
            ),
        )

    def preview(self, dataset_id: str, n: int = 5) -> QueryResult:
        self.get_dataset(dataset_id)  # varlık kontrolü
        return self.execute_sql(f"SELECT * FROM {dataset_id} LIMIT {int(n)}")

    def health(self) -> dict[str, Any]:
        tables = self._con.execute("SHOW TABLES").fetch_df()
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "physical_tables": tables["name"].tolist() if not tables.empty else [],
            "catalog_datasets": list(self._catalog),
        }
