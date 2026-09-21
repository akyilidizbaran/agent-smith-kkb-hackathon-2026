"""Catalog-driven real ingestion: fetch every active series meta.series knows
about, generically, with zero per-series code in this file.

The list of series is NOT hardcoded here — it is read from meta.series (the
catalog loaded from catalog/series/*.yml by bootstrap_database()). Adding a
new series to a catalog YAML and re-running bootstrap makes it show up here
automatically. What each source needs to build a real FetchSpec lives in
ingestion_registry.py, keyed by source_id, not by series.

This is a manual validation/ingestion utility, NOT wired into CI or the
Makefile. Run it on demand, by hand.

Usage (from lakehouse-core/, with DBeaver disconnected from
data/lakehouse.duckdb):

    uv run python scripts/run_catalog_ingestion.py
"""

from __future__ import annotations

import truststore

truststore.inject_into_ssl()

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _env import load_dotenv_simple

load_dotenv_simple(_REPO_ROOT)

from ingestion_registry import CONNECTOR_REGISTRY, SeriesRow

from src.lakehouse.catalog.artifacts import ArtifactRepository
from src.lakehouse.contracts.identifiers import new_run_id
from src.lakehouse.ingestion.observability import (
    RUN_STATUS_FAILED,
    RUN_STATUS_SUCCESS,
    RUN_STATUS_WARNING,
    IngestionWarning,
    RunArtifactLink,
    RunRepository,
    describe_exception,
)
from src.lakehouse.contracts.models import FetchSpec
from src.lakehouse.db.bootstrap import bootstrap_database
from src.lakehouse.errors import ErrorPayload, LakehouseError
from src.lakehouse.ingestion.windowing import plan_evds_windows, windowed_fetch_specs
from src.lakehouse.storage.parquet import ParquetConflictError, ParquetStorage
from src.lakehouse.storage.raw import RawStorage

# Yüklü kapsam (M00 K04, 14 Eyl): 2016-01'den itibaren; istenen başka dönem --start/--end ile.
DEFAULT_START = date(2016, 1, 1)
DEFAULT_END = date(2026, 6, 30)

# BDDK aylık bülten: bir kalemin şeması değişince kimliği de değişir ve eski aylar eski kimlikte kalır
# (21 Eyl ölçümü: 2021 başından sonra başlayan 70 serinin 63'ü). Bu dosya seri → eski kimlik → dönem
# penceresi eşlemesidir; pencereler örtüşmez (geçiş ayı yalnız yeni kimlikten alınır).
HISTORY_FILE = _REPO_ROOT / "catalog" / "bddk_monthly_history.yml"   # catalog/series/ altında değil: o klasörün her dosyası seri kataloğu sayılır


@dataclass(frozen=True)
class HistoryWindow:
    series_id: str
    native_code: str
    start: date
    end: date


def load_history(path: Path | None = None) -> dict[str, list[HistoryWindow]]:
    """series_id → its older schema ids with the months each one answers for. Missing file → {}."""
    path = HISTORY_FILE if path is None else path       # çağrı anında okunur: test dosyayı değiştirebilir
    if not path.is_file():
        return {}
    import yaml

    entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out: dict[str, list[HistoryWindow]] = {}
    for entry in entries:
        window = HistoryWindow(
            series_id=str(entry["series_id"]), native_code=str(entry["native_code"]),
            start=entry["start"] if isinstance(entry["start"], date) else date.fromisoformat(str(entry["start"])),
            end=entry["end"] if isinstance(entry["end"], date) else date.fromisoformat(str(entry["end"])),
        )
        if window.start > window.end:
            raise ValueError(f"{path.name}: {window.series_id} {window.native_code}: start after end")
        out.setdefault(window.series_id, []).append(window)
    for series_id, windows in out.items():
        windows.sort(key=lambda w: w.start)
        for earlier, later in zip(windows, windows[1:]):
            if earlier.end >= later.start:
                raise ValueError(f"{path.name}: {series_id}: windows of {earlier.native_code} and "
                                 f"{later.native_code} overlap; the transition month belongs to one id only")
    return out


