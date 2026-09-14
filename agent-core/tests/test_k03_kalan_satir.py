"""K03 hedefli canlı tekrar bulgusu (14 Eyl; gece koşuları 0133/0154'te de): doğru cevap "Kalan 50 ay aktif analiz tablosunda" dediği
için sayılar rozeti ✗ oluyordu. Kalan satır sayısı tablodan türetilir: tablo satırı − cevapta gösterilen farklı satır; yalnız
bununla tutarlıysa ve yanında "kalan/diğer" gibi bir sözcük varsa doğrulanmış sayılır."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.evidence import EvidenceBuilder  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402

AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim"]


class _Seed:
    pass


def _panel(tail: str):
    dates = pd.date_range("2021-01-31", periods=60, freq="ME")
    frame = pd.DataFrame({"observation_date": dates, "value": [276000.0 + 1000 * i for i in range(60)]})
    ws = AnalysisWorkspace()
    ws.set_table(frame, description="konut kredisi 60 ay")
    listed = "\n".join(f"- {AYLAR[i]} 2021: {276 + i}.000 milyon TL" for i in range(10))
    answer = f"2021–2025 arası 60 aylık konut kredisi bakiyeleri aktif analiz tablosunda.\n\n{listed}\n\n{tail}"
    panel = EvidenceBuilder(_Seed()).build("2021-2025 yılları arasındaki 60 aylık veriden konut kredilerini göster.", answer, ws, [])
    return panel, {n.text: n for n in panel.numbers}


def test_canli_cevap_kalan_ay_sayisi_tablodan_turetilir() -> None:
    panel, m = _panel("Kalan 50 ay aktif analiz tablosunda; isterseniz grafiğini çizebilirim.")
    assert m["50"].matched and m["50"].column == "(kalan satır sayısı)" and "10 satır" in m["50"].row_key
    assert panel.claims_ok, panel.summary()


def test_tabloyla_tutarsiz_kalan_sayisi_dogrulanmaz() -> None:
    panel, m = _panel("Kalan 48 ay aktif analiz tablosunda.")
    assert not m["48"].matched and not panel.claims_ok


def test_kalan_sozcugu_olmayan_sayi_dogrulanmaz() -> None:
    panel, m = _panel("Bakiye 50 ayda iki katına çıktı.")
    assert not m["50"].matched and not panel.claims_ok
