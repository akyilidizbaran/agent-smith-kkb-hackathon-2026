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
from ..contracts.lakehouse import GoldRefused, LakehouseError, QueryProvenance, QueryResult
from .duckdb_lakehouse import guard_sql, hardened_connection, register_reader
from .gold_cli import GoldCLI, GoldRunOutcome

SILVER_RELATION = "silver.fact_observation"
ADHOC_RELATION = "adhoc.fact_observation"
GOLD_BUILD_TABLE = "meta.gold_build"
GOLD_SCHEMA = "gold"
"""Gold tabloları (`python -m lakehouse gold`, ADR-0031): kataloglanmış bir fonksiyon
çağrısının Silver'dan kurulmuş önbelleği. Hangi tablonun hangi metrik olduğunu ve hangi
Silver'dan kurulduğunu `meta.gold_build` söyler; adaptör tabloyu değil, defteri okur."""

SILVER_FINGERPRINT_SQL = """
SELECT coalesce(md5(string_agg(
           series_id || '|' || coalesce(entity_id, '') || '|' || observation_date
           || '|' || coalesce(value::VARCHAR, '') || '|' || quality_flag
           || '|' || artifact_sha256,
           ','
           ORDER BY series_id, entity_id, observation_date, artifact_sha256
       )), 'empty')
FROM silver.fact_observation
"""
"""Veri ekibinin `lakehouse.gold.build.silver_fingerprint` tanımının birebir kopyası —
sözleşmenin parçası. Gold tablosu kurulurken kaydedilen parmak iziyle canlı parmak izi
farklıysa tablo BAYATTIR: Silver sonradan yeniden kurulmuş, Gold kurulmamıştır."""

