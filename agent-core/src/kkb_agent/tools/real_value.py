"""`workspace_real_value` — nominal tutarı fiyat endeksiyle reel değere çevirir (M09, ADR-0058).

Transkript 17:04: "konut kredisi tutarlarını enflasyondan arındırıp gösterir misin, tabloyu bozmadan".
Model formül yazmaz; araç deterministik hesaplar:

    reel_t = nominal_t × endeks(baz) / endeks(t)

Kurallar (M09-T05/T06/T08): endeks serisi katalogda ölçüm tipi INDEX olmalı; baz dönem endeksin kapsamında
olmalı; aynı ayda birden çok satır varsa (haftalık tablo) önce aylık hizalanmalı; endeks sıfır/boş ise o
satır boş kalır ve söylenir; farklı bazlı endeksler BİRLEŞTİRİLMEZ (tek endeks serisi). Endeks değerleri de
tabloya ayrı kolon olarak girer: reel sütunun girdisi görünür, kanıt paneli iki sayıyı da SQL'e bağlar.
Analyst yeteneğidir; ortak kataloğa yazmaz (M09-T11).
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, Field

from ..contracts.catalog import ColumnRole, SemanticType
from ..contracts.lakehouse import LakehouseClient, LakehouseError, QueryProvenance
from ..core.errors import ToolError
from ..core.evidence import _time_column
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace
from .gold import unverified_consent

REAL_VALUE_PROMPT_RULES = """

