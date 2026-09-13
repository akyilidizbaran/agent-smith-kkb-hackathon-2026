"""`workspace_join` — oturumdaki iki tabloyu anahtarla birleştirir (M11-T03, A09, ADR-0059).

Kural: birleştirme DURUM üzerinden denetlenir, model sonucu tahmin etmez.
- Anahtar verilmediyse ve iki tabloda tek ortak kolon yoksa araç sorar (netleştirme): ortak kolonları listeler.
- Sağ tabloda yinelenen anahtar satırı çoğaltır: reddedilir, yinelenen değerler gösterilir.
- Eşleşmeyen satırlar sayılır ve karta yazılır; `left` birleştirmede sol tablonun satır sayısı değişmez.
- Aynı adlı kolon sağ tablonun kimliğiyle soneklenir; her kolon kendi kaynağının provenance'ını taşır.
Veri havuzuna yazmaz; sonuç yeni aktif tablo olur, önceki tablolar oturumda kalır.
"""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace


class JoinParams(BaseModel):
    right: str = Field(description="Eklenecek oturum tablosunun kimliği (k1, k2, …)")
    left: str = Field(default="aktif", description="Sol tablo: 'aktif' ya da kN")
    left_key: str | None = Field(default=None, description="Sol tablodaki eşleştirme kolonu; boşsa tek ortak kolon kullanılır")
    right_key: str | None = Field(default=None, description="Sağ tablodaki eşleştirme kolonu; boşsa left_key ile aynı ad")
    how: Literal["left", "inner", "outer"] = Field(default="left", description="left: sol tablonun satırları korunur")
    columns: list[str] | None = Field(default=None, description="Sağ tablodan alınacak kolonlar; boşsa anahtar dışındakilerin hepsi")
    purpose: str = Field(description="Bu birleştirmenin neyi cevapladığını anlatan tek cümle")


def _norm_key(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s).dt.normalize()
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce").astype("float64")
    text = s.astype("string").str.strip()
    as_num = pd.to_numeric(text, errors="coerce")
    if text.notna().any() and as_num[text.notna()].notna().all():
        return as_num.astype("float64")
    as_date = pd.to_datetime(text, errors="coerce", format="mixed") if text.str.contains(r"\d{4}-\d{2}", na=False).all() else None
    if as_date is not None and as_date.notna().all():
        return as_date.dt.normalize()
    return text.str.casefold()


