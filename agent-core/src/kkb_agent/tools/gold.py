"""Gold araçları — frekans dönüşümü SQL'de değil, katalog kurallı fonksiyonda (ADR-0031).

"Çeyreklik göster", "aylığa indir", "iki seriyi aynı dönemde karşılaştır", "kümülatifi
çöz" — bunların hepsi bir toplama/ortalama kararı gerektirir ve o karar modelin değil
kataloğun: stok → dönemin son gözlemi, akım → toplam, oran → katalogdaki kural. Model
SQL'de `AVG(value)` yazdığında stoku ortalar; burada yazamaz. Veri ekibinin Gold
fonksiyonu ya sonucu verir ya da SEBEBİYLE reddeder; red kullanıcıya iletilir, sayı
uydurulmaz.

Üç araç aynı gövdeyi paylaşır: referans kontrolü (seri var mı, yüklenmiş mi) sınır
doğrulayıcıda; çağrı adaptörde (`GoldCapable`); sonuç aktif analiz tablosu olur.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from ..contracts.lakehouse import GoldCapable, GoldRefused, LakehouseError, QueryResult
from ..core.errors import ToolError
from ..core.period_intent import parse_period_intent
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace
from .lakehouse import _dataset_missing

REASON_TR: dict[str, str] = {
    "NOT_DECOMPOSABLE": "Bu seri birikimli değil; çözülecek bir kümülatif yok. Değerler zaten "
                        "kendi dönemlerinin değerleridir (stok seride dönem sonu bakiyesi).",
    "DECOMPOSITION_REQUIRED": "Bu seri birikimli (yıl başından/kuruluştan itibaren toplam); "
                              "dönem toplamları alınmaz, önce gold_decompose ile akımlara çözülmeli.",
    "UPSAMPLING_REFUSED": "Kaynak serinin frekansı hedeften daha kaba; kaynağın yayımlamadığı "
                          "gözlem uydurulmaz.",
    "UNSUPPORTED_TARGET_FREQUENCY": "Hedef dönem yalnız aylık ya da çeyreklik olabilir.",
    "UNSUPPORTED_SOURCE_FREQUENCY": "Kaynak frekansı bu dönüşüm için tanımlı değil "
                                    "(haftalık/günlük birikimli seri çözülmez: tatil haftası "
                                    "kayması ile boşluk ayırt edilemez).",
    "UNVERIFIED_SEMANTICS": "Serinin anlamı (ölçüm tipi/birim) katalogda doğrulanmamış; otomatik "
                            "dönüşüm yapılmaz. Kullanıcı 'doğrulanmamış olsa da kullan' derse aynı çağrı "
                            "onayla yapılır; yoksa ham gözlemler lakehouse_query ile gösterilir.",
    "INACTIVE_SERIES": "Seri taslak ya da kullanımdan kaldırılmış; Gold hesapları yalnız onaylı "
                       "seriye uygulanır. Taslak seri ham hâliyle lakehouse_query ile gösterilebilir.",
    "UNSUPPORTED_MEASURE_TYPE": "Bu ölçüm tipi (oran/adet/bilinmeyen) için güvenli bir birleştirme "
                                "kuralı yok; oran pay ve paydadan yeniden hesaplanmalı.",
    "MISSING_AGGREGATION_RULE": "Katalog bu seri için frekans indirgeme kuralı vermemiş; kural uydurulmaz.",
    "UNSUPPORTED_AGGREGATION_RULE": "Katalogdaki kural bu ölçüm tipi için anlamsız (ör. oranı toplamak).",
    "AMBIGUOUS_VINTAGE": "Aynı dönem için birden çok okuma (revizyon) var; hangisinin geçerli "
                         "olduğuna dair bir politika yok.",
    "NO_OBSERVATIONS": "Seri katalogda var ama Silver'da gözlemi yok; veri henüz çekilmemiş.",
    "PERIOD_GRAIN_CONFLICT": "Aynı frekansta bir döneme birden çok gözlem düşüyor; ortalama alınmaz.",
    "MISSING_CUMULATIVE_RESET": "Yıl başından birikimli seride sıfırlama sınırı tanımlı değil.",
    "SERIES_NOT_CATALOGUED": "Seri katalogda yok; kural yok.",
    "INVALID_ARGUMENT": "Çağrı argümanı geçersiz.",
}

_ALTERNATIVE_TR: dict[str, str] = {
    "NOT_DECOMPOSABLE": "Kullanıcı dönem değerleri istiyorsa gold_align ile istenen döneme indirge.",
    "DECOMPOSITION_REQUIRED": "Önce gold_decompose çağır; sonucu olduğu gibi göster.",
    "UNVERIFIED_SEMANTICS": "Kullanıcıya sor: 'doğrulanmamış olsa da kullanayım mı?'; onay verirse aynı aracı yeniden çağır.",
    "INACTIVE_SERIES": "Ham gözlemleri lakehouse_query ile göster ve taslak olduğunu söyle.",
    "UPSAMPLING_REFUSED": "Kaynağın kendi frekansında göster.",
}

GOLD_PROMPT_RULES = """

