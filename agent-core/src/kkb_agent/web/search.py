"""Web araması — Tavily. Anahtar yoksa araç yoktur; agent bunu söyler, taklit etmez.

Arama sonucu VERİ DEĞİLDİR: başlık, adres, kısa alıntı. Sayı oradan okunmaz; sayfa
`web_url` ile açılır, tablo yüklenir, kanıt zinciri ona iner. Anahtar `TAVILY_API_KEY`
ortam değişkeninden okunur ve yalnız isteğe gider; loga, karta, cevaba girmez.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping

from ..contracts.access import AccessOutcome
from ..core.access_policy import classify_access

TAVILY_ENV = "TAVILY_API_KEY"
TAVILY_URL = "https://api.tavily.com/search"


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
    def __init__(self, *, environ: Mapping[str, str] | None = None, session: Any = None, timeout: float = 20.0) -> None:
        self._environ = environ if environ is not None else os.environ
        self._session = session
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return search_available(self._environ)

    def search(self, query: str, *, max_results: int = 5, include_domains: list[str] | None = None) -> tuple[list[SearchHit], AccessOutcome]:
        if not self.available:
            outcome = classify_access(TAVILY_URL, http_status=401, environ=self._environ)
            return [], outcome
        session = self._session
        if session is None:
            from .session import default_session
            session = default_session()
        payload: dict[str, Any] = {
            "api_key": self._environ[TAVILY_ENV], "query": query,
            "max_results": max(1, min(int(max_results), 10)), "search_depth": "basic",
        }
        if include_domains:
            payload["include_domains"] = include_domains
        try:
            resp = session.post(TAVILY_URL, json=payload, timeout=self.timeout)
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


__all__ = ["SearchHit", "TAVILY_ENV", "TavilySearch", "search_available"]
