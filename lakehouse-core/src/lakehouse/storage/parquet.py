"""Generic, immutable Parquet storage for parsed batches."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..contracts.models import ParsedBatch


class ParquetConflictError(ValueError):
    """Raised when an existing path does not match the requested representation."""


@dataclass(frozen=True)
class ParquetIdentity:
    """Recoverable provenance identity embedded in every Bronze Parquet file."""

    source_id: str
    dataset_id: str
    artifact_sha256: str
    schema_version: str


def schema_version_key(schema_version: str) -> str:
    """Return a filesystem-safe deterministic key for a schema version."""

    return hashlib.sha256(schema_version.encode("utf-8")).hexdigest()


def identity_for(batch: ParsedBatch) -> ParquetIdentity:
    """Build the storage identity without changing the shared ParsedBatch contract."""

    return ParquetIdentity(
        source_id=batch.source_id,
        dataset_id=batch.dataset_id,
        artifact_sha256=batch.artifact_sha256,
        schema_version=batch.schema_version,
    )


def read_identity(path: str | Path) -> ParquetIdentity:
    """Recover provenance identity from Parquet schema metadata."""

    metadata = pq.read_schema(Path(path)).metadata or {}
    names = (
        "source_id",
        "dataset_id",
        "artifact_sha256",
        "schema_version",
    )
    values = {
        name: metadata.get(f"lakehouse.{name}".encode("utf-8"))
        for name in names
    }
    if any(value is None for value in values.values()):
        raise ParquetConflictError(f"Parquet file has incomplete lakehouse identity: {path}")
    return ParquetIdentity(
        source_id=values["source_id"].decode("utf-8"),
        dataset_id=values["dataset_id"].decode("utf-8"),
        artifact_sha256=values["artifact_sha256"].decode("utf-8"),
        schema_version=values["schema_version"].decode("utf-8"),
    )


class ParquetStorage:
    """Write and read ParsedBatch DataFrames without source-specific mapping."""

    def __init__(self, root: str | Path = Path("data/bronze")) -> None:
        self.root = Path(root)

    def path_for(self, batch: ParsedBatch) -> Path:
        """Return a deterministic Hive-style path including schema identity."""

        return (
            self.root
            / f"source_id={batch.source_id}"
            / f"dataset_id={batch.dataset_id}"
            / f"schema_version_sha256={schema_version_key(batch.schema_version)}"
            / f"artifact_sha256={batch.artifact_sha256}.parquet"
        )

    def write(self, batch: ParsedBatch, *, overwrite: bool = False) -> Path:
        """Atomically write a representation and reject identity-preserving mutation."""

        path = self.path_for(batch)
        identity = identity_for(batch)
        table = self._table_for(batch, identity)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            if not path.is_file():
                raise IsADirectoryError(path)
            try:
                existing_identity = read_identity(path)
                existing_table = pq.read_table(path)
            except Exception as exc:
                raise ParquetConflictError(
                    f"existing Parquet representation is invalid: {path}"
                ) from exc
            if existing_identity != identity or not existing_table.equals(
                table, check_metadata=True
            ):
                action = "overwrite=True cannot mutate" if overwrite else "cannot mutate"
                raise ParquetConflictError(
                    f"{action} an existing Parquet representation with the same identity: {path}"
                )
            return path

        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            pq.write_table(table, temporary_path)
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return path

    def register_local_parquet(
        self,
        connection: duckdb.DuckDBPyConnection,
        path: str | Path,
        relation_name: str,
    ) -> None:
        """Register a validated local Bronze file for trusted internal queries."""

        if not relation_name.isidentifier():
            raise ValueError("relation_name must be a valid Python-style identifier")
        candidate = Path(path).resolve(strict=True)
        root = self.root.resolve()
        if root != candidate and root not in candidate.parents:
            raise ValueError("Parquet path must be inside the configured storage root")
        connection.register(relation_name, self.read(candidate))

    @staticmethod
    def _table_for(batch: ParsedBatch, identity: ParquetIdentity) -> pa.Table:
        table = pa.Table.from_pandas(batch.dataframe, preserve_index=False)
        metadata = dict(table.schema.metadata or {})
        metadata.update(
            {
                b"lakehouse.source_id": identity.source_id.encode("utf-8"),
                b"lakehouse.dataset_id": identity.dataset_id.encode("utf-8"),
                b"lakehouse.artifact_sha256": identity.artifact_sha256.encode("utf-8"),
                b"lakehouse.schema_version": identity.schema_version.encode("utf-8"),
            }
        )
        return table.replace_schema_metadata(metadata)

    @staticmethod
    def read(path: str | Path) -> pd.DataFrame:
        """Read a Parquet artifact back into a pandas DataFrame."""

        return pq.read_table(Path(path)).to_pandas()


__all__ = [
    "ParquetConflictError",
    "ParquetIdentity",
    "ParquetStorage",
    "identity_for",
    "read_identity",
    "schema_version_key",
]
