"""M05-T03: web getirme, dosya okuyucu ve lakehouse bağlayıcısı aynı adres/ad vakalarında aynı kararı verir.

Vakalar repo kökündeki `docs/sozlesmeler/url_erisim_vakalari.json`; lakehouse tarafı
`lakehouse-core/tests/generic/test_shared_url_cases.py` aynı dosyayı okur. Ağ yok: çözümleyici yamalanır."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.builder import read as reader  # noqa: E402
from kkb_agent.web import fetch  # noqa: E402

CASES = json.loads((Path(__file__).resolve().parents[2] / "docs" / "sozlesmeler" / "url_erisim_vakalari.json").read_text(encoding="utf-8"))


def _fake_resolver(address: str):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return lambda host, port, *a, **k: [(family, socket.SOCK_STREAM, 6, "", (address, 0))]


@pytest.mark.parametrize("case", CASES["adresler"], ids=lambda c: c["adres"])
def test_ortak_adres_vakasi_web_ve_okuyucu_ayni_karar(case, monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver(case["adres"]))
    expected = case["beklenen"] == "ret"
    assert fetch.private_host("veri.example.com") is expected, case
    assert reader._private_host("veri.example.com") is expected, case
    assert fetch.private_host(case["adres"]) is expected, "adres doğrudan yazıldığında da aynı"


@pytest.mark.parametrize("case", CASES["adlar"], ids=lambda c: c["ad"])
def test_ortak_ad_vakasi(case, monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver("93.184.216.34"))
    assert fetch.private_host(case["ad"]) is (case["beklenen"] == "ret"), case


def test_redirect_hedefi_ortak_kurala_takilir(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _fake_resolver("224.0.0.1"))
    with pytest.raises(fetch.RedirectRefused):
        fetch._check_target("http://yayin.example.com/x.csv", allow_private=False)
