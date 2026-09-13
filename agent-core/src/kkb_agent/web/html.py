"""Sayfa içeriği → başlık, metin, tablolar, bağlantılar. Yorum yok, çıkarım yok.

Tablolar önce METİN olarak çıkarılır (lxml), sonra profilcinin sayı dilbilgisiyle
(`builder.profile`) sayıya çevrilir: hangi (ondalık, binlik) çiftinin kolonun %100'ünü
ayrıştırdığı ölçülür; belirsizse ("3.151") metin kalır ve söylenir. pandas'ın tahmini
kullanılmaz — ölçüldü, TCMB'nin "31.51"ini 3151 yapıyordu. Doğrudan veri dosyaları
(CSV/XLSX/JSON) profilleme okuyucusunun tablo ayrıştırıcısıyla okunur: aynı dilbilgisi.
"""

from __future__ import annotations

from collections import Counter

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
    table_labels: list[str] = field(default_factory=list)   # tablo başına bağlam ("sayfa 2: GÜMÜŞ / SILVER"); tables ile hizalı

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
    ambiguous: list[tuple[str, dict[tuple[str, str | None], list[float | None]], str]] = []
    resolved_pairs: Counter[tuple[str, str | None]] = Counter()
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
            # Bu kolonun ayraç çiftleri (hepsi aynı sayıyı verdi) tablonun kuralına oy verir; ayraçlı
            # (binlik ya da ondalık gerçekten görülen) çiftler sayılır, ayraçsız düz sayılar sayılmaz.
            for (decimal, thousands) in parsed:
                if any(("," in v or "." in v) for v in values if v):
                    resolved_pairs[(decimal, thousands)] += 1
        else:
            sample = next((v for v in values if v), "")
            ambiguous.append((col.name, parsed, sample))
    # Tablo düzeyinde ayraç kuralı (ölçüldü, OCR provası): "1.484", "514.813" gibi tek noktalı sayılar
    # kolon başına belirsizdir ama aynı tablonun başka kolonları "1.234,56" ise nokta binliktir.
    # Kural yalnız tablonun kendi çözümlü kolonlarından türer; dışarıdan varsayım yok.
    convention = None
    if resolved_pairs:
        convention, _votes = resolved_pairs.most_common(1)[0]
        if any(pair[0] != convention[0] for pair in resolved_pairs):
            convention = None      # tablo kendi içinde çelişiyor: kural yok
    for name, parsed, sample in ambiguous:
        values = frame[name].map(lambda t: "" if t is None else str(t))
        if convention is not None and convention in parsed:
            out[name] = pd.Series(parsed[convention], index=frame.index, dtype="float64")
            notes.append(f"'{name}' sayı biçimi belirsizdi (ör. {sample!r}); tablonun diğer kolonlarının "
                         f"ayraç kuralıyla (ondalık {convention[0]!r}, binlik {convention[1]!r}) çözüldü")
            continue
        # Karışık kolon kuralı (ölçüldü, OCR provası: elmas tabloları): kolonda hem düz tam sayılar
        # ("89", "129") hem de tek noktalı 3 haneli gruplar ("1.484") varsa nokta binliktir; ondalıklı
        # bir kolon her satırda ondalık taşırdı. Yalnız bu iki biçim varsa uygulanır.
        nonblank = [v for v in values if v]
        dotted = [v for v in nonblank if "." in v]
        plain = [v for v in nonblank if "." not in v and "," not in v]
        if (dotted and plain and not any("," in v for v in nonblank)
                and all(re.fullmatch(r"-?\d{1,3}(\.\d{3})+", v) for v in dotted) and (",", ".") in parsed):
            out[name] = pd.Series(parsed[(",", ".")], index=frame.index, dtype="float64")
            notes.append(f"'{name}' sayı biçimi belirsizdi (ör. {sample!r}); kolonda düz tam sayılar da olduğundan "
                         f"nokta binlik sayıldı")
            continue
        notes.append(f"'{name}' sayı biçimi belirsiz (ör. {sample!r}: binlik mi ondalık mı?); metin bırakıldı")
    out, date_notes = convert_dates(out)
    return out, notes + date_notes


