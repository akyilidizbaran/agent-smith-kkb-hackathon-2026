"""`workspace_query` — aktif analiz tablosu üzerinde SQL; veri havuzuna dokunmaz.

Sohbet boyutunda kalan analiz: web'den ya da bir dosyadan yüklenen tablo veritabanına
yazılmadan filtrelenir, toplanır, sıralanır. Motor `workspace_compute_column` ile aynı
sertleştirilmiş bellek-içi DuckDB (dış erişim kapalı, tek SELECT, sözcük engel listesi);
tablo `t` adıyla kayıtlıdır, başka hiçbir ilişki yoktur. Varsayılan BAKIŞ modu: sonuç karta
yazılır, aktif tablo değişmez, sonuç kanıt paneli için not edilir (ölçüldü: filtre/özet
sorguları tabloyu ezince model 5 satırla ya da tek satırlık özetle kaldı). `as_active_table=true`
ile sonuç yeni aktif tablo olur, önceki tablo geçmişte kalır (`revert` ile geri gelir);
provenance "workspace_query: <sql>" ve kaynak kolonların provenance'ı taşınır — kanıt zinciri kopmaz.
"""

from __future__ import annotations

import re

import pandas as pd
from pydantic import BaseModel, Field

from ..adapters.duckdb_lakehouse import guard_sql, hardened_connection
from ..contracts.lakehouse import LakehouseError, QueryProvenance
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace

TABLE_ALIAS = "t"


class WorkspaceQueryParams(BaseModel):
    sql: str = Field(description="Aktif tablo üzerinde SELECT; tablonun adı `t`. Ör. SELECT * FROM t WHERE year >= 2000 ORDER BY year")
    purpose: str = Field(description="Bu sorgunun neyi yaptığını anlatan tek cümle (kullanıcıya gösterilir)")
    as_active_table: bool = Field(
        default=False,
        description="Sonuç, kullanıcının bundan sonra üzerinde çalışacağı TABLO mu olsun? Filtreleme/kırpma için true. "
                    "Bakış, özet, tek satırlık toplam ya da 'en yüksek hangisi' için false (aktif tablo korunur).",
    )


class WorkspaceQueryTool(Tool):
    name = "workspace_query"
    role = "execute"
    description = (
        "Aktif analiz tablosu üzerinde SQL çalıştırır (tablo adı `t`): satır filtreleme, sıralama, "
        "gruplayıp toplama, dönem kırpma. Veri havuzuna DOKUNMAZ; web'den ya da dosyadan yüklenen "
        "bir tabloyu kaydetmeden analiz etmek için kullan. Varsayılan bakış modu (tablo değişmez); "
        "as_active_table=true ile sonuç yeni aktif tablo olur, öncekisi geçmişte kalır."
    )
    Params = WorkspaceQueryParams

    def __init__(self, workspace: AnalysisWorkspace) -> None:
        self.workspace = workspace

    def validate_refs(self, params: WorkspaceQueryParams) -> ToolError | None:
        if not self.workspace.has_table:
            return ToolError(error_code="NO_ACTIVE_TABLE", layer="workspace",
                             message="Aktif tablo yok; önce veriyi getir (lakehouse_query, web_url, gold_*).")
        if not re.search(rf"\b(FROM|JOIN)\s+({TABLE_ALIAS}|k\d+)\b", params.sql, re.I):
            return ToolError(error_code="INVALID_ARGS", layer="schema",
                             message=f"Sorgu aktif tabloyu `{TABLE_ALIAS}` ya da oturum tablosunu `kN` adıyla okumalı (FROM {TABLE_ALIAS}).")
        known = {src.id for src in self.workspace.sources()}
        unknown = sorted(set(re.findall(r"\b(k\d+)\b", params.sql)) - known)
        if unknown:
            return ToolError(error_code="INVALID_ARGS", layer="reference", candidates=sorted(known),
                             message=f"Oturumda böyle tablo yok: {', '.join(unknown)}.")
        return None

    def run(self, params: WorkspaceQueryParams) -> ToolResult:
        table = self.workspace.table
        assert table is not None
        try:
            text = guard_sql(params.sql)
        except LakehouseError as exc:
            return ToolResult.fail("UNSAFE_SQL", str(exc), layer="policy", retryable=False)
        con = hardened_connection(None)
        try:
            con.register(TABLE_ALIAS, table)
            for src in self.workspace.sources():            # oturum tabloları (M11): k1, k2, …
                con.register(src.id, src.frame)
            out = con.execute(text).fetch_df()
        except Exception as exc:  # noqa: BLE001 — SQL hatası modele geri gider
            return ToolResult.fail("SQL_FAILED", f"Sorgu çalışmadı: {exc}", layer="data",
                                   hint="Kolon adlarını aktif tablodan (workspace_show) birebir al.")
        finally:
            con.close()
        if out.empty:
            return ToolResult(content="Sorgu çalıştı ama hiç satır dönmedi; filtre değerini kontrol et.", ok=True)

        from ..core.preview import preview_table, span_summary   # ≤24 satır tamamı, üstü baş+son (PART 41)

        span = span_summary(out)     # ilk → son farkı harness hesaplar (core/preview)
        if not params.as_active_table:
            # Bakış modu (ölçüldü: filtre/özet sorguları aktif tabloyu ezince model sonraki turda
            # yalnız 5 satırlık alt kümeyle ya da tek satırlık özetle kaldı ve yanlış dönem için
            # cevap verdi). Sonuç karta yazılır, tablo değişmez.
            content = (
                f"Sorgu başarılı: {len(out)} satır, {len(out.columns)} sütun — AKTİF TABLO DEĞİŞMEDİ (bakış modu; "
                f"tabloyu buna çevirmek için as_active_table=true).\n"
                f"Sütunlar: {', '.join(map(str, out.columns))}\n" + preview_table(out, where="bu sorgunun sonucunda")
                + ("\n" + span if span else "")
            )
            self.workspace.note_peek(text, out)
            return ToolResult(content=content, data=out)

        parents = [self.workspace.column_provenance(str(c)) for c in table.columns]
        sources: list[str] = []
        urls: list[str] = []
        for p in parents:
            if p is None:
                continue
            sources.extend(s for s in p.sources if s not in sources)
            urls.extend(u for u in p.source_urls if u not in urls)
        prov = QueryProvenance(sql=f"workspace_query: {text}", dataset_ids=[], sources=sources,
                               source_urls=urls, row_count=len(out),
                               warnings=[f"Türetildi: önceki aktif tablodan ({len(table)} satır) SQL ile; veri havuzuna yazılmadı."])
        self.workspace.set_table(out, description=params.purpose, provenance=prov)
        self.workspace.title = params.purpose
        content = (
            f"Sorgu başarılı: {len(out)} satır, {len(out.columns)} sütun — artık AKTİF TABLO bu (veri havuzuna yazılmadı).\n"
            f"Sütunlar: {', '.join(map(str, out.columns))}\n" + preview_table(out)
            + ("\n" + span if span else "")
        )
        return ToolResult(content=content, data=out, provenance=prov)


__all__ = ["WorkspaceQueryTool", "WorkspaceQueryParams"]
