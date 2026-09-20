"""Validate frozen V2.1 prompt/oracle contracts and local reference artifacts.

Run from any directory:
    python3 agent-core/scripts/m02_benchmark/validate_contract_v2_1.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPTS_PATH = REPO_ROOT / "tests/benchmark/prompts_v2.jsonl"
ANSWERS_PATH = REPO_ROOT / "docs/benchmark/answers_v2_local.jsonl"
STATUSES_PATH = REPO_ROOT / "tests/benchmark/reference_status_v2.jsonl"
PROMPTS_MD_PATH = REPO_ROOT / "docs/benchmark/TEST_PROMPTLARI_V2.md"
ANSWER_KEY_MD_PATH = REPO_ROOT / "docs/benchmark/ANSWER_KEY_V2_LOCAL.md"
EXPECTATIONS_MD_PATH = REPO_ROOT / "docs/benchmark/reference/LOCAL_CASE_EXPECTATIONS.md"
CONTRACT_MD_PATH = REPO_ROOT / "docs/benchmark/CONTRACT_V2_1.md"
VALID_SURFACES = {
    "agent_cli",
    "performance_repeat",
    "concurrency",
    "fault_injection",
    "ui_e2e",
    "artifact_export_e2e",
    "external_fixture",
    "live_web",
}
NON_CLI_LOCAL = {"L06", "L07", "L08", "O03", "O06"}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise TypeError(f"{path}:{line_number}: JSON object bekleniyor")
        result.append(value)
    return result


def _unique_by_id(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = str(row.get("id", "")).strip()
        if not case_id:
            raise ValueError(f"{label}: id boş")
        if case_id in output:
            raise ValueError(f"{label}: yinelenen id {case_id}")
        output[case_id] = row
    return output


def validate() -> list[str]:
    prompts = _unique_by_id(_read_jsonl(PROMPTS_PATH), "prompt manifest")
    answers = _unique_by_id(_read_jsonl(ANSWERS_PATH), "answer manifest")
    statuses = _unique_by_id(_read_jsonl(STATUSES_PATH), "reference status")

    local_ids = {case_id for case_id, row in prompts.items() if row.get("external_mode") == "none"}
    if len(prompts) != 120:
        raise ValueError(f"120 prompt bekleniyordu, {len(prompts)} bulundu")
    if len(local_ids) != 76:
        raise ValueError(f"76 yerel vaka bekleniyordu, {len(local_ids)} bulundu")
    if set(answers) != local_ids:
        raise ValueError(
            f"Cevap anahtarı eşleşmiyor; eksik={sorted(local_ids-set(answers))}, "
            f"fazla={sorted(set(answers)-local_ids)}"
        )
    if set(statuses) != set(prompts):
        raise ValueError("reference_status_v2.jsonl tüm 120 prompt ID'sini birebir kapsamalı")
    for path in (PROMPTS_MD_PATH, ANSWER_KEY_MD_PATH, EXPECTATIONS_MD_PATH, CONTRACT_MD_PATH):
        if not path.is_file():
            raise ValueError(f"Gerekli sözleşme belgesi yok: {path.relative_to(REPO_ROOT)}")
    prompt_headings = re.findall(r"^### ([A-Z]\d{2}) — ", PROMPTS_MD_PATH.read_text(encoding="utf-8"), re.MULTILINE)
    if len(prompt_headings) != len(set(prompt_headings)) or set(prompt_headings) != set(prompts):
        raise ValueError("İnsan okunur prompt aynası 120 ID'yi manifestle birebir kapsamalı")
    answer_headings = re.findall(r"^## ([A-Z]\d{2}) — ", EXPECTATIONS_MD_PATH.read_text(encoding="utf-8"), re.MULTILINE)
    if len(answer_headings) != len(set(answer_headings)) or set(answer_headings) != local_ids:
        raise ValueError("Vaka beklenti aynası 76 yerel ID'yi manifestle birebir kapsamalı")
    answer_rows = re.findall(r"^\| \*\*([A-Z]\d{2})\*\* \|", ANSWER_KEY_MD_PATH.read_text(encoding="utf-8"), re.MULTILINE)
    if len(answer_rows) != len(set(answer_rows)) or set(answer_rows) != local_ids:
        raise ValueError("Okunabilir cevap anahtarı 76 yerel ID'yi manifestle birebir kapsamalı")

    surfaces: dict[str, int] = {}
    for case_id in sorted(local_ids):
        prompt = prompts[case_id]
        answer = answers[case_id]
        contract = prompt.get("contract_v2_1")
        evaluation = answer.get("evaluation_contract")
        if not isinstance(contract, dict) or contract.get("version") != "2.1":
            raise ValueError(f"{case_id}: contract_v2_1.version eksik veya hatalı")
        surface = contract.get("surface")
        if surface not in VALID_SURFACES:
            raise ValueError(f"{case_id}: bilinmeyen test surface {surface!r}")
        surfaces[str(surface)] = surfaces.get(str(surface), 0) + 1
        for key in ("workspace", "setup", "oracle", "objective"):
            if not contract.get(key):
                raise ValueError(f"{case_id}: contract_v2_1.{key} boş")
        turns = prompt.get("turns") or [prompt.get("prompt", "")]
        if not isinstance(turns, list) or not turns or any(not str(turn).strip() for turn in turns):
            raise ValueError(f"{case_id}: boş/bozuk turns")
        expected_workspace = "same_conversation" if len(turns) > 1 else "fresh_per_case"
        if contract["workspace"] != expected_workspace:
            raise ValueError(f"{case_id}: turns ile workspace başlangıç sözleşmesi çelişiyor")
        if not isinstance(evaluation, dict) or evaluation.get("version") != "2.1":
            raise ValueError(f"{case_id}: evaluation_contract.version eksik veya hatalı")
        if not evaluation.get("acceptance_criteria") or not evaluation.get("critical_failures"):
            raise ValueError(f"{case_id}: kabul/başarısızlık ölçütü eksik")

        artifact = answer.get("artifact")
        if answer.get("answer_mode") == "numeric_artifact":
            if not isinstance(artifact, dict):
                raise ValueError(f"{case_id}: numeric_artifact için bağımsız artifact gerekli")
            path = (REPO_ROOT / str(artifact.get("path", ""))).resolve()
            if not path.is_file() or REPO_ROOT not in path.parents:
                raise ValueError(f"{case_id}: artifact yok veya repo dışına çıkıyor: {path}")
            raw = path.read_bytes()
            actual_hash = hashlib.sha256(raw).hexdigest()
            if actual_hash != artifact.get("sha256"):
                raise ValueError(f"{case_id}: artifact SHA-256 uyuşmuyor")
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.reader(stream)
                columns = next(reader, [])
                rows = list(reader)
            if len(rows) != artifact.get("row_count"):
                raise ValueError(f"{case_id}: artifact satır sayısı uyuşmuyor")
            if columns != artifact.get("columns"):
                raise ValueError(f"{case_id}: artifact kolon manifesti uyuşmuyor")

    actual_non_cli = {case_id for case_id in local_ids if prompts[case_id]["contract_v2_1"]["surface"] != "agent_cli"}
    if actual_non_cli != NON_CLI_LOCAL:
        raise ValueError(
            f"CLI dışı vakalar beklenen {sorted(NON_CLI_LOCAL)} değil: {sorted(actual_non_cli)}"
        )
    cli_count = sum(1 for case_id in local_ids if prompts[case_id]["contract_v2_1"]["surface"] == "agent_cli")
    if cli_count != 71:
        raise ValueError(f"Agent CLI koşucusunun 71 vaka seçmesi bekleniyor, {cli_count} bulundu")
    expected_rows = {"P04": 16, "F01": 24, "T03": 1, "T06": 60, "F08": 36, "L03": 1620, "L04": 20, "Q04": 1, "Q05": 4, "I08": 2}
    for case_id, expected in expected_rows.items():
        actual = answers[case_id].get("artifact", {}).get("row_count")
        if actual != expected:
            raise ValueError(f"{case_id}: dondurulmuş oracle {expected} satır olmalı, {actual} bulundu")
    finturk = answers["L03"]["artifact"]
    finturk_path = REPO_ROOT / finturk["path"]
    with finturk_path.open(newline="", encoding="utf-8") as stream:
        province_rows = list(csv.DictReader(stream))
    if len({row["province"] for row in province_rows}) != 81 or len({row["quarter_end"] for row in province_rows}) != 20:
        raise ValueError("L03 oracle 81 il ve 20 doğal çeyrek içermeli")

    external_modes: dict[str, int] = {}
    for row in prompts.values():
        mode = str(row.get("external_mode", "none"))
        if mode != "none":
            external_modes[mode] = external_modes.get(mode, 0) + 1
            contract = row.get("contract_v2_1")
            if not isinstance(contract, dict) or contract.get("version") != "2.1":
                raise ValueError(f"{row['id']}: harici vaka için de test yüzeyi sözleşmesi gerekli")
    return [
        (
            f"{len(prompts)} vaka · {len(local_ids)} yerel · {cli_count} agent_cli · "
            f"{len(actual_non_cli)} entegrasyon/performans · {len(answers)} oracle · "
        f"{len([a for a in answers.values() if a.get('artifact')])} doğrulanmış artifact"
        ),
        "Yüzey dağılımı: " + ", ".join(f"{name}={count}" for name, count in sorted(surfaces.items())),
        "Harici durum dağılımı: " + ", ".join(f"{name}={count}" for name, count in sorted(external_modes.items())),
    ]


if __name__ == "__main__":
    try:
        for message in validate():
            print(message)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Benchmark contract invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
