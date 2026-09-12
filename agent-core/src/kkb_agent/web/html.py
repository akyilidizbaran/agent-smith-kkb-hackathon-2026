"""Sayfa içeriği → başlık, metin, tablolar, bağlantılar. Yorum yok, çıkarım yok.

Tablolar önce METİN olarak çıkarılır (lxml), sonra profilcinin sayı dilbilgisiyle
(`builder.profile`) sayıya çevrilir: hangi (ondalık, binlik) çiftinin kolonun %100'ünü
ayrıştırdığı ölçülür; belirsizse ("3.151") metin kalır ve söylenir. pandas'ın tahmini
kullanılmaz — ölçüldü, TCMB'nin "31.51"ini 3151 yapıyordu. Doğrudan veri dosyaları
(CSV/XLSX/JSON) profilleme okuyucusunun tablo ayrıştırıcısıyla okunur: aynı dilbilgisi.
"""

from __future__ import annotations

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
    kind: str = "html"   # html | data | text
    notes: list[str] = field(default_factory=list)   # sayı biçimi belirsizlikleri vb.

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


def _clean_cell(text: str) -> str:
    """Hücre metni: NBSP ve baştaki/sondaki yüzde işareti atılır; sayı dilbilgisi dokunmaz."""
    return _PCT.sub("", str(text).replace("\xa0", " ")).strip()


def _string_tables(doc: Any) -> list[pd.DataFrame]:
    """HTML tabloları METİN olarak: tip çıkarımı yok. Sayıya çevirme profilci kuralıyla ayrı."""
    tables: list[pd.DataFrame] = []
    for table in doc.xpath("//table"):
        rows: list[list[str]] = []
        header: list[str] | None = None
        for tr in table.xpath(".//tr"):
            cells = tr.xpath("./th|./td")
            if not cells:
                continue
            values = [_clean_cell(c.text_content()) for c in cells]
            if header is None and all(c.tag == "th" for c in cells):
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


def extract_page(content: bytes, media_type: str, url: str) -> PageContent:
    kind = media_type.split(";")[0].strip().lower()
    path = urlparse(url).path.lower()
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
