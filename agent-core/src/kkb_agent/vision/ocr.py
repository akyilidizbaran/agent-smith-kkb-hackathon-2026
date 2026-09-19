"""OCR istemcisi ve belge → tablo hattı. LLM'in kendisi değil, vision katmanı (ADR-0022).

Kloudeks `kkbhackathon2026/Unlimited-OCR` OpenAI-uyumlu `/chat/completions` ucundan çalışır:
tek görsel, base64 `image_url`, istem `<image>\\ndocument parsing`, `skip_special_tokens=false`,
`vllm_xargs={ngram_size: 35, window_size: 128}` (rehber). Çıktı `<|det|>tür [bbox]<|/det|>`
yerleşim etiketleri ve HTML `<table>` blokları. Ölçüldü (10 Eylül): çıktının başında belgeye
göre deterministik bir önek geliyor; ilk `<|det|>` öncesi atılır (9/9 tabloyu bozmadı).

Sınırlar deterministik: sayfa başına tek görsel, en çok `max_pages` sayfa (varsayılan 5),
2× render ölçeği, çağrı başına zaman aşımı. OCR bir OKUMA'dır, doğrulama değildir: her tablo
"görüntüden okundu, doğrulanmadı" notuyla gelir ve kanıt zinciri belgenin sha256'sında biter.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlparse

OCR_PROMPT = "<image>\ndocument parsing"
DOC_SUFFIXES = (".pdf", ".png", ".jpg", ".jpeg", ".webp")
IMAGE_MEDIA = ("image/png", "image/jpeg", "image/webp")
PDF_MEDIA = "application/pdf"
DEFAULT_MAX_PAGES = 5
RENDER_SCALE = 2.0

_DET_TAG = re.compile(r"<\|det\|>.*?<\|/det\|>|<\|ref\|>.*?<\|/ref\|>", re.S)
_TABLE_RE = re.compile(r"<table\b.*?</table>", re.S | re.I)
_HTML_TAG = re.compile(r"<[^>]+>")


def is_document(media_type: str, url: str) -> bool:
    kind = (media_type or "").split(";")[0].strip().lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    return kind == PDF_MEDIA or kind in IMAGE_MEDIA or suffix in DOC_SUFFIXES


def clean_ocr_text(raw: str) -> str:
    """İlk `<|det|>` öncesini at (belgeye bağlı çözümleme artefaktı, ADR-0022)."""
    i = raw.find("<|det|>")
    return raw[i:] if i > 0 else raw


def tables_from_ocr(text: str) -> list[str]:
    return [m.group(0) for m in _TABLE_RE.finditer(text)]


def prose_from_ocr(text: str, limit: int = 4000) -> str:
    """Tablo dışı metin: yerleşim etiketleri ve HTML atılmış."""
    no_tables = _TABLE_RE.sub(" ", text)
    no_tags = _HTML_TAG.sub(" ", _DET_TAG.sub("\n", no_tables))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", no_tags)).strip()[:limit]


def parse_pages(spec: str | None, total: int, *, max_pages: int = DEFAULT_MAX_PAGES) -> list[int]:
    """"3", "2-4", "1,5,7" → 1 tabanlı sayfa listesi; boşsa ilk `max_pages`. Sınır dışı sayfa atlanır,
    liste yine `max_pages` ile kesilir (deterministik bütçe)."""
    if not spec or not str(spec).strip():
        return list(range(1, min(total, max(1, max_pages)) + 1))
    out: list[int] = []
    for part in str(spec).replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                continue
            out.extend(range(max(1, lo), min(total, hi) + 1))
        else:
            try:
                n = int(part)
            except ValueError:
                continue
            if 1 <= n <= total:
                out.append(n)
    seen: list[int] = []
    for n in out:
        if n not in seen:
            seen.append(n)
    return seen[:max(1, max_pages)]


def pdf_pages_to_png(content: bytes, *, max_pages: int = DEFAULT_MAX_PAGES, scale: float = RENDER_SCALE,
                     pages: Sequence[int] | None = None) -> tuple[list[tuple[int, bytes]], int]:
    """((sayfa no, PNG) listesi, belgedeki toplam sayfa). pypdfium2, tarayıcı yok."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(content)
    total = len(doc)
    wanted = list(pages) if pages else list(range(1, min(total, max(1, max_pages)) + 1))
    out: list[tuple[int, bytes]] = []
    for n in wanted:
        if not 1 <= n <= total:
            continue
        page = doc[n - 1]
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        out.append((n, buf.getvalue()))
    return out, total


