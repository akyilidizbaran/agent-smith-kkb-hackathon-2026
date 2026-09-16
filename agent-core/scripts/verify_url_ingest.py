"""Run the Architect ingestion tool against a live URL and inspect an isolated DB.

The model is not called. Resource/table selectors are explicit command-line arguments.
Original page, attachment, extracted CSV and source manifest are kept beside the test DB.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kkb_agent.adapters.lakehouse_cli import subprocess_env
from kkb_agent.builder.ingest import LakehouseCLI
from kkb_agent.tools.ingest import IngestFromUrlTool


class Reader:
    def __init__(self, database: Path):
        self.db_path = database
        self.connection = None
        self.reload()

    def reload(self):
        self.close()
        if self.db_path.exists():
            self.connection = duckdb.connect(str(self.db_path), read_only=True)

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def list_datasets(self):
        if self.connection is None:
            return []
        rows = self.connection.execute("SELECT series_id, source_id FROM meta.series").fetchall()
        return [SimpleNamespace(dataset_id=series, source=source) for series, source in rows]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--resource-index", type=int)
    parser.add_argument("--table-index", type=int)
    parser.add_argument("--value-row")
    parser.add_argument("--pages")
    parser.add_argument("--series-key", default="url_acceptance")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    core = repo / "lakehouse-core"
    python = core / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    root = args.output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    db = root / "test.duckdb"
    calls = []

    def runner(command, cwd):
        # Explicit executable list: works even when the workspace path contains spaces.
        command = [str(python), "-B", "-X", "utf8", *command[3:]]
        env = subprocess_env()
        env["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, check=False,
                                   text=True, encoding="utf-8", timeout=180)
        calls.append({"returncode": completed.returncode,
                      "stdout": completed.stdout, "stderr": completed.stderr})
        return completed.returncode, completed.stdout, completed.stderr

    reader = Reader(db)
    question = f"{args.url} adresindeki {args.value_row or 'veriyi'} taslak seri olarak kaydet."
    registry = SimpleNamespace(user_text=question, active_question=question, turn=1)
    tool = IngestFromUrlTool(reader, LakehouseCLI(core_dir=core, database=db, data_root=root / "data", runner=runner),
                            allowed_root=root / "incoming", registry=registry)
    report = {"url": args.url, "database": str(db),
              "checked_at": datetime.now(UTC).isoformat()}
    try:
        result = tool.validate_and_run({"locator": args.url, "name": args.value_row or "URL verisi",
            "resource_index": args.resource_index, "table_index": args.table_index,
            "value_row": args.value_row, "pages": args.pages, "series_key": args.series_key})
        report.update({"tool_ok": result.ok, "content": result.content, "writer_calls": calls})
        print(result.content, flush=True)
    finally:
        reader.close()
    if db.exists():
        with duckdb.connect(str(db), read_only=True) as con:
            def query(sql):
                cursor = con.execute(sql, [f"adhoc:{args.series_key}"])
                columns = [d[0] for d in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
            report["catalog"] = query("SELECT series_id, status, unit, frequency, measure_type FROM meta.series WHERE series_id=?")
            report["observations"] = query("SELECT series_id, observation_date, entity_id, value, unit, run_id, artifact_sha256 FROM adhoc.fact_observation WHERE series_id=? ORDER BY entity_id")
    (root / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: report.get(k) for k in ("catalog", "observations")}, ensure_ascii=False, indent=2, default=str))
    return 0 if report.get("observations") and report["content"].startswith("EKLENDİ:") else 1


if __name__ == "__main__":
    raise SystemExit(main())
