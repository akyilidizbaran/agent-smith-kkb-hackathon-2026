"""Workspace araçları — analiz tablosu üzerinde ameliyat.

Örnek senaryonun kalbi burası:
    "konut kredisi ve faiz tablosunu BOZMADAN sadece tutarları enflasyondan arındır"
    "bu tabloyu HİÇ BOZMADAN yeni bir sütun olarak konut fiyat endeksini getir"

Bu iki cümlede kullanıcı, üzerinde çalıştığı tablonun kimliğini koruyor. Her
soruda sıfırdan sorgu üreten bir agent burada başarısız olur: tablo yeniden
kurulur, satır sayısı değişir, kullanıcının baktığı görünüm kaybolur.

AnalysisWorkspace bu durumu zaten tutuyordu; bu modül onu modele açar.
Ayrım kasıtlı: model tabloyu YENİDEN KURAMAZ, yalnızca üzerine sütun
ekleyebilir veya mevcut sütunlardan yeni sütun türetebilir.
"""

from __future__ import annotations

import re

import duckdb
import pandas as pd
from pydantic import BaseModel, Field

from ..adapters.duckdb_lakehouse import hardened_connection
from ..contracts.lakehouse import LakehouseClient, LakehouseError
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace

# Türetilmiş sütun ifadesinde veri değiştiren / dosya okuyan hiçbir şey olamaz.
_UNSAFE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|ATTACH|COPY|INSTALL|LOAD|PRAGMA|"
    r"read_csv|read_parquet|read_json|read_text|read_blob|glob)\b",
    re.IGNORECASE,
)


class AddColumnParams(BaseModel):
    dataset_id: str = Field(description="Verinin çekileceği tablo")
    key_column: str = Field(
        description="Kaynak tablodaki eşleştirme kolonu, ör. '{example_time_column}'"
    )
    value_column: str = Field(
        description="Çekilecek ÖLÇÜM kolonu. Tabloda GERÇEKTEN VAR OLAN bir kolon adı "
        "olmalı, ör. '{example_measure}'. Yeni sütuna vermek istediğin adı buraya yazma."
    )
    column_name: str = Field(description="Analiz tablosuna eklenecek yeni sütunun adı")
    join_on: str = Field(
        description="Analiz tablosundaki eşleştirme kolonu, ör. '{example_time_column}'"
    )
    purpose: str = Field(description="Bu sütunun ne olduğunu anlatan tek cümlelik Türkçe açıklama")
    filter_column: str | None = Field(
        default=None,
        description="İsteğe bağlı kategori filtresi kolonu, ör. '{example_category_column}'",
    )
    filter_value: str | None = Field(
        default=None,
        description="filter_column'un alacağı BİREBİR değer. Önce "
        "lakehouse_distinct_values ile gerçek değeri doğrula.",
    )


