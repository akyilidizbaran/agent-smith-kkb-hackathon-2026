"""Search katmanı sözleşmesi — sağlayıcıdan bağımsız web arama ve sayfa çekme.

Mentör kararı (10 Eylül): Tavily, Firecrawl gibi web search/scraping servisleri
serbest; kısıt cloud warehouse'larda. Ama "search katmanını provider
bağımsız/modüler tasarlayın" — servis değişince ana yapı değişmesin.

Bu modül LLMClient ile aynı deseni izler: agent yalnız bu Protocol'ü görür;
hangi servisin arkada olduğu .env'de belirlenir. Web araçları
(web_search, web_url) bu sözleşmeye karşı yazılır, sağlayıcıya karşı değil.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class SearchHit:
    """Tek bir arama sonucu — modele gidecek kısa, kaynaklı özet."""

    title: str
    url: str
    snippet: str
    published_at: datetime | None = None
    score: float | None = None


@dataclass
class PageContent:
    """Bir URL'den çekilen içerik. Ham HTML değil, işlenebilir metin/tablo."""

    url: str
    title: str | None
    text: str                              # temizlenmiş gövde metni
    tables: list[list[list[str]]] = field(default_factory=list)  # ayıklanan tablolar
    media_type: str = "text/html"
    fetched_at: datetime = field(default_factory=datetime.now)
    truncated: bool = False


class SearchError(Exception):
    """Sağlayıcı hatası; araç bunu modele okunabilir hataya çevirir."""


@runtime_checkable
class SearchClient(Protocol):
    """Web arama sağlayıcısının karşılaması gereken arayüz."""

    def search(self, query: str, *, max_results: int = 5) -> list[SearchHit]: ...

    def fetch(self, url: str, *, max_chars: int = 20_000) -> PageContent:
        """Sayfa/dosya içeriğini çeker. PDF/görsel için OCR ayrı katmandır (vision)."""
        ...
