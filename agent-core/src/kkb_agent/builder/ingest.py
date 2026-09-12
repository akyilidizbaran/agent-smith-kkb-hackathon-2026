"""Veri ekibinin CLI'ını çağıran yazma yolu — Architect'in tek kalemi.

Agent `lakehouse-core`'u import etmez; sözleşme sınırı (ADR-0024) yazma tarafında
da geçerli. Ingest, onların operatör yüzeyi olan `python -m lakehouse ingest-file`
komutuyla yapılır: aynı sertleştirilmiş connector, aynı parser, aynı draft
sözleşmesi, aynı provenance. Biz yalnız 15 alanı doldurup çağırırız ve çıktının
`anahtar: değer` satırlarını okuruz.

Mentörün jüri sorusu ("yarın REST API / DB / stream verirsek?") burada da aynı
cevabı alır: yeni kaynak türü onların tarafında bir connector; bu dosya değişmez.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .profile import MappingProposal, SemanticsProposal

Runner = Callable[[list[str], Path], tuple[int, str, str]]
"""(komut, çalışma dizini) → (dönüş kodu, stdout, stderr). Testte sahte, üretimde subprocess."""


def _subprocess_runner(command: list[str], cwd: Path) -> tuple[int, str, str]:
    # Agent'ın kendi venv'i alt sürece sızmasın: uv, VIRTUAL_ENV'i görünce uyarıyor ve
    # lakehouse-core'un kendi ortamı yerine bizimkini kullanmaya kalkabiliyor.
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False,
                          timeout=600, env=env)
    return proc.returncode, proc.stdout, proc.stderr


@dataclass(frozen=True)
class IngestOutcome:
    ok: bool
    status: str
    run_id: str | None = None
    artifact_sha256: str | None = None
    bronze_path: str | None = None
    series_ids: tuple[str, ...] = ()
    rows_written: int | None = None
    rows_unchanged: int | None = None
    warnings: int = 0
    error: str | None = None
    command: tuple[str, ...] = ()
    raw: str = ""

    def provenance_lines(self) -> list[str]:
        out = []
        if self.run_id:
            out.append(f"run_id: {self.run_id}")
        if self.artifact_sha256:
            out.append(f"artifact_sha256: {self.artifact_sha256}")
        if self.bronze_path:
            out.append(f"bronze: {self.bronze_path}")
        return out


def _parse_kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


@dataclass
class LakehouseCLI:
    """`python -m lakehouse` sarmalayıcısı. `runner` testte sahteyle değiştirilir."""

    core_dir: Path
    database: Path
    data_root: Path
    launcher: str = "uv run python"
    runner: Runner = field(default=_subprocess_runner)

    @property
    def available(self) -> bool:
        return (self.core_dir / "src" / "lakehouse" / "cli.py").is_file()

    def ingest_file_command(
        self, *, locator: str, dataset_id: str, mapping: MappingProposal, semantics: SemanticsProposal,
        name: str, description: str, allowed_root: Path, timeout: float = 60.0,
    ) -> list[str]:
        cmd = [*self.launcher.split(), "-m", "lakehouse", "ingest-file", locator,
               "--database", str(self.database), "--data-root", str(self.data_root),
               "--dataset-id", dataset_id, "--allowed-local-root", str(allowed_root),
               "--timeout", str(timeout),
               "--series-id", mapping.series_id,
               "--date-column", mapping.observation_date_column,
               "--value-column", mapping.value_column,
               "--date-format", mapping.date_format,
               "--decimal-separator", mapping.decimal_separator,
               "--name", name, "--description", description,
               "--frequency", semantics.frequency,
               "--unit", semantics.unit or "",
               "--measure-type", semantics.measure_type]
        if mapping.thousands_separator:
            cmd += ["--thousands-separator", mapping.thousands_separator]
        if mapping.entity_id_column:
            cmd += ["--entity-column", mapping.entity_id_column]
        if semantics.default_agg:
            cmd += ["--default-agg", semantics.default_agg]
        if semantics.week_anchor:
            cmd += ["--week-anchor", semantics.week_anchor]
        if semantics.cumulative_reset:
            cmd += ["--cumulative-reset", semantics.cumulative_reset]
        return cmd

    def ingest_file(self, **kwargs) -> IngestOutcome:
        cmd = self.ingest_file_command(**kwargs)
        code, out, err = self.runner(cmd, self.core_dir)
        kv = _parse_kv(out + "\n" + err)
        ok = code == 0 and kv.get("status") == "success"
        return IngestOutcome(
            ok=ok, status=kv.get("status", "failed" if code else "unknown"),
            run_id=kv.get("run_id"), artifact_sha256=kv.get("artifact_sha256"),
            bronze_path=kv.get("bronze_path"),
            series_ids=tuple(s.strip() for s in kv.get("series_id", "").split(",") if s.strip()),
            rows_written=int(kv["rows_written"]) if kv.get("rows_written", "").isdigit() else None,
            rows_unchanged=int(kv["rows_unchanged"]) if kv.get("rows_unchanged", "").isdigit() else None,
            warnings=int(kv["warnings"]) if kv.get("warnings", "").isdigit() else 0,
            error=kv.get("error") if not ok else None,
            command=tuple(cmd), raw=(out + err)[-2000:],
        )


__all__ = ["IngestOutcome", "LakehouseCLI", "Runner"]
