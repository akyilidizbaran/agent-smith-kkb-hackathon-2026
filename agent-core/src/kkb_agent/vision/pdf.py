"""PDF native-text extraction, kept distinct from OCR-derived table values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

MAX_PDF_TEXT_CHARS = 400_000


class PdfTextLayerError(RuntimeError):
    """PDF text layer could not be parsed by the configured PDF reader."""


@dataclass(frozen=True)
class PdfTextLayer:
    pages: list[tuple[int, str]]
    total_pages: int
    selected_pages: list[int]
    truncated: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(f"[Sayfa {number}]\n{text}" for number, text in self.pages if text)

    @property
    def has_text(self) -> bool:
        return sum(char.isalnum() for _, text in self.pages for char in text) >= 8

    def note(self) -> str:
        read_pages = ", ".join(str(number) for number, _ in self.pages) or "—"
        suffix = " (metin uzunluk sınırında kesildi)" if self.truncated else ""
        return (f"PDF'in yerel metin katmanı okundu; seçilen sayfalar: {read_pages} / "
                f"toplam {self.total_pages}{suffix}. Bu çıkarım tablo hücrelerini doğrulamaz.")

    def metadata(self) -> dict[str, object]:
        return {
            "method": "pdf_text_layer",
            "pages": [number for number, _ in self.pages],
            "selected_pages": list(self.selected_pages),
            "total_pages": self.total_pages,
            "text_chars": len(self.text),
            "truncated": self.truncated,
            "structured_tables": False,
        }


def extract_pdf_text_layer(
    content: bytes,
    *,
    pages: str | Sequence[int] | None = None,
    max_pages: int = 5,
    max_chars: int = MAX_PDF_TEXT_CHARS,
) -> PdfTextLayer:
    """Extract bounded native text from PDF pages without OCR or table claims.

    Uses pypdfium2's Unicode-aware ``get_text_bounded`` API. Page/table layout
    is not reconstructed; callers must keep this content separate from tables.
    """
    from .ocr import parse_pages

    try:
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(content)
        try:
            total = len(document)
            selected = (
                [int(number) for number in pages][:max(1, max_pages)]
                if pages is not None and not isinstance(pages, str)
                else parse_pages(pages, total, max_pages=max_pages)
            )
            extracted: list[tuple[int, str]] = []
            chars_left = max(0, max_chars)
            truncated = False
            for number in selected:
                if not 1 <= number <= total:
                    continue
                page = document[number - 1]
                text_page = page.get_textpage()
                try:
                    text = text_page.get_text_bounded().replace("\r\n", "\n").replace("\x00", "").strip()
                finally:
                    text_page.close()
                if len(text) > chars_left:
                    text = text[:chars_left]
                    truncated = True
                chars_left -= len(text)
                if text:
                    extracted.append((number, text))
                if chars_left <= 0:
                    truncated = True
                    break
            return PdfTextLayer(extracted, total, selected, truncated)
        finally:
            document.close()
    except Exception as exc:  # noqa: BLE001 — caller can fall back to OCR without treating it as absent data
        raise PdfTextLayerError(f"PDF metin katmanı okunamadı: {exc}") from exc


@dataclass(frozen=True)
class PdfTable:
    """PDF'in kendi metin katmanından çıkarılmış bir tablo — OCR değil, birebir hücreler."""

    page: int
    index: int
    rows: list[list[str]]
    pages: tuple[int, ...] = ()
    """Birleştirilmiş tablolarda kaynak sayfaların tamamı; tek sayfalıkta boş."""

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.rows), max((len(row) for row in self.rows), default=0))

    @property
    def source_pages(self) -> tuple[int, ...]:
        return self.pages or (self.page,)

    def note(self, sha256: str, locator: str) -> str:
        satir, sutun = self.shape
        sayfalar = ", ".join(str(number) for number in self.source_pages)
        devam = " (sayfalar boyunca süren tek tablo birleştirildi)" if len(self.source_pages) > 1 else ""
        return (f"Belge {locator} (sha256 {sha256}) PDF'in yerel metin katmanından okundu: "
                f"sayfa {sayfalar}, tablo #{self.index} ({satir}×{sutun}){devam}. Hücreler dosyanın "
                f"kendi metnidir, OCR tahmini değildir; sayı okuması kaynakla birebir aynıdır.")

    def metadata(self) -> dict[str, object]:
        satir, sutun = self.shape
        return {
            "method": "pdf_native_tables",
            "page": self.page,
            "pages": list(self.source_pages),
            "table_index": self.index,
            "rows": satir,
            "columns": sutun,
            "structured_tables": True,
        }


def _header_key(row: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(cell).strip().casefold() for cell in row)


