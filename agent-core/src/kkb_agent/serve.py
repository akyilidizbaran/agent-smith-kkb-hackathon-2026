"""`python -m kkb_agent.serve` — arayüzü yerelde açar (uvicorn). `kkb_agent.web` paketi web araçlarına ait."""

from __future__ import annotations

import os

import uvicorn

from .web_app import build_default_app


def main() -> None:
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8765"))
    uvicorn.run(build_default_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
