"""Regression tests for schema-backed SQL identifiers requiring quoting."""

from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd

from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency
from kkb_agent.contracts.lakehouse import QueryProvenance, QueryResult
from kkb_agent.core.sql_identifiers import quote_identifier, quote_known_identifiers
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.tools.lakehouse import LakehouseQueryTool
from kkb_agent.tools.workspace_query import WorkspaceQueryTool

SPECIAL_NEEDS = "bddk_monthly:1536_Toplam@bddk:10001::value"
SPECIAL_CARD = "bddk_monthly:1539_Toplam@bddk:10001::value"
SPECIAL_GENERIC = "passengers:monthly@city::value"


def _spec(*columns: str) -> DatasetSpec:
    return DatasetSpec(
        dataset_id="test_special",
        name="Special identifiers",
        description="test",
        source="TEST",
        frequency=Frequency.MONTHLY,
        time_column="period_end",
        grain=["period_end"],
        columns=[
            ColumnSpec(name="period_end", role=ColumnRole.TIME, dtype="DATE", description="date"),
            *[
                ColumnSpec(name=column, role=ColumnRole.MEASURE, dtype="DOUBLE", description=column)
                for column in columns
            ],
        ],
        coverage=Coverage(start=date(2022, 1, 1), end=date(2022, 3, 31)),
    )


class _SpecialLakehouse:
    def __init__(self, spec: DatasetSpec) -> None:
        self.spec = spec
        self.executed: list[str] = []

    def list_datasets(self):
        return [self.spec]

    def get_dataset(self, dataset_id: str):
        return self.spec

    def execute_sql(self, sql: str, *, max_rows: int = 10_000):
        del max_rows
        self.executed.append(sql)
        con = duckdb.connect()
        try:
            columns = ", ".join(
                f'"{column.name}" DOUBLE'
                for column in self.spec.columns
                if column.name != "period_end"
            )
            con.execute(f"CREATE TABLE test_special (period_end DATE, {columns})")
            values = ", ".join(
                "463792.0"
                if column.name == SPECIAL_NEEDS
                else "214776.0"
                if column.name == SPECIAL_CARD
                else "12.0"
                for column in self.spec.columns
                if column.name != "period_end"
            )
            con.execute(f"INSERT INTO test_special VALUES (DATE '2022-01-31', {values})")
            frame = con.execute(sql).fetch_df()
        finally:
            con.close()
        return QueryResult(
            data=frame,
            provenance=QueryProvenance(
                sql=sql, dataset_ids=["test_special"], sources=["TEST"], row_count=len(frame)
            ),
        )


def test_quote_known_identifiers_is_generic_and_literal_safe() -> None:
    names = [
        "column with space",
        "metric:value",
        "metric@source",
        "metric::value",
        "Türkçe ölçü",
        "metric-(v1)",
    ]
    sql = "SELECT " + ", ".join(names) + ", 'metric:value' AS literal FROM t"
    normalized = quote_known_identifiers(sql, names)

    for name in names:
        assert quote_identifier(name) in normalized
    assert quote_identifier('embedded"quote') == '"embedded""quote"'
    assert "'metric:value' AS literal" in normalized


def test_lakehouse_query_quotes_two_special_identifiers_and_preserves_provenance() -> None:
    lake = _SpecialLakehouse(_spec(SPECIAL_NEEDS, SPECIAL_CARD))
    workspace = AnalysisWorkspace()
    result = LakehouseQueryTool(lake, workspace).validate_and_run(
        {
            "sql": f"SELECT period_end, {SPECIAL_NEEDS}, {SPECIAL_CARD} FROM test_special",
            "purpose": "special identifier test",
        }
    )

    assert result.ok, result.content
    assert lake.executed == [
        f'SELECT period_end, "{SPECIAL_NEEDS}", "{SPECIAL_CARD}" FROM test_special'
    ]
    assert result.provenance is not None
    assert result.provenance.dataset_ids == ["test_special"]
    assert workspace.column_provenance(SPECIAL_NEEDS).sources == ["TEST"]


def test_simple_and_generic_special_identifiers_work() -> None:
    lake = _SpecialLakehouse(_spec(SPECIAL_GENERIC))
    result = LakehouseQueryTool(lake, AnalysisWorkspace()).validate_and_run(
        {"sql": f"SELECT period_end, {SPECIAL_GENERIC} FROM test_special", "purpose": "generic"}
    )
    assert result.ok, result.content
    assert lake.executed[0].endswith(f'"{SPECIAL_GENERIC}" FROM test_special')


def test_already_quoted_identifier_is_not_double_quoted() -> None:
    quoted = f'SELECT "{SPECIAL_NEEDS}" FROM test'
    assert quote_known_identifiers(quoted, [SPECIAL_NEEDS]) == quoted


def test_workspace_query_quotes_complex_active_columns_and_preserves_source() -> None:
    workspace = AnalysisWorkspace()
    workspace.set_table(
        pd.DataFrame({SPECIAL_GENERIC: [12.0], "period_end": pd.to_datetime(["2022-01-31"])}),
        description="generic",
        provenance=QueryProvenance(
            sql="SELECT", dataset_ids=["transport:passengers"], sources=["transport"]
        ),
    )
    result = WorkspaceQueryTool(workspace).validate_and_run(
        {"sql": f"SELECT period_end, {SPECIAL_GENERIC} FROM t", "purpose": "generic"}
    )

    assert result.ok, result.content
    assert workspace.column_provenance(SPECIAL_GENERIC).dataset_ids == ["transport:passengers"]
