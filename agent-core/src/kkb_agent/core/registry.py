"""ToolRegistry — araçların kayıt defteri.

Yeni bir yetenek eklemek = yeni bir Tool sınıfı yazıp register etmek.
Agent kodunda hiçbir değişiklik gerekmez.
"""

from __future__ import annotations

from typing import Any, Iterator

from ..domain import DomainProfile
from .tool import Tool, ToolResult


class ToolRegistry:
    def __init__(self, profile: DomainProfile | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        # Araç açıklamaları modele gönderilmeden önce bu profille doldurulur.
        self.profile = profile or DomainProfile.generic()
        # Cevaplanmakta olan soru. Bazı araçlar sonucu soruyla karşılaştırıp
        # eksik kalan bir kısıtı fark edebilir (ör. atlanan dönem filtresi).
        self.active_question: str = ""

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"'{tool.name}' adlı araç zaten kayıtlı.")
        self._tools[tool.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.openai_schema(self.profile) for t in self._tools.values()]

    def describe(self) -> str:
        """Native tool-calling desteklemeyen modeller için metin katalog."""
        return "\n".join(
            f"- {t.name}: {self.profile.render(t.description)}" for t in self._tools.values()
        )

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult.fail(
                "UNKNOWN_TOOL",
                f"'{name}' adlı bir araç yok.",
                hint="Yalnızca listelenen araçlardan birini çağır.",
                candidates=self.names(),
                layer="schema",
            )
        return tool.validate_and_run(args)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)
