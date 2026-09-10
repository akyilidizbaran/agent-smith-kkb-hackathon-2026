"""Genericlik: motor kodunda alan terimi yok; alan bilgisi yalnız domain/*.md'de."""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "kkb_agent_v3"
_FINANS = re.compile(r"\b(konut|kredi|bddk|tcmb|faiz|mortgage|tüfe)\b", re.I)


def test_motor_kodunda_finans_terimi_yok() -> None:
    kirli = []
    for p in SRC.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        # Docstring/yorumlardaki ölçüm anlatımları serbest; yalnız kod satırlarına bak.
        body = re.sub(r'"""[\s\S]*?"""', "", text)
        body = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("#"))
        if _FINANS.search(body):
            kirli.append(p.name)
    assert kirli == [], kirli
