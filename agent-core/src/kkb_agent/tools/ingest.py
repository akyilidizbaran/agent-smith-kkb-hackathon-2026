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
from ..builder.read import ReadRefused, read_table_for_profiling
from ..builder.verify import verify_mapping
from ..adapters.duckdb_lakehouse import release_connections
from ..contracts.lakehouse import LakehouseClient
from ..core.access_policy import decide, detect_source_constraint, render_for_model, to_tool_error
from ..core.intent import locator_from_user, write_intent
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult


class IngestParams(BaseModel):
    locator: str = Field(description="Yerel dosya yolu ya da http(s) URL'i (CSV, TSV, XLSX, JSON)")
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
        registry: object | None = None, dataset_prefix: str = "adhoc", session: Any = None,
    ) -> None:
        self.lakehouse = lakehouse
        self.cli = cli
        self.allowed_root = Path(allowed_root)
        self._registry = registry
        self.dataset_prefix = dataset_prefix
        self.session = session  # HTTP oturumu; testte sahte, üretimde requests'in kendisi

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
        try:
            frame, outcome = read_table_for_profiling(
                params.locator, allowed_roots=[self.allowed_root], session=self.session
            )
        except ReadRefused as exc:
            return ToolResult.fail(
                "ACCESS_BLOCKED", f"Kaynak okunamadı: {exc}",
                hint="Dosyayı izinli klasöre koy ya da http(s) bir adres ver.", layer="access",
            )
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

        # 3. doğrulama — yayınlama kurallarıyla
        # Çakışma yalnız küratörlü/başka kaynaklı serilerle: aynı dosyanın ikinci ingest'i
        # kendi taslağına düşer ve veri ekibinin yayınlama kuralı onu çözer (aynı satır
        # "değişmeyen", aynı tarihe farklı değer "revizyon çatışması" — sessiz ezme yok).
        existing = [s.dataset_id for s in self.lakehouse.list_datasets() if s.source != "adhoc"]
        report = verify_mapping(frame, mapping, existing_series_ids=existing)
        asks: list[str] = []
        if not report.ok:
            asks += [f"{c.name}: {c.detail}" for c in report.failures]
        if semantics.unit is None:
            asks.append("birim: veriden çıkarılamıyor; kaynağın birimi nedir (ör. milyon TL, %, adet)?")
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
        )
        # Süreçteki BÜTÜN okuyucular kapanmalı, yalnız bu adaptör değil: DuckDB aynı
        # süreçteki salt-okunur bağlantıları tek örnekte paylaşır ve dosya kilidi son
        # bağlantı kapanana kadar kalır (ölçüldü: eski bir agent örneğinin bağlantısı
        # yazar alt sürecin kilidini engelledi).
        self.lakehouse.close()
        release_connections(getattr(self.lakehouse, "db_path", None))
        try:
            out = self.cli.ingest_file(
                locator=params.locator, dataset_id=f"{self.dataset_prefix}_{key}",
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
            f"kaynak: {params.locator}",
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
        card.append(render_for_model(outcome, decision).splitlines()[0])
        return ToolResult(content="\n".join(card), artifacts={"ingest": out, "proposal": mapping})


__all__ = ["IngestFromUrlTool", "IngestParams"]
