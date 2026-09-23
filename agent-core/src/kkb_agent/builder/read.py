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

import io
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


def excel_sheets(content: bytes, *, engine: str | None = None) -> list[str]:
    """XLSX/XLS sayfa adları (M10-T05): birden çok sayfa varsa kullanıcı/model seçer, sessizce ilki alınmaz."""
    with pd.ExcelFile(io.BytesIO(content), engine=engine) as xf:
        return [str(n) for n in xf.sheet_names]


def _table_from_bytes(content: bytes, name: str, *, sheet: str | int | None = None) -> pd.DataFrame:
    """Tip çıkarımı YOK: her hücre metin. Boş hücre boş kalır, NaN olmaz.

    XLSX: `sheet` ad ya da 0-tabanlı indeks; verilmemişse ve birden çok sayfa varsa ReadRefused ile
    sayfa listesi döner (belirsizlik sorulur). Eski .xls xlrd ile okunur (21 Eyl: TÜİK/TBB dosyaları);
    veri havuzu .xls almaz, ingest yolu türetilmiş CSV'yi sahneler.
    """
    suffix = Path(name.split("?")[0]).suffix.lower()
    if suffix in (".xlsx", ".xlsm", ".xls"):
        engine = "xlrd" if suffix == ".xls" else "openpyxl"
        try:
            names = excel_sheets(content, engine=engine)
        except Exception as exc:  # noqa: BLE001 — bozuk/şifreli/yanlış uzantılı dosya: sebebi söylenir, tahmin yok
            raise ReadRefused(f"Excel dosyası ({suffix}) okunamadı: {type(exc).__name__}: {str(exc)[:120]}; "
                              "dosya bozuk, şifreli ya da uzantısı yanlış olabilir") from exc
        if sheet is None and len(names) > 1:
            raise ReadRefused("Excel dosyasında birden çok sayfa var: " + ", ".join(names) + " — `sheet` ile birini seç")
        target: str | int = 0 if sheet is None else sheet
        if isinstance(target, str) and target.isdigit():
            target = int(target)
        if isinstance(target, str) and target not in names:
            raise ReadRefused(f"sayfa '{target}' yok; sayfalar: {', '.join(names)}")
        if isinstance(target, int) and not (0 <= target < len(names)):
            raise ReadRefused(f"sayfa indeksi {target} yok; {len(names)} sayfa var")
        frame = pd.read_excel(io.BytesIO(content), sheet_name=target, dtype=str, keep_default_na=False, engine=engine)
        return frame.fillna("")
    text = content.decode("utf-8-sig", errors="replace")
    if suffix == ".json":
        frame = pd.read_json(io.StringIO(text), dtype=False)
        return frame.astype(str).where(frame.notna(), "")
    sep = "\t" if suffix == ".tsv" else None  # None → sniff (',' ';' '\t' '|')
    skip = _preamble_rows(text, sep)
    return pd.read_csv(io.StringIO(text), sep=sep, engine="python", dtype=str, keep_default_na=False,
                       skiprows=skip).fillna("")




def _preamble_rows(text: str, sep: str | None) -> int:
    """Başlık öncesi üst bilgi satırlarının sayısı ("Dışa Aktarım Tarihi:,23.09.2026", "Toplam Kayıt Sayısı:,261", boş).

    Gerçek başlık, tablonun alan sayısına (satırların çoğunluğundaki alan sayısı) sahip ilk satırdır; ondan önceki
    satırlar atlanır. Ölçüldü (23 Eyl, TEFAS CSV dışa aktarımı): ilk satır başlık sanıldı, "Dönem" kolonu görünmedi,
    kayıt reddedildi. Düzenli dosyada 0 döner."""
    import csv
    from collections import Counter
    lines = text.splitlines()[:200]
    if len(lines) < 3:
        return 0
    delim = sep
    if delim is None:
        try:
            delim = csv.Sniffer().sniff("\n".join(lines[-20:]), delimiters=",;\t|").delimiter
        except csv.Error:
            delim = ","
    counts = [len(row) for row in csv.reader(lines, delimiter=delim)]
    wide = [c for c in counts if c >= 2]
    if not wide:
        return 0
    modal = Counter(wide).most_common(1)[0][0]
    if sum(1 for c in counts if c == modal) < max(3, len(counts) // 2):
        return 0
    return next((i for i, c in enumerate(counts) if c == modal), 0)

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
        try:
            for chunk in resp.iter_content(65536):
                size += len(chunk)
                if size > max_bytes:
                    raise ReadRefused(f"kaynak {max_bytes} bayt sınırını aşıyor")
                chunks.append(chunk)
        finally:
            resp.close()
        content = b"".join(chunks)
        outcome = classify_access(
            locator, http_status=resp.status_code, final_url=getattr(resp, "url", None),
            body_excerpt=content[:4096].decode("utf-8", errors="ignore"), environ=environ,
        )
        headers = {str(k).lower(): v for k, v in (getattr(resp, "headers", {}) or {}).items()}
        media = str(headers.get("content-type") or "").split(";")[0].strip().lower()
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
