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
from pathlib import Path

from .adapters.duckdb_lakehouse import DuckDBLakehouse
from .adapters.gold_cli import GoldCLI
from .adapters.silver_lakehouse import SilverLakehouse
from .contracts.lakehouse import GoldCapable, LakehouseError
from .config import load_settings
from .core.agent import SYSTEM_PROMPT, AnalyticsAgent
from .core.context import build_question_context
from .core.evidence import EvidenceBuilder
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
from .builder.ingest import LakehouseCLI
from .tools.ingest import IngestFromUrlTool
from .tools.promote import PromoteDraftTool
from .tools.gold import GOLD_PROMPT_RULES, GoldAlignTool, GoldDecomposeTool, GoldJoinTool
from .tools.chart import CHART_PROMPT_RULES, ChartTool
from .tools.workspace_query import WorkspaceQueryTool
from .tools.real_value import REAL_VALUE_PROMPT_RULES, WorkspaceRealValueTool
from .tools.workspace_join import WorkspaceJoinTool
from .vision.ocr import OcrClient
from .adapters.mia_embedder import EmbeddingCache, MiaEmbedder
from .core.retriever import RetrievalPolicy
from .tools.analytics import ANALYTICS_PROMPT_RULES, AnomalyDetectTool, ChangePointsTool, LeadLagTool
from .tools.web import (
    WEB_PROMPT_RULES, WEB_SEARCH_PROMPT_RULES, WEB_SEARCH_UNAVAILABLE_RULES, WebSearchTool, WebUrlTool,
)
from .web.search import TavilySearch


WORKSPACE_QUERY_RULES = """

SOHBETTE KALAN ANALİZ:
web_url ile yüklenen ya da elde olan aktif tabloyu satır filtrelemek, sıralamak, gruplayıp toplamak \
için workspace_query kullan (tablo adı `t`); veri havuzuna yazmaz. Varsayılan BAKIŞ modudur, aktif \
tablo değişmez; kullanıcının bundan sonra üzerinde çalışacağı tabloyu üretiyorsan (ör. yıl aralığına \
kırpma) as_active_table=true ver. Özet, toplam, "en yüksek hangisi" gibi sorular için bakış modu yeter."""

ARCHITECT_PROMPT_RULES = """

ARCHITECT AKIŞI (yeni veri):
1) Kullanıcı bir dosya/adres verip 'ekle' derse ingest_from_url → TASLAK seri (adhoc). Araç birim ya da \
ölçüm tipini soruyorsa kullanıcıya sor; kullanıcı söyleyince aynı aracı unit/measure_type/default_agg \
alanlarıyla yeniden çağır, uydurma. 2) Taslak sorgulanabilir ama Gold'a giremez. Kullanıcı 'onaylıyorum, \
kataloğa al' derse promote_draft → aktif seri, Silver'a kopyalanır. 3) Onaylanmış seri de doğrulanmamış \
sayılır: gold_* araçları reddederse kullanıcıya 'doğrulanmamış olsa da kullanayım mı' diye sor; \
'doğrulanmamış olsa da kullan' derse aynı aracı yeniden çağır."""


BUILD_HINT = "veri kurmak için: `make demo-data` (repo kökünde) ya da `uv run python scripts/build_demo_data.py`"


