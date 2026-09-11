"""Uçtan uca çalıştırıcı: soru → agent → cevap + izlenebilirlik.

Kullanım:
    python -m kkb_agent.cli "2025 yılında konut kredisi bakiyesi nasıl değişti?"
    python -m kkb_agent.cli            # etkileşimli mod
    python -m kkb_agent.cli --health   # bağlantı kontrolü
"""

from __future__ import annotations

import argparse
import logging
import sys

from .adapters.duckdb_lakehouse import DuckDBLakehouse
from .adapters.silver_lakehouse import SilverLakehouse
from .contracts.lakehouse import LakehouseError
from .config import load_settings
from .core.agent import AnalyticsAgent
from .core.registry import ToolRegistry
from .core.workspace import AnalysisWorkspace
from .domain import DomainProfile
from .llm.openai_compat import OpenAICompatClient
from .tools.workspace import (
    WorkspaceAddColumnTool,
    WorkspaceComputeColumnTool,
    WorkspaceShowTool,
)
from .tools.lakehouse import (
    LakehouseDescribeTool,
    LakehouseDistinctValuesTool,
    LakehouseQueryTool,
    LakehouseSearchTool,
)


def open_lakehouse(path) -> SilverLakehouse | DuckDBLakehouse:
    """Veritabanının şemasına göre adaptörü seçer.

    Şemayı ayrı bir bağlantı açarak yoklamıyoruz: DuckDB aynı dosyaya farklı
    yapılandırmayla ikinci bağlantıyı reddediyor (sertleştirilmiş bağlantı
    read_only + locked config kullanıyor). Bunun yerine Silver adaptörünü
    kurmayı deniyoruz; beklenen ilişkiler yoksa kendi seed adaptörümüze düşüyoruz.
    """
    try:
        return SilverLakehouse(path)
    except LakehouseError as exc:
        if "meta.series" not in str(exc) and "silver.fact_observation" not in str(exc):
            raise
        return DuckDBLakehouse(path)


def build_agent(max_steps: int = 10) -> AnalyticsAgent:
    """Motoru kurar. Yeni araçlar buraya eklenir; agent kodu değişmez."""
    settings = load_settings()
    # Veri ekibinin Silver şeması varsa ona bağlan; yoksa kendi BDDK seed'imize.
    # Gerçek Lakehouse geldiğinde değişen tek şey LAKEHOUSE_PATH olur.
    lakehouse = open_lakehouse(settings.lakehouse_path)
    workspace = AnalysisWorkspace()

    # Alan profili katalogdan deterministik olarak türetilir; üslup tercihleri
    # (.env'deki DOMAIN_DESCRIPTION / DOMAIN_AUDIENCE) varsa onlar geçerlidir.
    profile = DomainProfile.from_catalog(
        lakehouse.list_datasets(),
        domain=settings.domain_description,
        audience=settings.domain_audience,
    )

    registry = ToolRegistry(profile)
    registry.register_all(
        [
            LakehouseSearchTool(lakehouse),
            LakehouseDescribeTool(lakehouse),
            LakehouseDistinctValuesTool(lakehouse),
            LakehouseQueryTool(lakehouse, workspace, registry),
            WorkspaceAddColumnTool(lakehouse, workspace),
            WorkspaceComputeColumnTool(workspace),
            WorkspaceShowTool(workspace),
        ]
    )

    llm = OpenAICompatClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        disable_thinking=settings.disable_thinking,
    )
    print(
        f"[motor] sağlayıcı={settings.provider_label} model={settings.llm_model} "
        f"alan={profile.domain!r} araçlar={len(registry)}",
        file=sys.stderr,
    )
    return AnalyticsAgent(
        llm, registry, workspace=workspace, max_steps=max_steps, profile=profile
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="KKB Agentic Analytics Engine")
    parser.add_argument("question", nargs="*", help="Sorulacak soru")
    parser.add_argument("--trace", action="store_true", help="Araç çağrılarını göster")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--health", action="store_true", help="Lakehouse durumunu göster")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.health:
        agent = build_agent()
        lh = agent.registry.get("lakehouse_search").lakehouse
        info = lh.health()
        for key, value in info.items():
            shown = ", ".join(map(str, value)) if isinstance(value, list) else value
            print(f"  {key:20} {shown if shown != '' else '—'}")
        print(f"  {'alan profili':20} {agent.profile.domain}")
        for spec in lh.list_datasets():
            print(
                f"    - {spec.dataset_id}: {spec.coverage.row_count} gözlem "
                f"({spec.coverage.start} → {spec.coverage.end}) [{spec.frequency.value}]"
            )
        return

    agent = build_agent(max_steps=args.max_steps)

    def answer(q: str) -> None:
        result = agent.ask(q)
        if args.trace:
            print("\n--- izlenebilirlik ---")
            print(result.trace_text())
            print("---")
        print(f"\n{result.text}\n")
        if result.hit_step_limit:
            print("(uyarı: adım limitine ulaşıldı)", file=sys.stderr)

    if args.question:
        answer(" ".join(args.question))
        return

    print("Etkileşimli mod. Çıkmak için 'q'. Analizi sıfırlamak için 'reset'.")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"q", "quit", "exit"}:
            break
        if q.lower() == "reset":
            agent.reset()
            print("Analiz sıfırlandı.")
            continue
        if q:
            answer(q)


if __name__ == "__main__":
    main()
