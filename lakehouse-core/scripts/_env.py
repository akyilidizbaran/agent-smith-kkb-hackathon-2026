"""Shared helper: load lakehouse-core/.env into os.environ for the scripts/ utilities.

python-dotenv is not a project dependency (see pyproject.toml), so this reads the file by
hand rather than adding one for a handful of manual scripts. Existing environment variables
are never overwritten (os.environ.setdefault), so an explicitly-exported EVDS_API_KEY still
wins over whatever .env says.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv_simple(repo_root: Path) -> None:
    env_path = repo_root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


__all__ = ["load_dotenv_simple"]
