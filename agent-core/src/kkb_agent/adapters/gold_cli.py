"""Salt-okunur Gold çağrısı — veri ekibinin `gold-run` komutu üzerinden.

Gold fonksiyonları (`align_frequency`, `decompose_cumulative`, `join_on_period`) veri
ekibinin paketinde yaşar ve kuralı `meta.series`'ten okur: stok → dönem sonu, akım →
toplam, oran → katalogdaki kural. Model bu kuralı seçemez; fonksiyon ya sonucu verir ya
da SEBEBİYLE reddeder (`GoldRefusal`). Bu dosya o çağrıyı ayrı bir süreçte yaptırır ve
sonucu (bir JSON belgesi) DataFrame'e çevirir.

Neden import değil, alt süreç: agent `lakehouse-core`'u import etmez (ADR-0024). Ingest
(ADR-0030) ile aynı sınır, aynı tesisat. Okuma olduğu için okuyucuyu kapatmak gerekmez:
DuckDB birden çok salt-okunur süreci aynı anda kabul eder; `gold-run` de sertleştirilmiş
salt-okunur profille açar.

JSON belgesi sözleşmesi (`lakehouse.gold.serialize`): `columns`, `rows`; tarih ISO metin,
liste dizi, eksik `null`. Tipler burada kolonun TABAN adından (son `::` sonrası) geri
kazanılır — join çerçevesinde `<seri>@<varlık>::value` gibi.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .lakehouse_cli import Runner, cli_available, parse_kv, subprocess_runner

GOLD_FUNCTIONS = ("align_frequency", "decompose_cumulative", "join_on_period")
TARGET_FREQUENCIES = ("monthly", "quarterly")

_DOUBLE = frozenset({"value", "cumulative_value", "previous_cumulative_value", "raw_change"})
_DATE = frozenset({"period_start", "period_end", "previous_observation_date"})
_INTEGER = frozenset({"observations", "missing_observations", "warned_observations", "contributor_count"})
_DATE_LIST = frozenset({"source_observation_dates"})


def _base(column: str) -> str:
    return column.rsplit("::", 1)[-1]


def _to_date(value: Any) -> Any:
    return date.fromisoformat(value) if isinstance(value, str) else value


def document_to_frame(document: dict[str, Any]) -> pd.DataFrame:
    """JSON belgesini, kolon taban adına göre tiplenmiş bir DataFrame'e çevirir.

    `value` float64 olur (eksik → NaN) ki golden'ın sayısal kolon taraması ve grafik
    araçları onu görsün; tarihler `datetime.date`; sayımlar Int64; listeler liste kalır.
    """
    columns = [str(c) for c in document["columns"]]
    frame = pd.DataFrame(document["rows"], columns=columns)
    for column in columns:
        base = _base(column)
        if base in _DOUBLE:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")
        elif base in _INTEGER:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
        elif base in _DATE:
            frame[column] = frame[column].map(_to_date)
        elif base in _DATE_LIST:
            frame[column] = frame[column].map(
                lambda items: [_to_date(v) for v in items] if isinstance(items, list) else items
            )
    return frame


@dataclass(frozen=True)
class GoldRunOutcome:
    ok: bool
    status: str                      # success | refused | failed
    function: str
    arguments: dict[str, Any]
    frame: pd.DataFrame | None = None
    reason: str | None = None        # GoldRefusal.reason (kapalı sözlük)
    series_id: str | None = None
    message: str | None = None
    command: tuple[str, ...] = ()
    raw: str = field(default="", repr=False)


@dataclass
class GoldCLI:
    """`python -m lakehouse gold-run` sarmalayıcısı. `runner` testte sahteyle değiştirilir."""

    core_dir: Path
    database: Path
    launcher: str = "uv run python"
    runner: Runner = field(default=subprocess_runner)
    scratch_dir: Path | None = None

    @property
    def available(self) -> bool:
        return cli_available(self.core_dir)

    def command(
        self, *, function: str, series_ids: list[str], target_frequency: str | None,
        out: Path, allow_unverified_semantics: bool = False,
    ) -> list[str]:
        cmd = [*self.launcher.split(), "-m", "lakehouse", "gold-run",
               "--database", str(self.database), "--function", function]
        for series_id in series_ids:
            cmd += ["--series", series_id]
        if target_frequency:
            cmd += ["--target", target_frequency]
        if allow_unverified_semantics:
            cmd.append("--allow-unverified-semantics")
        cmd += ["--out", str(out)]
        return cmd

    def run(
        self, *, function: str, series_ids: list[str], target_frequency: str | None = None,
        allow_unverified_semantics: bool = False,
    ) -> GoldRunOutcome:
        if function not in GOLD_FUNCTIONS:
            raise ValueError(f"bilinmeyen Gold fonksiyonu: {function!r}")
        arguments = {"series_ids": list(series_ids), "target_frequency": target_frequency,
                     "allow_unverified_semantics": allow_unverified_semantics}
        scratch = Path(self.scratch_dir or tempfile.gettempdir())
        scratch.mkdir(parents=True, exist_ok=True)
        out = scratch / f"gold_run_{uuid.uuid4().hex}.json"
        cmd = self.command(function=function, series_ids=list(series_ids),
                           target_frequency=target_frequency, out=out,
                           allow_unverified_semantics=allow_unverified_semantics)
        try:
            code, stdout, stderr = self.runner(cmd, self.core_dir)
            kv = parse_kv(stdout + "\n" + stderr)
            status = kv.get("status", "failed" if code else "unknown")
            raw = (stdout + stderr)[-2000:]
            if status == "success" and out.is_file():
                document = json.loads(out.read_text(encoding="utf-8"))
                return GoldRunOutcome(ok=True, status="success", function=function,
                                      arguments=arguments, frame=document_to_frame(document),
                                      command=tuple(cmd), raw=raw)
            if status == "refused":
                return GoldRunOutcome(ok=False, status="refused", function=function,
                                      arguments=arguments, reason=kv.get("reason"),
                                      series_id=kv.get("series_id"), message=kv.get("message"),
                                      command=tuple(cmd), raw=raw)
            return GoldRunOutcome(ok=False, status="failed", function=function, arguments=arguments,
                                  message=kv.get("error") or (stderr.strip()[-400:] or f"çıkış kodu {code}"),
                                  command=tuple(cmd), raw=raw)
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass


__all__ = ["GOLD_FUNCTIONS", "TARGET_FREQUENCIES", "GoldCLI", "GoldRunOutcome", "document_to_frame"]
