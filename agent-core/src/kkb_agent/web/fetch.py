"""Tek sayfa çekme — erişim sözleşmesi (ADR-0028) ve sınırlar burada, yorum yok.

Mentörün çizgisi kod olarak: bot denetimi ve CAPTCHA aşılmaz (sınıflandırılır ve
söylenir), robots.txt'ye uyulur, kimlik bilgisi yalnız ortam değişkeninden aranır ve
değeri hiç görülmez. Özel/loopback adreslere gidilmez (SSRF); yerel dosya yalnız izinli
kökten. Her çekim sha256 ve zaman damgası taşır: kanıt paneli buna iner.
"""

from __future__ import annotations

import hashlib
import time
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse, urlunparse

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
    """Ortak adres kuralı (M05-T03): `web.addresses.blocked_host`; lakehouse bağlayıcısıyla aynı vakalar."""
    from .addresses import blocked_host
    return blocked_host(host) is not None

MAX_REDIRECTS = 5
ROBOTS_MAX_BYTES = 512 * 1024


class RedirectRefused(FetchRefused):
    """Yönlendirme hedefi güven sınırının dışında (özel adres, şema, döngü, sekme sayısı)."""


def _check_target(url: str, *, allow_private: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise RedirectRefused(f"desteklenmeyen şema: {parsed.scheme or '—'}")
    if not allow_private and private_host(parsed.hostname or ""):
        raise RedirectRefused("özel/loopback adreslere erişim yok")


def guarded_get(session: Any, url: str, *, timeout: float, allow_private: bool = False,
                robots: "RobotsCache | None" = None, stream: bool = True,
                headers: Mapping[str, str] | None = None, max_redirects: int = MAX_REDIRECTS,
                deadline: float | None = None) -> tuple[Any, str]:
    """Yönlendirmeleri KENDİ takip eder: her hedef istekten ÖNCE doğrulanır (M05, ADR-0051).

    İlk host izinli olsa bile `Location` özel adrese gidebilir; kütüphanenin otomatik takibi bunu
    görmez. Döngü, sekme sınırı, şema ve toplam süre de burada. Kimlik bilgisi taşımıyoruz
    (yalnız User-Agent/Accept), yine de başlıklar başka hosta olduğu gibi gitmez.
    Döner: (yanıt, son_url). Kütüphane takibi kapalı (allow_redirects=False).
    """
    base_headers = dict(headers or {})
    current, visited = url, [url]
    for _hop in range(max_redirects + 1):
        _check_target(current, allow_private=allow_private)
        if robots is not None and current != url and not robots.allowed(current, session):
            raise RedirectRefused(f"yönlendirme hedefi robots.txt ile kapalı: {current}")
        if deadline is not None and time.monotonic() > deadline:
            raise FetchRefused("toplam süre sınırı aşıldı (yönlendirmeler dâhil)")
        hop_headers = base_headers if same_domain(current, url) else {k: v for k, v in base_headers.items() if k.lower() in ("user-agent", "accept")}
        resp = session.get(current, timeout=timeout, allow_redirects=False, stream=stream, headers=hop_headers)
        status = getattr(resp, "status_code", None)
        location = (getattr(resp, "headers", {}) or {}).get("Location") or (getattr(resp, "headers", {}) or {}).get("location")
        if status in (301, 302, 303, 307, 308) and location:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
            nxt = urljoin(current, location)
            if nxt in visited:
                raise RedirectRefused(f"yönlendirme döngüsü: {nxt}")
            visited.append(nxt)
            current = nxt
            continue
        return resp, current
    raise RedirectRefused(f"{max_redirects} yönlendirmeden sonra hedefe varılamadı")


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
                # Aynı güven sınırı: robots yönlendirmesi de özel adrese gidemez; boyut sınırlı (M05-T02).
                resp, _final = guarded_get(session, f"{host}/robots.txt", timeout=10, robots=None, stream=False,
                                           headers={"User-Agent": self.user_agent})
                status = getattr(resp, "status_code", None)
                if status == 200:
                    raw = resp.content if isinstance(resp.content, bytes) else str(resp.content).encode()
                    text = raw[:ROBOTS_MAX_BYTES].decode("utf-8", errors="ignore")
                    parser.parse(text.splitlines())
                    self._parsers[host] = parser
                else:
                    self._parsers[host] = None  # robots yok → izinli
            except RedirectRefused:
                self._parsers[host] = None      # robots'a güvenli ulaşılamadı → izinli sayılır, kaydedilir
                self.unreachable_hosts.add(host)
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
            ".webp": "image/webp", ".xml": "application/xml"}.get(suffix, "application/octet-stream")


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
        resp, final_url = guarded_get(
            session, url, timeout=timeout, allow_private=allow_private, robots=robots, stream=True,
            headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,text/csv,*/*"},
            deadline=time.monotonic() + max(timeout, 1.0) * 3,
        )
    except FetchRefused:
        raise                       # yönlendirme sınırı: ağ isteği yapılmadan ret, sebep kullanıcıya
    except Exception:  # noqa: BLE001 — DNS/TLS/timeout → unreachable
        return FetchResult(url=url, final_url=None, http_status=None, media_type="", content=b"", sha256="",
                           fetched_at=now, outcome=classify_access(url, http_status=None, environ=environ),
                           elapsed_ms=(time.perf_counter() - started) * 1000)
    chunks: list[bytes] = []
    size = 0
    try:
        for chunk in resp.iter_content(65536):
            size += len(chunk)
            if size > max_bytes:
                raise FetchRefused(f"kaynak {max_bytes} bayt sınırını aşıyor")
            chunks.append(chunk)
    except FetchRefused:
        resp.close()
        raise
    except Exception:  # noqa: BLE001 — yarım indirme: bağlantı kapanır, açık cevap (M05-T04)
        try:
            resp.close()
        finally:
            return FetchResult(url=url, final_url=final_url, http_status=getattr(resp, "status_code", None), media_type="",
                               content=b"", sha256="", fetched_at=now,
                               outcome=classify_access(url, http_status=None, environ=environ),
                               elapsed_ms=(time.perf_counter() - started) * 1000)
    content = b"".join(chunks)
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


__all__ = ["DATA_SUFFIXES", "FetchRefused", "FetchResult", "RedirectRefused", "RobotsCache", "USER_AGENT", "guarded_get",
           "canonical", "fetch_url", "private_host", "same_domain"]
