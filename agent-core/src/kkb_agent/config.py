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
    # Architect: veri ekibinin CLI'ı hangi dizinde ve nasıl çalıştırılır. Agent
    # lakehouse-core'u import etmez; ingest'i onların operatör yüzeyinden (CLI) ister.
    lakehouse_core_dir: Path
    lakehouse_cli: str          # ör. "uv run python" — core_dir içinde çalıştırılır
    ingest_allowed_root: Path   # Architect'in okuyabileceği tek yerel kök
    # Grafik: belirtim + PNG/SVG buraya yazılır; il sınırları (GeoJSON) buradan okunur.
    chart_dir: Path
    geo_dir: Path
    # Ön-yükleme (ADR-0013/0035): soruya göre seçilen seri kartları için token bütçesi; 0 kapatır.
    preload_budget_tokens: int
    preload_k: int
    # Retrieval kademesi (ADR-0043): auto | preload_all | bm25 | hybrid; eşikler retrieval golden ile ölçülür.
    retrieval_mode: str
    retrieval_small_max: int
    retrieval_hybrid_min: int
    embedding_cache_dir: Path
    narrate_temperature: float   # nihai anlatı turu; araç turları hep 0 (ADR-0046)
    # Araç kapısı (ADR-0043): soruya göre araç alt kümesi sunulur; "off" ile ölçüm için kapatılır.
    tool_gate: bool

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
        lakehouse_core_dir=Path(os.getenv("LAKEHOUSE_CORE_DIR", PROJECT_ROOT.parent / "lakehouse-core")),
        lakehouse_cli=os.getenv("LAKEHOUSE_CLI", "uv run python"),
        ingest_allowed_root=Path(os.getenv("INGEST_ALLOWED_ROOT", PROJECT_ROOT.parent / "incoming")),
        chart_dir=Path(os.getenv("CHART_DIR", PROJECT_ROOT / "data" / "charts")),
        geo_dir=Path(os.getenv("GEO_DIR", PROJECT_ROOT / "assets" / "geo")),  # data/ gitignore'da; sınır dosyası lisansıyla repoya girer
        preload_budget_tokens=int(os.getenv("PRELOAD_BUDGET_TOKENS", "6000")),
        preload_k=int(os.getenv("PRELOAD_K", "8")),
        retrieval_mode=os.getenv("RETRIEVAL_MODE", "auto"),
        retrieval_small_max=int(os.getenv("RETRIEVAL_SMALL_MAX", "60")),
        retrieval_hybrid_min=int(os.getenv("RETRIEVAL_HYBRID_MIN", "5000")),
        embedding_cache_dir=Path(os.getenv("EMBEDDING_CACHE_DIR", PROJECT_ROOT / "data" / "cache" / "embeddings")),
        narrate_temperature=float(os.getenv("LLM_NARRATE_TEMPERATURE", "0.5")),
        tool_gate=os.getenv("TOOL_GATE", "on").lower() != "off",
    )