FREKANS DÖNÜŞÜMÜ KURALI (Gold):
"Çeyreklik göster", "aylığa indir", "yıllık ortalama", "iki seriyi aynı dönemde karşılaştır", \
"kümülatifi çöz / akıma çevir" gibi isteklerde SQL ile toplama/ortalama YAPMA — stoku ortalamak, \
oranı toplamak yanlış sayı üretir. Bunun için:
  - Tek seriyi aylık/çeyrekliğe indirmek: gold_align
  - Birden çok seriyi aynı dönem ekseninde yan yana koymak: gold_join
  - Yıl başından/kuruluştan birikimli seriyi dönem akımlarına çözmek: gold_decompose
Kural (son değer / toplam / ortalama) katalogdan gelir, sen seçemezsin. Araç reddederse \
sebebini kullanıcıya sade Türkçeyle söyle; sayı üretme, SQL ile aynı işi yapmaya kalkma.
Hazır Gold tabloları (kimliği gold. ile başlar) lakehouse_search'te görünür; onlar zaten \
hesaplanmıştır, lakehouse_query ile doğrudan sorgulanır.
Kullanıcıya bu tabloları "Gold" diye anma ve kimliklerini yazma: "hesaplanmış tablo" de ve hangi kaynağın verisinden, \
hangi kuralla (ör. haftalıktan aylık ortalama) hesaplandığını söyle."""

# Hesapta kullanma rızası; kalıcı yayın onayı ("onaylıyorum", "kataloğa al") bu rızayı VERMEZ (D03-T06, ADR-0068).
_CONSENT = re.compile(
    r"(doğrulanmamış\s+olsa\s+da|dogrulanmamis\s+olsa\s+da|yine\s+de\s+kullan|riski\s+kabul)", re.I,
)


def unverified_consent(user_text: str) -> bool:
    """Sözleşme: doğrulanmamış semantiği kullanma kararı insanındır, agent aktarır (ADR-0031).
    Kullanıcı metninde açık rıza yoksa bayrak açılmaz."""
    return bool(_CONSENT.search(user_text or ""))


_DROP_FROM_WORKSPACE = frozenset({
    "vintage_id_list", "run_id_list", "source_frequency", "target_frequency",
    "aggregation", "measure_type", "unit", "warned_observations", "series_id",
})
_HIDE_IN_PREVIEW_SUFFIXES = ("artifact_sha256_list", "source_observation_dates",
                             "contributing_series", "absent_series")


def _base(column: str) -> str:
    return column.rsplit("::", 1)[-1]


def parse_period(text: str | None, *, end: bool) -> date | None:
    """'2025' | '2025-03' | '2025-03-31' → tarih; boş → None. Biçim bozuksa ValueError."""
    if text is None or not str(text).strip():
        return None
    t = str(text).strip()
    if re.fullmatch(r"\d{4}", t):
        y = int(t)
        return date(y, 12, 31) if end else date(y, 1, 1)
    if re.fullmatch(r"\d{4}-\d{2}", t):
        y, m = int(t[:4]), int(t[5:7])
        return date(y, m, calendar.monthrange(y, m)[1]) if end else date(y, m, 1)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
        return date.fromisoformat(t)
    raise ValueError(f"dönem biçimi anlaşılmadı: {t!r} (YYYY, YYYY-AA ya da YYYY-AA-GG bekleniyor)")


def workspace_view(frame: pd.DataFrame) -> pd.DataFrame:
    """Analiz tablosuna giden kesit: kanıt kolonları kalır, kurulum/iç alanlar düşer.

    `artifact_sha256_list` ve `source_observation_dates` kalır — kanıt paneli (C2) satırdan
    RAW'a bu iki kolonla iner. `series_id` düşer: tek seride sabit, join'de zaten kolon adında.
    """
    keep = [c for c in frame.columns if _base(str(c)) not in _DROP_FROM_WORKSPACE]
    view = frame[keep].copy()
    # Gold CLI/JSON boundaries may serialize canonical dates as ISO strings.
    # Restore true date objects before the result becomes an active workspace:
    # downstream date arithmetic and DuckDB window tools must not see a VARCHAR
    # time axis merely because the transport format was textual.
    for column in ("period_start", "period_end"):
        if column not in view.columns:
            continue
        present = view[column].notna()
        parsed = pd.to_datetime(view[column], errors="coerce")
        if int(present.sum()) == int(parsed.notna().sum()):
            dates = parsed.dt.date.astype(object)
            view[column] = dates.where(parsed.notna(), None)
    if "entity_id" in view.columns and view["entity_id"].isna().all():
        view = view.drop(columns=["entity_id"])
    return view.reset_index(drop=True)


def _preview_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if not str(c).endswith(_HIDE_IN_PREVIEW_SUFFIXES)]


class _GoldParamsBase(BaseModel):
    purpose: str = Field(description="Bu hesabın neyi cevapladığını anlatan tek cümlelik Türkçe açıklama.")
    period_from: str | None = Field(
        default=None,
        description="Dönem filtresi başlangıcı: 'YYYY', 'YYYY-AA' ya da 'YYYY-AA-GG'. Kullanıcı yıl/dönem söylediyse ver.",
    )
    period_to: str | None = Field(default=None, description="Dönem filtresi sonu, aynı biçimde. Tek yıl için period_from ile aynı yılı ver.")


class GoldAlignParams(_GoldParamsBase):
    series_id: str = Field(description="lakehouse_search'ten dönen seri kimliği (gold. ile başlayan tablo DEĞİL)")
    target_frequency: Literal["monthly", "quarterly"] = Field(
        description="Hedef dönem: 'monthly' (aylık) ya da 'quarterly' (çeyreklik). Kaynaktan kaba olmalı."
    )


class GoldDecomposeParams(_GoldParamsBase):
    series_id: str = Field(description="Birikimli (YTD/kümülatif) serinin kimliği")


class GoldJoinParams(_GoldParamsBase):
    series_ids: list[str] = Field(min_length=2, max_length=6, description="Aynı dönem ekseninde yan yana konacak seri kimlikleri (2–6)")
    target_frequency: Literal["monthly", "quarterly"] = Field(description="Ortak dönem: 'monthly' ya da 'quarterly'")


class _GoldTool(Tool):
    role = "execute"
    function: str

    def __init__(self, lakehouse: GoldCapable, workspace: AnalysisWorkspace, *, registry: object | None = None) -> None:
        self.lakehouse = lakehouse
        self.workspace = workspace
        self._registry = registry

    def _consent(self) -> bool:
        reg = self._registry
        return unverified_consent(getattr(reg, "user_text", None) or getattr(reg, "active_question", "") or "")

    def _canonical_month_window(self, params: BaseModel) -> tuple[date, date] | None:
        """Return the resolved outer month window for an ambiguous containment request.

        The model may correctly notice the anchor years but still pass those years as
        ``period_from``/``period_to`` to Gold.  Gold otherwise treats those arguments as
        an ordinary display filter and silently installs a 24-row table for a 60-month
        request.  The agent's resolved question is the canonical period decision, so the
        harness applies it consistently across lakehouse_query and all Gold tools.
        """
        if getattr(params, "target_frequency", None) != "monthly":
            return None
        question = getattr(self._registry, "active_question", "") if self._registry is not None else ""
        intent = parse_period_intent(question or "")
        if not (
            intent.window_months
            and intent.outer_bounds_explicit
            and intent.outer_start is not None
            and intent.outer_end is not None
        ):
            return None
        return intent.outer_start, intent.outer_end

    # ---- sınır doğrulayıcı kancaları
    def _series_ids(self, params: BaseModel) -> list[str]:
        return list(getattr(params, "series_ids", None) or [getattr(params, "series_id")])

    def validate_refs(self, params: BaseModel) -> ToolError | None:
        try:
            parse_period(getattr(params, "period_from", None), end=False)
            parse_period(getattr(params, "period_to", None), end=True)
        except ValueError as exc:
            return ToolError(error_code="INVALID_ARGS", message=str(exc), layer="schema",
                             hint="period_from/period_to alanlarını 'YYYY' ya da 'YYYY-AA' biçiminde ver.")
        for sid in self._series_ids(params):
            if sid.startswith("gold."):
                return ToolError(
                    error_code="DATASET_NOT_FOUND", layer="reference",
                    message=f"'{sid}' bir seri değil, hazır bir Gold tablosu; zaten hesaplanmış.",
                    hint=f"lakehouse_query ile doğrudan sorgula: SELECT period_end, value FROM {sid} ORDER BY period_end",
                )
            missing = _dataset_missing(self.lakehouse, sid)  # type: ignore[arg-type]
            if missing:
                return missing
        return None

    def _verified_alternatives(self, series_id: str | None, limit: int = 3) -> list[str]:
        """Reddedilen serinin adıyla arayıp semantiği doğrulanmış, başka kimlikli serileri döndürür (en çok `limit`)."""
        if not series_id:
            return []
        try:
            spec = self.lakehouse.get_dataset(series_id)
            hits = self.lakehouse.search_datasets(str(getattr(spec, "name", "") or series_id), limit=8)
        except Exception:  # noqa: BLE001 — öneri üretilemezse ret yine geçerli
            return []
        return [str(h.dataset_id) for h in hits
                if str(h.dataset_id) != series_id and getattr(h, "semantic_confidence", None) == "verified"
                and not str(h.dataset_id).startswith("gold.")][:limit]

    # ---- çağrı
    def _call(self, params: BaseModel) -> QueryResult:
        raise NotImplementedError

    def _headline(self, params: BaseModel) -> str:
        raise NotImplementedError

    def run(self, params: BaseModel) -> ToolResult:
        try:
            result = self._call(params)
        except GoldRefused as exc:
            reason = exc.reason
            tr = REASON_TR.get(reason, exc.detail)
            alt = _ALTERNATIVE_TR.get(reason, "")
            verified = self._verified_alternatives(exc.series_id) if reason == "UNVERIFIED_SEMANTICS" else []
            if verified:
                # Ölçüldü (benchmark P04, 22 Eyl): model "Toplam Krediler (Krediler tablosu)" — semantiği doğrulanmamış —
                # seçti, Gold reddetti, tur bitti; aynı kavramın doğrulanmış serisi (Bilanço "Krediler, Toplam") duruyordu.
                # Aday genel: aynı adla aranan, semantiği doğrulanmış, başka kimlikli seriler.
                alt = (alt + " Aynı kavramın DOĞRULANMIŞ serisi var: " + ", ".join(verified)
                       + " — onay istemeden önce aynı işlemi bu seriyle yeniden dene.").strip()
            result = ToolResult.fail(
                "GOLD_REFUSED",
                f"Gold reddetti [{reason}]{f' ({exc.series_id})' if exc.series_id else ''}: {tr} "
                f"(veri katmanı: {exc.detail})",
                hint=("Kullanıcıya bu sebebi sade Türkçeyle söyle; sayı üretme, aynı işi SQL ile "
                      "yapmaya kalkma. " + alt).strip(),
                layer="policy", retryable=False, candidates=verified,
            )
            if verified and result.error is not None:
                # Doğrulanmış eşdeğer varken tur bitmez: model aynı işlemi o seriyle yeniden dener (terminal=False,
                # CLARIFY_NOT_ALLOWED ile aynı sözleşme). Eşdeğer yoksa ret terminal kalır, kullanıcıya sorulur.
                result.error.terminal = False
            return result
        except LakehouseError as exc:
            return ToolResult.fail("TOOL_FAILED", str(exc), layer="harness", retryable=False,
                                   hint="Kullanıcıya hesabın yapılamadığını söyle.")

        frame = result.data
        start = parse_period(getattr(params, "period_from", None), end=False)
        end = parse_period(getattr(params, "period_to", None), end=True)
        canonical_window = self._canonical_month_window(params)
        if canonical_window is not None:
            # The selected outer window wins over an anchor-only model argument.  This
            # keeps the active table and the period note on the same 60-month contract.
            start, end = canonical_window
        full_span = (frame["period_end"].min(), frame["period_end"].max()) if len(frame) else (None, None)
        filtered = frame
        if start is not None:
            filtered = filtered[filtered["period_end"] >= start]
        if end is not None:
            filtered = filtered[filtered["period_end"] <= end]
        if len(frame) and filtered.empty:
            return ToolResult(
                content=(
                    "SONUÇ: İstenen dönem hesaplanan Gold sonucunda yok. Bu bir hata değildir; "
                    f"hesap doğru çalıştı. Elde olan dönemler: {full_span[0]} → {full_span[1]}.\n"
                    "ŞİMDİ YAPACAĞIN: Araç çağırmayı bırak ve kullanıcıya istediği dönemin "
                    "bulunmadığını, hangi aralığın mevcut olduğunu tek paragrafta söyle. Sayı tahmin etme."
                ),
                ok=True, provenance=result.provenance,
            )

        view = workspace_view(filtered)
        self.workspace.set_table(view, description=params.purpose, provenance=result.provenance)  # type: ignore[attr-defined]
        self.workspace.title = params.purpose  # type: ignore[attr-defined]

        from ..core.preview import preview_table

        shown = _preview_columns(view)
        lines = [
            self._headline(params) + f": {len(frame)} dönem hesaplandı ({full_span[0]} → {full_span[1]})"
            + (f"; dönem filtresiyle {len(view)} satır" if len(view) != len(frame) else ""),
            self._rule_line(result),
            f"Sütunlar: {', '.join(map(str, view.columns))}",
            preview_table(view[shown]),   # ≤24 satır tamamı, üstü baş+son (core/preview, PART 41)
        ]
        if self._consent() and any("DOĞRULANMAMIŞ" in w for w in result.provenance.warnings):
            lines.append("NOT: seri semantiği doğrulanmamış; kullanıcının açık onayıyla kullanıldı — cevapta söyle.")
        lines.append("Kanıt: her satırda source_observation_dates ve artifact_sha256_list (kaynak gözlem → RAW).")
        lines.append(f"Kaynak: {result.provenance.summary()}")
        return ToolResult(content="\n".join(lines), data=view, provenance=result.provenance)

    def _rule_line(self, result: QueryResult) -> str:
        frame = result.data
        parts: list[str] = []
        for column in frame.columns:
            base = _base(str(column))
            if base == "aggregation":
                key = str(column).rsplit("::", 1)[0] if "::" in str(column) else "kural"
                mt_col = str(column).replace("aggregation", "measure_type")
                unit_col = str(column).replace("aggregation", "unit")
                agg = frame[column].dropna().astype(str).unique().tolist()
                mt = frame[mt_col].dropna().astype(str).unique().tolist() if mt_col in frame.columns else []
                unit = frame[unit_col].dropna().astype(str).unique().tolist() if unit_col in frame.columns else []
                parts.append(f"{key}: {'/'.join(mt) or '?'} → {'/'.join(agg)}" + (f", birim {'/'.join(unit)}" if unit else ""))
        if "decomposition_flag" in frame.columns:
            counts = frame["decomposition_flag"].astype(str).value_counts()
            parts.append("çözümleme: " + ", ".join(f"{k}×{int(v)}" for k, v in counts.items()))
        return "Kural (katalogdan): " + ("; ".join(parts) if parts else "—")


class GoldAlignTool(_GoldTool):
    name = "gold_align"
    function = "align_frequency"
    description = (
        "Bir seriyi katalog kuralıyla AYLIK ya da ÇEYREKLİK takvim dönemine indirger "
        "(stok → dönemin son değeri, akım → toplam, oran → katalogdaki kural). 'Çeyreklik göster', "
        "'aylığa indir', 'çeyrek sonu bakiyesi' gibi frekans dönüşümü isteklerinde SQL ile "
        "toplama/ortalama YAPMA, bu aracı kullan. Sonuç aktif analiz tablosu olur; her satır "
        "kaynak gözlem tarihlerini ve kanıt özetlerini taşır. Kural katalogdan gelir, seçilemez; "
        "dönüşüm güvenli değilse sebebiyle reddeder."
    )
    Params = GoldAlignParams

    def _call(self, params: GoldAlignParams) -> QueryResult:
        return self.lakehouse.gold_align(params.series_id, params.target_frequency, allow_unverified=self._consent())

    def _headline(self, params: GoldAlignParams) -> str:
        return f"Gold align: {params.series_id} → {params.target_frequency}"


class GoldDecomposeTool(_GoldTool):
    name = "gold_decompose"
    function = "decompose_cumulative"
    description = (
        "Yıl başından itibaren (YTD) ya da kuruluştan itibaren birikimli bir seriyi dönem "
        "AKIMLARINA çözer (bu ayın değeri = bu ay − geçen ay; Ocak'ta yıl başından sıfırlanır). "
        "Yalnız kataloğu birikimli diyen seride çalışır; stok ya da düz akım seride 'birikimli "
        "değil' diye reddeder — o zaman kullanıcıya bunu söyle, kendin fark alma. Her satır "
        "decomposition_flag ile durumunu söyler (ok / no_prior_base / spans_multiple_periods ...)."
    )
    Params = GoldDecomposeParams

    def _call(self, params: GoldDecomposeParams) -> QueryResult:
        return self.lakehouse.gold_decompose(params.series_id, allow_unverified=self._consent())

    def _headline(self, params: GoldDecomposeParams) -> str:
        return f"Gold decompose: {params.series_id}"


class GoldJoinTool(_GoldTool):
    name = "gold_join"
    function = "join_on_period"
    description = (
        "Birden çok seriyi HER BİRİNİ kendi katalog kuralıyla aynı aylık/çeyreklik dönem eksenine "
        "hizalayıp yan yana koyar (dış birleştirme: bir serinin yayımlamadığı dönem boş kalır, "
        "sıfır olmaz). 'İki seriyi aynı dönemde karşılaştır', 'faiz ile bakiyeyi aylık yan yana "
        "göster' gibi isteklerde kullan. Kolonlar '<seri>::value' biçimindedir. Herhangi bir seri "
        "güvenle dönüştürülemiyorsa tümü reddedilir."
    )
    Params = GoldJoinParams

    def _call(self, params: GoldJoinParams) -> QueryResult:
        return self.lakehouse.gold_join(list(params.series_ids), params.target_frequency, allow_unverified=self._consent())

    def _headline(self, params: GoldJoinParams) -> str:
        return f"Gold join: {' + '.join(params.series_ids)} → {params.target_frequency}"


__all__ = [
    "GOLD_PROMPT_RULES", "REASON_TR", "unverified_consent", "GoldAlignTool", "GoldDecomposeTool", "GoldJoinTool",
    "parse_period", "workspace_view",
]
