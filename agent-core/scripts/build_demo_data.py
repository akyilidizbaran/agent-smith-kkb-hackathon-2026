"""Demo verisini kalıcı DATA_ROOT'a kurar — veri DEĞİŞTİREN tek komut (M01, ADR-0049).

Ön kontrolden (`--preflight`) ayrı: bu betik indirir ve yazar. Adımlar veri ekibinin CLI'ıdır:
bootstrap → canlı ingest (yalnız demo serileri, `--only`) → silver → gold; ardından jüri dosya
fikstürleri izinli köke kopyalanır. Mevcut DB'yi ancak `--fresh --yes` ile siler; silinecekleri
önce listeler.

    uv run python scripts/build_demo_data.py            # DATA_ROOT (varsayılan repo/data)
    uv run python scripts/build_demo_data.py --fresh --yes
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from kkb_agent.config import load_settings  # noqa: E402
from scripts.demo_acceptance import DEMO_SERIES, _run, _stage_incoming, build_commands  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", default=",".join(DEMO_SERIES), help="virgülle seri kimlikleri (varsayılan demo seti)")
    ap.add_argument("--fresh", action="store_true", help="mevcut DB ve RAW/Bronze'u sil, sıfırdan kur (--yes ister)")
    ap.add_argument("--yes", action="store_true", help="--fresh için onay")
    ap.add_argument("--skip-ingest", action="store_true", help="bootstrap/ingest/silver/gold'u atla; yalnız fikstürleri kopyala")
    args = ap.parse_args()

    s = load_settings()
    db, data, core = s.lakehouse_path, s.data_root, s.lakehouse_core_dir
    print(f"DEMO VERİSİ — DB {db} · veri kökü {data} · lakehouse-core {core}")
    if not (core / "src" / "lakehouse" / "cli.py").is_file():
        print(f"✗ lakehouse-core bulunamadı: {core} (LAKEHOUSE_CORE_DIR)")
        return 2
    if args.fresh:
        targets = [p for p in (db, db.with_suffix(".duckdb.wal"), data / "raw", data / "bronze", data / "silver", data / "quarantine") if p.exists()]
        if targets:
            print("SİLİNECEK:"); [print(f"  - {t}") for t in targets]
            if not args.yes:
                print("✗ --fresh için --yes gerekli; hiçbir şey silinmedi."); return 2
            for t in targets:
                shutil.rmtree(t) if t.is_dir() else t.unlink()
            print("  silindi.")
    data.mkdir(parents=True, exist_ok=True)
    if not args.skip_ingest:
        code, help_text = _run([*s.lakehouse_cli.split(), "scripts/run_catalog_ingestion.py", "--help"], core, timeout=120)
        if code != 0 or "--only" not in help_text:
            print("✗ run_catalog_ingestion.py '--only' tanımıyor; filtresiz canlı ingest ÇALIŞTIRILMAZ."); return 2
        only = tuple(x.strip() for x in args.only.split(",") if x.strip())
        for name, cmd in build_commands(data.parent, core, launcher=s.lakehouse_cli, db=db, data=data, only=only):
            t = time.perf_counter(); code, out = _run(cmd, core); secs = time.perf_counter() - t
            tail = "\n".join(out.strip().splitlines()[-4:])
            print(f"{'✓' if code == 0 else '✗'} {name} ({secs:.0f} s)"); [print(f"    {l}") for l in tail.splitlines()]
            if code != 0:
                return 1
    incoming = _stage_incoming(data)          # data/incoming: jüri dosyası + fikstürler
    if incoming != s.ingest_allowed_root:
        print(f"! fikstürler {incoming} altına kondu; INGEST_ALLOWED_ROOT={s.ingest_allowed_root} farklı")
    print(f"✓ izinli dosya kökü: {incoming}")
    print("Sonraki adım: uv run python -m kkb_agent.cli --preflight")
    return 0


if __name__ == "__main__":
    sys.exit(main())
