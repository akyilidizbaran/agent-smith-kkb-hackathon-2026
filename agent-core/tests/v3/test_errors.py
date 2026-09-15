from __future__ import annotations

from kkb_agent_v3.errors import DEFAULT_RETRYABLE, ToolError


def test_varsayilan_retry_koddan_gelir() -> None:
    assert ToolError(error_code="UNSAFE_SQL", message="x").is_retryable is False
    assert ToolError(error_code="SERIES_NOT_FOUND", message="x").is_retryable is True
    assert ToolError(error_code="OUT_OF_COVERAGE", message="x").is_retryable is False


def test_arac_gerekcesi_varsayilani_ezer() -> None:
    assert ToolError(error_code="SERIES_NOT_FOUND", message="x", retryable=False).is_retryable is False


def test_gozlem_kisa_ve_yapili() -> None:
    e = ToolError(error_code="SERIES_NOT_FOUND", message="'foo' yok.", candidates=["a", "b", "c", "d", "e", "f"],
                  hint="Adaylardan birini kullan.")
    obs = e.observation()
    assert obs.startswith("SERIES_NOT_FOUND: 'foo' yok.")
    assert "Adaylar: a | b | c | d | e" in obs and " f" not in obs.split("Adaylar:")[1].split("\n")[0]
    assert "YAPACAĞIN: Adaylardan birini kullan." in obs
    assert "tekrar denemeyle çözülmez" not in obs


def test_retry_edilemez_hata_bunu_soyler() -> None:
    obs = ToolError(error_code="POLICY_VIOLATION", message="yasak").observation()
    assert "tekrar denemeyle çözülmez" in obs


def test_tum_kodlarin_varsayilani_var() -> None:
    from typing import get_args

    from kkb_agent_v3.errors import ErrorCode

    for code in get_args(ErrorCode):
        assert code in DEFAULT_RETRYABLE, code
