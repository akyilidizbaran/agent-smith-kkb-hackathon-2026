"""Lakehouse araç ailesi (V3) — ekip motoruyla AYNI araç adları, yapılandırılmış hatalar.

Adlar bilerek aynı (`lakehouse_search/describe/distinct_values/query`): golden
set'in `must_use_tools` kontrolleri ve benchmark'ın SQL denetimleri iki motorda
da değişmeden çalışır; karşılaştırma araç adına değil davranışa bakar.

Fark: "seri yok / kolon yok / dönem kapsam dışı / dönem filtresi eksik" kararları
`validate_refs` içinde, sorgu çalışmadan verilir ve `ToolError` zarfıyla döner.
"""

from __future__ import annotations

import difflib
import re

from pydantic import BaseModel, Field

from kkb_agent.contracts.catalog import ColumnRole, DatasetSpec
from kkb_agent.contracts.lakehouse import LakehouseClient, LakehouseError
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.domain import kisa_terim

from ..core.tool import Tool, ToolResult
from ..errors import ToolError

_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _closest(name: str, options: list[str], n: int = 3) -> list[str]:
    return difflib.get_close_matches(name, options, n=n, cutoff=0.3) or options[:n]


def _dataset_or_error(lakehouse: LakehouseClient, dataset_id: str) -> tuple[DatasetSpec | None, ToolError | None]:
    try:
        return lakehouse.get_dataset(dataset_id), None
    except LakehouseError:
        ids = [s.dataset_id for s in lakehouse.list_datasets()]
        return None, ToolError(
            error_code="SERIES_NOT_FOUND", layer="reference",
            message=f"'{dataset_id}' adlı tablo katalogda yok.",
            candidates=_closest(dataset_id, ids),
            hint="Adaylardan birini birebir kullan; emin değilsen lakehouse_search çağır.",
        )


# ---------------------------------------------------------------------------
class SearchParams(BaseModel):
    query: str = Field(description="Aranan konuyu anlatan kısa Türkçe ifade, ör. 'aylık {example_entity}'")


class LakehouseSearchTool(Tool):
    name = "lakehouse_search"
    description = (
        "Veri havuzunda hangi tabloların bulunduğunu keşfeder. Ön-yüklü katalogda aradığını "
        "bulamadığında kullan. Tablo adlarını ve ne içerdiklerini döndürür."
    )
    Params = SearchParams

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse

    def run(self, params: SearchParams) -> ToolResult:
        specs = self.lakehouse.search_datasets(params.query)
        if not specs:
            return ToolResult(content="Bu konuyla ilgili tablo bulunamadı.")
        lines = ["Bulunan tablolar:"]
        for s in specs:
            lines.append(
                f"- {s.dataset_id}: {s.name}. {s.description[:180]} "
                f"[frekans: {s.frequency.value}, kapsam: {s.coverage.start}→{s.coverage.end}]"
            )
        return ToolResult(content="\n".join(lines))


# ---------------------------------------------------------------------------
class DescribeParams(BaseModel):
    dataset_id: str = Field(description="Tablo kimliği (katalogdaki ad)")


class LakehouseDescribeTool(Tool):
    name = "lakehouse_describe"
    description = (
        "Bir tablonun kolonlarını, birimlerini, kümülatif olup olmadığını ve örnek satırlarını "
        "gösterir. Ön-yüklü katalogda olmayan bir tablo için SQL yazmadan önce çağır."
    )
    Params = DescribeParams

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse

    def validate_refs(self, params: DescribeParams) -> ToolError | None:
        _, err = _dataset_or_error(self.lakehouse, params.dataset_id)
        return err

    def run(self, params: DescribeParams) -> ToolResult:
        spec = self.lakehouse.get_dataset(params.dataset_id)
        sample = self.lakehouse.preview(params.dataset_id, n=5)
        return ToolResult(content=spec.to_prompt_card() + "\n\nÖrnek satırlar:\n" + sample.data.to_string(index=False))


# ---------------------------------------------------------------------------
class DistinctValuesParams(BaseModel):
    dataset_id: str = Field(description="Tablo kimliği")
    column: str = Field(description="Değerleri listelenecek kırılım kolonu, ör. '{example_category_column}'")
    contains: str | None = Field(
        default=None,
        description="Sadece bu metni içeren değerleri getir (büyük/küçük harf duyarsız), ör. '{example_entity}'.",
    )
    limit: int = Field(default=20, ge=1, le=200, description="En fazla kaç değer döndürülsün")