def history_rows(row: SeriesRow, windows: list[HistoryWindow], start: date, end: date) -> list[tuple[SeriesRow, date, date]]:
    """The extra fetches a series needs inside the requested window: (row with the old id, start, end)."""
    key = row.series_id.split(":", 1)[1] if ":" in row.series_id else row.series_id
    out = []
    for w in windows:
        lo, hi = max(w.start, start), min(w.end, end)
        if lo > hi:
            continue
        out.append((SeriesRow(row.series_id, row.source_id, w.native_code, row.dataset_id, row.name_tr, series_key=key), lo, hi))
    return out


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# EVDS tek istekte en çok 1.000 gözlem döndürür ve fazlasını SESSİZCE kırpar (bitiş tarihinden geriye sayar).
# Ölçüldü (14 Eyl, 2016+ kurulum): günlük kur ve fonlama serileri tek pencereyle istendi, tam 1.000 gözlemle
# 2022–2023'te "başladı". Pencere ≤365 gün (bağlayıcı sözleşmesi); limit dolu dönen yanıt kırpılmış sayılır.
EVDS_OBSERVATION_LIMIT = 1000


def _fetch_specs(spec: FetchSpec) -> tuple[FetchSpec, ...]:
    if spec.source_id == "evds" and spec.start_date is not None and spec.end_date is not None:
        return windowed_fetch_specs(spec, plan_evds_windows(spec.start_date, spec.end_date))
    return (spec,)


@dataclass
class SeriesOutcome:
    """One series' result, persisted as JSON so a partial run is never reported as complete (M07-T10)."""

    series_id: str
    status: str                 # ok | warning | failed | skipped | shared
    run_id: str | None = None
    assets: int = 0
    new: int = 0
    already: int = 0
    failed: int = 0
    empty: int = 0              # çok pencereli çekimde gözlemsiz dönen pencere: uyarı, hata değil (17 Eyl)
    rows_out: int = 0
    warnings: int = 0
    error: str | None = None
    seconds: float = 0.0
    shared_with: str | None = None
    history_code: str | None = None     # set when this outcome is an older schema id fetched for the series


@dataclass
class RunReport:
    requested: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)       # --only listed but not active in catalog
    stale_runs_closed: list[str] = field(default_factory=list)
    outcomes: list[SeriesOutcome] = field(default_factory=list)
    start: str = ""
    end: str = ""

    @property
    def ok(self) -> bool:
        return not self.missing and all(o.status in ("ok", "warning", "shared") for o in self.outcomes)


def close_stale_runs(connection, *, now: datetime) -> list[str]:
    """Runs left ``running`` by an interrupted process are closed as failed (M07-T11).

    This script is the only writer while it runs (DuckDB single-writer file lock), so any run
    still ``running`` when it starts belongs to a process that died. Leaving it open would make
    "running" mean nothing; closing it keeps the evidence and says why. RAW/Bronze files the
    dead run already wrote stay: they are content-addressed, and the next run re-links them.
    """

    repo = RunRepository(connection)
    stale = [r[0] for r in connection.execute(
        "SELECT run_id FROM meta.run WHERE status = 'running' AND started_at < ? ORDER BY started_at", [now]
    ).fetchall()]
    for run_id in stale:
        try:
            repo.finish(run_id=run_id, status=RUN_STATUS_FAILED, ended_at=now,
                        error="interrupted: run was still 'running' when a new ingestion started")
        except Exception:  # noqa: BLE001 - a bookkeeping race must not stop ingestion
            continue
    return stale

