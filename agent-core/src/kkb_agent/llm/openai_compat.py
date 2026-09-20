"""OpenAI-uyumlu tek istemci: Ollama (geliştirme) ve Kloudeks (demo).

Sağlayıcıyı değiştirmek için kod değil, .env değişir.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import APIError, OpenAI, RateLimitError

from .base import ChatMessage, LLMResponse, ToolCall

log = logging.getLogger(__name__)


class OpenAICompatClient:
    """OpenAI protokolü konuşan herhangi bir sunucuya bağlanır."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float = 180.0,
        max_retries: int = 2,
        native_tools: bool = True,
        disable_thinking: bool = False,
    ) -> None:
        # SDK'nın kendi tekrar denemesi KAPALI (M15-T03): varsayılan 2 deneme bizim döngümüzün içinde çarpılıyordu
        # (3 × 3 × zaman aşımı). Tekrar politikası tek yerde, aşağıda.
        self._client = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout, max_retries=0)
        self.timeout = timeout
        self.model = model
        self.base_url = base_url
        self._max_retries = max_retries
        self._native_tools = native_tools
        self._deadline: float | None = None
        self._temporary_disable_thinking: bool | None = None
        # Provider-call diagnostics are metadata-only; prompt and response text
        # are never copied into logs or telemetry.
        self.last_call_metrics: dict[str, Any] = {}
        # Reasoning modelleri (qwen3, deepseek-r1 sınıfı) her turda uzun bir düşünce
        # zinciri üretir. Araç seçimi gibi kısa kararlarda bu sadece gecikme yaratır;
        # ilk ölçümde adım başına 26-60 sn'nin büyük kısmı buradan geliyordu.
        self._disable_thinking = disable_thinking

    def set_deadline(self, deadline: float | None) -> None:
        """Set a per-question monotonic deadline for all internal retries."""
        self._deadline = deadline

    def set_thinking(self, disabled: bool | None) -> None:
        """Temporarily override reasoning for one harness call.

        ``None`` restores the configured global setting.  The agent uses this
        only for the first low-risk tool-selection call; later data and
        narration calls keep the user's configured reasoning behavior.
        """
        self._temporary_disable_thinking = disabled

    def supports_native_tools(self) -> bool:
        return self._native_tools

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        call_started = time.perf_counter()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        disable_thinking = (
            self._disable_thinking
            if self._temporary_disable_thinking is None
            else self._temporary_disable_thinking
        )
        if disable_thinking:
            # Reasoning zincirini kapat. Ölçüm (2026-09-08, qwen3:8b, M5):
            # varsayılan 12.7s / 162 token  →  reasoning_effort=none 0.5s / 4 token.
            # Araç seçimi gibi kısa kararlarda düşünce zinciri sadece gecikme üretiyordu.
            # 'reasoning_effort' OpenAI-standart bir alan olduğu için Kloudeks'te de
            # geçerli olması beklenir; tanımayan sunucu extra_body içeriğini yok sayar.
            payload["extra_body"] = {
                "reasoning_effort": "none",
                "chat_template_kwargs": {"enable_thinking": False},
            }
        if tools and self._native_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_err: Exception | None = None
        attempts_made = 0
        retry_wait_ms = 0.0
        self.last_call_metrics = {
            "attempts": 0,
            "retry_count": 0,
            "retry_wait_ms": 0.0,
            "request_id": None,
            "first_token_ms": None,
            "status": "pending",
        }
        for attempt in range(1, self._max_retries + 1):
            remaining = None
            if self._deadline is not None:
                remaining = self._deadline - time.perf_counter()
                if remaining <= 0:
                    break
            try:
                attempts_made = attempt
                client = self._client
                if remaining is not None:
                    client = client.with_options(timeout=min(self.timeout, max(0.1, remaining)))
                resp = client.chat.completions.create(**payload)
                choice = resp.choices[0]
                raw_calls = getattr(choice.message, "tool_calls", None) or []
                usage: dict[str, Any] = {}
                if resp.usage:
                    usage = {
                        "prompt": resp.usage.prompt_tokens,
                        "completion": resp.usage.completion_tokens,
                    }
                    details = getattr(resp.usage, "prompt_tokens_details", None)
                    cached_tokens = getattr(details, "cached_tokens", None) if details else None
                    if cached_tokens is not None:
                        usage["cached_prompt"] = int(cached_tokens)
                request_id = getattr(resp, "_request_id", None)
                duration_ms = (time.perf_counter() - call_started) * 1000
                self.last_call_metrics = {
                    "attempts": attempts_made,
                    "retry_count": max(0, attempts_made - 1),
                    "retry_wait_ms": retry_wait_ms,
                    "request_id": request_id,
                    # Non-streaming responses do not expose time-to-first-token.
                    "first_token_ms": None,
                    "duration_ms": duration_ms,
                    "status": "ok",
                }
                usage.update({
                    "provider_attempts": attempts_made,
                    "provider_retry_count": max(0, attempts_made - 1),
                    "provider_retry_wait_ms": round(retry_wait_ms, 3),
                    "provider_request_id": request_id,
                })
                return LLMResponse(
                    content=choice.message.content or "",
                    tool_calls=[ToolCall.from_openai(tc) for tc in raw_calls],
                    finish_reason=choice.finish_reason,
                    usage=usage,
                )
            except APIError as exc:
                last_err = exc
                status = getattr(exc, "status_code", None)
                if status is not None and 400 <= int(status) < 500 and int(status) not in (408, 409, 429):
                    raise                     # istek hatası: tekrar denemek sonucu değiştirmez
                if attempt >= self._max_retries:
                    break
                # Mentör: kota yok ama retry/backoff olsun. 429'da sunucunun
                # Retry-After'ı varsa ona uy; yoksa üstel bekleme (2,4,8… ≤15 s).
                wait = min(2**attempt, 15)
                if isinstance(exc, RateLimitError):
                    ra = (getattr(exc, "response", None) or {}) and exc.response.headers.get("retry-after")
                    if ra and str(ra).isdigit():
                        wait = min(int(ra), 60)
                if self._deadline is not None:
                    remaining = self._deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    wait = min(wait, max(0.0, remaining))
                retry_wait_ms += wait * 1000
                log.warning(
                    "LLM çağrısı başarısız (deneme %d/%d): %s — %ss bekleniyor",
                    attempt,
                    self._max_retries,
                    exc,
                    wait,
                )
                if wait:
                    time.sleep(wait)

        duration_ms = (time.perf_counter() - call_started) * 1000
        request = getattr(last_err, "request_id", None) if last_err is not None else None
        self.last_call_metrics = {
            "attempts": attempts_made,
            "retry_count": max(0, attempts_made - 1),
            "retry_wait_ms": retry_wait_ms,
            "request_id": request,
            "first_token_ms": None,
            "duration_ms": duration_ms,
            "status": "error",
            "error_type": type(last_err).__name__ if last_err is not None else "deadline_exhausted",
        }
        detail = str(last_err) if last_err is not None else "çağrı başlamadan süre bütçesi doldu"
        raise RuntimeError(f"LLM {attempts_made} denemede yanıt vermedi: {detail}")

    def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Collect a text-only streamed answer and measure first visible token.

        This is intentionally separate from ``chat``: the harness enables it
        only for verified, tool-free narration. OpenAI-compatible providers
        differ in streaming/usage support, so callers can keep it disabled
        until their endpoint passes a live canary.
        """
        call_started = time.perf_counter()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_openai() for message in messages],
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        disable_thinking = (
            self._disable_thinking
            if self._temporary_disable_thinking is None
            else self._temporary_disable_thinking
        )
        if disable_thinking:
            payload["extra_body"] = {
                "reasoning_effort": "none",
                "chat_template_kwargs": {"enable_thinking": False},
            }

        last_err: Exception | None = None
        attempts_made = 0
        retry_wait_ms = 0.0
        first_token_ms: float | None = None
        self.last_call_metrics = {
            "attempts": 0,
            "retry_count": 0,
            "retry_wait_ms": 0.0,
            "request_id": None,
            "first_token_ms": None,
            "status": "pending",
            "streaming": True,
        }
        for attempt in range(1, self._max_retries + 1):
            remaining = None
            if self._deadline is not None:
                remaining = self._deadline - time.perf_counter()
                if remaining <= 0:
                    break
            stream = None
            try:
                attempts_made = attempt
                client = self._client
                if remaining is not None:
                    client = client.with_options(timeout=min(self.timeout, max(0.1, remaining)))
                stream = client.chat.completions.create(**payload)
                content: list[str] = []
                usage: dict[str, Any] = {}
                finish_reason: str | None = None
                for chunk in stream:
                    choices = getattr(chunk, "choices", None) or []
                    if choices:
                        choice = choices[0]
                        delta = getattr(choice, "delta", None)
                        text = getattr(delta, "content", None) if delta is not None else None
                        if text:
                            if first_token_ms is None:
                                first_token_ms = (time.perf_counter() - call_started) * 1000
                            content.append(str(text))
                        if getattr(choice, "finish_reason", None):
                            finish_reason = choice.finish_reason
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage is not None:
                        usage = {
                            "prompt": int(getattr(chunk_usage, "prompt_tokens", 0) or 0),
                            "completion": int(getattr(chunk_usage, "completion_tokens", 0) or 0),
                        }
                        details = getattr(chunk_usage, "prompt_tokens_details", None)
                        cached = getattr(details, "cached_tokens", None) if details else None
                        if cached is not None:
                            usage["cached_prompt"] = int(cached)

                response = getattr(stream, "response", None)
                headers = getattr(response, "headers", {}) or {}
                request_id = (
                    getattr(stream, "_request_id", None)
                    or headers.get("x-request-id")
                    or headers.get("request-id")
                )
                duration_ms = (time.perf_counter() - call_started) * 1000
                self.last_call_metrics = {
                    "attempts": attempts_made,
                    "retry_count": max(0, attempts_made - 1),
                    "retry_wait_ms": retry_wait_ms,
                    "request_id": request_id,
                    "first_token_ms": first_token_ms,
                    "duration_ms": duration_ms,
                    "status": "ok",
                    "streaming": True,
                    "usage_available": bool(usage),
                }
                usage.update({
                    "first_token_ms": first_token_ms,
                    "provider_attempts": attempts_made,
                    "provider_retry_count": max(0, attempts_made - 1),
                    "provider_retry_wait_ms": round(retry_wait_ms, 3),
                    "provider_request_id": request_id,
                    "streaming": True,
                })
                return LLMResponse(
                    content="".join(content),
                    finish_reason=finish_reason,
                    usage=usage,
                )
            except APIError as exc:
                last_err = exc
                status = getattr(exc, "status_code", None)
                detail = str(exc).lower()
                if status in (400, 422) and ("stream" in detail or "stream_options" in detail):
                    # Some nominally OpenAI-compatible servers do not implement
                    # streamed usage options. Retry once through the known
                    # non-streaming path; correctness still takes precedence.
                    fallback = self.chat(messages, temperature=temperature, max_tokens=max_tokens)
                    fallback.usage["stream_fallback"] = True
                    fallback.usage["streaming"] = False
                    self.last_call_metrics["stream_fallback"] = True
                    return fallback
                if status is not None and 400 <= int(status) < 500 and int(status) not in (408, 409, 429):
                    raise
                if attempt >= self._max_retries:
                    break
                wait = min(2**attempt, 15)
                if isinstance(exc, RateLimitError):
                    response = getattr(exc, "response", None)
                    retry_after = response.headers.get("retry-after") if response is not None else None
                    if retry_after and str(retry_after).isdigit():
                        wait = min(int(retry_after), 60)
                if self._deadline is not None:
                    remaining = self._deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    wait = min(wait, max(0.0, remaining))
                retry_wait_ms += wait * 1000
                log.warning(
                    "LLM akış çağrısı başarısız (deneme %d/%d): %s — %ss bekleniyor",
                    attempt,
                    self._max_retries,
                    exc,
                    wait,
                )
                if wait:
                    time.sleep(wait)
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

        duration_ms = (time.perf_counter() - call_started) * 1000
        request_id = getattr(last_err, "request_id", None) if last_err is not None else None
        self.last_call_metrics = {
            "attempts": attempts_made,
            "retry_count": max(0, attempts_made - 1),
            "retry_wait_ms": retry_wait_ms,
            "request_id": request_id,
            "first_token_ms": first_token_ms,
            "duration_ms": duration_ms,
            "status": "error",
            "error_type": type(last_err).__name__ if last_err is not None else "deadline_exhausted",
            "streaming": True,
        }
        detail = str(last_err) if last_err is not None else "çağrı başlamadan süre bütçesi doldu"
        raise RuntimeError(f"LLM akış çağrısı {attempts_made} denemede yanıt vermedi: {detail}")