class LakehouseDistinctValuesTool(Tool):
    name = "lakehouse_distinct_values"
    description = (
        "Bir kırılım kolonundaki GERÇEK değerleri listeler. Ön-yüklü listede bulamadığın bir "
        "kalemi filtrelemeden önce çağır; değer adını asla tahmin etme."
    )
    Params = DistinctValuesParams

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse

    def validate_refs(self, params: DistinctValuesParams) -> ToolError | None:
        spec, err = _dataset_or_error(self.lakehouse, params.dataset_id)
        if err:
            return err
        assert spec is not None
        if spec.column(params.column) is None:
            cols = [c.name for c in spec.columns]
            return ToolError(
                error_code="COLUMN_NOT_FOUND", layer="reference",
                message=f"'{params.column}' kolonu {params.dataset_id} tablosunda yok.",
                candidates=_closest(params.column, cols),
                hint="Adaylardan birini birebir kullan.",
            )
        return None

    def run(self, params: DistinctValuesParams) -> ToolResult:
        spec = self.lakehouse.get_dataset(params.dataset_id)
        col = params.column
        has_flag = spec.column("is_alt_toplam") is not None
        select = f"{col}, is_alt_toplam" if has_flag else col
        where = ""
        if params.contains:
            safe = params.contains.replace("'", "''")
            where = f"WHERE {col} ILIKE '%{safe}%'"
        result = self.lakehouse.execute_sql(
            f"SELECT DISTINCT {select} FROM {params.dataset_id} {where} ORDER BY 1 LIMIT {int(params.limit)}"
        )
        if result.is_empty:
            return ToolResult.fail(ToolError(
                error_code="EMPTY_DATASET", layer="runtime",
                message=f"'{col}' kolonunda '{params.contains or ''}' içeren değer yok.",
                hint="Daha genel bir arama terimi dene veya contains parametresini boş bırak.",
            ))
        # Filtresiz çağrı çok fazla değer döndürdüğünde model boğuluyor (ekip ölçümü: 0/7);
        # tam listeyi basmak yerine daraltmaya yönlendir.
        total = self._count(params.dataset_id, col)
        if params.contains is None and total > 15:
            sample = "\n".join(f"  - {getattr(r, col, r[0])}" for r in result.data.head(8).itertuples(index=False))
            first = result.data.iloc[0][col] if col in result.data.columns else result.data.iloc[0, 0]
            return ToolResult(
                content=(
                    f"'{col}' kolonunda {total} farklı değer var — aradığın kalemi daralt: bu aracı "
                    f"contains parametresiyle tekrar çağır, ör. contains='{kisa_terim(str(first))}'.\n"
                    f"İlk 8 değer (fikir vermesi için):\n{sample}"
                ),
                data=result.data,
            )
        lines = [f"'{col}' kolonundaki değerler ({len(result.data)} adet):"]
        for row in result.data.itertuples(index=False):
            value = getattr(row, col, row[0])
            flag = "   ⚠ ALT TOPLAM (alt kalemlerle birlikte toplama)" if has_flag and bool(row[1]) else ""
            lines.append(f"  - {value}{flag}")
        lines.append(
            "\nDİKKAT: Bu değerlerden SADECE BİRİNİ seç ve birebir yaz. Kullanıcı açıkça 'hepsi' / "
            "'karşılaştır' demedikçe birden fazlasını IN veya LIKE ile birlikte alma."
        )
        return ToolResult(content="\n".join(lines), data=result.data)

    def _count(self, dataset_id: str, column: str) -> int:
        try:
            r = self.lakehouse.execute_sql(f"SELECT COUNT(DISTINCT {column}) AS n FROM {dataset_id}")
            return int(r.data.iloc[0, 0]) if not r.is_empty else 0
        except LakehouseError:
            return 0


# ---------------------------------------------------------------------------
class QueryParams(BaseModel):
    sql: str = Field(
        description="Çalıştırılacak DuckDB SQL sorgusu. Sadece SELECT/WITH. Kolon ve tablo adları "
        "katalogla birebir aynı olmalı."
    )
    purpose: str = Field(description="Bu sorgunun neyi hesapladığını anlatan tek cümlelik Türkçe açıklama.")
    as_active_table: bool = Field(
        default=True,
        description="Bu sorgu kullanıcının sorusunu cevaplayan SONUÇ mu? Öyleyse true — tek satırlık "
        "cevap olsa bile true. Sadece ara kontroller için false.",
    )


