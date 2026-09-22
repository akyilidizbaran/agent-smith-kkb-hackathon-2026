"""Web niyeti, domain sınırı ve doğrulanmış yokluk fallback planı.

Kurum ve kaynak adları ``source_hints.json`` yapılandırmasında kalır. Bu modül yalnızca
güvenli bir plan kurar; fetch yapmaz, model çağırmaz ve kullanıcı metnini arama sorgusuna
taşımaz.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..source_hints import load_source_hints
from .access_policy import detect_source_constraint
from .lexical import fold

# A bare domain needs a known top-level label: `[a-z]{2,}` accepted Turkish
# ordinal suffixes such as "5.sayfadaki" as a host name.
_TLD = (
    r"(?:com|org|net|gov|edu|int|mil|info|biz|io|co|eu|tr|de|uk|fr|us|nl|ch|at|it|es|be|se|no|dk|fi|"
    r"pl|cz|ru|jp|cn|kr|in|br|ca|au|nz|za|ae|sa|az|kz|ua|gr|pt|ie|hu|ro|bg|hr|rs|ba|mk|al|me|cy|mt|"
    r"lu|li|is|ee|lv|lt|sk|si|ai|app|dev|xyz|online|cloud|news|tv|example)"
)
_ADDRESS = re.compile(
    r"https?://[^\s<>\"'()]+|(?<![\w/@])(?:[a-z0-9-]+\.)+" + _TLD + r"(?![\wçğıöşü])(?:/[^\s<>\"'()]*)?",
    re.IGNORECASE,
)
_WEB_REQUEST = re.compile(
    r"internet|web(?:den|de|ten)?\b|çevrimiçi|online|araştır|research|search", re.IGNORECASE
)
_PRIVATE = re.compile(
    r"müşteri|hesap numara|kurum içi|şirket içi|internal|private|confidential|gizli|kişisel|personel",
    re.IGNORECASE,
)
_NO_WEB = re.compile(
    r"\binternete?\s+(?:gitme|çıkma)\b|"
    r"\binternet(?:i|te|ten)?\s+(?:kullanma|arama\s+yapma|arama(?:sı)?\s+yapma)\b|"
    r"\bweb\w*\s+(?:kullanma|arama(?:sı)?\s+yapma)\b|"
    r"\b(?:yalnızca|sadece)\s+(?:veri\s*tabanı|veritabanı|database|db)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_SQL_OR_CODE = re.compile(r"\b(?:select|from|where|join|union|insert|update|delete|drop|create|alter|pragma)\b", re.I)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_WORDS = re.compile(r"[a-zçğıöşü]+", re.I)
_QUERY_STOP = frozenset({
    "getir", "getirsin", "bul", "ara", "araştır", "arastir", "internetten", "internet",
    "web", "veri", "verileri", "verisini", "kaynak", "kaynağından", "kaynaklar",
    "lütfen", "lutfen", "için", "icin", "olan", "bana", "göster", "goster",
    "tablo", "tablosu", "hangi", "nedir", "yılında", "yillari", "döneminde", "doneminde",
})


def addresses(question: str) -> list[str]:
    """Return URL/domain references while ignoring bare file names."""

    text = question or ""
    return [
        match.group(0).rstrip(".,;:")
        for match in _ADDRESS.finditer(text)
        if not re.match(r"\s*\(", text[match.end():])
        and (
            not match.group(0).lower().endswith((".pdf", ".csv", ".xlsx", ".png", ".jpg"))
            or "/" in match.group(0)
        )
    ]


def host_of(url: str) -> str:
    parsed = urlparse(url if "://" in url else "https://" + url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return host.removeprefix("www.")


def within_domains(url: str, domains: list[str] | tuple[str, ...]) -> bool:
    """Match a host or its subdomains without accepting suffix lookalikes."""

    host = host_of(url)
    normalized = [host_of(domain) for domain in domains if host_of(domain)]
    return bool(host) and any(host == domain or host.endswith("." + domain) for domain in normalized)


def source_domains(question: str) -> list[str]:
    """Resolve explicit URL pins first, then configured institution pins."""

    urls = addresses(question)
    if urls:
        return list(dict.fromkeys(host for url in urls if (host := host_of(url))))
    constraint = detect_source_constraint(question)
    if not constraint.pinned or not constraint.source_ref:
        return []
    mapping = load_source_hints().get("institution_hosts", {})
    # Keys are casefolded at load time, but "Tüik"/"Bist" and "TÜİK"/"BİST"
    # casefold differently (dotted İ); fold both sides to ASCII instead.
    wanted = fold(constraint.source_ref)
    return list(next((hosts for name, hosts in mapping.items() if fold(name) == wanted), ()))


def web_forbidden(question: str) -> bool:
    return bool(_NO_WEB.search(question or ""))


def discovery_requested(question: str) -> bool:
    urls = addresses(question)
    if any(urlparse(url if "://" in url else "https://" + url).path in ("", "/") for url in urls):
        return True
    return bool(
        source_domains(question)
        and not urls
        and re.search(r"site(?:sinden|sinde|si)?\b|sayfa|domain", question, re.IGNORECASE)
    )


def web_requested(question: str) -> bool:
    return not web_forbidden(question) and bool(
        _WEB_REQUEST.search(question or "") or addresses(question) or discovery_requested(question)
    )


def public_db_fallback(question: str, sources: list[str] | tuple[str, ...] | None = None) -> bool:
    """Trust catalog source IDs, not claims in user text, when deciding public fallback."""

    if web_forbidden(question) or _PRIVATE.search(question or "") or not sources:
        return False
    configured = load_source_hints().get("public_source_domains", {})
    return all(str(source).casefold() in configured for source in sources)


def _safe_search_terms(value: str | None) -> list[str]:
    """Keep a short topical query; reject obvious private/SQL-shaped text."""

    text = value or ""
    if not text or _PRIVATE.search(text) or _SQL_OR_CODE.search(text) or _EMAIL.search(text):
        return []
    words = [word.casefold() for word in _WORDS.findall(text)]
    return list(dict.fromkeys(word for word in words if len(word) > 2 and word not in _QUERY_STOP))[:8]


def _source_ids_for_pins(
    pinned_domains: list[str], public_domains: dict[str, tuple[str, ...] | list[str]]
) -> list[str]:
    return [
        source for source, domains in public_domains.items()
        if any(within_domains("https://" + pinned, domains) for pinned in pinned_domains)
    ]


def catalog_ids_in_sql(sql: str, lakehouse: object) -> list[str]:
    """Resolve only exact catalog IDs present in a validated query to metadata."""

    list_datasets = getattr(lakehouse, "list_datasets", None)
    if not callable(list_datasets) or not sql:
        return []
    try:
        specs = list(list_datasets())
    except Exception:  # noqa: BLE001 — failed metadata lookup must disable fallback
        return []
    found = []
    for spec in specs:
        dataset_id = str(getattr(spec, "dataset_id", "") or "")
        if dataset_id and re.search(r"(?<![\w])" + re.escape(dataset_id) + r"(?![\w])", sql, re.I):
            found.append(dataset_id)
    return found


def public_fallback_plan(
    question: str,
    provenance: object | None,
    lakehouse: object,
    *,
    search_terms: str | None = None,
) -> dict[str, list[str] | str] | None:
    """Build a bounded query from catalog metadata and an explicit safe topic.

    When no local dataset matched, fallback is allowed only if the user explicitly
    pinned a configured public source. The raw user question and SQL are never copied.
    """

    dataset_ids = getattr(provenance, "dataset_ids", None) or []
    if web_forbidden(question) or _PRIVATE.search(question or ""):
        return None
    specs = []
    if dataset_ids:
        get_dataset = getattr(lakehouse, "get_dataset", None)
        if not callable(get_dataset):
            return None
        try:
            specs = [get_dataset(dataset_id) for dataset_id in dataset_ids]
        except Exception:  # noqa: BLE001 — missing/unknown catalog metadata fails closed
            return None
        if not specs:
            return None
    sources = [str(getattr(spec, "source", "")) for spec in specs]
    pinned_domains = source_domains(question)
    if not sources:
        if not pinned_domains:
            return None
        configured_domains = load_source_hints().get("public_source_domains", {})
        sources = _source_ids_for_pins(pinned_domains, configured_domains)
        if not sources:
            return None
    if not public_db_fallback(question, sources):
        return None

    public_domains = load_source_hints().get("public_source_domains", {})
    domains = list(dict.fromkeys(
        domain for source in sources for domain in public_domains[source.casefold()]
    ))
    if pinned_domains:
        # Preserve a URL's exact host pin; institution-name pins can map to all
        # configured official hosts for that institution.
        if any(within_domains("https://" + pinned, domains) for pinned in pinned_domains):
            domains = [pinned for pinned in pinned_domains if within_domains("https://" + pinned, domains)]
        else:
            domains = [domain for domain in domains if within_domains("https://" + domain, pinned_domains)]
    if not domains:
        return None

    years = _YEAR.findall(question or "")
    names = [str(getattr(spec, "name", "")).strip() for spec in specs]
    topic_terms = _safe_search_terms(search_terms) if not names else []
    if not names and (not search_terms or not topic_terms):
        return None
    constraint = detect_source_constraint(question)
    source_label = str(constraint.source_ref or "").strip()
    if source_label.startswith(("http://", "https://")):
        source_label = host_of(source_label)
    labels = [source_label] if not names and source_label else []
    parts = list(dict.fromkeys(part for part in (*names, *labels, *topic_terms, *years) if part))
    query = " ".join(parts)[:500]
    if not query:
        return None
    return {"query": query, "include_domains": domains, "topic": "finance", "max_results": 5}


__all__ = [
    "addresses",
    "catalog_ids_in_sql",
    "discovery_requested",
    "host_of",
    "public_db_fallback",
    "public_fallback_plan",
    "source_domains",
    "web_forbidden",
    "web_requested",
    "within_domains",
]
