"""Sayfa içeriği → başlık, metin, tablolar, bağlantılar. Yorum yok, çıkarım yok.

Tablolar önce METİN olarak çıkarılır (lxml), sonra profilcinin sayı dilbilgisiyle
(`builder.profile`) sayıya çevrilir: hangi (ondalık, binlik) çiftinin kolonun %100'ünü
ayrıştırdığı ölçülür; belirsizse ("3.151") metin kalır ve söylenir. pandas'ın tahmini
kullanılmaz — ölçüldü, TCMB'nin "31.51"ini 3151 yapıyordu. Doğrudan veri dosyaları
(CSV/XLSX/JSON) profilleme okuyucusunun tablo ayrıştırıcısıyla okunur: aynı dilbilgisi.
"""

from __future__ import annotations

from pathlib import Path

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse

import pandas as pd

from ..builder.read import _table_from_bytes
from .fetch import DATA_SUFFIXES, same_domain

_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n\s*\n+")


@dataclass
class PageContent:
    url: str
    title: str = ""
    text: str = ""
    tables: list[pd.DataFrame] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)   # (metin, mutlak href) — aynı alan adı
    data_links: list[tuple[str, str]] = field(default_factory=list)
    kind: str = "html"   # html | data | text | ocr | document
    notes: list[str] = field(default_factory=list)   # sayı biçimi belirsizlikleri vb.
    ocr: dict[str, Any] | None = None                # {"model", "pages", "sha256", "truncated"} — OCR ile okunduysa

    def table_previews(self, max_rows: int = 3) -> list[str]:
        out = []
        for i, t in enumerate(self.tables):
            cols = ", ".join(map(str, t.columns))[:160]
            out.append(f"#{i}: {len(t)}×{len(t.columns)} — kolonlar: {cols}\n"
                       + t.head(max_rows).to_string(index=False)[:400])
        return out


def _clean_text(text: str) -> str:
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _NL.sub("\n\n", text).strip()


_PCT = re.compile(r"^\s*%\s*|\s*%\s*$")


_PLACEHOLDER = re.compile(r"^(?:[-–—]+|n\.?a\.?|n/a|\.{3}|…|x)$", re.I)


def _clean_cell(text: str) -> str:
    """Hücre metni: NBSP ve baştaki/sondaki yüzde işareti atılır; sayı dilbilgisi dokunmaz.
    "-", "n.a.", "…" gibi yer tutucular boş değerdir (ölçüldü: altın ithalat tablosunda tek "-"
    hücresi altı ay kolonunu metin bıraktı)."""
    cleaned = _PCT.sub("", str(text).replace("\xa0", " ")).strip()
    return "" if _PLACEHOLDER.match(cleaned) else cleaned


def _span(cell: Any, attr: str) -> int:
    try:
        return max(1, int(str(cell.get(attr) or "1").strip()))
    except ValueError:
        return 1


def _grid_rows(table: Any) -> list[tuple[list[str], bool]]:
    """`<tr>`'leri colspan/rowspan açılmış hücre ızgarasına çevirir: (değerler, hepsi <th> mi).

    Ölçüldü (Borsa İstanbul altın işlem tablosu, OCR): `<td rowspan=2>AY/MONTH</td><td colspan=3>TL</td>…`
    açılmadan üst başlık ('TL', 'USD', 'EUR') yanlış kolonlara kayıyordu. Yayılan hücrenin değeri
    kapladığı her kolona yazılır (pandas.read_html ile aynı davranış)."""
    pending: dict[tuple[int, int], str] = {}   # (satır, kolon) → rowspan ile inen değer
    rows: list[tuple[list[str], bool]] = []
    for r, tr in enumerate(table.xpath(".//tr")):
        cells = tr.xpath("./th|./td")
        values: list[str] = []
        c = 0
        for cell in cells:
            while (r, c) in pending:
                values.append(pending.pop((r, c)))
                c += 1
            text = _clean_cell(cell.text_content())
            cs, rs = _span(cell, "colspan"), _span(cell, "rowspan")
            for k in range(cs):
                values.append(text)
                for dr in range(1, rs):
                    pending[(r + dr, c + k)] = text
            c += cs
        while (r, c) in pending:
            values.append(pending.pop((r, c)))
            c += 1
        if values:
            rows.append((values, bool(cells) and all(x.tag == "th" for x in cells)))
    return rows


