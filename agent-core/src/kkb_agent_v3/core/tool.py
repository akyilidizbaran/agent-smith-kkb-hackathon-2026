"""Araç sözleşmesi (V3).

Ekip motorundaki `kkb_agent.core.tool.Tool` ile aynı fikir — Pydantic parametre
modeli, OpenAI şeması, modele kısa içerik — iki farkla:

1. Hata bir string değil `ToolError` zarfıdır (`ToolResult.error` alanı);
   `content` o zarfın kısa özetidir. Harness `retryable`'a göre karar verir.
2. Araç, referans doğrulamasını `validate_refs` ile bildirir; sınır
   doğrulayıcı (validator.py) bunu `run`'dan ÖNCE çağırır. Böylece "seri yok /
   kolon yok / dönem kapsam dışı" hataları araç gövdesine girmeden yakalanır.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import BaseModel

from kkb_agent.contracts.lakehouse import QueryProvenance
from kkb_agent.domain import DomainProfile

from ..errors import ToolError


@dataclass
class ToolResult:
    """Bir araç çalıştırmasının sonucu.

    `content` modele gider ve kısa olmalıdır; ham veri `data`'da kalır.
    """

    content: str
    ok: bool = True
    data: pd.DataFrame | None = None
    provenance: QueryProvenance | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)
    error: ToolError | None = None

    @classmethod
    def fail(cls, error: ToolError) -> ToolResult:
        return cls(content=error.observation(), ok=False, error=error)

    @property
    def error_code(self) -> str | None:
        return self.error.error_code if self.error else None


class Tool(ABC):
    """Tüm V3 araçlarının ortak sözleşmesi."""

    name: str
    description: str
    Params: type[BaseModel]
    # Analiz tablosunu değiştiren araçlar aynı turda sırayla çalışır; diğerleri paralel.
    mutates: bool = False

    @abstractmethod
    def run(self, params: BaseModel) -> ToolResult:
        """Doğrulanmış parametrelerle aracın işini yapar."""

    def validate_refs(self, params: BaseModel) -> ToolError | None:
        """Referans katmanı: seri/kolon/dönem gerçekten var mı? Varsayılan: kontrol yok."""
        return None

    def check_policy(self, params: BaseModel) -> ToolError | None:
        """Politika katmanı: index kilidi, satır limiti, side-effect. Varsayılan: kontrol yok."""
        return None

    # ---- harness tarafından kullanılır ----
    def openai_schema(self, profile: DomainProfile | None = None) -> dict[str, Any]:
        """Pydantic modelinden function-calling şeması; açıklamalar profille doldurulur (ADR-0012)."""
        schema = self.Params.model_json_schema()
        schema.pop("title", None)
        if profile is not None:
            schema = _render_schema(schema, profile)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": profile.render(self.description) if profile else self.description,
                "parameters": schema,
            },
        }


def _render_schema(node: Any, profile: DomainProfile) -> Any:
    if isinstance(node, dict):
        return {
            k: (profile.render(v) if k == "description" and isinstance(v, str)
                else _render_schema(v, profile))
            for k, v in node.items()
        }
    if isinstance(node, list):
        return [_render_schema(v, profile) for v in node]
    return node
