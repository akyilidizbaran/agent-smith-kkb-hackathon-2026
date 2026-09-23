"""Araç kapısı — soruya göre o tur sunulacak araç alt kümesi (ADR-0043).

Ölçüldü: 18 aracın şeması her çağrıda ~5.300 token; büyük katalogda model hem seri hem araç
seçiminde daha çok yanılıyor (aylık soruya çeyreklik Gold tablosu, grafik yerine sorgu).
Kapı seçenek kaldırır (ADR-0010): sorunun sinyali yoksa aile hiç sunulmaz.

Her zaman açık: lakehouse ×4, workspace ×4, gold ×3 (demo sorularının çoğu dönem ister).
Sinyalle açılan: chart (grafik sözcükleri), analitik (aykırı/kırılma/öncülük), web (adres,
"sayfa", "ara"), Architect (yazma niyeti ya da dosya/adres + ekle/onayla). Kapalı bir aracı
model yine de adıyla çağırırsa kayıt defteri onu çalıştırır: kapı sunulan şemayı daraltır,
yetkiyi değil. `TOOL_GATE=off` ile ölçüm için kapatılır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .intent import write_intent
from .question_preflight import _PREMISE as _PREMISE_Q   # öncül kalıbı tek yerde (Büşra, V3 §3.9)

ALWAYS = frozenset({
    "lakehouse_search", "lakehouse_describe", "lakehouse_distinct_values", "lakehouse_query",
    "lakehouse_breakdown_panel",
    "workspace_add_column", "workspace_compute_column", "workspace_show", "workspace_query", "workspace_real_value", "workspace_join",
    "gold_align", "gold_decompose", "gold_join",
    "clarify",   # netleştirme (tools/clarify.py): şema küçük, politika kapısı kendi içinde (yalnız uygunluk "kısmen" dediğinde)
})
# İlk planlama çağrısında yalnız veri keşfi ve sorgu araçları sunulur. Veri
# üretildikten sonra dönüşüm/analiz aileleri açılır.
RETRIEVAL_PHASE = frozenset({
    "lakehouse_search", "lakehouse_describe", "lakehouse_distinct_values",
    "lakehouse_query", "lakehouse_breakdown_panel", "clarify",
})
GOLD_PHASE = frozenset({"gold_align", "gold_decompose", "gold_join"})
WORKSPACE_PHASE = frozenset({
    "workspace_add_column", "workspace_compute_column", "workspace_show",
    "workspace_query", "workspace_real_value", "workspace_join",
})
CHART = frozenset({"chart"})
ANALYTICS = frozenset({"anomaly_detect", "change_points", "lead_lag"})
WEB = frozenset({"web_url", "web_search"})
ARCHITECT = frozenset({"ingest_from_url", "ingest_source", "promote_draft"})
#: Öncül ailesi (Büşra, tools/premise.py): soru bir yön varsayıyorsa ("düştüğü için", "neden arttı") açılır.
PREMISE = frozenset({"check_premise"})

_CHART = re.compile(r"grafi|çiz|gorselle|görselle|\bplot\b|\bchart\b|harita", re.I)
_ANALYTICS = re.compile(r"anomali|aykır|sapan|sapma|olağan ?dışı|sıra ?dışı|kırılma|rejim değişi|öncül|önden mi|korelasyon|granger|ilişki|mevsimsel|seasonal|\bmad\b|medyan mutlak", re.I)
_WEB = re.compile(r"https?://|www\.|\.pdf\b|\.png\b|\.jpe?g\b|\.csv\b|\.xlsx?\b|sayfa|siteden|linkten|adres|internet|web|\barama\b|\bara\b|bul\b|"
                  # Kırılma dönemlerini "yorumla" isteği dönemin gelişmelerine dayanır; web araştırması açılır (23 Eyl demo).
                  r"kırılma[\s\S]{0,120}yorumla|kirilma[\s\S]{0,120}yorumla", re.I)
_ARCHITECT = re.compile(r"taslak|onayl|kataloğa al|kataloga al|ekle\b|yükle|yukle|kaydet|ingest|terfi|yayınla", re.I)
_WORKSPACE_HINT = re.compile(
    r"birleştir|birles|\bjoin\b|iki (?:ayrı )?tablo|sütun|kolon|tabloyu|tabloya|"
    r"workspace|hesapla|oran|yüzde|yuzde|değişim|degisim|normalleştir|normalestir|"
    r"ekle|dönüştür|donustur",
    re.I,
)


@dataclass(frozen=True)
class GateDecision:
    allowed: frozenset[str]
    opened: tuple[str, ...]      # sinyalle açılan aileler
    closed: tuple[str, ...]      # sunulmayan aileler


def initial_allowed(
    decision: GateDecision,
    *,
    has_table: bool = False,
) -> frozenset[str]:
    """İlk LLM çağrısı için küçük şema yüzünü döndür.

    Mevcut tablo takibinde tüm araçlar korunur. Yeni veri sorusunda açıkça
    istenen chart/web/analitik/architect ailesi görünür; workspace ve Gold
    şemaları ilk retrieval sonucu gelene kadar bekler.
    """
    if has_table:
        return decision.allowed
    opened_tools = decision.allowed - ALWAYS
    retrieval = RETRIEVAL_PHASE
    return frozenset((decision.allowed & retrieval) | opened_tools)


def post_retrieval_allowed(
    decision: GateDecision,
    question: str,
    *,
    has_table: bool = False,
    include_gold: bool = False,
) -> frozenset[str]:
    """Return the second-phase schema without reopening unrelated families.

    Plain retrieval questions keep the retrieval face until a deterministic
    ``GOLD_REQUIRED`` result proves that Gold conversion is needed. Workspace
    tools are added only when the user asks for a table transformation/join;
    chart/analytics/web/Architect families stay controlled by ``decision``.
    """
    if has_table:
        return decision.allowed
    opened_tools = decision.allowed - ALWAYS
    allowed = set(decision.allowed & RETRIEVAL_PHASE)
    if include_gold:
        allowed.update(decision.allowed & GOLD_PHASE)
    if _WORKSPACE_HINT.search(question):
        allowed.update(decision.allowed & WORKSPACE_PHASE)
    allowed.update(opened_tools)
    return frozenset(allowed)


def open_verified_public_web_fallback(
    decision: GateDecision,
    registered: set[str] | frozenset[str],
) -> GateDecision:
    """Open only registered web tools after the harness has verified absence.

    Callers must already have a source/domain-constrained fallback plan. This
    helper only changes the offered schema; it does not grant execution policy.
    """

    web_tools = WEB & frozenset(registered)
    if not web_tools:
        return decision
    allowed = decision.allowed | web_tools
    opened = decision.opened if "web_fallback" in decision.opened else (*decision.opened, "web_fallback")
    closed = tuple(family for family in decision.closed if family != "web")
    return GateDecision(allowed, opened, closed)


def decide(
    question: str,
    registered: set[str] | frozenset[str],
    *,
    user_text: str = "",
    has_table: bool = False,
    enabled: bool = True,
    initial_tools: set[str] | frozenset[str] | None = None,
) -> GateDecision:
    if not enabled:
        return GateDecision(frozenset(registered), (), ())
    text = f"{question}\n{user_text}"
    allowed = set(ALWAYS)
    if initial_tools is not None:
        allowed.update(initial_tools)
    opened: list[str] = []
    closed: list[str] = []
    for family, names, pattern in (("grafik", CHART, _CHART), ("analitik", ANALYTICS, _ANALYTICS), ("web", WEB, _WEB),
                                   ("öncül", PREMISE, _PREMISE_Q)):
        if pattern.search(question) or (family == "web" and pattern.search(user_text)):
            allowed |= names
            opened.append(family)
        else:
            closed.append(family)
    if write_intent(text) or _ARCHITECT.search(question):
        allowed |= ARCHITECT
        opened.append("architect")
    else:
        closed.append("architect")
    return GateDecision(frozenset(n for n in allowed if n in registered), tuple(opened), tuple(closed))


__all__ = ["ALWAYS", "ANALYTICS", "ARCHITECT", "CHART", "GOLD_PHASE", "GateDecision", "PREMISE", "RETRIEVAL_PHASE", "WEB", "WORKSPACE_PHASE", "decide", "initial_allowed", "open_verified_public_web_fallback", "post_retrieval_allowed"]
