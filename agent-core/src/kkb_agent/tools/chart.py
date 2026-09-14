"""`chart` — aktif tablodan grafik; eksen ve ölçek kararı araçta, denetçi geçmeden dosya yok.

Model yalnız NE çizileceğini söyler: tür, kolonlar, başlık. NASIL çizileceği (stok için
sıfırdan başlayan eksen, birim ve dönem başlıkta, uyarılı gözlem işaretli, çift eksen ve
log yalnız istenirse) inşacının kuralı, denetçinin sınavıdır (ADR-0032). Denetçi
geçmezse grafik yazılmaz: kesik eksenli bir stok grafiği yanlış bir sayı kadar yanıltır.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..charts import ChartIntent, build_spec, lint_spec, load_geo_asset, period_label, render_chart
from ..contracts.catalog import ColumnRole, SemanticType
from ..contracts.lakehouse import LakehouseClient, LakehouseError
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace

UNIT_UNKNOWN = "birim belirtilmemiş"
"""Katalog birim vermiyorsa (türetilmiş kolon) başlık ve eksen bunu AÇIKÇA yazar; sessiz boşluk yok."""

_NON_LEVEL = {SemanticType.RATE, SemanticType.INDEX, SemanticType.RATIO}
"""Oran/endeks/rasyo: sıfır tabanı zorunlu değil. Geri kalan her şey (ve bilinmeyen) sıfırdan başlar."""

CHART_PROMPT_RULES = """

GRAFİK KURALI:
chart aracını YALNIZ kullanıcı grafik, çizim, görselleştirme ya da harita istediyse çağır; \
istemediyse çağırma, tablo yeter. İstediyse önce veriyi aktif tabloya getir \
(lakehouse_query ya da gold_*), sonra chart aracını çağır. Eksen, ölçek ve işaretleme kararını \
araç verir: stok için sıfırdan başlayan eksen, birim ve dönem başlıkta, uyarılı gözlem işaretli. \
dual_axis ve log_scale alanlarını YALNIZ kullanıcı açıkça istediyse true yap. Seriler farklı birimdeyse de \
chart aracını çağır: araç zaman eksenli çizgi grafikte her seriyi ilk döneminde 100'e çevirerek karşılaştırmalı \
çizer; birim farkı yüzünden grafiği kendin reddetme. Grafiği kendin \
metinle çizmeye kalkma; cevapta grafiği tek cümleyle tanıt. Dosya yolunu YAZMA, sistem grafiği \
cevabın altında ayrıca gösterir."""


class ChartParams(BaseModel):
    chart_type: Literal["line", "bar", "map"] = Field(
        description="'line' zaman serisi, 'bar' dönem/kategori karşılaştırması, 'map' il haritası"
    )
    y_columns: list[str] = Field(
        min_length=1, max_length=6,
        description="Çizilecek sayısal kolon(lar); aktif tablodaki adlarla birebir",
    )
    x_column: str | None = Field(
        default=None, description="Yatay eksen kolonu (dönem). Boş bırakılırsa tablodaki tarih kolonu seçilir.",
    )
    title: str = Field(description="Grafiğin konusu, kısa Türkçe. Birim ve dönem otomatik eklenir, yazma.")
    dual_axis: bool = Field(
        default=False,
        description="YALNIZ kullanıcı 'iki eksen', 'ikinci eksen', 'sağ eksen' dediyse true; tam iki y kolonu gerekir.",
    )
    log_scale: bool = Field(default=False, description="YALNIZ kullanıcı logaritmik ölçek istediyse true.")
    province_column: str | None = Field(default=None, description="Harita için il adı kolonu.")


def _is_datelike(series: pd.Series) -> bool:
    if pd.api.types.is_datetime64_any_dtype(series):
        return True
    values = series.dropna()
    return not values.empty and all(hasattr(v, "year") for v in values.head(20))