class WorkspaceAddColumnTool(Tool):
    """Mevcut tabloyu bozmadan yeni sütun ekler.

    Bu araç bilerek SQL ALMIYOR. Ölçülmüş sebep: serbest SQL alan sürümünde
    model, eklemek istediği yeni sütunun adını SELECT listesine var olan bir
    kolon gibi yazdı ("SELECT donem, tasit_kredisi FROM ..."), hata aldı,
    hatadan çıkamadı ve sonunda lakehouse_query'ye kaçıp analiz tablosunu
    yeniden kurdu — yani "tabloyu bozmadan" garantisi çöktü.

    Yapılandırılmış parametrelerde bu hata mümkün değil: kolon adları katalogla
    doğrulanır, SQL'i harness üretir. Semantic layer literatüründeki gözlemin
    küçük ölçekli uygulaması — deterministik sorgu üretimi, modelin sessizce
    yanlış sorgu kurmasını imkânsız kılar.
    """

    name = "workspace_add_column"
    description = (
        "Mevcut analiz tablosunu BOZMADAN, veri havuzundan çektiği bir ölçümü yeni sütun "
        "olarak ekler. Kullanıcı 'tabloyu bozmadan', 'bu tabloya', 'yeni sütun olarak ekle' "
        "dediğinde BU aracı kullan — lakehouse_query ile yeni tablo kurma, kullanıcının "
        "baktığı tablo kaybolur. Satır sayısı değişmez."
    )
    Params = AddColumnParams

    def __init__(self, lakehouse: LakehouseClient, workspace: AnalysisWorkspace) -> None:
        self.lakehouse = lakehouse
        self.workspace = workspace

    def run(self, params: AddColumnParams) -> ToolResult:
        if not self.workspace.has_table:
            return ToolResult.error(
                "Ortada bir analiz tablosu yok. Önce lakehouse_query ile tabloyu oluştur."
            )
        table = self.workspace.table
        assert table is not None

        if params.join_on not in table.columns:
            return ToolResult.error(
                f"'{params.join_on}' kolonu analiz tablosunda yok. "
                f"Mevcut kolonlar: {', '.join(table.columns)}"
            )
        if params.column_name in table.columns:
            return ToolResult.error(f"'{params.column_name}' zaten tabloda var. Farklı bir ad seç.")

        # Kolon adları katalogla doğrulanır: model var olmayan bir kolon uyduramaz.
        try:
            spec = self.lakehouse.get_dataset(params.dataset_id)
        except LakehouseError as exc:
            return ToolResult.error(str(exc))

        gecerli = {c.name for c in spec.columns}
        for alan, deger in (
            ("key_column", params.key_column),
            ("value_column", params.value_column),
            ("filter_column", params.filter_column),
        ):
            if deger and deger not in gecerli:
                ipucu = ""
                if deger == params.column_name:
                    ipucu = (
                        f" '{deger}' senin eklemek istediğin YENİ sütunun adı; kaynak tabloda "
                        f"böyle bir kolon yok. value_column'a var olan bir ölçüm kolonu yaz."
                    )
                return ToolResult.error(
                    f"{alan}='{deger}' {params.dataset_id} tablosunda yok.{ipucu} "
                    f"Mevcut kolonlar: {', '.join(sorted(gecerli))}"
                )

        # SQL'i harness üretir, model değil.
        where = ""
        if params.filter_column and params.filter_value is not None:
            kacisli = params.filter_value.replace("'", "''")
            where = f" WHERE {params.filter_column} = '{kacisli}'"
        sql = (
            f"SELECT {params.key_column}, {params.value_column} "
            f"FROM {params.dataset_id}{where}"
        )

        try:
            result = self.lakehouse.execute_sql(sql)
        except LakehouseError as exc:
            return ToolResult.error(str(exc))

        df = result.data
        if df.empty:
            return ToolResult.error(
                f"Sorgu hiç satır döndürmedi. filter_value='{params.filter_value}' "
                f"değerini lakehouse_distinct_values ile doğrula."
            )

        key_col, value_col = df.columns[0], df.columns[1]
        # Anahtar tiplerini hizala: DATE ile datetime64 karışımı sessizce NaN üretir.
        left_key = self._normalize(table[params.join_on])
        series = pd.Series(df[value_col].to_numpy(), index=self._normalize(df[key_col]))
        series = series[~series.index.duplicated(keep="first")]
        aligned = series.reindex(left_key)

        matched = int(aligned.notna().sum())
        if matched == 0:
            return ToolResult.error(
                f"Eşleşen satır bulunamadı: kaynak '{key_col}' değerleri ile tablodaki "
                f"'{params.join_on}' değerleri örtüşmüyor."
            )

        self.workspace.add_column(
            params.column_name,
            pd.Series(aligned.to_numpy(), index=table.index),
            description=params.purpose,
            provenance=result.provenance,
        )

        note = ""
        if matched < len(table):
            note = f" ({len(table) - matched} satırda karşılık yok, boş bırakıldı)"
        updated = self.workspace.table
        assert updated is not None
        return ToolResult(
            content=(
                f"'{params.column_name}' sütunu eklendi{note}. Tablo bozulmadı: "
                f"{len(updated)} satır, {len(updated.columns)} sütun.\n"
                f"Sütunlar: {', '.join(updated.columns)}\n"
                f"İlk 5 satır:\n{updated.head(5).to_string(index=False)}"
            ),
            data=updated,
            provenance=result.provenance,
        )

    @staticmethod
    def _normalize(s: pd.Series) -> pd.Index:
        """Tarih benzeri anahtarları ortak tipe indirger."""
        if pd.api.types.is_datetime64_any_dtype(s):
            return pd.Index(pd.to_datetime(s).dt.normalize())
        if s.dtype == object:
            try:
                return pd.Index(pd.to_datetime(s).normalize())
            except (ValueError, TypeError):
                return pd.Index(s)
        return pd.Index(s)


