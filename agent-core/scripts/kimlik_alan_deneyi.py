"""Kimlik deneyi: yalnız veritabanı içeriği değişince "Sen kimsin?" cevabı değişiyor mu?

Kod, istem ve model aynı; her senaryoda yalnız DB farklı. Asıl demo DB'ye dokunulmaz (kopya ya da geçici kök).
Senaryolar:
  A_finans         demo DB kopyası (BDDK + EVDS kataloğu)
  B_bos            boş katalog (bootstrap --catalog none)
  C_saglik         boş katalog + kullanıcı serisi: aylık acil başvuru (sentetik fikstür)
  D_web            boş katalog + kullanıcı serisi: aylık web ziyareti (sentetik fikstür)
  E_finans_saglik  demo DB kopyası + aylık acil başvuru
Seri ekleme Architect araçlarıyla (ingest_from_url, promote_draft) modelsiz yapılır; sorular gerçek modele, her soru
yeni bir Analyst ajanına (sohbet geçmişi yok) sorulur.

    uv run python scripts/kimlik_alan_deneyi.py --work /tmp/kimlik [--tekrar 3]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
FIX = ROOT / "tests" / "fixtures" / "generic"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.k01_kabul import lakehouse, sha256  # noqa: E402

SERIES = {
    "acil": {"file": "acil_basvuru_aylik.csv", "key": "acil_basvuru", "name": "Acil servis başvuruları (aylık)",
             "message": "Dosya: {path}\nBu dosyayı taslak seri olarak ekle; birim kişi, ölçüm tipi flow_periodic, aylık kural sum.",
             "args": {"series_key": "acil_basvuru", "unit": "kişi", "measure_type": "flow_periodic", "default_agg": "sum"}},
    "web": {"file": "web_ziyaret_kirilma.csv", "key": "web_ziyaret", "name": "Günlük web ziyareti (aylık)",
            "message": "Dosya: {path}\nBu dosyayı taslak seri olarak ekle; birim ziyaret, ölçüm tipi count, aylık kural avg.",
            "args": {"series_key": "web_ziyaret", "unit": "ziyaret", "measure_type": "count", "default_agg": "avg"}},
}
SCENARIOS = [("A_finans", "demo", []), ("B_bos", "none", []), ("C_saglik", "none", ["acil"]), ("D_web", "none", ["web"]),
             ("E_finans_saglik", "demo", ["acil"])]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--tekrar", type=int, default=3, help="'Sen kimsin?' kaç kez sorulsun (model dalgalanması)")
    ap.add_argument("--senaryo", action="append", help="yalnız bu senaryo(lar)")
    args = ap.parse_args()
    questions = [("Sen kimsin?", args.tekrar), ("Neler yapabilirsin?", 1), ("Hangi veri setlerine sahipsin?", 1)]
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    demo_db = REPO / "data" / "lakehouse.duckdb"
    demo_before = sha256(demo_db)
    import kkb_agent.cli as cli_mod
    from kkb_agent.web_app import _close_agent_readers

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    report = {"meta": {"commit": commit, "at": datetime.now().isoformat(timespec="seconds"), "demo_db_sha256_once": demo_before},
              "senaryolar": []}

    for name, base, series in SCENARIOS:
        if args.senaryo and name not in args.senaryo:
            continue
        data = work / name / "data"
        (data / "incoming").mkdir(parents=True)
        db = data / "lakehouse.duckdb"
        os.environ.update({
            "DATA_ROOT": str(data), "LAKEHOUSE_PATH": str(db), "INGEST_ALLOWED_ROOT": str(data / "incoming"),
            "CHART_DIR": str(data / "charts"), "EMBEDDING_CACHE_DIR": str(data / "cache" / "embeddings"),
            "LAKEHOUSE_MODE": "demo", "VISION_MODEL": "",
        })
        if base == "demo":
            shutil.copy2(demo_db, db)
        else:
            boot = lakehouse("bootstrap", "--database", str(db), "--data-root", str(data), "--catalog", "none")
            if boot.returncode != 0:
                print(boot.stdout[-1500:], boot.stderr[-1500:])
                return 2
        setup = []
        if series:
            arch = cli_mod.build_agent(profile="architect")
            reg = arch.registry
            for key in series:
                spec = SERIES[key]
                path = data / "incoming" / spec["file"]
                shutil.copy2(FIX / spec["file"], path)
                for tool, message, tool_args in (
                    ("ingest_from_url", spec["message"].format(path=path), {"locator": str(path), "name": spec["name"], **spec["args"]}),
                    ("promote_draft", f"{spec['key']} taslağını onaylıyorum, kataloğa al.", {"series_id": f"adhoc:{spec['key']}", "purpose": "kullanıcı onayı"}),
                ):
                    reg.turn += 1
                    reg.current_message = reg.active_question = message
                    reg.user_text = (reg.user_text + "\n" + message).strip()
                    result = reg.execute(tool, tool_args)
                    setup.append({"arac": tool, "seri": spec["key"], "ok": result.ok, "ozet": result.content[:240]})
                    print(f"  [{name}] {tool} {spec['key']}: {'✓' if result.ok else '✗'} {result.content[:120]!r}", flush=True)
            _close_agent_readers(arch, db)
            del arch

        probe = cli_mod.build_agent(profile="analyst")
        specs = probe.registry.get("lakehouse_search").lakehouse.list_datasets()
        catalog = {}
        for s in specs:
            catalog[s.source] = catalog.get(s.source, 0) + 1
        domain = probe.profile.domain
        _close_agent_readers(probe, db)
        del probe
        print(f"[{name}] katalog={catalog} alan={domain!r}", flush=True)

        rows = []
        for question, reps in questions:
            for rep in range(1, reps + 1):
                agent = cli_mod.build_agent(profile="analyst")
                started = time.perf_counter()
                try:
                    answer = agent.ask(question)
                    text, tools = answer.text, [s.tool_name for s in answer.steps if s.tool_name]
                    llm = any(s.role != "narrate" or "LLM çağrılmadı" not in (s.thought or "") for s in answer.steps)
                except Exception as exc:  # noqa: BLE001 — deney raporu hatayı da kaydeder
                    text, tools, llm = f"HATA {type(exc).__name__}: {exc}", [], None
                rows.append({"soru": question, "tekrar": rep, "cevap": text, "araclar": tools, "llm": llm,
                             "sure_s": round(time.perf_counter() - started, 1)})
                print(f"  [{name}] {question} #{rep} ({rows[-1]['sure_s']} s, araç {tools}):\n    {text[:400]!r}", flush=True)
                _close_agent_readers(agent, db)
                del agent
        report["senaryolar"].append({"ad": name, "taban": base, "eklenen_seriler": series, "kurulum": setup,
                                     "katalog_kaynaklari": catalog, "alan_tanimi": domain, "cevaplar": rows})

    report["meta"]["demo_db_sha256_sonra"] = sha256(demo_db)
    report["meta"]["demo_db_degismedi"] = report["meta"]["demo_db_sha256_sonra"] == demo_before
    out = REPO / "docs" / "experiments" / f"kimlik_alan_deneyi_{datetime.now():%Y-%m-%d_%H%M}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nRAPOR: {out} · demo DB değişmedi: {report['meta']['demo_db_degismedi']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
