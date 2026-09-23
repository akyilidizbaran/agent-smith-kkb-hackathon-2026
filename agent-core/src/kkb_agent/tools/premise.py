"""`check_premise` — sorunun varsaydığı yönü veriden doğrular (V3 §3.9; Büşra, 16 Eyl).

Neden var (ölçüldü, 14 Eyl UEB A09/A10, docs/calisma-notlari/HUMAN_ERROR_RESEARCH_2026-09-14.md PART 19/37): "2025'te konut
kredisi bakiyesi DÜŞTÜĞÜ için ihtiyaç kredileri arttı mı?" — konut 2025'te 512.259 → 678.970 ARTTI. Model iki
koşuda da öncülü düzeltti ama bu modele bağlıydı: harness'ta öncülü sınayan hiçbir şey yoktu; soru ön-koşulu
(core/question_preflight) yalnız "soru bir yön varsayıyor" der. Bu araç o yönü DETERMİNİSTİK sınar: serinin
dönemdeki ilk ve son gözlemi karşılaştırılır, karar üç değerlidir — DESTEKLİYOR / ÇELİŞİYOR / BİLİNMİYOR.
Çevrimdışı prova (`scripts/ueb_after_offline.py::premise_check`) A09/A10'da doğru kararı verdi, D kontrollerinde
hiç tetiklenmedi; oradaki alan sabitleri (kalem adları, tablo adı) buraya GİRMEDİ: seri, kolon ve kırılım
değerini model katalogdan seçer, araç yalnız yönü ölçer.

Tabloyu değiştirmez (workspace'e dokunmaz); kart sayıları taşır ki cevaptaki düzeltme grounding havuzunda
bulunsun. Aynı döneme birden çok satır düşüyorsa (kırılımsız çağrı) karar verilmez, model kırılımı seçer.
"""

from __future__ import annotations

import re

import pandas as pd
from pydantic import BaseModel, Field

from ..contracts.lakehouse import LakehouseClient, LakehouseError, QueryProvenance
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult

PREMISE_PROMPT_RULES = """

ÖNCÜL KURALI: Soru bir yön varsayıyorsa ("X düştüğü için", "X neden arttı", "X'teki düşüşün nedeni") cevap yazmadan \
ÖNCE check_premise ile o yönü veriden doğrula (seri, kırılım değeri, yıl, iddia edilen yön). Kart ÇELİŞİYOR derse \
cevabın İLK cümlesi düzeltmedir ("2025'te konut kredisi bakiyesi düşmedi, arttı: … → …") ve öncül üzerine kurulu \
'neden' anlatısı YAZMA. DESTEKLİYOR derse bunu tek cümleyle söyle ve sorunun kalanına geç. BİLİNMİYOR derse \
doğrulanamadığını söyle. Kartın sayıları dışında sayı üretme."""

_DOWN = re.compile(r"düş|dus|azal|geril|küçül|kucul|\bin(di|iş|is)\b|decreas|fell|fall|drop|declin|down", re.I)
_UP = re.compile(r"art|yüksel|yuksel|çık|cik|büyü|buyu|increas|rose|rise|grow|\bup\b", re.I)


def normalize_direction(text: str) -> str | None:
    """'düştü / azaldı / geriledi' → 'düştü'; 'arttı / yükseldi / büyüdü' → 'arttı'; anlaşılmazsa None."""
    t = (text or "").strip()
    if _DOWN.search(t):
        return "düştü"
    if _UP.search(t):
        return "arttı"
    return None


def _fmt(v: float) -> str:
    """Türkçe sayı: binlik '.', ondalık ','. Tam sayıya yakın büyük değerler ondalıksız."""
    if abs(v) >= 1000 and abs(v - round(v)) < 0.05:
        return f"{v:,.0f}".replace(",", ".")
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class CheckPremiseParams(BaseModel):
    dataset_id: str = Field(description="Öncülün dayandığı seri/tablo kimliği (katalogdan; lakehouse_search ile bulunmuş)")
    value_column: str = Field(description="Yönü ölçülecek sayısal ölçüm kolonu")
    claimed_direction: str = Field(description="Sorunun varsaydığı yön: 'arttı' ya da 'düştü' (azaldı/geriledi de olur)")
    subject: str = Field(description="Öncülün konusu, tek cümle Türkçe (ör. '2025'te konut kredisi bakiyesi düştü')")
    filter_column: str | None = Field(default=None, description="Kalem/kırılım kolonu (tek seri seçmek için); tablo tek seriyse boş")
    filter_value: str | None = Field(default=None, description="Kırılımın GERÇEK değeri (lakehouse_distinct_values ile bulunmuş); tahmin etme")
    year: int | None = Field(default=None, ge=1900, le=2100, description="Öncülün yılı: o yılın ilk ve son gözlemi karşılaştırılır")
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$", description="Yıl yerine dönem aralığı başlangıcı 'YYYY-MM'")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$", description="Dönem aralığı sonu 'YYYY-MM'")


