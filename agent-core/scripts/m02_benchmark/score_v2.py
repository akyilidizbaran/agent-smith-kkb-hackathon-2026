"""V2 benchmark otomatik puanlayıcı (sayısal oracle vakaları).

`csv_numeric_reference` vakalarında ajanın ürettiği tablo, bağımsız referans CSV ile karşılaştırılır.
Davranış/politika vakaları (`behavioral_rubric`, `policy_invariants`) için yalnız inceleme paketi
çıkarılır; onların puanı sözleşmedeki rubrikle ayrıca verilir.

Rubrik (CONTRACT_V2_1 §5, sayısal vakalar):
  25 niyet/dönem  → referans anahtar kümesinin kapsanması (fazla ve eksik satır cezalı)
  35 değer        → referans sayısal kolonlarının, en iyi eşleşen çıktı kolonunda bulunan değer oranı
  20 tamlık       → referans kolonlarının kaçı ≥%90 eşleşti ve null sayısı tuttu
  10 projection   → satır sayısı ve fazla analiz kolonu olmaması
  10 anlatım      → cevap metni boş/başarısızlık bildirimi değil

Değer eşleşmesi satır hizalamasına bağlı değildir: referans kolondaki değerlerin çıktı kolonunda
(göreli 1e-4 ya da mutlak 0,005 toleransla) bulunma oranıdır. Kolon adları serbesttir (sözleşme §4).

Kullanım (agent-core dizininden):
    uv run python scripts/m02_benchmark/score_v2.py RUN.jsonl [RUN2.jsonl ...] [--manual SCORE.md] [--json OUT.json]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
ANSWERS = REPO_ROOT / "docs" / "benchmark" / "answers_v2_local.jsonl"
_FAIL_TEXT = re.compile(r"doğrulayamadım|dogrulayamadim|tamamlanamadı|başarısız oldu|hesaplanamadı|üretilemedi|veremiyorum", re.I)
_DATE_NAME = re.compile(r"period|date|donem|dönem|tarih|quarter|month|ay\b|observation", re.I)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _num(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    text = series.astype(str).str.strip()
    # Türkçe biçim (1.234,5) ve düz biçim (1234.5) ikisi de
    tr = text.str.contains(r"^\-?\d{1,3}(?:\.\d{3})+(?:,\d+)?$|^\-?\d+,\d+$", regex=True)
    text = text.where(~tr, text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(text, errors="coerce")


def _numeric_columns(frame: pd.DataFrame) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for col in frame.columns:
        if _DATE_NAME.search(str(col)) and not pd.api.types.is_numeric_dtype(frame[col]):
            continue
        values = _num(frame[col])
        if values.notna().sum() >= max(1, int(0.5 * frame[col].notna().sum())) and frame[col].notna().any():
            out[str(col)] = values
    return out


def _date_keys(frame: pd.DataFrame) -> set[str] | None:
    for col in frame.columns:
        raw = frame[col].dropna().astype(str)
        if raw.empty:
            continue
        if not (_DATE_NAME.search(str(col)) or raw.str.match(r"^\d{4}-\d{2}").mean() > 0.8):
            continue
        parsed = pd.to_datetime(raw, errors="coerce")
        if parsed.notna().mean() > 0.8:
            return {d.strftime("%Y-%m") for d in parsed.dropna()}
    return None


def _match_fraction(ref: pd.Series, out: pd.Series) -> float:
    ref_vals = ref.dropna().to_numpy()
    out_vals = out.dropna().to_numpy()
    if len(ref_vals) == 0:
        return 1.0 if len(out_vals) == 0 else 0.0
    if len(out_vals) == 0:
        return 0.0
    out_sorted = sorted(out_vals)
    import bisect
    hits = 0
    for v in ref_vals:
        tol = max(abs(v) * 1e-4, 0.005)
        i = bisect.bisect_left(out_sorted, v - tol)
        if i < len(out_sorted) and out_sorted[i] <= v + tol:
            hits += 1
    return hits / len(ref_vals)


# Yapısı genel karşılaştırmaya uymayan vakalar elle (rubrikle) puanlanır:
# P03 esnek pencere, D05 kırılma kayıtları, R02 aday listesi.
MANUAL_NUMERIC = {"P03", "D05", "R02"}
# "table": kullanıcının gördüğü projeksiyon (ADR-0105 sonrası koşular); "workspace_table": ham çalışma tablosu.
TABLE_KEY = "table"


def _scaled_fraction(ref: pd.Series, out: pd.Series) -> float:
    """Endeks bazı farklıysa (TÜFE 2003=100 ↔ 2025=100) değerler sabit oranla eşleşir; oran medyanla bulunur."""
    r = ref.dropna(); o = out.dropna()
    if len(r) < 3 or len(o) < 3 or (r == 0).any():
        return 0.0
    n = min(len(r), len(o))
    k = statistics.median((o.to_numpy()[:n]) / (r.to_numpy()[:n]))
    if not math.isfinite(k) or k == 0:
        return 0.0
    return _match_fraction(r * k, o)


def _aligned(ref: pd.DataFrame, out: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Tarih anahtarıyla satır hizalaması (null kaybını görmek için)."""
    def key(frame: pd.DataFrame) -> pd.Series | None:
        for col in frame.columns:
            raw = frame[col].astype(str)
            if _DATE_NAME.search(str(col)) or raw.str.match(r"^\d{4}-\d{2}").mean() > 0.8:
                parsed = pd.to_datetime(frame[col], errors="coerce")
                if parsed.notna().mean() > 0.8:
                    return parsed.dt.strftime("%Y-%m")
        return None
    rk, ok = key(ref), key(out)
    if rk is None or ok is None:
        return None
    return ref.assign(_k=rk.values).drop_duplicates("_k").set_index("_k"), out.assign(_k=ok.values).drop_duplicates("_k").set_index("_k")


