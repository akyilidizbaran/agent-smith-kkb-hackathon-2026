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

from pydantic import BaseModel, Field

from ..contracts.catalog import ColumnRole
from ..contracts.lakehouse import LakehouseClient, LakehouseError
from ..domain import kisa_terim
from ..core.errors import ToolError
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace


class SearchParams(BaseModel):
    query: str = Field(
        description="Aranan konuyu anlatan kısa Türkçe ifade, ör. 'aylık {example_entity}'"
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

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse

    def run(self, params: SearchParams) -> ToolResult:
        specs = self.lakehouse.search_datasets(params.query)
        if not specs:
            return ToolResult(content="Bu konuyla ilgili tablo bulunamadı.", ok=True)
        lines = ["Bulunan tablolar:"]
        for s in specs:
            lines.append(
                f"- {s.dataset_id}: {s.name}. {s.description[:180]} "
                f"[frekans: {s.frequency.value}, kapsam: {s.coverage.start}→{s.coverage.end}]"
            )
            # Kimlik ile fiziksel erişim kalıbı aynı şey olmak zorunda değil. Seed'de
            # dataset_id gerçekten tablo adı; Silver'da 'evds:TP.KTF12' bir tablo DEĞİL,
            # tek bir ilişkideki bir satır kümesinin kimliği. Bu satır olmadığında model
            # arama çıktısındaki kimliği FROM'a yazıyordu (ölçüldü: Silver şemasında
            # SQL_FAILED, tek kök neden). Kalıbı adaptör üretiyor (ADR-0024, series_sql):
            # çalıştırılabilir SQL veriyoruz, tarif değil — tarif kopyalanınca bozuluyor.
            hint = self._access_sql(s)
            if hint:
                lines.append(f"    '{s.dataset_id}' bir tablo adı DEĞİL. SQL'de şöyle eriş: {hint}")
        lines.append("\nSorgu yazmadan önce lakehouse_describe ile kolonları incele.")
        return ToolResult(content="\n".join(lines))

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

    def __init__(
        self,
        lakehouse: LakehouseClient,
        workspace: AnalysisWorkspace,
        registry: object | None = None,
    ) -> None:
        self.lakehouse = lakehouse
        self.workspace = workspace
        # Sorulan soruya erişim: atlanan dönem kısıtını yakalamak için.
        self._registry = registry

    def check_policy(self, params: QueryParams) -> ToolError | None:
        """Sorgu çalışmadan önce reddet: uyarı olarak eklendiğinde model onu okuyup
        yine de cevaba geçiyordu (ölçüldü: 0/2). Kapsam kontrolünde işe yarayan kalıp
        bu — modele seçenek bırakmamak (ADR-0010). Mesajlar ADR-0017'deki gibi."""
        kapsam_disi_soru = self._soru_kapsam_disi()
        if kapsam_disi_soru:
            return ToolError(
                error_code="OUT_OF_COVERAGE", message=kapsam_disi_soru,
                hint="Bu dönem için sorgu çalıştırma. Kullanıcıya verinin hangi tarihe "
                     "kadar yayımlandığını söyle; istersen mevcut son dönemi teklif et.",
                layer="data",
            )
        eksik_donem = self._atlanmis_donem_filtresi(params.sql)
        if eksik_donem:
            yil = eksik_donem.split(",")[0].strip()
            return ToolError(
                error_code="MISSING_PERIOD_FILTER",
                message=f"Sorguda dönem filtresi yok. Kullanıcı {eksik_donem} dönemini sordu ama "
                        f"sorgun tablonun tamamını getiriyor.",
                hint=f"Sorguya dönem kısıtını ekleyip tekrar çalıştır, ör. "
                     f"WHERE EXTRACT(year FROM <dönem_kolonu>) = {yil}",
                layer="policy",
            )
        return None

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
                )
            return ToolResult(
                content="Sorgu çalıştı ancak hiç satır dönmedi. Dönem aralığı kapsam içinde, "
                "yani sorun büyük olasılıkla filtre değerinde. Kalem/kategori adını "
                "lakehouse_distinct_values ile doğrula.",
                ok=True,
                provenance=result.provenance,
            )

        if params.as_active_table:
            self.workspace.set_table(
                result.data, description=params.purpose, provenance=result.provenance
            )
            self.workspace.title = params.purpose

        # Modele TAM tablo değil, özet gider: context window'u koruyoruz.
        df = result.data
        preview_rows = min(10, len(df))
        content = (
            f"Sorgu başarılı: {len(df)} satır, {len(df.columns)} sütun.\n"
            f"Sütunlar: {', '.join(df.columns)}\n"
            f"İlk {preview_rows} satır:\n{df.head(preview_rows).to_string(index=False)}"
        )
        if len(df) > preview_rows:
            content += f"\n... ({len(df) - preview_rows} satır daha; tamamı analiz tablosunda)"
        units = self._units_for(df.columns, result.provenance.dataset_ids)
        if units:
            content += "\nBirimler: " + ", ".join(units)
        content += f"\nKaynak: {result.provenance.summary()}"
        return ToolResult(content=content, data=df, provenance=result.provenance)

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