def convert_dates(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Tarih biçimi tanınan metin kolonlarını gerçek tarihe çevirir (M10-T04, ADR-0054).

    Ölçüldü (jüri CSV provası): "31.01.2025" metin kalınca `LAG(...) OVER (ORDER BY "Tarih")` sözlük
    sırasına göre sıralandı (28.02 < 30.04 < 31.01 …) ve aylık değişimler yanlış çıktı; sayılar
    tabloda olduğu için kanıt paneli de yakalayamadı. Kural: profilci bir biçimi %100 ayrıştırıyorsa
    çevir; gün/ay belirsizse (tüm günler ≤ 12, iki biçim de geçiyor) metin kalır ve söylenir.
    """
    from ..builder.profile import profile_table

    out = frame.copy()
    notes: list[str] = []
    for col in profile_table(frame).columns:
        if not col.date_formats or col.non_empty != col.rows or pd.api.types.is_datetime64_any_dtype(frame[col.name]):
            continue
        if col.date_ambiguous:
            notes.append(f"'{col.name}' tarih ama gün/ay ayrımı belirsiz ({', '.join(col.date_formats)}); metin bırakıldı, kullanıcıya sorulmalı")
            continue
        fmt = col.date_formats[0]
        try:
            parsed = pd.to_datetime(frame[col.name].map(lambda t: "" if t is None else str(t).strip()), format=fmt, errors="raise")
        except (ValueError, TypeError):
            continue
        out[col.name] = parsed
        notes.append(f"'{col.name}' tarih kolonu ({fmt})")
    return out, notes


_DIGIT = re.compile(r"\d")
_UNIT_TOKEN = re.compile(r"^[A-Za-zÇĞİÖŞÜçğıöşü%/.]{1,8}$")


def promote_header_rows(frame: pd.DataFrame, max_rows: int = 2) -> pd.DataFrame:
    """OCR tabloları başlığı `<th>` ile değil ilk satır(lar)da `<td>` ile verir (ölçüldü: Borsa
    İstanbul altın tabloları 'sütun_n' ve ilk satır 'Yıl / Year, Oca./Jan., …'). Kolon adları
    zaten anlamlıysa dokunulmaz; aksi hâlde hiç rakam içermeyen ilk en çok `max_rows` satır
    başlık olur, çok satırlı başlık ' | ' ile birleşir. Sayı içeren satır asla başlık olmaz."""
    if frame.empty:
        return frame
    generic = all(str(c).startswith("sütun_") for c in frame.columns)
    # Adlı kolonlarda (<th> vardı) da başın altında alt başlık / birim satırı kalabilir (ölçüldü, elmas:
    # <th> satırından sonra "Hacim/ Volume" ve "TL | USD | EURO" satırları veri sanılıyordu).
    header_rows: list[list[str]] = [] if generic else [[str(c) for c in frame.columns]]
    body = frame
    limit = max_rows if generic else max_rows + 1
    while len(header_rows) < limit and len(body) > 1:
        cells = [str(v).strip() for v in body.iloc[0].tolist()]
        if not any(cells):
            break
        first_digits = bool(_DIGIT.search(cells[0]))
        rest_digits = any(_DIGIT.search(c) for c in cells[1:])
        if not first_digits and not rest_digits and generic:
            header_rows.append(cells)          # düz başlık satırı (yalnız adsız kolonlarda)
        elif first_digits and not rest_digits and any(cells[1:]):
            # Birim / alt başlık satırı (ölçüldü, elmas): "2025 | TL | USD | Miktar/Amount carat" — ilk hücre
            # rowspan'lı yıl artığı, kalan hücrelerde rakam yok. Veri satırı olsa sayı taşırdı.
            header_rows.append([""] + cells[1:])
        else:
            break
        body = body.iloc[1:]
    if not header_rows or (not generic and len(header_rows) == 1):
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


_TOTAL_COL = re.compile(r"toplam|total", re.I)
_OCR_DECIMAL_DOT = re.compile(r"^(-?\d{1,3}(?:\.\d{3})*)\.(\d{2})$")
_GARBLED = re.compile(r"^\d*[A-Za-z]\d+$|^\d+[A-Za-z]\d*$|^[A-Za-z]\d{2,}$")


def normalize_ocr_decimals(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """OCR virgülü nokta okur: "133.119.720,04" → "133.119.720.04", "0,00" → "0.00" (ölçüldü, elmas
    tabloları: hiçbir kolon sayıya çevrilemedi). Son noktadan sonra tam 2 hane varsa ve hücrede
    virgül yoksa o nokta ondalık virgüldür; 3 haneli gruplar ("1.484") dokunulmaz. Yalnız OCR
    tablolarına uygulanır; HTML sayfaları kendi ayracını taşır."""
    out = frame.copy()
    fixed = 0
    for col in out.columns:
        if pd.api.types.is_numeric_dtype(out[col]):
            continue
        def fix(v):
            nonlocal fixed
            if isinstance(v, str):
                m = _OCR_DECIMAL_DOT.match(v.strip())
                if m:
                    fixed += 1
                    return f"{m.group(1)},{m.group(2)}"
            return v
        out[col] = out[col].map(fix)
    return out, fixed


def garble_ratio(frame: pd.DataFrame) -> float:
    """Rakam-harf karışık hücrelerin oranı ("2O25", "l7582", "4O"): OCR'ın görüntüyü çözemediğinin
    deterministik izi."""
    cells = [str(v).strip() for v in frame.to_numpy().ravel() if isinstance(v, str) and str(v).strip()]
    if not cells:
        return 0.0
    return sum(1 for c in cells if _GARBLED.match(c)) / len(cells)


def row_sum_consistency(table: pd.DataFrame, tolerance: float = 0.01) -> float | None:
    """Toplam sütunu olan sayısal tabloda satırların kaçında öbür sayısal kolonların toplamı toplamla
    örtüşüyor (0–1). OCR kalitesinin deterministik ölçüsü (ölçüldü: JPEG q35 taramada değerler
    sessizce yanlıştı). Toplam kolonu ya da yeterli satır yoksa None: karar yok."""
    numeric = [c for c in table.columns if pd.api.types.is_numeric_dtype(table[c])]
    totals = [c for c in numeric if _TOTAL_COL.search(str(c))]
    if not totals or len(numeric) < 4:
        return None
    total_col = totals[0]
    parts = [c for c in numeric if c != total_col and not re.search(r"y[ıi]l|year|s[ıi]ra|no\b", str(c), re.I)]
    if len(parts) < 2:
        return None
    ok = checked = 0
    for _, row in table.iterrows():
        t = row[total_col]
        vals = [row[c] for c in parts]
        vals = [v for v in vals if v == v]
        if t != t or not vals or abs(float(t)) < 1e-9:
            continue
        checked += 1
        if abs(sum(vals) - float(t)) <= tolerance * abs(float(t)):
            ok += 1
    if checked < 3:
        return None
    return ok / checked


def extract_ocr_page(url: str, doc: Any) -> PageContent:
    """OCR belgesi (vision.ocr.OcrDocument) → sayfa içeriği: tablolar aynı profilci dilbilgisiyle
    sayıya çevrilir; her tablo 'görüntüden okundu, doğrulanmadı' notunu taşır."""
    from lxml import html as lh

    tables: list[pd.DataFrame] = []
    labels: list[str] = []
    notes: list[str] = [doc.note()]
    # Sayfa bağlamı tablonun adıdır: aynı yapıdaki iki tablo (sayfa 1 altın, sayfa 2 gümüş) başlıkta
    # metal adını taşımayabilir; ölçüldü (G18c), model gümüş tablosunu altın diye verdi. Sayfanın
    # metin başı tablo etiketine girer, kart ve provenance onu gösterir.
    page_title = {p.page_no: " · ".join(line.strip() for line in (p.prose or "").splitlines()
                                        if line.strip() and line.strip() != "[Non-Text]")[:80] for p in doc.pages}
    for page_no, html in doc.tables:
        try:
            frag = lh.fromstring("<html><body>" + html + "</body></html>")
            for raw in _string_tables(frag):
                named = promote_header_rows(raw, max_rows=3)
                named, fixed = normalize_ocr_decimals(named)
                converted, table_notes = convert_numbers(named)
                if fixed:
                    table_notes.append(f"{fixed} hücrede OCR'ın nokta okuduğu ondalık virgül düzeltildi (\"…,04\" biçimi)")
                tables.append(converted)
                labels.append(f"sayfa {page_no}" + (f": {page_title[page_no]}" if page_title.get(page_no) else ""))
                notes.extend(table_notes)
        except Exception as exc:  # noqa: BLE001 — OCR HTML bozuksa tablo yok, metin var
            notes.append(f"OCR tablosu ayrıştırılamadı (sayfa {page_no}): {exc}")
    quality = "bilinmiyor"
    # Yapı çözülememişse (başlıklar 'sütun_n', sayısal kolon yok) OCR görüntüyü okuyamamıştır (ölçüldü:
    # JPEG q35 tarama, 2× büyütmeyle bile); tablo var diye sayı verilmez, söylenir.
    unstructured = [t for t in tables if len(t.columns) >= 3
                    and len(t.select_dtypes("number").columns) < 0.3 * len(t.columns)
                    and (sum(str(c).startswith("sütun_") for c in t.columns) >= 0.5 * len(t.columns)
                         or garble_ratio(t) >= 0.15)]
    if tables and len(unstructured) == len(tables):
        quality = "belirsiz"
        notes.append("DİKKAT: OCR tablo yapısını çözemedi (başlıklar okunmadı, sayısal kolon yok); görüntü kalitesi "
                     "düşük olabilir. Bu tablodan sayı verme; kullanıcıdan daha net bir kopya ya da CSV iste.")
    checks = [row_sum_consistency(t) for t in tables]
    checked = [c for c in checks if c is not None]
    if checked:
        worst = min(checked)
        quality = "düşük" if worst < 0.5 else "tutarlı"
        if worst < 0.5:
            notes.append(f"DİKKAT: OCR tablosunda satır toplamları toplam sütunuyla tutmuyor (tutarlı satır oranı "
                         f"{worst:.0%}); görüntü kalitesi düşük olabilir, sayılar güvenilmez — kaynağın kendisiyle karşılaştır.")
        else:
            notes.append(f"OCR tutarlılık denetimi: satır toplamları toplam sütunuyla örtüşüyor ({worst:.0%}).")
    text = "\n".join(p.prose for p in doc.pages if p.prose)[:20000]
    title = Path(urlparse(url).path).name or url
    return PageContent(url=url, title=title, text=text, tables=tables, kind="ocr", notes=notes, table_labels=labels,
                       ocr={"model": doc.model, "pages": [p.page_no for p in doc.pages], "sha256": doc.sha256,
                            "truncated": doc.truncated, "total_pages": doc.total_pages, "quality": quality})


def extract_page(content: bytes, media_type: str, url: str, *, ocr: Any = None,
                 ocr_options: dict[str, Any] | None = None) -> PageContent:
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
            doc = ocr_document(content, kind, client=ocr, url=url, **(ocr_options or {}))
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