class LakehouseQueryTool(Tool):
    name = "lakehouse_query"
    description = (
        "Veri havuzunda SQL çalıştırır ve sonucu döndürür. Toplama, ortalama, yüzde değişim gibi TÜM "
        "hesapları bu araçla yaptır, kendin hesaplama. Sonuç aktif analiz tablosu olarak kaydedilir."
    )
    Params = QueryParams
    mutates = True

    def __init__(self, lakehouse: LakehouseClient, workspace: AnalysisWorkspace, registry: object | None = None) -> None:
        self.lakehouse = lakehouse
        self.workspace = workspace
        self._registry = registry  # active_question için

    # --- referans katmanı ---
    def validate_refs(self, params: QueryParams) -> ToolError | None:
        sql = params.sql
        specs = [s for s in self.lakehouse.list_datasets() if s.dataset_id in sql]
        if not specs:
            ids = [s.dataset_id for s in self.lakehouse.list_datasets()]
            return ToolError(
                error_code="SERIES_NOT_FOUND", layer="reference",
                message="Sorgu katalogdaki hiçbir tabloya başvurmuyor.",
                candidates=ids[:5],
                hint="FROM kısmında katalogdaki tablo adını birebir kullan.",
            )
        # ADR-0017: soruda yıl geçiyor ama sorguda geçmiyorsa reddet (ölçülmüş hata modu).
        question = getattr(self._registry, "active_question", "") or ""
        asked = set(_YEAR_RE.findall(question))
        in_sql = set(_YEAR_RE.findall(sql))
        missing = sorted(asked - in_sql)
        if missing:
            return ToolError(
                error_code="MISSING_PERIOD_FILTER", layer="reference",
                message=f"Kullanıcı {', '.join(missing)} dönemini sordu ama sorguda dönem filtresi yok.",
                hint=(
                    f"Sorguya dönem kısıtını ekle, ör. WHERE EXTRACT(year FROM <dönem_kolonu>) = {missing[0]}. "
                    "LAG/önceki dönem gerekiyorsa pencereyi alt sorguda hesapla, yıl filtresini DIŞ sorguda uygula."
                ),
            )
        # Edge-case 5 — DOUBLE_COUNT: alt toplam bayrağı olan tabloda toplama var ama ne bayrak
        # filtresi ne de tek kalem eşitliği var → alt toplam + bileşenler aynı toplama girer.
        for spec in specs:
            if spec.column("is_alt_toplam") is None:
                continue
            low = sql.lower()
            dim = next((c.name for c in spec.columns if c.role == ColumnRole.DIMENSION and c.dtype.upper() in ("VARCHAR", "TEXT", "STRING")), None)
            has_sum = re.search(r"\bsum\s*\(", low) is not None
            filters_flag = "is_alt_toplam" in low
            picks_items = dim is not None and re.search(rf"\b{re.escape(dim)}\b\s*(=|in\s*\()", low) is not None
            if has_sum and not filters_flag and not picks_items:
                return ToolError(
                    error_code="DOUBLE_COUNT", layer="reference",
                    message=f"{spec.dataset_id} tablosunda alt toplam satırları var; SUM alt toplamı bileşenleriyle birlikte toplar.",
                    hint="Ya `is_alt_toplam = FALSE` filtresi ekle ya da toplanacak kalemleri "
                         f"{dim or 'kırılım kolonu'} = / IN ile açıkça seç.",
                )
        # Kapsam: sorgudaki yılların hiçbiri tablonun kapsamında değilse veri yok — tekrar denemek anlamsız.
        years = {int(y) for y in in_sql}
        if years:
            for spec in specs:
                lo, hi = spec.coverage.start.year, spec.coverage.end.year
                if not any(lo <= y <= hi for y in years):
                    return ToolError(
                        error_code="OUT_OF_COVERAGE", layer="reference", retryable=False,
                        message=(
                            f"Sorgudaki {', '.join(map(str, sorted(years)))} yılı {spec.dataset_id} "
                            f"tablosunun kapsamı dışında (mevcut aralık: {spec.coverage.start} → {spec.coverage.end})."
                        ),
                        hint=(
                            "Araç çağırmayı bırak; kullanıcıya istediği dönemin verisinin mevcut olmadığını ve "
                            "elde hangi aralığın bulunduğunu tek paragrafta söyle. Sayı tahmin etme."
                        ),
                    )
        return None

    def run(self, params: QueryParams) -> ToolResult:
        result = self.lakehouse.execute_sql(params.sql)
        if result.is_empty:
            return ToolResult.fail(ToolError(
                error_code="EMPTY_DATASET", layer="runtime",
                message="Sorgu çalıştı ancak hiç satır dönmedi; dönem kapsam içinde, sorun büyük olasılıkla filtre değerinde.",
                hint="Kalem/kategori adını ön-yüklü listeden birebir kopyala veya lakehouse_distinct_values ile doğrula.",
            ))
        if params.as_active_table:
            self.workspace.set_table(result.data, description=params.purpose, provenance=result.provenance)
            self.workspace.title = params.purpose
        df = result.data
        # ≤24 satır (aylık seri, iki yıl) tam gösterilir: 12 satırın 10'unu görünce model
        # kalanını görmek için aynı sorguyu tekrarlıyordu (L4-01 döngüsü, 10 Eylül 2. oturum).
        n = len(df) if len(df) <= 24 else 10
        content = (
            f"Sorgu başarılı: {len(df)} satır, {len(df.columns)} sütun.\n"
            f"Sütunlar: {', '.join(df.columns)}\n"
            f"İlk {n} satır:\n{df.head(n).to_string(index=False)}"
        )
        if len(df) > n:
            content += f"\n... ({len(df) - n} satır daha; tamamı analiz tablosunda)"
        units = self._units_for(list(df.columns), result.provenance.dataset_ids)
        if units:
            content += "\nBirimler: " + ", ".join(units)
        content += f"\nKaynak: {result.provenance.summary()}"
        return ToolResult(content=content, data=df, provenance=result.provenance)

    def _units_for(self, columns: list[str], dataset_ids: list[str]) -> list[str]:
        out: list[str] = []
        for ds_id in dataset_ids:
            try:
                spec = self.lakehouse.get_dataset(ds_id)
            except LakehouseError:
                continue
            for col in columns:
                cs = spec.column(col)
                if cs and cs.unit and cs.role == ColumnRole.MEASURE:
                    out.append(f"{col} = {cs.unit}")
        return out