class WorkspaceJoinTool(Tool):
    name = "workspace_join"
    role = "execute"
    description = (
        "Oturumdaki iki tabloyu (aktif tablo ve kN) anahtar kolonla birleştirir; sonuç yeni aktif tablo olur. "
        "Yinelenen anahtar, eşleşmeyen satır ve kolon adı çakışması denetlenir ve karta yazılır. Anahtar belirsizse "
        "araç ortak kolonları listeler: kullanıcıya hangisiyle birleştirileceğini sor."
    )
    Params = JoinParams

    def __init__(self, workspace: AnalysisWorkspace) -> None:
        self.workspace = workspace

    def _keys(self, params: JoinParams, left, right) -> tuple[str, str] | ToolError:
        if params.left_key is None and params.right_key is None:
            common = [c for c in left.frame.columns if c in set(right.frame.columns)]
            if len(common) != 1:
                return ToolError(error_code="INVALID_ARGS", layer="reference", candidates=[str(c) for c in common],
                                 message=("Birleştirme anahtarı belirsiz: " + (f"ortak kolonlar {', '.join(map(str, common))}" if common else "ortak adlı kolon yok")
                                          + ". Kullanıcıya hangi kolonla birleştirileceğini sor."))
            return str(common[0]), str(common[0])
        lk = params.left_key or params.right_key
        rk = params.right_key or params.left_key
        assert lk is not None and rk is not None
        if lk not in left.frame.columns:
            return ToolError(error_code="COLUMN_NOT_FOUND", layer="reference", candidates=list(map(str, left.frame.columns)),
                             message=f"'{lk}' {left.id} tablosunda yok.")
        if rk not in right.frame.columns:
            return ToolError(error_code="COLUMN_NOT_FOUND", layer="reference", candidates=list(map(str, right.frame.columns)),
                             message=f"'{rk}' {right.id} tablosunda yok.")
        return lk, rk

    def validate_refs(self, params: JoinParams) -> ToolError | None:
        left, right = self.workspace.source(params.left), self.workspace.source(params.right)
        known = ["aktif", *[s.id for s in self.workspace.sources()]]
        if left is None or right is None:
            return ToolError(error_code="INVALID_ARGS", layer="reference", candidates=known,
                             message=f"Oturumda böyle tablo yok: {params.left if left is None else params.right}.")
        if params.left == params.right:
            return ToolError(error_code="INVALID_ARGS", layer="schema", message="Bir tablo kendisiyle birleştirilmez.")
        keys = self._keys(params, left, right)
        return keys if isinstance(keys, ToolError) else None

    def run(self, params: JoinParams) -> ToolResult:
        left, right = self.workspace.source(params.left), self.workspace.source(params.right)
        assert left is not None and right is not None
        keys = self._keys(params, left, right)
        if isinstance(keys, ToolError):
            return ToolResult(content=keys.message, ok=False, error=keys)
        lk, rk = keys
        lf, rf = left.frame.copy(), right.frame.copy()
        lf["__k"], rf["__k"] = _norm_key(lf[lk]), _norm_key(rf[rk])
        dup_right = rf["__k"][rf["__k"].duplicated(keep=False)]
        if len(dup_right):
            examples = ", ".join(map(str, list(dict.fromkeys(rf.loc[dup_right.index, rk].tolist()))[:5]))
            return ToolResult.fail("JOIN_MISMATCH",
                                   f"{right.id} tablosunda '{rk}' yinelenen değerler taşıyor ({dup_right.nunique()} değer, {len(dup_right)} satır; ör. {examples}): "
                                   "birleştirme satırları çoğaltır.",
                                   hint="Önce workspace_query ile tekilleştir (GROUP BY) ya da kullanıcıya hangi satırın alınacağını sor.",
                                   layer="data", retryable=False)
        dup_left = int(lf["__k"].duplicated().sum())
        take = params.columns or [c for c in rf.columns if c not in (rk, "__k")]
        missing = [c for c in take if c not in rf.columns]
        if missing:
            return ToolResult.fail("COLUMN_NOT_FOUND", f"{right.id} tablosunda yok: {', '.join(map(str, missing))}.",
                                   candidates=list(map(str, right.frame.columns)), layer="reference")
        renamed: dict[str, str] = {}
        for c in take:
            if c in lf.columns:
                renamed[c] = f"{c}_{right.id}"
        rsel = rf[["__k", *take]].rename(columns=renamed)
        merged = lf.merge(rsel, on="__k", how=params.how, indicator=True)
        both = int((merged["_merge"] == "both").sum())
        right_only = int((merged["_merge"] == "right_only").sum())
        # Eşleşmeyen satırlar birleştirme türünden bağımsız sayılır: left'te sağın kaybolan satırları da görünür (A09).
        left_only = int((~lf["__k"].isin(rf["__k"])).sum())
        right_unmatched = int((~rf["__k"].isin(lf["__k"])).sum())
        if params.how == "outer" and right_only:
            merged[lk] = merged[lk].where(merged[lk].notna(), rf.set_index("__k")[rk].reindex(merged["__k"]).to_numpy())
        merged = merged.drop(columns=["__k", "_merge"]).reset_index(drop=True)
        if both == 0:
            return ToolResult.fail("JOIN_MISMATCH", f"'{lk}' ile '{rk}' değerleri hiç eşleşmedi (biçim farkı olabilir).",
                                   hint="İki kolonun örnek değerlerini workspace_query ile karşılaştır.", layer="data")
        col_prov = dict(left.provenance)
        for c in take:
            if c in right.provenance:
                col_prov[renamed.get(c, c)] = right.provenance[c]
        sid = self.workspace.set_table(merged, description=params.purpose, column_provenance=col_prov)
        self.workspace.title = params.purpose
        notes = []
        if left_only:
            notes.append(f"{left_only} {left.id} satırı {right.id} içinde eşleşmedi" + (" (değerleri boş)" if params.how == "left" else ""))
        if right_unmatched:
            notes.append(f"{right_unmatched} {right.id} satırı {left.id} içinde eşleşmedi"
                         + (" (sonuç tablosuna girmedi)" if params.how in ("left", "inner") else ""))
        if dup_left:
            notes.append(f"{left.id} tablosunda '{lk}' {dup_left} kez yineleniyor: aynı sağ değer her birine yazıldı (çoktan-bire)")
        if renamed:
            notes.append("ad çakışması: " + ", ".join(f"{a} → {b}" for a, b in renamed.items()))
        card = [
            f"BİRLEŞTİRME: {left.id} ⟕ {right.id} · anahtar {lk} = {rk} · {params.how} · sonuç {sid}: {len(merged)} satır, {len(merged.columns)} kolon",
            f"Eşleşen {both} · yalnız solda {left_only} · yalnız sağda {right_unmatched}",
            *notes,
            "Eklenen kolonlar: " + ", ".join(renamed.get(c, c) for c in take),
            "İlk 5 satır:\n" + merged.head(5).to_string(index=False),
        ]
        return ToolResult(content="\n".join(card), data=merged)


__all__ = ["JoinParams", "WorkspaceJoinTool"]
