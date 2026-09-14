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
from ..core.approvals import PendingOp, book_of, decide
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult

# Kalıcı yayın onayı; Gold'un "doğrulanmamış olsa da kullan" hesap rızasıyla karışmaz (D03-T06: "kabul ediyorum" çıkarıldı).
_CONFIRM = re.compile(
    r"\b(onayl[ıi]yorum|onayla|onaylayalım|kataloğa al|kataloga al|terfi ettir|yayınla|yayinla|"
    r"silver'?a al|aktif et)\b", re.I,
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

    def _current(self) -> tuple[str, int]:
        reg = self._registry
        message = getattr(reg, "current_message", None)
        if message is None:                       # eski kayıt defteri: yalnız etkin soru (geçmiş değil)
            message = getattr(reg, "active_question", "") or ""
        return message, int(getattr(reg, "turn", 0) or 0)

    def check_policy(self, params: PromoteParams) -> ToolError | None:
        message, turn = self._current()
        book = book_of(self._registry)
        targets = [p.series_id for p in book.of("promote")]
        decision = decide(book, operation="promote", series_id=params.series_id, message=message, turn=turn,
                          known_targets=targets)
        if not decision.ok:
            if "reddediyor" not in decision.reason:
                # Onaysız deneme: işlem bekleyene yazılır; kullanıcı kapsamı gördükten sonra kısa "evet" diyebilir.
                book.register(PendingOp(series_id=params.series_id, operation="promote", shown_turn=turn,
                                        summary=f"{params.series_id} taslağı kataloğa aktif seri olarak alınacak ve Silver'a kopyalanacak"))
            return ToolError(
                error_code="INTENT_REQUIRED", layer="policy", retryable=False,
                message=decision.reason,
                hint=("Kullanıcıya taslağın kimliğini, eşlemesini ve anlamını özetleyip bu işlem için onay iste "
                      f"('{params.series_id}' kataloğa alınsın mı?); onaylarsa bu aracı yeniden çağır. Reddettiyse yapma."),
            )
        if not self.cli.available:
            return ToolError(error_code="TOOL_FAILED", layer="policy", retryable=False,
                             message="Veri ekibinin lakehouse CLI'ı bu ortamda yok; terfi yapılamaz.")
        return None

    def run(self, params: PromoteParams) -> ToolResult:
        # Onay denemede tüketilir: başarısız işlem yeniden onay ister, başarılı işlem başka bir işleme onay sayılmaz.
        book_of(self._registry).discard("promote", params.series_id)
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
