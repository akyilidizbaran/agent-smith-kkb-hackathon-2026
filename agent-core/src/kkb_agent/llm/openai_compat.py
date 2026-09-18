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
        for attempt in range(1, self._max_retries + 1):
            remaining = None
            if self._deadline is not None:
                remaining = self._deadline - time.perf_counter()
                if remaining <= 0:
                    break
            try:
                client = self._client
                if remaining is not None:
                    client = client.with_options(timeout=min(self.timeout, max(0.1, remaining)))
                resp = client.chat.completions.create(**payload)
                choice = resp.choices[0]
                raw_calls = getattr(choice.message, "tool_calls", None) or []
                return LLMResponse(
                    content=choice.message.content or "",
                    tool_calls=[ToolCall.from_openai(tc) for tc in raw_calls],
                    finish_reason=choice.finish_reason,
                    usage=(
                        {
                            "prompt": resp.usage.prompt_tokens,
                            "completion": resp.usage.completion_tokens,
                        }
                        if resp.usage
                        else {}
                    ),
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
                log.warning(
                    "LLM çağrısı başarısız (deneme %d/%d): %s — %ss bekleniyor",
                    attempt,
                    self._max_retries,
                    exc,
                    wait,
                )
                if wait:
                    time.sleep(wait)

        raise RuntimeError(f"LLM {self._max_retries} denemede yanıt vermedi: {last_err}")
