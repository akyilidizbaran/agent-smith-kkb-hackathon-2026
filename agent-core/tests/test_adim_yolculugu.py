"""ADR-0085: adım yolculuğu. Ajanın araç adımları sırayla, her araç türü kendi figürüyle; arka arkaya aynı araç tek durak.

Durak kurucusu (`stepStops`) arayüzün JS'inde; kanıt yolculuğu testleri gibi node üzerinde gerçek adım yükü şekliyle koşturulur.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from kkb_agent.web_app import STATIC_DIR

HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def _chain_js() -> str:
    start = HTML.index("// ---------------- Kanıt yolculuğu (ADR-0083)")
    return HTML[start:HTML.index('$("btn-journey").addEventListener', start)]


def _helper(name: str) -> str:
    i = HTML.index(f"const {name} = ")
    return HTML[i:re.compile(r"\n(?=\S)").search(HTML, i).start()]


def _stops(payload: dict) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("node yok; durak kurucusu tarayıcı dışında koşturulamıyor")
    helpers = "\n".join(_helper(n) for n in ("esc", "fmtInt", "hostOf", "httpUrl", "fmtWhen", "prettySql", "sqlTables"))
    script = (f"globalThis.window = {{}};\n{helpers}\n{_chain_js()}\n"
              f"process.stdout.write(JSON.stringify(stepStops({json.dumps(payload)}).map((s) => ({{kind: s.kind, state: s.state, status: s.status, n: s.calls.length, total: s.total || null}}))));")
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=30, check=True)
    return json.loads(out.stdout)


def _step(tool: str | None, *, ok: bool = True, ms: int = 1700, role: str = "execute", index: int = 1, **kw) -> dict:
    return {"index": index, "role": role, "tool": tool, "ok": ok, "duration_ms": ms, "label": "", "detail": kw.get("detail", ""),
            "args": kw.get("args", {}), "error_code": kw.get("error_code"), "summary": kw.get("summary", ""), "thought": kw.get("thought", "")}


def test_adimlar_sirali_ayni_arac_tek_durak_hata_rozetli() -> None:
    steps = [_step("workspace_join", ok=False, error_code="JOIN_MISMATCH"), _step("workspace_query", index=2), _step("workspace_query", index=2),
             _step("workspace_join", ok=False, index=3), _step("workspace_query", index=4),
             *[_step("lakehouse_search", role="retrieve", index=i, ms=2000) for i in (5, 6, 6, 7, 8)],
             _step("lakehouse_describe", role="retrieve", index=9), _step("lakehouse_query", index=10, ms=3400), _step("chart", role="narrate", index=11),
             _step(None, ok=False, role="validate", index=12, thought="grounding: MISS")]
    stops = _stops({"steps": steps, "usage": {"prompt": 235958, "completion": 900, "calls": 12}, "elapsed_s": 31.2})
    assert [s["kind"] for s in stops] == ["join", "wsquery", "join", "wsquery", "search", "describe", "query", "chart", "validate", "answer"], "sıra korunur"
    assert stops[0]["state"] == "broken" and stops[0]["status"] == "1 hata · 1,7 s"
    assert stops[1]["n"] == 2 and stops[1]["status"] == "×2 · 3,4 s", "arka arkaya aynı araç tek durak"
    assert stops[4]["n"] == 5 and stops[4]["status"] == "×5 · 10,0 s"
    assert stops[8]["state"] == "warn" and stops[8]["status"] == "taslak geri gönderildi"
    assert stops[-1]["status"] == "31,2 s" and stops[-1]["total"]["tools"] == 13 and stops[-1]["total"]["errors"] == 2 and stops[-1]["total"]["backs"] == 1


def test_kismen_hatali_grup_amber_arac_yoksa_yalniz_cevap() -> None:
    stops = _stops({"steps": [_step("lakehouse_query", ok=False), _step("lakehouse_query")], "elapsed_s": 4})
    assert stops[0]["state"] == "warn" and stops[0]["status"] == "×2 · 1 hata · 3,4 s"
    only = _stops({"steps": [{"index": 1, "role": "narrate", "tool": None, "ok": True, "thought": "selamlaşma", "duration_ms": 0}], "elapsed_s": 0})
    assert [s["kind"] for s in only] == ["answer"]


def test_her_arac_turunun_figuru_ve_adi_var_bilinmeyen_arac_genel_figur() -> None:
    js = _chain_js()
    kinds = set(re.findall(r'"(\w+)"', js[js.index("const STEP_KIND = {"):js.index("};", js.index("const STEP_KIND = {"))])[1::2])
    for kind in kinds | {"validate", "answer", "tool"}:
        assert re.search(rf"\n  {kind}: ", js[js.index("const SFIG = {"):js.index("const SMETA")]), f"{kind} figürü yok"
        assert f"{kind}: [\"" in js[js.index("const SMETA = {"):js.index("const STEP_KIND")], f"{kind} adı yok"
    assert _stops({"steps": [_step("yeni_arac")], "elapsed_s": 1})[0]["kind"] == "tool"


def test_arayuz_yolculugun_yaninda_adimlari_izle_alt_cubuk_tek_satir() -> None:
    right = HTML[HTML.index('<aside class="right">'):]
    assert right.index('id="btn-journey"') < right.index('id="btn-steps"') < right.index('id="ev-badge"'), "Yolculuğu izle'nin yanında"
    trace = HTML[HTML.index("function renderTrace(p) {"):HTML.index("\n}\n", HTML.index("function renderTrace(p) {"))]
    assert 'class="chip' not in trace and "data-steps" in trace, "alt çubukta çip dizisi yok; tek satır özet ve pencere düğmesi"
    assert 'chainViewer({\n  id: "journey"' in HTML and 'chainViewer({\n  id: "steps"' in HTML, "iki pencere aynı göstericiyi kullanır"
