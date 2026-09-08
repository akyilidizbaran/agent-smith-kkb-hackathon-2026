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
    def openai_schema(self) -> dict[str, Any]:
        """Pydantic modelinden OpenAI function-calling şeması üretir.

        Elle JSON şema yazmıyoruz: parametre modeli değiştiğinde şema
        kendiliğinden güncellenir, tutarsızlık riski kalmaz.
        """
        schema = self.Params.model_json_schema()
        schema.pop("title", None)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

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