class ChartTool(Tool):
    name = "chart"
    role = "narrate"
    description = (
        "Aktif analiz tablosundan grafik üretir (çizgi, çubuk ya da il haritası) ve PNG olarak "
        "kaydeder. Kullanıcı 'grafiğini çiz', 'görselleştir', 'harita' dediğinde, veri tabloya "
        "geldikten SONRA çağır. Eksen sıfırı, birim, dönem ve uyarılı gözlem işareti araç tarafından "
        "kurala göre konur; deterministik denetçi geçmeden dosya yazılmaz."
    )
    Params = ChartParams

    def __init__(
        self, lakehouse: LakehouseClient, workspace: AnalysisWorkspace, *,
        chart_dir: Path, geo_dir: Path | None = None,
    ) -> None:
        self.lakehouse = lakehouse
        self.workspace = workspace
        self.chart_dir = Path(chart_dir)
        self.geo_dir = Path(geo_dir) if geo_dir else None

    # ------------------------------------------------------------ hooks
    _X_PREFERENCE = ("period_end", "observation_date", "donem", "dönem", "tarih", "date")

    def _x_column(self, params: ChartParams, table: pd.DataFrame) -> str | None:
        """Model vermediyse dönem kolonu: önce dönem SONU adları (Silver/Gold etiketi), sonra
        ilk tarih benzeri kolon. Ölçüldü: Gold join'de ilk tarih kolonu period_start seçiliyordu."""
        if params.x_column:
            return params.x_column
        datelike = [str(c) for c in table.columns if _is_datelike(table[c])]
        for name in self._X_PREFERENCE:
            for c in datelike:
                if c.rsplit("::", 1)[-1].lower() == name:
                    return c
        return datelike[0] if datelike else None

    def validate_refs(self, params: ChartParams) -> ToolError | None:
        if not self.workspace.has_table:
            return ToolError(
                error_code="NO_ACTIVE_TABLE", layer="workspace",
                message="Aktif bir analiz tablosu yok; grafik çizilecek veri henüz getirilmedi.",
                hint="Önce lakehouse_query (ya da gold_*) ile veriyi tabloya getir, sonra chart çağır.",
            )
        table = self.workspace.table
        assert table is not None
        columns = list(map(str, table.columns))
        wanted = [*params.y_columns, *([params.x_column] if params.x_column else []),
                  *([params.province_column] if params.province_column else [])]
        missing = [c for c in wanted if c not in columns]
        if missing:
            return ToolError(
                error_code="COLUMN_NOT_FOUND", layer="reference",
                message=f"Tabloda olmayan kolon: {', '.join(missing)}.",
                candidates=columns, hint="Kolon adlarını aktif tablodan (workspace_show) birebir al.",
            )
        not_numeric = [c for c in params.y_columns if not pd.api.types.is_numeric_dtype(table[c])]
        if not_numeric:
            return ToolError(
                error_code="INVALID_ARGS", layer="schema",
                message=f"Sayısal olmayan y kolonu: {', '.join(not_numeric)}.",
                candidates=[c for c in columns if pd.api.types.is_numeric_dtype(table[c])],
            )
        if params.dual_axis and len(params.y_columns) != 2:
            return ToolError(error_code="INVALID_ARGS", layer="schema",
                             message="Çift eksen tam iki y kolonu ister.")
        if params.chart_type == "map":
            if not params.province_column:
                return ToolError(error_code="INVALID_ARGS", layer="schema",
                                 message="Harita için il adı kolonu (province_column) gerekli.")
            if len(params.y_columns) != 1:
                return ToolError(error_code="INVALID_ARGS", layer="schema",
                                 message="Harita tek bir değer kolonu alır.")
        elif self._x_column(params, table) is None:
            return ToolError(
                error_code="COLUMN_NOT_FOUND", layer="reference",
                message="Yatay eksen için tarih kolonu bulunamadı; x_column ver.",
                candidates=columns,
            )
        return None

    def check_policy(self, params: ChartParams) -> ToolError | None:
        if params.chart_type == "map" and load_geo_asset(self.geo_dir) is None:
            return ToolError(
                error_code="TOOL_FAILED", layer="policy", retryable=False,
                message=("İl sınır dosyası bu ortamda yok "
                         f"({self.geo_dir or 'GEO_DIR tanımsız'}/tr_provinces.geojson); harita çizilemez."),
                hint="Kullanıcıya haritanın bu ortamda üretilemediğini söyle; aynı veriyi çubuk grafik "
                     "olarak (chart_type='bar', x_column=il kolonu) önerebilirsin.",
            )
        return None

    # ------------------------------------------------------------ anlam
    def _column_semantics(
        self, columns: list[str]
    ) -> tuple[dict[str, str], set[str], list[str], dict[str, str]]:
        """(birim, sıfır tabanlı kolonlar, kaynak notları, eksen etiketleri) — katalogdan, tahmin yok.

        Kolon → katalog eşlemesi üç yoldan, sırayla: (1) kolon adı katalogda birebir var;
        (2) Gold kolonu `<seri>[@varlık]::alan` — önek seri kimliğidir; (3) sorgunun tek bir
        ölçümü var ve SQL'de yeniden adlandırılmış. Hiçbiri tutmazsa birim 'belirtilmemiş'
        diye AÇIKÇA yazılır ve eksen sıfırdan başlar (bilinmeyen için güvenli varsayım).
        """
        units: dict[str, str] = {}
        levels: set[str] = set()
        sources: list[str] = []
        labels: dict[str, str] = {}
        for col in columns:
            prov = self.workspace.column_provenance(col)
            specs = []
            for ds in (prov.dataset_ids if prov else []):
                try:
                    specs.append(self.lakehouse.get_dataset(ds))
                except LakehouseError:
                    continue
            for src in (prov.sources if prov else []):
                if src not in sources:
                    sources.append(src)
            spec_col = None
            owner = None
            match = next((s for s in specs if s.column(col)), None)
            if match is not None:
                spec_col, owner = match.column(col), match
            elif "::" in col:
                prefix = col.split("::", 1)[0].split("@", 1)[0]
                owner = next((s for s in specs if s.dataset_id == prefix), None)
                if owner is None:
                    try:
                        owner = self.lakehouse.get_dataset(prefix)
                    except LakehouseError:
                        owner = None
                if owner is not None:
                    measures = [c for c in owner.columns if c.role is ColumnRole.MEASURE]
                    spec_col = measures[0] if len(measures) == 1 else None
            if spec_col is None and "::" not in col:
                # Önekli (Gold) kolon buraya düşmez: öneki tanınmayan seri başka bir serinin
                # birimini MİRAS ALMAMALI (ölçüldü: KTF12 'milyon TL' oluyordu).
                measures = [c for s in specs for c in s.columns if c.role is ColumnRole.MEASURE]
                if measures and len({m.unit for m in measures}) == 1 and len({m.semantic_type for m in measures}) == 1:
                    spec_col, owner = measures[0], specs[0]  # SQL'de yeniden adlandırılmış tek ölçüm
            units[col] = spec_col.unit if (spec_col is not None and spec_col.unit) else UNIT_UNKNOWN
            if owner is not None and "::" in col:
                labels[col] = owner.name
            if spec_col is None or spec_col.semantic_type not in _NON_LEVEL:
                levels.add(col)
        return units, levels, sources, labels

    # ------------------------------------------------------------ run
    def run(self, params: ChartParams) -> ToolResult:
        table = self.workspace.table
        assert table is not None
        x = None if params.chart_type == "map" else self._x_column(params, table)
        units, levels, sources, labels = self._column_semantics(list(params.y_columns))
        # quality_flag ≠ ok gibi, anomaly_detect'in <sütun>_anomali kolonu da halka ile işaretlenir (ADR-0040).
        quality = next((c for c in table.columns if str(c).endswith("quality_flag")), None) \
            or next((c for c in table.columns if str(c).endswith("_anomali")), None)
        intent = ChartIntent(
            kind=params.chart_type, x=x, y=tuple(params.y_columns), title=params.title,
            unit_labels=units, labels=labels,
            period=period_label(table, x) if x else self._period_from_history(),
            level_columns=frozenset(levels), quality_column=quality,
            dual_axis=params.dual_axis, log_scale=params.log_scale,
            province_column=params.province_column,
            geo=load_geo_asset(self.geo_dir) if params.chart_type == "map" else None,
            source_note=("Kaynak: " + "; ".join(sources[:2])) if sources else "",
        )
        try:
            spec = build_spec(table, intent)
        except ValueError as exc:
            return ToolResult.fail("INVALID_ARGS", str(exc), layer="schema")

        report = lint_spec(spec, table, intent)
        rebased = False
        if not report.ok and self._can_rebase(report, params, table, x):
            # M16 kabul bulgusu (14 Eyl): "karşılaştırmalı grafik" isteğinde iki farklı birimli seri L9'a takıldı ve
            # model grafiği hiç vermedi. Çift eksen yanıltıcı olduğu için kendiliğinden açılmaz (ADR-0034); bunun
            # yerine her seri kendi ilk döneminde 100'e çevrilir — birim tektir, eğilim karşılaştırması dürüsttür.
            table, intent = self._rebase_to_100(table, intent, list(params.y_columns))
            spec = build_spec(table, intent)
            report = lint_spec(spec, table, intent)
            rebased = report.ok
        if not report.ok:
            # Denetçi geçmedi: bu modelin değil, inşacının hatasıdır ya da veri kurala uymuyor
            # (ör. haritada sınırı olmayan il). Dosya YAZILMAZ; sebep kullanıcıya gider.
            return ToolResult.fail(
                "TOOL_FAILED",
                "Grafik denetçiden geçmedi, dosya yazılmadı:\n" + report.render(),
                hint=("Kullanıcıya grafiğin hangi kural yüzünden üretilmediğini söyle; sayıları tablodan ver. "
                      "Farklı birimli seriler için kullanıcı açıkça isterse dual_axis=true (tam iki seri) ile yeniden çağır."),
                layer="harness", retryable=False,
            )
        files = render_chart(spec, out_dir=self.chart_dir)

        y_cols = list(intent.y)
        y_desc = ", ".join(f"{c} ({intent.unit_labels.get(c) or units.get(c)})" for c in y_cols)
        shown_cols = [c for c in ([x] if x else []) + y_cols if c in table.columns]
        card = [
            f"GRAFİK: {spec['title']['text'] if isinstance(spec.get('title'), dict) else params.title}",
            report.render().splitlines()[0] + f" | tür: {params.chart_type} | x: {x or params.province_column} | y: {y_desc} | {len(table)} satır",
            *report.render().splitlines()[1:],
            *(["NOT: seriler farklı birimde olduğu için her biri ilk döneminde 100 olacak şekilde endekslendi "
               "(çift eksen kullanılmadı). Cevapta bunu tek cümleyle söyle; düzey sayılarını önceki tablodan ver."]
              if rebased else []),
            *files.lines(),
            # Çizilen satırlar burada: model sayıları yeniden sorgulamaya kalkmasın (ölçüldü: grafik
            # sonrası 8 fazla adım, sırf tabloyu "doğrulamak" için).
            "Çizilen veri (ilk 12 satır):\n" + table[shown_cols].head(12).to_string(index=False),
            "YAPACAĞIN: ARAÇ ÇAĞIRMAYI BIRAK; cevapta grafiği tek cümleyle tanıt, sayıları yukarıdaki tablodan ver.",
        ]
        artifact = {
            # K02-T05 (A07/A26): arayüz ve rapor PNG'deki başlığın aynısını taşır — birim ve dönem dahil (yalnız konu değil).
            "kind": params.chart_type, "title": spec["title"]["text"] if isinstance(spec.get("title"), dict) else intent.title,
            "topic": intent.title,
            "spec_path": str(files.spec_path),
            "png_path": str(files.png_path) if files.png_path else None,
            "svg_path": str(files.svg_path) if files.svg_path else None,
            "lint": report.render(), "lint_ok": report.ok, "rebased_to_100": rebased,
            "render_error": files.render_error,
        }
        return ToolResult(content="\n".join(card), artifacts={"chart": artifact})

    _REBASE_UNIT = "endeks (ilk dönem = 100)"

    @staticmethod
    def _can_rebase(report, params: ChartParams, table: pd.DataFrame, x: str | None) -> bool:
        """Yalnız tek kusur farklı birimse, zaman ekseninde çizgi grafikse ve her serinin ilk değeri pozitifse."""
        if params.chart_type != "line" or params.dual_axis or x is None or not _is_datelike(table[x]):
            return False
        rules = {r.rule for r in report.failures}
        # axis_unit yalnız birimi bilinmeyen seri yüzünden düşer; endekslenince eksen birimi tektir.
        if "single_unit_axis" not in rules or not rules <= {"single_unit_axis", "axis_unit"}:
            return False
        ordered = table.sort_values(x)
        for c in params.y_columns:
            first = ordered[c].dropna()
            if first.empty or float(first.iloc[0]) <= 0:
                return False
        return True

    def _rebase_to_100(self, table: pd.DataFrame, intent: ChartIntent, y: list[str]) -> tuple[pd.DataFrame, ChartIntent]:
        frame = table.sort_values(intent.x).reset_index(drop=True)
        new_cols: list[str] = []
        labels: dict[str, str] = {}
        for c in y:
            base = float(frame[c].dropna().iloc[0])
            name = f"{c}_100"
            frame[name] = (frame[c] / base * 100).round(2)
            new_cols.append(name)
            labels[name] = f"{intent.labels.get(c) or c} (ilk dönem = 100)"
        rebased = replace(
            intent, y=tuple(new_cols), unit_labels={c: self._REBASE_UNIT for c in new_cols},
            labels=labels, level_columns=frozenset(), dual_axis=False,
            title=intent.title if "100" in intent.title else f"{intent.title} (ilk dönem = 100)",
        )
        return frame, rebased

    def _period_from_history(self) -> str:
        """Harita için dönem: tablo tek dönemse ilk tarih kolonundan, yoksa başlıktan."""
        table = self.workspace.table
        if table is None:
            return ""
        for c in table.columns:
            if _is_datelike(table[c]):
                return period_label(table, str(c))
        return self.workspace.title or ""


__all__ = ["CHART_PROMPT_RULES", "ChartParams", "ChartTool", "UNIT_UNKNOWN"]
