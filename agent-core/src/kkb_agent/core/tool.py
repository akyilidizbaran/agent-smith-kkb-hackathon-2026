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
from .errors import ErrorCode, ToolError


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
    error: ToolError | None = None  # ok=False ise dolu

    @classmethod
    def fail(
        cls,
        error_code: ErrorCode,
        message: str,
        *,
        hint: str | None = None,
        candidates: list[str] | None = None,
        layer: str = "data",
        retryable: bool | None = None,
    ) -> ToolResult:
        """Hata da bir sonuçtur: modele geri verilir ki kendini onarsın.

        Kod ve onarılabilirlik bilgisi harness'a; mesaj ve ipucu modele gider.
        """
        err = ToolError(
            error_code=error_code,
            message=message,
            hint=hint,
            candidates=list(candidates or []),
            layer=layer,  # type: ignore[arg-type]
            retryable=retryable,
        )
        return cls(content=err.render(), ok=False, error=err)


class Tool(ABC):
    """Tüm araçların ortak sözleşmesi."""

    name: str
    description: str
    Params: type[BaseModel]
    #: İzde görünen rol. Katalog araçları `retrieve`, iş yapanlar `execute`.
    #: Planner LLM'in kendisidir, Validator `core/validator.py`, Narrator son tur —
    #: dördü de rol olarak tutuluyor, ayrı agent olarak değil.
    role: str = "execute"

    @abstractmethod
    def run(self, params: BaseModel) -> ToolResult:
        """Aracın işini yapar. DOĞRULANMIŞ parametrelerle çağrılır: referans ve politika
        kontrolleri buraya gelmeden `BoundaryValidator`'da yapılmıştır."""

    def validate_refs(self, params: BaseModel) -> ToolError | None:
        """Referans katmanı: seri/kolon/tablo gerçekten var mı? Varsayılan: kontrol yok."""
        return None

    def check_policy(self, params: BaseModel) -> ToolError | None:
        """Politika katmanı: referansı sağlam çağrı yine de çalışmamalı mı? Varsayılan: yok."""
        return None

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
        """Ham LLM argümanlarını sınır doğrulayıcıdan geçirip çalıştırır.

        Küçük modeller sık sık eksik/yanlış tipte argüman üretir; yakalanan hata
        modele okunabilir biçimde döner ve model çağrıyı düzeltir — harness'ın
        'onarım' yeteneği budur. Katmanların sırası `core/validator.py`'da.
        """
        from .validator import DEFAULT_VALIDATOR  # döngüsel import: validator bu modülü tanır

        return DEFAULT_VALIDATOR.validate_and_run(self, raw_args)
