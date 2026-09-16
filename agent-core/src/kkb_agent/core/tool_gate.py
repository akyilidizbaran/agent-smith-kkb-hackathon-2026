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
    "workspace_add_column", "workspace_compute_column", "workspace_show", "workspace_query", "workspace_real_value", "workspace_join",
    "gold_align", "gold_decompose", "gold_join",
    "clarify",   # netleştirme (tools/clarify.py): şema küçük, politika kapısı kendi içinde (yalnız uygunluk "kısmen" dediğinde)
})
CHART = frozenset({"chart"})
ANALYTICS = frozenset({"anomaly_detect", "change_points", "lead_lag"})
WEB = frozenset({"web_url", "web_search"})
ARCHITECT = frozenset({"ingest_from_url", "ingest_source", "promote_draft"})
#: Öncül ailesi (Büşra, tools/premise.py): soru bir yön varsayıyorsa ("düştüğü için", "neden arttı") açılır.
PREMISE = frozenset({"check_premise"})

_CHART = re.compile(r"grafi|çiz|gorselle|görselle|\bplot\b|\bchart\b|harita", re.I)
_ANALYTICS = re.compile(r"anomali|aykır|olağan ?dışı|sıra ?dışı|kırılma|rejim değişi|öncül|önden mi|korelasyon|granger|ilişki", re.I)
_WEB = re.compile(r"https?://|www\.|\.pdf\b|\.png\b|\.jpe?g\b|\.csv\b|\.xlsx?\b|sayfa|siteden|linkten|adres|internet|web|\barama\b|\bara\b|bul\b", re.I)
_ARCHITECT = re.compile(r"taslak|onayl|kataloğa al|kataloga al|ekle\b|yükle|yukle|kaydet|ingest|terfi|yayınla", re.I)


@dataclass(frozen=True)
class GateDecision:
    allowed: frozenset[str]
    opened: tuple[str, ...]      # sinyalle açılan aileler
    closed: tuple[str, ...]      # sunulmayan aileler


def decide(question: str, registered: set[str] | frozenset[str], *, user_text: str = "",
           has_table: bool = False, enabled: bool = True) -> GateDecision:
    if not enabled:
        return GateDecision(frozenset(registered), (), ())
    text = f"{question}\n{user_text}"
    allowed = set(ALWAYS)
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


__all__ = ["ALWAYS", "ANALYTICS", "ARCHITECT", "CHART", "GateDecision", "PREMISE", "WEB", "decide"]