_ERROR_HINTS = {
    "SOURCE_UNAVAILABLE": (
        "Network/TLS/auth problem. For EVDS this usually means EVDS_API_KEY is "
        "not set. For BDDK, a TLS failure even after truststore injection means "
        "the Windows store could not resolve the missing intermediate cert."
    ),
    "SCHEMA_MISMATCH": (
        "Response shape did not match what the parser expected (identity "
        "mismatch, source changed, or a wrong parameter)."
    ),
    "EMPTY_DATASET": "Source answered but returned zero observations for this range.",
    "FETCH_TIMEOUT": "The request timed out after retries.",
}


def _require_repo_root_cwd() -> None:
    cwd = Path.cwd().resolve()
    if cwd != _REPO_ROOT:
        print(
            "ERROR: run this script with the working directory set to "
            f"{_REPO_ROOT} (lakehouse-core/), not {cwd}.\n"
            "Fix: cd into lakehouse-core/ and rerun "
            "`uv run python scripts/run_catalog_ingestion.py`."
        )
        raise SystemExit(2)


def _load_active_series(connection) -> list[SeriesRow]:
    """Read every active series meta.series currently knows about.

    This is the entire "which series exist" answer for this script — it comes
    from the real catalog, not from a list written here.
    """

    rows = connection.execute(
        """
        SELECT series_id, source_id, native_code, dataset_id, name_tr
        FROM meta.series
        WHERE status = 'active'
        ORDER BY source_id, series_id
        """
    ).fetchall()
    return [SeriesRow(*row) for row in rows]


def _validate_asset(spec: FetchSpec, asset) -> None:
    """Same identity check IngestionPipeline._validate_asset makes, reimplemented here
    (not imported — it's a private method) so a bad asset is still caught before parsing."""

    if asset.source_id != spec.source_id or asset.dataset_id != spec.dataset_id:
        raise LakehouseError(
            ErrorPayload(
                error_code="SCHEMA_MISMATCH",
                message=(
                    f"FetchSpec/FetchedAsset mismatch: expected "
                    f"{spec.source_id}/{spec.dataset_id}, got "
                    f"{asset.source_id}/{asset.dataset_id}"
                ),
                source_id=spec.source_id,
                dataset_id=spec.dataset_id,
                retryable=False,
            )
        )


def _validate_batch(asset, batch) -> None:
    """Same identity check IngestionPipeline._validate_batch makes, reimplemented here."""

    if (
        batch.source_id != asset.source_id
        or batch.dataset_id != asset.dataset_id
        or batch.artifact_sha256 != asset.artifact_sha256
    ):
        raise LakehouseError(
            ErrorPayload(
                error_code="SCHEMA_MISMATCH",
                message="FetchedAsset/ParsedBatch identity mismatch",
                source_id=asset.source_id,
                dataset_id=asset.dataset_id,
                retryable=False,
            )
        )


