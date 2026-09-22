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


__all__ = ["MAX_PDF_TEXT_CHARS", "PdfTextLayer", "PdfTextLayerError", "extract_pdf_text_layer"]
