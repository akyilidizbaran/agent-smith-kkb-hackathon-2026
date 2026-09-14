"""Shared URL-access behaviour cases with the agent (M05-T03).

The agent's web fetch and file reader (agent-core ``kkb_agent.web.addresses``) and this connector must reach the
same decision for the same address or host name. The cases live once, at the repository root
(``docs/sozlesmeler/url_erisim_vakalari.json``), and both packages' tests read them. The reason label is
documentation only: CPython 3.12 patch releases disagree on it for IPv4-mapped addresses.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import pytest

from src.lakehouse.generic._access import AccessDeniedError, assert_url_is_allowed

CASES = json.loads(
    (Path(__file__).resolve().parents[3] / "docs" / "sozlesmeler" / "url_erisim_vakalari.json").read_text(
        encoding="utf-8"
    )
)
URL = "https://veri.example.com/data.csv"


@pytest.mark.parametrize("case", CASES["adresler"], ids=lambda c: c["adres"])
def test_shared_address_case(case: dict) -> None:
    def resolver(_host: str) -> list:
        return [ipaddress.ip_address(case["adres"])]

    if case["beklenen"] == "ret":
        with pytest.raises(AccessDeniedError):
            assert_url_is_allowed(URL, resolver=resolver)
    else:
        assert_url_is_allowed(URL, resolver=resolver)


@pytest.mark.parametrize("case", CASES["adlar"], ids=lambda c: c["ad"])
def test_shared_host_name_case(case: dict) -> None:
    def resolver(_host: str) -> list:
        return [ipaddress.ip_address("93.184.216.34")]

    url = f"https://{case['ad']}/data.csv"
    if case["beklenen"] == "ret":
        with pytest.raises(AccessDeniedError):
            assert_url_is_allowed(url, resolver=resolver)
    else:
        assert_url_is_allowed(url, resolver=resolver)
