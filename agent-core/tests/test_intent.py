"""Niyet kapısı: adres kullanıcıdan mı, yazma isteği var mı; alt süreç ortamı gizleri taşımaz (ADR-0037)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.adapters.lakehouse_cli import subprocess_env  # noqa: E402
from kkb_agent.core.intent import locator_from_user, write_intent  # noqa: E402


def test_url_kullanici_metninde_ya_da_onayli_listede() -> None:
    text = "Şu sayfadan bak: https://www.tcmb.gov.tr/x/Enflasyon+Verileri/ ve bir de https://a.example/b?x=1"
    assert locator_from_user("https://www.tcmb.gov.tr/x/Enflasyon+Verileri", text)
    assert locator_from_user("https://a.example/b?x=1", text)
    assert not locator_from_user("https://a.example/b?x=2", text)
    assert not locator_from_user("https://a.example/b", text)
    assert not locator_from_user("https://evil.example/tufe.csv", text)
    assert locator_from_user("https://evil.example/tufe.csv", text, sanctioned={"https://evil.example/tufe.csv/"})
    assert not locator_from_user("", text)


def test_yerel_dosya_adi_kullanici_metninde() -> None:
    assert locator_from_user("/tmp/kkb_incoming/konut_test.csv", "şu dosyayı ekle: /tmp/kkb_incoming/konut_test.csv")
    assert locator_from_user("file:///tmp/in/tufe_2025.html", "Şu sayfadan: /tmp/in/tufe_2025.html")
    assert not locator_from_user("/tmp/kkb_incoming/baska.csv", "konut_test.csv dosyasını ekle")


def test_yazma_niyeti() -> None:
    assert write_intent("Şu dosyayı veri havuzuna taslak seri olarak ekle")
    assert write_intent("bunu yükler misin")
    assert not write_intent("Şu dosyada 2025 değeri ne?")


def test_alt_surec_ortami_gizleri_tasimaz() -> None:
    env = subprocess_env({"PATH": "/usr/bin", "HOME": "/h", "MIA_API_KEY": "gizli", "LLM_API_KEY": "gizli",
                          "EVDS_API_KEY": "gizli", "TAVILY_API_KEY": "gizli", "VIRTUAL_ENV": "/venv", "LANG": "tr"})
    assert env == {"PATH": "/usr/bin", "HOME": "/h", "LANG": "tr"}
