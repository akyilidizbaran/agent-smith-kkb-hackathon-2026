"""Shared helpers for the generic and ad-hoc test suites.

Every byte in these tests is **SYNTHETIC**: written by the test itself into a temporary
directory, never taken from `tests/fixtures/raw/`, and never representing a real published
figure. Nothing here opens a socket; the HTTP tests drive a fake session that returns
prepared responses.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.generic import GenericTabularConnector, GenericTabularParser
from src.lakehouse.ingestion.pipeline import IngestionPipeline
from src.lakehouse.storage.parquet import ParquetStorage
from src.lakehouse.storage.raw import RawStorage


FETCHED_AT = datetime(2026, 9, 13, 9, tzinfo=timezone.utc)
REQUESTED_AT = datetime(2026, 9, 13, 8, tzinfo=timezone.utc)

SYNTHETIC_CSV = (
    "donem,deger,kurum\n"
    "2026-01-31,100.5,SYNTHETIC-A\n"
    "2026-02-28,,SYNTHETIC-A\n"
    "2026-03-31,120.25,SYNTHETIC-A\n"
)
"""SYNTHETIC. Round invented numbers; not a real economic series."""


# ------------------------------------------------------------- fake transport


class FakeResponse:
    """Minimal stand-in for a streamed ``requests`` response."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
        raise_on_iter: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._content = content
        self.headers = headers or {}
        self._raise_on_iter = raise_on_iter
        self.closed = False

    def iter_content(self, chunk_size: int = 65536) -> Iterable[bytes]:
        if self._raise_on_iter is not None:
            raise self._raise_on_iter
        for start in range(0, len(self._content), chunk_size):
            yield self._content[start : start + chunk_size]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Returns prepared responses in order. Never touches the network."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.requests: list[str] = []

    def get(self, url: str, **_: Any):
        self.requests.append(url)
        if not self._responses:
            raise AssertionError(f"no prepared response for {url}")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def public_resolver(_host: str) -> list:
    """Pretend every hostname resolves to one ordinary public address."""

    import ipaddress

    return [ipaddress.ip_address("93.184.216.34")]


# ------------------------------------------------------------- file factories


def write_csv(root: Path, name: str = "synthetic.csv", body: str = SYNTHETIC_CSV) -> Path:
    path = root / name
    path.write_text(body, encoding="utf-8")
    return path


def write_bytes(root: Path, name: str, payload: bytes) -> Path:
    path = root / name
    path.write_bytes(payload)
    return path


def xlsx_bytes(
    sheets: dict[str, list[list[Any]]], *, hidden: tuple[str, ...] = ()
) -> bytes:
    """Build a SYNTHETIC workbook in memory."""

    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(title=name)
        for row in rows:
            sheet.append(row)
        if name in hidden:
            sheet.sheet_state = "hidden"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def zip_bomb_bytes(uncompressed: int) -> bytes:
    """A tiny archive whose directory claims a huge uncompressed size."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", b"<Types/>")
        archive.writestr("xl/workbook.xml", b"\0" * uncompressed)
    return buffer.getvalue()


def json_bytes(document: Any) -> bytes:
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


# --------------------------------------------------------------- ingestion


def spec(
    locator: str,
    *,
    dataset_id: str = "adhoc_synthetic",
    parameters: dict[str, Any] | None = None,
) -> FetchSpec:
    return FetchSpec(
        source_id="adhoc",
        dataset_id=dataset_id,
        locator=locator,
        parameters=parameters or {},
        requested_at=REQUESTED_AT,
    )


def ingest(
    tmp_path: Path,
    fetch_spec: FetchSpec,
    *,
    allowed_local_roots: list[Any] | None = None,
    session: Any = None,
    connection=None,
    **connector_kwargs: Any,
):
    """Run the real ingestion pipeline over the generic connector and parser."""

    owned = connection is None
    connection = connection or bootstrap_database(tmp_path / "data/lakehouse.duckdb")
    pipeline = IngestionPipeline(
        connector=GenericTabularConnector(
            RawStorage(tmp_path / "data/raw"),
            allowed_local_roots=allowed_local_roots,
            session=session,
            clock=lambda: FETCHED_AT,
            **connector_kwargs,
        ),
        parser=GenericTabularParser(),
        artifact_repository=ArtifactRepository(connection),
        parquet_storage=ParquetStorage(tmp_path / "data/bronze"),
    )
    try:
        result = pipeline.run(fetch_spec)[0]
    except Exception:
        if owned:
            connection.close()
        raise
    return connection, result


SYNTHETIC_SERIES_RECORD: dict[str, Any] = {
    "series_id": "adhoc:synthetic_series",
    "native_code": "synthetic_series",
    "dataset_id": "adhoc_synthetic",
    "name_tr": "SYNTHETIC test serisi",
    "description": "SYNTHETIC. Test-only ad-hoc series; not a real economic quantity.",
    "frequency": "monthly",
    "unit": "TRY_mn",
    "measure_type": "stock",
}
"""SYNTHETIC catalog proposal, in the same shape a YAML entry uses."""
