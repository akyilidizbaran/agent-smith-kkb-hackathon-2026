"""Web araması — Tavily. Anahtar yoksa araç yoktur; agent bunu söyler, taklit etmez.

Arama sonucu VERİ DEĞİLDİR: başlık, adres, kısa alıntı. Sayı oradan okunmaz; sayfa
`web_url` ile açılır, tablo yüklenir, kanıt zinciri ona iner. Anahtar `TAVILY_API_KEY`
ortam değişkeninden okunur ve yalnız isteğe gider; loga, karta, cevaba girmez.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Mapping

from ..contracts.access import AccessOutcome
from ..core.access_policy import classify_access

TAVILY_ENV = "TAVILY_API_KEY"
TAVILY_URL = "https://api.tavily.com/search"
# Süreç başına arama bütçesi: ücretsiz katman ayda 1.000 kredi (basic arama 1 kredi). Golden
# döngüsü ya da kaçak bir tekrar bunu bir öğleden sonra bitirebilir; kural mentörün "budget-based"
# çizgisiyle aynı. Ortamdan değiştirilebilir, demo günü yükseltilir.
BUDGET_ENV = "WEB_SEARCH_BUDGET"
DEFAULT_BUDGET = 20


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    score: float | None = None


def search_available(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return bool(env.get(TAVILY_ENV))


class TavilySearch:
    def __init__(self, *, environ: Mapping[str, str] | None = None, session: Any = None, timeout: float = 20.0,
                 budget: int | None = None) -> None:
        self._environ = environ if environ is not None else os.environ
        self._session = session
        self.timeout = timeout
        raw = self._environ.get(BUDGET_ENV, "") if budget is None else str(budget)
        self.budget = int(raw) if str(raw).strip().isdigit() else DEFAULT_BUDGET
        self.calls = 0

    @property
    def available(self) -> bool:
        return search_available(self._environ)

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.calls)

    def search(self, query: str, *, max_results: int = 5, include_domains: list[str] | None = None,
               topic: str = "general", time_range: str | None = None) -> tuple[list[SearchHit], AccessOutcome]:
        if not self.available:
            outcome = classify_access(TAVILY_URL, http_status=401, environ=self._environ)
            return [], outcome
        if self.calls >= self.budget:
            base = classify_access(TAVILY_URL, http_status=429, environ=self._environ)
            return [], replace(base, message=f"Bu oturumun web arama bütçesi doldu ({self.budget} arama; "
                                             f"{BUDGET_ENV} ile artırılır). Kullanıcıdan adres iste.")
        session = self._session
        if session is None:
            from .session import default_session
            session = default_session()
        # Anahtar gövdeye değil Authorization başlığına gider (Tavily'nin güncel sözleşmesi);
        # gövde loglansa bile anahtar sızmaz.
        headers = {"Authorization": f"Bearer {self._environ[TAVILY_ENV]}", "Content-Type": "application/json"}
        payload: dict[str, Any] = {
            "query": query, "max_results": max(1, min(int(max_results), 10)), "search_depth": "basic",
            "topic": topic if topic in ("general", "news", "finance") else "general",
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if time_range in ("day", "week", "month", "year"):
            payload["time_range"] = time_range
        self.calls += 1
        try:
            resp = session.post(TAVILY_URL, json=payload, headers=headers, timeout=self.timeout)
        except Exception:  # noqa: BLE001
            return [], classify_access(TAVILY_URL, http_status=None, environ=self._environ)
        status = getattr(resp, "status_code", None)
        if status != 200:
            return [], classify_access(TAVILY_URL, http_status=status, environ=self._environ)
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            return [], classify_access(TAVILY_URL, http_status=500, environ=self._environ)
        hits = [
            SearchHit(title=str(r.get("title") or ""), url=str(r.get("url") or ""),
                      snippet=str(r.get("content") or "")[:300], score=r.get("score"))
            for r in data.get("results", []) if r.get("url")
        ]
        return hits, classify_access(TAVILY_URL, http_status=200, environ=self._environ)


__all__ = ["BUDGET_ENV", "DEFAULT_BUDGET", "SearchHit", "TAVILY_ENV", "TavilySearch", "search_available"]