def open_lakehouse(path, *, gold: GoldCLI | None = None, mode: str = "auto") -> SilverLakehouse | DuckDBLakehouse:
    """Veritabanının şemasına göre adaptörü seçer; mod sessiz düşüşü engeller (M01, ADR-0049).

    demo: Silver şeması şart. DB yoksa ya da şema seed ise açık nedenle durur; seed'e düşmez.
    seed: geliştirme seed'i (DuckDBLakehouse). auto: Silver'ı dene, yoksa seed (testler, eski davranış).
    Şemayı ayrı bağlantıyla yoklamıyoruz: DuckDB aynı dosyaya farklı yapılandırmayla ikinci
    bağlantıyı reddediyor; Silver adaptörünü kurmayı deniyoruz.
    """
    path = Path(path)
    if mode not in {"demo", "seed", "auto"}:
        raise LakehouseError(f"LAKEHOUSE_MODE geçersiz: {mode!r} (demo | seed | auto)")
    if mode == "seed":
        return DuckDBLakehouse(path)
    if mode == "demo" and not path.exists():
        raise LakehouseError(f"LAKEHOUSE_MODE=demo: veritabanı yok: {path}. {BUILD_HINT}. "
                             "Geliştirme seed'i istiyorsan LAKEHOUSE_MODE=seed.")
    try:
        return SilverLakehouse(path, gold=gold)
    except LakehouseError as exc:
        if "meta.series" not in str(exc) and "silver.fact_observation" not in str(exc):
            raise
        if mode == "demo":
            raise LakehouseError(f"LAKEHOUSE_MODE=demo: {path} Silver şeması taşımıyor (meta.series / "
                                 f"silver.fact_observation yok); bu bir seed ya da bozuk dosya. {BUILD_HINT}.") from exc
        return DuckDBLakehouse(path)


PROFILES = ("analyst", "architect")


def architect_enabled(profile: str, *, silver: bool, cli: bool) -> bool:
    """Architect araçları yalnız architect profilinde VE veri ekibinin şeması + CLI'ı varken (M04-T02).
    Analyst'te araç kayıt defterine hiç girmez: kapı değil, yokluk — model adıyla çağırsa UNKNOWN_TOOL."""
    return profile == "architect" and silver and cli


