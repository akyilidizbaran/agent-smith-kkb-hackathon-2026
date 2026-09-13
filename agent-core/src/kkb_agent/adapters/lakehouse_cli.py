"""Veri ekibinin `python -m lakehouse` yüzeyine ortak alt süreç tesisatı.

İki yol bu dosyayı paylaşır: Architect'in yazma yolu (`builder/ingest.py`, ingest-file)
ve Analist'in salt-okunur Gold çağrısı (`adapters/gold_cli.py`, gold-run). Agent
`lakehouse-core`'u import etmez (ADR-0024); her iki yol da onların CLI'ını ayrı bir
süreçte çalıştırıp `anahtar: değer` satırlarını okur. Komut ve çıktı biçimi sözleşmedir,
paket değil.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

Runner = Callable[[list[str], Path], tuple[int, str, str]]
"""(komut, çalışma dizini) → (dönüş kodu, stdout, stderr). Testte sahte, üretimde subprocess."""


ENV_ALLOWLIST = ("PATH", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE", "TERM",
                 "UV_CACHE_DIR", "UV_PYTHON", "UV_PROJECT_ENVIRONMENT", "PYTHONIOENCODING",
                 "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "XDG_CACHE_HOME", "USER")
"""Alt sürece geçen ortam değişkenleri (ADR-0037). MIA/LLM anahtarı, EVDS anahtarı ve
öteki gizler geçmez: ingest-file ve gold-run hiçbirine ihtiyaç duymaz. VIRTUAL_ENV de
geçmez: uv onu görünce lakehouse-core'un ortamı yerine bizimkini kullanmaya kalkıyor."""


def subprocess_env(source: dict[str, str] | None = None) -> dict[str, str]:
    base = os.environ if source is None else source
    return {k: v for k, v in base.items() if k in ENV_ALLOWLIST}


def subprocess_runner(command: list[str], cwd: Path, *, timeout: float = 600) -> tuple[int, str, str]:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False,
                          timeout=timeout, env=subprocess_env())
    return proc.returncode, proc.stdout, proc.stderr


def parse_kv(text: str) -> dict[str, str]:
    """`anahtar: değer` satırlarını sözlüğe çevirir; ilk iki noktadan böler."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def cli_available(core_dir: Path) -> bool:
    return (Path(core_dir) / "src" / "lakehouse" / "cli.py").is_file()


__all__ = ["ENV_ALLOWLIST", "Runner", "cli_available", "parse_kv", "subprocess_env", "subprocess_runner"]
