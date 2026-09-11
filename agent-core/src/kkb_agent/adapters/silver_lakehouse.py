"""Veri ekibinin Lakehouse'una bağlanan adaptör.

`LakehouseClient` protokolünü `meta.series` + `silver.fact_observation` üzerinde
uygular. `lakehouse-core` paketini İMPORT ETMEZ: ihtiyaç duyduğu her şey iki
tablo ve salt-okunur bir bağlantı, ikisi de SQL ile erişilebilir. Bu sayede
kurulum/paketleme sözleşmesi netleşmeden geliştirilip test edilebiliyor.

Eşleme kararı — her SERİ bir `DatasetSpec`:
    meta.series seri-merkezli; `unit` ve `measure_type` serinin özelliği, tablonun
    değil. Tek bir "fact_observation" DatasetSpec'i üretilseydi bu alanlar
    kaybolurdu ve `lakehouse_search` tabloyu bulup seriyi bulamazdı. Katalog
    büyüdüğünde aranan şey seri olacağı için (ADR-0013) doğru granülarite bu.

Fiziksel sorgu her zaman aynı tablodan gider:
    SELECT ... FROM silver.fact_observation WHERE series_id = '<id>'
Bu kalıp `DatasetSpec.source_detail` alanında yazılı; `to_prompt_card()` onu
modele gösterir.
"""

from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from ..contracts.catalog import (
    ColumnRole,
    ColumnSpec,
    Coverage,
    CumulativeKind,
    DatasetSpec,
    Frequency,
    SemanticType,
)
from ..contracts.lakehouse import LakehouseError, QueryProvenance, QueryResult
from .duckdb_lakehouse import guard_sql, hardened_connection

SILVER_RELATION = "silver.fact_observation"

# Veri ekibinin measure_type sözlüğü -> bizim SemanticType + CumulativeKind ikilisi.
# Onlarınki daha iyi (kümülatiflik tipin içinde); çeviri burada tek noktada.
_MEASURE_TYPE: dict[str, tuple[SemanticType, CumulativeKind]] = {
    "stock": (SemanticType.STOCK, CumulativeKind.NONE),
    "flow_periodic": (SemanticType.FLOW, CumulativeKind.NONE),
    "flow_ytd": (SemanticType.FLOW, CumulativeKind.YTD),
    "flow_cumulative": (SemanticType.FLOW, CumulativeKind.SINCE_INCEPTION),
    "rate": (SemanticType.RATE, CumulativeKind.NONE),
    "ratio": (SemanticType.RATIO, CumulativeKind.NONE),
    "index": (SemanticType.INDEX, CumulativeKind.NONE),
    "count": (SemanticType.COUNT, CumulativeKind.NONE),
    "unknown": (SemanticType.STOCK, CumulativeKind.NONE),  # aşağıda uyarı ile
}

# Kontrollü birim sözlüğü -> insan okunur etiket + gerçek birime çarpan.
_UNIT: dict[str, tuple[str, float]] = {
    "TRY": ("TL", 1.0),
    "TRY_th": ("bin TL", 1_000.0),
    "TRY_mn": ("milyon TL", 1_000_000.0),
    "pct": ("yüzde", 1.0),
    "index": ("endeks", 1.0),
    "count": ("adet", 1.0),
}

_FREQUENCY: dict[str, Frequency] = {
    "daily": Frequency.DAILY,
    "business_daily": Frequency.DAILY,
    "weekly": Frequency.WEEKLY,
    "biweekly": Frequency.WEEKLY,
    "monthly": Frequency.MONTHLY,
    "quarterly": Frequency.QUARTERLY,
    "semiannual": Frequency.QUARTERLY,
    "yearly": Frequency.YEARLY,
}


