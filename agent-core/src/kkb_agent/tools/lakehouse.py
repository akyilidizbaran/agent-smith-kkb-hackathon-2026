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

from ..contracts.lakehouse import LakehouseClient, LakehouseError
from ..core.tool import Tool, ToolResult
from ..core.workspace import AnalysisWorkspace


class SearchParams(BaseModel):
    query: str = Field(
        description="Aranan konuyu anlatan kısa Türkçe ifade, ör. 'aylık {example_entity}'"
    )


class LakehouseSearchTool(Tool):
    name = "lakehouse_search"
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
        lines.append("\nSorgu yazmadan önce lakehouse_describe ile kolonları incele.")
        return ToolResult(content="\n".join(lines))


class DescribeParams(BaseModel):
    dataset_id: str = Field(description="lakehouse_search'ten dönen tablo kimliği")


class LakehouseDescribeTool(Tool):
    name = "lakehouse_describe"
    description = (
        "Bir tablonun kolonlarını, birimlerini, kümülatif olup olmadığını ve örnek satırlarını "
        "gösterir. SQL yazmadan ÖNCE mutlaka çağır: kolon adlarını ve birimleri buradan öğren."
    )
    Params = DescribeParams

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse

    def run(self, params: DescribeParams) -> ToolResult:
        try:
            spec = self.lakehouse.get_dataset(params.dataset_id)
            sample = self.lakehouse.preview(params.dataset_id, n=5)
        except LakehouseError as exc:
            return ToolResult.error(str(exc))

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

    def run(self, params: QueryParams) -> ToolResult:
        # Sorgu çalışmadan önce reddet: uyarı olarak eklendiğinde model onu
        # okuyup yine de cevaba geçiyordu (ölçüldü: 0/2). Kapsam kontrolünde
        # işe yarayan kalıp bu — modele seçenek bırakmamak (ADR-0010).
        eksik_donem = self._atlanmis_donem_filtresi(params.sql)
        if eksik_donem:
            return ToolResult.error(
                f"Sorguda dönem filtresi yok. Kullanıcı {eksik_donem} dönemini sordu ama "
                f"sorgun tablonun tamamını getiriyor.\n"
                f"YAPACAĞIN: sorguya dönem kısıtını ekleyip tekrar çalıştır, ör. "
                f"WHERE EXTRACT(year FROM <dönem_kolonu>) = {eksik_donem.split(',')[0].strip()}"
            )
        try:
            result = self.lakehouse.execute_sql(params.sql)
        except LakehouseError as exc:
            # Hata modele geri döner; harness'ın onarım döngüsü devreye girer.
            return ToolResult.error(str(exc))

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
    limit: int = Field(default=50, description="En fazla kaç değer döndürülsün")


class LakehouseDistinctValuesTool(Tool):
    """Modelin en sık yaptığı hatayı kapatan araç.

    İlk ölçümde model 'Tüketici Kredileri - Konut' kaleminin adını TAHMİN etti,
    iki sorgu boşa gitti, sonra `LIKE '%Konut%'` ile üç ayrı kalemi birden
    çekip mükerrer topladı. Filtre yazmadan önce gerçek değerleri görmek bu
    sınıf hataların tamamını ortadan kaldırıyor.
    """

    name = "lakehouse_distinct_values"
    description = (
        "Bir kırılım kolonundaki GERÇEK değerleri listeler. Bir kalemi/kategoriyi filtrelemeden "
        "ÖNCE mutlaka bunu çağır — değer adını asla tahmin etme. Alt toplam satırlarını da "
        "işaretler, böylece mükerrer sayımdan kaçınırsın."
    )
    Params = DistinctValuesParams

    def __init__(self, lakehouse: LakehouseClient) -> None:
        self.lakehouse = lakehouse

    def run(self, params: DistinctValuesParams) -> ToolResult:
        try:
            spec = self.lakehouse.get_dataset(params.dataset_id)
        except LakehouseError as exc:
            return ToolResult.error(str(exc))

        if spec.column(params.column) is None:
            return ToolResult.error(
                f"'{params.column}' kolonu {params.dataset_id} tablosunda yok. "
                f"Mevcut kolonlar: {', '.join(c.name for c in spec.columns)}"
            )

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
            return ToolResult.error(str(exc))

        if result.is_empty:
            hint = f" ('{params.contains}' içeren değer yok)" if params.contains else ""
            return ToolResult(
                content=f"'{col}' kolonunda değer bulunamadı{hint}. "
                f"Daha genel bir arama terimi dene veya contains parametresini boş bırak.",
                ok=True,
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
