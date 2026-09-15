"""E8 — how large can the catalog be before "catalog in the prompt" stops working or gets too slow?

For N in --sizes, put the whole catalog (one line per series) in the prompt, ask the model to return the
single best series_id for each test query, and measure accuracy, latency and prompt tokens.
Non-thinking, temperature 0. Uses scripts/exp_catalog.py (synthetic, REAL targets always included).

    python scripts/exp_e8_catalog_threshold.py --sizes 60,200,1000,3000 --out docs/experiments/E8_catalog_threshold.md
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from exp_catalog import QUERIES, build  # noqa: E402

try:
    from openai import OpenAI
except ImportError:
    sys.exit("pip install openai")


def env_yukle(yol: str = ".env") -> None:
    p = Path(yol)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        if v:
            os.environ.setdefault(k.strip(), v)


SYSTEM = ("Sen bir veri kataloğu yönlendiricisisin. Kullanıcının sorusuna EN uygun tek bir series_id döndür. "
          "Yalnızca series_id yaz; açıklama, noktalama, ek metin yok. Katalogda uygun seri yoksa NONE yaz.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="60,200,1000,3000")
    ap.add_argument("--out", default="docs/experiments/E8_catalog_threshold.md")
    ap.add_argument("--max-queries", type=int, default=50)
    args = ap.parse_args()
    env_yukle()
    key = os.environ.get("LLM_API_KEY") or os.environ.get("MIA_API_KEY")
    if not key:
        sys.exit("LLM_API_KEY yok")
    client = OpenAI(base_url=os.environ.get("LLM_BASE_URL", "https://mia.csp.kloudeks.com/v1"), api_key=key, timeout=180)
    model = os.environ.get("LLM_MODEL", "kkbhackathon2026/Qwen3.8-27B")
    queries = QUERIES[: args.max_queries]

    lines = ["# E8 — katalog-prompt'ta eşiği", "", f"model: `{model}` · sorgu sayısı: {len(queries)} · non-thinking, T=0", "",
             "| N seri | prompt token | doğruluk | p50 s | p95 s | kategori kırılımı |", "|---|---|---|---|---|---|"]
    for n in [int(s) for s in args.sizes.split(",")]:
        cat = build(n)
        catalog_text = "\n".join(s.prompt_line() for s in cat)
        correct, lat, ptoks = 0, [], []
        by_cat: dict[str, list[int]] = {}
        errors = []
        for q, target, category in queries:
            t0 = time.perf_counter()
            r = client.chat.completions.create(
                model=model, temperature=0, max_tokens=40,
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": f"KATALOG:\n{catalog_text}\n\nSORU: {q}\nYalnızca series_id yaz."}],
                extra_body={"reasoning_effort": "none"},
            )
            lat.append(time.perf_counter() - t0)
            if r.usage:
                ptoks.append(r.usage.prompt_tokens)
            ans = (r.choices[0].message.content or "").strip().split()[0] if (r.choices[0].message.content or "").strip() else ""
            ok = int(ans == target)
            correct += ok
            by_cat.setdefault(category, []).append(ok)
            if not ok:
                errors.append(f"{q!r} → {ans} (beklenen {target})")
        acc = correct / len(queries)
        p50 = statistics.median(lat)
        p95 = sorted(lat)[int(0.95 * (len(lat) - 1))]
        cats = ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in by_cat.items())
        lines.append(f"| {n} | {int(statistics.mean(ptoks)) if ptoks else '-'} | {acc:.0%} | {p50:.2f} | {p95:.2f} | {cats} |")
        print(lines[-1])
        if errors:
            lines.append("")
            lines.append(f"<details><summary>N={n} hatalar ({len(errors)})</summary>\n\n" + "\n".join(f"- {e}" for e in errors) + "\n\n</details>")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
