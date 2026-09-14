"""K03 canlı tekrar bulgusu (14 Eyl): doğru cevap "işaret uyarısı" alıyordu. Model aynı büyüklüğü tabloda işaretli ("−0,51 puan"),
yorumda işaretsiz ve yön sözcüğüyle ("faiz düşüşü küçük (0,06–0,51 puan)") yazdı; yön penceresi ilk (işaretli) geçişe bakıyordu
ve işaret çevirmeli eşleşmede gösterilen ondalığın yuvarlama toleransı yoktu. A14 kuralı korunur: yönsüz işaretsiz sayı uyarı alır."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.evidence import EvidenceBuilder, _direction_word_near  # noqa: E402
from kkb_agent.core.workspace import AnalysisWorkspace  # noqa: E402


class _Seed:
    pass


def _panel(answer: str):
    frame = pd.DataFrame({
        "observation_date": [date(2021, 2, 28), date(2021, 5, 31), date(2023, 12, 31), date(2024, 1, 31)],
        "konut_kredisi": [276263.0, 275130.0, 438222.0, 436688.0], "konut_faizi": [17.985, 17.835, 42.088, 41.5775],
        "faiz_degisim": [-0.403, -0.299, -0.062, -0.5105], "kredi_degisim": [-522.0, -1196.0, -2190.0, -1534.0],
    })
    ws = AnalysisWorkspace()
    ws.set_table(frame, description="faiz düşerken kredi artmayan aylar")
    panel = EvidenceBuilder(_Seed()).build("Faiz düşerken kredi artmayan dönemler?", answer, ws, [])
    return panel, {n.text: n for n in panel.numbers}


# Canlı koşudaki cevabın (acceptance_m16_2026-09-14_k03_tekrar3.json, A02-A07 3. tur) sayı taşıyan kısmı.
LIVE = """| Ay | Bakiye (milyon TL) | Faiz (%) | Bakiye değişimi | Faiz değişimi |
|---|---|---|---|---|
| Şubat 2021 | 276.263 | 17,99 | −522 | −0,40 puan |
| Mayıs 2021 | 275.130 | 17,84 | −1.196 | −0,30 puan |
| Aralık 2023 | 438.222 | 42,09 | −2.190 | −0,06 puan |
| Ocak 2024 | 436.688 | 41,58 | −1.534 | −0,51 puan |

- 2021'deki iki ayda faiz düşüşü sınırlı (0,3–0,4 puan) ve bakiye de küçük miktarda gerilemiş.
- Aralık 2023 – Ocak 2024'te faiz düşüşü daha belirgin (özellikle Ocak 2024'te 0,51 puan) ama bakiye yine azalmış.
Bu aylarda faiz düşüşü küçük (0,06–0,51 puan)."""


def test_canli_cevap_isaretli_tablo_ve_yon_sozcuklu_yorum_uyari_almaz() -> None:
    panel, m = _panel(LIVE)
    for t in ("0,3", "0,4", "0,51", "0,06"):
        assert m[t].matched and not m[t].sign_warning, (t, m[t].row_key)
    assert panel.claims_ok, panel.summary()


def test_yonsuz_isaretsiz_sayi_hala_uyari_alir_a14() -> None:
    panel, m = _panel("| Ocak 2024 | −0,51 puan |\nOcak 2024 için değer 0,51 puan.")
    assert m["0,51"].matched and m["0,51"].sign_warning and not panel.claims_ok


def test_isaret_cevirmede_gosterilen_ondalik_toleransi_maddi_fark_eslesmez() -> None:
    _, m = _panel("Faiz 0,06 puan düştü; kredi 0,07 puan düştü.")
    assert m["0,06"].matched and not m["0,06"].sign_warning, "−0,062 ↔ 0,06 yuvarlama"
    assert not m["0,07"].matched, "−0,062 ↔ 0,07 yarım birimden büyük fark"


def test_isaretli_gecis_yon_penceresine_sayilmaz() -> None:
    assert not _direction_word_near("Düşüş: −0,51.", "0,51"), "yalnız işaretli geçiş var"
    assert _direction_word_near("−0,51 tabloda; yorum: 0,51 puan geriledi.", "0,51")
    assert not _direction_word_near("10,51 düştü", "0,51"), "başka sayının parçası geçiş değildir"
