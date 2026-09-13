"""Retrieval golden: sorudan seriye recall ölçümü — kademe eşikleri buradan konur (ADR-0043).

Sorgu kaynağı iki türlü: (1) katalogdan üretilen — her serinin adı ve takma adları
(kullanıcının söyleyeceği ifadeler, ADR-0003), (2) elle yazılmış Türkçe sorular
(`HAND_QUERIES`): il, frekans, kaynak yüzleri ve ulusal/il ayrımı gibi tuzaklar.

Katalog kaynağı iki türlü: `--database <duckdb>` (meta.series, üretimdeki 2.214) ya da
`--json <evds_all_series.json>` (EVDS'nin 53k serisi, yalnız retrieval ölçümü için).

Ölçülen: recall@1 ve recall@8, mod başına (bm25 yüzsüz, bm25 yüzlü, hybrid). Aynı
`CatalogRetriever` üretimde de çalışır; ölçülen şey kullanılan şeydir.

    uv run python scripts/retrieval_golden.py --database /tmp/kkb_demo_acceptance/data/lakehouse.duckdb
    uv run python scripts/retrieval_golden.py --json .../evds_all_series.json --modes bm25,hybrid --sample 2000
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kkb_agent.core.facets import province_of  # noqa: E402
from kkb_agent.core.lexical import fold  # noqa: E402
from kkb_agent.core.retriever import CatalogRecord, CatalogRetriever, RetrievalPolicy  # noqa: E402

# (soru, beklenen kimlik ya da 're:<düzenli ifade>' ad üzerinde)
HAND_QUERIES: list[tuple[str, str]] = [
    ("2025'te dolar kuru ne kadardı?", "evds:TP.DK.USD.A.YTL"),
    ("euro kuru", "evds:TP.DK.EUR.A.YTL"),
    ("TCMB politika faizi", "evds:TP.BISPOLFAIZ.TUR"),
    ("ağırlıklı ortalama fonlama maliyeti", "evds:TP.APIFON4"),
    ("mevduat faizi 3 aylık", "evds:TP.TRY.MT02"),
    ("kredi kartı harcamaları haftalık", "evds:TP.KKHARTUT.KT1"),
    ("M2 para arzı", "evds:TP.HPBITABLO1.11"),
    ("geniş para arzı M3", "evds:TP.HPBITABLO1.18"),
    ("TÜFE genel endeks", "evds:TP.TUKFIY2025.GENEL"),
    ("konut kredisi faiz oranı haftalık", "evds:TP.KTF12"),
    ("konut fiyat endeksi Türkiye", "evds:TP.KFE.TR"),
    ("konut kredisi bakiyesi aylık", "bddk_monthly:1534_Toplam"),
    ("2025 yılında konut kredisi bakiyesi", "bddk_monthly:1534_Toplam"),
    ("taşıt kredisi bakiyesi", "bddk_monthly:1535_Toplam"),
    ("ihtiyaç kredileri toplamı", "bddk_monthly:1536_Toplam"),
    ("bireysel kredi kartı borcu", "bddk_monthly:1539_Toplam"),
    ("takipteki konut kredileri", "bddk_monthly:1545_Toplam"),
    ("takipteki ihtiyaç kredisi", "bddk_monthly:1547_Toplam"),
    ("bankacılık sektörü toplam kredileri", "bddk_monthly:1160_Toplam"),
    ("toplam aktifler", "bddk_monthly:1688_Toplam"),
    ("bankaların özkaynakları", "bddk_monthly:1717_Toplam"),
    ("toplam mevduat", "bddk_monthly:1357_Toplam"),
    ("takipteki alacak oranı", "bddk_monthly:544_Rasyo"),
    ("kredi mevduat oranı", "bddk_monthly:1749_Rasyo"),
    ("sermaye yeterlilik oranı", "bddk_monthly:1746_Rasyo"),
    ("haftalık konut kredisi bakiyesi", "bddk_weekly:5690_3"),
    ("İzmir'de taşıt kredisi", "bddk_finturk:IZMIR_TasitKredisi"),
    ("Ankara kredi kartı bakiyesi", "bddk_finturk:ANKARA_BireyselKrediKartlari"),
    ("İstanbul takipteki konut kredisi", "bddk_finturk:ISTANBUL_TakiptekiKonutKredisi"),
    ("Van ilindeki konut kredisi", "bddk_finturk:VAN_KonutKredisi"),
    ("Bursa ihtiyaç kredisi çeyreklik", "bddk_finturk:BURSA_DigerTuketiciKredileri"),
    ("Konya'da kredili mevduat hesabı", "bddk_finturk:KONYA_KrediliMevduatHesabi"),
    ("taşıt kredisi faizi", "re:Taşıt Kredisi \\(TL, Akım"),
    ("ticari kredi faiz oranı", "re:^Ticari Krediler \\(TL, Akım"),
]


def load_records_from_db(path: str) -> list[CatalogRecord]:
    import duckdb

    con = duckdb.connect(path, read_only=True)
    rows = con.execute(
        "SELECT series_id, source_id, name_tr, description, aliases, tags, frequency FROM meta.series WHERE status='active'"
    ).fetchall()
    con.close()
    out = []
    for sid, source, name, desc, aliases, tags, freq in rows:
        out.append(CatalogRecord(id=sid, name=name or "", description=desc or "", aliases=tuple(aliases or []),
                                 tags=tuple(tags or []), frequency=freq, source=source,
                                 province=province_of(f"{sid} {name}")))
    return out


def load_records_from_json(path: str, sample: int | None, seed: int = 7) -> list[CatalogRecord]:
    items = json.load(open(path, encoding="utf-8"))
    freq_map = {"GÜNLÜK": "daily", "İŞ GÜNÜ": "business_daily", "HAFTALIK(CUMA)": "weekly", "HAFTALIK": "weekly",
                "AYLIK": "monthly", "3 AYLIK": "quarterly", "ÜÇ AYLIK": "quarterly", "6 AYLIK": "semiannual", "YILLIK": "yearly"}
    recs = [CatalogRecord(id=f"evds:{it['code']}", name=it.get("name") or "", description=f"{it.get('group') or ''}. Birim: {it.get('unit') or ''}",
                          frequency=freq_map.get(str(it.get("freq") or "").strip().upper()), source="evds")
            for it in items if it.get("code")]
    if sample and sample < len(recs):
        random.Random(seed).shuffle(recs)
        recs = recs[:sample]
    return recs


def generated_queries(records: list[CatalogRecord], per_record: int, seed: int = 7) -> list[tuple[str, str]]:
    rng = random.Random(seed)
    out = []
    for r in records:
        cands = [r.name] + list(r.aliases)
        rng.shuffle(cands)
        for q in cands[:per_record]:
            q = re.sub(r"\s+", " ", q).strip()
            if len(q) >= 4:
                out.append((q, r.id))
    return out


def expected_match(expected: str, records_by_id: dict[str, CatalogRecord], cand_id: str) -> bool:
    if expected.startswith("re:"):
        rec = records_by_id.get(cand_id)
        return bool(rec and re.search(expected[3:], rec.name))
    return cand_id == expected


def evaluate(retriever: CatalogRetriever, queries: list[tuple[str, str]], *, mode: str, use_facets: bool, k: int = 8) -> dict:
    by_id = {r.id: r for r in retriever.records}
    hit1 = hit8 = 0
    misses: list[tuple[str, str, list[str]]] = []
    started = time.perf_counter()
    vectors: list | None = None
    if mode == "hybrid" and retriever.embedder is not None:
        vectors = retriever.embed_queries([q for q, _ in queries])
    for idx, (q, expected) in enumerate(queries):
        hits = retriever.search(q, k=k, mode=mode, use_facets=use_facets,
                                query_vector=vectors[idx] if vectors is not None else None)
        ids = [h.id for h in hits]
        ok8 = any(expected_match(expected, by_id, i) for i in ids)
        ok1 = bool(ids) and expected_match(expected, by_id, ids[0])
        hit1 += ok1
        hit8 += ok8
        if not ok8 and len(misses) < 25:
            misses.append((q, expected, ids[:3]))
    n = len(queries)
    return {"mode": mode, "facets": use_facets, "n": n, "recall@1": round(hit1 / n, 3) if n else 0,
            "recall@8": round(hit8 / n, 3) if n else 0, "seconds": round(time.perf_counter() - started, 1), "misses": misses}


def main() -> int:
    ap = argparse.ArgumentParser(description="Retrieval golden: recall@k, mod başına")
    ap.add_argument("--database")
    ap.add_argument("--json")
    ap.add_argument("--sample", type=int, default=None, help="JSON kataloğundan örneklem (büyük ölçek)")
    ap.add_argument("--per-record", type=int, default=2, help="seri başına üretilen sorgu")
    ap.add_argument("--modes", default="bm25,bm25f", help="virgülle: bm25 (yüzsüz), bm25f (yüzlü), hybrid")
    ap.add_argument("--hand-only", action="store_true")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()

    if args.database:
        records = load_records_from_db(args.database)
    elif args.json:
        records = load_records_from_json(args.json, args.sample)
    else:
        ap.error("--database ya da --json gerekli")
    by_id = {r.id: r for r in records}
    hand = [(q, e) for q, e in HAND_QUERIES if e.startswith("re:") or e in by_id]
    queries = hand if args.hand_only else generated_queries(records, args.per_record) + hand
    print(f"katalog: {len(records)} seri | sorgu: {len(queries)} (elle {len(hand)})")

    embedder = None
    cache = None
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    if "hybrid" in modes:
        from kkb_agent.adapters.mia_embedder import EmbeddingCache, MiaEmbedder
        import kkb_agent.config as cfg
        st = cfg.load_settings()
        embedder = MiaEmbedder(base_url=st.llm_base_url, api_key=st.llm_api_key, model=st.embedding_model or "kkbhackathon2026/Qwen3-Embedding-8B")
        cache = EmbeddingCache(st.embedding_cache_dir)
    retriever = CatalogRetriever(records, policy=RetrievalPolicy(mode="bm25"), embedder=embedder, embedding_cache=cache)

    results = []
    for m in modes:
        mode, facets = {"bm25": ("bm25", False), "bm25f": ("bm25", True), "hybrid": ("hybrid", True), "hybridnf": ("hybrid", False)}[m]
        res = evaluate(retriever, queries, mode=mode, use_facets=facets)
        results.append(res)
        print(f"  {m:9s} recall@1={res['recall@1']:.3f} recall@8={res['recall@8']:.3f} ({res['seconds']} s)")
        if res["misses"]:
            print("    ilk kaçaklar:")
            for q, e, ids in res["misses"][:6]:
                print(f"      {q!r} → beklenen {e} | gelen {ids}")
    if args.report:
        Path(args.report).write_text(json.dumps({"catalog": len(records), "queries": len(queries), "results": results},
                                                ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
