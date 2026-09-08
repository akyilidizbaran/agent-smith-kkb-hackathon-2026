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
from .config import load_settings
from .core.agent import AnalyticsAgent
from .core.registry import ToolRegistry
from .core.workspace import AnalysisWorkspace
from .llm.openai_compat import OpenAICompatClient
from .tools.lakehouse import (
    LakehouseDescribeTool,
    LakehouseDistinctValuesTool,
    LakehouseQueryTool,
    LakehouseSearchTool,
)


def build_agent(max_steps: int = 10) -> AnalyticsAgent:
    """Motoru kurar. Yeni araçlar buraya eklenir; agent kodu değişmez."""
    settings = load_settings()
    lakehouse = DuckDBLakehouse(settings.lakehouse_path)
    workspace = AnalysisWorkspace()

    registry = ToolRegistry()
    registry.register_all(
        [
            LakehouseSearchTool(lakehouse),
            LakehouseDescribeTool(lakehouse),
            LakehouseDistinctValuesTool(lakehouse),
            LakehouseQueryTool(lakehouse, workspace),
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
        f"araçlar={', '.join(registry.names())}",
        file=sys.stderr,
    )
    return AnalyticsAgent(llm, registry, workspace=workspace, max_steps=max_steps)


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
        settings = load_settings()
        lh = DuckDBLakehouse(settings.lakehouse_path)
        info = lh.health()
        print(f"Lakehouse : {info['db_path']}")
        print(f"Tablolar  : {', '.join(info['physical_tables']) or '—'}")
        print(f"Katalog   : {', '.join(info['catalog_datasets']) or '—'}")
        for spec in lh.list_datasets():
            print(
                f"  - {spec.dataset_id}: {spec.coverage.row_count} satır "
                f"({spec.coverage.start} → {spec.coverage.end})"
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