_GOLD_MEASURE_BASES = frozenset({"value", "cumulative_value", "previous_cumulative_value", "raw_change"})
_GOLD_TIME_BASES = frozenset({"period_start", "period_end"})
_GOLD_DIMENSION_BASES = frozenset({"series_id", "entity_id"})
_GOLD_COLUMN_NOTES = {
    "period_end": "Dönem sonu — satırın etiketi",
    "period_start": "Dönem başı",
    "value": "Dönemin hesaplanmış değeri (kural katalogdan)",
    "cumulative_value": "Kaynağın birikimli okuması (dokunulmamış)",
    "previous_cumulative_value": "Bir önceki dönemin birikimli okuması (taban)",
    "raw_change": "İki okuma farkı; dönem akımı olarak yazılmadıysa burada durur",
    "quality_flag": "ok | partial_period | boundary_missing | missing_value | source_warning",
    "decomposition_flag": "ok | no_prior_base | unattributable_year_start | spans_multiple_periods | negative_change | missing_value",
    "observations": "Döneme giren kaynak gözlem sayısı",
    "missing_observations": "Dönemde eksik gelen gözlem sayısı",
    "warned_observations": "Parser uyarısı taşıyan gözlem sayısı",
    "source_observation_dates": "Döneme giren kaynak gözlem tarihleri (kanıt)",
    "artifact_sha256_list": "Katkıda bulunan RAW artifact özetleri (kanıt zinciri)",
    "vintage_id_list": "Katkıda bulunan Silver sürümleri",
    "run_id_list": "Katkıda bulunan ingest koşuları",
    "contributing_series": "Bu dönemde yayımlayan seriler",
    "absent_series": "Bu dönemde yayımlamayan seriler",
    "is_complete_period": "Tüm seriler bu dönemde yayımladı mı",
    "aggregation": "Uygulanan kural (last/sum/avg/identity)",
    "measure_type": "Kaynak serinin ölçüm tipi (katalogdan)",
    "unit": "Kaynak serinin birim kodu (katalogdan)",
    "source_frequency": "Kaynak frekansı",
    "target_frequency": "Hedef dönem",
    "contributor_count": "Satıra giren okuma sayısı (1: tek okuma, 2: fark)",
    "previous_observation_date": "Taban okumanın tarihi",
    "artifact_sha256": "Bu okumanın RAW artifact özeti (kanıt)",
    "previous_artifact_sha256": "Taban okumanın RAW artifact özeti (kanıt)",
    "vintage_id": "Bu okumanın Silver sürümü",
    "previous_vintage_id": "Taban okumanın Silver sürümü",
    "run_id": "Bu okumanın ingest koşusu",
    "previous_run_id": "Taban okumanın ingest koşusu",
    "series_id": "Kaynak seri kimliği",
    "entity_id": "Varlık (il, banka grubu); tek varlıklı seride NULL",
}
_GOLD_RULE_TR = {
    "stock": "stok → dönemin son gözlemi (last)",
    "flow_periodic": "akım → dönem toplamı (sum)",
    "flow_ytd": "yıl başından birikimli → önce çözülür",
    "flow_cumulative": "kuruluştan birikimli → önce çözülür",
}
"""Aynı kolonlar, aynı anlam; yalnız şema adı verinin nereden geldiğini söyler (veri
ekibinin DDL notu). Küratörlü ve taslak veri ayrı ilişkilerde durur ki karışmasın —
ama Analist ikisini de okur; taslak olan `status='draft'` notuyla gelir."""

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

    def __init__(self, db_path: str | Path, *, gold: GoldCLI | None = None) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise LakehouseError(
                f"Lakehouse bulunamadı: {self.db_path}. Veri ekibinin ingestion'ı çalıştırılmalı "
                "ya da geliştirme için `python scripts/dev_seed_silver.py`."
            )
        # Salt-okunur Gold çağrısı (gold-run). Yoksa gold_* araçları kayıt edilmez; hazır
        # gold.* tabloları yine görünür — onlar defterden okunur, CLI gerektirmez.
        self.gold = gold
        self._con = hardened_connection(self.db_path)
        register_reader(self.db_path, self)
        self._require_relations()
        self._catalog: dict[str, DatasetSpec] = self._load_catalog()

    def _conn(self) -> duckdb.DuckDBPyConnection:
        """Bağlantı; `release_connections` ile bırakıldıysa aynı sertleştirmeyle yeniden açılır."""
        if getattr(self, "_con", None) is None:
            self._con = hardened_connection(self.db_path)
            register_reader(self.db_path, self)
        return self._con

    # ---------- yaşam döngüsü ----------
    def close(self) -> None:
        """Okuyucuyu bırak. Architect yazarken çağrılır; `reload()` ile geri gelir."""
        con = getattr(self, "_con", None)
        if con is not None:
            con.close()
            self._con = None  # type: ignore[assignment]

    def reload(self) -> None:
        """Sertleştirilmiş bağlantıyı yeniden aç, kataloğu yeniden oku.

        Ingest'ten sonra `meta.series`'te yeni bir draft satır ve `adhoc`/`silver`'da
        yeni gözlemler vardır; eski katalog nesnesi bunları bilmez. Aynı sertleştirme
        (read_only, external access kapalı, config kilitli) yeniden uygulanır.
        """
        self.close()
        self._con = hardened_connection(self.db_path)
        register_reader(self.db_path, self)
        self._require_relations()
        self._catalog = self._load_catalog()

    # ---------- kurulum ----------
    def _require_relations(self) -> None:
        """Beklenen iki ilişki yoksa erken ve anlaşılır biçimde dur."""
        found = {
            f"{r[0]}.{r[1]}"
            for r in self._conn().execute(
                "SELECT table_schema, table_name FROM information_schema.tables"
            ).fetchall()
        }
        for rel in ("meta.series", SILVER_RELATION):
            if rel not in found:
                raise LakehouseError(
                    f"'{rel}' bulunamadı ({self.db_path}). Mevcut ilişkiler: "
                    f"{', '.join(sorted(found)) or '—'}"
                )
        # adhoc isteğe bağlı: seed/test veritabanlarında olmayabilir.
        self._has_adhoc = ADHOC_RELATION in found
        # Gold defteri de isteğe bağlı: `python -m lakehouse gold` hiç koşmadıysa yoktur.
        self._has_gold_ledger = GOLD_BUILD_TABLE in found

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
        rows = self._conn().execute(
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
            self._conn().execute(
                f"SELECT series_id, count(*) FROM {SILVER_RELATION} GROUP BY 1"
            ).fetchall()
        )
        # Taslak seriler adhoc ilişkisinde yaşar; ingest'ten hemen sonra Analist'in onları
        # görmesi gerekir (ölçüldü: görmüyordu — "yeni: []"). Kaynağı 'adhoc' olan seri o
        # ilişkiden sayılır ve sorgulanır; küratörlü olanlar Silver'dan.
        self._relation_by_series: dict[str, str] = {}
        if getattr(self, "_has_adhoc", False):
            adhoc_counts = dict(
                self._conn().execute(
                    f"SELECT series_id, count(*) FROM {ADHOC_RELATION} GROUP BY 1"
                ).fetchall()
            )
        else:
            adhoc_counts = {}
        catalog: dict[str, DatasetSpec] = {}
        self._uningested: dict[str, str] = {}
        for row in rows:
            series_id, source_id, name_tr = row[0], row[1], row[4]
            relation = ADHOC_RELATION if source_id == "adhoc" else SILVER_RELATION
            self._relation_by_series[series_id] = relation
            n = adhoc_counts.get(series_id) if relation == ADHOC_RELATION else counts.get(series_id)
            if n:
                catalog[series_id] = self._to_spec(row, n)
            else:
                self._uningested[series_id] = name_tr
        catalog.update(self._load_gold_catalog(catalog))
        return catalog

    def _relation_for(self, series_id: str) -> str:
        return self._relation_by_series.get(series_id, SILVER_RELATION)

    # ---------- Gold tabloları (ADR-0031) ----------
    def _is_gold(self, dataset_id: str) -> bool:
        return dataset_id in getattr(self, "_gold_meta", {})

    def _silver_fingerprint(self) -> str:
        return str(self._conn().execute(SILVER_FINGERPRINT_SQL).fetchone()[0])

    def _load_gold_catalog(self, series_catalog: dict[str, DatasetSpec]) -> dict[str, DatasetSpec]:
        """`meta.gold_build`'de güncel ve `built` olan her metrik bir DatasetSpec.

        Tablo değil defter okunur: tablonun hangi fonksiyonun, hangi serilerin, hangi
        Silver'ın ürünü olduğunu yalnız defter bilir. Defterde olup diskte olmayan tablo
        (yarım kalmış bir kurulum) listelenmez; defterde olmayan `gold.*` tablosu da
        listelenmez — kim kurduğu belli olmayan bir tablo modele gösterilmez.
        """
        self._gold_meta: dict[str, dict[str, Any]] = {}
        if not getattr(self, "_has_gold_ledger", False):
            return {}
        rows = self._conn().execute(
            f"""
            SELECT metric_id, function, series_ids, target_frequency, name_tr, description,
                   aliases, tags, allow_unverified_semantics, row_count, silver_fingerprint,
                   built_at::VARCHAR, build_id
            FROM {GOLD_BUILD_TABLE}
            WHERE is_current AND status = 'built'
            ORDER BY metric_id
            """
        ).fetchall()
        if not rows:
            return {}
        tables = {
            r[0] for r in self._conn().execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = ?",
                [GOLD_SCHEMA],
            ).fetchall()
        }
        live = self._silver_fingerprint()
        out: dict[str, DatasetSpec] = {}
        for row in rows:
            metric_id = row[0]
            if metric_id not in tables:
                continue
            spec = self._gold_spec(row, stale=row[10] != live, series_catalog=series_catalog)
            out[spec.dataset_id] = spec
        return out

    def _gold_spec(self, row: tuple, *, stale: bool, series_catalog: dict[str, DatasetSpec]) -> DatasetSpec:
        (metric_id, function, series_ids, target, name_tr, description, aliases, tags,
         allow_unverified, row_count, fingerprint, built_at, build_id) = row
        series_ids = list(series_ids or [])
        table = f"{GOLD_SCHEMA}.{metric_id}"
        dataset_id = table

        # Serilerin kural ve birimleri: hangi kolonun ne olduğu ancak katalogla anlaşılır.
        semantics: dict[str, dict[str, Any]] = {}
        for sid, unit, mt, agg, freq, name in self._conn().execute(
            "SELECT series_id, unit, measure_type, default_agg, frequency, name_tr "
            "FROM meta.series WHERE series_id IN (SELECT unnest(?))", [series_ids],
        ).fetchall():
            semantics[sid] = {"unit": unit, "measure_type": mt, "default_agg": agg,
                              "frequency": freq, "name": name}

        def rule_of(sid: str) -> str:
            sem = semantics.get(sid, {})
            mt, agg = sem.get("measure_type"), sem.get("default_agg")
            if mt in _GOLD_RULE_TR:
                return _GOLD_RULE_TR[mt]
            return f"{mt} → katalog kuralı {agg}" if agg else f"{mt}"

        described = self._conn().execute(f"DESCRIBE {table}").fetchall()
        columns: list[ColumnSpec] = []
        for col_name, dtype, *_ in described:
            base = col_name.rsplit("::", 1)[-1]
            key_series = col_name.split("::", 1)[0].split("@", 1)[0] if "::" in col_name else (series_ids[0] if series_ids else "")
            sem = semantics.get(key_series, {})
            if base in _GOLD_MEASURE_BASES:
                unit_label, multiplier = _UNIT.get(sem.get("unit") or "", (sem.get("unit") or "birimsiz", 1.0))
                semantic_type, cumulative = _MEASURE_TYPE.get(
                    sem.get("measure_type") or "", (SemanticType.STOCK, CumulativeKind.NONE)
                )
                if function == "decompose_cumulative" and base == "value":
                    semantic_type, cumulative = SemanticType.FLOW, CumulativeKind.NONE
                columns.append(ColumnSpec(
                    name=col_name, role=ColumnRole.MEASURE, dtype=dtype,
                    description=f"{_GOLD_COLUMN_NOTES.get(base, base)} — {sem.get('name', key_series)}; {rule_of(key_series)}",
                    semantic_type=semantic_type, cumulative=cumulative,
                    unit=unit_label, unit_multiplier=multiplier, aliases=list(aliases or []),
                ))
            elif base in _GOLD_TIME_BASES and "::" not in col_name:
                columns.append(ColumnSpec(
                    name=col_name, role=ColumnRole.TIME, dtype=dtype,
                    description=_GOLD_COLUMN_NOTES[base],
                    aliases=["dönem", "tarih", "çeyrek", "ay"] if base == "period_end" else [],
                ))
            elif base in _GOLD_DIMENSION_BASES:
                columns.append(ColumnSpec(name=col_name, role=ColumnRole.DIMENSION, dtype=dtype,
                                          description=_GOLD_COLUMN_NOTES[base]))
            else:
                note = _GOLD_COLUMN_NOTES.get(base, "Kurulum kaydı" if base.startswith("gold_") or base == "silver_fingerprint" else base)
                columns.append(ColumnSpec(name=col_name, role=ColumnRole.METADATA, dtype=dtype, description=note))

        start, end, n = self._conn().execute(
            f"SELECT min(period_start), max(period_end), count(*) FROM {table}"
        ).fetchone()
        source_freq = semantics.get(series_ids[0], {}).get("frequency") if series_ids else None
        frequency = _FREQUENCY.get(target or source_freq or "", Frequency.IRREGULAR)

        rules = "; ".join(f"{sid}: {rule_of(sid)}" for sid in series_ids)
        notes = [
            f"GOLD TABLOSU ({function}): {', '.join(series_ids)} → "
            f"{target or 'kaynak frekansı'}. Kural katalogdan — {rules}. Değerler hesaplanmış "
            "dönem değerleridir: yeniden toplama/ortalama alma, doğrudan göster.",
            "Her satır kendi kanıtını taşır: source_observation_dates ve artifact_sha256_list "
            f"(kaynak gözlemler → RAW). Kurulum: {build_id[:8]} @ {built_at[:19]}.",
        ]
        if function == "join_on_period":
            notes.append("Dış birleştirme: is_complete_period=false olan dönemde bir seri yayımlamamıştır; "
                         "o hücre boş kalır, sıfır değildir.")
        if allow_unverified:
            notes.append("Doğrulanmamış semantikle kurulmuş (insan onayı katalogda yazılı); cevapta belirt.")
        if stale:
            notes.append(
                "⚠ BAYAT: Silver bu tablo kurulduktan sonra değişti (parmak izi farklı). "
                "`python -m lakehouse gold` yeniden çalıştırılmalı; cevapta tablonun önceki "
                "Silver'dan geldiğini söyle."
            )
        measure_cols = [c.name for c in columns if c.role is ColumnRole.MEASURE]
        first_measure = measure_cols[0] if measure_cols else "value"
        notes.append(
            f'Fiziksel sorgu: SELECT period_end, "{first_measure}" FROM {table} ORDER BY period_end'
        )
        self._gold_meta[dataset_id] = {
            "metric_id": metric_id, "function": function, "series_ids": series_ids,
            "target_frequency": target, "stale": stale, "build_id": build_id,
            "list_columns": [c for c, d, *_ in described if d.endswith("[]")],
        }
        grain = ["period_end"] if function == "join_on_period" else ["series_id", "entity_id", "period_end"]
        return DatasetSpec(
            dataset_id=dataset_id,
            name=name_tr,
            description=description,
            source="gold",
            source_url=None,
            source_detail=f"{table} — {function}({', '.join(series_ids)}) kurulum {build_id[:8]}",
            frequency=frequency,
            time_column="period_end",
            grain=grain,
            columns=columns,
            coverage=Coverage(
                start=start or date(1900, 1, 1), end=end or date(1900, 1, 1), row_count=int(n),
                known_gaps=["BAYAT: Silver sonradan değişti"] if stale else [],
            ),
            tags=list(tags or []) + ["gold"],
            notes=notes,
            last_refreshed=None,
        )

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
            notes.append(
                "TASLAK seri: kullanıcının getirdiği veriden makine tarafından önerildi, bir "
                "insan onaylamadı. Sorgulanabilir; frekans dönüşümü ve Gold hesapları uygulanmaz. "
                "Cevapta taslak olduğunu söyle."
            )
        if week_anchor:
            notes.append(f"Haftalık seri, dönem çapası: {week_anchor}.")
        if default_agg:
            notes.append(f"Frekans indirgemede kullanılacak kural: {default_agg}.")
        relation = ADHOC_RELATION if source_id == "adhoc" else SILVER_RELATION
        notes.append(
            "Fiziksel sorgu: "
            f"SELECT observation_date, value FROM {relation} "
            f"WHERE series_id = '{series_id}'"
        )

        return DatasetSpec(
            dataset_id=series_id,
            name=name_tr,
            description=description,
            source=source_id,
            source_url=metadata_url,
            source_detail=f"{relation} WHERE series_id = '{series_id}' (kaynak kodu: {native_code})",
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
            # Her sorgu kendi imlecinde. Tek bir DuckDBPyConnection'ı iki iş
            # parçacığından aynı anda kullanmak sonucu ortadan çekiyor: ölçüldü, 800
            # eşzamanlı sorguda 2 kez "TypeError: object of type 'NoneType' has no
            # len()". Motor bir turda birden çok okuma aracını paralel çalıştırabildiği
            # için bu teorik bir durum değil. cursor() aynı veritabanını paylaşır,
            # sertleştirilmiş yapılandırma (read_only + kilitli config) korunur.
            df = self._conn().cursor().execute(bounded).fetch_df()
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
        if self._is_gold(dataset_id):
            meta = self._gold_meta[dataset_id]
            skip = set(meta["list_columns"]) | {
                "gold_metric_id", "gold_function", "gold_build_id", "gold_built_at",
                "gold_catalog_content_sha256", "silver_fingerprint",
            }
            cols = [c.name for c in self._catalog[dataset_id].columns
                    if c.name not in skip and not c.name.endswith(("::unit", "::measure_type", "::aggregation", "::series_id"))]
            quoted = ", ".join(f'"{c}"' for c in cols)
            return self.execute_sql(f"SELECT {quoted} FROM {dataset_id} ORDER BY period_end LIMIT {int(n)}")
        return self.execute_sql(
            f"SELECT observation_date, value, quality_flag FROM {self._relation_for(dataset_id)} "
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
        if self._is_gold(dataset_id):
            # Gold tablosu gerçek bir tablo: kimlik FROM'a yazılır, kolon adları tırnaklı
            # (join tablosunda '<seri>@<varlık>::value' gibi adlar var).
            sql = f'SELECT "{key_column}", "{value_column}" FROM {dataset_id}'
            if filter_column and filter_value is not None:
                sql += f" WHERE \"{filter_column}\" = '{filter_value.replace(chr(39), chr(39) * 2)}'"
            return sql + f' ORDER BY "{key_column}"'
        sid = dataset_id.replace("'", "''")
        sql = (
            f"SELECT {key_column}, {value_column} FROM {self._relation_for(dataset_id)} "
            f"WHERE series_id = '{sid}'"
        )
        if filter_column and filter_value is not None:
            sql += f" AND {filter_column} = '{filter_value.replace(chr(39), chr(39) * 2)}'"
        return sql + f" ORDER BY {key_column}"

    # ---------- Gold çağrıları (GoldCapable, ADR-0031) ----------
    def _gold_call(self, function: str, series_ids: list[str], target_frequency: str | None) -> QueryResult:
        if self.gold is None:
            raise LakehouseError(
                "Bu lakehouse Gold çağrısı sunmuyor: veri ekibinin `gold-run` komutu bu ortamda yok."
            )
        for sid in series_ids:
            if self._is_gold(sid):
                raise LakehouseError(
                    f"'{sid}' bir seri değil, hazır bir Gold tablosu; onu lakehouse_query ile "
                    "doğrudan sorgula. Gold araçları seri kimliği ister."
                )
            self.get_dataset(sid)  # yüklenmemiş/olmayan seri burada anlaşılır sebeple durur
        started = time.perf_counter()
        out: GoldRunOutcome = self.gold.run(
            function=function, series_ids=list(series_ids), target_frequency=target_frequency
        )
        duration = (time.perf_counter() - started) * 1000
        if out.status == "refused":
            raise GoldRefused(out.reason or "REFUSED", out.message or "", series_id=out.series_id)
        if not out.ok or out.frame is None:
            raise LakehouseError(f"Gold çağrısı başarısız: {out.message or out.status}")

        frame = out.frame
        specs = [self._catalog[s] for s in series_ids if s in self._catalog]
        warnings: list[str] = []
        for column in frame.columns:
            base = str(column).rsplit("::", 1)[-1]
            if base in ("quality_flag", "decomposition_flag"):
                counts = frame[column].astype(str).value_counts()
                flagged = {k: int(v) for k, v in counts.items() if k not in ("ok", "None", "nan")}
                if flagged:
                    warnings.append(
                        f"{column}: " + ", ".join(f"{k}×{v}" for k, v in sorted(flagged.items()))
                    )
        if "is_complete_period" in frame.columns:
            incomplete = int((~frame["is_complete_period"].astype(bool)).sum())
            if incomplete:
                warnings.append(f"{incomplete} dönemde en az bir seri yayımlamamış (hücre boş, sıfır değil).")
        for spec in specs:
            warnings.extend(n for n in spec.notes if not n.startswith("Fiziksel sorgu"))
        args = ", ".join(f"'{s}'" for s in series_ids)
        if target_frequency:
            args += f", target_frequency='{target_frequency}'"
        return QueryResult(
            data=frame,
            provenance=QueryProvenance(
                sql=f"gold-run {function}({args})",
                dataset_ids=list(series_ids),
                sources=[f"{s.source} — {s.name}" for s in specs] + [f"gold — {function}"],
                source_urls=[s.source_url for s in specs if s.source_url],
                row_count=len(frame),
                duration_ms=duration,
                warnings=warnings,
            ),
        )

    def gold_align(self, series_id: str, target_frequency: str) -> QueryResult:
        return self._gold_call("align_frequency", [series_id], target_frequency)

    def gold_decompose(self, series_id: str) -> QueryResult:
        return self._gold_call("decompose_cumulative", [series_id], None)

    def gold_join(self, series_ids: list[str], target_frequency: str) -> QueryResult:
        return self._gold_call("join_on_period", list(series_ids), target_frequency)

    def health(self) -> dict[str, Any]:
        n_obs = self._conn().execute(f"SELECT count(*) FROM {SILVER_RELATION}").fetchone()[0]
        n_adhoc = (self._conn().execute(f"SELECT count(*) FROM {ADHOC_RELATION}").fetchone()[0]
                   if getattr(self, "_has_adhoc", False) else 0)
        unverified = sorted(
            s.dataset_id for s in self._catalog.values()
            if any("DOĞRULANMAMIŞ" in n for n in s.notes)
        )
        return {
            "ok": True,
            "db_path": str(self.db_path),
            "relation": SILVER_RELATION,
            "queryable_series": len(self._catalog) - len(self._gold_meta),
            "catalogued_series": len(self._catalog) - len(self._gold_meta) + len(self._uningested),
            "uningested_series": len(self._uningested),
            "observations": n_obs,
            "adhoc_observations": n_adhoc,
            "draft_series": sum(1 for sid, rel in self._relation_by_series.items()
                                if rel == ADHOC_RELATION and sid in self._catalog),
            "gold_tables": len(self._gold_meta),
            "stale_gold_tables": sum(1 for m in self._gold_meta.values() if m["stale"]),
            "gold_run_available": self.gold is not None,
            # Sayı önce, örnek sonra: 1600 kimliği ekrana dökmek teşhis değil gürültüdür.
            "unverified_series": (
                f"{len(unverified)} seri"
                + (f" (ör. {', '.join(unverified[:5])})" if unverified else "")
            ),
            "hardened": True,
        }
