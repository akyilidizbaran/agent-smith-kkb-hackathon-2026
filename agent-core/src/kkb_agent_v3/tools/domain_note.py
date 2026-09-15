"""lookup_domain_note — alan notu bölümünü isteğe bağlı çeker.

Yalnızca notlar prompt bütçesini aştığında kayıt edilir (loader.render_for_prompt
→ lookup_gerekli=True). Bütçe altındayken notlar zaten gömülü; bu aracın şeması
bile prompt'a girmez.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.tool import Tool, ToolResult
from ..domain.loader import DomainKnowledge
from ..errors import ToolError


class LookupParams(BaseModel):
    topic: str = Field(description="Dizindeki başlık ya da ona yakın birkaç kelime")


class LookupDomainNoteTool(Tool):
    name = "lookup_domain_note"
    description = (
        "Alan notları dizinindeki bir başlığın içeriğini getirir. Bir kuralı, düzenleme tarihini "
        "ya da anlatım şablonunu bilmen gerektiğinde çağır; dizinde olmayan konu için çağırma."
    )
    Params = LookupParams

    def __init__(self, knowledge: DomainKnowledge) -> None:
        self.knowledge = knowledge

    def validate_refs(self, params: LookupParams) -> ToolError | None:
        body, cands = self.knowledge.lookup(params.topic)
        if body is None:
            return ToolError(
                error_code="INVALID_ARGS", layer="reference",
                message=f"'{params.topic}' başlıklı alan notu yok.",
                candidates=cands, hint="Dizindeki başlıklardan birini kullan.",
            )
        return None

    def run(self, params: LookupParams) -> ToolResult:
        body, matched = self.knowledge.lookup(params.topic)
        return ToolResult(content=f"[{matched[0]}]\n{body}")
