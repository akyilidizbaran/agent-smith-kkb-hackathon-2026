"""K02-T12 / A30 canlı prova: Architect yüklü aralık DIŞINDAKİ dönemi kayıtlı kaynağından çeker.

Geçici kökte başlangıç kataloğuyla DB kurulur; gerçek web uygulaması, gerçek harness ve gerçek `ingest_source` aracı kullanılır
(model yerine betik). Aracın içi ağa çıkar: toplu ingest betiği gerçek kaynağa gider. Silver'da istenen dönemin gözlemi
aranır. Asıl demo DB dokunulmaz (parmak iziyle gösterilir).

    uv run python scripts/k02_a30_canli.py --work /tmp/k02_a30 [--series bddk_monthly:1534_Toplam --start 2015-12-01 --end 2015-12-31]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def query(db: Path, sql: str, params: list) -> list:
    code = ("import duckdb, json, sys; a = json.load(sys.stdin); con = duckdb.connect(a['db'], read_only=True); "
            "print(json.dumps(con.execute(a['sql'], a['params']).fetchall(), default=str))")
    out = subprocess.run([sys.executable, "-c", code], input=json.dumps({"db": str(db), "sql": sql, "params": params}),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--series", default="bddk_monthly:1534_Toplam")
    ap.add_argument("--start", default="2015-12-01")
    ap.add_argument("--end", default="2015-12-31")
    args = ap.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    data = work / "data"
    (data / "incoming").mkdir(parents=True)
    db = data / "lakehouse.duckdb"
    os.environ.update({"DATA_ROOT": str(data), "LAKEHOUSE_PATH": str(db), "INGEST_ALLOWED_ROOT": str(data / "incoming"),
                       "CHART_DIR": str(data / "charts"), "EMBEDDING_CACHE_DIR": str(data / "cache" / "embeddings"),
                       "ARCHITECT_TOKEN": "a30", "AGENT_PROFILE": "architect", "LAKEHOUSE_MODE": "demo", "EMBEDDING_MODEL": "",
                       "VISION_MODEL": "", "TOOL_GATE": "off"})
    sys.path.insert(0, str(ROOT / "src"))
    from fastapi.testclient import TestClient

    from kkb_agent.llm.base import LLMResponse, ToolCall
    from kkb_agent.web_app import build_default_app

    demo_db = REPO / "data" / "lakehouse.duckdb"
    demo_before = sha256(demo_db)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    boot = subprocess.run(["uv", "run", "python", "-m", "lakehouse", "bootstrap", "--database", str(db), "--data-root", str(data),
                           "--catalog", "default"], cwd=REPO / "lakehouse-core", capture_output=True, text=True, check=False)
    steps: list[dict] = []

    def check(sid, beklenen, ok, gozlenen):
        steps.append({"id": sid, "beklenen": beklenen, "ok": bool(ok), "gozlenen": str(gozlenen)[:800]})
        print(f"  {'✓' if ok else '✗'} {sid}: {beklenen} — {str(gozlenen)[:260]}", flush=True)

    check("kurulum", "geçici kökte başlangıç kataloğu", boot.returncode == 0, boot.stdout.strip().replace("\n", " · ") or boot.stderr[-300:])
    before = query(db, "SELECT count(*) FROM silver.fact_observation WHERE series_id = ? AND observation_date BETWEEN ? AND ?",
                   [args.series, args.start, args.end])[0][0]
    check("once", "istenen dönem yüklü değil", before == 0, before)

    app = build_default_app()
    client = TestClient(app)

    class Scripted:
        model = "a30-betik"

        def __init__(self, turns):
            self.turns = list(turns)

        def supports_native_tools(self):
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            return self.turns.pop(0) if self.turns else LLMResponse(content="Tamam.")

    app.state.session.agent.llm = Scripted([
        LLMResponse(content="", tool_calls=[ToolCall(id="c1", name="ingest_source", arguments={
            "series_id": args.series, "start": args.start, "end": args.end, "purpose": "yüklü aralık dışını kaynaktan çek"})]),
        LLMResponse(content="İstenen dönem kaynağından çekildi; sorgulanabilir."),
    ])
    t0 = datetime.now()
    payload = client.post("/api/ask", json={"question": f"{args.series} serisinin {args.start} – {args.end} dönemini kaynağından çek."}).json()
    secs = round((datetime.now() - t0).total_seconds(), 1)
    step = next((s for s in payload.get("steps", []) if s.get("tool") == "ingest_source"), {})
    check("arac", "ingest_source gerçek kaynaktan çekti ve Silver'ı yeniledi", step.get("ok"),
          {"süre_s": secs, "özet": step.get("summary") or step.get("error_code"), "hata": step.get("error_code")})
    after = query(db, "SELECT observation_date, value FROM silver.fact_observation WHERE series_id = ? AND observation_date BETWEEN ? AND ? ORDER BY 1",
                  [args.series, args.start, args.end])
    runs = query(db, "SELECT count(*) FROM meta.run", [])[0][0]
    check("sonra", "istenen dönemin gözlemi Silver'da, run kaydıyla", bool(after) and runs >= 1, {"gözlem": after, "run": runs})
    check("demo-db", "asıl demo DB değişmedi", sha256(demo_db) == demo_before, "aynı" if sha256(demo_db) == demo_before else "DEĞİŞTİ")
    out = REPO / "docs" / "experiments" / f"k02_a30_canli_{datetime.now():%Y-%m-%d_%H%M}.json"
    out.write_text(json.dumps({"meta": {"commit": commit, "series": args.series, "start": args.start, "end": args.end, "work": str(work)},
                               "passed": sum(s["ok"] for s in steps), "total": len(steps), "steps": steps}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\nSONUÇ: {sum(s['ok'] for s in steps)}/{len(steps)} · rapor {out}")
    return 0 if all(s["ok"] for s in steps) else 1


if __name__ == "__main__":
    sys.exit(main())
