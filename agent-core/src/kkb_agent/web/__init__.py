"""Web erişimi — bütçeli, robots'a saygılı, erişim sözleşmesinden geçen (ADR-0034).

- `fetch.py`  — tek sayfa: özel/loopback adres yok, boyut sınırı, robots.txt, ADR-0028 sonucu.
- `html.py`   — sayfa → başlık, metin, tablolar (pandas/lxml), aynı alan adındaki bağlantılar.
- `crawl.py`  — bütçeli tarama: sayfa/derinlik/süre sınırı, doğrudan veri bağlantıları önce,
                anahtar sözcük ilgisi; taranıp kullanılmayan sayfalar kanıt paneline.
- `search.py` — Tavily araması; anahtar yoksa araç kayıt edilmez, agent bunu söyler.
"""

from .crawl import CrawlBudget, CrawlResult, crawl
from .fetch import ContentTooLarge, FetchResult, RobotsCache, fetch_url
from .html import PageContent, extract_page
from .search import SearchHit, TavilySearch, search_available

__all__ = [
    "CrawlBudget", "CrawlResult", "ContentTooLarge", "FetchResult", "PageContent", "RobotsCache", "SearchHit",
    "TavilySearch", "crawl", "extract_page", "fetch_url", "search_available",
]
