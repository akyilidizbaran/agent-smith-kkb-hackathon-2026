"""`lakehouse_breakdown_panel` — seriler ve kırılım grupları tek aylık eksende, deterministik (ADR-0108).

Ölçüldü (23 Eyl): vade grubu istenen soruda model kovaları SQL ile kendisi topladı ve "3 aya kadar"dan Vadesiz'i
dışarıda bıraktı. Ayrıca stoktan aylık harekete geçerken yalnız toplam sütunlarını farkladı, grupları stok bıraktı
ve dönemin ilk ayı için bir önceki ayı çekmedi. Bu araç üçünü de modelden alır:

- **Kova seçimi kodda.** Bir toplamın vade kovaları ilişki grafından okunur (`child_breakdown`, `vade_ay=(a,b]`).
  "X aya kadar" Vadesiz'i de kapsar; "X aydan fazla" yalnız X'ten uzun vadeli kovaları. Kovayı bölen bir sınır
  (2 ay, 5 yıl) isteği kapsayan en dar kova kümesine genişletilir ve kartta söylenir; kova oranlanarak bölünmez.
- **Aylık hareket aynı kuralla her sütuna.** `value=monthly_change` iken bir önceki ay kendiliğinden çekilir,
  fark alınır, sonra dönem dışına düşen taban ayı atılır. Eksik ay boş kalır; sıfır yazılmaz.
- **Denetim.** Bir toplamın grupları kovalarının tamamını kapsıyorsa grupların toplamı toplamla karşılaştırılır
  (kaynağın yuvarlaması: kova başına ±0,5).
"""

from __future__ import annotations

import math
import re
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..contracts.lakehouse import LakehouseClient, LakehouseError, QueryProvenance
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace

BREAKDOWN_PROMPT_RULES = """

VADE / KIRILIM GRUBU KURALI: Bir toplamın vade kırılımı ("3 aya kadar", "3 aydan fazla", "6-12 ay", "1 yıldan uzun", \
"vadesiz") ya da aynı eksende birden çok seri istendiğinde lakehouse_breakdown_panel kullan; vade kovalarını SQL ile \
KENDİN TOPLAMA. "X aya kadar" Vadesiz'i de kapsar. Kullanıcı "o aydaki / stok olmasın / aylık hareket / akım" diyorsa \
value=monthly_change ver; araç bir önceki ayı kendisi çeker. İstenmeyen sütun (pay, oran, yüzde) ekleme. Takipte aktif \
tablo varsa mevcut sütunları yeniden çekme; yalnız istenen yeni seriyi ekle (reel değer için workspace_real_value). \
Bir serinin KENDİ ADINDAKİ vade (ör. "3 aya kadar vadeli TL mevduat faiz oranı") kırılım isteği değildir: o seriyi olduğu \
gibi kullan, cevapta vade kırılımından söz etme. \
ÇOK KAYNAKLI ANALİZ (BDDK + EVDS + yüklenen dosya): her kavram için TEK arama yap; bulduğun bütün katalog serilerini \
(mevduat toplamları, vade grupları, faiz, TÜFE, kur) TEK lakehouse_breakdown_panel çağrısında al; yüklenen dosyayı \
önce web_url ile aylık oku, SONRA tek panel çağrısında join_session=true, deflator_series_id=<TÜFE>, \
index_base='2021-01' ver: araç dosyayı ay üzerinden ekler, reel hâle getirir ve tutarları endeksler. Paneli İKİNCİ kez \
çağırma (önceki tabloyu değiştirir); vade gruplarını da aynı çağrının groups alanına koy. Sonra tabloya dayanarak yorumla."""

# "Stok olmasın" niyeti (23 Eyl demo): model aynı soruda bir kez hareket, bir kez stok seçti. Değer türü soruda açıkça
# söylenmişse modele bırakılmaz.
FLOW_INTENT = re.compile(
    r"stok\s+(?:veri\s+)?olma|stok\s+değil|stok\s+degil|o\s+aydaki|aylık\s+hareket|aylik\s+hareket|"
    r"\bakım\b|\bakim\b|aylık\s+akış|aylik\s+akis|net\s+(?:giriş|akış)",
    re.I,
)

_INTERVAL = re.compile(r"^vade_ay=([\[(])\s*([-\d.]+)\s*,\s*([-\d.]+|inf)\s*([\])])$")


