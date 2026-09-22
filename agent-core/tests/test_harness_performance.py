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
            _request_id="req_test_123",
        )


class _StreamSuccess:
    def __init__(self) -> None:
        self.chat = self
        self.completions = self
        self.kwargs = None
        self.response = SimpleNamespace(headers={"x-request-id": "req_stream_test"})

    def with_options(self, *, timeout: float):
        return self

    def create(self, **kwargs):
        self.kwargs = kwargs
        usage = SimpleNamespace(prompt_tokens=10, completion_tokens=3, prompt_tokens_details=None)
        class FakeStream:
            response = SimpleNamespace(headers={"x-request-id": "req_stream_test"})

            def __iter__(self):
                return iter([
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="ha"), finish_reason=None)], usage=None),
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="zır"), finish_reason="stop")], usage=None),
            SimpleNamespace(choices=[], usage=usage),
                ])

            def close(self):
                pass

        return FakeStream()


def test_provider_retryler_toplam_deadlineyi_asamaz() -> None:
    client = OpenAICompatClient("http://example.invalid/v1", "x", "model", timeout=90, max_retries=2)
    fake = _AlwaysTimeout()
    client._client = fake  # provider çağrısı yerine deterministik test doubles
    client.set_deadline(time.perf_counter() + 0.05)

    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="LLM 1 denemede"):
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
    assert response.usage["provider_request_id"] == "req_test_123"
    assert response.usage["provider_attempts"] == 1
    assert response.usage["provider_retry_count"] == 0
    assert client.last_call_metrics["status"] == "ok"
    assert client.last_call_metrics["first_token_ms"] is None
    assert fake.kwargs["extra_body"]["reasoning_effort"] == "none"

    client.set_thinking(None)
    client.chat([])
    assert "extra_body" not in fake.kwargs


def test_tool_free_stream_narration_measures_first_token_and_usage():
    client = OpenAICompatClient("http://example.invalid/v1", "x", "model", timeout=5, max_retries=1)
    fake = _StreamSuccess()
    client._client = fake

    response = client.chat_stream([], max_tokens=64)

    assert response.content == "hazır"
    assert response.usage["first_token_ms"] is not None
    assert response.usage["prompt"] == 10 and response.usage["completion"] == 3
    assert response.usage["provider_request_id"] == "req_stream_test"
    assert fake.kwargs["stream"] is True
    assert fake.kwargs["stream_options"] == {"include_usage": True}
    assert client.last_call_metrics["streaming"] is True


def test_varsayilan_provider_deneme_sayisi_uctur():
    """22 Eyl: PR #18 varsayılanı 2'ye indirmişti; paralel MIA koşusunda tek zaman aşımında vakalar düştü."""
    client = OpenAICompatClient("http://example.invalid/v1", "x", "model")
    assert client._max_retries == 3