def merge_continuations(tables: list[PdfTable]) -> list[PdfTable]:
    """Sayfa sayfa kesilmiş tek bir tabloyu geri birleştir.

    Uzun bir rapor her sayfada başlığını tekrar eder; sayfa başına bir tablo döndürmek
    "en büyük tabloyu al" diyen çağıranı raporun yalnız bir sayfasıyla bırakır. Başlık satırı
    birebir aynı olan ardışık tablolar tek tabloya katlanır, tekrar eden başlıklar düşer.
    Başlık değişiyorsa birleştirme yapılmaz: farklı başlık farklı tablodur.
    """
    merged: list[PdfTable] = []
    for table in tables:
        if merged and _header_key(merged[-1].rows[0]) == _header_key(table.rows[0]):
            previous = merged[-1]
            merged[-1] = PdfTable(
                page=previous.page,
                index=previous.index,
                rows=previous.rows + table.rows[1:],
                pages=previous.source_pages + (table.page,),
            )
            continue
        merged.append(table)
    return merged


def extract_pdf_tables(
    content: bytes,
    *,
    pages: str | Sequence[int] | None = None,
    max_pages: int = 100,
    max_tables: int = 400,
) -> list[PdfTable]:
    """Sayısal üretilmiş bir PDF'teki tabloları hücre hücre çıkar; bulunamazsa boş liste.

    Dışa aktarma araçlarının ürettiği PDF'lerde tablo çizgileri ve metin katmanı gerçektir,
    dolayısıyla hücreler tahmin edilmez — okunur. Bu yol OCR'dan hem hızlı hem kesindir;
    taranmış (metin katmanı olmayan) belgede boş döner ve çağıran OCR'a düşer.

    Tablo dışındaki serbest metin (rapor önsözü, sayfa altlığı) tabloya girmez.
    """
    found: list[PdfTable] = []
    try:
        for number, index, grid in _page_grids(content, pages, max_pages):
            rows = [
                ["" if cell is None else str(cell).replace("\n", " ").strip() for cell in row]
                for row in grid
            ]
            rows = [row for row in rows if any(cell for cell in row)]
            if len(rows) < 2:
                continue
            found.append(PdfTable(page=number, index=index, rows=rows))
            if len(found) >= max_tables:
                break
    except Exception:  # noqa: BLE001 - bozuk/şifreli PDF: OCR'a düşülür, veri yokmuş gibi davranılmaz
        return merge_continuations(found)
    return merge_continuations(found)


def _selected_pages(pages: str | Sequence[int] | None, total: int, max_pages: int) -> list[int]:
    from .ocr import parse_pages

    if pages is not None and not isinstance(pages, str):
        return [int(number) for number in pages][: max(1, max_pages)]
    return parse_pages(pages, total, max_pages=max_pages)


def _page_grids(content: bytes, pages: str | Sequence[int] | None, max_pages: int):
    """(sayfa no, tablo sırası, ham ızgara) üçlüleri; kurulu olan ilk tablo okuyucusuyla.

    Sıra bilinçli: pdfplumber (MIT) projenin bağımlılığıdır; pymupdf (AGPL) yalnız ortamda
    zaten varsa kullanılır. İkisi de yoksa hiçbir şey üretilmez ve çağıran OCR'a düşer.
    """
    import io

    try:
        import pdfplumber
    except ImportError:
        pdfplumber = None
    if pdfplumber is not None:
        with pdfplumber.open(io.BytesIO(content)) as document:
            total = len(document.pages)
            for number in _selected_pages(pages, total, max_pages):
                if not 1 <= number <= total:
                    continue
                try:
                    grids = document.pages[number - 1].extract_tables()
                except Exception:  # noqa: BLE001 - tek sayfanın düzeni çözülemeyebilir
                    continue
                for index, grid in enumerate(grids):
                    yield number, index, grid
        return

    try:
        import pymupdf
    except ImportError:  # pragma: no cover - eski kurulumlarda modülün adı fitz
        try:
            import fitz as pymupdf  # type: ignore[no-redef]
        except ImportError:
            return
    document = pymupdf.open(stream=content, filetype="pdf")
    try:
        total = document.page_count
        for number in _selected_pages(pages, total, max_pages):
            if not 1 <= number <= total:
                continue
            try:
                tables = document[number - 1].find_tables()
            except Exception:  # noqa: BLE001
                continue
            for index, table in enumerate(tables.tables):
                try:
                    yield number, index, table.extract()
                except Exception:  # noqa: BLE001
                    continue
    finally:
        document.close()


__all__ = [
    "MAX_PDF_TEXT_CHARS",
    "PdfTable",
    "PdfTextLayer",
    "PdfTextLayerError",
    "extract_pdf_tables",
    "extract_pdf_text_layer",
    "merge_continuations",
]
