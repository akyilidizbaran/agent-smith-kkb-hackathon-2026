"""Yapılandırılmış hata zarfı ve harness'ın ona verdiği tepki.

Serbest metin hatalar üç şeyi imkânsız kılıyordu: saymak, onarılabilir olanı
olmayandan ayırmak, adayları yapısal taşımak. Bu testler üçünü de kilitler.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.errors import NOT_RETRYABLE, ToolError  # noqa: E402
from kkb_agent.core.tool import ToolResult  # noqa: E402


def test_kod_ve_ipucu_modele_gider() -> None:
    r = ToolResult.fail(
        "COLUMN_NOT_FOUND", "'x' kolonu yok.",
        hint="describe çıktısındaki adlardan birini seç.",
        candidates=["donem", "toplam"],
    )
    assert not r.ok and r.error is not None
    assert r.error.error_code == "COLUMN_NOT_FOUND"
    assert "HATA[COLUMN_NOT_FOUND]" in r.content
    assert "ADAYLAR: donem, toplam" in r.content
    assert "YAPACAĞIN:" in r.content


def test_cok_aday_kirpilir() -> None:
    r = ToolResult.fail("COLUMN_NOT_FOUND", "m", candidates=[f"c{i}" for i in range(15)])
    assert "+7 tane daha" in r.content
    assert r.error.candidates == [f"c{i}" for i in range(15)], "tam liste yapısal korunmalı"


def test_tekrar_denemeyle_cozulmeyen_hata_isaretlenir() -> None:
    """Modelin üsluptan anlaması beklenmiyor; açıkça söyleniyor."""
    r = ToolResult.fail("OUT_OF_COVERAGE", "2015 verisi yok.")
    assert not r.error.is_retryable
    assert "TEKRAR DENEMEYLE ÇÖZÜLMEZ" in r.content

    r2 = ToolResult.fail("MISSING_PERIOD_FILTER", "dönem filtresi yok")
    assert r2.error.is_retryable
    assert "TEKRAR DENEMEYLE ÇÖZÜLMEZ" not in r2.content


def test_retryable_acikca_gecilebilir() -> None:
    assert not ToolError("SQL_FAILED", "m", retryable=False).is_retryable
    assert ToolError("OUT_OF_COVERAGE", "m", retryable=True).is_retryable


def test_not_retryable_kumesi_beklendigi_gibi() -> None:
    """Küme bilerek sabitlenmiş: bir kod buraya ancak gerekçesiyle girer.

    ADR-0028 üç erişim kodu ekledi — aynı kaynağı aynı biçimde tekrar istemek sonucu
    değiştirmez; alternatif kaynak ayrı bir çağrıdır ve kararı harness verir.
    """
    assert NOT_RETRYABLE == {
        "OUT_OF_COVERAGE", "UNSAFE_SQL", "UNKNOWN_TOOL",
        "NEEDS_CREDENTIAL", "ACCESS_BLOCKED", "SOURCE_NOT_FOUND",
    }


def test_bilinmeyen_arac_aday_listeler() -> None:
    from kkb_agent.core.registry import ToolRegistry

    r = ToolRegistry().execute("olmayan_arac", {})
    assert r.error.error_code == "UNKNOWN_TOOL"
    assert not r.error.is_retryable


def test_gecersiz_argumanlar_sema_katmani() -> None:
    from pydantic import BaseModel

    from kkb_agent.core.tool import Tool

    class P(BaseModel):
        zorunlu: str

    class T(Tool):
        name, description, Params = "t", "d", P

        def run(self, params):  # pragma: no cover
            return ToolResult(content="ok")

    r = T().validate_and_run({})
    assert r.error.error_code == "INVALID_ARGS"
    assert r.error.layer == "schema"
    assert "zorunlu" in r.content


def test_arac_istisnasi_yutulmaz_kodlanir() -> None:
    from pydantic import BaseModel

    from kkb_agent.core.tool import Tool

    class P(BaseModel):
        x: str = "a"

    class T(Tool):
        name, description, Params = "t", "d", P

        def run(self, params):
            raise RuntimeError("beklenmedik")

    r = T().validate_and_run({})
    assert r.error.error_code == "TOOL_FAILED" and r.error.layer == "harness"
    assert r.error.is_retryable


def test_kod_dokumu_sayilabilir() -> None:
    from kkb_agent.core.agent import AgentAnswer, AgentStep

    ans = AgentAnswer(
        text="x",
        steps=[
            AgentStep(index=1, tool_name="a", error_code="SQL_FAILED", ok=False),
            AgentStep(index=2, tool_name="a", error_code="SQL_FAILED", ok=False),
            AgentStep(index=3, tool_name="b", error_code="EMPTY_RESULT", ok=False),
            AgentStep(index=4, tool_name="b", ok=True),
        ],
    )
    assert ans.error_codes() == {"SQL_FAILED": 2, "EMPTY_RESULT": 1}
