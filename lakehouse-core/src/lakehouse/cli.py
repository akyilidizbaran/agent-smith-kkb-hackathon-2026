"""Thin command-line adapter for the lakehouse composition root."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from .adhoc import AdhocObservationMapping
from .application import (
    _adhoc_record,
    run_adhoc_ingestion,
    run_bootstrap,
    run_gold_build,
    run_known_source_ingestion,
    run_promote_draft,
    run_silver_build,
)
from .db.connection import connect_untrusted
from .catalog.promotion import PromotionError
from .errors import LakehouseError
from .gold.build import call_gold_function
from .gold.catalog import DEFAULT_GOLD_CATALOG_ROOT, GOLD_FUNCTIONS, GoldCatalogError
from .gold.errors import GoldError
from .gold.periods import TARGET_FREQUENCIES
from .gold.serialize import frame_to_document, write_document
from .generic.config import ENCODINGS
from .generic.formats import SUPPORTED_FORMATS
from .ingestion.observability import describe_exception
from .ingestion.windowing import WindowedIngestionFailure


_DEFAULT_DATABASE = Path("data/lakehouse.duckdb")
_DEFAULT_DATA_ROOT = Path("data")
_DELIMITERS = (",", ";", "\t", "|")


def _iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; use ISO format YYYY-MM-DD"
        ) from exc


def _add_storage_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--database",
        type=Path,
        default=_DEFAULT_DATABASE,
        help="DuckDB path (default: data/lakehouse.duckdb)",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=_DEFAULT_DATA_ROOT,
        help="root containing raw/ and bronze/ (default: data)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m lakehouse",
        description="Operate the local lakehouse through its existing ingestion services.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    bootstrap = commands.add_parser(
        "bootstrap", help="create or update the local DuckDB schemas and catalog"
    )
    _add_storage_options(bootstrap)
    bootstrap.add_argument(
        "--catalog",
        choices=("default", "none"),
        default=None,
        help=("series catalog mode stored in the database: 'default' loads catalog/series/*.yml, "
              "'none' keeps an empty catalog for a new domain (default: keep the stored mode)"),
    )
    bootstrap.set_defaults(handler=_handle_bootstrap)

    ingest = commands.add_parser(
        "ingest", help="ingest one explicitly registered source dataset"
    )
    _add_storage_options(ingest)
    ingest.add_argument("--source", required=True, help="registered source id")
    ingest.add_argument("--dataset", required=True, help="registered dataset id")
    ingest.add_argument("--start-date", required=True, type=_iso_date)
    ingest.add_argument("--end-date", required=True, type=_iso_date)
    ingest.add_argument(
        "--headers-ref",
        help="environment variable name for source credentials (default is source-defined)",
    )
    ingest.add_argument("--timeout", type=float, default=30.0)
    ingest.set_defaults(handler=_handle_ingest)

    silver = commands.add_parser(
        "silver",
        help="rebuild silver.fact_observation from every catalogued Bronze observation",
    )
    _add_storage_options(silver)
    silver.set_defaults(handler=_handle_silver)

    gold = commands.add_parser(
        "gold",
        help="materialize the reviewed Gold metrics (catalog/gold/*.yml) as gold.* tables; run after silver",
    )
    _add_storage_options(gold)
    gold.add_argument(
        "--gold-catalog",
        type=Path,
        default=DEFAULT_GOLD_CATALOG_ROOT,
        help="directory of metric YAML files (default: catalog/gold)",
    )
    gold.set_defaults(handler=_handle_gold)

    promote = commands.add_parser(
        "promote-draft",
        help="promote an ad-hoc draft series to active and copy its rows into Silver (a human's decision)",
    )
    _add_storage_options(promote)
    promote.add_argument("--series", required=True, help="adhoc:<key> draft series id")
    promote.set_defaults(handler=_handle_promote_draft)

    gold_run = commands.add_parser(
        "gold-run",
        help="run ONE Gold function read-only and write the frame as JSON; refusals exit 3",
    )
    _add_storage_options(gold_run)
    gold_run.add_argument("--function", required=True, choices=sorted(GOLD_FUNCTIONS))
    gold_run.add_argument(
        "--series", required=True, action="append", help="series id; repeat for join_on_period"
    )
    gold_run.add_argument("--target", choices=TARGET_FREQUENCIES)
    gold_run.add_argument(
        "--allow-unverified-semantics",
        action="store_true",
        help="relay a HUMAN's consent to use a series whose semantics are not verified",
    )
    gold_run.add_argument("--out", required=True, type=Path, help="JSON document to write")
    gold_run.set_defaults(handler=_handle_gold_run)

    ingest_file = commands.add_parser(
        "ingest-file", help="ingest a local or public tabular artifact into the ad-hoc table"
    )
    _add_storage_options(ingest_file)
    ingest_file.add_argument("file_or_url", metavar="file-or-url")
    ingest_file.add_argument("--dataset-id", required=True)
    ingest_file.add_argument(
        "--allowed-local-root",
        action="append",
        type=Path,
        help="permitted local directory; repeat for multiple roots",
    )
    ingest_file.add_argument("--format", choices=SUPPORTED_FORMATS)
    ingest_file.add_argument("--delimiter", choices=_DELIMITERS)
    ingest_file.add_argument("--encoding", choices=(*ENCODINGS, "auto"))
    ingest_file.add_argument("--records-field")
    ingest_file.add_argument("--sheet-name")
    ingest_file.add_argument("--table-index", type=int)
    ingest_file.add_argument("--timeout", type=float, default=30.0)

    mapping = ingest_file.add_argument_group("explicit observation mapping")
    mapping.add_argument("--series-id", required=True, help="adhoc:<native-series-key>")
    mapping.add_argument("--date-column", required=True)
    mapping.add_argument("--value-column", required=True)
    mapping.add_argument("--entity-column")
    mapping.add_argument("--date-format")
    mapping.add_argument("--decimal-separator", choices=(".", ","), default=".")
    mapping.add_argument("--thousands-separator")

    semantics = ingest_file.add_argument_group("explicit draft catalog semantics")
    semantics.add_argument("--name", required=True, help="human-readable series name")
    semantics.add_argument("--description", required=True)
    semantics.add_argument("--frequency", required=True)
    semantics.add_argument("--unit", required=True)
    semantics.add_argument("--measure-type", required=True)
    semantics.add_argument("--week-anchor")
    semantics.add_argument("--default-agg")
    semantics.add_argument("--cumulative-reset")
    ingest_file.set_defaults(handler=_handle_ingest_file)

    return parser


def _parser_parameters(args: argparse.Namespace) -> dict[str, Any]:
    values = {
        "format": args.format,
        "delimiter": args.delimiter,
        "encoding": args.encoding,
        "records_field": args.records_field,
        "sheet_name": args.sheet_name,
        "table_index": args.table_index,
    }
    return {key: value for key, value in values.items() if value is not None}


def _handle_bootstrap(args: argparse.Namespace, **_: Any) -> int:
    summary = run_bootstrap(args.database, catalog_mode=args.catalog)
    print("status: success")
    print(f"database: {summary.database}")
    print(f"catalog_mode: {summary.catalog_mode}")
    print(f"catalog_series_count: {summary.catalog_series_count}")
    return 0


def _handle_ingest(
    args: argparse.Namespace, *, session: Any = None, clock: Any = None
) -> int:
    summary = run_known_source_ingestion(
        source_id=args.source,
        dataset_id=args.dataset,
        start_date=args.start_date,
        end_date=args.end_date,
        database=args.database,
        data_root=args.data_root,
        timeout=args.timeout,
        headers_ref=args.headers_ref,
        session=session,
        clock=clock,
    )
    _print_windowed_summary(summary)
    return 0


def _handle_silver(
    args: argparse.Namespace, *, session: Any = None, clock: Any = None
) -> int:
    """Turn Bronze into the trusted query surface an agent actually reads."""

    report = run_silver_build(database=args.database, data_root=args.data_root)
    print("status: success")
    print(report.render())
    return 0


def _handle_gold(
    args: argparse.Namespace, *, session: Any = None, clock: Any = None
) -> int:
    """Cache the reviewed metric calls as tables; record what the functions refused."""

    try:
        report = run_gold_build(database=args.database, catalog_root=args.gold_catalog)
    except GoldCatalogError as exc:
        print("status: failed", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("status: success")
    print(report.render())
    return 0


def _handle_promote_draft(
    args: argparse.Namespace, *, session: Any = None, clock: Any = None
) -> int:
    """Draft → active on a human's say-so. Refuses curated or non-draft rows."""

    try:
        result = run_promote_draft(database=args.database, series_id=args.series)
    except PromotionError as exc:
        print("status: failed", file=sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("status: success")
    print(f"series_id: {result.series_id}")
    print(f"previous_status: {result.previous_status}")
    print("status_now: active")
    print("semantic_confidence: derived")
    print(f"rows_promoted: {result.rows_promoted}")
    print(f"silver_rows_replaced: {result.silver_rows_replaced}")
    return 0


def _handle_gold_run(
    args: argparse.Namespace, *, session: Any = None, clock: Any = None
) -> int:
    """One Gold call on the hardened read-only profile, serialized for another process.

    This is the path an agent in a separate process uses: it does not import this package
    and holds no writable handle. A refusal is an outcome, not a crash -- it is printed as
    ``status: refused`` with the machine-readable reason and exits 3, distinct from 2.
    """

    if args.function != "decompose_cumulative" and args.target is None:
        print("status: failed", file=sys.stderr)
        print(f"error: --target is required for {args.function}", file=sys.stderr)
        return 2
    if args.function == "decompose_cumulative" and args.target is not None:
        print("status: failed", file=sys.stderr)
        print("error: decompose_cumulative keeps the source frequency; drop --target", file=sys.stderr)
        return 2
    if not Path(args.database).is_file():
        print("status: failed", file=sys.stderr)
        print(f"error: database {args.database} does not exist", file=sys.stderr)
        return 2

    connection = connect_untrusted(args.database)
    try:
        frame = call_gold_function(
            connection,
            function=args.function,
            series_ids=list(args.series),
            target_frequency=args.target,
            allow_unverified_semantics=bool(args.allow_unverified_semantics),
        )
    except GoldError as exc:
        print("status: refused")
        print(f"reason: {exc.refusal.reason}")
        if exc.refusal.series_id:
            print(f"series_id: {exc.refusal.series_id}")
        print(f"message: {exc.refusal.message}")
        return 3
    finally:
        connection.close()

    arguments = {"series_ids": list(args.series), "target_frequency": args.target,
                 "allow_unverified_semantics": bool(args.allow_unverified_semantics)}
    write_document(frame_to_document(frame, function=args.function, arguments=arguments), args.out)
    print("status: success")
    print(f"function: {args.function}")
    print(f"rows: {len(frame)}")
    print(f"columns: {len(frame.columns)}")
    print(f"out: {args.out}")
    return 0


def _handle_ingest_file(
    args: argparse.Namespace, *, session: Any = None, clock: Any = None
) -> int:
    series_record = _adhoc_record(
        series_id=args.series_id,
        dataset_id=args.dataset_id,
        name=args.name,
        description=args.description,
        frequency=args.frequency,
        unit=args.unit,
        measure_type=args.measure_type,
        week_anchor=args.week_anchor,
        default_agg=args.default_agg,
        cumulative_reset=args.cumulative_reset,
    )
    mapping = AdhocObservationMapping(
        series_id=args.series_id,
        observation_date_column=args.date_column,
        value_column=args.value_column,
        entity_id_column=args.entity_column,
        date_format=args.date_format,
        decimal_separator=args.decimal_separator,
        thousands_separator=args.thousands_separator,
    )
    summary = run_adhoc_ingestion(
        locator=args.file_or_url,
        dataset_id=args.dataset_id,
        database=args.database,
        data_root=args.data_root,
        allowed_local_roots=args.allowed_local_root,
        parser_parameters=_parser_parameters(args),
        mapping=mapping,
        series_record=series_record,
        timeout=args.timeout,
        session=session,
        clock=clock,
    )
    _print_ingestion_summary(summary.ingestion)
    print(f"series_id: {', '.join(summary.publication.series_ids)}")
    print(f"rows_written: {summary.publication.rows_written}")
    print(f"rows_unchanged: {summary.publication.rows_unchanged}")
    return 0


def _print_ingestion_summary(summary: Any) -> None:
    print(f"status: {summary.status}")
    print(f"source_id: {summary.source_id}")
    print(f"dataset_id: {summary.dataset_id}")
    print(f"run_id: {summary.run_id}")
    print(f"artifact_sha256: {summary.artifact_sha256}")
    print(f"bronze_path: {summary.bronze_path}")
    if summary.warning_count:
        print(f"warnings: {summary.warning_count}")


def _print_windowed_summary(summary: Any) -> None:
    """Print all artifact identities without pretending one represents a whole run."""

    print(f"status: {summary.status}")
    print(f"source_id: {summary.source_id}")
    print(f"dataset_id: {summary.dataset_id}")
    print(f"run_id: {summary.run_id}")
    if summary.window_count == 1 and len(summary.artifact_sha256s) == 1:
        print(f"artifact_sha256: {summary.artifact_sha256s[0]}")
        print(f"bronze_path: {summary.bronze_paths[0]}")
    else:
        print(f"window_count: {summary.window_count}")
        print(f"artifact_count: {len(summary.artifact_sha256s)}")
        print(f"artifact_sha256s: {', '.join(summary.artifact_sha256s)}")
        print(f"bronze_paths: {', '.join(str(path) for path in summary.bronze_paths)}")
    print(f"observation_count: {summary.observation_count}")
    if summary.warning_count:
        print(f"warnings: {summary.warning_count}")


def main(
    argv: Sequence[str] | None = None, *, session: Any = None, clock: Any = None
) -> int:
    """Parse arguments, invoke the composition root, and return 0 or a failure code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args, session=session, clock=clock)
    except WindowedIngestionFailure as exc:
        print("status: failed", file=sys.stderr)
        print(f"run_id: {exc.run_id}", file=sys.stderr)
        print(f"failed_window_start: {exc.window.start_date}", file=sys.stderr)
        print(f"failed_window_end: {exc.window.end_date}", file=sys.stderr)
        print(f"error: {describe_exception(exc.cause)}", file=sys.stderr)
        return 2
    except (LakehouseError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


__all__ = ["main"]
