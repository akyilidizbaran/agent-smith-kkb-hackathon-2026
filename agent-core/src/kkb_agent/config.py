"""Ortam yapılandırması. Gizli değerler yalnızca .env'den okunur."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

# agent-core/ dizini: veri ve yapılandırma yolları buna göre çözülür.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# .env takımın ortak deposunda, repo kökünde durur (agent-core'un bir üstü).
# find_dotenv yukarı doğru aradığı için hangi dizinden çalıştırıldığımız fark etmez.
load_dotenv(find_dotenv(usecwd=False) or PROJECT_ROOT.parent / ".env")


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    embedding_model: str | None
    vision_model: str | None
    lakehouse_path: Path
    evds_api_key: str | None
    disable_thinking: bool
    domain_description: str | None
    domain_audience: str | None

    @property
    def provider_label(self) -> str:
        """Loglarda hangi sağlayıcıda olduğumuzu görmek için."""
        return "ollama (yerel)" if "localhost" in self.llm_base_url else "kloudeks"


def load_settings() -> Settings:
    return Settings(
        llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        llm_api_key=os.getenv("LLM_API_KEY", "ollama"),
        llm_model=os.getenv("LLM_MODEL", "qwen3:8b"),
        embedding_model=os.getenv("EMBEDDING_MODEL") or None,
        vision_model=os.getenv("VISION_MODEL") or None,
        lakehouse_path=PROJECT_ROOT / os.getenv("LAKEHOUSE_PATH", "data/lakehouse.duckdb"),
        evds_api_key=os.getenv("EVDS_API_KEY") or None,
        disable_thinking=os.getenv("LLM_DISABLE_THINKING", "true").lower() == "true",
        domain_description=os.getenv("DOMAIN_DESCRIPTION") or None,
        domain_audience=os.getenv("DOMAIN_AUDIENCE") or None,
    )
