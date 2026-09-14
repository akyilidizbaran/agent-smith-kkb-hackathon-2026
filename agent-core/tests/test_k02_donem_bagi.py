"""K02-T14 (M13-T04/T07): aynı sayının başka dönemde bulunması doğrulama sayılmaz; eski tablo eşleşmesi kimlik, kaynak ve
sorguyla gösterilir."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kkb_agent.contracts.lakehouse import QueryProvenance  # noqa: E402
from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402


class _Seed:
    def list_datasets(self):
        return []


def _ws() -> AnalysisWorkspace:
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"donem": [date(2024, 12, 31), date(2025, 12, 31)], "bakiye": [100.0, 120.0]}), description="yıllık",
                 provenance=QueryProvenance(sql="SELECT donem, bakiye FROM silver.x", dataset_ids=["s"], sources=["BDDK Aylık"]))
    return ws


def test_yanlis_donemdeki_ayni_sayi_dogrulanmis_sayilmaz() -> None:
    wrong = EvidenceBuilder(_Seed()).build("q", "Aralık 2025'te bakiye 100 milyon TL idi.", _ws(), [])
    n = next(x for x in wrong.numbers if x.text == "100")
    assert n.matched and n.period_warning and not wrong.claims_ok and "dönem uyuşmazlığı" in wrong.summary()
    right = EvidenceBuilder(_Seed()).build("q", "Aralık 2024'te bakiye 100 milyon TL idi; 2025 sonunda 120 oldu.", _ws(), [])
    assert right.claims_ok, [(x.text, x.row_key, x.period_warning) for x in right.numbers]
    assert next(x for x in right.numbers if x.text == "120").row_key.startswith("2025-12-31")
    no_period = EvidenceBuilder(_Seed()).build("q", "Bakiye 100 milyon TL seviyesindeydi.", _ws(), [])
    assert no_period.claims_ok, "dönem yazılmamışsa bağ denetimi yapılmaz"


def test_onceki_tablo_eslesmesi_kimlik_kaynak_ve_sorgu_tasir() -> None:
    ws = _ws()
    ws.set_table(pd.DataFrame({"il": ["Adana"], "hastane": [41.0]}), description="yeni",
                 provenance=QueryProvenance(sql="web_url hastane.csv tablo#0", dataset_ids=[], sources=["web — hastane.csv"]))
    panel = EvidenceBuilder(_Seed()).build("q", "Önceki tabloda bakiye 120 idi.", ws, [])
    n = next(x for x in panel.numbers if x.text == "120")
    assert n.matched and n.row_key.startswith("önceki tablo k1") and "BDDK Aylık" in n.row_key and "SELECT donem" in n.row_key
