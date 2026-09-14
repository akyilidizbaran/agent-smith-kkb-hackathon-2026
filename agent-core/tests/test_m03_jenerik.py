"""M03 (ADR-0060): aynı motor, finans kataloğu olmadan, farklı bir kaynak türüyle (bellek-içi adaptör) çalışır.

Kanıtlanan: (1) `LakehouseClient` sözleşmesini sağlayan yeni bir adaptör ajan koduna dokunmadan takılır
(REST/DB/stream kaynağının ekleneceği yer burasıdır); (2) alan profili bu katalogdan türetilir, modele giden
metinde finans terimi yoktur; (3) araçlar (arama, tanım, sorgu, kolon ekleme, analitik) yeni alanda çalışır;
(4) yüklenen iki tarihsiz tablo modelden bağımsız beklenen sonuçla birleşir (A08, A09). LLM yok.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.builder.read import read_table_for_profiling  # noqa: E402
from kkb_agent.contracts.catalog import ColumnRole, ColumnSpec, Coverage, DatasetSpec, Frequency, SemanticType  # noqa: E402
from kkb_agent.contracts.lakehouse import LakehouseError, QueryProvenance, QueryResult  # noqa: E402
from kkb_agent.core.agent import SYSTEM_PROMPT  # noqa: E402
from kkb_agent.core.registry import ToolRegistry  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.domain import DomainProfile  # noqa: E402
from kkb_agent.tools.analytics import AnomalyDetectTool, AnomalyParams  # noqa: E402
from kkb_agent.tools.lakehouse import LakehouseDescribeTool, LakehouseSearchTool  # noqa: E402
from kkb_agent.tools.workspace import AddColumnParams, WorkspaceAddColumnTool  # noqa: E402
from kkb_agent.tools.workspace_join import JoinParams, WorkspaceJoinTool  # noqa: E402
from kkb_agent.web.html import convert_numbers  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "generic"
FINANCE = re.compile(r"kredi|bakiye|faiz|enflasyon|banka|bddk|evds|tüfe|konut|mevduat", re.I)


class MemoryLakehouse:
    """Yeni kaynak türü: bellek-içi uzun tablo. Ajan kodu bu sınıfı tanımaz; yalnız sözleşmeyi kullanır."""

    def __init__(self, frames: dict[str, tuple[DatasetSpec, pd.DataFrame]]) -> None:
        self.frames = frames
        self.con = duckdb.connect(":memory:")
        long = pd.concat([f.assign(series_id=sid) for sid, (_, f) in frames.items()], ignore_index=True)
        self.con.register("obs", long)

    def list_datasets(self):
        return [spec for spec, _ in self.frames.values()]

    def get_dataset(self, dataset_id):
        if dataset_id not in self.frames:
            raise LakehouseError(f"'{dataset_id}' yok")
        return self.frames[dataset_id][0]

    def search_datasets(self, query, limit=5):
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
        hits = [spec for spec, _ in self.frames.values() if any(w in f"{spec.name} {spec.description}".lower() for w in words)]
        return hits[:limit]

    def execute_sql(self, sql, *, max_rows=10_000):
        if not sql.lstrip().upper().startswith("SELECT"):
            raise LakehouseError("yalnız SELECT")
        data = self.con.execute(sql).fetch_df().head(max_rows)
        ids = [sid for sid in self.frames if sid in sql]
        return QueryResult(data=data, provenance=QueryProvenance(sql=sql, dataset_ids=ids, sources=["bellek-içi test kaynağı"], row_count=len(data)))

    def preview(self, dataset_id, n=5):
        return self.execute_sql(f"SELECT * FROM obs WHERE series_id = '{dataset_id}' LIMIT {n}")

    def series_sql(self, dataset_id, *, key_column, value_column, filter_column=None, filter_value=None):
        spec = self.get_dataset(dataset_id)
        if value_column not in [c.name for c in spec.columns]:
            raise LakehouseError(f"'{value_column}' kolonu yok")
        return f"SELECT {key_column}, {value_column} FROM obs WHERE series_id = '{dataset_id}' ORDER BY 1"

    def health(self):
        return {"ok": True, "datasets": len(self.frames)}

    def close(self):
        self.con.close()


def _spec(sid, name, desc, semantic, unit):
    return DatasetSpec(
        dataset_id=sid, name=name, description=desc, source="SAĞLIK-TEST", frequency=Frequency.MONTHLY, time_column="donem",
        grain=["donem"], columns=[ColumnSpec(name="donem", role=ColumnRole.TIME, dtype="DATE", description="ay sonu"),
                                  ColumnSpec(name="deger", role=ColumnRole.MEASURE, dtype="DOUBLE", description=name, semantic_type=semantic, unit=unit)],
        coverage=Coverage(start=date(2025, 1, 31), end=date(2025, 12, 31), row_count=12), tags=["saglik"],
    )


def _lake() -> MemoryLakehouse:
    acil = pd.read_csv(FIX / "acil_basvuru_aylik.csv", sep=";")
    acil = pd.DataFrame({"donem": pd.to_datetime(acil["tarih"]), "deger": acil["acil_basvuru"].astype(float)})
    doluluk = pd.DataFrame({"donem": acil["donem"], "deger": [71.0, 69, 73, 72, 75, 77, 80, 79, 74, 72, 71, 88]})
    return MemoryLakehouse({
        "saglik:acil_basvuru": (_spec("saglik:acil_basvuru", "Acil servis başvuru sayısı", "Aylık toplam acil servis başvurusu", SemanticType.FLOW, "adet"), acil),
        "saglik:yatak_doluluk": (_spec("saglik:yatak_doluluk", "Yatak doluluk oranı", "Aylık ortalama yatak doluluk oranı (%)", SemanticType.RATIO, "yüzde"), doluluk),
    })


def test_a08_profil_yeni_katalogdan_ve_modele_giden_metin_finans_terimi_tasimaz() -> None:
    lake = _lake()
    profile = DomainProfile.from_catalog(lake.list_datasets())
    rendered = profile.render(SYSTEM_PROMPT)
    assert "SAĞLIK-TEST" in profile.domain and not FINANCE.search(profile.domain)
    assert not FINANCE.search(rendered), FINANCE.findall(rendered)
    registry = ToolRegistry(profile)
    ws = AnalysisWorkspace()
    registry.register_all([LakehouseSearchTool(lake), LakehouseDescribeTool(lake), WorkspaceAddColumnTool(lake, ws), AnomalyDetectTool(ws)])
    schemas = str(registry.schemas())
    assert not FINANCE.search(schemas), FINANCE.findall(schemas)


def test_yeni_kaynak_turu_arac_zincirinde_calisir() -> None:
    lake = _lake()
    ws = AnalysisWorkspace()
    registry = ToolRegistry(DomainProfile.from_catalog(lake.list_datasets()))
    registry.register_all([LakehouseSearchTool(lake), LakehouseDescribeTool(lake), WorkspaceAddColumnTool(lake, ws), AnomalyDetectTool(ws)])
    found = registry.execute("lakehouse_search", {"query": "acil servis başvuru"})
    assert found.ok and "saglik:acil_basvuru" in found.content
    assert registry.execute("lakehouse_describe", {"dataset_id": "saglik:acil_basvuru"}).ok
    base = lake.execute_sql(lake.series_sql("saglik:acil_basvuru", key_column="donem", value_column="deger"))
    ws.set_table(base.data.rename(columns={"deger": "acil"}), description="acil başvuru", provenance=base.provenance)
    added = registry.execute("workspace_add_column", {"dataset_id": "saglik:yatak_doluluk", "key_column": "donem", "value_column": "deger",
                                                        "column_name": "doluluk", "join_on": "donem", "purpose": "doluluk"})
    assert added.ok and ws.table["doluluk"].iloc[-1] == 88.0 and len(ws.table) == 12, "tablo bozulmadan ikinci seri"
    anomaly = registry.execute("anomaly_detect", {"column": "acil", "purpose": "aykırı ay"})
    t = ws.table
    assert anomaly.ok and t.loc[t["acil_anomali"] == "aykırı", "donem"].dt.month.tolist() == [12], "Aralık sıçraması (beklenen sonuç)"


def test_a09_yuklenen_iki_tarihsiz_tablo_beklenen_sonucla_birlesir() -> None:
    hastane, _ = read_table_for_profiling(str(FIX / "hastane_il.csv"), allowed_roots=[FIX])
    nufus, _ = read_table_for_profiling(str(FIX / "nufus_il.csv"), allowed_roots=[FIX])
    hastane, notes = convert_numbers(hastane)
    assert any("yatak_sayisi" in n and "belirsiz" in n for n in notes), notes
    nufus, _ = convert_numbers(nufus)
    # "7.120 / 22.310": kolonun tamamı tek noktalı üçlü grup → 7,12 mi 7120 mi veriden çıkmaz: METİN kalır (sorulur).
    # "5.864 / 818": düz tam sayı da olduğu için nokta binliktir (karışık kolon kuralı) → 5864.
    assert hastane["yatak_sayisi"].tolist()[:2] == ["7.120", "22.310"] and nufus["nufus_bin"].tolist()[:2] == [5864.0, 2274.0]
    ws = AnalysisWorkspace()
    ws.set_table(nufus, description="nüfus", provenance=QueryProvenance(sql="web_url nufus_il.csv tablo#0", dataset_ids=[], sources=["web — nufus_il.csv"]))
    ws.set_table(hastane, description="hastane", provenance=QueryProvenance(sql="web_url hastane_il.csv tablo#0", dataset_ids=[], sources=["web — hastane_il.csv"]))
    tool = WorkspaceJoinTool(ws)
    dup = tool.run(JoinParams(left="k1", right="k2", left_key="il_adi", right_key="il", purpose="nüfus ve hastane"))
    assert not dup.ok and "Van" in dup.error.message, "sağda yinelenen anahtar (Van) → ret"
    ws.set_table(hastane.drop_duplicates(), description="hastane tekil", provenance=QueryProvenance(sql="workspace_query tekil", dataset_ids=[], sources=["web — hastane_il.csv"]))
    asked = tool.run(JoinParams(left="k1", right="k3", left_key="il_adi", right_key="il", purpose="nüfus ve hastane"))
    assert not asked.ok and "metin_normal" in asked.error.candidates, "D01: 'ankara' ↔ 'Ankara' eşdeğerliği sorulur"
    ok = tool.run(JoinParams(left="k1", right="k3", left_key="il_adi", right_key="il", key_policy="metin_normal", purpose="nüfus ve hastane"))
    t = ws.table
    assert ok.ok and "Eşleşen 3 · yalnız solda 1 · yalnız sağda 1" in ok.content
    assert t.loc[t["il_adi"] == "ankara", "hastane_sayisi"].iloc[0] == 96 and pd.isna(t.loc[t["il_adi"] == "Trabzon", "hastane_sayisi"].iloc[0])
    assert ws.column_provenance("hastane_sayisi").sources == ["web — hastane_il.csv"]
