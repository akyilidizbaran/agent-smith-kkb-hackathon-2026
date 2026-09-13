"""Görüntü ve PDF girişi: sayfa → PNG → MIA Unlimited-OCR → HTML tablo (ADR-0022, ADR-0041)."""
from .ocr import OcrClient, OcrDocument, OcrPage, clean_ocr_text, is_document, ocr_document, pdf_pages_to_png, tables_from_ocr

__all__ = ["OcrClient", "OcrDocument", "OcrPage", "clean_ocr_text", "is_document", "ocr_document", "pdf_pages_to_png", "tables_from_ocr"]
