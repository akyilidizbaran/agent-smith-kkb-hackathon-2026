"""Analitik araçlar — aktif tablo üzerinde deterministik tespit; model yalnız anlatır (ADR-0040).

Yarışmanın asgari araç listesindeki üç ad: Anomali, Change Detection, Causality. Üçü de
`AnalysisWorkspace.table` üzerinde çalışır, hangi veri olduğu umurlarında değildir, LLM yoktur.
Sonuç tabloya sütun olarak eklenir (satır sayısı değişmez, provenance "türetilmiş: …") ya da
karta yazılır ve kanıt paneli için not edilir. Model kartı anlatır, sayı üretmez.

"Causality" adını dürüst kullanıyoruz: `lead_lag` gecikmeli korelasyon ve Granger öncüllük
testidir; kart "öncülük, nedensellik değil" der ve anlatı guard'ı (`causal_language`) modelin
"neden oldu" yazmasını yine geri çevirir.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from ..analytics.methods import detect_anomalies, detect_change_points, lead_lag
from ..contracts.lakehouse import QueryProvenance
from ..core.errors import ToolError
from ..core.evidence import _time_column as time_column
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace

ANALYTICS_PROMPT_RULES = """

ANALİTİK KURALI:
"olağandışı / aykırı / anomali / sıra dışı dönem" → anomaly_detect; "kırılma / rejim değişimi / \
büyüme ne zaman değişti" → change_points; "öncülük ediyor mu / önden mi izliyor / korelasyon / \
Granger" → lead_lag. Önce veriyi aktif tabloya getir (iki seri için ikincisini workspace_add_column \
ile aynı tabloya ekle), sonra aracı çağır. Bu araçlar çalışmadan aykırılık, kırılma ya da öncülük \
iddiası yazma; sayıları aracın kartından aynen aktar. lead_lag nedensellik kanıtı değildir: \
"öncülük ediyor / birlikte hareket ediyor" de, "neden oldu" deme. Aykırılığın sebebini uydurma; \
veride sebep yoktur."""

MIN_POINTS = 8
_BASIS_TEXT = {"level": "düzey", "change": "dönemlik yüzde değişim"}


def _labels(table: pd.DataFrame) -> tuple[str | None, list[str]]:
    tcol = time_column(table)
    if tcol is None:
        return None, [str(i) for i in table.index]
    return tcol, [str(v)[:10] for v in table[tcol]]


def _fmt(v: float, nd: int = 2) -> str:
    return "—" if v is None or v != v else f"{v:.{nd}f}"


class _AnalyticsTool(Tool):
    role = "execute"

    def __init__(self, workspace: AnalysisWorkspace) -> None:
        self.workspace = workspace

    def _numeric(self, column: str) -> ToolError | None:
        if not self.workspace.has_table:
            return ToolError(error_code="NO_ACTIVE_TABLE", layer="workspace",
                             message="Aktif tablo yok; önce veriyi getir (lakehouse_query, gold_*, web_url).")
        table = self.workspace.table
        assert table is not None
        numeric = [str(c) for c in table.columns if pd.api.types.is_numeric_dtype(table[c])]
        if column not in table.columns:
            return ToolError(error_code="COLUMN_NOT_FOUND", layer="reference", candidates=numeric,
                             message=f"'{column}' aktif tabloda yok.", hint="Kolon adını aktif tablodan birebir al.")
        if column not in numeric:
            return ToolError(error_code="INVALID_ARGS", layer="schema", candidates=numeric,
                             message=f"'{column}' sayısal değil.")
        if int(table[column].notna().sum()) < MIN_POINTS:
            return ToolError(error_code="INVALID_ARGS", layer="data", retryable=False,
                             message=f"'{column}' için en az {MIN_POINTS} gözlem gerekir; {int(table[column].notna().sum())} var.")
        return None


# ----------------------------------------------------------------------------- anomaly_detect
class AnomalyParams(BaseModel):
    column: str = Field(description="Aykırılık aranacak SAYISAL sütun; aktif tablodaki adıyla birebir")
    method: Literal["iqr", "zscore"] = Field(default="iqr", description="iqr: Tukey çiti (k=1.5); zscore: |z|>3")
    basis: Literal["auto", "level", "change"] = Field(
        default="auto",
        description="auto: seri trendliyse dönemlik yüzde değişim, değilse düzey üzerinde çalışır; "
                    "level/change ile zorlanır",
    )
    purpose: str = Field(description="Tek cümle: kullanıcı neyi sordu")


class AnomalyDetectTool(_AnalyticsTool):
    name = "anomaly_detect"
    description = (
        "Aktif tablodaki bir sayısal sütunda olağandışı (aykırı) gözlemleri deterministik olarak bulur: "
        "IQR ya da z-skoru; trendli seride (bakiye, endeks) dönemlik yüzde değişim üzerinde. Tabloya "
        "<sütun>_anomali ('ok'/'aykırı') ve <sütun>_skor sütunlarını ekler, satır sayısı değişmez. "
        "Kullanıcı olağandışı, aykırı, anomali, sıra dışı dönem sorduğunda veriyi getirdikten SONRA çağır."
    )
    Params = AnomalyParams

    def validate_refs(self, params: AnomalyParams) -> ToolError | None:
        return self._numeric(params.column)

    def run(self, params: AnomalyParams) -> ToolResult:
        table = self.workspace.table
        assert table is not None
        col = params.column
        res = detect_anomalies(table[col].to_numpy(dtype=float), method=params.method, basis=params.basis)
        tcol, labels = _labels(table)
        flag_col, score_col = f"{col}_anomali", f"{col}_skor"
        desc = f"anomali({res.method}, {res.basis}, k={res.threshold:g}) {col}"
        prov = QueryProvenance(sql=f"türetilmiş: {desc}", dataset_ids=[],
                               sources=[f"türetilmiş sütun — {desc}"])
        if res.basis == "change" and f"{col}_degisim_yuzde" not in table.columns:
            self.workspace.add_column(f"{col}_degisim_yuzde", pd.Series(np.round(res.analysed, 4), index=table.index),
                                      description=f"{col} dönemlik yüzde değişim (aykırılık tabanı)",
                                      provenance=QueryProvenance(sql=f"türetilmiş: yüzde_değişim({col})", dataset_ids=[],
                                                                 sources=[f"türetilmiş sütun — yüzde_değişim({col})"]))
        self.workspace.add_column(flag_col, pd.Series(np.where(res.flags, "aykırı", "ok"), index=table.index),
                                  description=f"{params.purpose} [{desc}]", provenance=prov)
        self.workspace.add_column(score_col, pd.Series(np.round(res.scores, 3), index=table.index),
                                  description=f"{col} aykırılık skoru ({'z' if res.method.startswith('zscore') else 'IQR birimi'})",
                                  provenance=prov)
        updated = self.workspace.table
        assert updated is not None

        idx = np.where(res.flags)[0]
        rows = pd.DataFrame({
            "dönem": [labels[i] for i in idx],
            col: [float(table[col].iloc[i]) for i in idx],
            **({"degisim_yuzde": [round(float(res.analysed[i]), 2) for i in idx]} if res.basis == "change" else {}),
            "skor": [round(float(res.scores[i]), 2) for i in idx],
        })
        if len(rows):
            rows = rows.reindex(rows["skor"].abs().sort_values(ascending=False).index)
            self.workspace.note_peek(f"anomaly_detect({col})", rows)
        # Kart parametreleri de sayıdır (ölçüldü: model k=1.5 ve n=66'yı yazdı, panel "tabloda yok" dedi).
        self.workspace.note_peek(f"anomaly_detect({col}) parametreler", pd.DataFrame({
            "k": [res.threshold], "n": [int(np.sum(~np.isnan(res.analysed)))], "aykiri": [res.count],
            "alt_sinir": [round(float(res.lower), 2)], "ust_sinir": [round(float(res.upper), 2)],
            "trend_rho": [round(float(res.trend_rho), 2)]}))
        unit = "%" if res.basis == "change" else ""
        card = [
            f"AYKIRILIK: {col} — yöntem {res.method} (k={res.threshold:g}) | taban: {_BASIS_TEXT[res.basis]} "
            f"(trend rho={res.trend_rho:.2f}) | normal aralık: [{_fmt(res.lower)}{unit}, {_fmt(res.upper)}{unit}] | "
            f"n={int(np.sum(~np.isnan(res.analysed)))} | aykırı: {res.count}",
            f"Tabloya eklendi: {flag_col}, {score_col}" + (f", {col}_degisim_yuzde" if res.basis == "change" else "")
            + f"; tablo bozulmadı ({len(updated)} satır).",
        ]
        if len(rows):
            card.append("Aykırı dönemler (skora göre):\n" + rows.head(12).to_string(index=False))
        else:
            card.append("Aykırı gözlem yok: hiçbir değer normal aralığın dışına çıkmıyor.")
        card.append("YAPACAĞIN: aykırı dönemleri ve sayıları bu karttan aktar; sebep uydurma, veride sebep yok. "
                    "ARAÇ ÇAĞIRMAYI BIRAK, cevabını yaz.")
        return ToolResult(content="\n".join(card), data=updated)


# ----------------------------------------------------------------------------- change_points
class ChangePointsParams(BaseModel):
    column: str = Field(description="Kırılma aranacak SAYISAL sütun; aktif tablodaki adıyla birebir")
    basis: Literal["auto", "level", "change"] = Field(
        default="auto", description="auto: trendli seride büyüme hızının (yüzde değişim) rejimleri, değilse düzey")
    max_breaks: int = Field(default=3, ge=1, le=6, description="En çok kaç kırılma")
    min_size: int = Field(default=4, ge=2, le=24, description="Bir rejimin en az kaç gözlem sürmesi gerekir")
    purpose: str = Field(description="Tek cümle: kullanıcı neyi sordu")


class ChangePointsTool(_AnalyticsTool):
    name = "change_points"
    description = (
        "Aktif tablodaki bir sayısal sütunda rejim değişimlerini (kırılma noktalarını) deterministik "
        "olarak bulur: ikili bölütleme, parçalı sabit ortalama, log(n) cezası. Trendli seride büyüme "
        "hızının ne zaman değiştiğini bulur. Tabloya <sütun>_rejim sütununu ekler (1, 2, …), satır "
        "sayısı değişmez. Kullanıcı kırılma, rejim değişimi, 'ne zaman değişti' sorduğunda çağır."
    )
    Params = ChangePointsParams

    def validate_refs(self, params: ChangePointsParams) -> ToolError | None:
        return self._numeric(params.column)

    def run(self, params: ChangePointsParams) -> ToolResult:
        table = self.workspace.table
        assert table is not None
        col = params.column
        res = detect_change_points(table[col].to_numpy(dtype=float), basis=params.basis,
                                   min_size=params.min_size, max_breaks=params.max_breaks)
        tcol, labels = _labels(table)
        regime = np.zeros(len(table), dtype=int)
        for j, seg in enumerate(res.segments, start=1):
            regime[seg.start:seg.end + 1] = j
        desc = f"kırılma(ikili bölütleme, {res.basis}, min={params.min_size}, max={params.max_breaks}) {col}"
        self.workspace.add_column(f"{col}_rejim", pd.Series(regime, index=table.index),
                                  description=f"{params.purpose} [{desc}]",
                                  provenance=QueryProvenance(sql=f"türetilmiş: {desc}", dataset_ids=[],
                                                             sources=[f"türetilmiş sütun — {desc}"]))
        updated = self.workspace.table
        assert updated is not None
        unit = "%" if res.basis == "change" else ""
        segs = pd.DataFrame({
            "rejim": list(range(1, len(res.segments) + 1)),
            "baslangic": [labels[s.start] for s in res.segments],
            "bitis": [labels[s.end] for s in res.segments],
            "gozlem": [s.n for s in res.segments],
            ("ortalama_degisim_yuzde" if res.basis == "change" else "ortalama"): [round(s.mean, 2) for s in res.segments],
        })
        self.workspace.note_peek(f"change_points({col})", segs)
        self.workspace.note_peek(f"change_points({col}) parametreler", pd.DataFrame({
            "n": [int(np.sum(~np.isnan(res.analysed)))], "kirilma": [len(res.breaks)],
            "min_size": [params.min_size], "max_breaks": [params.max_breaks], "trend_rho": [round(float(res.trend_rho), 2)]}))
        card = [
            f"KIRILMA: {col} — ikili bölütleme | taban: {_BASIS_TEXT[res.basis]} (trend rho={res.trend_rho:.2f}) | "
            f"n={int(np.sum(~np.isnan(res.analysed)))} | kırılma: {len(res.breaks)}",
            f"Tabloya eklendi: {col}_rejim; tablo bozulmadı ({len(updated)} satır).",
        ]
        if res.breaks:
            for k, b in enumerate(res.breaks):
                before, after = res.segments[k], res.segments[k + 1]
                card.append(f"kırılma {k + 1}: {labels[b]} — önceki rejim ortalaması {_fmt(before.mean)}{unit} "
                            f"({before.n} gözlem) → sonraki {_fmt(after.mean)}{unit} ({after.n} gözlem)")
            card.append("Rejimler:\n" + segs.to_string(index=False))
        else:
            card.append("Kırılma yok: tek rejim, ortalama " + _fmt(res.segments[0].mean if res.segments else float("nan")) + unit)
        card.append("YAPACAĞIN: kırılma tarihlerini ve rejim ortalamalarını bu karttan aktar; sebep uydurma. "
                    "ARAÇ ÇAĞIRMAYI BIRAK, cevabını yaz.")
        return ToolResult(content="\n".join(card), data=updated)


# ----------------------------------------------------------------------------- lead_lag
class LeadLagParams(BaseModel):
    column_a: str = Field(description="Öncü olduğu sınanacak SAYISAL sütun (A)")
    column_b: str = Field(description="Ardıl olduğu sınanacak SAYISAL sütun (B)")
    max_lag: int = Field(default=6, ge=1, le=24, description="Sınanacak en büyük gecikme (dönem)")
    basis: Literal["auto", "level", "change"] = Field(
        default="auto", description="auto: iki seriden biri trendliyse yüzde değişim, değilse düzey")
    purpose: str = Field(description="Tek cümle: kullanıcı neyi sordu")


class LeadLagTool(_AnalyticsTool):
    name = "lead_lag"
    description = (
        "Aktif tablodaki iki sayısal sütun arasında öncül-ardıl ilişkisini deterministik olarak sınar: "
        "gecikmeli korelasyon (-max_lag..+max_lag) ve iki yönlü Granger öncüllük F-testi. Nedensellik "
        "kanıtı DEĞİLDİR; 'A, B'den k dönem önce hareket ediyor' düzeyinde konuşur. İki seri aynı "
        "tabloda olmalı (ikincisini workspace_add_column ile ekle). Kullanıcı 'öncülük ediyor mu', "
        "'önden mi izliyor', 'korelasyon', 'Granger' sorduğunda çağır."
    )
    Params = LeadLagParams

    def validate_refs(self, params: LeadLagParams) -> ToolError | None:
        if params.column_a == params.column_b:
            return ToolError(error_code="INVALID_ARGS", layer="schema", message="İki farklı sütun gerekir.")
        return self._numeric(params.column_a) or self._numeric(params.column_b)

    def run(self, params: LeadLagParams) -> ToolResult:
        table = self.workspace.table
        assert table is not None
        a, b = params.column_a, params.column_b
        res = lead_lag(table[a].to_numpy(dtype=float), table[b].to_numpy(dtype=float),
                       max_lag=params.max_lag, basis=params.basis)
        # r iki ondalık: model kartı olduğu gibi kopyalar, kanıt paneli birebir bulur (ölçüldü: 0.263 → "yok").
        lag_df = pd.DataFrame({"gecikme": res.lags, "r": [round(r, 2) if r == r else float("nan") for r in res.correlations]})
        self.workspace.note_peek(f"lead_lag({a},{b})", lag_df)
        if res.best_r != res.best_r or res.n < MIN_POINTS:
            return ToolResult.fail("INVALID_ARGS", f"İki sütunun ortak (boş olmayan) gözlemi yetersiz: n={res.n}.",
                                   hint="Dönem aralığını genişlet ya da iki seriyi aynı dönemlere hizala.",
                                   layer="data", retryable=False)
        k = res.best_lag
        if k > 0:
            lead_text = f"{a}, {b}'den {k} dönem ÖNCE hareket ediyor (A öncü)"
        elif k < 0:
            lead_text = f"{b}, {a}'dan {-k} dönem ÖNCE hareket ediyor (B öncü)"
        else:
            lead_text = "aynı dönemde birlikte hareket ediyorlar (gecikme 0)"
        strength = "güçlü" if abs(res.best_r) >= 0.7 else "orta" if abs(res.best_r) >= 0.4 else "zayıf"
        # p üç ondalık: model kartı olduğu gibi kopyalar (ölçüldü: 0.0027 → model "0,003" yazdı, panel bulamadı).
        g_rows = [{"yön": g.direction.replace("A", a).replace("B", b), "gecikme": g.lag, "F": round(g.f_stat, 2),
                   "p": round(g.p_value, 3), "n": g.n_used} for g in res.granger]
        g_df = pd.DataFrame(g_rows) if g_rows else pd.DataFrame()
        if len(g_df):
            self.workspace.note_peek(f"granger({a},{b})", g_df)
        self.workspace.note_peek(f"lead_lag({a},{b}) parametreler", pd.DataFrame({
            "n": [res.n], "en_guclu_gecikme": [k], "r": [round(res.best_r, 2)], "max_lag": [params.max_lag],
            "p_esik": [0.05]}))   # "p < 0,05" anlamlılık eşiği de kartın sayısıdır (ölçüldü, G17)
        card = [
            f"ÖNCÜL-ARDIL: A={a}, B={b} — taban: {_BASIS_TEXT[res.basis]} | n={res.n} ortak gözlem "
            f"({len(table)} satır) | gecikme aralığı ±{params.max_lag}",
            f"En güçlü ilişki: gecikme {k:+d}, r={res.best_r:.2f} ({strength}); {lead_text}.",
            "Gecikme tablosu (pozitif: A önce):\n" + lag_df.to_string(index=False),
        ]
        if len(g_df):
            card.append("Granger öncüllük testi (p<0,05: öncülük istatistiksel olarak anlamlı):\n" + g_df.to_string(index=False))
        else:
            card.append("Granger testi: yeterli gözlem yok.")
        card.append("Bu bir öncülük/eşzamanlılık ölçüsüdür, NEDENSELLİK DEĞİLDİR. YAPACAĞIN: 'öncülük ediyor / "
                    "önden hareket ediyor / birlikte hareket ediyor' de; cevabında 'neden', 'yol aç', 'sebep', "
                    "'etkisiyle' sözcüklerini HİÇ kullanma (olumsuz cümlede bile); gecikme, r, p ve n değerlerini "
                    "karttan aktar. ARAÇ ÇAĞIRMAYI BIRAK, cevabını yaz.")
        return ToolResult(content="\n".join(card))


__all__ = ["ANALYTICS_PROMPT_RULES", "AnomalyDetectTool", "ChangePointsTool", "LeadLagTool"]
