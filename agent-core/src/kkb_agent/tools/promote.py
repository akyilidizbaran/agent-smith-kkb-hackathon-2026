"""`promote_draft` — taslak seriyi kullanıcının onayıyla kataloğa ve Silver'a alan Architect kapısı.

Makine önerir, insan onaylar (ADR-0030). İnsan burada sohbetteki kullanıcı: "bu taslağı
onaylıyorum, kataloğa al" demeden bu araç çalışmaz (niyet kapısı, ADR-0037). Yazma yine
ayrı süreçte, veri ekibinin `promote-draft` komutuyla: taslak → aktif, satırlar adhoc →
Silver, provenance dokunulmamış. Semantik yine `derived`: onay doğrulama değildir; Gold bu
seriyi ancak kullanıcı açıkça "doğrulanmamış olsa da kullan" derse birleştirir.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from ..adapters.duckdb_lakehouse import release_connections
from ..adapters.lakehouse_cli import parse_kv
from ..builder.ingest import LakehouseCLI
from ..contracts.lakehouse import LakehouseClient, LakehouseError
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult

_CONFIRM = re.compile(
    r"\b(onayl[ıi]yorum|onayla|onaylayalım|kataloğa al|kataloga al|terfi ettir|yayınla|yayinla|"
    r"silver'?a al|aktif et|kabul ediyorum)\b", re.I,
)


def confirm_intent(user_text: str) -> bool:
    return bool(_CONFIRM.search(user_text or ""))


class PromoteParams(BaseModel):
    series_id: str = Field(description="Onaylanacak TASLAK serinin kimliği, ör. 'adhoc:sicaklik'")
    purpose: str = Field(description="Tek cümle: kullanıcı neyi onayladı")


class PromoteDraftTool(Tool):
    name = "promote_draft"
    role = "execute"
    description = (
        "Kullanıcının getirip taslak olarak eklenmiş bir seriyi, KULLANICI AÇIKÇA ONAYLADIĞINDA "
        "('onaylıyorum', 'kataloğa al', 'yayınla') kataloğa aktif seri olarak alır ve gözlemlerini "
        "Silver'a kopyalar; Gold hesapları o zaman mümkün olur. Kullanıcı onay vermediyse çağırma."
    )
    Params = PromoteParams

    def __init__(self, lakehouse: LakehouseClient, cli: LakehouseCLI, *, registry: object | None = None) -> None:
        self.lakehouse = lakehouse
        self.cli = cli
        self._registry = registry

    def _user_text(self) -> str:
        reg = self._registry
        return getattr(reg, "user_text", None) or getattr(reg, "active_question", "") or ""

    def validate_refs(self, params: PromoteParams) -> ToolError | None:
        try:
            spec = self.lakehouse.get_dataset(params.series_id)
        except LakehouseError as exc:
            return ToolError(error_code="DATASET_NOT_FOUND", message=str(exc), layer="reference",
                             hint="lakehouse_search ile taslak serinin kimliğini bul.")
        if spec.source != "adhoc" or not any("TASLAK" in n for n in spec.notes):
            return ToolError(
                error_code="DATASET_NOT_FOUND", layer="reference", retryable=False,
                message=f"'{params.series_id}' bir taslak değil (kaynak {spec.source}); yalnız taslak seriler onaylanır.",
            )
        return None

    def check_policy(self, params: PromoteParams) -> ToolError | None:
        text = self._user_text()
        key = params.series_id.split(":", 1)[-1]
        if not confirm_intent(text):
            return ToolError(
                error_code="INTENT_REQUIRED", layer="policy", retryable=False,
                message="Kullanıcı taslağı açıkça onaylamadı ('onaylıyorum', 'kataloğa al' gibi bir ifade yok).",
                hint="Kullanıcıya taslağın eşleme ve anlamını özetleyip onay iste; onaylarsa bu aracı yeniden çağır.",
            )
        if key.lower() not in text.lower() and params.series_id.lower() not in text.lower():
            return ToolError(
                error_code="INTENT_REQUIRED", layer="policy", retryable=False,
                message=f"Kullanıcı hangi taslağı onayladığını söylemedi ('{key}' mesajlarda geçmiyor).",
                hint="Kullanıcıya hangi taslağı onayladığını sor.",
            )
        if not self.cli.available:
            return ToolError(error_code="TOOL_FAILED", layer="policy", retryable=False,
                             message="Veri ekibinin lakehouse CLI'ı bu ortamda yok; terfi yapılamaz.")
        return None

    def run(self, params: PromoteParams) -> ToolResult:
        cmd = [*self.cli.launcher.split(), "-m", "lakehouse", "promote-draft",
               "--database", str(self.cli.database), "--data-root", str(self.cli.data_root),
               "--series", params.series_id]
        self.lakehouse.close()
        release_connections(getattr(self.lakehouse, "db_path", None))
        try:
            code, out, err = self.cli.runner(cmd, self.cli.core_dir)
        finally:
            self.lakehouse.reload()
        kv = parse_kv(out + "\n" + err)
        if code != 0 or kv.get("status") != "success":
            return ToolResult.fail(
                "TOOL_FAILED", f"Terfi başarısız: {kv.get('error') or (out + err)[-300:]}",
                hint="Sebep taslak olmaması ya da gözlemi olmamasıysa kullanıcıya söyle; tekrar deneme.",
                layer="harness", retryable=False,
            )
        card = [
            f"ONAYLANDI: {params.series_id} — {params.purpose}",
            f"durum: taslak → aktif (kullanıcı onayı, semantik kaynağı 'manual')",
            f"Silver'a kopyalanan gözlem: {kv.get('rows_promoted', '?')}; provenance (artifact, run, vintage) korundu",
            "semantik güveni: derived — doğrulanmadı; Gold hesapları için kullanıcı 'doğrulanmamış olsa da kullan' demeli",
            "YAPACAĞIN: kullanıcıya serinin artık sorgulanabilir olduğunu ve Gold için onay gerektiğini söyle.",
        ]
        return ToolResult(content="\n".join(card), artifacts={"promotion": dict(kv)})


__all__ = ["PromoteDraftTool", "PromoteParams", "confirm_intent"]
