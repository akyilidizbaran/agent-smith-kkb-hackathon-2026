"""Geliştirme adaptörü: LakehouseClient'ın DuckDB üzerinde uygulaması.

Veri ekibi kendi Lakehouse'unu bitirdiğinde bu dosyanın yerine kendi adaptörleri
gelir; agent katmanında TEK SATIR değişmez. Contract'ın varlık sebebi budur.

Güvenlik modeli — veri ekibinin ilkesiyle aynı: SQL guard hiçbir zaman tek
bariyer değildir. Üç katman:
  1. Bağlantı sertleştirmesi: read_only + enable_external_access=false +
     lock_configuration=true. DuckDB'de bu ayarlar tek yönlüdür; bağlantı
     açıldıktan sonra geri açılamaz.
  2. Parser düzeyi: duckdb.extract_statements ile tek ifade zorunluluğu ve
     ifade türünün SELECT olması.
  3. Sözcüksel guard: dış erişim fonksiyonları ve DDL/DML anahtar kelimeleri.
Ekip incelemesinde read_csv_auto('...') ve "SELECT 1; SELECT 2" geçiyordu;
o yüzden 1 ve 2 eklendi, 3 genişletildi.
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

# Agent'ın ürettiği SQL için bağlantı yapılandırması. lock_configuration en sonda
# kilitlenir; sonrasında hiçbir SET çalışmaz.
HARDENED_CONFIG: dict[str, str] = {
    "enable_external_access": "false",
    "lock_configuration": "true",
}

# Katman 3: veri değiştiren ifadeler + dış dosya/ağ erişimi. Bağlantı zaten
# bunları engeller; guard, hata mesajının modele okunabilir olması ve
# savunma derinliği için durur.
_FORBIDDEN = re.compile(
    r"\b("
    r"INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|ATTACH|DETACH|COPY|EXPORT|IMPORT|"
    r"INSTALL|LOAD|PRAGMA|SET|RESET|CALL|VACUUM|CHECKPOINT|"
    r"read_csv(?:_auto)?|read_parquet|parquet_scan|read_json(?:_auto|_objects)?|"
    r"read_text|read_blob|read_ndjson(?:_auto|_objects)?|sniff_csv|glob|"
    r"httpfs|http_get|s3_|azure_|gcs_"
    r")\b",
    re.IGNORECASE,
)


def hardened_connection(path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Agent SQL'i için sertleştirilmiş bağlantı açar (dosya ya da bellek içi).

    Aynı yapılandırma hem adaptörde hem workspace_compute_column'da kullanılır,
    böylece modelin SQL çalıştırabildiği iki yol da aynı sınırlara sahip olur.
    """
    if path is None:
        con = duckdb.connect(config=HARDENED_CONFIG)
    else:
        con = duckdb.connect(str(path), read_only=True, config=HARDENED_CONFIG)
    verify_hardened(con, require_read_only=path is not None)
    return con


def verify_hardened(con: duckdb.DuckDBPyConnection, *, require_read_only: bool) -> None:
    """Bağlantının gerçekten sertleştirilmiş olduğunu DuckDB'nin kendi ayarlarından doğrular.

    Yapılandırma dict'inin sessizce yok sayılması ihtimaline karşı: guard'a
    güvenmeden önce ayarları okuyoruz.
    """

    def setting(name: str) -> Any:
        return con.execute("SELECT current_setting(?)", [name]).fetchone()[0]

    if require_read_only and setting("access_mode") != "read_only":
        raise LakehouseError("Adaptör bağlantısı read_only değil.")
    if setting("enable_external_access") is not False:
        raise LakehouseError("Adaptör bağlantısında enable_external_access kapalı değil.")
    if setting("lock_configuration") is not True:
        raise LakehouseError("Adaptör bağlantısında lock_configuration açık değil.")


