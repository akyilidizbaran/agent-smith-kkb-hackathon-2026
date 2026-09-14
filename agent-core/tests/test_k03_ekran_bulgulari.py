"""K03 ekran provası ve canlı tekrar bulguları (14 Eyl): kart tablosunda metin dolgusu, yıl-ay yazımı, bakış sonucu kanıtı."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.core.grounding import grounding_check, numbers_in  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402
from kkb_agent.tools.web import _plain  # noqa: E402


class _Seed:
    pass


def test_kart_tablosunda_metin_degerlerin_onunde_dolgu_yok() -> None:
    card = _plain(pd.DataFrame({"il": ["Adana", "Ankara", "Van"], "hastane_sayisi": [41, 96, 18],
                                "tarih": pd.to_datetime(["2025-01-31", "2025-02-28", "2025-03-31"])}))
    lines = card.splitlines()
    assert lines[1].startswith("Adana ") and lines[3].startswith("Van "), "kısa metin sola hizalı, satır başında boşluk yok"
    assert all(not ln.startswith(" ") for ln in lines)
    assert lines[1].split()[1] == "41" and "2025-01-31" in lines[1], "sayı ve tarih değeri korunur"


def test_yil_ay_yazimi_tarihtir_yil_araligi_degil() -> None:
    assert numbers_in("tablonun kapsamı 2026-06'ya kadar uzanıyor") == []
    assert numbers_in("2021-25 arası") == [2021.0, 25.0], "yıl aralığı maskelenmez"
    assert numbers_in("2026-13 kodu") != [], "geçersiz ay tarih sayılmaz"
    frame = pd.DataFrame({"observation_date": [date(2025, 1, 31)], "value": [523455.0]})
    ws = AnalysisWorkspace()
    ws.set_table(frame, description="2025")
    panel = EvidenceBuilder(_Seed()).build("2025 bakiyesi", "Ocak 2025: 523.455 milyon TL; kapsam 2026-06'ya kadar.", ws, [])
    assert panel.claims_ok, panel.summary()
    assert grounding_check("2025 bakiyesi", "kapsam 2026-06'ya kadar", ["523455"]) == "OK"


def test_lakehouse_bakis_sonucu_kanit_havuzuna_girer() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_lakehouse_tools import StubLakehouse
    from kkb_agent.tools.lakehouse import LakehouseQueryTool

    rates = pd.DataFrame({"donem": pd.to_datetime(["2025-01-31", "2025-02-28"]), "deger": [40.536, 39.975]})
    ws = AnalysisWorkspace()
    ws.set_table(pd.DataFrame({"observation_date": [date(2025, 1, 31), date(2025, 2, 28)], "value": [523455.0, 535029.0]}), description="bakiye")
    res = LakehouseQueryTool(StubLakehouse(rates), ws).validate_and_run({"sql": "SELECT donem, deger FROM test_tablo", "purpose": "faiz, bakış", "as_active_table": False})
    assert res.ok and list(ws.table.columns) == ["observation_date", "value"], "bakış modu aktif tabloyu değiştirmez"
    assert ws.peeks() and ws.peeks()[0][1]["deger"].tolist() == [40.536, 39.975]
    panel = EvidenceBuilder(_Seed()).build("faiz?", "Ocak 2025 faizi %40,54, Şubat 2025 %39,98.", ws, [])
    assert panel.claims_ok, panel.summary()
