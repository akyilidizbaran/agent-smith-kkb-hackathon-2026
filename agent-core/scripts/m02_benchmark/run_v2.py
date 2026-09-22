"""V2 yerel benchmark koşucusu.

Kullanım (agent-core dizininden):
    uv run python scripts/m02_benchmark/run_v2.py --dry-run
    uv run python scripts/m02_benchmark/run_v2.py --ids P01,R01,T01 --out ../docs/experiments/v2-smoke.jsonl

Varsayılan olarak yalnız `external_mode=none` ve `surface=agent_cli` vakalarını
çalıştırır. UI, performans tekrarı, concurrency ve fault-injection vakaları ayrı
test yüzeylerinde ölçülür. Sonuçlar otomatik başarılı sayılmaz; bağımsız oracle ile
değerlendirme gerekir.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CORE_ROOT = REPO_ROOT / "agent-core"
sys.path.insert(0, str(CORE_ROOT / "src"))


@dataclass(frozen=True)
class BenchmarkCase:
    id: str
    family: str
    title: str
    turns: tuple[str, ...]
    prompt: str
    reference: dict[str, Any]
    surface: str = "agent_cli"
    contract: dict[str, Any] = field(default_factory=dict)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: geçersiz JSONL: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise TypeError(f"{path}:{line_number}: kayıt JSON object olmalı")
        records.append(record)
    return records


def load_cases(
    prompts_path: Path,
    answers_path: Path,
    *,
    ids: set[str] | None = None,
    families: set[str] | None = None,
    include_external: bool = False,
    surfaces: set[str] | None = None,
) -> list[BenchmarkCase]:
    """Manifest/cevap anahtarını doğrula ve istenen vakaları seç.

    Varsayılan olarak yalnız harici girdiye ihtiyaç duymayan ve agent CLI ile
    gerçekten yürütülebilen V2 vakaları döner. UI, concurrency, perf ve fault
    injection testleri yanlışlıkla model kalitesi koşusu gibi çalıştırılmaz.
    """
    prompts = _read_jsonl(prompts_path)
    answers = _read_jsonl(answers_path)
    prompt_by_id: dict[str, dict[str, Any]] = {}
    answer_by_id: dict[str, dict[str, Any]] = {}
    for record, target, label in (
        *((row, prompt_by_id, "prompt") for row in prompts),
        *((row, answer_by_id, "cevap") for row in answers),
    ):
        case_id = str(record.get("id", "")).strip()
        if not case_id:
            raise ValueError(f"{label} kaydında id eksik")
        if case_id in target:
            raise ValueError(f"{label} manifestinde yinelenen id: {case_id}")
        target[case_id] = record

    missing_references = sorted(
        case_id
        for case_id, prompt in prompt_by_id.items()
        if prompt.get("external_mode") == "none" and case_id not in answer_by_id
    )
    if missing_references:
        raise ValueError("Yerel vaka cevap anahtarı eksik: " + ", ".join(missing_references))

    chosen: list[BenchmarkCase] = []
    unknown_ids = (ids or set()) - prompt_by_id.keys()
    if unknown_ids:
        raise ValueError("Manifestte bulunmayan vaka ID'si: " + ", ".join(sorted(unknown_ids)))
    allowed_surfaces = surfaces if surfaces is not None else {"agent_cli"}
    unsupported_ids = sorted(
        case_id
        for case_id in (ids or set())
        if str((prompt_by_id[case_id].get("contract_v2_1") or {}).get("surface", "agent_cli"))
        not in allowed_surfaces
    )
    if unsupported_ids:
        raise ValueError(
            "Agent CLI ile yürütülemeyen vaka yüzeyleri: "
            + ", ".join(unsupported_ids)
            + ". CONTRACT_V2_1.md prosedürünü kullanın."
        )

    for row in prompts:
        case_id = str(row["id"])
        external_mode = row.get("external_mode", "none")
        if not include_external and external_mode != "none":
            continue
        contract = row.get("contract_v2_1") or {}
        surface = str(contract.get("surface", "agent_cli"))
        if surface not in allowed_surfaces:
            continue
        if ids is not None and case_id not in ids:
            continue
        family = str(row.get("family", ""))
        if families is not None and family not in families:
            continue
        turns = row.get("turns") or [row.get("prompt", "")]
        if not isinstance(turns, list) or not turns or not all(isinstance(turn, str) and turn.strip() for turn in turns):
            raise ValueError(f"{case_id}: turns boş olmayan metin listesi olmalı")
        placeholders = row.get("placeholders") or []
        if external_mode == "none" and placeholders:
            raise ValueError(f"{case_id}: external_mode=none iken placeholder tanımlı")
        chosen.append(
            BenchmarkCase(
                id=case_id,
                family=family,
                title=str(row.get("title", "")),
                turns=tuple(turns),
                prompt=str(row.get("prompt", turns[0])),
                reference=answer_by_id.get(case_id, {}),
                surface=surface,
                contract=contract,
            )
        )
    return chosen


def _clean_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(sk-[a-z0-9_-]{12,})", "[REDACTED]", text)
    return text[:limit]


def _step_record(step: Any) -> dict[str, Any]:
    args = getattr(step, "tool_args", {}) or {}
    clean_args: dict[str, Any] = {}
    for key, value in args.items():
        if isinstance(value, str):
            clean_args[str(key)] = _clean_text(value, 500)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            clean_args[str(key)] = value
        else:
            clean_args[str(key)] = _clean_text(value, 300)
    return {
        "index": getattr(step, "index", None),
        "role": getattr(step, "role", None),
        "tool": getattr(step, "tool_name", None),
        "ok": bool(getattr(step, "ok", True)),
        "error_code": getattr(step, "error_code", None),
        "duration_ms": round(float(getattr(step, "duration_ms", 0) or 0), 1),
        "llm_duration_ms": round(float(getattr(step, "llm_duration_ms", 0) or 0), 1),
        "tool_duration_ms": round(float(getattr(step, "tool_duration_ms", 0) or 0), 1),
        "args": clean_args,
        "result": _clean_text(getattr(step, "result_summary", ""), 500),
    }


def _table_record(frame: Any, artifact_dir: Path | None, case_id: str, repetition: int) -> dict[str, Any]:
    if frame is None:
        return {"rows": 0, "columns": [], "sha256": None, "csv_path": None}
    columns = [str(column) for column in getattr(frame, "columns", [])]
    rows = len(frame)
    if artifact_dir is None:
        return {"rows": rows, "columns": columns, "sha256": None, "csv_path": None}
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"{case_id.lower()}-run-{repetition}.csv"
    csv_bytes = frame.to_csv(index=False, lineterminator="\n").encode("utf-8")
    path.write_bytes(csv_bytes)
    return {
        "rows": rows,
        "columns": columns,
        "sha256": hashlib.sha256(csv_bytes).hexdigest(),
        "csv_path": str(path),
    }


def execute_case(
    case: BenchmarkCase,
    build_agent: Callable[[], Any],
    *,
    repetition: int = 1,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Bir vaka ve tüm takip turlarını aynı agent/workspace üzerinde yürüt."""
    init_started = time.perf_counter()
    try:
        agent = build_agent()
    except Exception as exc:  # noqa: BLE001 - bir kurulum hatası tüm benchmark'ı durdurmasın
        return {
            "id": case.id,
            "family": case.family,
            "title": case.title,
            "repetition": repetition,
            "status": "setup_error",
            "setup_ms": round((time.perf_counter() - init_started) * 1000, 1),
            "turns": [],
            "table": {"rows": 0, "columns": [], "sha256": None, "csv_path": None},
            "failure": {"type": type(exc).__name__, "message": _clean_text(exc, 300)},
        }
    setup_ms = round((time.perf_counter() - init_started) * 1000, 1)

    turn_results: list[dict[str, Any]] = []
    steps: list[Any] = []
    started = time.perf_counter()
    failure: dict[str, str] | None = None
    for turn_index, question in enumerate(case.turns, 1):
        turn_started = time.perf_counter()
        try:
            answer = agent.ask(question)
            turn_steps = list(getattr(answer, "steps", []) or [])
            steps.extend(turn_steps)
            usage = dict(getattr(answer, "usage", {}) or {})
            turn_results.append(
                {
                    "turn": turn_index,
                    "question": question,
                    "duration_s": round(time.perf_counter() - turn_started, 2),
                    "answer": _clean_text(getattr(answer, "text", ""), 5000),
                    "usage": usage,
                    "grounding": getattr(answer, "grounding", ""),
                    "availability_status": getattr(answer, "availability_status", "UNKNOWN"),
                    "steps": [_step_record(step) for step in turn_steps],
                }
            )
        except Exception as exc:  # noqa: BLE001 - bir vaka hatası diğer vakalara engel olmasın
            failure = {"type": type(exc).__name__, "message": _clean_text(exc, 300)}
            turn_results.append(
                {
                    "turn": turn_index,
                    "question": question,
                    "duration_s": round(time.perf_counter() - turn_started, 2),
                    "exception": failure,
                }
            )
            break

    elapsed_s = round(time.perf_counter() - started, 2)
    workspace = getattr(agent, "workspace", None)
    frame = getattr(workspace, "table", None) if workspace is not None else None
    if frame is not None and getattr(frame, "empty", False):
        frame = None
    table = _table_record(frame, artifact_dir, case.id, repetition)
    llm_failed = any(
        int((turn.get("usage") or {}).get("failed_llm_calls", 0) or 0) > 0
        for turn in turn_results
    ) or any(getattr(step, "error_code", None) == "LLM_UNAVAILABLE" for step in steps)
    status = (
        "execution_error"
        if failure
        else "recovered_with_llm_failure"
        if llm_failed
        else "executed_needs_review"
    )
    return {
        "id": case.id,
        "family": case.family,
        "title": case.title,
        "surface": case.surface,
        "contract": case.contract,
        "repetition": repetition,
        "status": status,
        "setup_ms": setup_ms,
        "elapsed_s": elapsed_s,
        "turn_count": len(turn_results),
        "llm_failure_recovered": llm_failed,
        "turns": turn_results,
        "steps": [_step_record(step) for step in steps],
        "table": table,
        "reference": {
            "answer_mode": case.reference.get("answer_mode"),
            "reference_answer": case.reference.get("reference_answer"),
            "artifact": case.reference.get("artifact"),
            "source_series": case.reference.get("source_series", []),
            "evaluation_contract": case.reference.get("evaluation_contract"),
        },
        "failure": failure,
    }