def build_agent(max_steps: int = 10, profile: str | None = None) -> AnalyticsAgent:
    """Motoru kurar. Yeni araçlar buraya eklenir; agent kodu değişmez."""
    settings = load_settings()
    agent_profile_name = (profile or settings.agent_profile or "analyst").lower()
    if agent_profile_name not in PROFILES:
        raise ValueError(f"AGENT_PROFILE geçersiz: {agent_profile_name!r} (analyst | architect)")
    # Veri ekibinin Silver şeması varsa ona bağlan; yoksa kendi BDDK seed'imize.
    # Gerçek Lakehouse geldiğinde değişen tek şey LAKEHOUSE_PATH olur.
    system_prompt_extra = ""
    # Salt-okunur Gold çağrısı veri ekibinin `gold-run` komutuyla (ADR-0031); CLI yoksa
    # adaptör hazır gold.* tablolarını yine gösterir, gold_* araçları kayıt edilmez.
    gold = GoldCLI(
        core_dir=settings.lakehouse_core_dir,
        database=settings.lakehouse_path,
        launcher=settings.lakehouse_cli,
    )
    lakehouse = open_lakehouse(settings.lakehouse_path, gold=gold if gold.available else None, mode=settings.lakehouse_mode)
    workspace = AnalysisWorkspace()

    # Alan profili katalogdan deterministik olarak türetilir; üslup tercihleri
    # (.env'deki DOMAIN_DESCRIPTION / DOMAIN_AUDIENCE) varsa onlar geçerlidir.
    def profile_factory() -> DomainProfile:
        return DomainProfile.from_catalog(
            lakehouse.list_datasets(), domain=settings.domain_description, audience=settings.domain_audience,
        )

    profile = profile_factory()

    # Retrieval kademesi (ADR-0043): politika ayarlardan; hybrid için MIA embedder + disk önbelleği.
    policy = RetrievalPolicy(mode=settings.retrieval_mode, small_max=settings.retrieval_small_max,
                             hybrid_min=settings.retrieval_hybrid_min)
    lakehouse.retrieval_policy = policy
    if settings.embedding_model and settings.retrieval_mode in ("auto", "hybrid"):
        lakehouse.embedder = MiaEmbedder(base_url=settings.llm_base_url, api_key=settings.llm_api_key,
                                         model=settings.embedding_model)
        lakehouse.embedding_cache = EmbeddingCache(settings.embedding_cache_dir)
    registry = ToolRegistry(profile)
    # Görüntü/PDF girişi (ADR-0041): OCR istemcisi yalnız VISION_MODEL varsa; yoksa belgeler "okunamadı" der.
    ocr = OcrClient(base_url=settings.llm_base_url, api_key=settings.llm_api_key, model=settings.vision_model) \
        if settings.vision_model else None
    gold_cli = GoldCLI(
        core_dir=settings.lakehouse_core_dir, database=settings.lakehouse_path, launcher=settings.lakehouse_cli,
    )
    gold_on = isinstance(lakehouse, SilverLakehouse) and gold_cli.available
    registry.register_all(
        [
            LakehouseSearchTool(lakehouse),
            LakehouseDescribeTool(lakehouse),
            LakehouseDistinctValuesTool(lakehouse),
            LakehouseQueryTool(lakehouse, workspace, registry, gold_available=gold_on),
            WorkspaceAddColumnTool(lakehouse, workspace),
            WorkspaceComputeColumnTool(workspace),
            WorkspaceShowTool(workspace),
            WorkspaceQueryTool(workspace),
            WorkspaceRealValueTool(lakehouse, workspace, registry=registry),   # M09: reel dönüşüm, Analyst yeteneği
            WorkspaceJoinTool(workspace),                    # M11: iki oturum tablosu anahtarla
            # Analitik ailesi (ADR-0040): LLM yok, her adaptörde; veri ne olursa olsun aynı.
            AnomalyDetectTool(workspace),
            ChangePointsTool(workspace),
            LeadLagTool(workspace),
        ]
    )
    # Architect'e açılan tek kapı. Yalnız veri ekibinin şeması ve CLI'ı varsa: seed
    # adaptöründe adhoc/draft sözleşmesi yok, kapı da yok.
    cli = LakehouseCLI(
        core_dir=settings.lakehouse_core_dir,
        database=settings.lakehouse_path,
        data_root=settings.lakehouse_path.parent,
        launcher=settings.lakehouse_cli,
    )
    if architect_enabled(agent_profile_name, silver=isinstance(lakehouse, SilverLakehouse), cli=cli.available):
        settings.ingest_allowed_root.mkdir(parents=True, exist_ok=True)
        registry.register(
            IngestFromUrlTool(lakehouse, cli, allowed_root=settings.ingest_allowed_root, registry=registry, ocr=ocr)
        )
        registry.register(PromoteDraftTool(lakehouse, cli, registry=registry))
        # K02-T12 (A30): yüklü aralık dışını kayıtlı kaynağından çekme — yalnız Architect, aynı CLI kapısından.
        from .tools.ingest_source import IngestSourceTool
        registry.register(IngestSourceTool(lakehouse, cli, registry=registry))
        system_prompt_extra = ARCHITECT_PROMPT_RULES

    # Grafik her adaptörde var: veri aktif tablodan gelir, kural araçta (ADR-0032).
    registry.register(
        ChartTool(lakehouse, workspace, chart_dir=settings.chart_dir, geo_dir=settings.geo_dir)
    )
    system_prompt = SYSTEM_PROMPT + CHART_PROMPT_RULES + WORKSPACE_QUERY_RULES + ANALYTICS_PROMPT_RULES + REAL_VALUE_PROMPT_RULES
    # Dış kaynak (ADR-0034): web_url her zaman; web_search yalnız arama anahtarı varsa.
    settings.ingest_allowed_root.mkdir(parents=True, exist_ok=True)
    registry.register(WebUrlTool(workspace, allowed_local_root=settings.ingest_allowed_root, registry=registry, ocr=ocr))
    system_prompt += WEB_PROMPT_RULES
    search = TavilySearch()
    if search.available:
        registry.register(WebSearchTool(search, registry=registry))
        system_prompt += WEB_SEARCH_PROMPT_RULES
    else:
        system_prompt += WEB_SEARCH_UNAVAILABLE_RULES
    if isinstance(lakehouse, GoldCapable) and getattr(lakehouse, "gold", None) is not None:
        registry.register_all(
            [
                GoldAlignTool(lakehouse, workspace, registry=registry),
                GoldDecomposeTool(lakehouse, workspace, registry=registry),
                GoldJoinTool(lakehouse, workspace, registry=registry),
            ]
        )
        # Kural prompt'a yalnız araçlar varken girer: olmayan aracı öğütlemek UNKNOWN_TOOL üretir.
        system_prompt = system_prompt + GOLD_PROMPT_RULES
    system_prompt = system_prompt + system_prompt_extra

    if settings.llm_key_missing:
        raise SystemExit(f"Model anahtarı yok: LLM_API_KEY boş ({settings.llm_base_url}). .env dosyasını doldurun, sonra make preflight.")
    llm = OpenAICompatClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        disable_thinking=settings.disable_thinking, timeout=settings.llm_timeout)
    print(
        f"[motor] sağlayıcı={settings.provider_label} model={settings.llm_model} "
        f"alan={profile.domain!r} araçlar={len(registry)} profil={agent_profile_name}",
        file=sys.stderr,
    )
    # Ön-yükleme: soruya göre seçilen k serinin kartı + gerçek kırılım değerleri, bütçeyle.
    preloader = None
    if settings.preload_budget_tokens > 0:
        def preloader(question: str):
            return build_question_context(
                lakehouse, question, budget_tokens=settings.preload_budget_tokens, k=settings.preload_k,
                retrieval_mode=settings.retrieval_mode, small_max=settings.retrieval_small_max,
            )
    agent = AnalyticsAgent(
        llm, registry, workspace=workspace, max_steps=max_steps, profile=profile,
        system_prompt=system_prompt, evidence=EvidenceBuilder(lakehouse), preloader=preloader,
        tool_gate=settings.tool_gate, narrate_temperature=settings.narrate_temperature,
        profile_factory=profile_factory,
        max_tokens=settings.llm_max_tokens, time_budget_s=settings.agent_time_budget_s,
    )
    agent.profile_name = agent_profile_name          # analyst | architect (M04)
    agent.upload_root = settings.ingest_allowed_root
    return agent


