"""Retrieval bake-off (small) — alias-exact vs BM25 vs MIA dense embedding vs hybrid RRF.

Corpus: scripts/exp_catalog.py (REAL series with aliases + filler to N). Queries: hand-written QUERIES.
Metrics: Recall@1, Recall@3, Recall@5, MRR, latency. Embeddings via MIA Qwen3-Embedding-8B (instruction-aware);
BM25 via bm25s with a simple Turkish-aware lowercasing tokenizer (no stemmer; documented limitation).

    python scripts/exp_retrieval_bakeoff.py --n 300 --out docs/experiments/RETRIEVAL_bakeoff.md
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from exp_catalog import QUERIES, build  # noqa: E402

try:
    import bm25s
    from openai import OpenAI
except ImportError:
    sys.exit("pip install bm25s openai")

TR_MAP = str.maketrans("ÇĞİÖŞÜçğıöşü", "cgiosucgiosu")


def norm(s: str) -> str:
    s = s.replace("I", "ı").lower()
    s = s.translate(TR_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def tokens(s: str) -> list[str]:
    return [t for t in norm(s).split() if len(t) > 1]


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


def metrics(ranked: list[list[str]], targets: list[str]) -> dict[str, float]:
    r1 = r3 = r5 = mrr = 0.0
    for rk, t in zip(ranked, targets):
        if t in rk[:1]:
            r1 += 1
        if t in rk[:3]:
            r3 += 1
        if t in rk[:5]:
            r5 += 1
        if t in rk:
            mrr += 1 / (rk.index(t) + 1)
    n = len(targets)
    return {"R@1": r1 / n, "R@3": r3 / n, "R@5": r5 / n, "MRR": mrr / n}


def rrf(lists: list[list[str]], k: int = 60) -> list[str]:
    score: dict[str, float] = {}
    for lst in lists:
        for i, sid in enumerate(lst):
            score[sid] = score.get(sid, 0) + 1 / (k + i + 1)
    return [s for s, _ in sorted(score.items(), key=lambda x: -x[1])]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--out", default="docs/experiments/RETRIEVAL_bakeoff.md")
    ap.add_argument("--no-dense", action="store_true")
    args = ap.parse_args()
    env_yukle()
    cat = build(args.n)
    ids = [s.series_id for s in cat]
    docs = [s.doc() for s in cat]
    queries = [q for q, _, _ in QUERIES]
    targets = [t for _, t, _ in QUERIES]
    cats = [c for _, _, c in QUERIES]
    results: dict[str, list[list[str]]] = {}
    timing: dict[str, float] = {}

    # --- alias exact (normalized substring on name/aliases)
    t0 = time.perf_counter()
    alias_rank = []
    for q in queries:
        nq = norm(q)
        hits = [s.series_id for s in cat if nq and (nq in norm(s.name_tr) or any(nq == norm(a) or nq in norm(a) for a in s.aliases))]
        alias_rank.append(hits[:10])
    results["alias_exact"] = alias_rank
    timing["alias_exact"] = (time.perf_counter() - t0) / len(queries)

    # --- BM25
    t0 = time.perf_counter()
    corpus_tokens = [tokens(d) for d in docs]
    retriever = bm25s.BM25()
    retriever.index(corpus_tokens)
    bm_rank = []
    for q in queries:
        qt = tokens(q) or ["_"]
        res, _ = retriever.retrieve([qt], k=min(10, len(ids)))
        bm_rank.append([ids[i] for i in res[0]])
    results["bm25"] = bm_rank
    timing["bm25"] = (time.perf_counter() - t0) / len(queries)

    # --- dense (MIA)
    if not args.no_dense:
        key = os.environ.get("LLM_API_KEY") or os.environ.get("MIA_API_KEY")
        if not key:
            sys.exit("LLM_API_KEY yok (dense için)")
        client = OpenAI(base_url=os.environ.get("LLM_BASE_URL", "https://mia.csp.kloudeks.com/v1"), api_key=key, timeout=180)
        emb_model = os.environ.get("EMBEDDING_MODEL", "kkbhackathon2026/Qwen3-Embedding-8B")

        def embed(texts: list[str]) -> np.ndarray:
            out = []
            for i in range(0, len(texts), 64):
                r = client.embeddings.create(model=emb_model, input=texts[i:i + 64], encoding_format="float")
                out.extend(d.embedding for d in r.data)
            m = np.asarray(out, dtype=np.float32)
            return m / np.linalg.norm(m, axis=1, keepdims=True)

        t0 = time.perf_counter()
        D = embed(docs)
        t_index = time.perf_counter() - t0
        instr = "Instruct: Türkçe finansal veri sorusu için eşleşen zaman serisi metadata kaydını bul\nQuery: "
        t0 = time.perf_counter()
        Q = embed([instr + q for q in queries])
        sims = Q @ D.T
        dense_rank = [[ids[j] for j in np.argsort(-sims[i])[:10]] for i in range(len(queries))]
        results["dense_qwen3"] = dense_rank
        timing["dense_qwen3"] = (time.perf_counter() - t0) / len(queries)
        results["hybrid_rrf"] = [rrf([b, d])[:10] for b, d in zip(bm_rank, dense_rank)]
        timing["hybrid_rrf"] = timing["bm25"] + timing["dense_qwen3"]
        results["hybrid_rrf+alias"] = [rrf([a, b, d])[:10] if a else rrf([b, d])[:10] for a, b, d in zip(alias_rank, bm_rank, dense_rank)]
        timing["hybrid_rrf+alias"] = timing["hybrid_rrf"]
        print(f"index build (dense, {len(docs)} docs): {t_index:.1f}s")

    lines = ["# Retrieval bake-off (küçük, sentetik katalog)", "",
             f"N={len(cat)} seri (REAL {sum(1 for s in cat if not s.series_id.startswith('syn:fill'))} + filler) · {len(queries)} el yazımı sorgu · "
             "BM25 stemmer'sız (Türkçe karakter normalize) · dense = Qwen3-Embedding-8B instruct'lı, cosine", "",
             "| Sistem | R@1 | R@3 | R@5 | MRR | ms/sorgu |", "|---|---|---|---|---|---|"]
    for name, rk in results.items():
        m = metrics(rk, targets)
        lines.append(f"| {name} | {m['R@1']:.2f} | {m['R@3']:.2f} | {m['R@5']:.2f} | {m['MRR']:.2f} | {timing[name] * 1000:.0f} |")
        print(lines[-1])
    lines += ["", "## Kategori kırılımı (R@3)", "", "| Sistem | " + " | ".join(sorted(set(cats))) + " |", "|---|" + "---|" * len(set(cats))]
    for name, rk in results.items():
        cells = []
        for c in sorted(set(cats)):
            idx = [i for i, cc in enumerate(cats) if cc == c]
            hit = sum(1 for i in idx if targets[i] in rk[i][:3])
            cells.append(f"{hit}/{len(idx)}")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## Hatalar (R@3 dışı)", ""]
    for name, rk in results.items():
        miss = [f"{queries[i]!r} → {rk[i][:3]} (beklenen {targets[i]})" for i in range(len(queries)) if targets[i] not in rk[i][:3]]
        lines.append(f"<details><summary>{name}: {len(miss)} hata</summary>\n\n" + "\n".join(f"- {m}" for m in miss) + "\n\n</details>\n")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
