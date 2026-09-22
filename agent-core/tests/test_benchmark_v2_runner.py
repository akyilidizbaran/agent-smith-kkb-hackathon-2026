from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.m02_benchmark.run_v2 import BenchmarkCase, execute_case, load_cases


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_load_cases_defaults_to_local_and_checks_reference_coverage(tmp_path):
    prompts = tmp_path / "prompts.jsonl"
    answers = tmp_path / "answers.jsonl"
    _write_jsonl(
        prompts,
        [
            {"id": "P01", "family": "P", "title": "local", "turns": ["ilk", "takip"], "external_mode": "none"},
            {"id": "E01", "family": "E", "title": "file", "turns": ["dosya"], "external_mode": "fixture", "placeholders": ["{{CSV}}"]},
        ],
    )
    _write_jsonl(answers, [{"id": "P01", "reference_answer": "beklenti"}])

    cases = load_cases(prompts, answers)

    assert [case.id for case in cases] == ["P01"]
    assert cases[0].turns == ("ilk", "takip")
    assert cases[0].reference["reference_answer"] == "beklenti"


def test_load_cases_rejects_missing_local_reference(tmp_path):
    prompts = tmp_path / "prompts.jsonl"
    answers = tmp_path / "answers.jsonl"
    _write_jsonl(prompts, [{"id": "P01", "family": "P", "turns": ["soru"], "external_mode": "none"}])
    _write_jsonl(answers, [])

    try:
        load_cases(prompts, answers)
    except ValueError as exc:
        assert "P01" in str(exc)
    else:
        raise AssertionError("yerel referans eksikliği hata vermeliydi")


def test_load_cases_keeps_integration_cases_out_of_agent_cli(tmp_path):
    prompts = tmp_path / "prompts.jsonl"
    answers = tmp_path / "answers.jsonl"
    _write_jsonl(
        prompts,
        [
            {
                "id": "P01",
                "family": "P",
                "turns": ["soru"],
                "external_mode": "none",
                "contract_v2_1": {"surface": "agent_cli"},
            },
            {
                "id": "O03",
                "family": "O",
                "turns": ["ui"],
                "external_mode": "none",
                "contract_v2_1": {"surface": "ui_e2e"},
            },
        ],
    )
    _write_jsonl(answers, [{"id": "P01", "evaluation_contract": {"version": "2.1"}}, {"id": "O03"}])

    cases = load_cases(prompts, answers)

    assert [case.id for case in cases] == ["P01"]
    assert cases[0].surface == "agent_cli"
    try:
        load_cases(prompts, answers, ids={"O03"})
    except ValueError as exc:
        assert "O03" in str(exc)
        assert "CONTRACT_V2_1.md" in str(exc)
    else:
        raise AssertionError("CLI dışı vakayı açıkça seçmek hata vermeliydi")


def test_frozen_v2_1_benchmark_contract_and_artifacts_validate():
    repo_root = Path(__file__).resolve().parents[2]
    validator = repo_root / "agent-core/scripts/m02_benchmark/validate_contract_v2_1.py"
    result = subprocess.run(
        [sys.executable, str(validator)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "120 vaka" in result.stdout


def test_execute_case_keeps_followups_in_one_agent_and_writes_table(tmp_path):
    table = pd.DataFrame({"period": ["2024-01", "2024-02"], "value": [10.0, 12.0]})

    class FakeAgent:
        def __init__(self):
            self.workspace = SimpleNamespace(table=table)
            self.questions = []

        def ask(self, question):
            self.questions.append(question)
            return SimpleNamespace(
                text=f"cevap: {question}",
                steps=[SimpleNamespace(index=len(self.questions), role="retrieve", tool_name="lakehouse_search", ok=True,
                                       error_code=None, duration_ms=2, tool_args={"query": question}, result_summary="ok")],
                usage={"calls": 1, "prompt": 5},
                grounding="OK",
                availability_status="FOUND",
            )

    agent = FakeAgent()
    case = BenchmarkCase(
        id="F02", family="F", title="follow-up", turns=("ilk", "takip"), prompt="ilk",
        reference={"answer_mode": "numeric_artifact", "reference_answer": "iki satır"},
    )

    row = execute_case(case, lambda: agent, artifact_dir=tmp_path)

    assert agent.questions == ["ilk", "takip"]
    assert row["status"] == "executed_needs_review"
    assert row["turn_count"] == 2
    assert len(row["steps"]) == 2
    assert row["table"]["rows"] == 2
    assert Path(row["table"]["csv_path"]).exists()
    assert len(row["table"]["sha256"]) == 64


def test_execute_case_marks_recovered_narration_failure():
    class FakeAgent:
        workspace = SimpleNamespace(table=pd.DataFrame({"value": [1]}))

        def ask(self, question):
            return SimpleNamespace(
                text="Tablo hazır; anlatı üretilemedi.",
                steps=[SimpleNamespace(index=1, role="narrate", tool_name=None, ok=False,
                                       error_code="LLM_UNAVAILABLE", duration_ms=30_000,
                                       tool_args={}, result_summary="narration timeout")],
                usage={"calls": 1, "failed_llm_calls": 1, "failed_llm_phase": "narration"},
                grounding="",
                availability_status="FOUND",
            )

    case = BenchmarkCase(
        id="P01", family="P", title="local", turns=("soru",), prompt="soru", reference={}
    )

    row = execute_case(case, FakeAgent)

    assert row["status"] == "recovered_with_llm_failure"
    assert row["llm_failure_recovered"] is True
