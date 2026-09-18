"""Ortam yapılandırması. Gizli değerler yalnızca .env'den okunur."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

# agent-core/ dizini (kod) ve repo kökü (veri, .env, lakehouse-core). M01 (ADR-0049): veri
# yolları REPO_ROOT/data altında toplanır; göreli yollar repo köküne göre çözülür, kod dizinine değil.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent


def _path(env: str, default: Path, *, base: Path | None = None) -> Path:
    """Ortam değişkeni varsa (göreliyse repo köküne göre), yoksa varsayılan."""
    raw = os.getenv(env)
    if not raw:
        return default
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (base or REPO_ROOT) / p

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
    # demo: Silver şeması şart, yoksa açık nedenle durur · seed: geliştirme seed'i · auto: dene, düş (testler)
    lakehouse_mode: str
    data_root: Path              # RAW/Bronze/incoming/charts/cache kökü (LAKEHOUSE --data-root ile aynı)
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
    # Profil (M04, ADR-0056): analyst = yazma araçları kayıt defterine hiç girmez; architect = ingest/terfi/sıfırlama.
    # Profil başlatmada seçilir; oturumda geçiş yalnız ARCHITECT_TOKEN ile (boşsa geçiş kapalı).
    agent_profile: str
    architect_token: str
    # Bütçeler (M15): tek çağrı zaman aşımı, çıktı sınırı, soru başına toplam süre.
    llm_timeout: float
    llm_max_retries: int
    llm_max_tokens: int
    agent_time_budget_s: float
    # Çağrı türüne göre dinamik completion tavanları (global tavanın altında).
    llm_plan_max_tokens: int = 1000
    llm_tool_max_tokens: int = 1800
    llm_narrate_max_tokens: int = 2800
    llm_long_narrate_max_tokens: int = 3400
    llm_recovery_max_tokens: int = 1400

    @property
    def provider_label(self) -> str:
        """Loglarda hangi sağlayıcıda olduğumuzu görmek için."""
        return "ollama (yerel)" if "localhost" in self.llm_base_url else "kloudeks"

    @property
    def llm_key_missing(self) -> bool:
        """K02-T01 (A01): uzak model uç noktası için anahtar boşsa arayüz başlayamaz; ön kontrol bunu HAZIR saymamalı."""
        local = any(h in self.llm_base_url for h in ("localhost", "127.0.0.1"))
        return not local and not (self.llm_api_key or "").strip()


def load_settings() -> Settings:
    data_root = _path("DATA_ROOT", REPO_ROOT / "data")
    return Settings(
        llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        llm_api_key=os.getenv("LLM_API_KEY", "ollama"),
        llm_model=os.getenv("LLM_MODEL", "qwen3:8b"),
        embedding_model=os.getenv("EMBEDDING_MODEL") or None,
        vision_model=os.getenv("VISION_MODEL") or None,
        lakehouse_path=_path("LAKEHOUSE_PATH", data_root / "lakehouse.duckdb"),
        lakehouse_mode=os.getenv("LAKEHOUSE_MODE", "demo").strip().lower(),
        data_root=data_root,
        evds_api_key=os.getenv("EVDS_API_KEY") or None,
        disable_thinking=os.getenv("LLM_DISABLE_THINKING", "true").lower() == "true",
        domain_description=os.getenv("DOMAIN_DESCRIPTION") or None,
        domain_audience=os.getenv("DOMAIN_AUDIENCE") or None,
        lakehouse_core_dir=_path("LAKEHOUSE_CORE_DIR", REPO_ROOT / "lakehouse-core"),
        lakehouse_cli=os.getenv("LAKEHOUSE_CLI", "uv run python"),
        ingest_allowed_root=_path("INGEST_ALLOWED_ROOT", data_root / "incoming"),
        chart_dir=_path("CHART_DIR", data_root / "charts"),
        geo_dir=_path("GEO_DIR", PROJECT_ROOT / "assets" / "geo"),  # sınır dosyası lisansıyla repoya girer
        preload_budget_tokens=int(os.getenv("PRELOAD_BUDGET_TOKENS", "6000")),
        preload_k=int(os.getenv("PRELOAD_K", "8")),
        retrieval_mode=os.getenv("RETRIEVAL_MODE", "auto"),
        retrieval_small_max=int(os.getenv("RETRIEVAL_SMALL_MAX", "60")),
        retrieval_hybrid_min=int(os.getenv("RETRIEVAL_HYBRID_MIN", "5000")),
        embedding_cache_dir=_path("EMBEDDING_CACHE_DIR", data_root / "cache" / "embeddings"),
        narrate_temperature=float(os.getenv("LLM_NARRATE_TEMPERATURE", "0.5")),
        tool_gate=os.getenv("TOOL_GATE", "on").lower() != "off",
        agent_profile=os.getenv("AGENT_PROFILE", "analyst").strip().lower(),
        architect_token=os.getenv("ARCHITECT_TOKEN", "").strip(),
        llm_timeout=float(os.getenv("LLM_TIMEOUT", "90")),
        llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        # The full table is kept as a structured UI artifact, but 1,500 tokens
        # is too small for a legitimate 24/60-month narration. Keep the
        # environment override and give the default final turn enough room.
        llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4000")),
        # Demo'da uzun çok-adımlı sorguların istemci tarafından erken kesilmemesi
        # için varsayılan soru bütçesi 600 s. Ortam değişkeniyle daha düşük bir
        # bütçe verilirse o değer önceliklidir.
        agent_time_budget_s=float(os.getenv("AGENT_TIME_BUDGET_S", "600")),
        llm_plan_max_tokens=int(os.getenv("LLM_PLAN_MAX_TOKENS", "1000")),
        llm_tool_max_tokens=int(os.getenv("LLM_TOOL_MAX_TOKENS", "1800")),
        llm_narrate_max_tokens=int(os.getenv("LLM_NARRATE_MAX_TOKENS", "2800")),
        llm_long_narrate_max_tokens=int(os.getenv("LLM_LONG_NARRATE_MAX_TOKENS", "3400")),
        llm_recovery_max_tokens=int(os.getenv("LLM_RECOVERY_MAX_TOKENS", "1400")),
    )