def pdf_text_layer(content: bytes, *, pages: str | None = None, max_pages: int = DEFAULT_MAX_PAGES) -> tuple[str, int, list[int]]:
    """PDF'in KENDİ metin katmanını doğrudan çıkarır (pypdfium2, OCR/ağ yok). Dönen: (metin, toplam sayfa, okunan sayfalar).

    Metin katmanı varsa sayılar BİREBİR ve doğrulanmıştır (OCR gerekmez). Taranmış/görüntü PDF'de metin ~boş döner;
    çağıran o zaman OCR'a düşer. Sayfa seçimi OCR ile aynı (`parse_pages`)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(content)
    total = len(doc)
    wanted = parse_pages(pages, total, max_pages=max_pages)
    chunks: list[str] = []
    read: list[int] = []
    for n in wanted:
        if not 1 <= n <= total:
            continue
        body = (doc[n - 1].get_textpage().get_text_bounded() or "").strip()
        if body:
            chunks.append(body)
            read.append(n)
    return "\n".join(chunks), total, read


def has_text_layer(text: str, *, min_chars: int = 40, min_letters: int = 20) -> bool:
    """Anlamlı bir metin katmanı mı? Taranmış PDF neredeyse boş/harfsiz döner → OCR'a düşülür."""
    body = (text or "").strip()
    return len(body) >= min_chars and sum(c.isalpha() for c in body) >= min_letters


@dataclass(frozen=True)
class OcrPage:
    page_no: int                 # 1 tabanlı
    tables: list[str]            # HTML <table> blokları
    prose: str
    raw_chars: int
    elapsed_ms: float


@dataclass(frozen=True)
class OcrDocument:
    sha256: str
    media_type: str
    model: str
    pages: list[OcrPage] = field(default_factory=list)
    total_pages: int = 0
    truncated: bool = False      # max_pages'ten uzun belge ya da zaman bütçesi
    truncated_reason: str = ""
    elapsed_ms: float = 0.0

    @property
    def tables(self) -> list[tuple[int, str]]:
        """(sayfa, html) — belge sırasıyla."""
        return [(p.page_no, t) for p in self.pages for t in p.tables]

    def note(self) -> str:
        pages = ", ".join(str(p.page_no) for p in self.pages) or "-"
        extra = ""
        if self.truncated:
            extra = (f" (belge {self.total_pages} sayfa, okunan {len(self.pages)}: {self.truncated_reason}; "
                     f"başka sayfa için pages='3' ya da '4-6' iste)")
        elif self.total_pages > len(self.pages):
            extra = f" (belge {self.total_pages} sayfa, seçilen {len(self.pages)})"
        return (f"Görüntüden OCR ile okundu ({self.model}, sayfa {pages}{extra}); sayılar doğrulanmadı, "
                f"kaynağın kendisiyle karşılaştırılmalı. Belge sha256 {self.sha256[:12]}…")


class OcrClient:
    """Tek görsel → OCR metni. `session` requests-benzeri (post(url, json=, headers=, timeout=))."""

    def __init__(self, *, base_url: str, api_key: str, model: str, session: Any = None, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.model = model
        self._session = session
        self.timeout = timeout
        self.calls = 0

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def ocr_png(self, png: bytes) -> str:
        session = self._session
        if session is None:
            from ..web.session import default_session
            session = default_session()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")}},
                {"type": "text", "text": OCR_PROMPT},
            ]}],
            "max_tokens": 8192, "temperature": 0.0,
            "skip_special_tokens": False,
            "vllm_xargs": {"ngram_size": 35, "window_size": 128},
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        self.calls += 1
        resp = session.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
        status = getattr(resp, "status_code", None)
        if status != 200:
            raise OcrError(f"OCR isteği {status} döndü")
        data = resp.json()
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as exc:
            raise OcrError(f"OCR yanıtı beklenen biçimde değil: {exc}") from exc


