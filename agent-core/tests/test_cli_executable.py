"""The core CLI must use its configured environment, including on Windows."""
from pathlib import Path
from types import SimpleNamespace

from kkb_agent.adapters import lakehouse_cli


def test_runner_resolves_executable_before_launch_and_filters_secrets(monkeypatch):
    env = {"PATH": "core-venv/Scripts", "LLM_API_KEY": "must-not-reach-core"}
    monkeypatch.setattr(lakehouse_cli.os, "environ", env)
    calls = []

    def which(name, *, path):
        assert name == "python"
        assert path == env["PATH"]
        return "C:/project with spaces/core/.venv/Scripts/python.exe"

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="status: success", stderr="")

    monkeypatch.setattr(lakehouse_cli.shutil, "which", which)
    monkeypatch.setattr(lakehouse_cli.subprocess, "run", run)
    original = ["python", "-B", "-X", "utf8", "-m", "lakehouse", "--help"]
    assert lakehouse_cli.subprocess_runner(original, Path("core")) == (0, "status: success", "")
    command, kwargs = calls[0]
    assert command == ["C:/project with spaces/core/.venv/Scripts/python.exe", *original[1:]]
    assert original[0] == "python"
    assert kwargs["env"] == {"PATH": "core-venv/Scripts"}
    assert kwargs["cwd"] == Path("core")
