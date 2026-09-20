"""Turn-scoped controls for bounded, auditable web research.

Search results are candidates, not evidence. A follow-up search must either
follow an opened candidate or name the unresolved information it is meant to
establish. The state is deliberately domain-neutral and is reset per user turn.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse


def _query_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ı", "i")
    normalized = "".join(
        char
        for char in unicodedata.normalize("NFKD", normalized)
        if not unicodedata.category(char).startswith("M")
    )
    return " ".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


def canonical_page_url(value: str) -> str:
    """Normalize URL identity without merging distinct hosts or query strings."""
    raw = str(value or "").strip()
    try:
        parsed = urlparse(raw)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return raw
        host = parsed.hostname.lower().rstrip(".")
        port = parsed.port
        default_port = (parsed.scheme.lower() == "https" and port == 443) or (
            parsed.scheme.lower() == "http" and port == 80
        )
        netloc = host if port is None or default_port else f"{host}:{port}"
        return urlunparse(
            (parsed.scheme.lower(), netloc, parsed.path or "/", parsed.params, parsed.query, "")
        )
    except ValueError:
        return raw


@dataclass(frozen=True)
class SearchDenial:
    error_code: str
    message: str
    hint: str


@dataclass
class WebResearchState:
    """Bounded per-turn web discovery, page reads, and model evidence context."""

    max_searches: int = 3
    max_unique_pages: int = 5
    max_model_evidence_chars: int = 48_000
    attempted_queries: list[str] = field(default_factory=list)
    successful_searches: int = 0
    pages_read: set[str] = field(default_factory=set)
    hosts_read: set[str] = field(default_factory=set)
    model_evidence_chars: int = 0
    context_truncated: bool = False
    stage: str = "idle"
    _last_search_had_candidates: bool = False
    _pages_read_after_search: int = 0

    def authorize_search(self, query: str, research_gap: str | None = None) -> SearchDenial | None:
        """Reserve a search only when this turn has budget and a distinct purpose."""
        key = _query_key(query)
        if not key:
            return SearchDenial(
                "INVALID_ARGS",
                "Arama sorgusu boş; yeni kaynak adayı bulunamadı.",
                "Kullanıcının istediği konuya bağlı, kısa bir arama sorgusu ver.",
            )
        if len(self.attempted_queries) >= self.max_searches:
            return SearchDenial(
                "WEB_RESEARCH_BUDGET",
                "Bu turdaki web arama bütçesi doldu.",
                "Açılmış kaynaklardan cevapla veya hangi kanıtın eksik kaldığını kullanıcıya bildir.",
            )
        if key in self.attempted_queries:
            return SearchDenial(
                "WEB_RESEARCH_DUPLICATE_QUERY",
                "Bu turda aynı arama sorgusu zaten denendi.",
                "Mevcut adayları kullan; yeni arama gerekiyorsa farklı ve kanıtlanabilir bir bilgi boşluğunu hedefle.",
            )
        if self.attempted_queries:
            if self._last_search_had_candidates and self._pages_read_after_search == 0:
                return SearchDenial(
                    "WEB_RESEARCH_NEEDS_READ",
                    "Önceki aramada bulunan bir kaynak henüz açılmadı.",
                    "Yeni arama yapmadan önce mevcut adaylardan uygun olanını web_url ile oku.",
                )
            if not str(research_gap or "").strip():
                return SearchDenial(
                    "WEB_RESEARCH_GAP_REQUIRED",
                    "Ek aramanın hangi bilgi boşluğunu kapatacağı belirtilmedi.",
                    "Açılmış kaynakların doğrulamadığı iddiayı veya kaynaklar arasındaki çelişkiyi research_gap alanında belirt.",
                )

        self.attempted_queries.append(key)
        self._last_search_had_candidates = False
        self._pages_read_after_search = 0
        self.stage = "searching"
        return None

    @property
    def remaining_searches(self) -> int:
        return max(0, self.max_searches - len(self.attempted_queries))

    @property
    def remaining_pages(self) -> int:
        return max(0, self.max_unique_pages - len(self.pages_read))

    @property
    def control_active(self) -> bool:
        """Whether the current turn is still in a tool-enabled web research loop."""
        return bool(self.attempted_queries) and self.stage != "complete"

    def page_budget(self, url: str, requested: int) -> int:
        """Clamp a crawl to the remaining unique-page budget; cached known URLs may be reread."""
        requested = max(0, int(requested))
        key = canonical_page_url(url)
        remaining = self.remaining_pages
        if remaining <= 0:
            return min(requested, 1) if key in self.pages_read else 0
        return min(requested, remaining)

    def record_tool_result(self, name: str, result: object) -> None:
        artifacts = getattr(result, "artifacts", {}) or {}
        if name == "web_search":
            search_artifact = artifacts.get("web_search") or {}
            if getattr(result, "ok", False) and search_artifact:
                self.successful_searches += 1
                self._last_search_had_candidates = bool(search_artifact.get("results"))
                self.stage = (
                    "awaiting_source" if self._last_search_had_candidates else "evidence_review"
                )
            else:
                self.stage = "evidence_review"
            return
        if name != "web_url":
            return
        web_artifact = artifacts.get("web") or {}
        newly_read = 0
        for page in web_artifact.get("visited") or []:
            try:
                status = int(page.get("status") or 0)
            except (TypeError, ValueError):
                status = 0
            url = canonical_page_url(str(page.get("url") or ""))
            host = (urlparse(url).hostname or "").lower()
            if 200 <= status < 300 and url and url not in self.pages_read:
                self.pages_read.add(url)
                if host:
                    self.hosts_read.add(host)
                newly_read += 1
        if newly_read:
            self._pages_read_after_search += newly_read
            self.stage = "evidence_review"

    def bound_model_evidence(self, content: str) -> str:
        """Keep accumulated external text bounded while retaining its source artifact."""
        text = content or ""
        remaining = max(0, self.max_model_evidence_chars - self.model_evidence_chars)
        if len(text) <= remaining:
            self.model_evidence_chars += len(text)
            return text
        self.model_evidence_chars += remaining
        self.context_truncated = True
        notice = (
            "\n[Bu turdaki dış kaynak metin bütçesi doldu; kaynak kaydı kanıt panelinde korunuyor. "
            "Eksik kalan iddiayı doğrulanmış gibi sunma.]"
        )
        return text[:remaining].rstrip() + notice

    def mark_complete(self) -> None:
        self.stage = "complete"

    def snapshot(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "search_attempts": len(self.attempted_queries),
            "successful_searches": self.successful_searches,
            "unique_pages_read": len(self.pages_read),
            "unique_hosts_read": len(self.hosts_read),
            "remaining_searches": self.remaining_searches,
            "remaining_pages": self.remaining_pages,
            "model_evidence_chars": self.model_evidence_chars,
            "context_truncated": self.context_truncated,
        }


__all__ = ["SearchDenial", "WebResearchState", "canonical_page_url"]
