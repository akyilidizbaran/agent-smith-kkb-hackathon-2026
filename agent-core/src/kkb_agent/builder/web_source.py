"""User-supplied page -> bounded attachment discovery -> textual table + source evidence.

No database writes here. HTML and original attachment bytes accompany the selected table;
the caller stages them only after mapping validation. A page grants access to its actual
same-host download links, not arbitrary URLs proposed by the model.
"""
from __future__ import annotations

import calendar
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

import pandas as pd

from ..contracts.access import AccessOutcome
from ..vision.ocr import is_document, ocr_document, parse_pages
from ..web.html import _string_tables, extract_ocr_page
from .read import _table_from_bytes, read_bytes_for_profiling


class SourceSelection(ValueError):
    """A source was read, but a file/table/measure must be selected before ingestion."""


@dataclass
class SourceAsset:
    url: str
    content: bytes
    suffix: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass
class SourceTable:
    frame: pd.DataFrame | None
    outcome: AccessOutcome
    assets: list[SourceAsset] = field(default_factory=list)
    note: str = ""
    entity_column: str | None = None
    frequency: str | None = None
    turkish_numbers: bool = False

    def stage(self, root: Path) -> tuple[str, str]:
        """Persist exact source snapshots and the selected CSV; catalog note is repeatable."""
        assert self.frame is not None
        root.mkdir(parents=True, exist_ok=True)
        sources = []
        for asset in self.assets:
            path = root / f"source_{asset.sha256}{asset.suffix}"
            if not path.exists():
                path.write_bytes(asset.content)
            sources.append({"url": asset.url, "sha256": asset.sha256, "file": path.name})
        csv = self.frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        digest = hashlib.sha256(csv).hexdigest()
        path = root / f"web_table_{digest}.csv"
        if not path.exists():
            path.write_bytes(csv)
        manifest = {"sources": sources, "table_sha256": digest, "transformation": self.note}
        # Different origins may have identical tables; retain a manifest for each chain.
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        manifest_path = root / f"source_manifest_{hashlib.sha256(manifest_bytes).hexdigest()}.json"
        if not manifest_path.exists():
            manifest_path.write_bytes(manifest_bytes)
        evidence = "; ".join(f"{s['url']} (sha256 {s['sha256']}, {s['file']})" for s in sources)
        return str(path), f"{self.note} Kaynak zinciri: {evidence}. Manifest: {manifest_path.name}."


