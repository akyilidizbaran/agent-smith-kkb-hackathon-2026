"""Tek sayfa çekme — erişim sözleşmesi (ADR-0028) ve sınırlar burada, yorum yok.

Mentörün çizgisi kod olarak: bot denetimi ve CAPTCHA aşılmaz (sınıflandırılır ve
söylenir), robots.txt'ye uyulur, kimlik bilgisi yalnız ortam değişkeninden aranır ve
değeri hiç görülmez. Özel/loopback adreslere gidilmez (SSRF); yerel dosya yalnız izinli
kökten. Her çekim sha256 ve zaman damgası taşır: kanıt paneli buna iner.
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse, urlunparse

from ..contracts.access import AccessOutcome
from ..core.access_policy import classify_access

USER_AGENT = "kkb-agent/0.1 (KKB Hackathon 2026; robots.txt'ye uyar)"
MAX_BYTES_DEFAULT = 8 * 1024 * 1024
DATA_SUFFIXES = (".csv", ".tsv", ".xlsx", ".xls", ".json")


class FetchRefused(Exception):
    """Politika reddi: özel adres, izinsiz kök, şema, boyut. Erişim sonucu değil, yerel karar."""


@dataclass(frozen=True)
class FetchResult:
    url: str
    final_url: str | None
    http_status: int | None
    media_type: str
    content: bytes
    sha256: str
    fetched_at: datetime
    outcome: AccessOutcome
    elapsed_ms: float = 0.0
    from_local_file: bool = False

    @property
    def ok(self) -> bool:
        return self.outcome.ok

    @property
    def is_data_file(self) -> bool:
        path = urlparse(self.final_url or self.url).path.lower()
        return path.endswith(DATA_SUFFIXES) or self.media_type.split(";")[0].strip() in (
            "text/csv", "application/json", "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def private_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def _under(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


class RobotsCache:
    """Host başına robots.txt; bir kez çekilir. Ulaşılamayan robots → izin var sayılır
    (standart davranış), ama `unreachable_hosts`'a yazılır ki kanıt panelinde görünsün."""

    def __init__(self, *, user_agent: str = USER_AGENT) -> None:
        self.user_agent = user_agent
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.unreachable_hosts: set[str] = set()

    def allowed(self, url: str, session: Any) -> bool:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host not in self._parsers:
            parser = urllib.robotparser.RobotFileParser()
            try:
                resp = session.get(f"{host}/robots.txt", timeout=10, allow_redirects=True, headers={"User-Agent": self.user_agent})
                status = getattr(resp, "status_code", None)
                if status == 200:
                    text = resp.content.decode("utf-8", errors="ignore") if isinstance(resp.content, bytes) else str(resp.content)
                    parser.parse(text.splitlines())
                    self._parsers[host] = parser
                else:
                    self._parsers[host] = None  # robots yok → izinli
            except Exception:  # noqa: BLE001
                self.unreachable_hosts.add(host)
                self._parsers[host] = None
        parser = self._parsers[host]
        return True if parser is None else parser.can_fetch(self.user_agent, url)


def _media_type(resp: Any, url: str) -> str:
    headers = getattr(resp, "headers", {}) or {}
    ctype = str(headers.get("Content-Type") or headers.get("content-type") or "")
    if ctype:
        return ctype.split(";")[0].strip().lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    return {".csv": "text/csv", ".json": "application/json", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls": "application/vnd.ms-excel", ".html": "text/html", ".htm": "text/html",
            ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp"}.get(suffix, "application/octet-stream")


def fetch_url(
    url: str,
    *,
    session: Any = None,
    robots: RobotsCache | None = None,
    allowed_local_roots: Iterable[Path] = (),
    max_bytes: int = MAX_BYTES_DEFAULT,
    timeout: float = 30.0,
    environ: Mapping[str, str] | None = None,
    allow_private: bool = False,
) -> FetchResult:
    """Bir URL'yi (http/https) ya da izinli kökteki yerel dosyayı çeker; sonucu sınıflandırır."""

    started = time.perf_counter()
    parsed = urlparse(url)
    now = datetime.now(timezone.utc)

    if parsed.scheme in ("", "file"):
        path = Path(parsed.path if parsed.scheme == "file" else url)
        if not _under(path, allowed_local_roots):
            raise FetchRefused(f"'{path}' izinli kökün altında değil")
        if not path.is_file():
            outcome = classify_access(str(path), http_status=404, environ=environ)
            return FetchResult(url=url, final_url=None, http_status=404, media_type="", content=b"",
                               sha256="", fetched_at=now, outcome=outcome, from_local_file=True)
        if path.stat().st_size > max_bytes:
            raise FetchRefused(f"dosya {max_bytes} bayt sınırını aşıyor")
        content = path.read_bytes()
        return FetchResult(
            url=url, final_url=str(path), http_status=200, media_type=_media_type(None, str(path)),
            content=content, sha256=hashlib.sha256(content).hexdigest(), fetched_at=now,
            outcome=classify_access(str(path), http_status=200, environ=environ),
            elapsed_ms=(time.perf_counter() - started) * 1000, from_local_file=True,
        )

    if parsed.scheme not in ("http", "https"):
        raise FetchRefused(f"desteklenmeyen şema: {parsed.scheme}")
    if not allow_private and private_host(parsed.hostname or ""):
        raise FetchRefused("özel/loopback adreslere erişim yok")
    if session is None:
        from .session import default_session
        session = default_session()

    if robots is not None and not robots.allowed(url, session):
        outcome = classify_access(url, http_status=None, robots_disallow=True, environ=environ)
        return FetchResult(url=url, final_url=None, http_status=None, media_type="", content=b"",
                           sha256="", fetched_at=now, outcome=outcome)
    try:
        resp = session.get(url, timeout=timeout, allow_redirects=True, stream=True,
                           headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,text/csv,*/*"})
    except Exception:  # noqa: BLE001 — DNS/TLS/timeout → unreachable
        return FetchResult(url=url, final_url=None, http_status=None, media_type="", content=b"", sha256="",
                           fetched_at=now, outcome=classify_access(url, http_status=None, environ=environ),
                           elapsed_ms=(time.perf_counter() - started) * 1000)
    chunks: list[bytes] = []
    size = 0
    for chunk in resp.iter_content(65536):
        size += len(chunk)
        if size > max_bytes:
            try:
                resp.close()
            finally:
                raise FetchRefused(f"kaynak {max_bytes} bayt sınırını aşıyor")
        chunks.append(chunk)
    content = b"".join(chunks)
    final_url = getattr(resp, "url", None)
    outcome = classify_access(
        url, http_status=resp.status_code, final_url=final_url,
        body_excerpt=content[:4096].decode("utf-8", errors="ignore"), environ=environ,
    )
    return FetchResult(
        url=url, final_url=final_url, http_status=resp.status_code, media_type=_media_type(resp, final_url or url),
        content=content, sha256=hashlib.sha256(content).hexdigest(), fetched_at=now, outcome=outcome,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


def same_domain(a: str, b: str) -> bool:
    ha, hb = (urlparse(a).hostname or "").lower(), (urlparse(b).hostname or "").lower()
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def canonical(url: str) -> str:
    p = urlparse(url)
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path or "/", "", p.query, ""))


__all__ = ["DATA_SUFFIXES", "FetchRefused", "FetchResult", "RobotsCache", "USER_AGENT",
           "canonical", "fetch_url", "private_host", "same_domain"]
