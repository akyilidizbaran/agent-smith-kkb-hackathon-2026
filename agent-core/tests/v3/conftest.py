"""V3 testleri için LLM'siz sahte bileşenler.

FakeLLM senaryolu cevap döndürür; StubLakehouse küçük bir DataFrame ile
LakehouseClient'ı taklit eder. Hiçbir test ağa çıkmaz.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from kkb_agent.contracts.catalog import (  # noqa: E402
    ColumnRole,
    ColumnSpec,
    Coverage,
    DatasetSpec,
    Frequency,
    SemanticType,
)
from kkb_agent.contracts.lakehouse import LakehouseError, QueryProvenance, QueryResult  # noqa: E402
from kkb_agent.llm.base import ChatMessage, LLMResponse, ToolCall  # noqa: E402

SPEC = DatasetSpec(
    dataset_id="test_krediler",
    name="Test Krediler",
    description="test",
    source="TEST",
    frequency=Frequency.MONTHLY,
    time_column="donem",
    grain=["donem", "kalem"],
    columns=[
        ColumnSpec(name="donem", role=ColumnRole.TIME, dtype="DATE", description="dönem"),
        ColumnSpec(name="kalem", role=ColumnRole.DIMENSION, dtype="VARCHAR", description="kalem",
                   example_values=["Kalem A", "Kalem B"]),
        ColumnSpec(name="is_alt_toplam", role=ColumnRole.DIMENSION, dtype="BOOLEAN", description="alt toplam"),
        ColumnSpec(name="toplam", role=ColumnRole.MEASURE, dtype="DOUBLE", description="toplam",
                   semantic_type=SemanticType.STOCK, unit="milyon TL"),
    ],
    coverage=Coverage(start=date(2021, 1, 31), end=date(2026, 6, 30), row_count=3),
)


class StubLakehouse:
    def __init__(self, df: pd.DataFrame | None = None) -> None:
        self._df = df if df is not None else pd.DataFrame({
            "donem": [date(2025, 1, 31), date(2025, 2, 28)], "kalem": ["Kalem A", "Kalem A"], "toplam": [100.0, 110.0],
        })
        self.calls: list[str] = []

    def list_datasets(self):
        return [SPEC]

    def get_dataset(self, dataset_id: str):
        if dataset_id != SPEC.dataset_id:
            raise LakehouseError(f"'{dataset_id}' bulunamadı.")
        return SPEC

    def search_datasets(self, query: str, limit: int = 5):
        return [SPEC]

    def preview(self, dataset_id: str, n: int = 5):
        return self.execute_sql("SELECT * FROM test_krediler LIMIT 5")

    def execute_sql(self, sql: str, *, max_rows: int = 10_000):
        self.calls.append(sql)
        if "COUNT(DISTINCT" in sql:
            df = pd.DataFrame({"n": [2]})
        else:
            df = self._df
        return QueryResult(data=df, provenance=QueryProvenance(sql=sql, dataset_ids=[SPEC.dataset_id], row_count=len(df)))


class FakeLLM:
    """Sırayla verilen cevapları döndürür; her çağrının tools/extra'sını kaydeder."""

    model = "fake"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def supports_native_tools(self) -> bool:
        return True

    def chat(self, messages: list[ChatMessage], *, tools=None, temperature: float = 0.0,
             max_tokens=None, extra=None) -> LLMResponse:
        self.calls.append({"tools": tools, "extra": extra, "max_tokens": max_tokens, "messages": list(messages)})
        if not self._responses:
            return LLMResponse(content="(cevap kalmadı)")
        return self._responses.pop(0)


def call(name: str, i: int = 0, **args: Any) -> ToolCall:
    return ToolCall(id=f"c{i}", name=name, arguments=args)


def tool_turn(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(content="", tool_calls=list(calls))


def final(text: str) -> LLMResponse:
    return LLMResponse(content=text)


@pytest.fixture
def lakehouse() -> StubLakehouse:
    return StubLakehouse()