class PanelSeries(BaseModel):
    series_id: str = Field(description="Katalogdaki seri kimliği (ör. bddk_monthly:524_Toplam)")
    column_name: str = Field(description="Tablodaki sütun adı (ör. yp_mevduat)")


class PanelGroup(BaseModel):
    total_series_id: str = Field(description="Kovaları olan toplam seri (ör. bddk_monthly:520_Toplam)")
    column_name: str = Field(description="Grup sütununun adı (ör. tp_3aya_kadar)")
    min_months: float | None = Field(
        default=None,
        description="Alt sınır, ay, HARİÇ ('3 aydan fazla' → 3). Boş: en kısadan başla, Vadesiz dahil ('3 aya kadar').",
    )
    max_months: float | None = Field(
        default=None, description="Üst sınır, ay, DAHİL ('3 aya kadar' → 3; '1 yıla kadar' → 12). Boş: üst sınır yok.",
    )


class BreakdownPanelParams(BaseModel):
    series: list[PanelSeries] = Field(default_factory=list, description="Olduğu gibi alınacak seriler (toplamlar dahil)")
    groups: list[PanelGroup] = Field(default_factory=list, description="Vade kovalarından toplanacak gruplar")
    period_from: str = Field(pattern=r"^\d{4}-\d{2}$", description="İlk ay 'YYYY-MM'")
    period_to: str = Field(pattern=r"^\d{4}-\d{2}$", description="Son ay 'YYYY-MM'")
    value: Literal["level", "monthly_change"] = Field(
        default="level",
        description="level: ay sonu değer (stok); monthly_change: bu ay − önceki ay (dönemin ilk ayı için önceki ay çekilir)",
    )
    join_session: bool = Field(
        default=False,
        description="true: oturumdaki diğer tablolar (yüklenen dosya, önceki turlar) ay anahtarıyla bu tabloya eklenir",
    )
    deflator_series_id: str | None = Field(
        default=None, description="Reel değer için fiyat endeksi serisi (ör. TÜFE); oturumdan gelen tutarlar reel hâle gelir",
    )
    base_period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$",
                                    description="Reel değer baz ayı 'YYYY-MM' (boşsa period_to)")
    index_base: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}$",
        description="Tutar serilerini bu ay = 100 olacak şekilde endeksle ('2021-01'); faiz, kur ve endeksler kendi biriminde kalır",
    )
    purpose: str = Field(description="Bu tablonun neyi cevapladığını anlatan tek cümlelik Türkçe açıklama")


def _bucket(dimension_path: list[str] | tuple[str, ...]) -> tuple[str, float, float] | None:
    """('1-3 Ay Arası', 1, 3) — (a, b] aralığı; Vadesiz [0,0] burada (-1, 0] olarak temsil edilir."""
    label = next((d.split("=", 1)[1] for d in dimension_path if d.startswith("vade=")), None)
    for entry in dimension_path:
        match = _INTERVAL.match(entry.strip())
        if match:
            lo, hi = float(match.group(2)), (math.inf if match.group(3) == "inf" else float(match.group(3)))
            if match.group(1) == "[" and lo == hi:        # nokta aralık: Vadesiz
                lo = lo - 1
            return (label or entry, lo, hi)
    return None


def resolve_group(buckets: dict[str, tuple[str, float, float]], min_months: float | None,
                  max_months: float | None) -> tuple[list[str], str | None]:
    """İstenen (min, max] aralığını kapsayan en dar kova kümesi ve genişletme notu."""
    lows = sorted({lo for _, lo, _ in buckets.values()})
    highs = sorted({hi for _, _, hi in buckets.values()})
    lo = -math.inf if min_months is None else max([x for x in lows if x <= min_months], default=lows[0])
    hi = math.inf if max_months is None else min([x for x in highs if x >= max_months], default=highs[-1])
    chosen = [sid for sid, (_, a, b) in buckets.items() if a >= lo and b <= hi]
    note = None
    widened = []
    if min_months is not None and lo != min_months:
        widened.append(f"alt sınır {min_months:g} ay → {max(lo, 0):g} ay")
    if max_months is not None and hi != max_months:
        widened.append(f"üst sınır {max_months:g} ay → " + ("sınırsız" if math.isinf(hi) else f"{hi:g} ay"))
    if widened:
        note = ("kaynak bu sınırı yayımlamıyor; isteği kapsayan en dar kova kümesi kullanıldı ("
                + "; ".join(widened) + ")")
    return chosen, note


