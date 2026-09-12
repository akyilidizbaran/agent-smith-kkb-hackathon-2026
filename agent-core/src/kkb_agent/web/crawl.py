"""Bütçeli tarama — sayfa, derinlik, süre ve bayt sınırı; aynı alan adı; ilgiye göre sıra.

Mentörün kuralı: tarama bütçe ve ilgi tabanlı olsun, "her şeyi çek" olmasın. Sıra
deterministik: önce doğrudan veri bağlantıları (.csv/.xlsx/.json), sonra metni ya da adresi
soru sözcükleriyle örtüşen bağlantılar, sonra kalanlar. Taranıp kullanılmayan her sayfa
`visited`'da kalır ve kanıt paneline gider; cevaba değil.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlparse

from .fetch import DATA_SUFFIXES, FetchRefused, FetchResult, RobotsCache, canonical, fetch_url, same_domain
from .html import PageContent, extract_page

_TOKEN = re.compile(r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]{3,}")
_STOP = {"için", "ile", "olan", "olarak", "bir", "ve", "veya", "the", "and", "from", "this"}


@dataclass(frozen=True)
class CrawlBudget:
    max_pages: int = 1
    max_depth: int = 0
    max_seconds: float = 20.0
    max_bytes_per_page: int = 8 * 1024 * 1024

    def clamp(self) -> "CrawlBudget":
        return CrawlBudget(
            max_pages=max(1, min(self.max_pages, 5)),
            max_depth=max(0, min(self.max_depth, 1)),
            max_seconds=max(5.0, min(self.max_seconds, 60.0)),
            max_bytes_per_page=self.max_bytes_per_page,
        )


@dataclass
class VisitedPage:
    url: str
    depth: int
    fetch: FetchResult
    page: PageContent | None
    score: float = 0.0

    @property
    def ok(self) -> bool:
        return self.fetch.ok and self.page is not None


@dataclass
class CrawlResult:
    start_url: str
    pages: list[VisitedPage] = field(default_factory=list)          # başarıyla okunan
    blocked: list[VisitedPage] = field(default_factory=list)        # erişim sözleşmesi reddi
    skipped: list[tuple[str, str]] = field(default_factory=list)    # (url, sebep) — bütçe / alan adı / politika
    elapsed_ms: float = 0.0
    budget: CrawlBudget = field(default_factory=CrawlBudget)

    @property
    def visited_urls(self) -> list[str]:
        return [p.url for p in self.pages] + [p.url for p in self.blocked]

    @property
    def first(self) -> VisitedPage | None:
        return self.pages[0] if self.pages else (self.blocked[0] if self.blocked else None)

    def summary(self) -> str:
        return (f"tarama: {len(self.pages)} sayfa okundu, {len(self.blocked)} erişilemedi, "
                f"{len(self.skipped)} atlandı; bütçe {self.budget.max_pages} sayfa / derinlik "
                f"{self.budget.max_depth} / {self.budget.max_seconds:.0f} s; süre {self.elapsed_ms / 1000:.1f} s")


def keywords_of(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "") if t.lower() not in _STOP}


def link_score(label: str, href: str, keywords: set[str]) -> float:
    """Doğrudan veri bağlantısı en öne; sonra sözcük örtüşmesi. Sıfır → ilgisiz."""
    score = 0.0
    path = urlparse(href).path.lower()
    if path.endswith(DATA_SUFFIXES):
        score += 10.0
    hay = f"{label} {href}".lower()
    score += sum(1.0 for k in keywords if k in hay)
    return score


def crawl(
    start_url: str,
    *,
    budget: CrawlBudget,
    keywords: Iterable[str] = (),
    session: Any = None,
    robots: RobotsCache | None = None,
    allowed_local_roots: Iterable[Any] = (),
    environ: Mapping[str, str] | None = None,
    fetcher: Callable[..., FetchResult] = fetch_url,
    allow_private: bool = False,
) -> CrawlResult:
    budget = budget.clamp()
    robots = robots or RobotsCache()
    kws = set(k.lower() for k in keywords)
    result = CrawlResult(start_url=start_url, budget=budget)
    started = time.perf_counter()
    queue: list[tuple[float, int, str]] = [(0.0, 0, start_url)]
    seen: set[str] = {canonical(start_url)}

    while queue:
        if len(result.pages) + len(result.blocked) >= budget.max_pages:
            result.skipped.extend((u, "bütçe: sayfa sınırı") for _, _, u in queue)
            break
        if time.perf_counter() - started > budget.max_seconds:
            result.skipped.extend((u, "bütçe: süre sınırı") for _, _, u in queue)
            break
        queue.sort(key=lambda item: (-item[0], item[1], item[2]))
        score, depth, url = queue.pop(0)
        try:
            fetched = fetcher(url, session=session, robots=robots, allowed_local_roots=allowed_local_roots,
                              max_bytes=budget.max_bytes_per_page, environ=environ, allow_private=allow_private)
        except FetchRefused as exc:
            result.skipped.append((url, f"politika: {exc}"))
            continue
        if not fetched.ok:
            result.blocked.append(VisitedPage(url=url, depth=depth, fetch=fetched, page=None, score=score))
            continue
        page = extract_page(fetched.content, fetched.media_type, fetched.final_url or url)
        result.pages.append(VisitedPage(url=url, depth=depth, fetch=fetched, page=page, score=score))
        if depth >= budget.max_depth:
            continue
        for label, href in page.data_links + page.links:
            key = canonical(href)
            if key in seen:
                continue
            seen.add(key)
            if not fetched.from_local_file and not same_domain(href, start_url):
                result.skipped.append((href, "başka alan adı"))
                continue
            s = link_score(label, href, kws)
            if s <= 0:
                result.skipped.append((href, "ilgisiz"))
                continue
            queue.append((s, depth + 1, href))
    result.elapsed_ms = (time.perf_counter() - started) * 1000
    return result


__all__ = ["CrawlBudget", "CrawlResult", "VisitedPage", "crawl", "keywords_of", "link_score"]