def score_numeric(case: dict[str, Any], record: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    ref_path = REPO_ROOT / case["artifact"]["path"]
    ref = pd.read_csv(ref_path)
    table = record.get(TABLE_KEY) or record.get("table") or {}
    csv_path = table.get("csv_path")
    answer = " ".join((t.get("answer") or "") for t in record.get("turns") or [])
    last_answer = ((record.get("turns") or [{}])[-1].get("answer") or "")
    result: dict[str, Any] = {"id": case["id"], "mode": "numeric", "notes": []}
    if not csv_path:
        result.update(score=0, parts={"period": 0, "values": 0, "complete": 0, "projection": 0, "narrative": 0})
        result["notes"].append("tablo yok")
        return result
    path = Path(csv_path)
    if not path.is_absolute():
        path = (REPO_ROOT / "agent-core" / path).resolve()
    if not path.exists():
        alt = run_dir / path.name
        path = alt if alt.exists() else path
    out = pd.read_csv(path)

    ref_num = {c: s for c, s in _numeric_columns(ref).items() if c not in {"observations", "n", "index"} or len(ref.columns) <= 3}
    out_num = _numeric_columns(out)
    mapping: dict[str, tuple[str | None, float]] = {}
    used: set[str] = set()
    for rc, rs in sorted(ref_num.items(), key=lambda kv: -kv[1].notna().sum()):
        best, best_f, scaled = None, 0.0, False
        for oc, os_ in out_num.items():
            if oc in used:
                continue
            f = _match_fraction(rs, os_)
            if f > best_f:
                best, best_f, scaled = oc, f, False
        if best_f < 0.9 and re.search(r"cpi|tufe|tüfe|endeks|index", rc, re.I):
            for oc, os_ in out_num.items():
                if oc in used:
                    continue
                f = _scaled_fraction(rs, os_)
                if f > best_f:
                    best, best_f, scaled = oc, f, True
        if scaled and best_f >= 0.9:
            result["notes"].append(f"{rc}: endeks bazı farklı, orantılı eşleşti")
        mapping[rc] = (best, best_f)
        if best:
            used.add(best)

    value_fracs = [f for _, f in mapping.values()] or [0.0]
    values = 35 * statistics.fmean(value_fracs)

    ref_keys, out_keys = _date_keys(ref), _date_keys(out)
    if ref_keys and out_keys is not None:
        inter = len(ref_keys & out_keys)
        recall = inter / len(ref_keys)
        precision = inter / len(out_keys) if out_keys else 0.0
        # dönem sınırı niyetin parçası: tek ay kayması da kısmi sayılır (sözleşme §5, P06 elle 55)
        period = 25.0 if ref_keys == out_keys else max(0.0, 25 * recall * precision - 12)
        if recall < 1:
            result["notes"].append(f"eksik dönem {len(ref_keys - out_keys)}")
        if precision < 1:
            result["notes"].append(f"fazla dönem {len(out_keys - ref_keys)}")
    else:
        period = 25 * min(len(ref), len(out)) / max(len(ref), len(out), 1)

    good_cols = 0.0
    lost_cells = 0
    aligned = _aligned(ref, out)
    for rc, (oc, f) in mapping.items():
        if oc is None or f < 0.9:
            result["notes"].append(f"kolon eşleşmedi: {rc} ({f:.0%})")
            continue
        lost = 0
        if aligned is not None:
            ra, oa = aligned
            common = ra.index.intersection(oa.index)
            lost = int((ra.loc[common, rc].notna() & _num(oa.loc[common, oc]).isna()).sum())
        lost_cells += lost
        if f >= 0.999 and lost == 0:
            good_cols += 1
        else:
            good_cols += 0.5
            if lost:
                result["notes"].append(f"{rc}: referansta dolu {lost} hücre çıktıda boş")
    complete = 20 * (good_cols / max(len(mapping), 1))

    extra = [c for c in out_num if c not in used and not re.search(r"quality|flag|observations|missing|series_id|sha|run_id|vintage", c, re.I)]
    projection = 10.0
    if len(out) != len(ref):
        projection -= 5
    if extra:
        projection -= 5
        result["notes"].append(f"fazla kolon: {', '.join(extra[:4])}")
    projection = max(projection, 0)

    narrative = 10.0 if last_answer.strip() and not _FAIL_TEXT.search(last_answer) else (5.0 if last_answer.strip() else 0.0)
    total = period + values + complete + projection + narrative
    if statistics.fmean(value_fracs) < 0.5:
        total = min(total, 49)
        result["notes"].append("değerlerin çoğu eşleşmedi (en çok başarısız)")
    elif any(f < 0.5 for _, f in mapping.values()):
        total = min(total, 49)
        result["notes"].append("istenen kolonlardan biri yok (en çok başarısız)")
    elif lost_cells:
        total = min(total, 84)
        result["notes"].append("veri kaybı: dolu olması gereken hücre boş (en çok kısmi)")
    result.update(score=round(total), parts={"period": round(period, 1), "values": round(values, 1), "complete": round(complete, 1),
                                           "projection": round(projection, 1), "narrative": round(narrative, 1)})
    _ = answer
    return result


def _status(score: float) -> str:
    return "PASS" if score >= 85 else "PARTIAL" if score >= 50 else "FAIL"


def _manual_scores(path: Path) -> dict[str, int]:
    scores = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*([A-Z]\d{2})\s*\|[^|]*\|\s*(\d+)\s*\|", line)
        if m:
            scores[m.group(1)] = int(m.group(2))
    return scores


def _table_preview(record: dict[str, Any], run_dir: Path, limit: int = 8) -> str:
    table = record.get("table") or {}
    csv_path = table.get("csv_path")
    if not csv_path:
        return "(tablo yok)"
    path = Path(csv_path)
    if not path.is_absolute():
        path = (REPO_ROOT / "agent-core" / path).resolve()
    if not path.exists():
        path = run_dir / path.name
    try:
        frame = pd.read_csv(path)
    except Exception as exc:  # noqa: BLE001
        return f"(tablo okunamadı: {exc})"
    head = frame.head(limit).to_csv(index=False)
    tail = frame.tail(2).to_csv(index=False, header=False) if len(frame) > limit else ""
    return f"{len(frame)} satır × {len(frame.columns)} kolon\n{head}{'...\n' + tail if tail else ''}"


def write_review_packets(runs: list[Path], out_dir: Path, ids: set[str]) -> int:
    """Rubrikle puanlanacak vakalar için tekrar başına adım, cevap ve tablo özetini tek dosyada toplar."""
    cases = {c["id"]: c for c in _read_jsonl(ANSWERS)}
    records: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)
    for run in runs:
        for rec in _read_jsonl(run):
            if rec["id"] in ids:
                records[rec["id"]].append((run, rec))
    out_dir.mkdir(parents=True, exist_ok=True)
    for cid, items in sorted(records.items()):
        case = cases[cid]
        contract = case["evaluation_contract"]
        lines = [f"# {cid} — {case['title']}", "", f"Oracle: {contract.get('oracle')} · mod: {case['answer_mode']}", "",
                 "## Beklenen davranış", contract.get("expected_behavior", ""), "", "## Kabul ölçütleri",
                 *[f"- {x}" for x in contract.get("acceptance_criteria", [])], "", "## Kritik hatalar",
                 *[f"- {x}" for x in contract.get("critical_failures", [])], "", "## Referans cevap", case["reference_answer"], ""]
        for n, (run, rec) in enumerate(items, 1):
            lines += [f"## Tekrar {n} (süre {rec.get('elapsed_s')} s)"]
            for turn in rec.get("turns") or []:
                steps = " > ".join((s.get("tool") or s.get("role") or "?") + ("" if s.get("ok") else f"✗{s.get('error_code') or ''}")
                                   for s in turn.get("steps") or [])
                lines += [f"### Tur {turn.get('turn')}", f"Soru: {turn.get('question')}", f"Adımlar: {steps}",
                          "Cevap:", (turn.get("answer") or "(boş)")[:2500], ""]
            lines += ["Son tablo:", "```", _table_preview(rec, run.parent), "```", ""]
        (out_dir / f"{cid}.md").write_text("\n".join(lines), encoding="utf-8")
    return len(records)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--manual", type=Path, help="elle puanlanmış rapor (kalibrasyon için)")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--review-dir", type=Path, help="rubrikle puanlanacak vakaların inceleme dosyaları buraya yazılır")
    ap.add_argument("--table-key", default="table", choices=["table", "workspace_table"],
                    help="hangi tablo puanlanır: kullanıcı projeksiyonu (varsayılan) ya da ham çalışma tablosu")
    args = ap.parse_args(argv)
    global TABLE_KEY
    TABLE_KEY = args.table_key
    cases = {c["id"]: c for c in _read_jsonl(ANSWERS)}
    manual = _manual_scores(args.manual) if args.manual else {}
    per_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    review: list[dict[str, Any]] = []
    for run in args.runs:
        for rec in _read_jsonl(run):
            case = cases.get(rec["id"])
            if not case:
                continue
            if case["evaluation_contract"].get("oracle") == "csv_numeric_reference" and rec["id"] not in MANUAL_NUMERIC:
                per_case[rec["id"]].append(score_numeric(case, rec, run.parent))
            else:
                review.append({"id": rec["id"], "run": run.name, "repetition": rec.get("repetition")})
    print(f"{'vaka':5} {'puanlar':22} {'ort':>5}  {'elle':>5}  notlar")
    agree = 0
    for cid in sorted(per_case):
        res = per_case[cid]
        scores = [r["score"] for r in res]
        mean = statistics.fmean(scores)
        man = manual.get(cid)
        if man is not None and _status(man) == _status(mean):
            agree += 1
        notes = "; ".join(dict.fromkeys(n for r in res for n in r["notes"]))[:110]
        print(f"{cid:5} {str(scores):22} {mean:5.1f}  {'' if man is None else man:>5}  {notes}")
    allscores = [statistics.fmean([r["score"] for r in v]) for v in per_case.values()]
    if allscores:
        print(f"\nsayısal vaka: {len(allscores)} · ortalama {statistics.fmean(allscores):.1f} · "
              f"PASS {sum(s >= 85 for s in allscores)} · PARTIAL {sum(50 <= s < 85 for s in allscores)} · FAIL {sum(s < 50 for s in allscores)}")
    if manual:
        both = [c for c in per_case if c in manual]
        print(f"elle puanla aynı sınıf (PASS/PARTIAL/FAIL): {agree}/{len(both)}")
    if args.review_dir:
        manual_ids = {c["id"] for c in cases.values()
                      if c["evaluation_contract"].get("oracle") != "csv_numeric_reference" or c["id"] in MANUAL_NUMERIC}
        n = write_review_packets(args.runs, args.review_dir, manual_ids)
        print(f"inceleme dosyası: {n} vaka → {args.review_dir}")
    if args.json:
        args.json.write_text(json.dumps({"numeric": per_case, "review": review}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