def _run_one(
    row: SeriesRow,
    raw_storage: RawStorage,
    session: requests.Session,
    artifact_repository: ArtifactRepository,
    parquet_storage: ParquetStorage,
    *,
    start: date = DEFAULT_START,
    end: date = DEFAULT_END,
    clock=_utc_now,
) -> SeriesOutcome:
    """Fetch and land every asset a series' FetchSpec produces, under one recorded run.

    Deliberately does NOT use IngestionPipeline.run(): that method processes every asset
    a connector returns as one all-or-nothing batch, so a single already-ingested asset
    (a real, expected case once a multi-period connector like BddkFinTurkConnector is
    re-run over a range it partly already covers) aborts the whole call and silently
    drops any later, genuinely-new assets in the same batch. This function fetches once,
    then lands each asset independently, so one quarter/month already in Bronze cannot
    hide others that are not.

    Run tracking (M07, ADR-0057) follows the same contract as IngestionPipeline: a
    ``meta.run`` row is opened before the fetch, every registered artifact is linked in
    ``meta.run_artifact`` BEFORE parsing, every parser warning is persisted in
    ``meta.ingest_warning`` BEFORE the Bronze write, and the run closes exactly once as
    ``success`` / ``warning`` / ``failed`` with ``rows_out`` and a redacted, bounded error.
    Silver's ``_run_context`` reads these back, so a warned artifact stays ``source_warning``
    after a rebuild instead of being silently upgraded to ``ok``.
    """

    started = time.perf_counter()
    print(f"\n=== {row.series_id} ({row.name_tr}) ===")
    outcome = SeriesOutcome(series_id=row.series_id, status="failed")

    binding = CONNECTOR_REGISTRY.get(row.source_id)
    if binding is None:
        print(f"  SKIPPED: no connector registered for source_id={row.source_id!r}")
        outcome.status, outcome.error = "skipped", f"no connector for source_id={row.source_id}"
        return outcome

    try:
        spec = binding.build_spec(row, start, end)
    except ValueError as exc:
        print(f"  SKIPPED: {exc}")
        outcome.status, outcome.error = "skipped", str(exc)[:300]
        return outcome

    connection = artifact_repository.connection
    runs = RunRepository(connection)
    run_id = runs.start(run_id=new_run_id(), source_id=spec.source_id, dataset_id=spec.dataset_id,
                        started_at=clock())
    outcome.run_id = run_id

    def close(status: str, error: str | None = None) -> None:
        try:
            runs.finish(run_id=run_id, status=status, ended_at=clock(), rows_out=outcome.rows_out, error=error)
        except Exception as exc:  # noqa: BLE001 - never mask the ingestion outcome
            print(f"  WARNING: run {run_id} could not be closed: {type(exc).__name__}")
        outcome.seconds = round(time.perf_counter() - started, 2)

    connector = binding.connector_cls(raw_storage, session=session)
    parser = binding.parser_cls()

    try:
        assets = []
        for window_spec in _fetch_specs(spec):
            assets.extend(connector.fetch(window_spec))
    except LakehouseError as exc:
        payload = exc.payload
        print("  FAILED (fetch)")
        print(f"  error_code : {payload.error_code}")
        print(f"  message    : {payload.message}")
        hint = _ERROR_HINTS.get(payload.error_code)
        if hint:
            print(f"  hint       : {hint}")
        outcome.error = describe_exception(exc)
        close(RUN_STATUS_FAILED, outcome.error)
        return outcome
    except Exception as exc:  # noqa: BLE001 - an unexpected connector crash is still a recorded failure
        outcome.error = describe_exception(exc)
        print(f"  FAILED (fetch, unexpected): {outcome.error}")
        close(RUN_STATUS_FAILED, outcome.error)
        return outcome

    if not assets:
        print("  FAILED: connector returned no assets")
        outcome.error = "EMPTY_DATASET: connector returned no assets"
        close(RUN_STATUS_FAILED, outcome.error)
        return outcome

    outcome.assets = len(assets)
    errors: list[str] = []
    for asset_no, asset in enumerate(assets, start=1):
        try:
            _validate_asset(spec, asset)
            artifact_inserted = artifact_repository.register(asset)
            parser_config_sha256 = asset.metadata.get("parser_config_sha256") if isinstance(asset.metadata, dict) else None
            runs.link_artifact(RunArtifactLink(
                run_id=run_id, artifact_sha256=asset.artifact_sha256, source_id=asset.source_id,
                dataset_id=asset.dataset_id, fetched_at=asset.fetched_at, parser_config_sha256=parser_config_sha256,
            ))
            parsed_batch = parser.parse(asset)
            _validate_batch(asset, parsed_batch)
            if asset.source_id == "evds" and len(parsed_batch.dataframe) >= EVDS_OBSERVATION_LIMIT:
                raise LakehouseError(ErrorPayload(
                    error_code="SCHEMA_MISMATCH",
                    message=(f"EVDS response has {len(parsed_batch.dataframe)} observations: reached the EVDS per-request "
                             f"limit ({EVDS_OBSERVATION_LIMIT}); the window was truncated and is not landed"),
                    source_id=asset.source_id, dataset_id=asset.dataset_id, retryable=False))
            if parsed_batch.warnings:
                records = []
                for message in parsed_batch.warnings:
                    outcome.warnings += 1
                    records.append(IngestionWarning(
                        run_id=run_id, warning_seq=outcome.warnings, source_id=asset.source_id,
                        dataset_id=asset.dataset_id, artifact_sha256=asset.artifact_sha256, message=message,
                    ))
                runs.record_warnings(records, created_at=clock())
            bronze_path = parquet_storage.write(parsed_batch)
        except ParquetConflictError:
            # Same RAW artifact re-processed at a different wall-clock time: fetched_at
            # is embedded in every Bronze row, so a second parse of identical source
            # bytes is legitimately a different Bronze representation. Bronze already
            # holds this one asset; that is a per-asset skip, not a failure of the rest.
            outcome.already += 1
            continue
        except ValueError as exc:
            # ArtifactRepository.register() raises a plain ValueError when the same
            # artifact_sha256 was already registered with different byte-derived metadata
            # (media type, size, HTTP status). Same bytes under another dataset_id are NOT a
            # conflict any more (17 Eyl: EVDS's empty-window body is identical for every series).
            # A real identity conflict: flagged distinctly, recorded on the run, but it must
            # not abort every other asset's processing.
            print(f"  FAILED (artifact identity conflict): {exc}")
            outcome.failed += 1
            errors.append(describe_exception(exc))
            continue
        except LakehouseError as exc:
            payload = exc.payload
            if payload.error_code == "EMPTY_DATASET" and len(assets) > 1:
                # Çok pencereli çekimde gözlemsiz pencere (17 Eyl canlı tam set: 25 EVDS serisinde son pencere
                # 2026-01..06 boş döndü — kaynak o dönemi henüz yayımlamamış). Hata değil, kayıtlı uyarı: öteki
                # pencereler iner, Silver yeniden kurulunca uyarı meta.ingest_warning'den geri okunur.
                # Her pencere boşsa döngüden sonra eskisi gibi EMPTY_DATASET hatasıdır.
                meta = asset.metadata if isinstance(asset.metadata, dict) else {}
                # EVDS bağlayıcısı pencere bağlamını metadata'ya yazar; yazmayan bağlayıcıda sıra numarası yeter.
                window = (f"window {meta.get('window_index', asset_no)}/{meta.get('window_count', len(assets))} "
                          f"({meta.get('requested_start_date', '?')}..{meta.get('requested_end_date', '?')})")
                outcome.empty += 1
                outcome.warnings += 1
                runs.record_warnings([IngestionWarning(
                    run_id=run_id, warning_seq=outcome.warnings, source_id=asset.source_id, dataset_id=asset.dataset_id,
                    artifact_sha256=asset.artifact_sha256, message=f"{window} returned no observations: {payload.message}",
                )], created_at=clock())
                print(f"  EMPTY {window}: no observations in this range — recorded as a warning, not a failure")
                continue
            print(f"  FAILED (asset {asset.locator}, fetched_at={asset.fetched_at})")
            print(f"    error_code : {payload.error_code}")
            print(f"    message    : {payload.message}")
            outcome.failed += 1
            errors.append(describe_exception(exc))
            continue

        outcome.new += 1
        row_count = len(parsed_batch.dataframe)
        outcome.rows_out += row_count
        print(
            f"  OK   fetched_at={asset.fetched_at}  rows={row_count}  "
            f"inserted={artifact_inserted}  -> {bronze_path.name}"
        )
        if parsed_batch.warnings:
            print(f"       warnings: {parsed_batch.warnings}")

    if outcome.empty and not (outcome.new or outcome.already):
        # Her pencere boş: seri bu aralıkta gerçekten gözlemsiz → tek pencereli çekimle aynı sonuç (EMPTY_DATASET).
        outcome.failed += outcome.empty
        errors.append(f"EMPTY_DATASET: all {outcome.empty} window(s) returned no observations")
    print(
        f"  -- {row.series_id}: {outcome.new} new, {outcome.already} already in Bronze, "
        f"{outcome.failed} failed, {outcome.empty} empty window(s), out of {len(assets)} fetched asset(s) · run {run_id}"
    )
    if outcome.failed:
        outcome.status = "failed"
        outcome.error = f"{outcome.failed}/{len(assets)} asset(s) failed: " + " | ".join(errors[:3])
        close(RUN_STATUS_FAILED, describe_exception(RuntimeError(outcome.error)))
    else:
        outcome.status = "warning" if outcome.warnings else "ok"
        close(RUN_STATUS_WARNING if outcome.warnings else RUN_STATUS_SUCCESS)
    return outcome


