"""Tool soyutlaması — motorun genişletilebilirliğinin taşıyıcısı.

Yarışma 6 aracı minimum olarak istiyor (Lakehouse, Web Search, Web URL,
Anomali, Causality, Change Detection) ama asıl beklenti 'sınırsız sayıda tool
eklenebilen jenerik bir motor'. Bu yüzden araçlar merkezde tanımlı değil;
her biri bu sınıfı uygulayan bağımsız bir modüldür ve kayıt olduğu anda
agent tarafından kullanılabilir hale gelir.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import BaseModel

from ..contracts.lakehouse import QueryProvenance
from ..domain import DomainProfile


@dataclass
class ToolResult:
    """Bir araç çalıştırmasının sonucu.

    'content' modele geri verilir ve KISA olmalıdır: 60 aylık bir tabloyu
    modele geri yazmak context window'u yakar. Ham veri 'data' alanında
    workspace'e taşınır, model sadece özetini görür.
    """

    content: str
    ok: bool = True
    data: pd.DataFrame | None = None
    provenance: QueryProvenance | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)  # grafik verisi, dosya yolu vb.

    @classmethod
    def error(cls, message: str) -> ToolResult:
        """Hata da bir sonuçtur: modele geri verilir ki kendini onarsın."""
        return cls(content=f"HATA: {message}", ok=False)


class Tool(ABC):
    """Tüm araçların ortak sözleşmesi."""

    name: str
    description: str
    Params: type[BaseModel]

    @abstractmethod
    def run(self, params: BaseModel) -> ToolResult:
        """Aracın işini yapar. Doğrulanmış parametrelerle çağrılır."""

    # ---- harness tarafından kullanılır ----
    def openai_schema(self, profile: DomainProfile | None = None) -> dict[str, Any]:
        """Pydantic modelinden OpenAI function-calling şeması üretir.

        Elle JSON şema yazmıyoruz: parametre modeli değiştiğinde şema
        kendiliğinden güncellenir, tutarsızlık riski kalmaz.

        Açıklamalardaki `{example_table}` gibi yer tutucular alan profiliyle
        doldurulur. Bu şemalar her turda prompt'a giriyor; içlerine gömülü bir
        alan örneği motoru o alana bağlar (ADR-0012).
        """
        schema = self.Params.model_json_schema()
        schema.pop("title", None)
        if profile is not None:
            schema = self._render_schema(schema, profile)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (
                    profile.render(self.description) if profile else self.description
                ),
                "parameters": schema,
            },
        }

    @staticmethod
    def _render_schema(node: Any, profile: DomainProfile) -> Any:
        """JSON şemasındaki tüm `description` alanlarını profil ile doldurur."""
        if isinstance(node, dict):
            return {
                k: (profile.render(v) if k == "description" and isinstance(v, str)
                    else Tool._render_schema(v, profile))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [Tool._render_schema(v, profile) for v in node]
        return node

    def validate_and_run(self, raw_args: dict[str, Any]) -> ToolResult:
        """Ham LLM argümanlarını doğrular, sonra çalıştırır.

        Küçük modeller sık sık eksik/yanlış tipte argüman üretir. Burada
        yakalanan hata modele okunabilir biçimde geri döner ve model
        çağrıyı düzeltir — harness'ın 'onarım' yeteneği budur.
        """
        try:
            params = self.Params(**raw_args)
        except Exception as exc:
            return ToolResult.error(
                f"'{self.name}' aracının parametreleri geçersiz: {exc}. "
                f"Beklenen şema: {self.Params.model_json_schema().get('properties')}"
            )
        try:
            return self.run(params)
        except Exception as exc:
            return ToolResult.error(f"'{self.name}' çalışırken hata: {type(exc).__name__}: {exc}")
