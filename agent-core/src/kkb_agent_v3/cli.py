"""V3 motorunu kurar ve çalıştırır.

    python -m kkb_agent_v3.cli "2025 yılında <kalem> aylık nasıl değişti?"
    python -m kkb_agent_v3.cli --trace "..."

Ortam değişkenleri (hepsi opsiyonel):
    KKB_V3_DOMAIN_FILE   alan notları markdown'ı (varsayılan: domain/finance.md)
    KKB_V3_DOMAIN_BUDGET alan notları için prompt bütçesi, token (varsayılan 1500)
    KKB_V3_CATALOG_BUDGET katalog bütçesi, token (varsayılan 6000, E8)
    KKB_V3_GROUNDING     off | shadow | enforce (varsayılan enforce)
    KKB_V3_PARALLEL      0/1 (varsayılan 1)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from kkb_agent.cli import open_lakehouse
from kkb_agent.config import load_settings
from kkb_agent.core.workspace import AnalysisWorkspace
from kkb_agent.domain import DomainProfile

from .core.agent import AgentConfig, V3Agent
from .core.context import build_catalog_context
from .core.validator import ToolRegistry
from .domain.loader import DOMAIN_DIR, load_domain_file
from .llm import V3LLMClient
from .tools.domain_note import LookupDomainNoteTool
from .tools.lakehouse import (
    LakehouseDescribeTool,
    LakehouseDistinctValuesTool,
    LakehouseQueryTool,
    LakehouseSearchTool,
)
from .tools.workspace import workspace_tools


def build_agent(max_steps: int = 8, config: AgentConfig | None = None) -> V3Agent:
    settings = load_settings()
    # Ekip adaptör seçimi (ADR-0024): Silver şeması varsa SilverLakehouse, yoksa BDDK seed.
    lakehouse = open_lakehouse(settings.lakehouse_path)
    workspace = AnalysisWorkspace()
    profile = DomainProfile.from_catalog(
        lakehouse.list_datasets(), domain=settings.domain_description, audience=settings.domain_audience
    )
    if config is None:
        config = AgentConfig(
            max_turns=max_steps,
            grounding=os.getenv("KKB_V3_GROUNDING", "enforce"),
            parallel=os.getenv("KKB_V3_PARALLEL", "1") == "1",
        )

    registry = ToolRegistry(profile)
    registry.register_all([
        LakehouseSearchTool(lakehouse),
        LakehouseDescribeTool(lakehouse),
        LakehouseDistinctValuesTool(lakehouse),
        LakehouseQueryTool(lakehouse, workspace, registry),
        *workspace_tools(lakehouse, workspace),
    ])

    domain_file = os.getenv("KKB_V3_DOMAIN_FILE", str(DOMAIN_DIR / "finance.md"))
    knowledge = load_domain_file(domain_file)
    domain_text, needs_lookup = knowledge.render_for_prompt(int(os.getenv("KKB_V3_DOMAIN_BUDGET", "1500")))
    if needs_lookup:
        registry.register(LookupDomainNoteTool(knowledge))

    catalog = build_catalog_context(lakehouse, budget_tokens=int(os.getenv("KKB_V3_CATALOG_BUDGET", "6000")))

    llm = V3LLMClient(
        base_url=settings.llm_base_url, api_key=settings.llm_api_key, model=settings.llm_model,
        disable_thinking=settings.disable_thinking,
    )
    print(
        f"[v3] sağlayıcı={settings.provider_label} model={settings.llm_model} alan={profile.domain!r} "
        f"araçlar={len(registry)} katalog={catalog.mode}/{catalog.tokens}tok "
        f"notlar={'lookup' if needs_lookup else 'gömülü'}/{knowledge.inline_tokens()}tok",
        file=sys.stderr,
    )
    return V3Agent(llm, registry, workspace=workspace, profile=profile, config=config,
                   catalog_context=catalog.text, domain_context=domain_text)


def main() -> None:
    parser = argparse.ArgumentParser(description="KKB Agentic Analytics — V3 motoru")
    parser.add_argument("question", nargs="*")
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    agent = build_agent(max_steps=args.max_turns)

    def answer(q: str) -> None:
        result = agent.ask(q)
        if args.trace:
            print("\n--- izlenebilirlik ---\n" + result.trace_text() + "\n---")
            print(f"turlar={result.extra.get('llm_turns')} token={result.extra.get('tokens')} "
                  f"grounding={result.extra.get('grounding') or '-'} hatalar={result.extra.get('error_codes')}")
        print(f"\n{result.text}\n")
        if result.hit_step_limit:
            print("(uyarı: tur limitine ulaşıldı)", file=sys.stderr)

    if args.question:
        answer(" ".join(args.question))
        return
    print("Etkileşimli mod. Çıkmak için 'q', sıfırlamak için 'reset'.")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"q", "quit", "exit"}:
            break
        if q.lower() == "reset":
            agent.reset()
            continue
        if q:
            answer(q)


if __name__ == "__main__":
    main()
