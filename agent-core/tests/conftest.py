"""Test ortamı kancaları.

Opsiyonel gerçek-tarayıcı edinme katmanı (``web/browser.py``) birim/entegrasyon testlerinde
DEVRE DIŞI kalır: aksi halde boş/app-shell sayfa senaryolarında gerçek Chrome başlatılır ve
suite ağ + tarayıcıya bağımlı, yavaş ve kırılgan olurdu. Canlı tarayıcı yolu ayrı, işaretli
bir kabul koşusunda (WEB_BROWSER_FALLBACK=1) elle doğrulanır.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_browser_fallback(monkeypatch):
    monkeypatch.setenv("WEB_BROWSER_FALLBACK", "0")
