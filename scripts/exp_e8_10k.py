"""E8-10k — katalog özeti → search_series geçiş modunun EVDS ölçeğinde (3k / 10k / 30k seri) testi.

E8 (10 Eylül) tam kataloğu prompt'a koyup 60/200/1000/3000 seride ölçtü: doğruluk 1000'den,
gecikme 200'den sonra kırılıyor. 10k seri ≈ 280k token → tam-katalog kolu bağlam sınırının
dışında; bu deney GEÇİŞ MODUNU test eder: aday üretimi → ≤1k token liste → model seçer.

Katalog modeli (v2, ilk koşunun dersinden sonra): her gerçek kavramın SINIRLI sayıda yakın
kopyası (banka grubu / il / para birimi / frekans; kavram başına ≤ MAX_VARIANTS, kategoriye
uygun olanlar) + kalan yer İLGİSİZ filler (exp_catalog.build: başka kavramlar). İlk koşuda
(v1) kavram başına ~500 varyant vardı ve "Adana politika faizi" gibi anlamsız kombinasyonlar
üretiliyordu; sonuçlar bu yüzden aşırı kötümserdi (R@30 %69 @30k).

Kollar:
  bm25     düz BM25 top-K (V3 §3.5'in mevcut varsayımı)
  grouped  iki aşamalı: BM25 kavramlar (taban seriler) üstünde top-G → her kavram + sorguyla
           örtüşen varyantları (≤ V) → ≤K satır. openecon'un "provider → series" yönlendirmesine
           benzer; gerçek katalogda kavram anahtarı `meta.series` alanı gerektirir.
  hybrid   BM25 ∪ dense RRF (--dense)
  full     tam katalog, yalnız max_model_len izin veriyorsa (--full)

    python scripts/exp_e8_10k.py --sizes 3000,10000,30000 --out docs/experiments/E8_10k_results.md
    python scripts/exp_e8_10k.py --probe-only
"""
from __future__ import annotations

import argparse
import os
import random
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from exp_catalog import QUERIES, REAL, Series, build  # noqa: E402
from exp_retrieval_bakeoff import env_yukle, rrf, tokens  # noqa: E402

try:
    import bm25s
    import numpy as np
    from openai import OpenAI
except ImportError:
    sys.exit("pip install bm25s openai numpy")

SYSTEM = ("Sen bir veri kataloğu yönlendiricisisin. Aşağıdaki ADAY listesinden kullanıcının sorusuna EN uygun "
          "tek bir series_id döndür. Yalnızca series_id yaz; açıklama, noktalama, ek metin yok. "
          "Adaylarda uygun seri yoksa NONE yaz.")

MAX_VARIANTS = 48          # kavram başına yakın-kopya üst sınırı [ASM: EVDS'de bir kavramın 10–50 kırılımı olur]
_GROUPS = ["mevduat bankaları", "katılım bankaları", "kamu bankaları", "yerli özel bankalar", "yabancı bankalar", "kalkınma ve yatırım bankaları"]
_PROVINCES = ["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Adana", "Konya", "Gaziantep", "Kocaeli", "Mersin", "Kayseri", "Samsun"]
_CURRENCY = [("TP", "Türk parası"), ("YP", "yabancı para")]
_FREQ = ["monthly", "weekly", "quarterly", "daily"]
# Hangi kırılım hangi kategoriye uygulanabilir (anlamsız kombinasyon üretmemek için)
_BANK_CATS = ("krediler", "bilanço", "yapısal", "rasyolar", "mevduat", "kâr")


def _kinds_for(base: Series) -> list[tuple[str, str, list[str]]]:
    """(kind, alias_prefix_style, values) — bu kavrama uygulanabilir kırılımlar."""
    kinds: list[tuple[str, str, list[str]]] = []
    bankish = base.category.startswith(_BANK_CATS)
    if bankish:
        kinds.append(("group", "{v} {a}", _GROUPS))
        kinds.append(("province", "{v} {a}", _PROVINCES))
    if base.unit.startswith("TRY") and bankish:
        kinds.append(("currency", "{v} {a}", [c for c, _ in _CURRENCY]))
    kinds.append(("frequency", "{v} {a}", [f for f in _FREQ if f != base.frequency]))
    return kinds


