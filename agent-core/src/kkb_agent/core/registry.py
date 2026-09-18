"""ToolRegistry — araçların kayıt defteri.

Yeni bir yetenek eklemek = yeni bir Tool sınıfı yazıp register etmek.
Agent kodunda hiçbir değişiklik gerekmez.
"""

from __future__ import annotations

from typing import Iterable, Any, Iterator

from ..domain import DomainProfile
from .tool import Tool, ToolResult
from .validator import BoundaryValidator


class ToolRegistry:
    def __init__(
        self,
        profile: DomainProfile | None = None,
        validator: BoundaryValidator | None = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._schema_cache: dict[tuple[int, tuple[str, ...] | None], list[dict[str, Any]]] = {}
        # Araç açıklamaları modele gönderilmeden önce bu profille doldurulur.
        self.profile = profile or DomainProfile.generic()
        # Her çağrı aynı boru hattından: şema → SQL guard → referans → politika → run.
        self.validator = validator or BoundaryValidator()
        # Cevaplanmakta olan soru. Bazı araçlar sonucu soruyla karşılaştırıp
        # eksik kalan bir kısıtı fark edebilir (ör. atlanan dönem filtresi).
        self.active_question: str = ""
        # Konuşma boyunca kullanıcının yazdığı her şey (niyet kapısı, ADR-0037): yazma ve
        # dışarı çıkma yeteneği olan araçlar adresi yalnız buradan kabul eder.
        self.user_text: str = ""
        # D03 (ADR-0068): bu turun kullanıcı mesajı ve tur sayacı; kalıcı yazma onayı yalnız buna bakar.
        self.current_message: str = ""
        self.turn: int = 0
        from .approvals import ApprovalBook
        self.approvals = ApprovalBook()
        # Kullanıcının istediği bir aramanın döndürdüğü adresler; web_url için onaylı sayılır.
        self.sanctioned_locators: set[str] = set()

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"'{tool.name}' adlı araç zaten kayıtlı.")
        self._tools[tool.name] = tool
        self._schema_cache.clear()

    def register_all(self, tools: list[Tool]) -> None:
        for t in tools:
            self.register(t)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def initial_phase_names(self) -> frozenset[str]:
        """Names explicitly marked as safe for the first planning phase."""
        return frozenset(
            tool.name for tool in self._tools.values()
            if bool(getattr(tool, "initial_phase", False))
        )

    def schemas(self, only: Iterable[str] | None = None) -> list[dict[str, Any]]:
        """Modele sunulan şemalar; `only` verilirse araç kapısının alt kümesi (ADR-0043)."""
        names = None if only is None else tuple(sorted(set(only)))
        key = (id(self.profile), names)
        cached = self._schema_cache.get(key)
        if cached is not None:
            return cached
        allowed = set(names) if names is not None else None
        schemas = [t.openai_schema(self.profile) for t in self._tools.values()
                   if allowed is None or t.name in allowed]
        self._schema_cache[key] = schemas
        return schemas

    def describe(self, only: Iterable[str] | None = None) -> str:
        """Native tool-calling desteklemeyen modeller için metin katalog."""
        names = set(only) if only is not None else None
        return "\n".join(
            f"- {t.name}: {self.profile.render(t.description)}" for t in self._tools.values()
            if names is None or t.name in names
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
        return self.validator.validate_and_run(tool, args)

    def begin_turn(self, turn_id: int) -> None:
        """Notify registered tools that a fresh user turn has started."""
        for tool in self._tools.values():
            tool.begin_turn(turn_id)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)
