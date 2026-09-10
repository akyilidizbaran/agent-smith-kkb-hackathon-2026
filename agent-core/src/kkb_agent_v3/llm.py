"""V3 LLM istemcisi — ekip istemcisinin alt sınıfı, iki ek.

1. `extra`: tur bazında geçici ayar (E6: 2. ardışık hatada `reasoning_effort=low`).
   MIA ölçümü [EMP]: `reasoning_effort=low` thinking'i açıyor; o zaman
   `chat_template_kwargs.enable_thinking=false` kaldırılmalı.
2. Yalnız GEÇİCİ hatalar tekrar denenir (429, 5xx, bağlantı, zaman aşımı).
   400/401/403/404 aynı isteğe aynı cevabı verir; beklemek gecikme ekler.

Ekip sınıfı değişmez; bu sınıf `chat`'i yeniden tanımlar.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, RateLimitError

from kkb_agent.llm.base import ChatMessage, LLMResponse, ToolCall
from kkb_agent.llm.openai_compat import OpenAICompatClient

log = logging.getLogger(__name__)


class V3LLMClient(OpenAICompatClient):
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        body: dict[str, Any] = {}
        if self._disable_thinking:
            body = {"reasoning_effort": "none", "chat_template_kwargs": {"enable_thinking": False}}
        if extra:
            body.update(extra)
            if extra.get("reasoning_effort") not in (None, "none"):
                body.pop("chat_template_kwargs", None)
        if body:
            payload["extra_body"] = body
        if tools and self._native_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_err: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._client.chat.completions.create(**payload)
                choice = resp.choices[0]
                raw_calls = getattr(choice.message, "tool_calls", None) or []
                usage = {}
                if resp.usage:
                    usage = {"prompt": resp.usage.prompt_tokens, "completion": resp.usage.completion_tokens}
                return LLMResponse(
                    content=choice.message.content or "",
                    tool_calls=[ToolCall.from_openai(tc) for tc in raw_calls],
                    finish_reason=choice.finish_reason,
                    usage=usage,
                )
            except APIError as exc:
                last_err = exc
                status = getattr(exc, "status_code", None)
                transient = isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)) or (
                    isinstance(exc, APIStatusError) and status is not None and status >= 500
                )
                if not transient:
                    raise
                wait = min(2**attempt, 15)
                if isinstance(exc, RateLimitError):
                    ra = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after")
                    if ra and str(ra).isdigit():
                        wait = min(int(ra), 60)
                log.warning("LLM çağrısı başarısız (deneme %d/%d): %s — %ss", attempt, self._max_retries, exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"LLM {self._max_retries} denemede yanıt vermedi: {last_err}")
