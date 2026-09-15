"""Canlı ölçüm bulgusu (15 Eyl, ADR-0068 eki): arayüzden yüklenen dosya "cb6d79f3_hastane_basvuru_1.csv" adıyla saklanır, model seri
anahtarı vermeyince kimlik "adhoc:cb6d79f3_hastane_basvuru_1" olur. Kullanıcı "hastane_basvuru_1 taslağını onaylıyorum, kataloğa al"
dediğinde terfi reddediliyordu. Ön eksiz ad aynı hedeftir; D03 kuralları (güncel mesaj, ret kazanır, başka hedef) aynen geçerli."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.approvals import ApprovalBook, PendingOp, decide  # noqa: E402

SID = "adhoc:cb6d79f3_hastane_basvuru_1"


def _book(*series: str) -> ApprovalBook:
    book = ApprovalBook()
    for s in series:
        book.register(PendingOp(series_id=s, operation="promote", summary=f"{s} taslağı", shown_turn=1))
    return book


def _decide(book: ApprovalBook, message: str, sid: str = SID):
    return decide(book, operation="promote", series_id=sid, message=message, turn=2, known_targets=[p.series_id for p in book.of("promote")])


def test_on_eksiz_ad_ile_guncel_onay_gecer() -> None:
    assert _decide(_book(SID), "hastane_basvuru_1 taslağını onaylıyorum, kataloğa al.").ok
    assert _decide(_book(SID), "adhoc:cb6d79f3_hastane_basvuru_1 taslağını onaylıyorum").ok, "tam kimlik de geçer"


def test_d03_kurallari_on_eksiz_adda_da_gecerli() -> None:
    assert not _decide(_book(SID), "hastane_basvuru_1 yayınlama.").ok, "güncel ret kazanır"
    assert not _decide(_book(SID), "hastane_basvuru_1 taslağına bir bakalım.").ok, "onay sözü yok"
    other = "adhoc:9a1b2c3d_nufus_il"
    d = _decide(_book(SID, other), "nufus_il taslağını onaylıyorum, kataloğa al.")
    assert not d.ok and "nufus_il" in d.reason, "başka hedefin onayı bu işlemi onaylamaz"
    assert _decide(_book(SID, other), "nufus_il taslağını onaylıyorum, kataloğa al.", sid=other).ok


def test_benzer_ad_ve_onaltilik_olmayan_on_ek_eslesmez() -> None:
    assert not _decide(_book(SID), "hastane_basvuru_10 taslağını onaylıyorum, kataloğa al.").ok, "sözcük sınırı"
    sid = "adhoc:tasarim_hastane"
    assert not _decide(_book(sid), "hastane taslağını onaylıyorum, kataloğa al.", sid=sid).ok, "onaltılık olmayan önek ayıklanmaz"
