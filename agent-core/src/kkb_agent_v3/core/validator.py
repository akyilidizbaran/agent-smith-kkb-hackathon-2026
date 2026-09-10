"""Sınır doğrulayıcı — her araç çağrısı üç katmandan geçer (V3 §3.3).

    şema  → referans → politika → run

1. Şema: Pydantic. Eksik/yanlış tip → INVALID_ARGS + alan listesi.
2. Referans: aracın `validate_refs`'i. Seri/kolon var mı, dönem kapsamda mı,
   tip uyumlu mu. Şema doğrulaması "şekli" doğrular, "referansı" değil;
   halüsine argümanlar şemadan geçip retry ile temiz iz bırakır [SRC].
3. Politika: aracın `check_policy`'si + genel kurallar (`sql` alanı varsa
   ekip adaptörünün `guard_sql`'i). Politika ihlali retryable=False.

Kayıt defteri (ToolRegistry) de burada: ekip motorundaki ile aynı arayüz,
yürütme yolu doğrulayıcıdan geçer.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from pydantic import BaseModel, ValidationError

from kkb_agent.adapters.duckdb_lakehouse import guard_sql
from kkb_agent.contracts.lakehouse import LakehouseError
from kkb_agent.domain import DomainProfile

from ..errors import ToolError
from .tool import Tool, ToolResult

log = logging.getLogger(__name__)


class BoundaryValidator:
    """Araç çağrısını katman katman doğrular, geçerse çalıştırır."""

    def validate(self, tool: Tool, raw_args: dict[str, Any]) -> tuple[BaseModel | None, ToolError | None]:
        # 1. şema
        try:
            params = tool.Params(**raw_args)
        except ValidationError as exc:
            fields = sorted({".".join(str(p) for p in e.get("loc", ())) or "?" for e in exc.errors()})
            props = list(tool.Params.model_json_schema().get("properties", {}))
            return None, ToolError(
                error_code="INVALID_ARGS",
                layer="schema",
                message=f"'{tool.name}' parametreleri geçersiz: {', '.join(fields)}.",
                hint=f"Beklenen alanlar: {', '.join(props)}.",
                candidates=props[:5],
            )
        except Exception as exc:  # noqa: BLE001 — __raw__ gibi bozuk JSON durumları
            return None, ToolError(
                error_code="INVALID_ARGS", layer="schema",
                message=f"'{tool.name}' argümanları okunamadı: {type(exc).__name__}.",
                hint="Argümanları geçerli JSON nesnesi olarak ver.",
            )

        # 2a. politika/statik — SQL güvenlik guard'ı REFERANSTAN ÖNCE: yasak bir ifadenin
        # referanslarını doğrulamak anlamsız; "dönem filtresi ekle" deyip DROP'u tekrar
        # denetmek bir tur yakar. Sıra: şema → SQL guard → referans → araç politikası.
        sql = getattr(params, "sql", None)
        if isinstance(sql, str):
            try:
                guard_sql(sql)
            except LakehouseError as exc:
                return params, ToolError(
                    error_code="UNSAFE_SQL", layer="policy", message=str(exc),
                    hint="Yalnızca tek bir SELECT/WITH sorgusu; veri değiştiren ifade ve dosya/ağ erişimi yok.",
                    retryable=False,
                )

        # 2b. referans
        try:
            err = tool.validate_refs(params)
        except LakehouseError as exc:
            err = ToolError(error_code="SERIES_NOT_FOUND", layer="reference", message=str(exc))
        if err is not None:
            err.layer = err.layer or "reference"
            return params, err

        # 3. politika/araç — index kilidi, satır limiti, side-effect
        err = tool.check_policy(params)
        if err is not None:
            err.layer = err.layer or "policy"
            if err.retryable is None:
                err.retryable = False
            return params, err
        return params, None

    def validate_and_run(self, tool: Tool, raw_args: dict[str, Any]) -> ToolResult:
        params, err = self.validate(tool, raw_args)
        if err is not None:
            log.info("validator %s/%s: %s", tool.name, err.layer, err.error_code)
            return ToolResult.fail(err)
        assert params is not None
        try:
            return tool.run(params)
        except LakehouseError as exc:
            return ToolResult.fail(ToolError(
                error_code="TOOL_FAILED", layer="runtime",
                message=f"'{tool.name}' veri katmanı hatası: {exc}",
                hint="Hata mesajını oku, argümanı düzelt ve bir kez daha dene.",
            ))
        except Exception as exc:  # noqa: BLE001
            log.exception("araç istisnası: %s", tool.name)
            return ToolResult.fail(ToolError(
                error_code="TOOL_FAILED", layer="runtime",
                message=f"'{tool.name}' çalışırken hata: {type(exc).__name__}: {str(exc)[:160]}",
            ))


class ToolRegistry:
    """Araç kayıt defteri; yürütme sınır doğrulayıcıdan geçer."""

    def __init__(self, profile: DomainProfile | None = None, validator: BoundaryValidator | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self.profile = profile or DomainProfile.generic()
        self.validator = validator or BoundaryValidator()
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
        return "\n".join(f"- {t.name}: {self.profile.render(t.description)}" for t in self._tools.values())

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult.fail(ToolError(
                error_code="UNKNOWN_TOOL", layer="schema",
                message=f"'{name}' adlı bir araç yok.",
                candidates=self.names()[:5],
                hint="Adaylardan birini birebir kullan.",
            ))
        return self.validator.validate_and_run(tool, args)

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)
