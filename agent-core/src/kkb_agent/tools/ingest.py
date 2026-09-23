"""`ingest_from_url` — Analist'in Architect'e açılan tek kapısı.

Demo senaryosunun 2. sorusu: jüri yeni veri getirir, agent ingest eder ve belgeler.
Akış deterministik; burada LLM yok:

    erişim (ADR-0028) → profilleme oku → öner (kanıtla) → doğrula (yayınlama kuralları)
      → belirsizse KULLANICIYA SOR, yazma
      → okuyucuyu kapat → veri ekibinin CLI'ı draft'a yazar → okuyucuyu yeniden aç
      → belge kartı

Yazma yeteneği bu aracın dışında hiçbir yerde yok: Analist'in bağlantısı salt-okunur
kalır; yazan, ayrı bir süreçte çalışan veri ekibinin CLI'ıdır ve o da yalnız
`adhoc` + `draft` yazabilir. Curated Silver'a bu yoldan girilemez.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from ..adapters.duckdb_lakehouse import release_connections
from ..builder.ingest import LakehouseCLI
from ..builder.profile import profile_table, propose
from ..builder.read import ReadRefused, read_bytes_for_profiling, read_table_for_profiling
from ..builder.crosscheck import cross_check, file_points
from ..builder.quality import table_quality
from ..builder.relevance import assess as assess_relevance, catalog_entries, user_confirmed
from ..core.fitness import _LOCATOR as _LOCATOR_RE, Lexicon, assess as assess_fitness, signature_of
from ..builder.unit_guess import guess_unit
from ..builder.verify import verify_mapping
from ..builder.web_source import SourceSelection, measure_row_to_long, read_web_source
from ..contracts.lakehouse import LakehouseClient
from ..core.access_policy import decide, detect_source_constraint, render_for_model, to_tool_error
from ..core.errors import ToolError
from ..core.intent import locator_from_user, write_intent
from ..core.tool import Tool, ToolResult
from ..vision.ocr import is_document, ocr_document
from ..web.html import extract_ocr_page


class OcrUnavailable(RuntimeError):
    """Belge var ama OCR yok ya da tablo bulunamadı: uydurma yok, kullanıcıya söylenir."""


class IngestParams(BaseModel):
    locator: str = Field(description="Kullanıcının verdiği yerel dosya veya http(s) URL: veri dosyası ya da rapor ekleri içeren HTML sayfası. Sayfanın #bölüm kısmını koru.")
    resource_index: int | None = Field(default=None, ge=0, description="HTML sayfasında listelenen indirilebilir eklerden hangisi (0 tabanlı). İlk çağrıda boş bırak; seçeneklerden isteğe uygun raporu seç.")
    table_index: int | None = Field(default=None, ge=0, description="Listelenen PDF/HTML tablolarından hangisi (0 tabanlı). URL'de birden çok tablo varsa seçenekler döner.")
    value_row: str | None = Field(default=None, description="Aylık raporda ölçümler satırdaysa kaydedilecek ölçümün tam satır etiketi; seçenekler araç çıktısında verilir.")
    pages: str | None = Field(default=None, description="PDF için hangi sayfalar: '3', '2-4' (varsayılan ilk 5)")
    sheet: str | None = Field(default=None, description="Excel'de sayfa adı ya da 0 tabanlı indeks; birden çok sayfa varsa zorunlu")
    name: str = Field(description="Serinin okunabilir adı, ör. 'İl bazında konut satışları'")
    series_key: str | None = Field(
        default=None,
        description="Seri anahtarı (harf, rakam, alt çizgi). Boşsa dosya adından türetilir.",
    )
    description: str | None = Field(default=None, description="Bir cümlelik açıklama; boşsa üretilir.")
    # Kullanıcının beyan ettiği anlam: veriden çıkarılamayan alanlar buradan dolar. Model
    # uydurmaz, kullanıcının söylediğini aktarır; kartta "kullanıcı beyanı" diye yazılır.
    unit: str | None = Field(default=None, description="Kullanıcı söylediyse birim, ör. '°C', 'kişi', 'milyon TL'")
    measure_type: Literal["stock", "flow_periodic", "flow_ytd", "flow_cumulative", "rate", "ratio", "index", "count"] | None = Field(
        default=None, description="Kullanıcı söylediyse ölçüm tipi (stok/akım/oran/endeks/adet)")
    default_agg: Literal["avg", "sum", "min", "max", "first", "last"] | None = Field(
        default=None, description="Kullanıcı söylediyse frekans indirgeme kuralı (ör. aylık ortalama → avg)")
    frequency: Literal["daily", "business_daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "yearly"] | None = Field(
        default=None, description="Kullanıcı söylediyse frekans")
    date_format: str | None = Field(default=None, description="Kullanıcı söylediyse tarih biçimi, ör. '%d/%m/%Y' (belirsiz gün/ay için)")
    # Kolon seçimi (21 Eyl): çok kolonlu dosyada hangi kolonun seri olacağını kullanıcı söyler; araç önerdiği
    # seçeneklerden birini kullanıcı anmadan model seçemez (beyan kuralıyla aynı).
    value_column: str | None = Field(default=None, description="Kaydedilecek DEĞER kolonunun adı (araç seçenekleri listeler; kullanıcının andığı kolon)")
    date_column: str | None = Field(default=None, description="TARİH kolonunun adı; birden çok tarih kolonu varsa ya da öneri yanlışsa")
    entity_column: str | None = Field(default=None, description="Varlık/boyut kolonu (il, kurum, ülke); tarih başına birden çok satır varsa")
    # Beyan edilen dönem (21 Eyl): tarih kolonu olmayan kesit tablolarında (il × değer, kurum × tutar) kullanıcı
    # dönemi söyler ('Ağustos 2026', '2026-06-30', '2025', '2026Q2'); tüm satırlar o döneme bağlanır.
    period: str | None = Field(default=None, description="Tarih kolonu yoksa kullanıcının söylediği dönem: 'Ağustos 2026', '2026-08', '2026-06-30', '2025', '2026Q2'. Tabloda ay adları sütunu varsa (Ocak, Şubat…) yılı ver ('2026'): satırlar aylara bağlanır.")
    # İlgi kapısı (V3 §3.9): dosya soruyla ilgisiz görünürse yazılmaz ve sorulur. Kullanıcı
    # "yine de ekle / doğru dosya bu" derse model bu bayrağı açar; bayrak yalnız kullanıcı
    # metninde onay sözü varsa geçerlidir (beyan kuralıyla aynı: modelin sözü yetmez).
    user_confirmed: bool = Field(
        default=False,
        description="Kullanıcı 'yine de ekle' ya da 'doğru dosya bu' dediyse true; ilgi kapısını geçer.",
    )


# Arayüz yüklemesi dosyaya 8 onaltılık ön ek koyar (web_app.save_upload: "cb6d79f3_hastane.csv"). Kullanıcı ön eki görmez;
# seri anahtarına girince "adhoc:cb6d79f3_hastane" olur ve onay cümlesindeki adla eşleşmez (ADR-0068 eki, 15 Eyl).
_UPLOAD_PREFIX = re.compile(r"^[0-9a-f]{8}_(?=\w)")


def _locator_names(text: str) -> str:
    """Metindeki adres/yolu yalnız dosya adıyla değiştirir: '/private/var/…/incoming/cb6d79f3_sicaklik.csv' → 'sicaklik'.

    İlgi kapısı için (15 Eyl, PR #4 CI): dizin parçaları ('folders', 'incoming', kullanıcı adı) soru terimi sayılıyordu; adresi
    tümden silmek de kullanıcının dosyayı adıyla anmasını ('sicaklik.csv dosyasını ekle') ilgi işareti olmaktan çıkarıyordu."""
    def name(match: re.Match) -> str:
        base = re.split(r"[\\/]", match.group(0).split("?")[0].rstrip("/\\"))[-1]
        return " " + _UPLOAD_PREFIX.sub("", base.rsplit(".", 1)[0] if "." in base else base) + " "
    return _LOCATOR_RE.sub(name, text or "")


def _slug(text: str) -> str:
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ ", "cgiosuCGIOSU_")
    s = re.sub(r"[^A-Za-z0-9_]+", "_", text.translate(tr)).strip("_").lower()
    return s or "seri"


_MEASURE_WORDS = {
    "stock": ("stok", "bakiye", "stock"), "flow_periodic": ("akım", "akim", "dönemlik", "flow"),
    "flow_ytd": ("yıl başından", "ytd", "birikimli"), "flow_cumulative": ("kümülatif", "kumulatif", "cumulative"),
    "rate": ("oran", "faiz", "yüzde", "rate", "%"), "ratio": ("rasyo", "ratio"),
    "index": ("endeks", "index", "seviye"), "count": ("adet", "sayı", "sayi", "count"),
}
_AGG_WORDS = {"avg": ("ortalama", "avg", "average"), "sum": ("toplam", "sum"), "min": ("minimum", "en düşük", "min"),
              "max": ("maksimum", "en yüksek", "max"), "first": ("ilk", "first"), "last": ("son", "last", "dönem sonu")}


def undeclared(params: IngestParams, user_text: str) -> list[str]:
    """Modelin doldurduğu beyan alanlarından kullanıcı metninde karşılığı OLMAYANLAR.

    Ölçüldü: model ilk turda birimi ('°C') ve ölçüm tipini ('stock') kendisi uydurup yazdı;
    kullanıcı henüz bir şey söylememişti. Beyan kullanıcının sözüdür: birim metinde geçmeli,
    ölçüm tipi ve kural için anahtar sözcük geçmeli. Aksi hâlde alan yok sayılır ve sorulur."""
    text = (user_text or "").lower()
    bad: list[str] = []
    if params.unit and params.unit.lower() not in text:
        bad.append(f"unit={params.unit!r}")
    if params.measure_type and not any(w in text for w in _MEASURE_WORDS.get(params.measure_type, ())):
        bad.append(f"measure_type={params.measure_type!r}")
    if params.default_agg and not any(w in text for w in _AGG_WORDS.get(params.default_agg, ())):
        bad.append(f"default_agg={params.default_agg!r}")
    if params.frequency and params.frequency.lower() not in text and not any(
            w in text for w in {"daily": ("günlük",), "weekly": ("haftalık",), "monthly": ("aylık",),
                                "quarterly": ("çeyreklik",), "yearly": ("yıllık",)}.get(params.frequency, ())):
        bad.append(f"frequency={params.frequency!r}")
    # Kolon seçimi ve dönem de beyandır: model, aracın listelediği seçenekten kullanıcı anmadan seçemez.
    for field_name in ("value_column", "date_column", "entity_column"):
        value = getattr(params, field_name)
        if value and not _mentioned(value, text):
            bad.append(f"{field_name}={value!r}")
    if params.period:
        year = re.search(r"(19|20)\d{2}", params.period)
        if not year or year.group(0) not in text:
            bad.append(f"period={params.period!r}")
    return bad


_TR_MONTHS = {name: i + 1 for i, name in enumerate(
    ("ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık"))}
_TR_MONTHS.update({"subat": 2, "mayis": 5, "agustos": 8, "eylul": 9, "kasim": 11, "aralik": 12})


def parse_period(text: str | None) -> tuple[str, str | None] | None:
    """Kullanıcının söylediği dönemi (dönem sonu tarihi, frekans) çiftine çevirir; anlaşılmazsa None.

    Kabul edilen yazımlar: '2026-06-30' (gün), '2026-08' ve 'Ağustos 2026' / '2026 Ağustos' (ay → ay sonu, monthly),
    '2026Q2' / '2026 Ç2' (çeyrek → çeyrek sonu, quarterly), '2025' (yıl → yıl sonu, yearly). Tahmin yok: iki
    okuması olan yazım ('06/08/2026') kabul edilmez."""
    import calendar
    from datetime import date as _date

    s = (text or "").strip().lower().replace("i̇", "i")
    if not s:
        return None
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
        y, mo, d = map(int, m.groups())
        try:
            return _date(y, mo, d).isoformat(), None
        except ValueError:
            return None
    if m := re.fullmatch(r"(\d{4})[-/](\d{1,2})", s):
        y, mo = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"([a-zçğıöşü]+)\s+(\d{4})", s) or re.fullmatch(r"(\d{4})\s+([a-zçğıöşü]+)", s):
        a, b = m.groups()
        name, y = (a, int(b)) if a.isalpha() else (b, int(a))
        mo = _TR_MONTHS.get(name)
        if not mo:
            return None
    elif m := re.fullmatch(r"(\d{4})\s*[qç]\s*([1-4])", s):
        y, q = int(m[1]), int(m[2])
        mo = q * 3
        return f"{y:04d}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}", "quarterly"
    elif m := re.fullmatch(r"(\d{4})", s):
        y = int(m[1])
        return f"{y:04d}-12-31", "yearly"
    else:
        return None
    if not 1 <= mo <= 12:
        return None
    return f"{y:04d}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}", "monthly"


def _mentioned(name: str | None, user_text: str) -> bool:
    """Kolon adının anlamlı bir parçası (≥3 harf) kullanıcı metninde geçiyor mu — 'TL hacim' → 'Hacim/Volume (TL)'."""
    if not name:
        return False
    text = (user_text or "").lower()
    words = [w for w in re.split(r"[^0-9a-zçğıöşü]+", name.lower()) if len(w) >= 3]
    return any(w in text for w in words) or name.lower() in text


def _entity_label(user_text: str) -> str:
    """Satır-ölçüm matrisinde sütunlardan satıra inen varlık kolonunun adı, kullanıcının sözüyle: 'il bazında' → il,
    'kurum' → kurum, 'ülke' → ulke; söylenmediyse 'kurum' (Risk Merkezi örneği). Ölçüldü (21 Eyl, KFE.pdf): iller
    'kurum' başlığıyla dönünce model haklı olarak teyit istedi."""
    text = (user_text or "").lower()
    if re.search(r"il(ler|lere|lerin|de)?|il baz|şehir|sehir|bölge|bolge", text):
        return "il"
    if re.search(r"ülke|ulke|country", text):
        return "ulke"
    if re.search(r"banka|kurum|kuruluş|sektör", text):
        return "kurum"
    return "kurum"


_MONTH_TOKENS = {**{k: v for k, v in _TR_MONTHS.items()},
                 **{m: i + 1 for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july",
                                                     "august", "september", "october", "november", "december"))},
                 **{m: i + 1 for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"))},
                 **{m: i + 1 for i, m in enumerate(("oca", "şub", "mar", "nis", "may", "haz", "tem", "ağu", "eyl", "eki", "kas", "ara"))}}


def _month_of(cell: str) -> int | None:
    """'Ocak / January', 'Şubat/February', 'Mart', 'Aug' → ay numarası; 'TOPLAM / TOTAL' → None."""
    for token in re.split(r"[^0-9a-zçğıöşü]+", str(cell).lower().replace("i̇", "i")):
        if token in _MONTH_TOKENS:
            return _MONTH_TOKENS[token]
    return None


def month_names_to_dates(frame: Any, year: int) -> tuple[Any, str] | None:
    """Ay adı sütunu + beyan edilen yıl → ISO ay sonu tarihleri (21 Eyl; Borsa altın PDF'i: 'AY/MONTH' sütunu, yıl başlıkta).

    En az 6 farklı ay adı taşıyan ilk metin sütunu tarih sütunu olur; ay okunamayan satırlar (TOPLAM/TOTAL) düşürülür
    ve notta sayılır. Böyle bir sütun yoksa None (çağıran sabit dönem yoluna düşer)."""
    import calendar

    for column in frame.columns:
        values = [str(v) for v in frame[column].tolist()]
        months = [_month_of(v) for v in values]
        distinct = {m for m in months if m}
        if len(distinct) >= 6:
            keep = [m is not None for m in months]
            dropped = [values[i] for i, k in enumerate(keep) if not k and values[i].strip()]
            out = frame.loc[keep].copy()
            out[column] = [f"{year:04d}-{m:02d}-{calendar.monthrange(year, m)[1]:02d}" for m, k in zip(months, keep) if k]
            note = (f"'{column}' sütunundaki ay adları kullanıcının beyan ettiği {year} yılıyla ay sonu tarihlerine çevrildi"
                    + (f"; ay olmayan {len(dropped)} satır düşürüldü ({', '.join(d[:20] for d in dropped[:3])})" if dropped else "") + ".")
            return out, note
    return None


def year_column_to_dates(frame: Any, column: str) -> tuple[Any, str]:
    """Çıplak yıl sütunu → ISO yıl sonu tarihi (1960 → 1960-12-31); yıllık serinin dönem sonu kuralı (aylıkta ay sonu gibi).
    Veri ekibinin CLI'ı yalnız tam tarih alır; dönüşüm sahnelenen CSV'de, kaynak dosya değişmez."""
    out = frame.copy()
    out[column] = [f"{int(str(v).strip()):04d}-12-31" for v in out[column].tolist()]
    return out, f"'{column}' sütunundaki yıllar yıl sonu tarihine çevrildi (1960 → 1960-12-31); frekans yıllık."


def _bare_locator(locator: str) -> bool:
    """Adres ne http(s), ne file:, ne mutlak yol: yalnız bir dosya adı. Kullanıcı dosyayı eklemeden adını yazmıştır
    (ölçüldü 20 Eyl: 'bist_altin_2023.csv dosyasını kaydet' → araç düz adla arandı, ACCESS_BLOCKED)."""
    return not re.match(r"^(?:https?://|file:|[A-Za-z]:[\\/]|[\\/])", (locator or "").strip())


def _source_display_name(locator: str) -> str:
    """Kataloğa giren kaynak adı: yükleme kopyasının rastgele ön eki (`3bcc4cc9_`) kullanıcının dosya adı değildir.

    `PureWindowsPath` her platformda hem eğik hem ters eğik çizgi ayracını tanır: Linux CI'da Windows yolu tek parça kalıyordu
    (PR #21 ilk koşusu), Windows'ta Linux yolu zaten çalışır.
    """
    return _UPLOAD_PREFIX.sub("", PureWindowsPath(locator.split("?")[0]).name)


#: Ölçüm tipinden türeyen varsayılan toplama yöntemi (katalog sözleşmesindeki anlam: stok dönem sonu değeri,
#: dönemlik akım toplanır, yıl içi/kümülatif akım son değeri taşır, oran/endeks ortalanır, sayım toplanır).
_AGG_BY_MEASURE = {"stock": "last", "flow_periodic": "sum", "flow_ytd": "last", "flow_cumulative": "last",
                   "count": "sum", "rate": "avg", "ratio": "avg", "index": "avg"}


def _default_agg_from_measure(semantics):
    """Kullanıcı toplama yöntemi söylemediyse ölçüm tipinden türet ve kanıt satırıyla işaretle.

    Ölçüldü (20 Eyl): 'birim kg, aylık, dönemlik akım' beyanıyla kaydedilen taslakta `default_agg` NULL kaldı;
    Gold'a alınırken hizalama yöntemi belirsiz olurdu. Türetme deterministiktir ve kartta görünür; `unknown`
    ölçüm tipinde türetilmez (bilinmeyen anlamdan yöntem çıkmaz)."""
    from dataclasses import replace
    from ..builder.profile import Evidence

    if getattr(semantics, "default_agg", None) or semantics.measure_type not in _AGG_BY_MEASURE:
        return semantics
    agg = _AGG_BY_MEASURE[semantics.measure_type]
    evidence = [e for e in semantics.evidence if e.field != "default_agg"]
    evidence.append(Evidence("default_agg", agg, f"ölçüm tipinden türetildi ({semantics.measure_type} → {agg})", "strong"))
    return replace(semantics, default_agg=agg, evidence=tuple(evidence))


class ColumnChoiceError(ValueError):
    """Kullanıcının seçtiği kolon dosyada yok ya da istenen role uymuyor; kayıt yapılmadan söylenir."""


def _column_tokens(name: str) -> frozenset[str]:
    return frozenset(t for t in _slug(name).split("_") if t)


def _resolve_column(profile, name: str, kind: str):
    """Kullanıcının/modelin yazdığı kolon adını dosyadaki kolona bağlar: önce birebir, sonra büyük/küçük ve
    Türkçe harf farkı, sonra sözcük kapsaması ("TL Hacim" → "TL | Hacim/Volume (TL)"). Birden çok kolona
    uyuyorsa seçmez, adayları sayar; hiçbirine uymuyorsa kolon listesiyle reddeder."""
    col = profile.column(name)
    if col is not None:
        return col
    wanted = name.strip().casefold()
    hits = [c for c in profile.columns if c.name.strip().casefold() == wanted or _slug(c.name) == _slug(name)]
    if not hits:
        tokens = _column_tokens(name)
        if tokens:
            hits = [c for c in profile.columns if tokens <= _column_tokens(c.name)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ColumnChoiceError(f"{kind} kolonu {name!r} birden çok kolona uyuyor: "
                                + ", ".join(repr(c.name) for c in hits) + " — tam adını ver")
    raise ColumnChoiceError(f"{kind} kolonu {name!r} dosyada yok; kolonlar: "
                            + ", ".join(c.name for c in profile.columns))


def _apply_columns(mapping, profile, params: IngestParams):
    """Kullanıcının seçtiği tarih/değer/varlık kolonlarını öneriye uygular; uymayanı açıkça reddeder."""
    from dataclasses import replace

    from ..builder.profile import Evidence

    updates: dict[str, Any] = {}
    evidence = list(mapping.evidence)

    def _swap(field_name: str, value: Any, reason: str) -> None:
        nonlocal evidence
        updates[field_name] = value
        evidence = [e for e in evidence if e.field != field_name]
        evidence.append(Evidence(field_name, value, reason, "strong"))

    if params.date_column:
        col = _resolve_column(profile, params.date_column, "tarih")
        if not col.date_formats:
            raise ColumnChoiceError(f"{params.date_column!r} tarih olarak ayrışmıyor; tarih adayları: "
                                    + (", ".join(c.name for c in profile.date_candidates) or "yok"))
        _swap("observation_date_column", col.name, "kullanıcı seçimi")
        if not params.date_format:
            _swap("date_format", col.date_formats[0], f"{col.name} kolonunun biçimi")
    if params.value_column:
        col = _resolve_column(profile, params.value_column, "değer")
        if not col.numeric_under:
            raise ColumnChoiceError(f"{params.value_column!r} sayı olarak ayrışmıyor; sayısal kolonlar: "
                                    + (", ".join(c.name for c in profile.value_candidates) or "yok"))
        _swap("value_column", col.name, "kullanıcı seçimi")
        decimal, thousands = col.numeric_under[0]
        _swap("decimal_separator", decimal, f"{col.name} kolonu bu ayraçla ayrışıyor")
        updates["thousands_separator"] = thousands
    if params.entity_column:
        col = _resolve_column(profile, params.entity_column, "varlık")
        _swap("entity_id_column", col.name, "kullanıcı seçimi (varlık/boyut)")
    if updates:
        mapping = replace(mapping, **updates, evidence=tuple(evidence))
    return mapping


def _apply_declared(mapping, semantics, params: IngestParams):
    """Kullanıcı beyanı öneriyi tamamlar ya da geçersiz kılar; her alan kanıt satırıyla."""
    from dataclasses import replace

    from ..builder.profile import Evidence

    sem_updates: dict[str, Any] = {}
    sem_evidence = list(semantics.evidence)
    for field_name in ("unit", "measure_type", "default_agg", "frequency"):
        value = getattr(params, field_name)
        if value is None:
            continue
        sem_updates[field_name] = value
        sem_evidence = [e for e in sem_evidence if e.field != field_name]
        sem_evidence.append(Evidence(field_name, value, "kullanıcı beyanı (sohbette söylendi, model aktardı)", "strong"))
    if sem_updates:
        semantics = replace(semantics, **sem_updates, evidence=tuple(sem_evidence))
    if params.date_format:
        map_evidence = [e for e in mapping.evidence if e.field != "date_format"]
        map_evidence.append(Evidence("date_format", params.date_format, "kullanıcı beyanı", "strong"))
        mapping = replace(mapping, date_format=params.date_format, evidence=tuple(map_evidence))
    return mapping, semantics


class IngestFromUrlTool(Tool):
    name = "ingest_from_url"
    role = "execute"
    description = (
        "Kullanıcının getirdiği veri dosyasını veya rapor sayfasındaki eki (URL; HTML/PDF/CSV/TSV/XLSX/JSON) "
        "veri havuzuna TASLAK seri olarak ekler ve ne yaptığını belgeler. Dosyanın hangi kolonunun "
        "tarih, hangisinin değer olduğunu veriye bakarak kanıtıyla önerir; belirsizse eklemeden "
        "önce kullanıcıya sorar. Kullanıcı 'bu dosyayı ekle', 'şu linkteki veriyi yükle' dediğinde "
        "BU aracı kullan. HTML sayfası dosyaları resource_index ile, PDF tabloları table_index ve pages "
        "ile seçilir; ölçümler satırlardaysa value_row kullanılır. Birden çok sayısal kolon varsa kullanıcının "
        "andığı kolonu value_column ile ver (tarih için date_column, il/kurum için entity_column); tarih kolonu "
        "olmayan kesit tablosunda kullanıcının söylediği dönemi period ile ver ('Ağustos 2026'). Önceki çağrı "
        "seçenek döndürdüyse aynı locator ile uygun seçimi yap. Veri okunması kaydedildiği anlamına gelmez: EKLENDİ kartını bekle."
    )
    Params = IngestParams

    def __init__(
        self, lakehouse: LakehouseClient, cli: LakehouseCLI, *, allowed_root: Path,
        registry: object | None = None, dataset_prefix: str = "adhoc", session: Any = None, ocr: Any = None,
    ) -> None:
        self.ocr = ocr            # PDF/görsel belgeler için OCR istemcisi (ADR-0041)
        self.lakehouse = lakehouse
        self.cli = cli
        self.allowed_root = Path(allowed_root)
        self._registry = registry
        self.dataset_prefix = dataset_prefix
        self.session = session  # HTTP oturumu; testte sahte, üretimde requests'in kendisi

    # ------------------------------------------------------------------ belge (PDF/görsel)
    def _read_document(self, params: IngestParams):
        """PDF/görsel → OCR → seçilen tablo → izinli köke CSV (belgenin kendisi de yanına).

        Veri ekibinin CLI'ı yalnız tablo dosyası alır; RAW'a OCR tablosunun CSV'si girer, belgenin
        sha256'sı ve OCR modeli katalog açıklamasında ve kartta taşınır. Belge bayt bayt izinli
        kökte saklanır ki kanıt zinciri geriye doğru izlenebilsin."""
        if self.ocr is None:
            raise OcrUnavailable("PDF/görsel belge OCR istemcisi olmadan okunamaz (VISION_MODEL yapılandırılmamış).")
        content, media, outcome = read_bytes_for_profiling(
            params.locator, allowed_roots=[self.allowed_root], session=self.session
        )
        if content is None or not outcome.ok:
            return None, outcome, None, params.locator
        doc = ocr_document(content, media, client=self.ocr, url=params.locator.split("?")[0], pages=params.pages)
        page = extract_ocr_page(params.locator, doc)
        if not page.tables:
            raise OcrUnavailable(f"Belgede OCR tablo bulamadı ({len(doc.pages)} sayfa okundu). {doc.note()}")
        idx = params.table_index if params.table_index is not None else max(
            range(len(page.tables)), key=lambda i: page.tables[i].shape[0] * page.tables[i].shape[1])
        if idx < 0 or idx >= len(page.tables):
            raise OcrUnavailable(f"table_index {idx} yok; belgede {len(page.tables)} tablo var.")
        table = page.tables[idx]
        page_no = doc.tables[idx][0] if idx < len(doc.tables) else "?"
        stem = f"ocr_{doc.sha256[:12]}"
        self.allowed_root.mkdir(parents=True, exist_ok=True)
        suffix = Path(params.locator.split("?")[0]).suffix.lower() or ".bin"
        (self.allowed_root / f"{stem}{suffix}").write_bytes(content)
        csv_path = self.allowed_root / f"{stem}_p{page_no}_t{idx}.csv"
        table.to_csv(csv_path, index=False)
        note = (f"Belge {params.locator} (sha256 {doc.sha256}) OCR ile okundu: model {doc.model}, sayfa {page_no}, "
                f"tablo #{idx} ({len(table)}×{len(table.columns)}); sayılar doğrulanmadı, kaynağın kendisiyle "
                f"karşılaştırılmalı. Belge kopyası: {stem}{suffix}.")
        # OCR tablosu sayıya çevrilmiş DataFrame; profilci metin hücre bekler.
        frame = table.astype(str).where(table.notna(), "")
        return frame, outcome, note, str(csv_path)

    def _stage_frame(self, frame: Any, locator: str) -> str:
        """Türetilen tabloyu (dönem eklenmiş kesit, satır-ölçüm matrisi) izinli köke içerik adresli CSV olarak yazar.

        Veri ekibinin CLI'ı yalnız dosya alır; RAW'a bu CSV girer, kaynağın kendisi ve dönüşüm notu katalog
        açıklamasında ve kartta taşınır (OCR yolundaki `ocr_<sha>_*.csv` ile aynı kural)."""
        import hashlib

        self.allowed_root.mkdir(parents=True, exist_ok=True)
        csv = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
        digest = hashlib.sha256(csv).hexdigest()[:12]
        stem = _UPLOAD_PREFIX.sub("", Path(locator.split("?")[0]).stem) or "tablo"
        path = self.allowed_root / f"derived_{stem}_{digest}.csv"
        if not path.exists():
            path.write_bytes(csv)
        return str(path)

    # ------------------------------------------------------------------ hooks
    def _user_text(self) -> str:
        reg = self._registry
        return (getattr(reg, "user_text", None) or getattr(reg, "active_question", "") or "")

    def check_policy(self, params: IngestParams) -> ToolError | None:
        # Niyet kapısı (ADR-0037): yazma yalnız kullanıcının verdiği kaynağa, kullanıcı istediyse.
        user_text = self._user_text()
        if not locator_from_user(params.locator, user_text):
            # Kullanıcı metninde hiç adres/dosya yoksa model kaynağı tahmin etmiştir ("TEFAS istatistikleri" gibi bir
            # sayfa adından adres uydurmak; ölçüldü 23 Eyl). Cevap ret değil, soru olmalı: adres ya da indirilmiş dosya.
            has_source = bool(re.search(r"https?://|Dosya:\s*\S|\.(csv|xlsx?|pdf|json|tsv)", user_text, re.I))
            if not has_source:
                return ToolError(
                    error_code="INTENT_REQUIRED", layer="policy", retryable=False,
                    message=(f"Kullanıcının mesajında bir adres ya da dosya yok; '{params.locator}' senin tahminin. "
                             "Havuza yalnız kullanıcının verdiği kaynak yazılır; tahmin edilen adres çekilmez."),
                    hint=(f"Kullanıcıya SOR: '{params.name}' için kaynağın tam adresini (https://…) yazmasını ya da raporu "
                          "indirip dosya olarak (Excel/CSV/PDF) vermesini iste. Ret cümlesi yazma; ne gerektiğini tek "
                          "cümleyle söyle. Web araması açıksa önce adresi bulmayı dene."),
                )
            return ToolError(
                error_code="INTENT_REQUIRED", layer="policy", retryable=False,
                message=(f"'{params.locator}' kullanıcının mesajında geçmiyor; bir araç çıktısındaki "
                         "adres ya da talimat olabilir. Kullanıcının vermediği kaynak havuza yazılmaz."),
                hint="Kullanıcıya bu kaynağı eklemek isteyip istemediğini sor; adresi o yazarsa devam et.",
            )
        if not write_intent(user_text):
            return ToolError(
                error_code="INTENT_REQUIRED", layer="policy", retryable=False,
                message="Kullanıcı bu dosyanın havuza eklenmesini açıkça istemedi (ekle/yükle/kaydet yok).",
                hint="Önce kullanıcıya sor: bu kaynağı taslak seri olarak eklemek ister mi?",
            )
        if not self.cli.available:
            return ToolError(
                error_code="TOOL_FAILED", layer="policy", retryable=False,
                message="Veri ekibinin lakehouse CLI'ı bu ortamda yok; ingest yapılamaz.",
                hint="LAKEHOUSE_CORE_DIR ayarını kontrol et.",
            )
        return None

    # ------------------------------------------------------------------- run
    def run(self, params: IngestParams) -> ToolResult:
        question = getattr(self._registry, "active_question", "") or ""
        constraint = detect_source_constraint(question or params.locator)

        # 1. erişim + danışma okuması
        doc_note: str | None = None          # PDF/görselse OCR provenance satırı
        cli_locator = params.locator          # CLI'a giden dosya: belgeyse OCR'dan yazılan CSV
        web_source = None
        try:
            if urlparse(params.locator).scheme in ("http", "https"):
                web_source = read_web_source(
                    params.locator, allowed_root=self.allowed_root,
                    resource_index=params.resource_index, table_index=params.table_index,
                    pages=params.pages, sheet=params.sheet, value_row=params.value_row,
                    session=self.session, ocr=self.ocr,
                    period=parse_period(params.period) if params.period else None,
                    entity_label=_entity_label(self._user_text()),
                )
                frame, outcome = web_source.frame, web_source.outcome
            elif is_document("", params.locator.split("?")[0]):
                frame, outcome, doc_note, cli_locator = self._read_document(params)
            else:
                frame, outcome = read_table_for_profiling(
                    params.locator, allowed_roots=[self.allowed_root], session=self.session, sheet=params.sheet)
        except SourceSelection as exc:
            return ToolResult(content=f"EKLENMEDİ — kaynak seçimi veya ek bilgi gerekli:\n{exc}", ok=True)
        except ReadRefused as exc:
            bare = _bare_locator(params.locator)
            return ToolResult.fail(
                "ACCESS_BLOCKED", f"Kaynak okunamadı: {exc}",
                hint=("Dosya bu sohbete eklenmemiş: yalnız adı geçiyor, sunucuda kopyası yok. Kullanıcıya dosyayı "
                      "📎 Dosya düğmesiyle (ya da sürükleyip bırakarak) eklemesini ve isteği aynı mesajda yazmasını söyle; "
                      "diskte arama yapma, adı tahmin etme." if bare
                      else "Dosyayı izinli klasöre koy ya da http(s) bir adres ver."),
                layer="access",
            )
        except OcrUnavailable as exc:
            return ToolResult.fail("TOOL_FAILED", str(exc), layer="harness", retryable=False,
                                   hint="Kullanıcıya belgenin OCR olmadan okunamadığını söyle; CSV/XLSX isteyebilirsin.")
        decision = decide(outcome, constraint)
        if not outcome.ok or frame is None:
            err = to_tool_error(outcome, decision)
            return ToolResult(content=err.render(), ok=False, error=err)

        # 2. beyan kapısı önce: kullanıcının söylemediği alan (birim, ölçüm tipi, kolon seçimi, dönem) yok sayılır ve sorulur.
        invented = undeclared(params, self._user_text())
        if invented:
            params = params.model_copy(update={k.split("=")[0]: None for k in invented})

        # 2a. Şekil düzeltmeleri (21 Eyl): ölçümleri satırda gösteren rapor matrisi uzun tabloya; tarih kolonu olmayan
        # kesit tablosu kullanıcının beyan ettiği döneme bağlanır. İkisi de kaynağı değiştirmez: türetilen tablo
        # izinli köke CSV olarak yazılır, kaynak kopyası ve dönüşüm notu provenance'ta taşınır.
        period = parse_period(params.period) if params.period else None
        if params.period and period is None:
            return ToolResult.fail(
                "TOOL_FAILED", f"Dönem {params.period!r} anlaşılamadı; kabul edilen yazımlar: '2026-06-30', '2026-08', "
                "'Ağustos 2026', '2026Q2', '2025'.", hint="Kullanıcıya dönemi bu biçimlerden biriyle sor.",
                layer="data", retryable=False)
        derived_notes: list[str] = []
        local_matrix = None
        if web_source is None and params.value_row:
            try:
                local_matrix = measure_row_to_long(frame, params.value_row, period, entity_label=_entity_label(self._user_text()))
            except SourceSelection as exc:
                return ToolResult(content=f"EKLENMEDİ — kaynak seçimi veya ek bilgi gerekli:\n{exc}", ok=True)
            if local_matrix is not None:
                frame, note, matrix_frequency = local_matrix
                derived_notes.append(note.strip())
                if matrix_frequency and not params.frequency:
                    params = params.model_copy(update={"frequency": matrix_frequency})
        if web_source is None and Path(params.locator.split("?")[0]).suffix.lower() == ".xls":
            derived_notes.append("Eski Excel (.xls) xlrd ile okundu ve CSV'ye çevrildi; veri havuzu .xls almaz, "
                                 "kaynak dosya değiştirilmedi.")
        profile = profile_table(frame)
        year_cols = [c for c in profile.date_candidates if c.date_formats == ("%Y",)]
        if year_cols and local_matrix is None:      # yerel dosya da adres de: web kaynağında çerçeve stage() ile gider
            chosen = params.date_column if params.date_column in {c.name for c in year_cols} else year_cols[0].name
            frame, note = year_column_to_dates(frame, chosen)
            derived_notes.append(note)
            if not params.frequency:
                params = params.model_copy(update={"frequency": "yearly"})
            profile = profile_table(frame)
        if period is not None and not profile.date_candidates:
            by_month = month_names_to_dates(frame, int(period[0][:4])) if local_matrix is None else None
            if by_month is not None:
                # Ay adı sütunu + yıl: her satır kendi ayına (Borsa altın PDF'i, TÜİK aylık tabloları).
                frame, note = by_month
                derived_notes.append(note)
                if not params.frequency:
                    params = params.model_copy(update={"frequency": "monthly"})
            else:
                frame = frame.copy()
                frame.insert(0, "observation_date", period[0])
                derived_notes.append(f"Kaynakta tarih kolonu yok; tüm satırlar kullanıcının beyan ettiği döneme bağlandı: "
                                     f"dönem sonu {period[0]} ('{params.period}').")
                if period[1] and not params.frequency:
                    params = params.model_copy(update={"frequency": period[1]})
            profile = profile_table(frame)
        if derived_notes:
            if web_source is not None:
                web_source.frame = frame
                web_source.note += " " + " ".join(derived_notes)
            else:
                cli_locator = self._stage_frame(frame, params.locator)
                doc_note = ((doc_note + " ") if doc_note else "") + " ".join(derived_notes) + f" Türetilen tablo: {Path(cli_locator).name}."

        # 2b. profil + öneri
        key = params.series_key or _slug(_UPLOAD_PREFIX.sub("", Path(params.locator.split("?")[0]).stem))
        series_id = f"adhoc:{key}"
        mapping, semantics = propose(profile, frame, series_id=series_id)
        if mapping is not None and semantics is not None:
            from ..builder.profile import Evidence
            matrix_entity = web_source.entity_column if web_source is not None else (_entity_label(self._user_text()) if local_matrix else None)
            matrix_frequency = web_source.frequency if web_source is not None else (local_matrix[2] if local_matrix else None)
            turkish = web_source.turkish_numbers if web_source is not None else bool(local_matrix)
            if matrix_entity:
                mapping = replace(mapping, entity_id_column=matrix_entity,
                    evidence=tuple(e for e in mapping.evidence if e.field != "entity_id_column") +
                    (Evidence("entity_id_column", matrix_entity, "rapor sütunlarından korunan kurum başlıkları", "strong"),))
            if matrix_frequency:
                semantics = replace(semantics, frequency=matrix_frequency,
                    evidence=tuple(e for e in semantics.evidence if e.field != "frequency") +
                    (Evidence("frequency", matrix_frequency, "kaynak tablonun açık ay/yıl dönem başlığı ya da beyan edilen dönem", "strong"),))
            if turkish:
                mapping = replace(mapping, decimal_separator=",", thousands_separator=".",
                    evidence=tuple(e for e in mapping.evidence if e.field != "decimal_separator") +
                    (Evidence("decimal_separator", ",", "Türkçe aylık rapor: ondalık virgül, binlik nokta; tüm değerler doğrulanır", "strong"),))
            mapping, semantics = _apply_declared(mapping, semantics, params)
            try:
                before = mapping.value_column
                mapping = _apply_columns(mapping, profile, params)
                if mapping.value_column != before and params.unit is None:
                    # Profilci birimi kendi seçtiği kolonun başlığından çıkarmıştı; kolon değişti, birim yeniden okunur.
                    semantics = replace(semantics, unit=None,
                                        evidence=tuple(e for e in semantics.evidence if e.field != "unit"))
            except ColumnChoiceError as exc:
                return ToolResult.fail("TOOL_FAILED", f"Kolon seçimi uygulanamadı: {exc}",
                                       hint="Kullanıcıya dosyadaki kolonları göster ve doğru kolonu sor.", layer="data", retryable=False)
            semantics = _default_agg_from_measure(semantics)
        if mapping is None or semantics is None:
            has_date = bool(getattr(profile, "date_candidates", ()))
            return ToolResult.fail(
                "TOOL_FAILED",
                f"Tabloda tarih ve değer kolonu birlikte bulunamadı ({len(frame)} satır, "
                f"{len(frame.columns)} sütun: {', '.join(map(str, frame.columns))})."
                + ("" if has_date else " Tarih kolonu hiç yok: tarihsiz tablolar (il × değer gibi) veri havuzuna "
                                       "kalıcı seri olarak kaydedilemez; web_url ile oturumda okunup birleştirilebilir."),
                hint=("Kullanıcıya hangi kolonun tarih, hangisinin değer olduğunu sor." if has_date
                      else "Kullanıcıya söyle: tablo tarihsiz, kalıcı kayıt yapılamaz; oturumda analiz için web_url ile okuyabilirsin."),
                layer="data", retryable=False,
            )

        # 2b. ilgi kapısı (V3 §3.9, builder/relevance.py): dosya BİÇİMİ doğru olabilir ama
        # sorulan şeyle ilgisi olmayabilir (konut kredisi sorusuna otobüs tarifesi; 2023
        # dosyası 2024 sorusuna). Üç deterministik ölçüt: dönem, terim, katalog alias'ı.
        # Uygulanabilen ölçütlerin hiçbiri tutmuyorsa yazılmaz, kullanıcıya sorulur. Aynı
        # oturumda bakılan öbür dosyaların puanları hatırlanır: "doğru + yanlış dosya"
        # durumunda kart hangisinin daha uygun göründüğünü söyler (kanıt paneline de gider).
        specs_all = list(self.lakehouse.list_datasets())
        # Adreslerden yalnız dosya adı soru metninde kalır (dizin parçaları terim değildir; dosyanın adıyla anılması ilgidir).
        relevance = assess_relevance(
            _locator_names(question), _locator_names(self._user_text()), params.locator, frame, mapping,
            catalog=catalog_entries(s for s in specs_all if getattr(s, "source", "") != "adhoc"),
        )
        # 2b'. uygunluk kapısı (core/fitness.py, 15 Eyl): sözcük örtüşmesi değil GEREKSİNİM — soru hangi ölçümü/varlığı/
        # dönemi/granülariteyi istiyor, dosya hangisini sunuyor. Anlamca yakın yanlış dosyayı (fiyat endeksi ≠ bakiye;
        # 459.904'lük "faiz oranı") ilgi kapısı geçiriyordu (ölçüldü: ret %6 → %98, docs/experiments/ueb_wrongfile_ablation).
        # Ret kararını uygunluk verir; ilgi kapısı gereksinim çıkarılamayan soruda ("bu dosyayı ekle") yedek olarak kalır.
        sig = signature_of(frame, params.locator, mapping=mapping, semantics=semantics)
        lexicon = Lexicon.load().with_catalog(s for s in specs_all if getattr(s, "source", "") != "adhoc")
        # Soru yoksa kullanıcı metni; dosya adları/adresler çıkarılır ("konut.csv belirsiz.csv ekle" → 'konut' gereksinim olmasın).
        gate_q = question or " ".join(t for t in self._user_text().split() if not re.search(r"[./\\]", t))
        fit = assess_fitness(gate_q, sig, lexicon)
        quality = table_quality(frame, sig, gate_q)
        seen = self.__dict__.setdefault("_relevance_seen", {})
        seen[params.locator] = fit.score
        better = [f"{loc} ({sc:.2f})" for loc, sc in seen.items() if loc != params.locator and sc > fit.score]
        confirmed = params.user_confirmed and user_confirmed(self._user_text())
        irrelevant = fit.decision == "reject" or (not fit.required and relevance.irrelevant)
        if irrelevant and not confirmed:
            return ToolResult.fail(
                "FILE_IRRELEVANT",
                (fit.stop_message() if fit.decision == "reject" else
                 f"'{Path(params.locator.split('?')[0]).name}' dosyası sorulan şeyle ilgili görünmüyor: "
                 + "; ".join(relevance.lines()[1:]) + "."),
                hint=("Kullanıcıya sor: doğru dosya bu mu? Dosyada şu kolonlar var: "
                      + ", ".join(map(str, frame.columns)) + ". "
                      + (f"Daha uygun görünen dosya(lar): {', '.join(better)}. " if better else "")
                      + "Kullanıcı 'yine de ekle / doğru dosya bu' derse aynı çağrıyı user_confirmed=true ile yap. "
                        "Sayı uydurma, seriyi eklenmiş sayma."),
                layer="policy", retryable=False,
                candidates=[loc for loc, _ in sorted(seen.items(), key=lambda kv: -kv[1]) if loc != params.locator][:5],
            )

        # 2c. çapraz kontrol (builder/crosscheck.py): ilgi kapısı TEK bir katalog serisi bulduysa
        # ve frekans aynıysa örtüşen dönemler yan yana konur — örtüşüyor / birim farkı / ÇELİŞİYOR.
        # Engellemez; karta ve kanıt paneline gider. "Doğrulandı" değil "örtüşüyor" denir.
        crosscheck = cross_check(self.lakehouse, specs_all, relevance.catalog_hit_ids, frame, mapping, semantics)
        # 2d. birim tahmini (builder/unit_guess.py): belgede birim yoksa boş soru yerine kanıtlı aday;
        # yine yazılmaz, kullanıcı onaylar (beyan kuralı: unit= yalnız kullanıcı metninde geçerse).
        unit_hint = None
        unit_from_source: str | None = None
        if semantics.unit is None:
            # Önce seçilen değer kolonunun kendi başlığı ("TL Hacim (TL)"), sonra dosya adı/öbür kolonlar/belge notu:
            # öbür kolonun birimi ("Miktar (KG)") seçilen seriye sızmasın (ölçüldü 21 Eyl, altın PDF'i).
            from ..builder.unit_guess import _from_text as _unit_from_text
            unit_hint = _unit_from_text([str(mapping.value_column)]) or guess_unit(
                texts=[Path(params.locator.split("?")[0]).name, *map(str, frame.columns), doc_note or "",
                       (web_source.note if web_source is not None else "")],
                crosscheck=crosscheck, values=file_points(frame, mapping).values(),
            )
            # Kaynak birimi AÇIKÇA yazıyorsa (kolon başlığı "(Milyon TL)", "%", "kg", tablo başlığı "endeks")
            # sorulmaz, kaynaktan alınır ve kartta söylenir (21 Eyl; "birim vermeden kaydedilebilir mi?").
            # Ölçek/aralık tahminleri (katalog oranı, 0–100 arası) yine sorulur: onlar kaynağın sözü değil.
            if unit_hint is not None and unit_hint.confidence == "strong" and unit_hint.reason.startswith("metinde"):
                from ..builder.profile import Evidence
                unit_from_source = unit_hint.unit
                semantics = replace(semantics, unit=unit_hint.unit,
                                    evidence=tuple(e for e in semantics.evidence if e.field != "unit") +
                                    (Evidence("unit", unit_hint.unit, f"kaynak metninden alındı: {unit_hint.reason}", "strong"),))
                unit_hint = None
        if params.unit is None and semantics.unit is not None:
            unit_from_source = semantics.unit          # profilci kolon başlığından ("(milyon TL)") ya da yukarıdaki ipucundan

        # 3. doğrulama — yayınlama kurallarıyla
        # Çakışma yalnız küratörlü/başka kaynaklı serilerle: aynı dosyanın ikinci ingest'i
        # kendi taslağına düşer ve veri ekibinin yayınlama kuralı onu çözer (aynı satır
        # "değişmeyen", aynı tarihe farklı değer "revizyon çatışması" — sessiz ezme yok).
        existing = [s.dataset_id for s in specs_all if s.source != "adhoc"]
        report = verify_mapping(frame, mapping, existing_series_ids=existing)
        asks: list[str] = []
        if not report.ok:
            asks += [f"{c.name}: {c.detail}" for c in report.failures]
        # Çok kolonlu dosya (21 Eyl): "en dolu sayısal kolon" sessiz tahminiyle yanlış seri kaydedilir (TLREF'te
        # kapanış yerine en düşük değer). Birden çok sayısal kolon varsa ve kullanıcı seçmediyse sorulur.
        numeric_columns = [c.name for c in profile.value_candidates if c.name != mapping.observation_date_column]
        if len(numeric_columns) > 1 and not params.value_column:
            asks.append(f"değer kolonu: {len(numeric_columns)} sayısal kolon var ({', '.join(numeric_columns)}); "
                        f"öneri {mapping.value_column!r}. Kullanıcıya hangisinin kaydedileceğini sor; cevabı value_column ile aktar")
        if semantics.unit is None:
            if unit_hint is not None:
                asks.append(f"birim: belgede yazmıyor. {unit_hint.line()}. Kullanıcıya 'birim {unit_hint.unit!r} mi?' "
                            f"diye sor; onaylarsa aynı çağrıyı unit={unit_hint.unit!r} ile yap")
            else:
                asks.append("birim: veriden çıkarılamıyor; kaynağın birimi nedir (ör. milyon TL, %, adet)?")
        if semantics.frequency == "irregular":
            asks.append("frekans: gözlemlerden düzenli aralık belirlenemedi; kaynak günlük, aylık veya hangi sıklıkta yayımlanıyor?")
        if crosscheck is not None and crosscheck.verdict == "ÇELİŞİYOR":
            asks.append("çapraz kontrol: " + crosscheck.lines()[0] + " — kullanıcıya söyle; dosya mı katalog mu doğru, o karar versin")
        if invented:
            asks.append("beyan kullanıcıdan gelmeli: " + ", ".join(invented) +
                        " kullanıcı mesajında geçmiyor (model uydurmuş olabilir); kullanıcıya sor")
        if asks:
            lines = ["EKLENMEDİ — önce kullanıcıya sorulmalı:"] + [f"  - {a}" for a in asks]
            lines.append("\nÖNERİ (kanıtıyla):")
            lines += [f"  {e.field} = {e.value!r}  [{e.confidence}] {e.reason}" for e in mapping.evidence]
            lines += [f"  {e.field} = {e.value!r}  [{e.confidence}] {e.reason}" for e in semantics.evidence]
            if mapping.alternatives:
                lines.append("ALTERNATİFLER: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in mapping.alternatives.items()))
            lines.append("\nYAPACAĞIN: yukarıdaki soruları kullanıcıya sor; cevap gelince aynı aracı "
                         "series_key ile yeniden çağır. Sayı uydurma, seriyi eklenmiş sayma.")
            return ToolResult(content="\n".join(lines), ok=True,
                              artifacts={"proposal": mapping, "semantics": semantics, "report": report})

        # 4. yaz: okuyucuyu kapat → CLI → yeniden aç. DuckDB tek yazar kabul ediyor.
        #
        # Katalog kaydı DETERMİNİSTİK: aynı dosya + aynı öneri → bayt bayt aynı kayıt.
        # Ölçüldü: model ikinci koşuda farklı bir 'name' verdi, veri ekibinin sözleşmesi
        # "aynı draft farklı içerikle" diye reddetti (doğru davranış). Kullanıcının verdiği
        # ad karta girer, kataloğa değil; katalog adı dosya ve seri anahtarından türer.
        if web_source is not None:
            cli_locator, doc_note = web_source.stage(self.allowed_root)
        catalog_name = f"{key} — {_source_display_name(params.locator)} (taslak)"
        description = (
            f"Kullanıcının getirdiği kaynaktan ({params.locator}) Architect tarafından taslak olarak "
            f"eklendi. Eşleme ve anlam veriden önerildi; ölçüm tipi {semantics.measure_type!r} "
            f"({next(e.reason for e in semantics.evidence if e.field == 'measure_type')}). "
            "Kullanılabilmesi için bir insanın onaylayıp kataloğa alması gerekir."
            + (f" {doc_note}" if doc_note else "")
        )
        # Süreçteki BÜTÜN okuyucular kapanmalı, yalnız bu adaptör değil: DuckDB aynı
        # süreçteki salt-okunur bağlantıları tek örnekte paylaşır ve dosya kilidi son
        # bağlantı kapanana kadar kalır (ölçüldü: eski bir agent örneğinin bağlantısı
        # yazar alt sürecin kilidini engelledi).
        self.lakehouse.close()
        release_connections(getattr(self.lakehouse, "db_path", None))
        try:
            out = self.cli.ingest_file(
                locator=cli_locator, dataset_id=f"{self.dataset_prefix}_{key}",
                mapping=mapping, semantics=semantics, name=catalog_name, description=description,
                allowed_root=self.allowed_root,
                delimiter="," if cli_locator != params.locator else None,   # kendi yazdığımız CSV: ayraç bilinir
            )
        finally:
            self.lakehouse.reload()

        if not out.ok:
            conflict = "already exists as a draft with different content" in (out.error or "")
            return ToolResult.fail(
                "TOOL_FAILED",
                (f"'{series_id}' adlı bir taslak zaten var ve içeriği bu dosyadan farklı; veri "
                 "ekibinin sözleşmesi sessizce üstüne yazmaz." if conflict
                 else f"Ingest başarısız: {out.error or out.status}. {out.raw[-400:]}"),
                hint=("Kullanıcıya sor: başka bir series_key ile yeni taslak mı, yoksa mevcut taslak "
                      "korunsun mu? Aynı çağrıyı tekrarlama." if conflict
                      else "Hata mesajı bir eşleme sorununu söylüyorsa kullanıcıya sor; tekrar deneme."),
                layer="harness", retryable=False,
            )

        # 5. belge kartı — kullanıcıya gidecek olan
        card = [
            f"EKLENDİ: {series_id} — {params.name}",
            f"katalog adı: {catalog_name}",
            f"kaynak: {params.locator}" + (f" → çıkarılan tablo {Path(cli_locator).name}" if doc_note else ""),
            *([f"{'Kaynak işleme' if web_source else 'OCR'}: {doc_note}"] if doc_note else []),
            f"satır: {report.rows_mapped} eşlendi, {report.rows_null_value} boş değer korundu"
            + (f"; yazılan {out.rows_written}, değişmeyen {out.rows_unchanged}" if out.rows_written is not None else ""),
            f"katman: adhoc (taslak) — Silver'a ve Gold'a girmez; bir insan onaylayınca kataloğa alınır",
            "eşleme: " + ", ".join(f"{e.field}={e.value!r}" for e in mapping.evidence if e.field in
                                   ("observation_date_column", "date_format", "value_column", "decimal_separator", "entity_id_column")),
            f"anlam: frekans={semantics.frequency} ölçüm={semantics.measure_type} birim={semantics.unit}"
            + (f" (birim kaynaktan alındı; yanlışsa 'birim …' diyerek düzeltin)" if unit_from_source else "")
            + (f" toplama={semantics.default_agg}" if getattr(semantics, "default_agg", None) else "")
            + ("  ⚠ ölçüm tipi kanıtsız, 'unknown' olarak kaydedildi" if semantics.measure_type == "unknown" else ""),
            "kanıt: " + " | ".join(f"{e.field}: {e.reason}" for e in semantics.evidence if e.confidence != "none"),
            *out.provenance_lines(),
        ]
        if out.warnings:
            card.append(f"parser uyarısı: {out.warnings} (quality_flag='source_warning')")
        card.append(fit.lines()[0] + (" — kullanıcı onayıyla eklendi" if confirmed and irrelevant else ""))
        card.append(relevance.lines()[0])
        if relevance.period_ok is False:
            card.append("⚠ dosyanın tarih aralığı sorudaki yılı KAPSAMIYOR; o yıl için bu seriden sayı çıkmaz")
        card += [f"UYARI: {q}" for q in quality]
        if better:
            card.append(f"NOT: bu oturumda bakılan {', '.join(better)} bu soruya daha uygun görünüyor")
        if crosscheck is not None:
            card.extend(crosscheck.lines())
        card.append(render_for_model(outcome, decision).splitlines()[0])
        # D03 (ADR-0068): eklenen taslak, kapsamı kartta gösterilmiş bekleyen terfi işlemi olur.
        from ..core.approvals import PendingOp, book_of
        book_of(self._registry).register(PendingOp(
            series_id=series_id, operation="promote", shown_turn=int(getattr(self._registry, "turn", 0) or 0),
            summary=f"{series_id} ({params.name}) taslağı kataloğa aktif seri olarak alınacak"))
        return ToolResult(content="\n".join(card),
                          artifacts={"ingest": out, "proposal": mapping, "relevance": relevance,
                                     "fitness": {"decision": fit.decision, "score": fit.score, "reasons": list(fit.reasons),
                                                 "dims": dict(fit.dims), "required": list(fit.required), "present": list(fit.present),
                                                 "signature": sig.describe(), "coverage": sig.coverage(), "source": params.locator,
                                                 "quality": list(quality),
                                                 "confirmed": bool(confirmed)},
                                     **({"crosscheck": crosscheck} if crosscheck is not None else {})})


__all__ = ["IngestFromUrlTool", "IngestParams"]