class LakehouseBreakdownPanelTool(Tool):
    name = "lakehouse_breakdown_panel"
    role = "execute"
    description = (
        "Serileri ve bir toplamın vade kırılım gruplarını ('3 aya kadar', '3 aydan fazla', '6-12 ay') tek aylık "
        "tarih ekseninde getirir ve aktif tablo yapar. Kovaları ilişki grafından DETERMİNİSTİK seçer: 'X aya kadar' "
        "Vadesiz'i kapsar, kovayı bölen sınır en dar kapsayan kümeye genişletilir. value=monthly_change ile her "
        "sütun aylık harekete (bu ay − önceki ay) çevrilir; dönemin ilk ayı için önceki ay kendiliğinden çekilir. "
        "Grupların toplamı toplamla denetlenir. Haftalık/günlük seriler (faiz, kur) katalog kuralıyla aylığa iner; "
        "farklı kaynakların serileri TEK çağrıda aynı aylık tabloya gelir. Vade kovalarını lakehouse_query ile elle "
        "toplama; bu aracı kullan."
    )
    Params = BreakdownPanelParams

    def __init__(self, lakehouse: LakehouseClient, workspace: AnalysisWorkspace, *, registry: object | None = None) -> None:
        self.lakehouse = lakehouse
        self.workspace = workspace
        self._registry = registry

    # ------------------------------------------------------------ katalog
    def _spec(self, series_id: str):
        return self.lakehouse.get_dataset(series_id)

    def _buckets(self, total_series_id: str) -> dict[str, tuple[str, float, float]]:
        out: dict[str, tuple[str, float, float]] = {}
        for spec in self.lakehouse.list_datasets():
            if getattr(spec, "parent_series_id", None) != total_series_id:
                continue
            bucket = _bucket(getattr(spec, "dimension_path", ()) or ())
            if bucket is not None:
                out[spec.dataset_id] = bucket
        return out

    def _aggregation_rules(self, series_ids: list[str]) -> dict[str, str]:
        """Katalogdaki toplama kuralı (default_agg); okunamazsa stok gibi son gözlem."""
        if not series_ids:
            return {}
        quoted = ", ".join("'" + sid.replace("'", "''") + "'" for sid in series_ids)
        try:
            result = self.lakehouse.execute_sql(f"SELECT series_id, default_agg FROM meta.series WHERE series_id IN ({quoted})")
        except Exception:  # noqa: BLE001
            return {}
        data = getattr(result, "data", None)
        if data is None or data.empty:
            return {}
        return {str(r[0]): str(r[1] or "last") for r in data.itertuples(index=False)}

    def _is_amount(self, series_ids: list[str]) -> bool:
        """Tutar serisi mi (stok/akım)? Faiz, oran, kur ve endeks endekslenmez."""
        quoted = ", ".join("'" + sid.replace("'", "''") + "'" for sid in series_ids)
        try:
            data = self.lakehouse.execute_sql(f"SELECT measure_type, unit FROM meta.series WHERE series_id IN ({quoted})").data
        except Exception:  # noqa: BLE001
            return False
        if data is None or data.empty:
            return False
        return all(str(m).startswith(("stock", "flow")) for m in data.iloc[:, 0])

    def _join_session_tables(self, table: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
        """Oturumdaki tablolar ay anahtarıyla eklenir; ay başına birden çok satır varsa tablo alınmaz."""
        from ..builder.temporal import canonical_month, infer_temporal

        joined: list[str] = []
        lines: list[str] = []
        months = pd.to_datetime(table["donem"]).dt.strftime("%Y-%m")
        sources = self.workspace.sources() if hasattr(self.workspace, "sources") else []
        for source in sources:
            frame = source.frame
            if frame is None or frame.empty:
                continue
            temporal = infer_temporal(frame)
            if temporal.period_column is None:
                continue
            keys = frame[temporal.period_column].map(canonical_month)
            if keys.isna().all() or keys.dropna().duplicated().any():
                lines.append(f"NOT: {source.id} ({source.title[:50]}) aylık tekil anahtar taşımıyor; eklenmedi.")
                continue
            numeric = [c for c in frame.columns if c != temporal.period_column
                       and pd.api.types.is_numeric_dtype(pd.to_numeric(frame[c], errors="coerce"))
                       and pd.to_numeric(frame[c], errors="coerce").notna().any()
                       and not re.search(r"ortalama|oran|faiz|%|endeks|period|donem|dönem|yil|year|month|ay$",
                                         str(c), re.I)]
            added = []
            for column in numeric:
                name = str(column) if str(column) not in table.columns else f"{source.id}_{column}"
                lookup = dict(zip(keys, pd.to_numeric(frame[column], errors="coerce")))
                table[name] = months.map(lookup)
                added.append(name)
            if added:
                joined.extend(added)
                lines.append(f"OTURUM TABLOSU: {source.id} ({source.title[:60]}) ay üzerinden eklendi: {', '.join(added)}")
        return table, joined, lines

    def validate_refs(self, params: BreakdownPanelParams) -> ToolError | None:
        if not params.series and not params.groups:
            return ToolError(error_code="INVALID_ARGS", layer="schema", message="En az bir seri ya da grup ver.")
        if params.period_from > params.period_to:
            return ToolError(error_code="INVALID_ARGS", layer="schema", message="period_from, period_to'dan sonra olamaz.")
        names = [s.column_name for s in params.series] + [g.column_name for g in params.groups]
        if len(set(names)) != len(names):
            return ToolError(error_code="INVALID_ARGS", layer="schema", message="Sütun adları tekrar ediyor.")
        for series_id in [s.series_id for s in params.series] + [g.total_series_id for g in params.groups]:
            try:
                self._spec(series_id)
            except LakehouseError as exc:
                return ToolError(error_code="DATASET_NOT_FOUND", layer="reference", message=str(exc),
                                 hint="Seri kimliğini lakehouse_search ile bul.")
            if series_id.startswith("gold."):
                return ToolError(error_code="INVALID_ARGS", layer="reference",
                                 message=f"'{series_id}' bir Gold tablosu; bu araç seri kimliği alır.")
        question = str(getattr(self._registry, "active_question", "") or "")
        if params.value == "level" and FLOW_INTENT.search(question):
            return ToolError(
                error_code="INVALID_ARGS", layer="policy", retryable=True,
                message="Kullanıcı stok değil aylık hareket istiyor; value=level bu soruya cevap değil.",
                hint="Aynı çağrıyı value=monthly_change ile yap; araç bir önceki ayı kendisi çeker.",
            )
        for group in params.groups:
            if not self._buckets(group.total_series_id):
                return ToolError(
                    error_code="VALUE_NOT_FOUND", layer="reference",
                    message=f"'{group.total_series_id}' için katalogda vade kovası yok; grup üretilemez.",
                    hint="Kovaları olan bir toplam seç ya da kullanıcıya bu seride vade kırılımı olmadığını söyle.",
                )
            if group.min_months is not None and group.max_months is not None and group.min_months >= group.max_months:
                return ToolError(error_code="INVALID_ARGS", layer="schema",
                                 message=f"{group.column_name}: min_months, max_months'tan küçük olmalı.")
        return None

    # ------------------------------------------------------------ hesap
    def run(self, params: BreakdownPanelParams) -> ToolResult:
        first = pd.Period(params.period_from, "M")
        last = pd.Period(params.period_to, "M")
        fetch_from = first - 1 if params.value == "monthly_change" else first

        plan: list[tuple[str, list[str]]] = [(s.column_name, [s.series_id]) for s in params.series]
        # Grubu istenen toplam, seriler arasında yoksa tabloya kendiliğinden girer (23 Eyl senaryo koşusu: model toplamı
        # unuttu, tablo yalnız grupları taşıdı). Ad, grup sütunlarının ortak ön ekinden türer: tp_3aya_kadar → tp_toplam.
        listed = {s.series_id for s in params.series}
        for total_id in dict.fromkeys(g.total_series_id for g in params.groups):
            if total_id in listed:
                continue
            prefixes = {g.column_name.split("_", 1)[0] for g in params.groups if g.total_series_id == total_id}
            name = f"{prefixes.pop()}_toplam" if len(prefixes) == 1 else total_id.split(":", 1)[-1].lower()
            if name not in {column for column, _ in plan} and name not in {g.column_name for g in params.groups}:
                plan.append((name, [total_id]))
        notes: list[str] = []
        definitions: list[str] = []
        partitions: dict[str, list[str]] = {}
        for group in params.groups:
            buckets = self._buckets(group.total_series_id)
            chosen, note = resolve_group(buckets, group.min_months, group.max_months)
            if not chosen:
                return ToolResult.fail("VALUE_NOT_FOUND", f"{group.column_name}: istenen aralığa düşen kova yok.",
                                       layer="data", retryable=False)
            ordered = sorted(chosen, key=lambda sid: buckets[sid][1])
            plan.append((group.column_name, ordered))
            definitions.append(f"{group.column_name} = " + " + ".join(buckets[sid][0] for sid in ordered)
                               + f" ({group.total_series_id} kovaları)")
            if note:
                notes.append(f"{group.column_name}: {note}")
            partitions.setdefault(group.total_series_id, []).extend(ordered)

        wanted = sorted({sid for _, ids in plan for sid in ids} | set(partitions)
                        | ({params.deflator_series_id} if params.deflator_series_id else set()))
        relation_of = getattr(self.lakehouse, "_relation_for", None)
        by_relation: dict[str, list[str]] = {}
        for sid in wanted:
            by_relation.setdefault(relation_of(sid) if callable(relation_of) else "silver.fact_observation", []).append(sid)
        start = fetch_from.start_time.date().isoformat()
        end = last.end_time.date().isoformat()
        parts = [
            f"SELECT series_id, observation_date, value FROM {relation} WHERE series_id IN ("
            + ", ".join("'" + sid.replace("'", "''") + "'" for sid in ids)
            + f") AND observation_date BETWEEN DATE '{start}' AND DATE '{end}'"
            for relation, ids in by_relation.items()
        ]
        sql = " UNION ALL ".join(parts) + " ORDER BY observation_date, series_id"
        try:
            result = self.lakehouse.execute_sql(sql)
        except LakehouseError as exc:
            return ToolResult.fail("SQL_FAILED", str(exc), layer="data")
        raw = result.data if result.data is not None else pd.DataFrame(columns=["series_id", "observation_date", "value"])
        raw = raw.assign(month=pd.to_datetime(raw["observation_date"], errors="coerce").dt.to_period("M"))
        # Haftalık/günlük seri aylığa katalog kuralıyla iner (faiz/kur: ortalama, stok: son gözlem, akım: toplam).
        # Senaryo 5 (23 Eyl): mevduat, faiz, kur ve TÜFE tek panelde, tek aylık eksende.
        rules = self._aggregation_rules(wanted)
        aggregated_notes: list[str] = []
        frames = []
        for sid, part in raw.dropna(subset=["month"]).sort_values("observation_date").groupby("series_id"):
            rule = rules.get(sid, "last")
            counts = part.groupby("month").size()
            if int(counts.max()) > 1:
                aggregated_notes.append(f"{sid}: ayda birden çok gözlem, aylığa '{rule}' kuralıyla indirildi")
            values = part.dropna(subset=["value"]).groupby("month")["value"]
            series = {"avg": values.mean(), "sum": values.sum(min_count=1), "first": values.first(),
                      "min": values.min(), "max": values.max()}.get(rule, values.last())
            frames.append(series.rename(sid))
        wide = pd.concat(frames, axis=1) if frames else pd.DataFrame()
        notes.extend(aggregated_notes)
        months = pd.period_range(fetch_from, last, freq="M")
        wide = wide.reindex(months)

        table = pd.DataFrame({"donem": [m.end_time.normalize().date() for m in months]})
        for column, ids in plan:
            present = [sid for sid in ids if sid in wide.columns]
            if len(present) < len(ids):
                table[column] = float("nan")
                notes.append(f"{column}: {len(ids) - len(present)} kova/serinin bu dönemde gözlemi yok; sütun boş.")
                continue
            block = wide[ids]
            table[column] = block.sum(axis=1, min_count=len(ids)).where(block.notna().all(axis=1)).to_numpy()

        control_lines: list[str] = []
        for total_id, members in partitions.items():
            all_buckets = set(self._buckets(total_id))
            if set(members) != all_buckets or len(members) != len(set(members)) or total_id not in wide.columns:
                continue
            diff = (wide[members].sum(axis=1, min_count=len(members)) - wide[total_id]).abs()
            tolerance = 0.5 * len(members)
            bad = int((diff > tolerance).sum())
            compared = int(diff.notna().sum())
            control_lines.append(
                f"DENETİM {total_id}: gruplar toplamı karşılıyor mu? {compared} ayda karşılaştırıldı, "
                f"±{tolerance:g} dışında kalan ay: {bad} (en büyük fark {diff.max():g})."
            )

        value_cols = [column for column, _ in plan]
        if params.value == "monthly_change":
            for column in value_cols:
                table[column] = table[column] - table[column].shift(1)
            table = table.iloc[1:].reset_index(drop=True)
        table["donem"] = pd.to_datetime(table["donem"])

        missing = {c: int(table[c].isna().sum()) for c in value_cols if table[c].isna().any()}
        mode = "aylık hareket (bu ay − önceki ay)" if params.value == "monthly_change" else "ay sonu değer"
        provenance = QueryProvenance(
            sql=sql,
            dataset_ids=wanted,
            sources=["Kırılım paneli — " + "; ".join(definitions) if definitions else "Seri paneli"],
        )
        extra_lines: list[str] = []
        amount_columns = [column for column, ids in plan if self._is_amount(ids)]
        if params.join_session:
            table, joined, join_lines = self._join_session_tables(table)
            extra_lines.extend(join_lines)
            amount_columns.extend(joined)
            if params.deflator_series_id:
                if params.deflator_series_id not in wide.columns:
                    extra_lines.append(f"NOT: {params.deflator_series_id} gözlemi yok; reel değer hesaplanmadı.")
                else:
                    deflator = wide[params.deflator_series_id]
                    base = pd.Period(params.base_period or params.period_to, "M")
                    base_value = deflator.get(base)
                    months_of = pd.to_datetime(table["donem"]).dt.to_period("M")
                    ratio = months_of.map(lambda m: (base_value / deflator.get(m)) if base_value and deflator.get(m) else None)
                    for column in joined:
                        real = f"{column}_reel"
                        table[real] = pd.to_numeric(table[column], errors="coerce") * pd.to_numeric(ratio, errors="coerce")
                        amount_columns.append(real)
                    extra_lines.append(f"REEL: oturumdan gelen tutarlar {params.deflator_series_id} ile {base} fiyatlarına "
                                       f"çevrildi (reel = nominal × endeks({base}) / endeks(ay)).")
        if params.index_base:
            base_month = pd.Period(params.index_base, "M")
            months_of = pd.to_datetime(table["donem"]).dt.to_period("M")
            row = table.loc[months_of == base_month]
            for column in list(dict.fromkeys(amount_columns)):
                if column not in table.columns or row.empty:
                    continue
                base_value = pd.to_numeric(row[column], errors="coerce").iloc[0]
                if base_value is None or pd.isna(base_value) or base_value == 0:
                    extra_lines.append(f"NOT: {column} için {params.index_base} değeri yok ya da sıfır; endekslenmedi.")
                    continue
                table[f"{column}_endeks"] = pd.to_numeric(table[column], errors="coerce") / base_value * 100
            extra_lines.append(f"ENDEKS: tutar serileri {params.index_base}=100; faiz, kur ve fiyat endeksi kendi biriminde.")
        notes.extend(line.removeprefix("NOT: ") for line in extra_lines if line.startswith("NOT: "))
        control_lines.extend(line for line in extra_lines if not line.startswith("NOT: "))
        self.workspace.set_table(table, description=params.purpose, provenance=provenance)
        self.workspace.title = params.purpose
        card = [
            f"PANEL: {len(table)} ay ({params.period_from} → {params.period_to}), değer: {mode}.",
            *(["GRUPLAR: " + " | ".join(definitions)] if definitions else []),
            *([f"TABAN AYI: {fetch_from} çekildi, yalnız ilk ayın hareketi için kullanıldı ve tablodan çıkarıldı."]
              if params.value == "monthly_change" else []),
            *control_lines,
            *(["NOT: " + n for n in notes]),
            *([f"BOŞ HÜCRE: {missing} (gözlem yok; sıfır yazılmadı)"] if missing else []),
            *(["DEĞER TÜRÜ: bu tablodaki sayılar STOK DEĞİL, aylık harekettir (bu ay − önceki ay); negatif değer o ay "
               "azalış demektir, veri hatası değildir."] if params.value == "monthly_change" else []),
            "İSTENEN TABLO BU: kullanıcı açıkça istemedikçe pay, oran, yüzde ya da başka türev sütun HESAPLAMA; "
            "cevapta grup tanımlarını ve değer türünü açıkça yaz.",
            "İlk 5 satır:\n" + table.head(5).to_string(index=False),
        ]
        return ToolResult(content="\n".join(card), data=table, provenance=provenance)


__all__ = ["BREAKDOWN_PROMPT_RULES", "LakehouseBreakdownPanelTool", "resolve_group"]
