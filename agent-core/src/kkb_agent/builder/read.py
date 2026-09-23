"""Profilleme için tablo okuma — kalıcı hiçbir şey yazmaz, yetkisiz hiçbir yere gitmez.

Bu okuma **danışma** amaçlıdır: profilci öneri üretsin diye. Kaynağın gerçek
çekimi, ayrıştırılması, RAW/Bronze'a yazılması ve provenance'ı veri ekibinin
sertleştirilmiş yolunda (`python -m lakehouse ingest-file`) olur; buradaki
okuma o yolun yerine geçmez, ondan önce gelir.

Sınırlar aynı: yerel dosya yalnız izinli kökün altından; URL yalnız http(s),
boyut sınırı, ve erişim sonucu ADR-0028 sözleşmesiyle (`AccessOutcome`) döner —
bot engeli, giriş sayfası, 404 burada sınıflandırılır, yorumlanmaz.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import pandas as pd

_NUMERIC_CELL = re.compile(r"^[\s]*[-+]?[\d.,\s]*\d[\d.,\s]*%?[\s]*$")


def _field_count(line: str, delim: str) -> int:
    try:
        return len(next(csv.reader([line], delimiter=delim)))
    except Exception:  # noqa: BLE001 — bozuk satır: kaba bölmeye düş
        return len(line.split(delim))


def _numeric_fraction(line: str, delim: str) -> float:
    try:
        cells = next(csv.reader([line], delimiter=delim))
    except Exception:  # noqa: BLE001
        cells = line.split(delim)
    cells = [c for c in cells if c.strip()]
    if not cells:
        return 0.0
    return sum(1 for c in cells if _NUMERIC_CELL.match(c)) / len(cells)


def _detect_delimiter_and_header(lines: list[str]) -> tuple[str, int, list[int]] | None:
    """Ayraç + başlık satırı + veri satırlarını keşfet (kaynak-bağımsız, preamble'a dayanıklı).

    Ayraç adayları öncelik sırasıyla denenir (';' TR Excel'inde yaygın çünkü ',' ondalıktır).
    En yüksek KAPSAM (aynı alan sayısına sahip satır oranı) veren ≥2 kolonlu ayraç seçilir; başlık,
    modal alan sayısına sahip ve çoğunlukla METİN (sayısal değil) olan ilk satırdır — üstündeki
    farklı-alanlı satırlar (metadata/preamble) atılır, altındaki tutarsız satırlar (Toplam/not) düşer.
    """
    idx = [i for i, l in enumerate(lines) if l.strip()]
    if not idx:
        return None
    best: tuple[tuple, str, int, dict[int, int]] | None = None
    for rank, delim in enumerate((";", "\t", "|", ",")):
        counts = {i: _field_count(lines[i], delim) for i in idx}
        modal_pool = Counter(n for n in counts.values() if n >= 2)
        if not modal_pool:
            continue
        modal, hits = modal_pool.most_common(1)[0]
        coverage = hits / len(idx)
        score = (round(coverage, 3), modal, -rank)   # yüksek kapsam > çok kolon > öncelikli ayraç
        if best is None or score > best[0]:
            best = (score, delim, modal, counts)
    if best is None:
        return None
    _, delim, modal, counts = best
    modal_lines = [i for i in idx if counts[i] == modal]
    header_i = next((i for i in modal_lines if _numeric_fraction(lines[i], delim) < 0.5), modal_lines[0])
    body = [i for i in modal_lines if i > header_i]
    return delim, header_i, body

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


def excel_sheets(content: bytes) -> list[str]:
    """XLSX sayfa adları (M10-T05): birden çok sayfa varsa kullanıcı/model seçer, sessizce ilki alınmaz."""
    with pd.ExcelFile(io.BytesIO(content)) as xf:
        return [str(n) for n in xf.sheet_names]


def _table_from_bytes(content: bytes, name: str, *, sheet: str | int | None = None) -> pd.DataFrame:
    """Tip çıkarımı YOK: her hücre metin. Boş hücre boş kalır, NaN olmaz.

    XLSX: `sheet` ad ya da 0-tabanlı indeks; verilmemişse ve birden çok sayfa varsa ReadRefused ile
    sayfa listesi döner (belirsizlik sorulur). Legacy .xls desteklenmez (xlrd yok) — açıkça söylenir.
    """
    suffix = Path(name.split("?")[0]).suffix.lower()
    if suffix == ".xls":
        raise ReadRefused("eski Excel (.xls) desteklenmiyor; dosyayı .xlsx olarak kaydedin")
    if suffix in (".xlsx", ".xlsm"):
        names = excel_sheets(content)
        if sheet is None and len(names) > 1:
            raise ReadRefused("Excel dosyasında birden çok sayfa var: " + ", ".join(names) + " — `sheet` ile birini seç")
        target: str | int = 0 if sheet is None else sheet
        if isinstance(target, str) and target.isdigit():
            target = int(target)
        if isinstance(target, str) and target not in names:
            raise ReadRefused(f"sayfa '{target}' yok; sayfalar: {', '.join(names)}")
        if isinstance(target, int) and not (0 <= target < len(names)):
            raise ReadRefused(f"sayfa indeksi {target} yok; {len(names)} sayfa var")
        frame = pd.read_excel(io.BytesIO(content), sheet_name=target, dtype=str, keep_default_na=False, engine="openpyxl")
        return frame.fillna("")
    text = content.decode("utf-8-sig", errors="replace")
    if suffix == ".json":
        frame = pd.read_json(io.StringIO(text), dtype=False)
        return frame.astype(str).where(frame.notna(), "")
    # Başlık/preamble keşfi + sağlam ayraç seçimi (aşağı yönlü sayı çevirimi profile.py'de yapılır).
    lines = text.splitlines()
    if suffix == ".tsv":
        detected: tuple[str, int, list[int]] | None = None
        idx = [i for i, l in enumerate(lines) if l.strip()]
        if idx:
            counts = {i: _field_count(lines[i], "\t") for i in idx}
            modal = Counter(n for n in counts.values() if n >= 1).most_common(1)[0][0]
            modal_lines = [i for i in idx if counts[i] == modal]
            header_i = next((i for i in modal_lines if _numeric_fraction(lines[i], "\t") < 0.5), modal_lines[0])
            detected = ("\t", header_i, [i for i in modal_lines if i > header_i])
    else:
        detected = _detect_delimiter_and_header(lines)
    if detected is None:  # tek kolon / boş: pandas'ın kendi çıkarımına bırak (eski davranış)
        return pd.read_csv(io.StringIO(text), sep="\t" if suffix == ".tsv" else None,
                           engine="python", dtype=str, keep_default_na=False).fillna("")
    delim, header_i, body = detected
    kept = "\n".join(lines[i] for i in (header_i, *body))
    return pd.read_csv(io.StringIO(kept), sep=delim, engine="python", dtype=str,
                       keep_default_na=False).fillna("")


def _private_host(host: str) -> bool:
    """Web getirmeyle aynı kural (M05-T03); `web.addresses` paket içinden import etmez, döngü yok."""
    from ..web.addresses import blocked_host
    return blocked_host(host) is not None


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
    if len(parsed.scheme) == 1:
        # Windows sürücü harfi: urlparse("C:\\veri\\x.csv").scheme == "c" — şema değil yerel yol (Büşra'nın notu, 13 Eyl)
        parsed = urlparse("")
    if parsed.scheme in ("http", "https"):
        if _private_host(parsed.hostname or ""):
            raise ReadRefused("özel/loopback adreslere erişim yok")
        if session is None:
            from ..web.session import default_session
            session = default_session()
        from ..web.fetch import FetchRefused, guarded_get   # döngüsel import: web.html → builder.read
        try:
            resp, _final = guarded_get(session, locator, timeout=30, stream=True)
        except FetchRefused as exc:
            raise ReadRefused(str(exc)) from exc
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
    sheet: str | int | None = None,
) -> tuple[pd.DataFrame | None, AccessOutcome]:
    """(tablo, erişim sonucu). Tablo yalnız `outcome.ok` iken dolu."""

    parsed = urlparse(locator)
    if len(parsed.scheme) == 1:
        # Windows sürücü harfi: urlparse("C:\\veri\\x.csv").scheme == "c" — şema değil yerel yol (Büşra'nın notu, 13 Eyl)
        parsed = urlparse("")
    if parsed.scheme in ("http", "https"):
        if _private_host(parsed.hostname or ""):
            raise ReadRefused("özel/loopback adreslere erişim yok")
        if session is None:
            from ..web.session import default_session
            session = default_session()
        from ..web.fetch import FetchRefused, guarded_get   # döngüsel import: web.html → builder.read
        try:
            resp, _final = guarded_get(session, locator, timeout=30, stream=True)
        except FetchRefused as exc:
            raise ReadRefused(str(exc)) from exc
        except Exception:  # noqa: BLE001 — DNS/TLS/timeout → unreachable
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
        return _table_from_bytes(content, parsed.path or locator, sheet=sheet), outcome

    if parsed.scheme not in ("", "file"):
        raise ReadRefused(f"desteklenmeyen şema: {parsed.scheme}")
    path = Path(parsed.path if parsed.scheme == "file" else locator)
    if not _under(path, allowed_roots):
        raise ReadRefused(f"'{path}' izinli kökün altında değil")
    if not path.is_file():
        return None, classify_access(str(path), http_status=404, environ=environ)
    if path.stat().st_size > max_bytes:
        raise ReadRefused(f"dosya {max_bytes} bayt sınırını aşıyor")
    frame = _table_from_bytes(path.read_bytes(), path.name, sheet=sheet)
    return frame, classify_access(str(path), http_status=200, environ=environ)


__all__ = ["MAX_BYTES_DEFAULT", "ReadRefused", "excel_sheets", "read_bytes_for_profiling", "read_table_for_profiling"]
