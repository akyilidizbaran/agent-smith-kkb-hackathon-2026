"""Ön kontrol — salt-okunur (M01, ADR-0049).

Hiçbir şey indirmez, yazmaz, kurmaz: yalnız bakar ve söyler. Amaç "demo açıldı" ile "demo hazır"
arasındaki farkı görünür kılmak: hangi DB, hangi şema, kaç seri yüklü, Gold bayat mı, veri ekibinin
CLI'ı erişilebilir mi, izinli dosya kökü var mı, hangi anahtarlar mevcut (değerleri asla).
`python -m kkb_agent.cli --preflight` · çıkış kodu: zorunlu bir kontrol düşerse 1.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .adapters.lakehouse_cli import cli_available, subprocess_runner
from .config import Settings

REQUIRED_RELATIONS = ("meta.series", "silver.fact_observation")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _key_status(name: str) -> str:
    v = os.getenv(name, "")
    return "var" if v.strip() else "yok"


def _db_checks(settings: Settings) -> list[Check]:
    path = settings.lakehouse_path
    out: list[Check] = []
    if not path.exists():
        out.append(Check("veritabanı", False, f"{path} yok · veri kurmak için: make demo-data"))
        return out
    out.append(Check("veritabanı", True, f"{path} ({path.stat().st_size / 1e6:.1f} MB)"))
    try:
        import duckdb
        conn = duckdb.connect(str(path), read_only=True)
    except Exception as exc:  # noqa: BLE001
        out.append(Check("bağlantı", False, f"salt-okunur açılamadı: {exc}"))
        return out
    try:
        rels = {f"{s}.{t}" for s, t in conn.execute(
            "SELECT table_schema, table_name FROM information_schema.tables").fetchall()}
        missing = [r for r in REQUIRED_RELATIONS if r not in rels]
        if missing:
            out.append(Check("şema", False, f"eksik ilişki: {', '.join(missing)} · bu dosya Silver değil (seed?)"))
            return out
        out.append(Check("şema", True, "meta.series + silver.fact_observation var"))
        n_series = conn.execute("SELECT count(*) FROM meta.series").fetchone()[0]
        n_obs = conn.execute("SELECT count(*) FROM silver.fact_observation").fetchone()[0]
        loaded, start, end = conn.execute(
            "SELECT count(DISTINCT series_id), min(observation_date), max(observation_date) FROM silver.fact_observation").fetchone()
        out.append(Check("veri", n_obs > 0, f"katalog {n_series:,} seri · yüklü {loaded:,} seri · {n_obs:,} gözlem · {start} → {end}".replace(",", ".")))
        try:
            ver, defined, ready = conn.execute(
                "WITH l AS (SELECT DISTINCT series_id FROM silver.fact_observation) "
                "SELECT count(*) FILTER (WHERE semantic_confidence='verified'), "
                "count(*) FILTER (WHERE unit IS NOT NULL AND measure_type <> 'unknown'), "
                "count(*) FILTER (WHERE l.series_id IS NOT NULL AND semantic_confidence='verified' AND measure_type <> 'unknown') "
                "FROM meta.series s LEFT JOIN l USING (series_id) WHERE status <> 'deprecated'").fetchone()
            full_verified_coverage = ver == ready if ver else n_obs == 0
            out.append(Check(
                "hazır oluş",
                full_verified_coverage,
                f"anlamı doğrulanmış {ver:,} · birim+ölçüm tipi tanımlı {defined:,} · "
                f"yüklü {loaded:,} · doğrulanmış hazır {ready:,}/{ver:,} · Gold'a hazır {ready:,} "
                "(ayrı sayılar, birbirinin yerine geçmez)".replace(",", "."),
                required=settings.lakehouse_mode == "demo",
            ))
        except Exception:  # noqa: BLE001
            pass
        gold = sorted(r for r in rels if r.startswith("gold."))
        out.append(Check("gold", True, f"{len(gold)} tablo: {', '.join(g.split('.', 1)[1] for g in gold)}" if gold else "gold tablosu yok (make demo-data `gold` adımı)", required=False))
        try:
            n_runs = conn.execute("SELECT count(*) FROM meta.run").fetchone()[0]
            n_art = conn.execute("SELECT count(*) FROM meta.artifact").fetchone()[0]
            out.append(Check("provenance", n_art > 0, f"{n_art} artifact · {n_runs} run kaydı", required=False))
        except Exception:  # noqa: BLE001
            out.append(Check("provenance", False, "meta.artifact / meta.run okunamadı", required=False))
        raw = settings.data_root / "raw"
        bronze = settings.data_root / "bronze"
        out.append(Check("RAW/Bronze", raw.is_dir() and bronze.is_dir(),
                         f"{raw} {'var' if raw.is_dir() else 'YOK'} · {bronze} {'var' if bronze.is_dir() else 'YOK'} (kanıt zinciri dosyaya iner)", required=False))
    finally:
        conn.close()
    return out


def run_preflight(settings: Settings, *, live: bool = False) -> list[Check]:
    checks: list[Check] = []
    mode = settings.lakehouse_mode
    checks.append(Check("mod", mode in {"demo", "seed", "auto"}, f"LAKEHOUSE_MODE={mode}" + ("  ← demo değil: seed/auto sessizce seed açabilir" if mode != "demo" else "")))
    checks.append(Check("veri kökü", settings.data_root.is_dir(), str(settings.data_root)))
    checks += _db_checks(settings)
    core = settings.lakehouse_core_dir
    if not core.is_dir():
        checks.append(Check("lakehouse-core", False, f"{core} yok → Architect araçları (ingest, terfi, gold_*) kapalı"))
    else:
        if not cli_available(core):
            checks.append(Check("lakehouse-core", False, f"{core} içinde src/lakehouse/cli.py yok"))
        else:
            try:  # gerçekten çalışıyor mu: --help (salt-okunur, ağ yok)
                code, out, err = subprocess_runner([*settings.lakehouse_cli.split(), "-m", "lakehouse", "--help"], core, timeout=90)
                ok = code == 0 and "bootstrap" in out
                checks.append(Check("lakehouse-core", ok, f"{core} · CLI {'çalışıyor' if ok else 'ÇALIŞMIYOR: ' + (err or out).strip()[-160:]} ({settings.lakehouse_cli})"))
            except Exception as exc:  # noqa: BLE001
                checks.append(Check("lakehouse-core", False, f"CLI koşulamadı: {exc}"))
    root = settings.ingest_allowed_root
    checks.append(Check("izinli dosya kökü", root.is_dir(), f"{root} {'var' if root.is_dir() else 'yok → jüri dosyası buraya konur; make demo-data oluşturur'}"))
    checks.append(Check("grafik dizini", True, f"{settings.chart_dir} {'var' if settings.chart_dir.is_dir() else 'ilk grafikte oluşturulur'}", required=False))
    checks.append(Check("model", bool(settings.llm_model) and not settings.llm_key_missing,
                        f"{settings.llm_base_url} · {settings.llm_model} · anahtar {_key_status('LLM_API_KEY')}"
                        + (" → uzak model için LLM_API_KEY boş: arayüz başlamaz; .env'yi doldur" if settings.llm_key_missing else "")))
    checks.append(Check("yardımcı modeller", True, f"embedding {settings.embedding_model or '—'} · vision {settings.vision_model or '—'}", required=False))
    checks.append(Check("anahtarlar", True, f"MIA {_key_status('MIA_API_KEY')} · EVDS {_key_status('EVDS_API_KEY')} · Tavily {_key_status('TAVILY_API_KEY')} (yalnız var/yok)", required=False))
    if live:
        checks.append(_live_llm(settings))
    return checks


def _live_llm(settings: Settings) -> Check:
    try:
        from .llm.base import ChatMessage
        from .llm.openai_compat import OpenAICompatClient
        client = OpenAICompatClient(base_url=settings.llm_base_url, api_key=settings.llm_api_key, model=settings.llm_model,
                                    disable_thinking=settings.disable_thinking, timeout=30.0)
        r = client.chat([ChatMessage(role="user", content="Yalnız 'hazır' yaz.")], max_tokens=5)
        return Check("MIA canlı", bool(r.content), f"cevap: {r.content.strip()[:20]!r}")
    except Exception as exc:  # noqa: BLE001
        return Check("MIA canlı", False, f"{type(exc).__name__}: {str(exc)[:120]}")


def render(checks: list[Check]) -> str:
    lines = ["ÖN KONTROL (salt-okunur)"]
    for c in checks:
        mark = "✓" if c.ok else ("✗" if c.required else "!")
        lines.append(f"  {mark} {c.name:18} {c.detail}")
    failed = [c for c in checks if not c.ok and c.required]
    lines.append("SONUÇ: " + ("hazır" if not failed else "HAZIR DEĞİL — " + ", ".join(c.name for c in failed)))
    return "\n".join(lines)


__all__ = ["Check", "render", "run_preflight"]