def _parse_args(argv: list[str] | None = None):
    """Optional overrides. Defaults keep the historical behaviour: repo-local data/ paths and
    every active series. ``--only`` runs a subset (comma-separated series ids); the demo
    acceptance script uses it to land five series instead of the whole catalog."""
    import argparse

    parser = argparse.ArgumentParser(description="Catalog-driven real ingestion (manual utility).")
    parser.add_argument("--database", type=Path, default=None, help="DuckDB path (default: data/lakehouse.duckdb)")
    parser.add_argument("--data-root", type=Path, default=None, help="root containing raw/ and bronze/ (default: data)")
    parser.add_argument("--only", default=None, help="comma-separated series ids; default: every active series")
    parser.add_argument("--only-file", type=Path, default=None, help="file with one series id per line (large sets)")
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START, help="YYYY-MM-DD (default 2016-01-01)")
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END, help="YYYY-MM-DD (default 2026-06-30)")
    parser.add_argument("--report", type=Path, default=None, help="write a JSON coverage report (requested/processed/skipped/failed)")
    return parser.parse_args(argv)


def _spec_key(spec) -> str:
    import json

    return json.dumps(
        {"source": spec.source_id, "locator": spec.locator, "start": str(spec.start_date), "end": str(spec.end_date),
         "parameters": spec.parameters},
        sort_keys=True, default=str, ensure_ascii=False,
    )


