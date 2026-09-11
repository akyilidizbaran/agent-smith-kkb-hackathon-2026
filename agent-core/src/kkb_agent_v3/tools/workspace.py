"""Workspace araçları — ekip motorunun araçları, V3 zarfına sarılmış.

`workspace_add_column / compute_column / show` ekipte ölçülerek tasarlandı
(ADR-0016: yapısal parametreler); yeniden yazmak ölçümü çöpe atmak olurdu.
Bu modül onları DEĞİŞTİRMEZ: aynı sınıfları import eder, `run` çıktısındaki
"HATA: ..." serbest metnini `ToolError` koduna çevirir. Ekip kodu tek satır
değişmeden iki motorda da çalışır.
"""

from __future__ import annotations

from kkb_agent.contracts.lakehouse import LakehouseClient
from kkb_agent.core.tool import Tool as TeamTool
from kkb_agent.core.tool import ToolResult as TeamToolResult
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.tools.workspace import (
    WorkspaceAddColumnTool,
    WorkspaceComputeColumnTool,
    WorkspaceShowTool,
)

from ..core.tool import Tool, ToolResult
from ..errors import ToolError

# Ekip araçlarının hata metinleri → V3 hata kodu. Sıra önemli: ilk eşleşen kazanır.
_ERROR_MAP: list[tuple[str, str, bool | None]] = [
    ("analiz tablosu yok", "WORKSPACE_EMPTY", True),
    ("izin verilmez", "POLICY_VIOLATION", False),
    ("zaten tabloda var", "INVALID_ARGS", True),
    ("hiç satır döndürmedi", "EMPTY_DATASET", True),
    ("eşleşen satır bulunamadı", "EMPTY_DATASET", True),
    ("satır sayısını değiştiren", "SEMANTIC_VIOLATION", True),
    ("tablosunda yok", "COLUMN_NOT_FOUND", True),
    ("analiz tablosunda yok", "COLUMN_NOT_FOUND", True),
    ("bulunamadı", "SERIES_NOT_FOUND", True),
    ("hesaplanamadı", "TOOL_FAILED", True),
]


# Ekip zarfının (ADR-0025) kodları → V3 kodları. Aynı adlılar olduğu gibi geçer.
_TEAM_CODE_MAP: dict[str, str] = {
    "DATASET_NOT_FOUND": "SERIES_NOT_FOUND",
    "VALUE_NOT_FOUND": "EMPTY_DATASET",
    "EMPTY_RESULT": "EMPTY_DATASET",
    "JOIN_MISMATCH": "SEMANTIC_VIOLATION",
    "NO_ACTIVE_TABLE": "WORKSPACE_EMPTY",
    "COLUMN_EXISTS": "INVALID_ARGS",
    "SQL_FAILED": "TOOL_FAILED",
}


def _convert(res: TeamToolResult) -> ToolResult:
    if res.ok:
        return ToolResult(content=res.content, data=res.data, provenance=res.provenance, artifacts=res.artifacts)
    team_err = getattr(res, "error", None)
    if team_err is not None:
        # Ekip motoru artık yapılandırılmış zarf döndürüyor (ADR-0025): metin ayrıştırmaya gerek yok.
        code = _TEAM_CODE_MAP.get(team_err.error_code, team_err.error_code)
        return ToolResult.fail(ToolError(
            error_code=code, layer="runtime", message=team_err.message[:300],
            hint=team_err.hint, candidates=list(team_err.candidates)[:5],
            retryable=team_err.is_retryable,
        ))
    # Geriye dönük: serbest metinli eski zarf
    text = res.content.removeprefix("HATA: ").strip()
    low = text.lower()
    code, retryable = "TOOL_FAILED", True
    for needle, c, r in _ERROR_MAP:
        if needle in low:
            code, retryable = c, r
            break
    # Ekip mesajları "Mevcut kolonlar: a, b, c" ile adayları zaten taşıyor; ayıkla.
    candidates: list[str] = []
    if "kolonlar:" in low:
        tail = text[low.index("kolonlar:") + len("kolonlar:"):]
        candidates = [c.strip() for c in tail.split(",") if c.strip()][:5]
    return ToolResult.fail(ToolError(
        error_code=code, layer="runtime", message=text.split("\n")[0][:300],
        candidates=candidates, retryable=retryable,
    ))


class _Adapted(Tool):
    """Ekip aracını V3 sözleşmesine sarar; ad/şema/parametre modeli aynen geçer."""

    def __init__(self, inner: TeamTool, *, mutates: bool) -> None:
        self._inner = inner
        self.name = inner.name
        self.description = inner.description
        self.Params = inner.Params
        self.mutates = mutates

    def run(self, params):  # type: ignore[override]
        return _convert(self._inner.run(params))


def workspace_tools(lakehouse: LakehouseClient, workspace: AnalysisWorkspace) -> list[Tool]:
    return [
        _Adapted(WorkspaceAddColumnTool(lakehouse, workspace), mutates=True),
        _Adapted(WorkspaceComputeColumnTool(workspace), mutates=True),
        _Adapted(WorkspaceShowTool(workspace), mutates=False),
    ]