class SilverLakehouse:
    """`meta.series` + `silver.fact_observation` üzerinde LakehouseClient."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise LakehouseError(
                f"Lakehouse bulunamadı: {self.db_path}. Veri ekibinin ingestion'ı çalıştırılmalı "
                "ya da geliştirme için `python scripts/dev_seed_silver.py`."
            )
        self._con = hardened_connection(self.db_path)
        self._require_relations()
        self._catalog: dict[str, DatasetSpec] = self._load_catalog()

    # ---------- kurulum ----------
    def _require_relations(self) -> None:
        """Beklenen iki ilişki yoksa erken ve anlaşılır biçimde dur."""
        found = {
            f"{r[0]}.{r[1]}"
            for r in self._con.execute(
                "SELECT table_schema, table_name FROM information_schema.tables"
            ).fetchall()
        }
        for rel in ("meta.series", SILVER_RELATION):
            if rel not in found:
                raise LakehouseError(
                    f"'{rel}' bulunamadı ({self.db_path}). Mevcut ilişkiler: "
                    f"{', '.join(sorted(found)) or '—'}"
                )

    def _load_catalog(self) -> dict[str, DatasetSpec]:
        """Kataloğu yükler ve yüklenmemiş serileri ayırır.

        `meta.series` "hangi serinin anlamı kayıtlı" sorusunu yanıtlar, "hangi serinin
        verisi var" sorusunu değil. Veri ekibinin kataloğunda 1620 seri var, bunların
        yalnızca bir kısmı gerçekten çekilmiş durumda. İkisi arasındaki fark modele
        gösterilecek olsaydı, model sorgulanamayacak bir seri seçip ya boş sonuç alır ya
        da — daha kötüsü — adından bir sayı uydururdu.

        Bu yüzden gözlemi olmayan seri kataloğa girmiyor. Ama yok sayılmıyor da: adı ve
        kimliği `_uningested` içinde tutuluyor, böylece "böyle bir seri var mı?" sorusuna
        "yok" değil, "var ama henüz yüklenmemiş" denebiliyor. Bu iki cevap birbirinin
        yerine geçmez.
        """
        rows = self._con.execute(
            """
            SELECT series_id, source_id, native_code, dataset_id, name_tr, description,
                   aliases, tags, frequency, week_anchor, unit, measure_type, default_agg,
                   cumulative_reset, semantic_confidence, first_obs, last_obs,
                   metadata_url, status
            FROM meta.series
            WHERE status <> 'deprecated'
            ORDER BY series_id
            """
        ).fetchall()
        counts = dict(
            self._con.execute(
                f"SELECT series_id, count(*) FROM {SILVER_RELATION} GROUP BY 1"
            ).fetchall()
        )
        catalog: dict[str, DatasetSpec] = {}
        self._uningested: dict[str, str] = {}
        for row in rows:
            series_id, name_tr = row[0], row[4]
            if counts.get(series_id):
                catalog[series_id] = self._to_spec(row, counts[series_id])
            else:
                self._uningested[series_id] = name_tr
        return catalog

    def _to_spec(self, row: tuple, row_count: int | None) -> DatasetSpec:
        (series_id, source_id, native_code, dataset_id, name_tr, description, aliases, tags,
         frequency, week_anchor, unit, measure_type, default_agg, cumulative_reset,
         confidence, first_obs, last_obs, metadata_url, status) = row

        semantic_type, cumulative = _MEASURE_TYPE.get(
            measure_type, (SemanticType.STOCK, CumulativeKind.NONE)
        )
        # cumulative_reset katalogda ayrıca verilmişse measure_type'ı doğrular
        if cumulative_reset == "yearly":
            cumulative = CumulativeKind.YTD
        unit_label, multiplier = _UNIT.get(unit or "", (unit or "birimsiz", 1.0))

        notes: list[str] = []
        if confidence != "verified":
            notes.append(
                f"Bu serinin semantiği DOĞRULANMAMIŞ (semantic_confidence={confidence}). "
                "Frekans dönüşümü, kümülatif çözme ve birim çevirisi otomatik yapılmaz; "
                "kullanıcıya sorulmalıdır."
            )
        if measure_type == "unknown":
            notes.append("Ölçüm tipi bilinmiyor: hiçbir otomatik toplama/ortalama uygulanamaz.")
        if status == "draft":
            notes.append("Taslak seri: kaynağı ya da eşlemesi henüz kesinleşmemiş.")
        if week_anchor:
            notes.append(f"Haftalık seri, dönem çapası: {week_anchor}.")
        if default_agg:
            notes.append(f"Frekans indirgemede kullanılacak kural: {default_agg}.")
        notes.append(
            "Fiziksel sorgu: "
            f"SELECT observation_date, value FROM {SILVER_RELATION} "
            f"WHERE series_id = '{series_id}'"
        )

        return DatasetSpec(
            dataset_id=series_id,
            name=name_tr,
            description=description,
            source=source_id,
            source_url=metadata_url,
            source_detail=f"{SILVER_RELATION} WHERE series_id = '{series_id}' (kaynak kodu: {native_code})",
            frequency=_FREQUENCY.get(frequency, Frequency.IRREGULAR),
            time_column="observation_date",
            grain=["observation_date"],
            columns=[
                ColumnSpec(
                    name="observation_date", role=ColumnRole.TIME, dtype="DATE",
                    description="Gözlemin ait olduğu dönem, DÖNEM SONU günüyle temsil edilir",
                    aliases=["dönem", "tarih", "ay", "donem"],
                ),
                ColumnSpec(
                    name="value", role=ColumnRole.MEASURE, dtype="DOUBLE",
                    description=f"{name_tr} değeri",
                    semantic_type=semantic_type, cumulative=cumulative,
                    unit=unit_label, unit_multiplier=multiplier,
                    aliases=list(aliases or []),
                ),
                ColumnSpec(
                    name="quality_flag", role=ColumnRole.METADATA, dtype="VARCHAR",
                    description="ok | missing_value | source_warning — kaynak uyarısı taşıyan satırlar",
                ),
                ColumnSpec(
                    name="entity_id", role=ColumnRole.DIMENSION, dtype="VARCHAR",
                    description="Gözlemin ait olduğu varlık (il, banka grubu); tek varlıklı seride NULL",
                ),
            ],
            coverage=Coverage(
                start=first_obs or date(1900, 1, 1),
                end=last_obs or date(1900, 1, 1),
                row_count=row_count,
                known_gaps=[] if first_obs else ["kapsam hesaplanmamış: seride gözlem yok"],
            ),
            tags=list(tags or []),
            notes=notes,
            last_refreshed=None,
        )

    # ---------- Katalog ----------
    def list_datasets(self) -> list[DatasetSpec]:
        return list(self._catalog.values())

    def get_dataset(self, dataset_id: str) -> DatasetSpec:
        spec = self._catalog.get(dataset_id)
        if spec is not None:
            return spec
        if dataset_id in self._uningested:
            raise LakehouseError(
                f"'{dataset_id}' ({self._uningested[dataset_id]}) katalogda tanımlı fakat bu "
                "veri tabanına henüz hiç gözlem yüklenmemiş. Seri yok değil, verisi yok — "
                "bu ikisi aynı şey değildir ve kullanıcıya böyle söylenmelidir."
            )
        # Tüm katalog listelenmiyor: 1600'den fazla seride bu mesajın kendisi hataya dönüşür.
        near = [sid for sid in self._catalog if dataset_id.lower() in sid.lower()][:8]
        suffix = f" Benzer olanlar: {', '.join(near)}" if near else ""
        raise LakehouseError(
            f"'{dataset_id}' bulunamadı ({len(self._catalog)} seri yüklü)."
            f"{suffix} Doğru kimliği bulmak için lakehouse_search kullan."
        )

    def search_datasets(self, query: str, limit: int = 5) -> list[DatasetSpec]:
        """Anahtar kelime skorlaması; `aliases` en ağırlıklı alan.

        Hibrit retrieval (BM25 + embedding + RRF) geldiğinde bu metot değişir,
        arayüz aynı kalır (ADR-0021, contracts/retrieval.py).
        """
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
        scored: list[tuple[int, DatasetSpec]] = []
        for spec in self._catalog.values():
            alias_text = " ".join(a for c in spec.columns for a in c.aliases).lower()
            body = " ".join([spec.name, spec.description, " ".join(spec.tags)]).lower()
            score = sum(3 * alias_text.count(t) + body.count(t) for t in terms)
            if score:
                scored.append((score, spec))
        scored.sort(key=lambda x: (-x[0], x[1].dataset_id))
        # Eşleşme yoksa boş dönüyoruz. Eskiden kataloğun ilk N serisi dönüyordu; dört
        # tablolu bir seed'de zararsız bir kolaylıktı, 1620 serilik bir katalogda ise
        # modele alakasız bir tablo verip onu o tablodan cevap üretmeye davet ediyor.
        return [s for _, s in scored[:limit]]

    # ---------- Sorgulama ----------
    def execute_sql(self, sql: str, *, max_rows: int = 10_000) -> QueryResult:
        text = guard_sql(sql)
        bounded = f"SELECT * FROM ({text}) AS _q LIMIT {int(max_rows) + 1}"
        started = time.perf_counter()
        try:
            df = self._con.execute(bounded).fetch_df()
        except Exception as exc:
            raise LakehouseError(f"SQL çalıştırılamadı: {exc}") from exc
        duration = (time.perf_counter() - started) * 1000

        warnings: list[str] = []
        if len(df) > max_rows:
            warnings.append(f"Sonuç {max_rows} satırdan uzun, kırpıldı.")
            df = df.head(max_rows)

        used = [sid for sid in self._catalog if sid in text]
        specs = [self._catalog[s] for s in used]
        # Kaynak uyarılı satırlar sessizce geçmesin: güven katmanının parçası.
        if "quality_flag" in df.columns:
            flagged = df["quality_flag"].astype(str).ne("ok").sum()
            if flagged:
                warnings.append(
                    f"{flagged} satır 'ok' dışında bir quality_flag taşıyor "
                    "(missing_value / source_warning)."
                )
        for spec in specs:
            warnings.extend(n for n in spec.notes if not n.startswith("Fiziksel sorgu"))

        return QueryResult(
            data=df,
            provenance=QueryProvenance(
                sql=text,
                dataset_ids=used,
                sources=[f"{s.source} — {s.name}" for s in specs],
                source_urls=[s.source_url for s in specs if s.source_url],
                row_count=len(df),
                duration_ms=duration,
                warnings=warnings,
            ),
        )

    def preview(self, dataset_id: str, n: int = 5) -> QueryResult:
        self.get_dataset(dataset_id)
        return self.execute_sql(
            f"SELECT observation_date, value, quality_flag FROM {SILVER_RELATION} "
            f"WHERE series_id = '{dataset_id}' ORDER BY observation_date LIMIT {int(n)}"
        )

    def series_sql(
        self,
        dataset_id: str,
        *,
        key_column: str,
        value_column: str,
        filter_column: str | None = None,
        filter_value: str | None = None,
    ) -> str:
        """Bu yerleşimde her seri aynı uzun formatlı tabloda bir satır kümesidir."""
        spec = self.get_dataset(dataset_id)
        valid = {c.name for c in spec.columns}
        for field, name in (("key_column", key_column), ("value_column", value_column),
                            ("filter_column", filter_column)):
            if name and name not in valid:
                raise LakehouseError(
                    f"{field}='{name}' bu seride yok. Mevcut kolonlar: {', '.join(sorted(valid))}"
                )
        sid = dataset_id.replace("'", "''")
        sql = (
            f"SELECT {key_column}, {value_column} FROM {SILVER_RELATION} "
            f"WHERE series_id = '{sid}'"
        )
        if filter_column and filter_value is not None:
            sql += f" AND {filter_column} = '{filter_value.replace(chr(39), chr(39) * 2)}'"
        return sql + f" ORDER BY {key_column}"

    def health(self) -> dict[str, Any]:
        n_obs = self._con.execute(f"SELECT count(*) FROM {SILVER_RELATION}").fetchone()[0]
        unverified = sorted(
            s.dataset_id for s in self._catalog.values()
            if any("DOĞRULANMAMIŞ" in n for n in s.notes)
        )
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "relation": SILVER_RELATION,
            "queryable_series": len(self._catalog),
            "catalogued_series": len(self._catalog) + len(self._uningested),
            "uningested_series": len(self._uningested),
            "observations": n_obs,
            # Sayı önce, örnek sonra: 1600 kimliği ekrana dökmek teşhis değil gürültüdür.
            "unverified_series": (
                f"{len(unverified)} seri"
                + (f" (ör. {', '.join(unverified[:5])})" if unverified else "")
            ),
            "hardened": True,
        }
