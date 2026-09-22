"""LLM katmanı için sağlayıcıdan bağımsız tipler.

Geliştirmeyi yerel Ollama ile, demoyu Kloudeks ile yapacağız. İkisi de
OpenAI-uyumlu protokol konuştuğu için tek bir istemci yeterli; sadece
base_url / api_key / model değişir. Agent kodu hiçbir yerde sağlayıcı adı
görmez.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    """Modelin çağırmak istediği araç."""

    id: str
    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_openai(cls, raw: Any) -> ToolCall:
        try:
            args = json.loads(raw.function.arguments or "{}")
        except json.JSONDecodeError:
            # Küçük modeller bozuk JSON üretebiliyor; ham metni saklayıp
            # onarım adımına bırakıyoruz.
            args = {"__raw__": raw.function.arguments}
        return cls(id=raw.id, name=raw.function.name, arguments=args)


@dataclass
class ChatMessage:
    role: Role
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.name:
            msg["name"] = self.name
        return msg


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


class LLMClient(Protocol):
    """Agent'ın gördüğü tek LLM arayüzü."""

    model: str

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...

    def supports_native_tools(self) -> bool:
        """Sağlayıcı/model gerçekten tool-calling destekliyor mu?

        Desteklemiyorsa harness JSON-protokol moduna düşer. Kloudeks'te
        hangi modelin ne desteklediğini demo öncesi ölçüp buradan yöneteceğiz.
        """
        ...
