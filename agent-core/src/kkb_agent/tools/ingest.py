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
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..builder.ingest import LakehouseCLI
from ..builder.profile import profile_table, propose
from ..builder.read import ReadRefused, read_bytes_for_profiling, read_table_for_profiling
from ..builder.crosscheck import cross_check, file_points
from ..builder.relevance import assess as assess_relevance, catalog_entries, user_confirmed
from ..builder.unit_guess import guess_unit
from ..builder.verify import verify_mapping
from ..adapters.duckdb_lakehouse import release_connections
from ..contracts.lakehouse import LakehouseClient
from ..core.access_policy import decide, detect_source_constraint, render_for_model, to_tool_error
from ..core.intent import locator_from_user, write_intent
from ..vision.ocr import is_document, ocr_document
from ..web.html import extract_ocr_page
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult


class OcrUnavailable(RuntimeError):
    """Belge var ama OCR yok ya da tablo bulunamadı: uydurma yok, kullanıcıya söylenir."""


class IngestParams(BaseModel):
    locator: str = Field(description="Yerel dosya yolu ya da http(s) URL'i (CSV, TSV, XLSX, JSON; PDF/PNG/JPG belgeler OCR ile okunur)")
    table_index: int | None = Field(default=None, description="PDF/görselde birden çok tablo varsa hangisi (0 tabanlı); boşsa en büyük tablo")
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
    # İlgi kapısı (V3 §3.9): dosya soruyla ilgisiz görünürse yazılmaz ve sorulur. Kullanıcı
    # "yine de ekle / doğru dosya bu" derse model bu bayrağı açar; bayrak yalnız kullanıcı
    # metninde onay sözü varsa geçerlidir (beyan kuralıyla aynı: modelin sözü yetmez).
    user_confirmed: bool = Field(
        default=False,
        description="Kullanıcı 'yine de ekle' ya da 'doğru dosya bu' dediyse true; ilgi kapısını geçer.",
    )


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
    return bad


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
        "Kullanıcının getirdiği yeni bir veri dosyasını (yerel yol ya da URL; CSV/TSV/XLSX/JSON) "
        "veri havuzuna TASLAK seri olarak ekler ve ne yaptığını belgeler. Dosyanın hangi kolonunun "
        "tarih, hangisinin değer olduğunu veriye bakarak kanıtıyla önerir; belirsizse eklemeden "
        "önce kullanıcıya sorar. Kullanıcı 'bu dosyayı ekle', 'şu linkteki veriyi yükle' dediğinde "
        "BU aracı kullan."
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

    # ------------------------------------------------------------------ hooks
    def _user_text(self) -> str:
        reg = self._registry
        return (getattr(reg, "user_text", None) or getattr(reg, "active_question", "") or "")

    def check_policy(self, params: IngestParams) -> ToolError | None:
        # Niyet kapısı (ADR-0037): yazma yalnız kullanıcının verdiği kaynağa, kullanıcı istediyse.
        user_text = self._user_text()
        if not locator_from_user(params.locator, user_text):
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
        try:
            if is_document("", params.locator.split("?")[0]):
                frame, outcome, doc_note, cli_locator = self._read_document(params)
            else:
                frame, outcome = read_table_for_profiling(
                    params.locator, allowed_roots=[self.allowed_root], session=self.session, sheet=params.sheet)
        except ReadRefused as exc:
            return ToolResult.fail(
                "ACCESS_BLOCKED", f"Kaynak okunamadı: {exc}",
                hint="Dosyayı izinli klasöre koy ya da http(s) bir adres ver.", layer="access",
            )
        except OcrUnavailable as exc:
            return ToolResult.fail("TOOL_FAILED", str(exc), layer="harness", retryable=False,
                                   hint="Kullanıcıya belgenin OCR olmadan okunamadığını söyle; CSV/XLSX isteyebilirsin.")
        decision = decide(outcome, constraint)
        if not outcome.ok or frame is None:
            err = to_tool_error(outcome, decision)
            return ToolResult(content=err.render(), ok=False, error=err)

        # 2. profil + öneri
        key = params.series_key or _slug(Path(params.locator.split("?")[0]).stem)
        series_id = f"adhoc:{key}"
        profile = profile_table(frame)
        mapping, semantics = propose(profile, frame, series_id=series_id)
        invented = undeclared(params, self._user_text())
        if invented:
            # Kullanıcının söylemediği beyan yok sayılır; alan boş kalır ve aşağıda sorulur.
            params = params.model_copy(update={k.split("=")[0]: None for k in invented})
        if mapping is not None and semantics is not None:
            mapping, semantics = _apply_declared(mapping, semantics, params)
        if mapping is None or semantics is None:
            return ToolResult.fail(
                "TOOL_FAILED",
                f"Tabloda tarih ve değer kolonu birlikte bulunamadı ({len(frame)} satır, "
                f"{len(frame.columns)} sütun: {', '.join(map(str, frame.columns))}).",
                hint="Kullanıcıya hangi kolonun tarih, hangisinin değer olduğunu sor.",
                layer="data", retryable=False,
            )

        # 2b. ilgi kapısı (V3 §3.9, builder/relevance.py): dosya BİÇİMİ doğru olabilir ama
        # sorulan şeyle ilgisi olmayabilir (konut kredisi sorusuna otobüs tarifesi; 2023
        # dosyası 2024 sorusuna). Üç deterministik ölçüt: dönem, terim, katalog alias'ı.
        # Uygulanabilen ölçütlerin hiçbiri tutmuyorsa yazılmaz, kullanıcıya sorulur. Aynı
        # oturumda bakılan öbür dosyaların puanları hatırlanır: "doğru + yanlış dosya"
        # durumunda kart hangisinin daha uygun göründüğünü söyler (kanıt paneline de gider).
        specs_all = list(self.lakehouse.list_datasets())
        relevance = assess_relevance(
            question, self._user_text(), params.locator, frame, mapping,
            catalog=catalog_entries(s for s in specs_all if getattr(s, "source", "") != "adhoc"),
        )
        seen = self.__dict__.setdefault("_relevance_seen", {})
        seen[params.locator] = relevance.score
        better = [f"{loc} ({sc}/{relevance.applicable})" for loc, sc in seen.items()
                  if loc != params.locator and sc > relevance.score]
        confirmed = params.user_confirmed and user_confirmed(self._user_text())
        if relevance.irrelevant and not confirmed:
            return ToolResult.fail(
                "FILE_IRRELEVANT",
                (f"'{Path(params.locator.split('?')[0]).name}' dosyası sorulan şeyle ilgili görünmüyor: "
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
        if semantics.unit is None:
            unit_hint = guess_unit(
                texts=[Path(params.locator.split("?")[0]).name, *map(str, frame.columns), doc_note or ""],
                crosscheck=crosscheck, values=file_points(frame, mapping).values(),
            )

        # 3. doğrulama — yayınlama kurallarıyla
        # Çakışma yalnız küratörlü/başka kaynaklı serilerle: aynı dosyanın ikinci ingest'i
        # kendi taslağına düşer ve veri ekibinin yayınlama kuralı onu çözer (aynı satır
        # "değişmeyen", aynı tarihe farklı değer "revizyon çatışması" — sessiz ezme yok).
        existing = [s.dataset_id for s in specs_all if s.source != "adhoc"]
        report = verify_mapping(frame, mapping, existing_series_ids=existing)
        asks: list[str] = []
        if not report.ok:
            asks += [f"{c.name}: {c.detail}" for c in report.failures]
        if semantics.unit is None:
            if unit_hint is not None:
                asks.append(f"birim: belgede yazmıyor. {unit_hint.line()}. Kullanıcıya 'birim {unit_hint.unit!r} mi?' "
                            f"diye sor; onaylarsa aynı çağrıyı unit={unit_hint.unit!r} ile yap")
            else:
                asks.append("birim: veriden çıkarılamıyor; kaynağın birimi nedir (ör. milyon TL, %, adet)?")
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
        source_name = Path(params.locator.split("?")[0]).name
        catalog_name = f"{key} — {source_name} (taslak)"
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
            f"kaynak: {params.locator}" + (f" → OCR tablosu {Path(cli_locator).name}" if doc_note else ""),
            *([f"OCR: {doc_note}"] if doc_note else []),
            f"satır: {report.rows_mapped} eşlendi, {report.rows_null_value} boş değer korundu"
            + (f"; yazılan {out.rows_written}, değişmeyen {out.rows_unchanged}" if out.rows_written is not None else ""),
            f"katman: adhoc (taslak) — Silver'a ve Gold'a girmez; bir insan onaylayınca kataloğa alınır",
            "eşleme: " + ", ".join(f"{e.field}={e.value!r}" for e in mapping.evidence if e.field in
                                   ("observation_date_column", "date_format", "value_column", "decimal_separator", "entity_id_column")),
            f"anlam: frekans={semantics.frequency} ölçüm={semantics.measure_type} birim={semantics.unit}"
            + ("  ⚠ ölçüm tipi kanıtsız, 'unknown' olarak kaydedildi" if semantics.measure_type == "unknown" else ""),
            "kanıt: " + " | ".join(f"{e.field}: {e.reason}" for e in semantics.evidence if e.confidence != "none"),
            *out.provenance_lines(),
        ]
        if out.warnings:
            card.append(f"parser uyarısı: {out.warnings} (quality_flag='source_warning')")
        card.append(relevance.lines()[0] + (" — kullanıcı onayıyla eklendi" if confirmed and relevance.irrelevant else ""))
        if relevance.period_ok is False:
            card.append("⚠ dosyanın tarih aralığı sorudaki yılı KAPSAMIYOR; o yıl için bu seriden sayı çıkmaz")
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
                                     **({"crosscheck": crosscheck} if crosscheck is not None else {})})


__all__ = ["IngestFromUrlTool", "IngestParams"]
