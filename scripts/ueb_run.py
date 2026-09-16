"""UEB koşucusu — mevcut harness'ı kullanıcı hatalarına karşı ölçer.

Kullanım (agent-core dizininden; fikstür yolları göreli):
    cd agent-core
    python ../scripts/ueb_run.py                       # tüm vakalar, 1 tekrar
    python ../scripts/ueb_run.py --track A B --repeat 2
    python ../scripts/ueb_run.py --cases A07 B01 --out ../docs/experiments/ueb_x.json

Çıktı: JSON (tam cevaplar, adımlar, bayraklar) + Markdown özet. Sınıflama:
  detected   : warn_any'den biri cevapta geçti (ya da clarify sorusu soruldu)
  wrong      : must_not'tan biri geçti (yanlış sayı/ifade)
  silent     : expected ∈ {abstain, warn, clarify} ve (tablo/sayı üretildi) ve not detected — ya da wrong
  overblock  : expected == answer ve doğru içerik yok ve (uyarı/soru var ya da tablo yok)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CORE = ROOT / "agent-core"
sys.path.insert(0, str(CORE / "src"))
sys.path.insert(0, str(HERE))
os.environ.setdefault("LLM_NARRATE_TEMPERATURE", "0")
# 15 Eyl (ADR-0049, main): varsayılan LAKEHOUSE_MODE=demo Silver şeması ister; UEB vakaları ve 14 Eyl baseline seed
# şemasında (bddk_aylik_krediler) koştu. Karşılaştırılabilirlik için seed modu; DB yolu vaka başına aşağıda ayarlanır.
os.environ["LAKEHOUSE_MODE"] = "seed"
# main'de izinli yerel kök data/incoming oldu (ADR-0054); UEB fikstürleri repo kökündeki incoming/ueb'de (14 Eyl baseline ile aynı).
os.environ.setdefault("INGEST_ALLOWED_ROOT", str(ROOT / "incoming"))

from ueb_cases import CASES, BY_ID, Case  # noqa: E402

DB_VARIANTS = {
    "seed": CORE / "data" / "lakehouse.duckdb",
}
for _v in ("stale", "stale_meta_wrong", "gaps", "dupes"):
    DB_VARIANTS[_v] = HERE / ".ueb_scratch" / "ueb_db" / _v / "lakehouse.duckdb"

_NUM = re.compile(r"(?<![\w.,])[-+]?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\w)|(?<![\w.,])[-+]?\d+(?:[.,]\d+)?(?!\w)")


def numbers_in_answer(text: str) -> list[str]:
    out = []
    for m in _NUM.finditer(text or ""):
        raw = m.group(0)
        v = raw.replace(".", "").replace(",", ".") if "," in raw else (raw.replace(".", "") if raw.count(".") >= 1 and re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", raw) else raw)
        try:
            f = float(v)
        except ValueError:
            continue
        if 1900 <= f <= 2100 and f.is_integer():
            continue  # yıl
        if abs(f) <= 31 and f.is_integer():
            continue  # ay/gün/sıra
        out.append(raw)
    return out


def _hit(text: str, needles: list[str]) -> list[str]:
    low = (text or "").lower()
    return [s for s in needles if s.lower() in low]


def classify(case: Case, answer: str, has_table: bool) -> dict:
    detected = _hit(answer, case.warn_any)
    wrong = _hit(answer, case.must_not)
    correct = _hit(answer, case.must_any)
    nums = numbers_in_answer(answer)
    asked = bool(re.search(r"\?\s*$", (answer or "").strip())) or bool(re.search(r"\?\s*\n", answer or ""))
    produced = has_table or bool(nums)
    verdict: str
    if case.expected in ("abstain", "warn", "clarify"):
        if wrong:
            verdict = "SILENT"
        elif case.expected == "abstain":
            verdict = "SAFE" if (detected and not has_table) else ("PARTIAL" if detected else ("SILENT" if produced else "SAFE"))
        elif case.expected == "clarify":
            verdict = "SAFE" if (asked or detected) else ("SILENT" if produced else "SAFE")
        else:  # warn
            verdict = "SAFE" if detected else ("SILENT" if produced else "PARTIAL")
    else:  # answer (kontrol)
        if wrong:
            verdict = "WRONG"
        elif correct:
            verdict = "PASS"
        elif asked or (not has_table and detected):
            verdict = "OVERBLOCK"
        else:
            verdict = "MISS"
    return {"verdict": verdict, "detected": detected, "wrong": wrong, "correct": correct,
            "asked": asked, "has_table": has_table, "numbers": nums[:12]}


def run_case(case: Case, build_agent, max_steps: int = 12) -> dict:
    db = DB_VARIANTS[case.db]
    if not db.exists():
        return {"id": case.id, "error": f"DB yok: {db} (python scripts/ueb_fixtures.py)"}
    os.environ["LAKEHOUSE_PATH"] = str(db)
    agent = build_agent(max_steps=max_steps)
    started = time.perf_counter()
    steps, answers, usage = [], [], {"prompt": 0, "completion": 0, "calls": 0}
    for q in case.queries:
        a = agent.ask(q)
        answers.append(a.text)
        steps += a.steps
        for k, v in (a.usage or {}).items():
            usage[k] = usage.get(k, 0) + int(v)
    dur = time.perf_counter() - started
    table = agent.workspace.table
    has_table = table is not None and not table.empty
    table_info = None
    if has_table:
        table_info = {"rows": int(len(table)), "cols": list(map(str, table.columns))[:12],
                      "head": table.head(3).to_string(index=False)[:400]}
    final = answers[-1]
    cls = classify(case, final, has_table)
    return {
        "id": case.id, "category": case.category, "persona": case.persona, "expected": case.expected,
        "severity": case.severity, "db": case.db, "queries": case.queries,
        "answer": final, "answers": answers, "duration_s": round(dur, 1),
        "tools": [s.tool_name for s in steps if s.tool_name],
        "error_codes": [s.error_code for s in steps if s.error_code],
        "trace": [f"{'✓' if s.ok else '✗'}{(' ' + s.error_code) if s.error_code else ''} {s.tool_name or s.role}"
                  f"({json.dumps(s.tool_args, ensure_ascii=False)[:90]}) → {s.result_summary[:120]}" for s in steps],
        "grounding": getattr(a, "grounding", ""), "usage": usage, "table": table_info, **cls,
        "note": case.note,
    }


def summarize(results: list[dict]) -> dict:
    guarded = [r for r in results if r.get("expected") in ("abstain", "warn", "clarify")]
    controls = [r for r in results if r.get("expected") == "answer"]
    silent = [r for r in guarded if r["verdict"] == "SILENT"]
    sw = sum(r["severity"] for r in silent)
    gw = sum(r["severity"] for r in guarded) or 1
    return {
        "n": len(results),
        "guarded": len(guarded), "safe": sum(1 for r in guarded if r["verdict"] == "SAFE"),
        "partial": sum(1 for r in guarded if r["verdict"] == "PARTIAL"), "silent": len(silent),
        "silent_rate": round(len(silent) / max(1, len(guarded)), 3),
        "severity_weighted_silent_rate": round(sw / gw, 3),
        "controls": len(controls), "control_pass": sum(1 for r in controls if r["verdict"] == "PASS"),
        "overblock": sum(1 for r in controls if r["verdict"] == "OVERBLOCK"),
        "control_wrong": sum(1 for r in controls if r["verdict"] in ("WRONG", "MISS")),
        "mean_duration_s": round(sum(r.get("duration_s", 0) for r in results) / max(1, len(results)), 1),
    }


def to_markdown(results: list[dict], summary: dict, label: str) -> str:
    lines = [f"# UEB sonucu — {label}", "", "## Özet", "",
             "| ölçüt | değer |", "|---|---:|"]
    for k, v in summary.items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Vakalar", "", "| id | beklenen | karar | tablo | tespit | yanlış | süre | araçlar | cevap (ilk 220) |", "|---|---|---|---|---|---|---:|---|---|"]
    for r in results:
        if "error" in r:
            lines.append(f"| {r['id']} | — | HATA | — | — | — | — | — | {r['error']} |")
            continue
        lines.append(
            f"| {r['id']} | {r['expected']} | **{r['verdict']}** | {'evet' if r['has_table'] else 'hayır'} | "
            f"{', '.join(r['detected'][:4])} | {', '.join(r['wrong'][:3])} | {r['duration_s']} | "
            f"{' → '.join(dict.fromkeys(r['tools']))[:80]} | {r['answer'][:220].replace('|', '/').replace(chr(10), ' ')} |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="*", default=[])
    ap.add_argument("--track", nargs="*", default=[], help="A B C D")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--out", default=None)
    ap.add_argument("--label", default="baseline")
    args = ap.parse_args()

    from kkb_agent.cli import build_agent  # noqa: E402 — env ayarlandıktan sonra

    selected = [c for c in CASES if (not args.cases or any(c.id.startswith(x) for x in args.cases))
                and (not args.track or c.id[0] in args.track)]
    out = Path(args.out) if args.out else ROOT / "docs" / "experiments" / f"ueb_{args.label}_{datetime.now():%Y-%m-%d_%H%M}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    all_runs: list[dict] = []
    print(f"UEB: {len(selected)} vaka × {args.repeat} tekrar → {out}")
    for rep in range(1, args.repeat + 1):
        for case in selected:
            print(f"▶ [{rep}/{args.repeat}] {case.id}", flush=True)
            try:
                r = run_case(case, build_agent, max_steps=args.max_steps)
            except Exception as exc:  # noqa: BLE001
                r = {"id": case.id, "expected": case.expected, "severity": case.severity, "error": f"{type(exc).__name__}: {exc}",
                     "verdict": "ERROR", "has_table": False, "detected": [], "wrong": [], "correct": [], "duration_s": 0, "tools": [], "answer": ""}
            r["rep"] = rep
            all_runs.append(r)
            print(f"   {r.get('verdict')} | {r.get('duration_s')}s | {' → '.join(dict.fromkeys(r.get('tools', [])))[:70]}", flush=True)
            out.write_text(json.dumps(all_runs, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = summarize([r for r in all_runs if "error" not in r])
    md = to_markdown(all_runs, summary, args.label)
    out.with_suffix(".md").write_text(md, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"→ {out} / {out.with_suffix('.md')}")


if __name__ == "__main__":
    main()