class ComputeColumnParams(BaseModel):
    expression: str = Field(
        description="Mevcut sütunlardan yeni sütun türeten SQL ifadesi. Sadece ifade yaz, "
        "SELECT yazma. İki sütunu oranlama: 'a_sutunu / b_sutunu * 100'. "
        "Dönemsel değişim: '{example_measure} - LAG({example_measure}) "
        "OVER (ORDER BY {example_time_column})'"
    )
    column_name: str = Field(description="Yeni sütunun adı")
    purpose: str = Field(description="Bu hesabın ne yaptığını anlatan tek cümlelik Türkçe açıklama")


class WorkspaceComputeColumnTool(Tool):
    """Mevcut sütunlardan yeni sütun türetir — hesap yine motorda yapılır.

    Enflasyondan arındırma, yüzde değişim, pay hesabı gibi işlemler burada
    çalışır. Model formülü yazar, hesabı DuckDB yapar; modelin kendi
    aritmetiğine hiçbir noktada güvenilmez.
    """

    name = "workspace_compute_column"
    description = (
        "Mevcut analiz tablosundaki sütunlardan yeni bir sütun HESAPLAR ve tabloya ekler: "
        "yüzde değişim, oran, bir seriyi başka bir seriye bölerek normalleştirme. Tablo "
        "bozulmaz, satır sayısı değişmez. Hesabı sen yapma, formülü bu araca yazdır."
    )
    Params = ComputeColumnParams

    def __init__(self, workspace: AnalysisWorkspace) -> None:
        self.workspace = workspace

    def run(self, params: ComputeColumnParams) -> ToolResult:
        if not self.workspace.has_table:
            return ToolResult.error(
                "Ortada bir analiz tablosu yok. Önce lakehouse_query ile tabloyu oluştur."
            )
        if _UNSAFE.search(params.expression):
            return ToolResult.error(
                "İfade yalnızca hesap içerebilir; veri değiştiren veya dosya okuyan "
                "ifadelere izin verilmez."
            )
        table = self.workspace.table
        assert table is not None
        if params.column_name in table.columns:
            return ToolResult.error(f"'{params.column_name}' zaten tabloda var.")

        # Adaptörle aynı sınırlar: dış dosya/ağ erişimi kapalı, yapılandırma kilitli.
        con = hardened_connection()
        try:
            con.register("analiz", table)
            out = con.execute(
                f'SELECT ({params.expression}) AS "{params.column_name}" FROM analiz'
            ).fetch_df()
        except Exception as exc:
            return ToolResult.error(
                f"İfade hesaplanamadı: {exc}. Kullanılabilir sütunlar: {', '.join(table.columns)}"
            )
        finally:
            con.close()

        if len(out) != len(table):
            return ToolResult.error(
                f"İfade {len(out)} satır üretti, tabloda {len(table)} satır var. "
                "Satır sayısını değiştiren bir ifade kullanma."
            )

        self.workspace.add_column(
            params.column_name,
            pd.Series(out.iloc[:, 0].to_numpy(), index=table.index),
            description=f"{params.purpose} [formül: {params.expression}]",
        )
        updated = self.workspace.table
        assert updated is not None
        return ToolResult(
            content=(
                f"'{params.column_name}' hesaplandı ve eklendi. Tablo bozulmadı: "
                f"{len(updated)} satır, {len(updated.columns)} sütun.\n"
                f"İlk 5 satır:\n{updated.head(5).to_string(index=False)}"
            ),
            data=updated,
        )


class ShowParams(BaseModel):
    max_rows: int = Field(default=24, description="Gösterilecek en fazla satır sayısı")


class WorkspaceShowTool(Tool):
    name = "workspace_show"
    description = (
        "Üzerinde çalışılan analiz tablosunun güncel halini ve ona uygulanan işlem geçmişini "
        "gösterir. Kullanıcı 'tabloyu göster' dediğinde veya tablonun son durumundan emin "
        "olman gerektiğinde kullan."
    )
    Params = ShowParams

    def __init__(self, workspace: AnalysisWorkspace) -> None:
        self.workspace = workspace

    def run(self, params: ShowParams) -> ToolResult:
        if not self.workspace.has_table:
            return ToolResult(content="Şu an aktif bir analiz tablosu yok.", ok=True)
        table = self.workspace.table
        assert table is not None
        lines = [
            f"Analiz tablosu: {len(table)} satır, {len(table.columns)} sütun",
            table.head(params.max_rows).to_string(index=False),
        ]
        if len(table) > params.max_rows:
            lines.append(f"... ({len(table) - params.max_rows} satır daha)")
        if self.workspace.history:
            lines.append("Uygulanan işlemler:")
            lines += [f"  {s.order}. {s.description}" for s in self.workspace.history]
        return ToolResult(content="\n".join(lines), data=table)
