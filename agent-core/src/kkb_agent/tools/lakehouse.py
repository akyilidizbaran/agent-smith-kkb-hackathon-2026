"""Lakehouse Tool ailesi — agent'ın veri havuzuna erişimi.

Yarışma şartnamesi bunu tek bir 'Lakehouse Tool' olarak sayıyor; burada üç
tek-amaçlı araca bölündü. Sebep pratik: küçük parametreli ve tek işi olan
araçlarda küçük modellerin isabet oranı belirgin biçimde yüksek. Motor
açısından hepsi aynı kayıt defterinde duran sıradan araçlardır.

Akış modele şu sırayı dayatır: önce KEŞFET, sonra İNCELE, sonra SORGULA.
Bu sıra, modelin var olmayan kolon adı uydurmasını büyük ölçüde engeller.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from ..contracts.catalog import Frequency, ColumnRole
from ..contracts.lakehouse import LakehouseClient, LakehouseError
from ..core.facets import extract_facets, province_of
from ..domain import kisa_terim
from ..core.errors import ToolError
from ..core.sql_identifiers import quote_known_identifiers
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace


class SearchParams(BaseModel):
    query: str = Field(
        description="Aranan konuyu anlatan kısa Türkçe ifade, ör. 'aylık {example_entity}'"
    )
    limit: int = Field(
        default=5, ge=1, le=40,
        description="Kaç aday listelensin (varsayılan 5). Kullanıcı eşleşen serileri LİSTELEMEK istiyorsa 40 ver.",
    )


class LakehouseSearchTool(Tool):
    name = "lakehouse_search"
    role = "retrieve"
    description = (
        "Veri havuzunda hangi tabloların bulunduğunu keşfeder. Bir soruyu cevaplamadan ÖNCE "
        "hangi verinin mevcut olduğunu öğrenmek için bunu kullan. Tablo adlarını ve ne "
        "içerdiklerini döndürür."
    )
    Params = SearchParams

    #: Üst üste kaç boş arama sonrası "bu yoldan sonuç çıkmaz" denir. Ölçüldü: gerçek
    #: DB'de olmayan bir seri için model on kez farklı sözcükle aradı ve bütçeyi yaktı.
    EMPTY_LIMIT = 2

    #: Üst üste kaç "aranan seri yüklenmemiş" sonucundan sonra durulur. Ölçüldü (G12, gerçek
    #: DB): üç arama üç kez konut serisini "taşıt eşleşmedi" notuyla döndürdü, model sonra
    #: SQL ile keşfe girişti: 10 LLM çağrısı, 125 bin token, cevap yine "yüklenmemiş".
    PENDING_LIMIT = 2

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse
        self._empty_streak = 0
        self._pending_streak = 0
        # Arama defteri (core/search_ledger): tur içinde tekil adayları, yeni aday üretimini ve istenen yüzleri izler.
        # Aramayı çağrı sayısı değil verim durdurur; ajan `ledger.begin_turn(soru)` ile turu açar.
        from ..core.search_ledger import SearchLedger
        self.ledger = SearchLedger()

    def begin_turn(self, turn_id: int) -> None:
        """Search limits apply inside one turn, never to a later user intent."""
        del turn_id
        self._empty_streak = 0
        self._pending_streak = 0
        self.ledger.begin_turn("")

    def run(self, params: SearchParams) -> ToolResult:
        specs = self.lakehouse.search_datasets(params.query, limit=int(params.limit))
        if not specs:
            self.ledger.record(params.query, [])
            self._empty_streak += 1
            search_un = getattr(self.lakehouse, "search_uningested", None)
            pending = list(search_un(params.query, 5)) if callable(search_un) else []
            lines = ["Bu konuyla ilgili SORGULANABİLİR seri yok."]
            if pending:
                lines.append("Katalogda tanımlı ama bu veri havuzuna HENÜZ YÜKLENMEMİŞ seriler:")
                lines += [f"  - {sid} — {name}" for sid, name in pending]
                lines.append("YAPACAĞIN: bu seriler için sorgu yazma; kullanıcıya verinin katalogda "
                             "tanımlı ama henüz çekilmemiş olduğunu söyle. Yeniden arama yapma.")
            else:
                lines.append("YAPACAĞIN: soruyu farklı sözcüklerle EN FAZLA bir kez daha ara; yine yoksa "
                             "kullanıcıya bu verinin havuzda bulunmadığını söyle. Birden çok kalemi birlikte "
                             "aradıysan her kalemi TEK TEK ara: biri yoksa "
                             "diğerleriyle devam et, eksik olanı cevapta belirt (M02 bulgusu L3-02).")
            if self._empty_streak >= self.EMPTY_LIMIT or pending:
                self._empty_streak = 0
                return ToolResult.fail(
                    "DATASET_NOT_FOUND", "\n".join(lines), layer="reference", retryable=False,
                    candidates=[sid for sid, _ in pending],
                )
            return ToolResult(content="\n".join(lines), ok=True)
        self._empty_streak = 0
        verdict = self.ledger.record(params.query, specs)
        terms = getattr(self.lakehouse, "last_search_terms", {}) or {}
        from ..labels import spec_origin
        lines = ["Bulunan tablolar:"]
        for s in specs:
            # ADR-0082: kimlik SQL içindir; kullanıcıya kaynak adıyla anlatılır ("hesaplanmış tablo (… verisinden)").
            lines.append(
                f"- {s.dataset_id}: {s.name}. {s.description[:180]} "
                f"[frekans: {s.frequency.value}, kapsam: {s.coverage.start}→{s.coverage.end}, kaynak: {spec_origin(s)}]"
            )
            matched, unmatched = terms.get(s.dataset_id, ([], []))
            if unmatched:
                # Ölçüldü: "taşıt kredisi" araması konut serisini "kredisi" ile buluyor; hangi
                # sözcüğün eşleşMEdiği yazılmazsa model konutu taşıt diye kullanabilir.
                lines.append(f"    eşleşen: {', '.join(matched) or '—'} | EŞLEŞMEYEN: {', '.join(unmatched)} "
                             "— bu seri sorunun tamamını karşılamıyor olabilir")
            # Kimlik ile fiziksel erişim kalıbı aynı şey olmak zorunda değil. Seed'de
            # dataset_id gerçekten tablo adı; Silver'da 'evds:TP.KTF12' bir tablo DEĞİL,
            # tek bir ilişkideki bir satır kümesinin kimliği. Bu satır olmadığında model
            # arama çıktısındaki kimliği FROM'a yazıyordu (ölçüldü: Silver şemasında
            # SQL_FAILED, tek kök neden). Kalıbı adaptör üretiyor (ADR-0024, series_sql):
            # çalıştırılabilir SQL veriyoruz, tarif değil — tarif kopyalanınca bozuluyor.
            hint = self._access_sql(s)
            if hint:
                lines.append(f"    '{s.dataset_id}' bir tablo adı DEĞİL. SQL'de şöyle eriş: {hint}")
        # Sorunun eşleşmeyen sözcükleri yüklenmemiş bir seriyi işaret ediyorsa bunu da söyle:
        # "yok" ile "var ama yüklenmemiş" aynı cevap değildir (ADR-0026).
        unmatched_all = sorted({t for m, u in terms.values() for t in u})
        every_hit_partial = bool(terms) and all(u for _, u in terms.values())
        search_un = getattr(self.lakehouse, "search_uningested", None)
        pending: list[tuple[str, str]] = []
        if unmatched_all and callable(search_un):
            pending = list(search_un(" ".join(unmatched_all), 5))
        if pending and every_hit_partial:
            # Aranan şeyin kendisi yüklenmemiş; bulunanlar yalnız ortak sözcükle geldi.
            self._pending_streak += 1
            lines.append("Katalogda tanımlı ama HENÜZ YÜKLENMEMİŞ ve soruya uyan seriler: "
                         + "; ".join(f"{sid} — {name}" for sid, name in pending)
                         + ". Yukarıdaki tablolar sorunun yalnız bir kısmıyla eşleşiyor; onları "
                         "aranan serinin yerine KULLANMA. Kullanıcıya verinin henüz çekilmediğini söyle.")
            if self._pending_streak >= self.PENDING_LIMIT:
                self._pending_streak = 0
                return ToolResult.fail(
                    "DATASET_NOT_FOUND", "\n".join(lines), layer="reference", retryable=False,
                    candidates=[sid for sid, _ in pending],
                )
        elif pending:
            lines.append("Katalogda tanımlı ama HENÜZ YÜKLENMEMİŞ ve soruya uyan seriler: "
                         + "; ".join(f"{sid} — {name}" for sid, name in pending)
                         + ". Bunlar için sorgu yazma; kullanıcıya verinin henüz çekilmediğini söyle.")
        else:
            self._pending_streak = 0
        lines.append("\nSorgu yazmadan önce lakehouse_describe ile kolonları incele.")
        lines.append(verdict.line())
        rows = self.ledger.candidates_frame().to_dict("records")
        if verdict.saturated:
            # Doygunluk: son aramalar yeni aday üretmedi. Bütçe dolduğu için değil, arama artık bir şey katmadığı için
            # durulur; tam aday listesi burada (model kısa anlatısıyla listenin yerine geçemez, ajan tabloya da koyar).
            lines.append(f"SEARCH_SATURATED: arama doydu ({verdict.searches} arama, {verdict.total_unique} tekil aday). "
                         "YENİDEN ARAMA YAPMA. Ya adaylardan uygun olanı seçip sorgula ya da istenen yüz "
                         "(frekans/il/kaynak) adaylarda yoksa bunu kullanıcıya açıkça söyle; 'veri yok' deme, adayları say.")
            lines.append("Tüm adaylar: " + "; ".join(f"{r['series_id']} ({r['frequency']}, {r['source']})" for r in rows))
        return ToolResult(content="\n".join(lines),
                          artifacts={"candidates": rows, "search_ledger": self.ledger.summary()})

    def _access_sql(self, spec) -> str | None:
        """Kimliğin tablo adı olmadığı adaptörler için çalıştırılabilir erişim kalıbı.

        Seed adaptöründe `dataset_id` gerçekten tablo adıdır ve satır yalnız gürültü
        olur; orada `source_detail` boştur ve bu metot None döner. Kalıbın nasıl
        yazılacağını adaptör bilir, araç değil.
        """
        measure = next((c for c in spec.columns if c.role is ColumnRole.MEASURE), None)
        if measure is None:
            return None
        try:
            sql = self.lakehouse.series_sql(
                spec.dataset_id, key_column=spec.time_column, value_column=measure.name
            )
        except Exception:  # noqa: BLE001 — ipucu üretilemiyorsa arama sonucu yine geçerli
            return None
        # Kimliğin tablo adı olup olmadığını tahmin etmiyoruz: adaptörün ürettiği SQL'e
        # bakıyoruz. `FROM <dataset_id>` yazıyorsa kimlik zaten tablo adıdır ve ipucu
        # yalnız gürültü olur (seed adaptörü böyle). Silver'da ilişki başka bir addır.
        if re.search(rf"\bFROM\s+{re.escape(spec.dataset_id)}\b", sql, re.IGNORECASE):
            return None
        return sql


def _dataset_missing(lakehouse: LakehouseClient, dataset_id: str) -> ToolError | None:
    """Kimlik katalogda yoksa referans hatası; adaylar en yakın 8, tüm katalog değil.

    Eski hâli bütün kataloğu aday olarak listeliyordu — 4 tabloda faydalı, 1620 seride
    hata mesajının kendisi hataya dönüşüyor (ADR-0026 dersi). Adaylar aramadan gelir.
    """
    try:
        lakehouse.get_dataset(dataset_id)
    except LakehouseError as exc:
        near = [s.dataset_id for s in lakehouse.search_datasets(dataset_id, limit=8)]
        return ToolError(
            error_code="DATASET_NOT_FOUND", message=str(exc),
            hint="lakehouse_search ile doğru kimliği bul.",
            candidates=near, layer="reference",
        )
    return None


class DescribeParams(BaseModel):
    dataset_id: str = Field(description="lakehouse_search'ten dönen tablo kimliği")


class LakehouseDescribeTool(Tool):
    name = "lakehouse_describe"
    role = "retrieve"
    description = (
        "Bir tablonun kolonlarını, birimlerini, kümülatif olup olmadığını ve örnek satırlarını "
        "gösterir. SQL yazmadan ÖNCE mutlaka çağır: kolon adlarını ve birimleri buradan öğren."
    )
    Params = DescribeParams

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse

    def validate_refs(self, params: DescribeParams) -> ToolError | None:
        return _dataset_missing(self.lakehouse, params.dataset_id)

    def run(self, params: DescribeParams) -> ToolResult:
        spec = self.lakehouse.get_dataset(params.dataset_id)
        sample = self.lakehouse.preview(params.dataset_id, n=5)

        content = spec.to_prompt_card()
        content += "\n\nÖrnek satırlar:\n" + sample.data.to_string(index=False)
        return ToolResult(content=content)


class QueryParams(BaseModel):
    sql: str = Field(
        description="Çalıştırılacak DuckDB SQL sorgusu. Sadece SELECT/WITH. "
        "Kolon ve tablo adları lakehouse_describe çıktısıyla birebir aynı olmalı."
    )
    purpose: str = Field(
        description="Bu sorgunun neyi hesapladığını anlatan tek cümlelik Türkçe açıklama. "
        "Kullanıcıya gösterilecek ve analiz geçmişine kaydedilecek."
    )
    as_active_table: bool = Field(
        default=True,
        description="Bu sorgu kullanıcının sorusunu cevaplayan SONUÇ mu? Öyleyse true — "
        "tek satırlık bir cevap olsa bile true. Sadece kolon adı doğrulama gibi ara "
        "kontroller için false kullan. Emin değilsen true.",
    )


class LakehouseQueryTool(Tool):
    name = "lakehouse_query"
    description = (
        "Veri havuzunda SQL çalıştırır ve sonucu döndürür. Toplama, ortalama, yüzde değişim "
        "gibi TÜM hesapları bu araçla yaptır, kendin hesaplama. Sonuç aktif analiz tablosu "
        "olarak kaydedilir."
    )
    Params = QueryParams

    #: Ay/çeyrek/yıl kutusuna toplama/ortalama: frekans dönüşümüdür, kural kataloğundur.
    _PERIOD_AGG = re.compile(
        r"(strftime\s*\([^)]*%Y-%m|date_trunc\s*\(\s*'(month|quarter|year)'|extract\s*\(\s*(month|quarter|year)\b|"
        r"year\s*\(|month\s*\(|quarter\s*\()", re.I,
    )
    _AGG_FN = re.compile(r"\b(avg|sum|mean|min|max)\s*\(", re.I)

    def __init__(
        self,
        lakehouse: LakehouseClient,
        workspace: AnalysisWorkspace,
        registry: object | None = None,
        *,
        gold_available: bool = False,
    ) -> None:
        self.lakehouse = lakehouse
        self.workspace = workspace
        # Sorulan soruya erişim: atlanan dönem kısıtını yakalamak için.
        self._registry = registry
        # Gold araçları kayıtlıysa ay/çeyrek toplaması SQL'de yapılmaz (ADR-0039).
        self.gold_available = gold_available

    def normalize_args(self, raw_args: dict[str, Any]) -> dict[str, Any]:
        """Quote schema-backed complex column names before the shared SQL guard."""
        sql = raw_args.get("sql")
        if not isinstance(sql, str):
            return raw_args
        list_datasets = getattr(self.lakehouse, "list_datasets", None)
        if not callable(list_datasets):
            return raw_args
        columns = [
            column.name
            for spec in list_datasets()
            for column in getattr(spec, "columns", [])
        ]
        normalized = quote_known_identifiers(sql, columns)
        return raw_args if normalized == sql else {**raw_args, "sql": normalized}

    def check_policy(self, params: QueryParams) -> ToolError | None:
        """Sorgu çalışmadan önce reddet: uyarı olarak eklendiğinde model onu okuyup
        yine de cevaba geçiyordu (ölçüldü: 0/2). Kapsam kontrolünde işe yarayan kalıp
        bu — modele seçenek bırakmamak (ADR-0010). Mesajlar ADR-0017'deki gibi."""
        kapsam_disi_soru = self._soru_kapsam_disi()
        if kapsam_disi_soru:
            can_fetch = callable(getattr(self._registry, "get", None)) and self._registry.get("ingest_source") is not None
            return ToolError(
                error_code="OUT_OF_COVERAGE", message=kapsam_disi_soru,
                hint="Bu dönem için sorgu çalıştırma. Kullanıcıya verinin hangi tarihe "
                     "kadar yayımlandığını söyle; istersen mevcut son dönemi teklif et."
                     + (" Kullanıcı bu dönemi kaynağından çekmek isterse ingest_source ile çek, sonra sorgula." if can_fetch else ""),
                layer="data",
            )
        if self.gold_available and self._is_period_aggregation(params.sql):
            # Ölçüldü: onaylanmış sıcaklık serisinde model "aylık ortalama"yı SQL'de AVG ile aldı;
            # katalogdaki kural (index → avg) ile örtüştüğü için sayı doğru çıktı ama kanıt zinciri
            # koptu (gözlem izi yok) ve kural stok olsaydı sessizce yanlış olurdu. Seçenek bırakılmaz.
            return ToolError(
                error_code="GOLD_REQUIRED", layer="policy", retryable=True,
                message="Bu sorgu dönemleri (ay/çeyrek/yıl) toplayıp ortalıyor; frekans dönüşümü SQL'de değil "
                        "Gold'da yapılır, kural katalogdan gelir.",
                hint="gold_align (tek seri) ya da gold_join (birden çok seri) çağır: target_frequency='monthly' "
                     "ya da 'quarterly', period_from/period_to ile dönem. Seri doğrulanmamışsa kullanıcının "
                     "onayı gerekir. Yıllık için gold_align aylık sonucu üzerinde workspace_query kullan.",
            )
        bayat = self._bayat_gold(params.sql)
        if bayat:
            # K02-T09 (A24): bayat Gold yalnız etiketlenmiyor. Etiketli uyarıyla dönen eski değer cevaba giriyordu;
            # sorgu çalışmadan reddedilir, tablo kurulmaz.
            return ToolError(
                error_code="GOLD_STALE", layer="data", retryable=False,
                message=(f"{', '.join(bayat)} bayat: Silver bu tablo kurulduktan sonra değişti; bu tablodan sayı verilmez."),
                hint=("Aynı hesabı canlı Silver'dan gold_align / gold_join ile yeniden yap." if self.gold_available else
                      "Kullanıcıya tablonun bayat olduğunu ve operatörün `python -m lakehouse gold` ile yeniden kurması "
                      "gerektiğini söyle; eski değeri verme."),
                candidates=bayat,
            )
        uyusmazlik = self._frekans_uyusmazligi(params.sql)
        if uyusmazlik:
            return uyusmazlik
        uyusmazlik = self._boyut_uyusmazligi(params.sql)
        if uyusmazlik:
            return uyusmazlik
        eksik_donem = self._atlanmis_donem_filtresi(params.sql)
        if eksik_donem:
            yil = eksik_donem.split(",")[0].strip()
            return ToolError(
                error_code="MISSING_PERIOD_FILTER",
                message=f"Sorguda dönem filtresi yok. Kullanıcı {eksik_donem} dönemini sordu ama "
                        f"sorgun tablonun tamamını getiriyor.",
                hint=f"Sorguya dönem kısıtını ekleyip tekrar çalıştır, ör. {self._donem_ipucu(yil)}",
                layer="policy",
            )
        return None

    def _boyut_uyusmazligi(self, sql: str) -> ToolError | None:
        """Reject silent geography/source substitutions during recovery.

        Frequency validation alone is insufficient: a provincial quarterly
        table can still be selected while a national monthly BDDK table was
        requested. Such a semantic substitution is never a valid fallback.
        """
        question = getattr(self._registry, "active_question", "") or ""
        facets = extract_facets(question)
        national = bool(re.search(r"\b(?:ulusal|national|türkiye geneli|turkiye geneli|ülke geneli|ulke geneli)\b", question, re.I))
        try:
            specs = list(self.lakehouse.list_datasets())
        except Exception:  # noqa: BLE001
            return None
        used = [spec for spec in specs if re.search(rf"(?<![\w.]){re.escape(spec.dataset_id)}(?![\w])", sql, re.I)]
        if not used:
            return None
        used_provinces = [province_of(f"{spec.dataset_id} {spec.name}") for spec in used]
        if national and any(used_provinces):
            return ToolError(
                error_code="GEOGRAPHY_MISMATCH", layer="policy", retryable=True,
                message="Ulusal veri istendi ancak sorgu il bazlı bir seri okuyor; il verisi ulusal verinin yerine kullanılamaz.",
                hint="Ulusal ve istenen frekanstaki doğru seriyi lakehouse_search ile bulup sorgula.",
                candidates=[spec.dataset_id for spec, province in zip(used, used_provinces) if not province],
            )
        if facets.provinces and any(province not in facets.provinces for province in used_provinces):
            return ToolError(
                error_code="GEOGRAPHY_MISMATCH", layer="policy", retryable=True,
                message="Sorgudaki seri kullanıcının istediği il ile uyuşmuyor; başka ilin ya da ulusal serinin verisi yerine kullanılamaz.",
                hint="İstenen il için doğru seriyi lakehouse_search ile bulup sorgula.",
                candidates=[spec.dataset_id for spec, province in zip(used, used_provinces) if province in facets.provinces],
            )
        if facets.sources and any(str(getattr(spec, "source", "")) not in facets.sources for spec in used):
            return ToolError(
                error_code="SOURCE_MISMATCH", layer="policy", retryable=True,
                message="Sorgudaki kaynak kullanıcının istediği kaynakla uyuşmuyor; başka kaynağın verisi sessizce kullanılamaz.",
                hint="İstenen kaynak için doğru seriyi lakehouse_search ile bulup sorgula.",
                candidates=[spec.dataset_id for spec in used if str(getattr(spec, "source", "")) in facets.sources],
            )
        return None

    def _bayat_gold(self, sql: str) -> list[str]:
        stale = getattr(self.lakehouse, "stale_gold_tables", None)
        if not callable(stale):
            return []
        used = {m.lower() for m in re.findall(r"\bgold\.[a-z0-9_]+", sql or "", re.I)}
        return [t for t in stale() if t.lower() in used]

    _ARALIK_SONRASI = re.compile(r"(19\d{2}|20\d{2})\s*'?\s*(?:den|dan|ten|tan)\s+(?:bu yana|beri|itibaren|sonra|günümüze|bugüne)|"
                                 r"(19\d{2}|20\d{2})\s+(?:başından|sonrası|ve sonrası)", re.I)
    _ARALIK_ONCESI = re.compile(r"(19\d{2}|20\d{2})\s*'?\s*(?:a|e|ya|ye)\s+kadar|(19\d{2}|20\d{2})\s+(?:öncesi|sonuna kadar)", re.I)

    def _donem_ipucu(self, yil: str) -> str:
        """"2021'den bu yana" tek yıl değil, aralıktır. Ölçüldü (G16): ipucu '= 2021' deyince model
        yalnız 2021'i çekti, 12 satırla kırılma aradı. Sorunun ifadesine göre >= / <= / BETWEEN."""
        soru = getattr(self._registry, "active_question", "") or ""
        yillar = sorted(set(re.findall(r"\b(19\d{2}|20\d{2})\b", soru)))
        if len(yillar) >= 2:
            return f"WHERE EXTRACT(year FROM <dönem_kolonu>) BETWEEN {yillar[0]} AND {yillar[-1]}"
        m = self._ARALIK_SONRASI.search(soru)
        if m and (m.group(1) or m.group(2)) == yil:
            return f"WHERE EXTRACT(year FROM <dönem_kolonu>) >= {yil}  (soru '{yil}'den bu yana' diyor: aralık, tek yıl değil)"
        m = self._ARALIK_ONCESI.search(soru)
        if m and (m.group(1) or m.group(2)) == yil:
            return f"WHERE EXTRACT(year FROM <dönem_kolonu>) <= {yil}"
        return f"WHERE EXTRACT(year FROM <dönem_kolonu>) = {yil}"

    def run(self, params: QueryParams) -> ToolResult:
        # SQL guard sınır doğrulayıcıda çalıştı (UNSAFE_SQL orada); buraya gelen bir
        # hata artık çalışma hatasıdır ve tekrar denemeyle çözülebilir.
        try:
            result = self.lakehouse.execute_sql(params.sql)
        except LakehouseError as exc:
            return ToolResult.fail(
                "SQL_FAILED", str(exc),
                hint="SQL'i düzeltip tekrar dene; kolon adlarını lakehouse_describe "
                     "çıktısıyla karşılaştır.",
                layer="data",
            )

        if result.is_empty:
            # Boş sonucun iki farklı sebebi var ve modele söylenecek şey taban tabana zıt:
            # (a) filtre yanlış  -> düzelt ve tekrar dene
            # (b) dönem kapsam dışı -> TEKRAR DENEME, kullanıcıya verinin olmadığını söyle
            # Ayrımı yapmazsak model (b) durumunda sonsuza kadar denemeye devam ediyor;
            # ölçümde her seferinde 12 adım harcayıp adım limitini yakıyordu.
            out_of_range = self._out_of_coverage(params.sql)
            if out_of_range:
                return ToolResult(
                    content=(
                        "SONUÇ: Bu veri kaynakta bulunmuyor. Bu bir hata değildir, "
                        "sorgun doğruydu; istenen dönem veri setinde yok.\n"
                        f"{out_of_range}\n"
                        "ŞİMDİ YAPACAĞIN: Araç çağırmayı bırak ve kullanıcıya tek "
                        "paragrafta şunu söyle: istediği dönemin verisi mevcut değil ve "
                        "elde hangi tarih aralığının bulunduğu. Sayı tahmin etme, başka "
                        "sorgu deneme, SQL veya teknik ayrıntı paylaşma."
                    ),
                    ok=True,
                    provenance=result.provenance,
                    artifacts={"availability_status": "CONFIRMED_ABSENT"},
                )
            return ToolResult(
                content="Sorgu çalıştı ancak hiç satır dönmedi. Dönem aralığı kapsam içinde, "
                "yani sorun büyük olasılıkla filtre değerinde. Kalem/kategori adını "
                "lakehouse_distinct_values ile doğrula.",
                ok=True,
                provenance=result.provenance,
                artifacts={"availability_status": "RETRIEVAL_FAILED"},
            )

        if params.as_active_table:
            self.workspace.set_table(
                result.data, description=params.purpose, provenance=result.provenance
            )
            self.workspace.title = params.purpose
        else:
            # K03 ekran provası bulgusu: bakış modunda (aktif tablo değişmez) dönen sonuç kanıt havuzuna girmiyordu; model faizleri
            # bu sonuçtan doğru yazdı ("40,54" ← 40.536) ama panel "tabloda yok" dedi. workspace_query'deki gibi bakış kaydı.
            self.workspace.note_peek(params.sql, result.data)

        # Modele TAM tablo değil, özet gider: context window'u koruyoruz. Sınır boyuta bağlı (core/preview, PART 41):
        # ≤24 satır tamamı (12 satırın 10'u gösterilince model kalan ayları "yok" sanıyordu — UEB A15/A06/A24), üstü baş+son.
        from ..core.preview import preview_table

        df = result.data
        content = (
            f"Sorgu başarılı: {len(df)} satır, {len(df.columns)} sütun.\n"
            f"Sütunlar: {', '.join(df.columns)}\n"
            + preview_table(df, where="aktif analiz tablosunda" if params.as_active_table else "bu sorgunun sonucunda")
        )
        units = self._units_for(df.columns, result.provenance.dataset_ids)
        if units:
            content += "\nBirimler: " + ", ".join(units)
        content += f"\nKaynak: {result.provenance.summary()}"
        return ToolResult(content=content, data=df, provenance=result.provenance)

    def _is_period_aggregation(self, sql: str) -> bool:
        text = sql.lower()
        return bool(self._PERIOD_AGG.search(text) and self._AGG_FN.search(text) and "group by" in text)

    _FREKANS_SOZ = (
        ("günlük", Frequency.DAILY), ("gunluk", Frequency.DAILY),
        ("haftalık", Frequency.WEEKLY), ("haftalik", Frequency.WEEKLY),
        ("aylık", Frequency.MONTHLY), ("aylik", Frequency.MONTHLY),
        ("çeyreklik", Frequency.QUARTERLY), ("ceyreklik", Frequency.QUARTERLY),
        ("yıllık", Frequency.YEARLY), ("yillik", Frequency.YEARLY),
    )
    _FREKANS_SIRA = {Frequency.DAILY: 0, Frequency.WEEKLY: 1, Frequency.MONTHLY: 2,
                     Frequency.QUARTERLY: 3, Frequency.YEARLY: 4}

    def _frekans_uyusmazligi(self, sql: str) -> ToolError | None:
        """Soru tek bir frekans söylüyor (aylık) ve sorgunun okuduğu her kaynak ondan KABA ise
        (çeyreklik, yıllık) sorgu çalışmaz: kabadan ince üretilemez. İnceden kaba (haftalıktan aylık)
        serbesttir, o Gold'un işi. Ölçüldü (G16): model "aylık ... büyüme hızı" sorusuna hazır
        çeyreklik Gold tablosunu okudu, 22 satırla kırılma aradı; cevap tutarlı ama soruya değil."""
        soru = (getattr(self._registry, "active_question", "") or "").lower()
        istenen = {f for w, f in self._FREKANS_SOZ if re.search(rf"\b{w}", soru)}
        if len(istenen) != 1:
            return None
        hedef = next(iter(istenen))
        try:
            specs = list(self.lakehouse.list_datasets())
        except Exception:  # noqa: BLE001 — katalog okunamıyorsa guard susar
            return None
        okunan = [sp for sp in specs if re.search(rf"(?<![\w.]){re.escape(sp.dataset_id)}(?![\w])", sql)]
        if not okunan:
            return None
        kaba = [sp for sp in okunan
                if sp.frequency in self._FREKANS_SIRA and self._FREKANS_SIRA[sp.frequency] > self._FREKANS_SIRA[hedef]]
        if len(kaba) != len(okunan):
            return None
        ad = {Frequency.DAILY: "günlük", Frequency.WEEKLY: "haftalık", Frequency.MONTHLY: "aylık",
              Frequency.QUARTERLY: "çeyreklik", Frequency.YEARLY: "yıllık"}
        adaylar: list[str] = []
        try:
            for sp in self.lakehouse.search_datasets(soru):
                if sp.frequency == hedef and sp.dataset_id not in adaylar:
                    adaylar.append(sp.dataset_id)
                if len(adaylar) >= 5:
                    break
        except Exception:  # noqa: BLE001
            adaylar = []
        okunan_metin = ", ".join(f"{sp.dataset_id} ({ad.get(sp.frequency, sp.frequency)})" for sp in kaba)
        return ToolError(
            error_code="FREQUENCY_MISMATCH", layer="policy", retryable=True, candidates=adaylar,
            message=f"Kullanıcı {ad[hedef]} seri sordu; sorgu {okunan_metin} okuyor. "
                    f"{ad[kaba[0].frequency].capitalize()} kaynaktan {ad[hedef]} seri üretilemez.",
            hint=(f"{ad[hedef].capitalize()} frekanslı seriyi sorgula: " + ", ".join(adaylar)) if adaylar
                 else f"lakehouse_search ile {ad[hedef]} frekanslı seriyi bul ve onu sorgula.",
        )

    def _atlanmis_donem_filtresi(self, sql: str) -> str | None:
        """Soruda bir yıl geçiyor ama sorguda geçmiyorsa bunu bildirir.

        Ölçülmüş hata modu: "2025 yılında ... aylık göster" sorusuna model dönem
        filtresiz sorgu üretip 66 satır (tüm kapsam) döndürdü. Aynı kök neden üç
        golden vakasını birden düşürdü — kapsam dışı vakası dahil, çünkü sorguda
        yıl geçmeyince kapsam kontrolü de tetiklenmiyor.
        """
        soru = getattr(self._registry, "active_question", "") or ""
        sorulan = set(re.findall(r"\b(19\d{2}|20\d{2})\b", soru))
        if not sorulan:
            return None
        sorguda = set(re.findall(r"\b(19\d{2}|20\d{2})\b", sql))
        eksik = sorted(sorulan - sorguda)
        return ", ".join(eksik) if eksik else None

    _AYLAR = {
        "ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5,
        "haziran": 6, "temmuz": 7, "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9,
        "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12,
    }

    def _soru_kapsam_disi(self) -> str | None:
        """Sorudaki AY kapsamın dışındaysa sorguyu hiç çalıştırma.

        Kapsam kontrolü yıl çözünürlüğündeydi ve bu bir boşluk bırakıyordu: veri
        2026-06'da bitiyorken "2026 Ağustos kaç?" sorusunda 2026 kapsam içinde
        göründüğü için hiçbir şey tetiklenmiyordu. Model o yılın mevcut aylarını
        çekip tablo kuruyor, sonra "Ağustos yok" diyordu. Cevap doğru ama ekranda
        sayı dolu bir tablo duruyor; jüri bakışında bunlardan birinin Ağustos
        olduğu sanılabilir. Ölçüldü (L9-02): iki şemada da 0/3.

        Yalnız hiçbir serinin veremeyeceği dönemlerde tetikleniyor — kataloğun en
        geniş aralığı dışında kalmayan bir ay varsa karışmıyor.
        """
        soru = getattr(self._registry, "active_question", "") or ""
        if not soru:
            return None
        istenen: set[tuple[int, int]] = set()
        low = soru.lower()
        for ay_adi, ay in self._AYLAR.items():
            for m in re.finditer(rf"\b(19\d{{2}}|20\d{{2}})\b[^\d]{{0,12}}{ay_adi}\b", low):
                istenen.add((int(m.group(1)), ay))
            for m in re.finditer(rf"{ay_adi}\b[^\d]{{0,12}}\b(19\d{{2}}|20\d{{2}})\b", low):
                istenen.add((int(m.group(1)), ay))
        for m in re.finditer(r"\b(19\d{2}|20\d{2})[-/](0[1-9]|1[0-2])\b", low):
            istenen.add((int(m.group(1)), int(m.group(2))))
        if not istenen:
            return None

        specs = self.lakehouse.list_datasets()
        if not specs:
            return None
        ilk = min(s.coverage.start for s in specs)
        son = max(s.coverage.end for s in specs)
        sinirlar = ((ilk.year, ilk.month), (son.year, son.month))
        disarida = sorted(d for d in istenen if d < sinirlar[0] or d > sinirlar[1])
        if not disarida or len(disarida) != len(istenen):
            return None
        yazi = ", ".join(f"{y}-{ay:02d}" for y, ay in disarida)
        return (
            f"Sorulan dönem ({yazi}) veri kapsamının dışında. Veri {ilk} ile {son} "
            "arasını kapsıyor; bu dönem için hiçbir seride gözlem yok."
        )

    def _out_of_coverage(self, sql: str) -> str | None:
        """Sorgudaki yıllar katalog kapsamının dışında mı?

        Basit ama etkili: SQL içindeki dört haneli yılları toplayıp kataloğun
        kapsadığı aralıkla karşılaştırıyoruz. Amaç kesin SQL analizi değil,
        modele "bu veri yok" diyebilmek için yeterli sinyali üretmek.
        """
        years = {int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", sql)}
        if not years:
            return None
        for spec in self.lakehouse.list_datasets():
            if spec.dataset_id not in sql:
                continue
            lo, hi = spec.coverage.start.year, spec.coverage.end.year
            outside = sorted(y for y in years if y < lo or y > hi)
            if outside and not any(lo <= y <= hi for y in years):
                return (
                    f"Sorgudaki {', '.join(map(str, outside))} yılı/yılları "
                    f"{spec.dataset_id} tablosunun kapsamı dışında "
                    f"(mevcut aralık: {spec.coverage.start} → {spec.coverage.end})."
                )
        return None

    def _units_for(self, columns: list[str], dataset_ids: list[str]) -> list[str]:
        """Sonuç kolonlarının birimlerini katalogdan çözer.

        Model birim çevirisi yapmasın diye değeri DEĞİL, etiketi veriyoruz:
        "toplam = milyon TL". İlk ölçümde model 523.455'i hem 'milyon TL' hem
        '523.455 milyon' diye yazmıştı; belirsizliğin kaynağı buydu.
        """
        out: list[str] = []
        for ds_id in dataset_ids:
            try:
                spec = self.lakehouse.get_dataset(ds_id)
            except LakehouseError:
                continue
            for col in columns:
                cs = spec.column(col)
                if cs and cs.unit:
                    out.append(f"{col} = {cs.unit}")
        return out


class DistinctValuesParams(BaseModel):
    dataset_id: str = Field(description="Tablo kimliği")
    column: str = Field(
        description="Değerleri listelenecek kırılım kolonu, ör. '{example_category_column}'"
    )
    contains: str | None = Field(
        default=None,
        description="Sadece bu metni içeren değerleri getir (büyük/küçük harf duyarsız). "
        "Ör. '{example_entity}'. Boş bırakılırsa tüm değerler listelenir.",
    )
    limit: int = Field(default=20, description="En fazla kaç değer döndürülsün")


class LakehouseDistinctValuesTool(Tool):
    """Modelin en sık yaptığı hatayı kapatan araç.

    İlk ölçümde model 'Tüketici Kredileri - Konut' kaleminin adını TAHMİN etti,
    iki sorgu boşa gitti, sonra `LIKE '%Konut%'` ile üç ayrı kalemi birden
    çekip mükerrer topladı. Filtre yazmadan önce gerçek değerleri görmek bu
    sınıf hataların tamamını ortadan kaldırıyor.
    """

    name = "lakehouse_distinct_values"
    role = "retrieve"
    description = (
        "Bir kırılım kolonundaki GERÇEK değerleri listeler. Bir kalemi/kategoriyi filtrelemeden "
        "ÖNCE mutlaka bunu çağır — değer adını asla tahmin etme. Alt toplam satırlarını da "
        "işaretler, böylece mükerrer sayımdan kaçınırsın."
    )
    Params = DistinctValuesParams

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse

    def validate_refs(self, params: DistinctValuesParams) -> ToolError | None:
        missing = _dataset_missing(self.lakehouse, params.dataset_id)
        if missing:
            return missing
        spec = self.lakehouse.get_dataset(params.dataset_id)
        if spec.column(params.column) is None:
            return ToolError(
                error_code="COLUMN_NOT_FOUND",
                message=f"'{params.column}' kolonu {params.dataset_id} tablosunda yok. "
                        f"Mevcut kolonlar: {', '.join(c.name for c in spec.columns)}",
                hint="Kırılım kolonlarından birini seç.",
                candidates=[c.name for c in spec.columns],
                layer="reference",
            )
        return None

    def run(self, params: DistinctValuesParams) -> ToolResult:
        spec = self.lakehouse.get_dataset(params.dataset_id)

        col = params.column
        # Alt toplam bayrağı varsa birlikte göster: mükerrer sayımı önleyen sinyal.
        has_flag = spec.column("is_alt_toplam") is not None
        select = f"{col}, is_alt_toplam" if has_flag else col
        where = ""
        if params.contains:
            safe = params.contains.replace("'", "''")
            where = f"WHERE {col} ILIKE '%{safe}%'"

        sql = (
            f"SELECT DISTINCT {select} FROM {params.dataset_id} {where} "
            f"ORDER BY 1 LIMIT {int(params.limit)}"
        )
        try:
            result = self.lakehouse.execute_sql(sql)
        except LakehouseError as exc:
            return ToolResult.fail("SQL_FAILED", str(exc), layer="data")

        if result.is_empty:
            hint = f" ('{params.contains}' içeren değer yok)" if params.contains else ""
            return ToolResult(
                content=f"'{col}' kolonunda değer bulunamadı{hint}. "
                f"Daha genel bir arama terimi dene veya contains parametresini boş bırak.",
                ok=True,
            )

        # Filtresiz çağrı çok fazla değer döndürdüğünde model boğuluyor: ölçümde
        # 50 kalemlik liste sonrası model sorgu yazmadan cevaba geçti (0/7).
        # Tam listeyi basmak yerine daraltmaya yönlendiriyoruz.
        toplam = self._toplam_deger_sayisi(params.dataset_id, col)
        if params.contains is None and toplam > 15:
            ornekler = "\n".join(
                f"  - {getattr(r, col, r[0])}" for r in result.data.head(8).itertuples(index=False)
            )
            return ToolResult(
                content=(
                    f"'{col}' kolonunda {toplam} farklı değer var — hepsini listelemek yerine "
                    f"aradığın kalemi daralt.\n"
                    f"YAPACAĞIN: bu aracı contains parametresiyle tekrar çağır, ör. "
                    f"contains='{self._ornek_terim(result.data, col)}'\n\n"
                    f"İlk 8 değer (yalnızca fikir vermesi için, tam liste değil):\n{ornekler}"
                ),
                ok=True,
                data=result.data,
            )

        lines = [f"'{col}' kolonundaki değerler ({len(result.data)} adet):"]
        for row in result.data.itertuples(index=False):
            value = getattr(row, col, row[0])
            if has_flag and bool(row[1]):
                lines.append(f"  - {value}   ⚠ ALT TOPLAM (alt kalemlerle birlikte toplama)")
            else:
                lines.append(f"  - {value}")
        lines.append(
            "\nDİKKAT: Bu değerlerden SADECE BİRİNİ seç ve birebir yaz. "
            "Kullanıcı açıkça 'hepsi' / 'karşılaştır' demedikçe birden fazlasını IN veya LIKE "
            "ile birlikte alma — aynı döneme birden çok satır düşer ve toplamlar bozulur.\n"
            "Benzer isimli kalemler farklı şeyleri ölçebilir: 'Takipteki ...' takipteki "
            "alacaktır, '... (Dövize Endeksli)' ayrı bir üründür. Kullanıcı bunları özellikle "
            "istemediyse ana kalemi seç."
        )
        return ToolResult(content="\n".join(lines), data=result.data)

    def _toplam_deger_sayisi(self, dataset_id: str, column: str) -> int:
        """Kolondaki toplam distinct değer sayısı — limit uygulanmadan önceki hâli."""
        try:
            r = self.lakehouse.execute_sql(
                f"SELECT COUNT(DISTINCT {column}) AS n FROM {dataset_id}"
            )
            return int(r.data.iloc[0, 0]) if not r.is_empty else 0
        except LakehouseError:
            return 0

    @staticmethod
    def _ornek_terim(df, column: str) -> str:
        """Daraltma önerisi için, dönen değerlerden kısa bir arama terimi seçer."""
        if df.empty:
            return "..."
        return kisa_terim(df.iloc[0][column] if column in df.columns else df.iloc[0, 0])