def _string_tables(doc: Any) -> list[pd.DataFrame]:
    """HTML tabloları METİN olarak: tip çıkarımı yok. Sayıya çevirme profilci kuralıyla ayrı."""
    tables: list[pd.DataFrame] = []
    for table in doc.xpath("//table"):
        rows: list[list[str]] = []
        header: list[str] | None = None
        for values, all_th in _grid_rows(table):
            if header is None and all_th:
                header = values
                continue
            rows.append(values)
        if not rows:
            continue
        width = max(len(r) for r in rows + ([header] if header else []))
        rows = [r + [""] * (width - len(r)) for r in rows]
        if header is None or len(header) != width:
            header = [f"sütun_{i + 1}" for i in range(width)]
        # aynı başlık iki kez geçerse pandas'ta kolon çakışır; numaralandır
        seen: dict[str, int] = {}
        cols = []
        for h in header:
            h = h or "sütun"
            seen[h] = seen.get(h, 0) + 1
            cols.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
        tables.append(pd.DataFrame(rows, columns=cols))
    return tables


def convert_numbers(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Metin tabloyu profilci dilbilgisiyle sayıya çevirir; belirsiz kolon metin kalır ve söylenir.

    Ölçüldü: pandas'ın `thousands="."` varsayımı TCMB sayfasındaki "31.51"i 3151 yaptı —
    yüz kat hata, sessiz. Profilci hangi (ondalık, binlik) çiftinin kolonun %100'ünü
    ayrıştırdığını ölçer; tek çift → çevir; birden çok çift aynı sayıları veriyorsa (ayraç
    yok) → çevir; farklı sayılar veriyorsa ("3.151") → BELİRSİZ, metin kalır, not düşer.
    """
    from ..builder.profile import _parse_number, profile_table

    out = frame.copy()
    notes: list[str] = []
    profile = profile_table(frame)
    for col in profile.columns:
        if not col.numeric_under or col.date_formats:
            continue
        values = frame[col.name].map(lambda t: "" if t is None else str(t))
        parsed: dict[tuple[str, str | None], list[float | None]] = {}
        for decimal, thousands in col.numeric_under:
            try:
                parsed[(decimal, thousands)] = [_parse_number(v, decimal, thousands) for v in values]
            except ValueError:
                continue
        if not parsed:
            continue
        distinct = {tuple(v) for v in parsed.values()}
        if len(distinct) == 1:
            out[col.name] = pd.Series(next(iter(parsed.values())), index=frame.index, dtype="float64")
        else:
            sample = next((v for v in values if v), "")
            notes.append(f"'{col.name}' sayı biçimi belirsiz (ör. {sample!r}: binlik mi ondalık mı?); metin bırakıldı")
    return out, notes


_DIGIT = re.compile(r"\d")


def promote_header_rows(frame: pd.DataFrame, max_rows: int = 2) -> pd.DataFrame:
    """OCR tabloları başlığı `<th>` ile değil ilk satır(lar)da `<td>` ile verir (ölçüldü: Borsa
    İstanbul altın tabloları 'sütun_n' ve ilk satır 'Yıl / Year, Oca./Jan., …'). Kolon adları
    zaten anlamlıysa dokunulmaz; aksi hâlde hiç rakam içermeyen ilk en çok `max_rows` satır
    başlık olur, çok satırlı başlık ' | ' ile birleşir. Sayı içeren satır asla başlık olmaz."""
    if frame.empty or not all(str(c).startswith("sütun_") for c in frame.columns):
        return frame
    header_rows: list[list[str]] = []
    body = frame
    while len(header_rows) < max_rows and len(body) > 1:
        cells = [str(v).strip() for v in body.iloc[0].tolist()]
        if not any(cells) or any(_DIGIT.search(c) for c in cells):
            break
        header_rows.append(cells)
        body = body.iloc[1:]
    if not header_rows:
        return frame
    # Birleşik (colspan) başlık hücreleri sağa doğru boş kalır: her başlık satırında soldaki
    # dolu hücre boşlara taşınır ("TL | Hacim", "TL | Miktar", "USD | Hacim").
    filled: list[list[str]] = []
    for row in header_rows:
        last = ""
        out_row = []
        for cell in row:
            last = cell or last
            out_row.append(last)
        filled.append(out_row)
    names: list[str] = []
    for j in range(len(frame.columns)):
        parts = [row[j] for row in filled if row[j]]
        name = " | ".join(dict.fromkeys(parts)) or f"sütun_{j + 1}"
        while name in names:
            name += "_"
        names.append(name)
    out = body.reset_index(drop=True)
    out.columns = names
    return out


def extract_ocr_page(url: str, doc: Any) -> PageContent:
    """OCR belgesi (vision.ocr.OcrDocument) → sayfa içeriği: tablolar aynı profilci dilbilgisiyle
    sayıya çevrilir; her tablo 'görüntüden okundu, doğrulanmadı' notunu taşır."""
    from lxml import html as lh

    tables: list[pd.DataFrame] = []
    notes: list[str] = [doc.note()]
    html_blocks = [html for _, html in doc.tables]
    if html_blocks:
        try:
            frag = lh.fromstring("<html><body>" + "".join(html_blocks) + "</body></html>")
            for raw in _string_tables(frag):
                converted, table_notes = convert_numbers(promote_header_rows(raw))
                tables.append(converted)
                notes.extend(table_notes)
        except Exception as exc:  # noqa: BLE001 — OCR HTML bozuksa tablo yok, metin var
            notes.append(f"OCR tablosu ayrıştırılamadı: {exc}")
    text = "\n".join(p.prose for p in doc.pages if p.prose)[:20000]
    title = Path(urlparse(url).path).name or url
    return PageContent(url=url, title=title, text=text, tables=tables, kind="ocr", notes=notes,
                       ocr={"model": doc.model, "pages": [p.page_no for p in doc.pages], "sha256": doc.sha256,
                            "truncated": doc.truncated, "total_pages": doc.total_pages})


def extract_page(content: bytes, media_type: str, url: str, *, ocr: Any = None) -> PageContent:
    kind = media_type.split(";")[0].strip().lower()
    path = urlparse(url).path.lower()
    from ..vision.ocr import is_document, ocr_document

    if is_document(kind, url):
        # PDF/görsel: tablo yalnız OCR ile çıkar; istemci yoksa "okunamadı" (uydurma yok).
        if ocr is None:
            return PageContent(url=url, title=Path(path).name, kind="document",
                               text="(PDF/görsel belge; OCR istemcisi yapılandırılmamış — VISION_MODEL yok)",
                               notes=["PDF/görsel belge OCR olmadan okunamaz."])
        try:
            doc = ocr_document(content, kind, client=ocr, url=url)
        except Exception as exc:  # noqa: BLE001 — servis hatası sayfa notuna, uydurma yok
            return PageContent(url=url, title=Path(path).name, kind="document",
                               text=f"(PDF/görsel belge; OCR başarısız: {exc})", notes=[f"OCR başarısız: {exc}"])
        return extract_ocr_page(url, doc)
    if kind in ("text/csv", "application/json", "application/vnd.ms-excel",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") or path.endswith(DATA_SUFFIXES):
        try:
            frame = _table_from_bytes(content, path or url)
        except Exception as exc:  # noqa: BLE001
            return PageContent(url=url, title="", text=f"(veri dosyası ayrıştırılamadı: {exc})", kind="data")
        converted, notes = convert_numbers(frame)
        return PageContent(url=url, title=path.rsplit("/", 1)[-1], tables=[converted], kind="data", notes=notes)

    text = content.decode("utf-8", errors="replace")
    if kind not in ("text/html", "application/xhtml+xml") and "<html" not in text[:2000].lower():
        return PageContent(url=url, title="", text=_clean_text(text)[:20000], kind="text")

    from lxml import html as lh

    try:
        doc = lh.fromstring(text)
    except Exception:  # noqa: BLE001
        return PageContent(url=url, title="", text=_clean_text(re.sub(r"<[^>]+>", " ", text))[:20000], kind="text")
    for bad in doc.xpath("//script|//style|//noscript|//nav|//footer|//header"):
        bad.drop_tree()
    title_nodes = doc.xpath("//title")
    title = _clean_text(title_nodes[0].text_content()) if title_nodes else ""
    # Blok öğeleri satır sonuyla ayır: aksi hâlde başlık ve hücreler birbirine yapışıyor.
    for node in doc.xpath("//p|//div|//li|//h1|//h2|//h3|//h4|//tr|//br|//td|//th"):
        node.tail = ("\n" if node.tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br") else " ") + (node.tail or "")
    body_text = _clean_text(doc.text_content())

    links: list[tuple[str, str]] = []
    data_links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in doc.xpath("//a[@href]"):
        href = urljoin(url, a.get("href").strip())
        if href.startswith(("mailto:", "javascript:", "tel:")) or href in seen:
            continue
        if not href.startswith(("http://", "https://")):
            continue
        seen.add(href)
        label = _clean_text(a.text_content())[:120]
        if urlparse(href).path.lower().endswith(DATA_SUFFIXES):
            data_links.append((label, href))
        elif same_domain(href, url):
            links.append((label, href))
    tables: list[pd.DataFrame] = []
    notes: list[str] = []
    for raw in _string_tables(doc):
        converted, table_notes = convert_numbers(raw)
        tables.append(converted)
        notes.extend(table_notes)
    return PageContent(url=url, title=title, text=body_text[:20000], tables=tables,
                       links=links, data_links=data_links, kind="html", notes=notes)


__all__ = ["PageContent", "convert_numbers", "extract_page"]
