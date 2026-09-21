"""`ingest_source` — Architect: katalogdaki bir serinin yüklü aralık DIŞINDAKİ dönemini kayıtlı kaynağından çeker (K02-T12, A30).

Analyst kapsam dışı dönemde "yüklü değil + mevcut aralık" der (ADR-0014). Architect ise aynı seriyi kaynağından çekebilir:
yazma veri ekibinin toplu ingest betiğiyle (`scripts/run_catalog_ingestion.py --only <seri> --start --end`) ayrı süreçte
yapılır — run kaydı, artifact bağı ve uyarılar korunur (ADR-0057); ardından `lakehouse silver` ile sorgu yüzeyi yenilenir.
Kaynak erişilemezse betiğin redakte edilmiş sebebi erişim hatası olarak döner; sahte başarı ve Silver yenilemesi yok.
"""

from __future__ import annotations

import json
import re
import tempfile
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from ..adapters.duckdb_lakehouse import release_connections
from ..builder.ingest import LakehouseCLI
from ..contracts.lakehouse import LakehouseClient, LakehouseError
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult

_FETCH_INTENT = re.compile(r"\b(çek|cek|çekelim|getir|indir|yükle|yukle|kaynaktan|güncelle|guncelle|tamamla|ekle)\w*", re.I)


class IngestSourceParams(BaseModel):
    series_id: str = Field(description="Katalogdaki seri kimliği (lakehouse_search'ten), ör. 'bddk_monthly:1534_Toplam'")
    start: str = Field(description="Başlangıç tarihi YYYY-MM-DD")
    end: str = Field(description="Bitiş tarihi YYYY-MM-DD")
    purpose: str = Field(description="Tek cümle: kullanıcı neyi istedi")