class CheckPremiseTool(Tool):
    name = "check_premise"
    role = "validate"
    description = (
        "Sorunun varsaydığı yönü ('X düştüğü için', 'X neden arttı') VERİDEN doğrular: seçilen serinin dönemdeki ilk ve "
        "son gözlemini karşılaştırır ve DESTEKLİYOR / ÇELİŞİYOR / BİLİNMİYOR der; tepe ve dip dönemini de yazar. Aktif "
        "tabloyu değiştirmez. Öncül içeren soruda cevap yazmadan ÖNCE çağır; kırılım değerini distinct_values'tan al."
    )
    Params = CheckPremiseParams

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse

    # ------------------------------------------------------------ doğrulama
    def validate_refs(self, params: CheckPremiseParams) -> ToolError | None:
        try:
            spec = self.lakehouse.get_dataset(params.dataset_id)
        except LakehouseError as exc:
            return ToolError(error_code="DATASET_NOT_FOUND", layer="reference", message=str(exc),
                             hint="lakehouse_search ile doğru seri kimliğini bul.")
        cols = [c.name for c in getattr(spec, "columns", []) or []]
        measures = [c.name for c in getattr(spec, "columns", []) or [] if str(getattr(getattr(c, "role", None), "value", "")) == "measure"]
        if cols and params.value_column not in cols:
            return ToolError(error_code="COLUMN_NOT_FOUND", layer="reference", candidates=measures or cols,
                             message=f"'{params.value_column}' {params.dataset_id} tablosunda yok.")
        if params.filter_column and cols and params.filter_column not in cols:
            return ToolError(error_code="COLUMN_NOT_FOUND", layer="reference", candidates=cols,
                             message=f"'{params.filter_column}' {params.dataset_id} tablosunda yok.")
        if params.filter_column and params.filter_value is None:
            return ToolError(error_code="INVALID_ARGS", layer="schema",
                             message="filter_column verildi ama filter_value boş; kırılımın gerçek değerini ver.")
        if normalize_direction(params.claimed_direction) is None:
            return ToolError(error_code="INVALID_ARGS", layer="schema", candidates=["arttı", "düştü"],
                             message=f"claimed_direction anlaşılmadı: {params.claimed_direction!r}.")
        if (params.start is None) != (params.end is None):
            return ToolError(error_code="INVALID_ARGS", layer="schema", message="start ve end birlikte verilir ('YYYY-MM').")
        return None

    # ------------------------------------------------------------ ölçüm
    def run(self, params: CheckPremiseParams) -> ToolResult:
        spec = self.lakehouse.get_dataset(params.dataset_id)
        key = str(getattr(spec, "time_column", "") or "")
        try:
            sql = self.lakehouse.series_sql(params.dataset_id, key_column=key, value_column=params.value_column,
                                            filter_column=params.filter_column, filter_value=params.filter_value)
            result = self.lakehouse.execute_sql(sql)
        except LakehouseError as exc:
            return ToolResult.fail("SQL_FAILED", str(exc), layer="data")
        df = result.data
        claimed = normalize_direction(params.claimed_direction) or params.claimed_direction
        scope = (f"{params.year}" if params.year else (f"{params.start}→{params.end}" if params.start else "tüm kapsam"))
        who = f"{params.dataset_id}" + (f" [{params.filter_column}={params.filter_value}]" if params.filter_column else "")
        prov = QueryProvenance(sql=sql, dataset_ids=[params.dataset_id], sources=list(getattr(result.provenance, "sources", []) or []),
                               source_urls=list(getattr(result.provenance, "source_urls", []) or []), row_count=0)
        if df is None or df.empty:
            return self._unknown(params, claimed, who, scope, "seri boş döndü (kırılım değeri yanlış olabilir)", prov)
        kcol, vcol = df.columns[0], df.columns[1] if len(df.columns) > 1 else df.columns[0]
        frame = pd.DataFrame({"donem": pd.to_datetime(df[kcol], errors="coerce"),
                              "deger": pd.to_numeric(df[vcol], errors="coerce")}).dropna().sort_values("donem")
        if params.year:
            frame = frame[frame["donem"].dt.year == params.year]
        elif params.start:
            lo = pd.Timestamp(params.start + "-01")
            hi = pd.Timestamp(params.end + "-01") + pd.offsets.MonthEnd(1)
            frame = frame[(frame["donem"] >= lo) & (frame["donem"] <= hi)]
        if frame["donem"].duplicated().any():
            return ToolResult.fail(
                "INVALID_ARGS", f"{who}: aynı döneme birden çok satır düşüyor; yön tek seri üzerinde ölçülür.",
                hint="filter_column/filter_value ile tek kalemi seç (lakehouse_distinct_values ile gerçek değeri bul).",
                layer="data",
            )
        if len(frame) < 2:
            return self._unknown(params, claimed, who, scope, f"{scope} için {len(frame)} gözlem var, yön ölçülemez", prov)
        first, last = frame.iloc[0], frame.iloc[-1]
        f_v, l_v = float(first["deger"]), float(last["deger"])
        actual = "arttı" if l_v > f_v else ("düştü" if l_v < f_v else "değişmedi")
        verdict = "DESTEKLİYOR" if actual == claimed else "ÇELİŞİYOR"
        pct = ((l_v - f_v) / abs(f_v) * 100.0) if f_v else None
        peak, trough = frame.loc[frame["deger"].idxmax()], frame.loc[frame["deger"].idxmin()]
        prov.row_count = int(len(frame))
        lines = [
            f"ÖNCÜL [{verdict}]: '{params.subject}' — iddia: {claimed}; veri: {actual}.",
            f"Seri: {who} | dönem {scope} | {len(frame)} gözlem.",
            f"İlk gözlem {first['donem']:%Y-%m}: {_fmt(f_v)} → son gözlem {last['donem']:%Y-%m}: {_fmt(l_v)}"
            + (f" (değişim {'+' if pct >= 0 else ''}{_fmt(pct)}%)" if pct is not None else ""),
            f"Dönem içi tepe {peak['donem']:%Y-%m}: {_fmt(float(peak['deger']))} | dip {trough['donem']:%Y-%m}: {_fmt(float(trough['deger']))}.",
        ]
        if verdict == "ÇELİŞİYOR":
            lines.append("YAPACAĞIN: cevabın İLK cümlesi bu düzeltme olsun; öncül üzerine kurulu 'neden' anlatısı yazma. "
                         "Sorunun kalanını (varsa) veriyle cevapla; kartın dışında sayı üretme.")
        else:
            lines.append("YAPACAĞIN: öncülün veriyle uyuştuğunu tek cümleyle söyle; neden-sonuç iddiası kurma "
                         "(iki serinin birlikte hareketi nedensellik değildir).")
        art = {"verdict": verdict, "claimed": claimed, "actual": actual, "first": f_v, "last": l_v,
               "first_period": f"{first['donem']:%Y-%m}", "last_period": f"{last['donem']:%Y-%m}", "n": int(len(frame)),
               "dataset_id": params.dataset_id, "filter": params.filter_value, "scope": scope}
        return ToolResult(content="\n".join(lines), provenance=prov, artifacts={"premise": art})

    @staticmethod
    def _unknown(params: CheckPremiseParams, claimed: str, who: str, scope: str, why: str, prov: QueryProvenance) -> ToolResult:
        text = (f"ÖNCÜL [BİLİNMİYOR]: '{params.subject}' — iddia: {claimed}; doğrulanamadı: {why}.\n"
                f"Seri: {who} | dönem {scope}.\n"
                "YAPACAĞIN: öncülü doğrulayamadığını cevabın ilk cümlesinde söyle; öncülü doğru varsayarak anlatma.")
        return ToolResult(content=text, provenance=prov,
                          artifacts={"premise": {"verdict": "BİLİNMİYOR", "claimed": claimed, "why": why,
                                                 "dataset_id": params.dataset_id, "filter": params.filter_value, "scope": scope}})


__all__ = ["PREMISE_PROMPT_RULES", "CheckPremiseParams", "CheckPremiseTool", "normalize_direction"]