def build_v2(n: int, seed: int = 11) -> tuple[list[Series], list[tuple[str, str, str]], dict[str, str]]:
    """REAL + gerçekçi varyantlar + ilgisiz filler; hard_variant sorguları; base_of haritası."""
    rng = random.Random(seed)
    out = list(REAL)
    base_of: dict[str, str] = {s.series_id: s.series_id for s in REAL}
    variants_of: dict[str, list[tuple[Series, str]]] = {}
    i = 0
    for base in REAL:
        combos: list[tuple[str, str]] = []
        for kind, style, values in _kinds_for(base):
            for v in values:
                combos.append((kind, v))
        # iki boyutlu kombinasyonlar (grup × para birimi) gerçekçi ve sık
        if base.category.startswith(_BANK_CATS) and base.unit.startswith("TRY"):
            for g in _GROUPS:
                for c, _ in _CURRENCY:
                    combos.append(("group+currency", f"{g}|{c}"))
        rng.shuffle(combos)
        for kind, v in combos[:MAX_VARIANTS]:
            if kind == "group+currency":
                g, c = v.split("|")
                name = f"{base.name_tr} ({g}, {c})"
                al = [f"{g} {c} {base.aliases[0]}"] if base.aliases else []
                freq = base.frequency
                qtext = f"{g} {c} {base.aliases[0]}" if base.aliases else name
            elif kind == "frequency":
                name, freq = f"{base.name_tr} ({v})", v
                al = [f"{v} {base.aliases[0]}"] if base.aliases else []
                qtext = f"{v} {base.aliases[0]}" if base.aliases else name
            else:
                name, freq = (f"{base.name_tr} – {v}" if kind == "province" else f"{base.name_tr} ({v})"), base.frequency
                al = [f"{v} {a}" for a in base.aliases[:2]]
                qtext = f"{v} {base.aliases[0]}" if base.aliases else name
            sid = f"syn:var:{i:06d}"
            s = replace(base, series_id=sid, name_tr=name, aliases=al, category=base.category + "/variant", frequency=freq)
            out.append(s)
            base_of[sid] = base.series_id
            variants_of.setdefault(base.series_id, []).append((s, qtext))
            i += 1
        if len(out) >= n:
            break
    # kalan yer: ilgisiz kavramlar (E8'in filler'ı; REAL'i tekrar eklemesin)
    if len(out) < n:
        filler = [s for s in build(n - len(out) + len(REAL), seed=seed + 1) if s.series_id.startswith("syn:fill:")]
        for s in filler[: n - len(out)]:
            out.append(s)
            base_of[s.series_id] = s.series_id
    rng.shuffle(out)
    out = out[:n]
    present = {s.series_id for s in out}
    hard: list[tuple[str, str, str]] = []
    bases = [b for b in variants_of if any(v.series_id in present for v, _ in variants_of[b])]
    for base_id in rng.sample(sorted(bases), min(20, len(bases))):
        v, qtext = rng.choice([(v, q) for v, q in variants_of[base_id] if v.series_id in present])
        hard.append((qtext, v.series_id, "hard_variant"))
    return out, hard, base_of