def _kind(content: bytes, media: str, locator: str) -> str:
    """Content/mime detection supports download endpoints without filename extensions."""
    media = media.split(";")[0].lower().strip()
    head = content[:2000].lstrip().lower()
    if content.startswith(b"%PDF-"):
        return ".pdf"
    if b"<html" in head or b"<!doctype html" in head or head.startswith(b"<table"):
        return ".html"
    suffix = Path(urlparse(locator).path).suffix.lower()
    mime = {"application/pdf": ".pdf", "text/html": ".html", "application/xhtml+xml": ".html",
            "application/json": ".json", "text/csv": ".csv", "text/tab-separated-values": ".tsv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
            "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
    if media in mime:
        return mime[media]
    if suffix in (".csv", ".tsv", ".xlsx", ".xlsm", ".xls", ".json", ".pdf", ".png", ".jpg", ".jpeg", ".webp"):
        return suffix
    if head.startswith((b"[", b"{")):
        return ".json"
    return ".csv"


def _select(items: list, index: int | None, parameter: str, labels: list[str]):
    if not items:
        raise SourceSelection(f"Kaynakta kullanılabilir {parameter} bulunamadı.")
    if index is None and len(items) == 1:
        return items[0]
    if index is None or not 0 <= index < len(items):
        choices = "\n".join(f"  {i}: {label}" for i, label in enumerate(labels))
        raise SourceSelection(f"{parameter} seçilmeli (0 tabanlı):\n{choices}\n"
                              f"İsteğe uygun seçeneği {parameter} ile aynı araca ver; belirsizse kullanıcıya sor.")
    return items[index]


def _html_scope(content: bytes, url: str):
    from lxml import html
    doc = html.fromstring(content)
    fragment = unquote(urlparse(url).fragment)
    if fragment:
        matches = doc.xpath("//*[@id=$fragment]", fragment=fragment)
        if not matches:
            raise SourceSelection(f"URL'deki #{fragment} bölümü sayfada bulunamadı; başka dönem seçilmedi.")
        return matches[0]
    return doc


def _attachments(scope: Any, base: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in scope.xpath('.//a[@href]'):
        href = urljoin(base, anchor.get("href", "").strip())
        parsed = urlparse(href)
        if parsed.scheme not in ("http", "https") or parsed.hostname != urlparse(base).hostname:
            continue
        mime = anchor.get("type", "").lower()
        name = anchor.get("title", "")
        is_file = ("download" in anchor.attrib or mime in (
            "application/pdf", "application/json", "text/csv",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            or Path(parsed.path).suffix.lower() in (".csv", ".tsv", ".json", ".xlsx", ".pdf", ".png", ".jpg")
            or Path(name).suffix.lower() in (".pdf", ".xlsx", ".csv"))
        if is_file and href not in seen:
            seen.add(href)
            label = " ".join(anchor.text_content().split()) or name or href
            out.append((label, href))
    return out


def _native_pdf(content: bytes, pages: str | None) -> list[tuple[str, pd.DataFrame]]:
    import pdfplumber
    tables = []
    with pdfplumber.open(io.BytesIO(content)) as doc:
        wanted = parse_pages(pages, len(doc.pages))
        if not wanted:
            raise SourceSelection(f"Sayfa seçimi geçersiz; belge {len(doc.pages)} sayfa.")
        for number in wanted:
            for raw in doc.pages[number - 1].extract_tables():
                if len(raw) < 2 or len(raw[0]) < 2:
                    continue
                cleaned = [[" ".join((cell or "").split()) for cell in row] for row in raw]
                headers = [cell or f"kolon_{i}" for i, cell in enumerate(cleaned[0])]
                if len(set(headers)) != len(headers):
                    headers = [f"{h} [{i}]" if headers.count(h) > 1 else h for i, h in enumerate(headers)]
                tables.append((f"PDF sayfa {number}", pd.DataFrame(cleaned[1:], columns=headers)))
    # Aynı başlıkla sayfa sayfa devam eden rapor tablosu tek tablodur (ölçüldü 23 Eyl: haftalık işlem hacmi raporu PDF'i,
    # 8 sayfa / 261 satır; yalnız ilk sayfanın 34 satırı kaydediliyordu). Farklı başlıklı tablolar ayrı kalır.
    merged: list[tuple[str, pd.DataFrame]] = []
    for label, frame in tables:
        if merged and list(merged[-1][1].columns) == list(frame.columns):
            prev_label, prev = merged[-1]
            first = prev_label.split("-")[0].strip()
            merged[-1] = (f"{first}-{label.rsplit(' ', 1)[-1]}", pd.concat([prev, frame], ignore_index=True))
        else:
            merged.append((label, frame))
    return merged


_MONTHS = {name: i + 1 for i, name in enumerate(
    ("ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık"))}


def header_period(frame: pd.DataFrame) -> tuple[str, str] | None:
    """İlk sütun başlığında açık 'Ay YYYY' varsa (dönem sonu tarihi, frekans); yoksa None."""
    match = re.fullmatch(r"([\wÇĞİÖŞÜçğıöşü]+)\s+(20\d{2}|19\d{2})", str(frame.columns[0]).strip())
    month = _MONTHS.get(match[1].lower()) if match else None
    if not month:
        return None
    year = int(match[2])
    return f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}", "monthly"


def measure_row_to_long(frame: pd.DataFrame, value_row: str | None, period: tuple[str, str] | None,
                        *, entity_label: str = "kurum") -> tuple[pd.DataFrame, str, str | None] | None:
    """Ölçümleri satırda, varlıkları sütunda gösteren rapor matrisini uzun tabloya çevirir.

    Dönem ya ilk başlıktan ('Temmuz 2026') ya da kullanıcının beyanından (`period`) gelir; ikisi de yoksa ve
    `value_row` verildiyse açıkça sorulur. Döner: (uzun tablo, not, frekans) ya da dönüşüm gerekmiyorsa None."""
    period = header_period(frame) or period
    if period is None:
        if value_row is not None:
            raise SourceSelection("value_row için ilk sütun başlığında açık bir ay/yıl bulunmalı ya da dönemi "
                                  "period ile söyleyin (ör. 'Ağustos 2026').")
        return None
    labels = frame.iloc[:, 0].tolist()
    if value_row not in labels or labels.count(value_row) != 1:
        raise SourceSelection("Bu tablo ölçümleri satırlarda gösteriyor. Kaydedilecek ölçümü value_row ile seç:\n"
                              + "\n".join(f"  {label}" for label in labels))
    selected = frame.loc[frame.iloc[:, 0] == value_row].iloc[0]
    date, frequency = period
    long = pd.DataFrame({"tarih": [date] * (len(frame.columns) - 1),
                         entity_label: list(frame.columns[1:]),
                         value_row: selected.iloc[1:].tolist()})
    note = (f" Ölçüm satırı {value_row!r}; {entity_label} sütunlardan satırlara çevrildi. "
            f"Dönem {'başlığı ' + repr(str(frame.columns[0])) if header_period(frame) else 'kullanıcı beyanı'}, "
            f"dönem sonu {date}; Türkçe sayı gösterimi: ondalık virgül, binlik nokta. Toplam ayrı satır olarak korundu.")
    return long, note, frequency


def _monthly_matrix(result: SourceTable, value_row: str | None, period: tuple[str, str] | None = None,
                    entity_label: str = "kurum") -> None:
    """An explicit month in the first header (or a user-declared period) anchors a metric-by-entity report matrix."""
    frame = result.frame
    assert frame is not None
    converted = measure_row_to_long(frame, value_row, period, entity_label=entity_label)
    if converted is None:
        return
    result.frame, note, frequency = converted
    result.entity_column = entity_label
    result.frequency = frequency
    result.turkish_numbers = True
    result.note += note


def read_web_source(locator: str, *, allowed_root: Path, resource_index: int | None = None,
                    table_index: int | None = None, pages: str | None = None,
                    sheet: str | None = None, value_row: str | None = None,
                    session: Any = None, ocr: Any = None,
                    period: tuple[str, str] | None = None, entity_label: str = "kurum") -> SourceTable:
    content, media, outcome = read_bytes_for_profiling(locator, allowed_roots=[allowed_root], session=session)
    result = SourceTable(None, outcome)
    if content is None or not outcome.ok:
        return result
    kind = _kind(content, media, locator)
    final_url = outcome.evidence.final_url or locator
    result.assets.append(SourceAsset(final_url, content, kind))
    tables: list[tuple[str, pd.DataFrame]] = []
    if kind == ".html":
        scope = _html_scope(content, locator)
        links = _attachments(scope, final_url)
        # An explicit attachment selection takes precedence over page tables.
        tables = [("HTML tablo", frame) for frame in _string_tables(scope)]
        if links and (resource_index is not None or not tables):
            label, target = _select(links, resource_index, "resource_index", [f"{label} — {url}" for label, url in links])
            content, media, outcome = read_bytes_for_profiling(target, allowed_roots=[allowed_root], session=session)
            result.outcome = outcome
            if content is None or not outcome.ok:
                return result
            kind = _kind(content, media, target)
            final_url = outcome.evidence.final_url or target
            result.assets.append(SourceAsset(final_url, content, kind))
            result.note = f"Sayfa {locator} üzerinden seçilen ek: {label}."
            if kind == ".html":
                raise SourceSelection("Seçilen indirme adresi veri dosyası yerine HTML döndürdü; kayıt yapılmadı.")
        elif not tables:
            raise SourceSelection("Sayfanın seçilen bölümünde tablo veya indirilebilir veri dosyası yok. "
                                  "JavaScript grafik verisi bu okuyucuda çalıştırılmaz.")
    if kind == ".pdf":
        try:
            tables = _native_pdf(content, pages)
        except SourceSelection:
            raise
        except Exception as exc:
            if ocr is None:
                raise SourceSelection(f"PDF metin/tablo okuması başarısız: {type(exc).__name__}.") from exc
            tables = []
        if tables:
            result.note += " PDF metin katmanından okundu (pdfplumber); OCR kullanılmadı."
    if not tables and is_document(media, f"source{kind}"):
        if ocr is None:
            raise SourceSelection("Belgede metin katmanından tablo bulunamadı; OCR istemcisi gerekli (VISION_MODEL).")
        doc = ocr_document(content, media, client=ocr, url=f"source{kind}", pages=pages)
        page = extract_ocr_page(final_url, doc)
        if page.ocr and page.ocr.get("quality") in ("düşük", "belirsiz"):
            raise SourceSelection("OCR tablosunun kalitesi düşük veya belirsiz; daha net kaynak gerekli.")
        tables = [(f"OCR tablo {i}", t.astype(str).where(t.notna(), "")) for i, t in enumerate(page.tables)]
        result.note += " " + doc.note()
    elif not tables and kind != ".html":
        if kind in (".xlsx", ".xlsm"):
            # The staged CSV must not bypass the lakehouse's formula/link refusal.
            import openpyxl
            workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=False, keep_links=True)
            try:
                if workbook._external_links:
                    raise SourceSelection("Excel dış çalışma kitabı bağlantıları içeriyor; değerlerden oluşan bir dosya gerekli.")
                for worksheet in workbook:
                    if any(cell.data_type == "f" for row in worksheet for cell in row):
                        raise SourceSelection("Excel formül içeriyor; formülleri değer olarak dışa aktarın.")
            finally:
                workbook.close()
        try:
            tables = [("Veri dosyası", _table_from_bytes(content, f"source{kind}", sheet=sheet))]
        except (ValueError, pd.errors.ParserError) as exc:
            raise SourceSelection(f"Veri dosyası okunamadı: {exc}") from exc
    label, result.frame = _select(tables, table_index, "table_index",
        [f"{label}, {len(t)} satır; sütunlar: {', '.join(map(str, t.columns))[:700]}; örnek: {t.head(2).to_dict('records')}"
         for label, t in tables])
    result.note += f" {label}, table_index={table_index if table_index is not None else 0}."
    _monthly_matrix(result, value_row, period, entity_label)
    return result