def _default_paths() -> tuple[Path, Path]:
    prompts = REPO_ROOT / "tests/benchmark/prompts_v2.jsonl"
    answers = REPO_ROOT / "docs/benchmark/answers_v2_local.jsonl"
    return prompts, answers


def main(argv: list[str] | None = None) -> int:
    prompts_default, answers_default = _default_paths()
    parser = argparse.ArgumentParser(description="V2 yerel benchmark koşucusu")
    parser.add_argument("--prompts", type=Path, default=prompts_default)
    parser.add_argument("--answers", type=Path, default=answers_default)
    parser.add_argument("--ids", help="Virgülle ayrılmış vaka kimlikleri")
    parser.add_argument("--families", help="Virgülle ayrılmış aile harfleri")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--out", type=Path, help="JSONL sonuç dosyası; belirtilmezse deney dizininde yeni dosya")
    parser.add_argument("--dry-run", action="store_true", help="Seçilen vakaları göster, model çağırma")
    parser.add_argument("--no-csv-artifacts", action="store_true")
    parser.add_argument(
        "--surfaces",
        help="Yalnız agent_cli yüzeyi yürütülebilir; UI/perf/fault testleri ayrı harness gerektirir.",
    )
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat en az 1 olmalı")

    requested_surfaces = (
        {part.strip() for part in args.surfaces.split(",") if part.strip()}
        if args.surfaces
        else None
    )
    if requested_surfaces and requested_surfaces != {"agent_cli"}:
        parser.error(
            "Bu koşucu yalnız agent_cli testlerini yürütür. Diğer yüzeyler CONTRACT_V2_1.md'deki "
            "UI/performance/concurrency/fault-injection prosedürleriyle çalıştırılmalıdır."
        )

    try:
        selected = load_cases(
            args.prompts,
            args.answers,
            ids={part.strip() for part in args.ids.split(",") if part.strip()} if args.ids else None,
            families={part.strip().upper() for part in args.families.split(",") if part.strip()} if args.families else None,
            surfaces=requested_surfaces,
        )
    except ValueError as exc:
        parser.error(str(exc))
    if not selected:
        parser.error("Filtrelerle eşleşen yerel vaka bulunamadı")
    if args.dry_run:
        for case in selected:
            print(f"{case.id}\t{case.family}\t{case.surface}\t{case.title}\t{len(case.turns)} tur")
        print(f"Toplam: {len(selected)} agent_cli vakası; entegrasyon ve harici vakalar atlandı.")
        return 0

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out_path = args.out or (REPO_ROOT / "docs/experiments" / f"v2_local_{timestamp}.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_dir = None if args.no_csv_artifacts else out_path.with_suffix("").with_name(out_path.stem + "_tables")

    from kkb_agent.cli import build_agent

    durations: list[float] = []
    completed = 0
    status_counts: Counter[str] = Counter()
    with out_path.open("a", encoding="utf-8") as output:
        for case_index, case in enumerate(selected, 1):
            for repetition in range(1, args.repeat + 1):
                print(f"[{case_index}/{len(selected)}] {case.id} tekrar {repetition}/{args.repeat} …", flush=True)
                row = execute_case(
                    case,
                    lambda: build_agent(max_steps=args.max_steps),
                    repetition=repetition,
                    artifact_dir=artifact_dir,
                )
                output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                output.flush()
                completed += 1
                status_counts[row["status"]] += 1
                if row.get("elapsed_s") is not None:
                    durations.append(float(row["elapsed_s"]))
                print(
                    f"  {row['status']} · {row.get('elapsed_s', 0):.2f}s · "
                    f"{row.get('table', {}).get('rows', 0)} satır",
                    flush=True,
                )

    p50 = statistics.median(durations) if durations else 0.0
    p95 = sorted(durations)[max(0, math.ceil(0.95 * len(durations)) - 1)] if durations else 0.0
    print(
        f"Bitti: {completed} koşu · p50 {p50:.2f}s · p95 {p95:.2f}s · "
        f"durumlar {dict(status_counts)} · {out_path}"
    )
    if artifact_dir:
        print(f"Tablo CSV çıktıları: {artifact_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