class OcrError(RuntimeError):
    """OCR servisi cevap vermedi ya da beklenmeyen biçimde cevap verdi."""


MIN_IMAGE_WIDTH = 1600   # bundan dar görseller OCR'dan önce 2× büyütülür (ölçüldü: küçük taramada sayılar bozuluyordu)


def _to_png(content: bytes, media_type: str) -> bytes:
    from PIL import Image

    image = Image.open(io.BytesIO(content)).convert("RGB")
    if image.width < MIN_IMAGE_WIDTH:
        image = image.resize((image.width * 2, image.height * 2), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


DEFAULT_MAX_SECONDS = 90.0   # belge başına OCR zaman bütçesi; aşılınca kalan sayfalar okunmaz, söylenir


def ocr_document(content: bytes, media_type: str, *, client: OcrClient, max_pages: int = DEFAULT_MAX_PAGES,
                 url: str = "", pages: str | Sequence[int] | None = None,
                 max_seconds: float = DEFAULT_MAX_SECONDS) -> OcrDocument:
    """PDF ya da görsel → sayfa sayfa OCR → tablolar + düz metin.

    Sayfa seçimi (`pages`: "3", "2-4", [1, 5]) ya da ilk `max_pages`; belge başına zaman bütçesi
    (`max_seconds`): canlı demoda 20 sayfalık bir bülten bütün süreyi yemesin, okunan kadarı
    dönsün ve kalanı için sayfa numarası istensin. İkisi de deterministik ve karta yazılır."""
    kind = (media_type or "").split(";")[0].strip().lower()
    suffix = Path(urlparse(url).path).suffix.lower()
    is_pdf = kind == PDF_MEDIA or suffix == ".pdf" or content[:5] == b"%PDF-"
    sha = hashlib.sha256(content).hexdigest()
    started_all = time.perf_counter()
    if is_pdf:
        import pypdfium2 as pdfium
        total = len(pdfium.PdfDocument(content))
        wanted = parse_pages(pages, total, max_pages=max_pages) if isinstance(pages, str) or pages is None else [int(n) for n in pages][:max_pages]
        pngs, total = pdf_pages_to_png(content, max_pages=max_pages, pages=wanted)
    else:
        pngs, total = [(1, _to_png(content, kind or {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")))], 1
        wanted = [1]
    out_pages: list[OcrPage] = []
    truncated_reason = ""
    for page_no, png in pngs:
        if out_pages and (time.perf_counter() - started_all) > max_seconds:
            truncated_reason = f"zaman bütçesi {max_seconds:.0f} s doldu"
            break
        started = time.perf_counter()
        raw = client.ocr_png(png)
        text = clean_ocr_text(raw)
        out_pages.append(OcrPage(page_no=page_no, tables=tables_from_ocr(text), prose=prose_from_ocr(text),
                                 raw_chars=len(raw), elapsed_ms=(time.perf_counter() - started) * 1000))
    if not truncated_reason and not (isinstance(pages, str) and pages.strip()) and pages is None and total > len(out_pages):
        truncated_reason = f"ilk {max_pages} sayfa sınırı"
    return OcrDocument(sha256=sha, media_type=PDF_MEDIA if is_pdf else (kind or "image/png"), model=client.model,
                       pages=out_pages, total_pages=total, truncated=bool(truncated_reason),
                       truncated_reason=truncated_reason, elapsed_ms=(time.perf_counter() - started_all) * 1000)


__all__ = ["DEFAULT_MAX_PAGES", "DEFAULT_MAX_SECONDS", "DOC_SUFFIXES", "OcrClient", "OcrDocument", "OcrError", "OcrPage",
           "clean_ocr_text", "has_text_layer", "is_document", "ocr_document", "parse_pages", "pdf_pages_to_png",
           "pdf_text_layer", "prose_from_ocr", "tables_from_ocr"]
