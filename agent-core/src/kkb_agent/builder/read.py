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
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import pandas as pd

from ..contracts.access import AccessOutcome
from ..core.access_policy import classify_access

MAX_BYTES_DEFAULT = 25 * 1024 * 1024

_DELIMITERS = (",", ";", "\t", "|")
MAX_PREAMBLE_ROWS = 20
"""Başlıktan önce atlanabilecek en fazla önsöz satırı. Daha uzun bir giriş rapor önsözü
değildir; orada tahmin etmek yerine dosya olduğu gibi okunur."""


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


def _tag_preamble(frame: pd.DataFrame, preamble: list[str]) -> pd.DataFrame:
    """Atlanan önsözü tabloya iliştir: kaybolmaz, ama sütun adı da olmaz.

    Kanıt zinciri için önemlidir — "Dışa Aktarım Tarihi" dosyanın ne zaman çekildiğini söyler —
    ama veri değildir, bu yüzden tabloya değil `attrs`'a yazılır.
    """
    if preamble:
        frame.attrs["preamble"] = list(preamble)
    return frame


def _table_width(counts: Iterable[int]) -> int:
    """Tablonun gerçek genişliği: en sık görülen alan sayısı (eşitlikte geniş olan).

    Tek alanlı satırlar (boş satır, serbest metin) sayılmaz; bir tablo en az iki sütundur.
    """
    tally = Counter(count for count in counts if count >= 2)
    if not tally:
        return 0
    return max(tally, key=lambda width: (tally[width], width))


def _header_index(counts: list[int], width: int) -> int:
    """Başlık satırının indeksi. Önsöz varsa >0, yoksa 0.

    Başlık, tablo genişliğinde olan **ilk** satırdır. Önündeki her satır kesinlikle daha dar
    olmalı: bu sayede tam genişlikte bir satır asla veri kaybı pahasına atılmaz. Ölçüt
    tutmuyorsa 0 döner ve dosya bugünkü gibi okunur — belirsizlikte tahmin yok.
    """
    if width < 2:
        return 0
    for index, count in enumerate(counts):
        if count != width:
            continue
        if 0 < index <= MAX_PREAMBLE_ROWS and all(earlier < width for earlier in counts[:index]):
            return index
        return 0
    return 0


def strip_preamble_rows(rows: list[list[str]]) -> tuple[list[list[str]], list[str]]:
    """Hazır bir hücre ızgarasından rapor önsözünü ayır: (tablo satırları, atılan satırlar).

    CSV/XLSX ile aynı ölçüt; PDF'ten çıkarılmış ızgara gibi zaten ayrıştırılmış veride kullanılır.
    """
    counts = [sum(1 for cell in row if str(cell).strip()) for row in rows]
    index = _header_index(counts, _table_width(counts))
    if index == 0:
        return rows, []
    skipped = [", ".join(str(cell).strip() for cell in row if str(cell).strip()) for row in rows[:index]]
    return rows[index:], [line for line in skipped if line]


def frame_from_grid(rows: list[list[Any]]) -> tuple[pd.DataFrame, list[str]]:
    """Hücre ızgarası (PDF tablosu gibi) → metin tablo: önsöz ayrılır, ilk satır başlık olur.

    Boş başlık `sutun_N`, tekrar eden başlık `ad_2` olur; pandas'ın sessiz yeniden adlandırması
    yerine burada açıkça yapılır. Başlık + en az bir veri satırı yoksa ReadRefused.
    """
    grid = [["" if cell is None else str(cell) for cell in row] for row in rows]
    body_rows, preamble = strip_preamble_rows(grid)
    if len(body_rows) < 2:
        raise ReadRefused("tabloda başlık ve en az bir veri satırı yok")
    width = max(len(row) for row in body_rows)
    header = [str(cell).strip() for cell in list(body_rows[0]) + [""] * (width - len(body_rows[0]))]
    header = [name or f"sutun_{position + 1}" for position, name in enumerate(header)]
    seen: dict[str, int] = {}
    for position, name in enumerate(header):
        seen[name] = seen.get(name, 0) + 1
        if seen[name] > 1:
            header[position] = f"{name}_{seen[name]}"
    body = [[(row[i] if i < len(row) else "") for i in range(width)] for row in body_rows[1:]]
    frame = pd.DataFrame(body, columns=header, dtype=str).fillna("")
    return _tag_preamble(frame, preamble), preamble