def main(argv: list[str] | None = None) -> int:
    _require_repo_root_cwd()
    args = _parse_args(argv)
    data_root = args.data_root or Path("data")
    if args.start > args.end:
        print(f"ERROR: --start {args.start} is after --end {args.end}")
        return 2

    trusted = bootstrap_database(args.database or (data_root / "lakehouse.duckdb"))
    from src.lakehouse.db.bootstrap import read_catalog_mode
    if (read_catalog_mode(trusted) or "default") == "none":
        # D04 (ADR-0067): boş katalog kipindeki veritabanına başlangıç kataloğunun serileri çekilmez.
        print("ERROR: this database is in empty-catalog mode (series_catalog=none); "
              "run `python -m lakehouse bootstrap --catalog default` first if the default catalog is wanted")
        trusted.close()
        return 2
    raw_storage = RawStorage(data_root / "raw")
    parquet_storage = ParquetStorage(data_root / "bronze")
    artifact_repository = ArtifactRepository(trusted)
    session = requests.Session()
    report = RunReport(start=str(args.start), end=str(args.end))
    report.stale_runs_closed = close_stale_runs(trusted, now=_utc_now())
    if report.stale_runs_closed:
        print(f"Closed {len(report.stale_runs_closed)} stale 'running' run(s) from an interrupted process.")

    series = _load_active_series(trusted)
    wanted: set[str] = set()
    if args.only:
        wanted |= {sid.strip() for sid in args.only.split(",") if sid.strip()}
    if args.only_file:
        wanted |= {line.strip() for line in args.only_file.read_text(encoding="utf-8").splitlines()
                   if line.strip() and not line.startswith("#")}
    if wanted:
        report.requested = sorted(wanted)
        series = [row for row in series if row.series_id in wanted]
        report.missing = sorted(wanted - {row.series_id for row in series})
        if report.missing:
            # A requested series that does not exist is a failure of the request, not a
            # silently smaller success (M07-T10).
            print(f"ERROR: --only listed series not active in the catalog: {', '.join(report.missing)}")
    print(f"Katalogda {len(series)} aktif seri bulundu · dönem {args.start} → {args.end}.")
    history = load_history()

    by_id: dict[str, SeriesOutcome] = {}
    # Aynı çekimi paylaşan seriler (FinTürk: bir ilin 8 ölçüm sütunu tek yanıtta gelir) bir kez
    # çekilir; parser yanıttaki bütün serileri Bronze'a yazdığı için ikinci çekim yalnız ağ
    # maliyetidir. Anahtar FetchSpec'in kendisidir (kaynak, adres, parametreler, tarih aralığı).
    shared: dict[str, str] = {}
    try:
        for position, row in enumerate(series):
            binding = CONNECTOR_REGISTRY.get(row.source_id)
            if binding is not None:
                try:
                    key = _spec_key(binding.build_spec(row, args.start, args.end))
                except ValueError:
                    key = None
                if key is not None and key in shared:
                    first = shared[key]
                    base = by_id[first]
                    shared_outcome = SeriesOutcome(series_id=row.series_id, status="shared" if base.status in ("ok", "warning") else base.status,
                                                   run_id=base.run_id, shared_with=first, error=base.error)
                    by_id[row.series_id] = shared_outcome
                    report.outcomes.append(shared_outcome)
                    print(f"\n=== {row.series_id} ({row.name_tr}) ===\n  aynı çekimden ({first}); yeniden istenmedi")
                    continue
                if key is not None:
                    shared[key] = row.series_id
            if position > 0:
                # Generic, source-agnostic pacing between DIFFERENT series' first requests.
                time.sleep(0.2)
            outcome = _run_one(row, raw_storage, session, artifact_repository, parquet_storage,
                               start=args.start, end=args.end)
            by_id[row.series_id] = outcome
            report.outcomes.append(outcome)
            for old_row, lo, hi in history_rows(row, history.get(row.series_id, []), args.start, args.end):
                time.sleep(0.2)
                print(f"  eski şema kimliği {old_row.native_code} · {lo} → {hi} (aynı seri)")
                old_outcome = _run_one(old_row, raw_storage, session, artifact_repository, parquet_storage, start=lo, end=hi)
                old_outcome.history_code = old_row.native_code
                report.outcomes.append(old_outcome)
    finally:
        trusted.close()
        session.close()
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            payload = {"start": report.start, "end": report.end, "ok": report.ok, "requested": len(report.requested),
                       "missing": report.missing, "stale_runs_closed": report.stale_runs_closed,
                       "counts": {k: sum(1 for o in report.outcomes if o.status == k) for k in ("ok", "warning", "shared", "failed", "skipped")},
                       "outcomes": [asdict(o) for o in report.outcomes]}
            args.report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    for o in report.outcomes:
        if o.status not in ("ok", "shared"):
            print(f"  [{o.status.upper()}] {o.series_id}" + (f" — {o.error[:160]}" if o.error else ""))
    counts = {k: sum(1 for o in report.outcomes if o.status == k) for k in ("ok", "warning", "shared", "failed", "skipped")}
    succeeded = counts["ok"] + counts["warning"] + counts["shared"]
    print(f"\n{succeeded}/{len(report.outcomes)} series ingested successfully "
          f"(ok {counts['ok']}, warning {counts['warning']}, shared {counts['shared']}, failed {counts['failed']}, "
          f"skipped {counts['skipped']}; missing from catalog {len(report.missing)}).")
    return 0 if report.ok and report.outcomes else 1


if __name__ == "__main__":
    raise SystemExit(main())
