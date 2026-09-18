"""Provider-independent harness latency contracts."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.agent import _is_llm_outage  # noqa: E402
from kkb_agent.llm.openai_compat import OpenAICompatClient  # noqa: E402
from openai import APITimeoutError  # noqa: E402


class _AlwaysTimeout:
    def __init__(self) -> None:
        self.timeouts: list[float] = []
        self.chat = self
        self.completions = self

    def with_options(self, *, timeout: float):
        self.timeouts.append(timeout)
        return self

    def create(self, **kwargs):
        raise APITimeoutError(request=None)


class _Success:
    def __init__(self) -> None:
        self.chat = self
        self.completions = self
        self.kwargs = None

    def with_options(self, *, timeout: float):
        return self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="hazır", tool_calls=[]),
                finish_reason="stop",
            )],
            usage=None,
        )


def test_provider_retryler_toplam_deadlineyi_asamaz() -> None:
    client = OpenAICompatClient("http://example.invalid/v1", "x", "model", timeout=90, max_retries=2)
    fake = _AlwaysTimeout()
    client._client = fake  # provider çağrısı yerine deterministik test doubles
    client.set_deadline(time.perf_counter() + 0.05)

    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="LLM 2 denemede"):
        client.chat([])
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert fake.timeouts and max(fake.timeouts) <= 0.1


def test_sarmalanmis_llm_timeout_agent_kesintisi_sayilir():
    assert _is_llm_outage(RuntimeError("LLM 2 denemede yanıt vermedi: Request timed out."))


def test_ilk_planlama_cagrisi_gecici_reasoning_kapatabilir():
    client = OpenAICompatClient("http://example.invalid/v1", "x", "model", timeout=5, max_retries=1)
    fake = _Success()
    client._client = fake

    client.set_thinking(True)
    response = client.chat([])
    assert response.content == "hazır"
    assert fake.kwargs["extra_body"]["reasoning_effort"] == "none"

    client.set_thinking(None)
    client.chat([])
    assert "extra_body" not in fake.kwargs