def _delimited_preamble(text: str) -> tuple[int, list[str]]:
    """(atlanacak fiziksel satır sayısı, atlanan satırlar) — sınırlayıcıyı kendisi bulur.

    TEFAS/EVDS gibi dışa aktarımlar tablonun üstüne "Dışa Aktarım Tarihi", "Toplam Kayıt
    Sayısı" gibi dar rapor satırları koyar. Bunlar pandas'ın gözünde ilk satır, yani başlık
    olur; dört sütunluk tablo iki sütuna sıkışır. Burada başlık satırı bulunur ve önsöz
    yalnızca *atlanır*, yorumlanmaz — hangi satırların atlandığı çağırana geri verilir.
    """
    best: tuple[tuple[int, int], str, list[list[str]], list[int]] | None = None
    for delimiter in _DELIMITERS:
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
            rows = [row for _, row in zip(range(MAX_PREAMBLE_ROWS + 200), reader)]
        except csv.Error:
            continue
        counts = [len(row) for row in rows]
        width = _table_width(counts)
        if width < 2:
            continue
        score = (sum(1 for count in counts if count == width), width)
        if best is None or score > best[0]:
            best = (score, delimiter, rows, counts)
    if best is None:
        return 0, []
    _score, delimiter, rows, counts = best
    index = _header_index(counts, _table_width(counts))
    if index == 0:
        return 0, []

    # Atlanacak olan fiziksel satır sayısıdır, alan satırı sayısı değil: tırnak içindeki bir
    # satır sonu ikisini ayırır. `line_num` okuyucunun gerçekten tükettiği satırı verir.
    probe = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    physical = 0
    for position, _row in enumerate(probe):
        if position == index - 1:
            physical = probe.line_num
            break
    skipped = [", ".join(cell.strip() for cell in row if cell.strip()) for row in rows[:index]]
    return physical, [line for line in skipped if line]


def _xlsx_preamble(content: bytes, sheet_name: str) -> tuple[int, list[str]]:
    """XLSX'te başlık satırının indeksi ve atlanan önsöz satırları.

    CSV ile aynı ölçüt; XLSX'te "Rapor Bilgileri" gibi tek hücrelik bir başlık daha olabildiği
    için sabit bir `skiprows` değeri doğru olmaz, genişlik ölçülür.
    """
    import openpyxl

    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        sheet = workbook[sheet_name]
        counts: list[int] = []
        texts: list[str] = []
        for position, row in enumerate(sheet.iter_rows(values_only=True)):
            cells = [str(cell).strip() for cell in row if cell is not None and str(cell).strip()]
            counts.append(len(cells))
            texts.append(", ".join(cells))
            if position > MAX_PREAMBLE_ROWS + 200:
                break
    finally:
        workbook.close()
    index = _header_index(counts, _table_width(counts))
    return index, [line for line in texts[:index] if line]


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
        sheet_name = names[target] if isinstance(target, int) else target
        skip, preamble = _xlsx_preamble(content, sheet_name)
        frame = pd.read_excel(
            io.BytesIO(content), sheet_name=target, dtype=str, keep_default_na=False,
            engine="openpyxl", skiprows=skip,
        )
        return _tag_preamble(frame.fillna(""), preamble)
    text = content.decode("utf-8-sig", errors="replace")
    if suffix == ".json":
        frame = pd.read_json(io.StringIO(text), dtype=False)
        return frame.astype(str).where(frame.notna(), "")
    sep = "\t" if suffix == ".tsv" else None  # None → sniff (',' ';' '\t' '|')
    skip, preamble = _delimited_preamble(text)
    frame = pd.read_csv(
        io.StringIO(text), sep=sep, engine="python", dtype=str, keep_default_na=False,
        skiprows=skip,
    ).fillna("")
    return _tag_preamble(frame, preamble)


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


__all__ = ["MAX_BYTES_DEFAULT", "MAX_PREAMBLE_ROWS", "ReadRefused", "excel_sheets", "frame_from_grid",
           "read_bytes_for_profiling", "read_table_for_profiling", "strip_preamble_rows"]