REEL DEĞER KURALI: "enflasyondan arındır / reel / sabit fiyatlarla" istendiğinde workspace_real_value kullan; \
"tutarlar / mevduatlar" gibi çoğul istekte tablodaki bütün tutar sütunlarını value_columns ile TEK çağrıda ver \
(endeks: fiyat endeksi serisi; compute_column ile elle formül YAZMA). Baz dönemi kullanıcı söylemediyse tablonun son \
dönemini ver ve cevapta "<baz dönem> fiyatlarıyla" diye açıkça belirt. Farklı bazlı iki endeksi birleştirme. \
Anlamı (baz yılı) doğrulanmamış endeks reel dönüşümde kullanılmaz; araç reddederse doğrulanmış endeks seç ya da \
kullanıcıya 'doğrulanmamış olsa da kullanayım mı?' diye sor."""


class RealValueParams(BaseModel):
    value_column: str | None = Field(default=None, description="Aktif tablodaki nominal tutar sütunu (tek sütun)")
    value_columns: list[str] = Field(
        default_factory=list,
        description="Birden çok tutar sütunu tek çağrıda (her biri '<sütun>_reel' adıyla eklenir). "
                    "Kullanıcı 'tutarları' dediyse tablodaki bütün tutar sütunlarını ver.",
    )
    index_dataset_id: str = Field(description="Fiyat endeksi serisinin kimliği (katalogda ölçüm tipi endeks)")
    base_period: str = Field(pattern=r"^\d{4}-\d{2}$", description="Baz dönem 'YYYY-MM': reel değerler bu ayın fiyatlarıyla")
    column_name: str | None = Field(default=None, description="Tek sütunda eklenecek reel sütunun adı")
    purpose: str = Field(description="Bu hesabın neyi cevapladığını anlatan tek cümlelik Türkçe açıklama")


class WorkspaceRealValueTool(Tool):
    name = "workspace_real_value"
    role = "execute"
    description = (
        "Aktif tablodaki nominal bir tutarı fiyat endeksiyle REEL değere çevirir ve yeni sütun olarak ekler "
        "(tablo bozulmaz): reel = nominal × endeks(baz) / endeks(dönem). Endeks değerleri de ayrı sütun olarak "
        "eklenir. Baz dönem 'YYYY-MM' ve endeks kapsamında olmalı; aynı ayda birden çok satır varsa önce aylık hizala."
    )
    Params = RealValueParams

    def __init__(self, lakehouse: LakehouseClient, workspace: AnalysisWorkspace, *, registry: object | None = None) -> None:
        self.lakehouse = lakehouse
        self.workspace = workspace
        self._registry = registry

    def _consent(self) -> bool:
        """Rıza yalnız GÜNCEL mesajdan (D03): önceki turdaki 'yine de kullan' bu hesaba sayılmaz."""
        reg = self._registry
        text = getattr(reg, "current_message", None) or getattr(reg, "user_text", None) or getattr(reg, "active_question", "") or ""
        return unverified_consent(text)

    # ------------------------------------------------------------ doğrulama
    def loaded_index_series(self) -> list[tuple[str, str]]:
        """Adayları metinle değil anlamla bul (canlı prova, 14 Eyl): yüklü endeks serisinin adı "Genel Endeks"
        olunca metin araması onu bulamadı, model yüklenmemiş eski seriyi seçti. Katalogda ölçüm tipi INDEX
        olan ve gözlemi bulunan seriler aday olarak döner — alan bilgisi yok, yalnız anlam."""
        out: list[tuple[str, str]] = []
        try:
            specs = list(self.lakehouse.list_datasets())
        except Exception:  # noqa: BLE001
            return out
        for spec in specs:
            measures = [c for c in getattr(spec, "columns", []) if c.role == ColumnRole.MEASURE]
            if measures and measures[0].semantic_type == SemanticType.INDEX and str(spec.dataset_id).find("gold.") != 0:
                out.append((spec.dataset_id, spec.name))
        return out

    def _index_spec(self, dataset_id: str):
        spec = self.lakehouse.get_dataset(dataset_id)
        measures = [c for c in spec.columns if c.role == ColumnRole.MEASURE]
        return spec, (measures[0] if measures else None)

    @staticmethod
    def _targets(params: RealValueParams) -> list[tuple[str, str]]:
        """(nominal sütun, reel sütun) çiftleri. Tek sütun eski sözleşmedir; çoklu kipte ad '<sütun>_reel'."""
        pairs: list[tuple[str, str]] = []
        if params.value_column:
            pairs.append((params.value_column, params.column_name or f"{params.value_column}_reel"))
        for column in params.value_columns:
            if column != params.value_column:
                pairs.append((column, f"{column}_reel"))
        return pairs

    def validate_refs(self, params: RealValueParams) -> ToolError | None:
        table = self.workspace.table
        if table is None or table.empty:
            return ToolError(error_code="NO_ACTIVE_TABLE", layer="workspace", message="Aktif tablo yok; önce nominal seriyi getir.")
        numeric = [str(c) for c in table.columns if pd.api.types.is_numeric_dtype(table[c])]
        targets = self._targets(params)
        if not targets:
            return ToolError(error_code="INVALID_ARGS", layer="schema", candidates=numeric,
                             message="value_column ya da value_columns ver.")
        for value_column, column_name in targets:
            if value_column not in table.columns:
                return ToolError(error_code="COLUMN_NOT_FOUND", layer="reference", candidates=numeric,
                                 message=f"'{value_column}' aktif tabloda yok.")
            if value_column not in numeric:
                return ToolError(error_code="INVALID_ARGS", layer="schema", candidates=numeric,
                                 message=f"'{value_column}' sayısal değil.")
            if column_name in table.columns:
                return ToolError(error_code="COLUMN_EXISTS", layer="workspace", candidates=list(table.columns),
                                 message=f"'{column_name}' zaten tabloda var.")
        if _time_column(table) is None:
            return ToolError(error_code="INVALID_ARGS", layer="data",
                             message="Aktif tabloda tarih kolonu yok: dönem eşlemesi yapılamaz.")
        try:
            spec, measure = self._index_spec(params.index_dataset_id)
        except LakehouseError as exc:
            near = self.loaded_index_series()
            return ToolError(error_code="DATASET_NOT_FOUND", layer="reference", candidates=[sid for sid, _ in near], message=str(exc),
                             hint=("Yüklü ve ölçüm tipi endeks olan seriler: " + "; ".join(f"{sid} — {name}" for sid, name in near[:6])
                                   if near else "Havuzda yüklü bir fiyat endeksi serisi yok; kullanıcıya bunu söyle."))
        if measure is None:
            return ToolError(error_code="INVALID_ARGS", layer="reference", message=f"'{params.index_dataset_id}' ölçüm kolonu yok.")
        if measure.semantic_type != SemanticType.INDEX:
            kind = measure.semantic_type.value if measure.semantic_type else "bilinmiyor"
            return ToolError(error_code="INVALID_ARGS", layer="reference",
                             message=f"'{params.index_dataset_id}' bir fiyat endeksi değil (ölçüm tipi: {kind}); reel dönüşüm endeksle yapılır.",
                             hint="Ölçüm tipi 'index' olan bir fiyat endeksi serisi seç.")
        return None

    def check_policy(self, params: RealValueParams) -> ToolError | None:
        """K02-T03 (A05, ADR-0075): baz yılı doğrulanmamış endeksle reel değer sessizce üretilmez. Katalogda
        semantic_confidence 'verified' olmayan endeks (ör. KFE 'derived') yalnız kullanıcının açık rızasıyla kullanılır."""
        try:
            spec = self.lakehouse.get_dataset(params.index_dataset_id)
        except LakehouseError:
            return None
        confidence = getattr(spec, "semantic_confidence", None)
        if confidence in (None, "verified") or self._consent():
            return None
        verified = [sid for sid, _ in self.loaded_index_series() if self._confidence(sid) == "verified"]
        # Doğrulanmış bir endeks varsa ret turu bitirmez: model aynı çağrıyı o endeksle yineler (canlı koşu, 23 Eyl:
        # model eski bazlı TP.FG.J0'ı seçti, ret turu kapattı, doğrulanmış TÜFE hiç denenmedi).
        return ToolError(
            terminal=False if verified else None,
            error_code="UNVERIFIED_SEMANTICS", layer="policy", retryable=False, candidates=verified,
            message=(f"'{params.index_dataset_id}' endeksinin anlamı katalogda doğrulanmamış (semantic_confidence={confidence}): "
                     "baz yılı güvenilmez, reel dönüşümde kullanılmaz."),
            hint=(("Aynı çağrıyı doğrulanmış endeksle yinele: index_dataset_id=" + verified[0] + ". "
                   if verified else "")
                  + "Doğrulanmış bir fiyat endeksi seç" + (f" ({', '.join(verified[:4])})" if verified else "")
                  + " ya da kullanıcıya 'doğrulanmamış olsa da kullanayım mı?' diye sor; açık rıza verirse yeniden çağır."),
        )

    def _confidence(self, dataset_id: str) -> str | None:
        try:
            return getattr(self.lakehouse.get_dataset(dataset_id), "semantic_confidence", None)
        except LakehouseError:
            return None

    # ------------------------------------------------------------ hesap
    def run(self, params: RealValueParams) -> ToolResult:
        table = self.workspace.table
        assert table is not None
        tcol = _time_column(table)
        spec, measure = self._index_spec(params.index_dataset_id)
        try:
            sql = self.lakehouse.series_sql(params.index_dataset_id, key_column=spec.time_column, value_column=measure.name)
            result = self.lakehouse.execute_sql(sql)
        except LakehouseError as exc:
            return ToolResult.fail("SQL_FAILED", str(exc), layer="data")
        idx = result.data
        if idx is None or idx.empty:
            return ToolResult.fail("EMPTY_RESULT", f"'{params.index_dataset_id}' endeks serisi boş döndü.", layer="data")
        key, val = idx.columns[0], idx.columns[1]
        months = pd.to_datetime(idx[key], errors="coerce").dt.to_period("M")
        if months.duplicated().any():
            return ToolResult.fail("INVALID_ARGS", f"'{params.index_dataset_id}' ayda birden çok gözlem taşıyor; aylık endeks gerekir.",
                                   hint="gold_align ile endeksi aylığa indir.", layer="data", retryable=False)
        index_by_month = pd.Series(pd.to_numeric(idx[val], errors="coerce").to_numpy(), index=months)
        base = pd.Period(params.base_period, "M")
        coverage = f"{index_by_month.index.min()} → {index_by_month.index.max()}"
        if base not in index_by_month.index or pd.isna(index_by_month.get(base)):
            return ToolResult.fail("OUT_OF_COVERAGE", f"Baz dönem {params.base_period} endeks kapsamında değil (kapsam {coverage}).",
                                   hint="Kapsamdaki bir ayı baz seç; farklı bazlı başka bir endeksle birleştirme yapılmaz.",
                                   layer="data", retryable=False)
        base_value = float(index_by_month[base])
        if base_value == 0:
            return ToolResult.fail("INVALID_ARGS", f"Baz dönem endeksi sıfır ({params.base_period}); bölme tanımsız.", layer="data", retryable=False)

        row_months = pd.to_datetime(table[tcol], errors="coerce").dt.to_period("M")
        if row_months.duplicated().any():
            return ToolResult.fail("INVALID_ARGS", "Aktif tabloda aynı aya düşen birden çok satır var (haftalık/günlük); "
                                   "reel dönüşüm aylık ya da daha seyrek tabloda yapılır.",
                                   hint="Önce gold_align ile tabloyu aylığa indir.", layer="data", retryable=False)
        aligned = pd.Series(row_months.map(index_by_month).to_numpy(dtype="float64"), index=table.index)
        usable = aligned.notna() & (aligned != 0)
        targets = self._targets(params)
        multi = len(targets) > 1 or not params.value_column
        # Çoklu kipte endeks sütunu bir kez eklenir; tek sütunda eski adlandırma korunur.
        index_col = (f"endeks_{params.index_dataset_id.split(':')[-1].replace('.', '_').lower()}" if multi
                     else f"{targets[0][1]}_endeks")
        if index_col not in (self.workspace.table.columns if self.workspace.table is not None else []):
            self.workspace.add_column(index_col, aligned.round(6),
                                      description=f"{params.index_dataset_id} endeks değeri (reel dönüşüm girdisi)",
                                      provenance=result.provenance)
        prov = None
        for value_column, column_name in targets:
            nominal = pd.to_numeric(table[value_column], errors="coerce")
            real = (nominal * base_value / aligned).where(usable)
            formula = f"{value_column} × endeks({params.base_period}) / endeks(dönem)"
            prov = QueryProvenance(
                sql=f"türetilmiş: reel_değer = {formula}; endeks {params.index_dataset_id}, baz {params.base_period} = {base_value:g}",
                dataset_ids=[params.index_dataset_id, *list(getattr(self.workspace.column_provenance(value_column), "dataset_ids", []) or [])],
                sources=[f"türetilmiş sütun — {formula}", *list(getattr(result.provenance, "sources", []) or [])],
            )
            self.workspace.add_column(column_name, real.round(4), description=params.purpose, provenance=prov)
        formula = ", ".join(f"{name} = {col} × endeks({params.base_period}) / endeks(dönem)" for col, name in targets)
        confidence = getattr(spec, "semantic_confidence", None)
        unverified = [] if confidence in (None, "verified") else [
            f"UYARI: {params.index_dataset_id} endeksinin anlamı doğrulanmamış (semantic_confidence={confidence}); baz yılı "
            "doğrulanmadı, kullanıcının açık rızasıyla kullanıldı. Cevapta bunu söyle."]
        if unverified:
            prov.warnings = [*prov.warnings, *unverified]
        missing = int((~usable).sum())
        updated = self.workspace.table
        assert updated is not None
        notes = [f"{missing} satırda endeks yok ya da sıfır: reel değer boş bırakıldı (dönemler uydurulmadı)"] if missing else []
        added = ", ".join([index_col, *[name for _, name in targets]])
        card = [
            f"REEL DEĞER: {formula}",
            f"Endeks: {params.index_dataset_id} (kapsam {coverage}) · baz {params.base_period} = {base_value:g}",
            f"Tabloya eklendi: {added}. Tablo bozulmadı: {len(updated)} satır; önceki sütunların hiçbiri değişmedi.",
            "İstenmeyen türev (yüzde değişim, pay) EKLEME; tablo bu hâliyle cevaptır.",
            *notes,
            *unverified,
            "Farklı bazlı endeksler birleştirilmedi. Cevapta 'baz dönem fiyatlarıyla' ifadesini ve sayıları tablodan aktar.",
            "İlk 5 satır:\n" + updated[[tcol, index_col, *[c for pair in targets for c in pair]]].head(5).to_string(index=False),
        ]
        return ToolResult(content="\n".join(card), data=updated, provenance=prov)


__all__ = ["REAL_VALUE_PROMPT_RULES", "RealValueParams", "WorkspaceRealValueTool"]