class IngestSourceTool(Tool):
    name = "ingest_source"
    role = "execute"
    description = (
        "YALNIZ ARCHITECT: katalogdaki bir serinin yüklü aralık dışındaki dönemini kayıtlı kaynağından (BDDK, EVDS …) çeker, "
        "run kaydıyla yazar ve Silver'ı yeniler. Kullanıcı o dönemi kaynaktan çekmeyi istediyse çağır; sonra lakehouse_query ile sorgula. "
        "Kaynak erişilemezse sebebi kullanıcıya söyle."
    )
    Params = IngestSourceParams

    def __init__(self, lakehouse: LakehouseClient, cli: LakehouseCLI, *, registry: object | None = None) -> None:
        self.lakehouse = lakehouse
        self.cli = cli
        self._registry = registry

    def validate_refs(self, params: IngestSourceParams) -> ToolError | None:
        try:
            spec = self.lakehouse.get_dataset(params.series_id)
        except LakehouseError:
            uningested = getattr(self.lakehouse, "_uningested", {}) or {}
            if params.series_id not in uningested:
                return ToolError(error_code="DATASET_NOT_FOUND", layer="reference", retryable=False,
                                 message=f"'{params.series_id}' katalogda yok; yalnız katalogdaki seriler kaynaktan çekilir.",
                                 hint="lakehouse_search ile serinin kimliğini bul.")
            return None
        if spec.source in ("adhoc", "gold") or params.series_id.startswith(("adhoc:", "gold.")):
            return ToolError(error_code="INVALID_ARGS", layer="reference", retryable=False,
                             message=f"'{params.series_id}' kayıtlı bir kaynağa bağlı değil (kaynak {spec.source}); kaynaktan çekilemez.")
        return None

    def check_policy(self, params: IngestSourceParams) -> ToolError | None:
        try:
            start, end = date.fromisoformat(params.start), date.fromisoformat(params.end)
        except ValueError:
            return ToolError(error_code="INVALID_ARGS", layer="schema", message="start/end YYYY-MM-DD biçiminde olmalı.")
        if start > end:
            return ToolError(error_code="INVALID_ARGS", layer="schema", message="start, end'den sonra olamaz.")
        message = getattr(self._registry, "current_message", None) or getattr(self._registry, "active_question", "") or ""
        if not _FETCH_INTENT.search(message):
            return ToolError(error_code="INTENT_REQUIRED", layer="policy", retryable=False,
                             message="Kullanıcının güncel mesajında kaynaktan veri çekme isteği yok.",
                             hint="Kullanıcıya bu dönemi kaynağından çekmek isteyip istemediğini sor.")
        if not self.cli.available:
            return ToolError(error_code="TOOL_FAILED", layer="policy", retryable=False,
                             message="Veri ekibinin lakehouse CLI'ı bu ortamda yok; kaynaktan çekilemez.")
        return None

    def run(self, params: IngestSourceParams) -> ToolResult:
        launcher = self.cli.launcher.split()
        with tempfile.TemporaryDirectory(prefix="ingest_source_") as tmp:
            report_path = Path(tmp) / "rapor.json"
            fetch = [*launcher, "scripts/run_catalog_ingestion.py", "--only", params.series_id, "--start", params.start,
                     "--end", params.end, "--database", str(self.cli.database), "--data-root", str(self.cli.data_root),
                     "--report", str(report_path)]
            self.lakehouse.close()
            release_connections(getattr(self.lakehouse, "db_path", None))
            try:
                code, out, err = self.cli.runner(fetch, self.cli.core_dir)
                report = {}
                if report_path.exists():
                    try:
                        report = json.loads(report_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        report = {}
                outcome = next((o for o in report.get("outcomes", []) if o.get("series_id") == params.series_id), {})
                status = outcome.get("status")
                if code != 0 or status not in ("ok", "warning", "shared"):
                    reason = outcome.get("error") or (err or out).strip()[-300:] or f"çıkış kodu {code}"
                    return ToolResult.fail(
                        "ACCESS_BLOCKED", f"{params.series_id} {params.start} → {params.end} kaynaktan çekilemedi: {reason}",
                        hint="Kullanıcıya kaynağın neden erişilemediğini söyle; yüklü aralıktaki veriyle devam etmeyi ya da "
                             "sonra yeniden denemeyi öner. Sayı uydurma.",
                        layer="access", retryable=False,
                    )
                silver = [*launcher, "-m", "lakehouse", "silver", "--database", str(self.cli.database), "--data-root", str(self.cli.data_root)]
                s_code, s_out, s_err = self.cli.runner(silver, self.cli.core_dir)
                if s_code != 0:
                    return ToolResult.fail("TOOL_FAILED", f"Veri çekildi ama Silver yenilenemedi: {(s_err or s_out).strip()[-300:]}",
                                           hint="Kullanıcıya verinin henüz sorgulanamadığını söyle.", layer="harness", retryable=False)
                # Silver değişti → Gold tabloları bayat olur; burada yenilenmezse bir sonraki Gold sorgusu GOLD_STALE ile düşer.
                gold_ok, gold_note = self.cli.refresh_gold()
            finally:
                self.lakehouse.reload()
        card = [
            f"KAYNAKTAN ÇEKİLDİ: {params.series_id} · {params.start} → {params.end} · durum {status}",
            f"run {outcome.get('run_id', '?')} · yeni artifact {outcome.get('new', '?')} · satır {outcome.get('rows_out', '?')}"
            + (f" · uyarı {outcome.get('warnings')}" if outcome.get("warnings") else ""),
            "Silver ve Gold yeniden kuruldu; seri artık bu dönemi de kapsıyor." if gold_ok
            else f"Silver yeniden kuruldu; Gold yenilenemedi ({gold_note}) — hazır Gold tabloları bayat kalabilir, seri Silver'dan sorgulanır.",
            "YAPACAĞIN: şimdi lakehouse_query ile istenen dönemi sorgula; sayıları o tablodan ver.",
        ]
        return ToolResult(content="\n".join(card), artifacts={"ingest_source": {"series_id": params.series_id, **outcome}})


__all__ = ["IngestSourceParams", "IngestSourceTool"]