def guard_sql(sql: str) -> str:
    """Tek, salt-okunur SELECT/WITH ifadesi olduğunu doğrular; aksi halde LakehouseError.

    Sırayla: (a) parser ile ifade sayısı ve türü, (b) sözcüksel yasak liste.
    Parser önce çalışır ki "SELECT 1; DROP ..." gibi girdiler sözcüksel
    guard'ı geçse bile ifade sayısından yakalansın.
    """
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise LakehouseError("Boş sorgu.")
    try:
        statements = duckdb.extract_statements(text)
    except duckdb.Error as exc:
        raise LakehouseError(f"SQL ayrıştırılamadı: {exc}") from exc
    if len(statements) != 1:
        raise LakehouseError(
            f"Tek bir sorgu bekleniyor, {len(statements)} ifade geldi. "
            "İfadeleri ';' ile birleştirme."
        )
    stmt_type = str(statements[0].type)
    if "SELECT" not in stmt_type.upper():
        raise LakehouseError(
            f"Sadece okuma sorgularına izin verilir (SELECT/WITH); gelen: {stmt_type}."
        )
    if m := _FORBIDDEN.search(text):
        raise LakehouseError(
            f"'{m.group(0)}' bu bağlamda kullanılamaz: veri değiştiren ifadeler ve "
            "dış dosya/ağ erişimi reddedilir."
        )
    return text


class DuckDBLakehouse:
    """Tek dosyalık DuckDB + JSON katalog."""

    def __init__(self, db_path: str | Path, catalog_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path)
        self.catalog_path = Path(catalog_path) if catalog_path else self.db_path.parent / "catalog.json"
        if not self.db_path.exists():
            raise LakehouseError(
                f"Lakehouse bulunamadı: {self.db_path}. Önce `python scripts/dev_seed.py` çalıştırın."
            )
        self._con = hardened_connection(self.db_path)
        self._catalog: dict[str, DatasetSpec] = self._load_catalog()

    def close(self) -> None:
        con = getattr(self, "_con", None)
        if con is not None:
            con.close()
            self._con = None  # type: ignore[assignment]

    def reload(self) -> None:
        self.close()
        self._con = hardened_connection(self.db_path)
        self._catalog = self._load_catalog()

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

        Bilinçli olarak basit: embedding geldiğinde bu metot semantik/hibrit
        aramaya geçer, arayüz aynı kalır, agent etkilenmez (ADR-0015).
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
        text = guard_sql(sql)
        # Satır sınırı motorda uygulanır: büyük sonucu belleğe alıp sonra kırpmak yerine.
        bounded = f"SELECT * FROM ({text}) AS _q LIMIT {int(max_rows) + 1}"
        started = time.perf_counter()
        try:
            # Her sorgu kendi imlecinde; gerekçe silver_lakehouse.execute_sql'de.
            df = self._con.cursor().execute(bounded).fetch_df()
        except Exception as exc:
            raise LakehouseError(f"SQL çalıştırılamadı: {exc}") from exc
        duration = (time.perf_counter() - started) * 1000

        warnings: list[str] = []
        if len(df) > max_rows:
            warnings.append(f"Sonuç {max_rows} satırdan uzun, ilk {max_rows} satıra kırpıldı.")
            df = df.head(max_rows)

        used = [ds_id for ds_id in self._catalog if ds_id in text]
        specs = [self._catalog[i] for i in used]
        return QueryResult(
            data=df,
            provenance=QueryProvenance(
                sql=text,
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

    def series_sql(
        self,
        dataset_id: str,
        *,
        key_column: str,
        value_column: str,
        filter_column: str | None = None,
        filter_value: str | None = None,
    ) -> str:
        """Bu yerleşimde `dataset_id` doğrudan tablo adıdır."""
        spec = self.get_dataset(dataset_id)
        valid = {c.name for c in spec.columns}
        for field, name in (("key_column", key_column), ("value_column", value_column),
                            ("filter_column", filter_column)):
            if name and name not in valid:
                raise LakehouseError(
                    f"{field}='{name}' {dataset_id} tablosunda yok. "
                    f"Mevcut kolonlar: {', '.join(sorted(valid))}"
                )
        where = ""
        if filter_column and filter_value is not None:
            where = f" WHERE {filter_column} = '{filter_value.replace(chr(39), chr(39) * 2)}'"
        return f"SELECT {key_column}, {value_column} FROM {dataset_id}{where}"

    def health(self) -> dict[str, Any]:
        tables = self._con.execute("SHOW TABLES").fetch_df()
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "physical_tables": tables["name"].tolist() if not tables.empty else [],
            "catalog_datasets": list(self._catalog),
            "hardened": True,
        }
