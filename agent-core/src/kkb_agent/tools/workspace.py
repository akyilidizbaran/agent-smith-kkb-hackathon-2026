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
    sql: str = Field(
        description="Yeni sütunun verisini getiren sorgu. TAM İKİ kolon döndürmeli: "
        "önce eşleştirme anahtarı (genelde dönem), sonra değer. "
        "Örn: SELECT donem, toplam FROM bddk_aylik_krediler WHERE kalem = '...'"
    )
    column_name: str = Field(description="Tabloya eklenecek sütunun adı, ör. 'tasit_kredisi'")
    join_on: str = Field(
        description="Mevcut analiz tablosundaki eşleştirme kolonu, ör. 'donem'. "
        "Sorgunun ilk kolonu ile bu kolon eşleştirilir."
    )
    purpose: str = Field(description="Bu sütunun ne olduğunu anlatan tek cümlelik Türkçe açıklama")


class WorkspaceAddColumnTool(Tool):
    """Mevcut tabloyu bozmadan yeni sütun ekler."""

    name = "workspace_add_column"
    description = (
        "Mevcut analiz tablosunu BOZMADAN yeni bir sütun ekler. Kullanıcı 'tabloyu bozmadan', "
        "'bu tabloya', 'yeni sütun olarak ekle' dediğinde BU aracı kullan — lakehouse_query ile "
        "yeni tablo kurma, çünkü kullanıcının baktığı tablo kaybolur. Satır sayısı değişmez."
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
            return ToolResult.error(
                f"'{params.column_name}' zaten tabloda var. Farklı bir ad seç."
            )

        try:
            result = self.lakehouse.execute_sql(params.sql)
        except LakehouseError as exc:
            return ToolResult.error(str(exc))

        df = result.data
        if df.empty:
            return ToolResult.error(
                "Sorgu hiç satır döndürmedi; eklenecek veri yok. Filtreleri kontrol et."
            )
        if len(df.columns) != 2:
            return ToolResult.error(
                f"Sorgu {len(df.columns)} kolon döndürdü, tam 2 olmalı "
                f"(eşleştirme anahtarı + değer). Dönen kolonlar: {', '.join(df.columns)}"
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
                f"Eşleşen satır bulunamadı: sorgunun '{key_col}' değerleri ile tablodaki "
                f"'{params.join_on}' değerleri örtüşmüyor. Dönem aralığını kontrol et."
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
        "SELECT yazma. Örn: 'konut_kredisi / (tufe / 100)' veya "
        "'100.0 * (toplam - LAG(toplam) OVER (ORDER BY donem)) / LAG(toplam) OVER (ORDER BY donem)'"
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
        "Mevcut analiz tablosundaki sütunlardan yeni bir sütun HESAPLAR ve tabloya ekler "
        "(enflasyondan arındırma, yüzde değişim, oran vb.). Tablo bozulmaz, satır sayısı "
        "değişmez. Hesabı sen yapma, formülü bu araca yazdır."
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

        con = duckdb.connect()
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