def probe_max_len(client: OpenAI, model: str) -> int | None:
    try:
        models = client.models.list()
    except Exception as exc:  # noqa: BLE001
        print("  /v1/models okunamadı:", exc)
        return None
    for m in models.data:
        if m.id == model:
            return getattr(m, "max_model_len", None) or (m.model_dump().get("max_model_len"))
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="3000,10000,30000")
    ap.add_argument("--k", type=int, default=30)
    ap.add_argument("--groups", type=int, default=8, help="grouped kolu: kaç kavram")
    ap.add_argument("--per-group", type=int, default=4, help="grouped kolu: kavram başına en fazla varyant")
    ap.add_argument("--arms", default="bm25,grouped")
    ap.add_argument("--dense", action="store_true")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--max-queries", type=int, default=50)
    ap.add_argument("--out", default="docs/experiments/E8_10k_results.md")
    args = ap.parse_args()
    env_yukle()
    key = os.environ.get("LLM_API_KEY") or os.environ.get("MIA_API_KEY")
    if not key:
        sys.exit("LLM_API_KEY yok")
    client = OpenAI(base_url=os.environ.get("LLM_BASE_URL", "https://mia.csp.kloudeks.com/v1"), api_key=key, timeout=300)
    model = os.environ.get("LLM_MODEL", "kkbhackathon2026/Qwen3.8-27B")

    max_len = probe_max_len(client, model)
    print(f"max_model_len={max_len}")
    if args.probe_only:
        return

    lines = [f"# E8-10k — geçiş modu EVDS ölçeğinde (katalog modeli v2: kavram başına ≤{MAX_VARIANTS} varyant + ilgisiz filler)", "",
             f"model: `{model}` · max_model_len: {max_len or 'bilinmiyor'} · sorgu: {args.max_queries} standart + 20 hard_variant · "
             f"K={args.k}, grouped G={args.groups}×V={args.per_group} · non-thinking, T=0", "",
             "| N seri | kol | R@K (retrieval tavanı) | uçtan uca doğruluk | prompt token | p50 s | p95 s | kırılım |",
             "|---|---|---|---|---|---|---|---|"]

    for n in [int(s) for s in args.sizes.split(",")]:
        cat, hard, base_of = build_v2(n)
        ids = [s.series_id for s in cat]
        by_id = {s.series_id: s for s in cat}
        queries = list(QUERIES[: args.max_queries]) + hard
        docs = [s.doc() for s in cat]
        retriever = bm25s.BM25()
        retriever.index([tokens(d) for d in docs])

        def bm25_rank(q: str, k: int = args.k) -> list[str]:
            res, _ = retriever.retrieve([tokens(q) or ["_"]], k=min(k, len(ids)))
            return [ids[i] for i in res[0]]

        # grouped: kavram (taban) düzeyinde ayrı indeks
        bases = [s for s in cat if base_of[s.series_id] == s.series_id]
        base_ids = [s.series_id for s in bases]
        base_ret = bm25s.BM25()
        base_ret.index([tokens(s.doc()) for s in bases])
        children: dict[str, list[str]] = {}
        for s in cat:
            b = base_of[s.series_id]
            if b != s.series_id:
                children.setdefault(b, []).append(s.series_id)

        def grouped_rank(q: str) -> list[str]:
            res, _ = base_ret.retrieve([tokens(q) or ["_"]], k=min(args.groups, len(base_ids)))
            qt = set(tokens(q))
            out: list[str] = []
            for i in res[0]:
                b = base_ids[i]
                out.append(b)
                kids = children.get(b, [])
                # sorguyla örtüşen varyantlar önce (varyantın EK token'ları sorguda geçiyor mu)
                base_tok = set(tokens(by_id[b].doc()))
                scored = sorted(kids, key=lambda k: -len((set(tokens(by_id[k].doc())) - base_tok) & qt))
                out.extend(scored[: args.per_group])
            return out[: args.k]

        arms: dict[str, object] = {}
        if "bm25" in args.arms:
            arms["bm25"] = bm25_rank
        if "grouped" in args.arms:
            arms["grouped"] = grouped_rank
        if args.dense:
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
            print(f"  dense index N={n}: {time.perf_counter() - t0:.0f}s")
            instr = "Instruct: Türkçe finansal veri sorusu için eşleşen zaman serisi metadata kaydını bul\nQuery: "

            def hybrid_rank(q: str) -> list[str]:
                qv = embed([instr + q])[0]
                dense = [ids[i] for i in np.argsort(-(D @ qv))[: args.k]]
                return rrf([bm25_rank(q), dense])[: args.k]

            arms["hybrid"] = hybrid_rank

        full_text = "\n".join(s.prompt_line() for s in cat)
        full_tokens_est = int(len(full_text) / 3.5)
        if args.full:
            if max_len and full_tokens_est < 0.8 * max_len:
                arms["full"] = None
            else:
                lines.append(f"| {n} | full | - | atlandı | ~{full_tokens_est} (> 0,8×max_model_len) | - | - | tam katalog bağlama sığmıyor |")

        for arm, rank_fn in arms.items():
            hit_k = correct = 0
            lat: list[float] = []
            ptoks: list[int] = []
            by_cat: dict[str, list[int]] = {}
            errors: list[str] = []
            for q, target, category in queries:
                if rank_fn is None:
                    cand_text, in_k = full_text, True
                else:
                    cands = rank_fn(q)  # type: ignore[operator]
                    in_k = target in cands
                    hit_k += int(in_k)
                    cand_text = "\n".join(by_id[c].prompt_line() for c in cands)
                t0 = time.perf_counter()
                r = client.chat.completions.create(
                    model=model, temperature=0, max_tokens=40,
                    messages=[{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": f"ADAYLAR:\n{cand_text}\n\nSORU: {q}\nYalnızca series_id yaz."}],
                    extra_body={"reasoning_effort": "none"},
                )
                lat.append(time.perf_counter() - t0)
                if r.usage:
                    ptoks.append(r.usage.prompt_tokens)
                content = (r.choices[0].message.content or "").strip()
                ans = content.split()[0] if content else ""
                ok = int(ans == target)
                correct += ok
                by_cat.setdefault(category, []).append(ok)
                if not ok:
                    errors.append(f"{q!r} → {ans} (beklenen {target}; top-K'da {'var' if in_k else 'YOK'})")
            nq = len(queries)
            rk = "-" if rank_fn is None else f"{hit_k / nq:.0%}"
            cats = ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in by_cat.items())
            row = (f"| {n} | {arm} | {rk} | {correct / nq:.0%} | {int(statistics.mean(ptoks)) if ptoks else '-'} | "
                   f"{statistics.median(lat):.2f} | {sorted(lat)[int(0.95 * (nq - 1))]:.2f} | {cats} |")
            lines.append(row)
            print(row, flush=True)
            if errors:
                lines.append(f"\n<details><summary>N={n} {arm} hatalar ({len(errors)})</summary>\n\n" + "\n".join(f"- {e}" for e in errors) + "\n\n</details>\n")

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", args.out)


if __name__ == "__main__":
    main()