def main() -> None:
    parser = argparse.ArgumentParser(description="KKB Agentic Analytics Engine")
    parser.add_argument("question", nargs="*", help="Sorulacak soru")
    parser.add_argument("--trace", action="store_true", help="Araç çağrılarını göster")
    parser.add_argument("--evidence", action="store_true",
                        help="Kanıt panelini göster: sayı → SQL → gözlem → artifact → RAW/URL")
    parser.add_argument("--max-steps", type=int, default=10)
    parser.add_argument("--health", action="store_true", help="Lakehouse durumunu göster")
    parser.add_argument("--preflight", action="store_true", help="Salt-okunur ön kontrol: mod, DB, şema, veri, CLI, dizinler, anahtarlar (M01)")
    parser.add_argument("--live", action="store_true", help="--preflight ile: MIA'ya bir deneme çağrısı da yap")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.preflight:
        from .preflight import run_preflight, render
        checks = run_preflight(load_settings(), live=args.live)
        print(render(checks))
        sys.exit(0 if all(c.ok or not c.required for c in checks) else 1)

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
            if result.context:
                print(result.context)
            if result.usage:
                print(f"token: prompt {result.usage.get('prompt', 0)} · completion {result.usage.get('completion', 0)} · {result.usage.get('calls', 0)} çağrı")
            print("---")
        print(f"\n{result.text}\n")
        for art in result.artifacts:
            print(f"[grafik] {art.get('png_path') or art.get('spec_path')}")
        if result.evidence is not None:
            print(f"[kanıt] {result.evidence.summary()}")
            if args.evidence:
                print("\n--- kanıt paneli ---")
                print(result.evidence.render())
                print("---")
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
