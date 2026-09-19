"""Generic web routing signals. Public-source configuration stays outside the harness."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..source_hints import load_source_hints
from .access_policy import detect_source_constraint

_ADDRESS = re.compile(
    r"https?://[^\s<>\"'()]+|(?<![\w/@])(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>\"'()]*)?",
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
    r"internete?\s+(?:gitme|çıkma)|web\w*\s+(?:arama(?!\w|\s+yap)|kullanma\b)|yalnızca\s+(?:veri tabanı|veritabanı|database|DB)|sadece\s+(?:veri tabanı|veritabanı|database|DB)",
    re.IGNORECASE,
)


def addresses(question: str) -> list[str]:
    # File names are not domains. User-provided spelling is retained; no institution aliases are guessed.
    return [
        m.group(0).rstrip(".,;:")
        for m in _ADDRESS.finditer(question or "")
        if not re.match(r"\s*\(", (question or "")[m.end():])
        and (not m.group(0).lower().endswith((".pdf", ".csv", ".xlsx", ".png", ".jpg"))
        or "/" in m.group(0))
    ]


def host_of(url: str) -> str:
    return (
        (urlparse(url if "://" in url else "https://" + url).hostname or "")
        .lower()
        .removeprefix("www.")
    )


def within_domains(url: str, domains: list[str]) -> bool:
    host = host_of(url)
    return bool(host) and any(host == d or host.endswith("." + d) for d in domains)


def source_domains(question: str) -> list[str]:
    urls = addresses(question)
    if urls:
        return list(dict.fromkeys(host_of(u) for u in urls))
    constraint = detect_source_constraint(question)
    mapping = load_source_hints().get("institution_hosts", {})
    return (
        list(mapping.get((constraint.source_ref or "").casefold(), ())) if constraint.pinned else []
    )


def discovery_requested(question: str) -> bool:
    return any(
        urlparse(u if "://" in u else "https://" + u).path in ("", "/") for u in addresses(question)
    ) or bool(source_domains(question) and not addresses(question)
              and re.search(r"site(?:sinden|sinde|si)?\b|sayfa|domain", question, re.IGNORECASE))


def web_requested(question: str) -> bool:
    return not web_forbidden(question) and bool(
        _WEB_REQUEST.search(question) or addresses(question) or discovery_requested(question)
    )


def web_forbidden(question: str) -> bool:
    return bool(_NO_WEB.search(question or ""))


def public_db_fallback(question: str, sources: list[str] | None = None) -> bool:
    """Trusted source identities, never words in a user question, establish public origin."""
    if web_forbidden(question) or _PRIVATE.search(question):
        return False
    public = load_source_hints().get("public_source_domains", {})
    return bool(sources) and all(s.casefold() in public for s in sources)


def public_fallback_plan(question: str, provenance: object, lakehouse: object) -> dict | None:
    """Build a bounded public query from catalog metadata; no SQL, rows or raw user text."""
    ids = getattr(provenance, "dataset_ids", []) or []
    if not ids or web_forbidden(question) or _PRIVATE.search(question):
        return None
    try:
        specs = [lakehouse.get_dataset(i) for i in ids]
    except Exception:  # noqa: BLE001 — unknown/unavailable catalog fails closed
        return None
    sources = [spec.source for spec in specs]
    if not public_db_fallback(question, sources):
        return None
    hints = load_source_hints()
    domains = list(dict.fromkeys(d for s in sources for d in hints["public_source_domains"][s.casefold()]))
    pin = source_domains(question)
    if pin:
        domains = [d for d in domains if within_domains("https://" + d, pin)]
    if not domains:
        return None
    # Only bounded calendar identifiers are taken from the user request.
    years = re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", question)
    query = " ".join(dict.fromkeys([*(spec.name for spec in specs), *years]))[:500]
    return {"query": query, "include_domains": domains}
