"""Profilleme için tablo okuma — kalıcı hiçbir şey yazmaz, yetkisiz hiçbir yere gitmez.

Bu okuma **danışma** amaçlıdır: profilci öneri üretsin diye. Kaynağın gerçek
çekilişi, ayrıştırılması, RAW/Bronze'a yazılması ve provenance'ı veri ekibinin
sertleştirilmiş yolunda (`python -m lakehouse ingest-file`) olur; buradaki
okuma o yolun yerine geçmez, ondan önce gelir.

Sınırlar aynı: yerel dosya yalnız izinli kökün altından; URL yalnız http(s),
boyut sınırı, ve erişim sonucu ADR-0028 sözleşmesiyle (`AccessOutcome`) döner —
bot engeli, giriş sayfası, 404 burada sınıflandırılır, yorumlanmaz.
"""

from __future__ import annotations

import io
import ipaddress
import socket
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import pandas as pd

from ..contracts.access import AccessOutcome
from ..core.access_policy import classify_access

MAX_BYTES_DEFAULT = 25 * 1024 * 1024


class ReadRefused(Exception):
    """Politika reddi: izinsiz kök, özel IP, boyut, biçim. Erişim sonucu değil, yerel karar."""


def _under(path: Path, roots: Iterable[Path]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(Path(root).resolve())
            return True
        except ValueError:
            continue
    return False


def _table_from_bytes(content: bytes, name: str) -> pd.DataFrame:
    """Tip çıkarımı YOK: her hücre metin. Boş hücre boş kalır, NaN olmaz."""

    suffix = Path(name.split("?")[0]).suffix.lower()
    if suffix in (".xlsx", ".xlsm"):
        return pd.read_excel(io.BytesIO(content), dtype=str, keep_default_na=False).fillna("")
    text = content.decode("utf-8-sig", errors="replace")
    if suffix == ".json":
        frame = pd.read_json(io.StringIO(text), dtype=False)
        return frame.astype(str).where(frame.notna(), "")
    sep = "\t" if suffix == ".tsv" else None  # None → sniff (',' ';' '\t' '|')
    return pd.read_csv(io.StringIO(text), sep=sep, engine="python", dtype=str, keep_default_na=False).fillna("")


def _private_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def read_bytes_for_profiling(
    locator: str,
    *,
    allowed_roots: Iterable[Path],
    max_bytes: int = MAX_BYTES_DEFAULT,
    session: Any = None,
    environ: dict[str, str] | None = None,
) -> tuple[bytes | None, str, AccessOutcome]:
    """(içerik, medya türü, erişim sonucu) — tablo dosyası da PDF/görsel de aynı kurallarla okunur."""

    parsed = urlparse(locator)
    if parsed.scheme in ("http", "https"):
        if _private_host(parsed.hostname or ""):
            raise ReadRefused("özel/loopback adreslere erişim yok")
        if session is None:
            from ..web.session import default_session
            session = default_session()
        try:
            resp = session.get(locator, timeout=30, allow_redirects=True, stream=True)
        except Exception:  # noqa: BLE001
            return None, "", classify_access(locator, http_status=None, environ=environ)
        chunks, size = [], 0
        for chunk in resp.iter_content(65536):
            size += len(chunk)
            if size > max_bytes:
                resp.close()
                raise ReadRefused(f"kaynak {max_bytes} bayt sınırını aşıyor")
            chunks.append(chunk)
        content = b"".join(chunks)
        outcome = classify_access(
            locator, http_status=resp.status_code, final_url=getattr(resp, "url", None),
            body_excerpt=content[:4096].decode("utf-8", errors="ignore"), environ=environ,
        )
        headers = getattr(resp, "headers", {}) or {}
        media = str(headers.get("Content-Type") or headers.get("content-type") or "").split(";")[0].strip().lower()
        return (content if outcome.ok else None), media, outcome
    if parsed.scheme not in ("", "file"):
        raise ReadRefused(f"desteklenmeyen şema: {parsed.scheme}")
    path = Path(parsed.path if parsed.scheme == "file" else locator)
    if not _under(path, allowed_roots):
        raise ReadRefused(f"'{path}' izinli kökün altında değil")
    if not path.is_file():
        return None, "", classify_access(str(path), http_status=404, environ=environ)
    if path.stat().st_size > max_bytes:
        raise ReadRefused(f"dosya {max_bytes} bayt sınırını aşıyor")
    return path.read_bytes(), "", classify_access(str(path), http_status=200, environ=environ)


def read_table_for_profiling(
    locator: str,
    *,
    allowed_roots: Iterable[Path],
    max_bytes: int = MAX_BYTES_DEFAULT,
    session: Any = None,
    environ: dict[str, str] | None = None,
) -> tuple[pd.DataFrame | None, AccessOutcome]:
    """(tablo, erişim sonucu). Tablo yalnız `outcome.ok` iken dolu."""

    parsed = urlparse(locator)
    if parsed.scheme in ("http", "https"):
        if _private_host(parsed.hostname or ""):
            raise ReadRefused("özel/loopback adreslere erişim yok")
        if session is None:
            from ..web.session import default_session
            session = default_session()
        try:
            resp = session.get(locator, timeout=30, allow_redirects=True, stream=True)
        except Exception as exc:  # noqa: BLE001 — DNS/TLS/timeout → unreachable
            return None, classify_access(locator, http_status=None, environ=environ)
        chunks, size = [], 0
        for chunk in resp.iter_content(65536):
            size += len(chunk)
            if size > max_bytes:
                resp.close()
                raise ReadRefused(f"kaynak {max_bytes} bayt sınırını aşıyor")
            chunks.append(chunk)
        content = b"".join(chunks)
        outcome = classify_access(
            locator, http_status=resp.status_code, final_url=getattr(resp, "url", None),
            body_excerpt=content[:4096].decode("utf-8", errors="ignore"), environ=environ,
        )
        if not outcome.ok:
            return None, outcome
        return _table_from_bytes(content, parsed.path or locator), outcome

    if parsed.scheme not in ("", "file"):
        raise ReadRefused(f"desteklenmeyen şema: {parsed.scheme}")
    path = Path(parsed.path if parsed.scheme == "file" else locator)
    if not _under(path, allowed_roots):
        raise ReadRefused(f"'{path}' izinli kökün altında değil")
    if not path.is_file():
        return None, classify_access(str(path), http_status=404, environ=environ)
    if path.stat().st_size > max_bytes:
        raise ReadRefused(f"dosya {max_bytes} bayt sınırını aşıyor")
    frame = _table_from_bytes(path.read_bytes(), path.name)
    return frame, classify_access(str(path), http_status=200, environ=environ)


__all__ = ["MAX_BYTES_DEFAULT", "ReadRefused", "read_bytes_for_profiling", "read_table_for_profiling"]
