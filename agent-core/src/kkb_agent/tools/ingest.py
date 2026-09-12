"""`ingest_from_url` — Analist'in Architect'e açılan tek kapısı.

Demo senaryosunun 2. sorusu: jüri yeni veri getirir, agent ingest eder ve belgeler.
Akış deterministik; burada LLM yok:

    erişim (ADR-0028) → profilleme oku → öner (kanıtla) → doğrula (yayınlama kuralları)
      → belirsizse KULLANICIYA SOR, yazma
      → okuyucuyu kapat → veri ekibinin CLI'ı draft'a yazar → okuyucuyu yeniden aç
      → belge kartı

Yazma yeteneği bu aracın dışında hiçbir yerde yok: Analist'in bağlantısı salt-okunur
kalır; yazan, ayrı bir süreçte çalışan veri ekibinin CLI'ıdır ve o da yalnız
`adhoc` + `draft` yazabilir. Curated Silver'a bu yoldan girilemez.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..builder.ingest import LakehouseCLI
from ..builder.profile import profile_table, propose
from ..builder.read import ReadRefused, read_table_for_profiling
from ..builder.verify import verify_mapping
from ..adapters.duckdb_lakehouse import release_connections
from ..contracts.lakehouse import LakehouseClient
from ..core.access_policy import decide, detect_source_constraint, render_for_model, to_tool_error
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult


class IngestParams(BaseModel):
    locator: str = Field(description="Yerel dosya yolu ya da http(s) URL'i (CSV, TSV, XLSX, JSON)")
    name: str = Field(description="Serinin okunabilir adı, ör. 'İl bazında konut satışları'")
    series_key: str | None = Field(
        default=None,
        description="Seri anahtarı (harf, rakam, alt çizgi). Boşsa dosya adından türetilir.",
    )
    description: str | None = Field(default=None, description="Bir cümlelik açıklama; boşsa üretilir.")


def _slug(text: str) -> str:
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ ", "cgiosuCGIOSU_")
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text.translate(tr)).strip("_").lower()
    return s or "seri"


class IngestFromUrlTool(Tool):
    name = "ingest_from_url"
    role = "execute"
    description = (
        "Kullanıcının getirdiği yeni bir veri dosyasını (yerel yol ya da URL; CSV/TSV/XLSX/JSON) "
        "veri havuzuna TASLAK seri olarak ekler ve ne yaptığını belgeler. Dosyanın hangi kolonunun "
        "tarih, hangisinin değer olduğunu veriye bakarak kanıtıyla önerir; belirsizse eklemeden "
        "önce kullanıcıya sorar. Kullanıcı 'bu dosyayı ekle', 'şu linkteki veriyi yükle' dediğinde "
        "BU aracı kullan."
    )
    Params = IngestParams

    def __init__(
        self, lakehouse: LakehouseClient, cli: LakehouseCLI, *, allowed_root: Path,
        registry: object | None = None, dataset_prefix: str = "adhoc", session: Any = None,
    ) -> None:
        self.lakehouse = lakehouse
        self.cli = cli
        self.allowed_root = Path(allowed_root)
        self._registry = registry
        self.dataset_prefix = dataset_prefix
        self.session = session  # HTTP oturumu; testte sahte, üretimde requests'in kendisi

    # ------------------------------------------------------------------ hooks
    def check_policy(self, params: IngestParams) -> ToolError | None:
        if not self.cli.available:
            return ToolError(
                error_code="TOOL_FAILED", layer="policy", retryable=False,
                message="Veri ekibinin lakehouse CLI'ı bu ortamda yok; ingest yapılamaz.",
                hint="LAKEHOUSE_CORE_DIR ayarını kontrol et.",
            )
        return None

    # ------------------------------------------------------------------- run
    def run(self, params: IngestParams) -> ToolResult:
        question = getattr(self._registry, "active_question", "") or ""
        constraint = detect_source_constraint(question or params.locator)

        # 1. erişim + danışma okuması
        try:
            frame, outcome = read_table_for_profiling(
                params.locator, allowed_roots=[self.allowed_root], session=self.session
            )
        except ReadRefused as exc:
            return ToolResult.fail(
                "ACCESS_BLOCKED", f"Kaynak okunamadı: {exc}",
                hint="Dosyayı izinli klasöre koy ya da http(s) bir adres ver.", layer="access",
            )
        decision = decide(outcome, constraint)
        if not outcome.ok or frame is None:
            err = to_tool_error(outcome, decision)
            return ToolResult(content=err.render(), ok=False, error=err)

        # 2. profil + öneri
        key = params.series_key or _slug(Path(params.locator.split("?")[0]).stem)
        series_id = f"adhoc:{key}"
        profile = profile_table(frame)
        mapping, semantics = propose(profile, frame, series_id=series_id)
        if mapping is None or semantics is None:
            return ToolResult.fail(
                "TOOL_FAILED",
                f"Tabloda tarih ve değer kolonu birlikte bulunamadı ({len(frame)} satır, "
                f"{len(frame.columns)} sütun: {', '.join(map(str, frame.columns))}).",
                hint="Kullanıcıya hangi kolonun tarih, hangisinin değer olduğunu sor.",
                layer="data", retryable=False,
            )

        # 3. doğrulama — yayınlama kurallarıyla
        # Çakışma yalnız küratörlü/başka kaynaklı serilerle: aynı dosyanın ikinci ingest'i
        # kendi taslağına düşer ve veri ekibinin yayınlama kuralı onu çözer (aynı satır
        # "değişmeyen", aynı tarihe farklı değer "revizyon çatışması" — sessiz ezme yok).
        existing = [s.dataset_id for s in self.lakehouse.list_datasets() if s.source != "adhoc"]
        report = verify_mapping(frame, mapping, existing_series_ids=existing)
        asks: list[str] = []
        if not report.ok:
            asks += [f"{c.name}: {c.detail}" for c in report.failures]
        if semantics.unit is None:
            asks.append("birim: veriden çıkarılamıyor; kaynağın birimi nedir (ör. milyon TL, %, adet)?")
        if asks:
            lines = ["EKLENMEDİ — önce kullanıcıya sorulmalı:"] + [f"  - {a}" for a in asks]
            lines.append("\nÖNERİ (kanıtıyla):")
            lines += [f"  {e.field} = {e.value!r}  [{e.confidence}] {e.reason}" for e in mapping.evidence]
            lines += [f"  {e.field} = {e.value!r}  [{e.confidence}] {e.reason}" for e in semantics.evidence]
            if mapping.alternatives:
                lines.append("ALTERNATİFLER: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in mapping.alternatives.items()))
            lines.append("\nYAPACAĞIN: yukarıdaki soruları kullanıcıya sor; cevap gelince aynı aracı "
                         "series_key ile yeniden çağır. Sayı uydurma, seriyi eklenmiş sayma.")
            return ToolResult(content="\n".join(lines), ok=True,
                              artifacts={"proposal": mapping, "semantics": semantics, "report": report})

        # 4. yaz: okuyucuyu kapat → CLI → yeniden aç. DuckDB tek yazar kabul ediyor.
        #
        # Katalog kaydı DETERMİNİSTİK: aynı dosya + aynı öneri → bayt bayt aynı kayıt.
        # Ölçüldü: model ikinci koşuda farklı bir 'name' verdi, veri ekibinin sözleşmesi
        # "aynı draft farklı içerikle" diye reddetti (doğru davranış). Kullanıcının verdiği
        # ad karta girer, kataloğa değil; katalog adı dosya ve seri anahtarından türer.
        source_name = Path(params.locator.split("?")[0]).name
        catalog_name = f"{key} — {source_name} (taslak)"
        description = (
            f"Kullanıcının getirdiği kaynaktan ({params.locator}) Architect tarafından taslak olarak "
            f"eklendi. Eşleme ve anlam veriden önerildi; ölçüm tipi {semantics.measure_type!r} "
            f"({next(e.reason for e in semantics.evidence if e.field == 'measure_type')}). "
            "Kullanılabilmesi için bir insanın onaylayıp kataloğa alması gerekir."
        )
        # Süreçteki BÜTÜN okuyucular kapanmalı, yalnız bu adaptör değil: DuckDB aynı
        # süreçteki salt-okunur bağlantıları tek örnekte paylaşır ve dosya kilidi son
        # bağlantı kapanana kadar kalır (ölçüldü: eski bir agent örneğinin bağlantısı
        # yazar alt sürecin kilidini engelledi).
        self.lakehouse.close()
        release_connections(getattr(self.lakehouse, "db_path", None))
        try:
            out = self.cli.ingest_file(
                locator=params.locator, dataset_id=f"{self.dataset_prefix}_{key}",
                mapping=mapping, semantics=semantics, name=catalog_name, description=description,
                allowed_root=self.allowed_root,
            )
        finally:
            self.lakehouse.reload()

        if not out.ok:
            conflict = "already exists as a draft with different content" in (out.error or "")
            return ToolResult.fail(
                "TOOL_FAILED",
                (f"'{series_id}' adlı bir taslak zaten var ve içeriği bu dosyadan farklı; veri "
                 "ekibinin sözleşmesi sessizce üstüne yazmaz." if conflict
                 else f"Ingest başarısız: {out.error or out.status}. {out.raw[-400:]}"),
                hint=("Kullanıcıya sor: başka bir series_key ile yeni taslak mı, yoksa mevcut taslak "
                      "korunsun mu? Aynı çağrıyı tekrarlama." if conflict
                      else "Hata mesajı bir eşleme sorununu söylüyorsa kullanıcıya sor; tekrar deneme."),
                layer="harness", retryable=False,
            )

        # 5. belge kartı — kullanıcıya gidecek olan
        card = [
            f"EKLENDİ: {series_id} — {params.name}",
            f"katalog adı: {catalog_name}",
            f"kaynak: {params.locator}",
            f"satır: {report.rows_mapped} eşlendi, {report.rows_null_value} boş değer korundu"
            + (f"; yazılan {out.rows_written}, değişmeyen {out.rows_unchanged}" if out.rows_written is not None else ""),
            f"katman: adhoc (taslak) — Silver'a ve Gold'a girmez; bir insan onaylayınca kataloğa alınır",
            "eşleme: " + ", ".join(f"{e.field}={e.value!r}" for e in mapping.evidence if e.field in
                                   ("observation_date_column", "date_format", "value_column", "decimal_separator", "entity_id_column")),
            f"anlam: frekans={semantics.frequency} ölçüm={semantics.measure_type} birim={semantics.unit}"
            + ("  ⚠ ölçüm tipi kanıtsız, 'unknown' olarak kaydedildi" if semantics.measure_type == "unknown" else ""),
            "kanıt: " + " | ".join(f"{e.field}: {e.reason}" for e in semantics.evidence if e.confidence != "none"),
            *out.provenance_lines(),
        ]
        if out.warnings:
            card.append(f"parser uyarısı: {out.warnings} (quality_flag='source_warning')")
        card.append(render_for_model(outcome, decision).splitlines()[0])
        return ToolResult(content="\n".join(card), artifacts={"ingest": out, "proposal": mapping})


__all__ = ["IngestFromUrlTool", "IngestParams"]
