"""Arayüz — FastAPI ile ajanı saran ince katman (D9, ADR-0044).

Yeni mantık yok: `build_agent` ne üretiyorsa onu JSON'a çevirir. Tek oturum, tek ajan; sorular
sırayla (kilit) çalışır çünkü ajan tek workspace taşır. Cevap nesnesi olduğu gibi serileştirilir:
metin, adımlar (rol, araç, hata), aktif tablo, grafik PNG'leri, kanıt paneli, token kullanımı,
araç kapısı kararı. Arayüz kanıtı ve izi gizlemez; jürinin göreceği şey harness'in kendisidir.

    uv run python -m kkb_agent.serve          # http://127.0.0.1:8765
"""

from __future__ import annotations

import base64
import json
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_ROWS = 200


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat() if (value.hour, value.minute, value.second) == (0, 0, 0) else value.isoformat(timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value != value:
        return None
    if is_dataclass(value) and not isinstance(value, type):
        return {k: _json_safe(v) for k, v in asdict(value).items()}
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return _json_safe(value.item())
        except Exception:  # noqa: BLE001
            return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def frame_to_dict(frame: pd.DataFrame | None, *, max_rows: int = MAX_ROWS) -> dict[str, Any] | None:
    if frame is None or frame.empty:
        return None
    head = frame.head(max_rows)
    rows = [[_json_safe(v) for v in row] for row in head.itertuples(index=False, name=None)]
    return {"columns": [str(c) for c in frame.columns], "rows": rows, "row_count": int(len(frame)),
            "truncated": len(frame) > max_rows}


def _png_base64(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if p.suffix.lower() != ".png" or not p.is_file():
        return None
    return base64.b64encode(p.read_bytes()).decode("ascii")


def evidence_to_dict(panel: Any) -> dict[str, Any] | None:
    if panel is None:
        return None
    return {
        "summary": panel.summary() if hasattr(panel, "summary") else str(panel),
        "complete": bool(getattr(panel, "complete", False)),
        "numbers": [_json_safe(n) for n in getattr(panel, "numbers", [])],
        "columns": [_json_safe(c) for c in getattr(panel, "columns", [])],
        "observations": [_json_safe(o) for o in list(getattr(panel, "observations", []))[:12]],
        "observation_count": len(getattr(panel, "observations", [])),
        "artifacts": _json_safe(getattr(panel, "artifacts", {})),
        "web_sources": _json_safe(getattr(panel, "web_sources", [])),
        "web_unused": _json_safe(getattr(panel, "web_unused", [])),
        "consulted_unused": list(getattr(panel, "consulted_unused", [])),
        "gaps": list(getattr(panel, "gaps", [])),
        "table_rows": int(getattr(panel, "table_rows", 0) or 0),
    }


DATA_TOOLS_PREFIX = ("lakehouse_query", "workspace_", "anomaly_detect", "change_points", "lead_lag", "gold_", "ingest")


def _table_touched(answer: Any, before: Any, after: Any) -> bool:
    """Tablo bu cevapta üretildi ya da ele alındı mı? Aksi hâlde eski tablo cevaba iliştirilmez."""
    if after is None:
        return False
    if before is not after:
        return True
    return any(s.tool_name and s.ok and s.tool_name.startswith(DATA_TOOLS_PREFIX) for s in getattr(answer, "steps", []))


def answer_to_dict(answer: Any, agent: Any, *, table_before: Any = None) -> dict[str, Any]:
    steps = []
    for s in getattr(answer, "steps", []):
        steps.append({
            "index": s.index, "role": s.role, "thought": s.thought, "tool": s.tool_name,
            "args": _json_safe(s.tool_args), "ok": bool(s.ok), "error_code": s.error_code,
            "summary": (s.result_summary or "")[:400], "duration_ms": round(float(getattr(s, "duration_ms", 0.0) or 0.0)),
        })
    charts = []
    for art in getattr(answer, "artifacts", []) or []:
        if not isinstance(art, dict) or art.get("kind") == "web":
            continue
        png = _png_base64(art.get("png_path"))
        if png or art.get("spec_path"):
            charts.append({"png": png, "title": art.get("title"), "kind": art.get("kind"), "spec_path": art.get("spec_path"),
                           "lint_ok": art.get("lint_ok"), "lint": _json_safe(art.get("lint"))})
    table = getattr(agent.workspace, "table", None)
    show_table = _table_touched(answer, table_before, table)
    gate = getattr(agent, "last_gate", None)
    search = getattr(getattr(agent.registry.get("web_search"), "search", None), "remaining", None) if agent.registry.get("web_search") else None
    return {
        "text": answer.text,
        "steps": steps,
        "table": frame_to_dict(table) if show_table else None,
        "table_title": (getattr(agent.workspace, "title", "") or "") if show_table else "",
        "charts": charts,
        "evidence": evidence_to_dict(getattr(answer, "evidence", None)),
        "usage": dict(getattr(answer, "usage", {}) or {}),
        "context": getattr(answer, "context", "") or "",
        "grounding": getattr(answer, "grounding", "") or "",
        "hit_step_limit": bool(getattr(answer, "hit_step_limit", False)),
        "gate": {"allowed": sorted(gate.allowed), "opened": list(gate.opened), "closed": list(gate.closed)} if gate else None,
        "search_budget_remaining": search,
    }


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class Session:
    """Tek ajan, sıralı sorular. `reset` ajanı yeniden kurar (temiz workspace)."""

    def __init__(self, agent_factory: Callable[[], Any]) -> None:
        self._factory = agent_factory
        self._lock = threading.Lock()
        self.agent = agent_factory()
        self.history: list[dict[str, Any]] = []
        self.answers: list[dict[str, Any]] = []   # tam cevap yükleri; sayfa yenilenince yeniden çizilir

    def ask(self, question: str) -> dict[str, Any]:
        with self._lock:
            started = time.perf_counter()
            table_before = getattr(self.agent.workspace, "table", None)
            answer = self.agent.ask(question)
            payload = answer_to_dict(answer, self.agent, table_before=table_before)
            payload["elapsed_s"] = round(time.perf_counter() - started, 1)
            payload["question"] = question
            payload["index"] = len(self.answers)
            self.history.append({"index": payload["index"], "question": question, "elapsed_s": payload["elapsed_s"],
                                 "steps": len([s for s in payload["steps"] if s["tool"]]),
                                 "evidence": (payload["evidence"] or {}).get("summary")})
            self.answers.append(payload)
            return payload

    def reset(self) -> None:
        with self._lock:
            self.agent = self._factory()
            self.history = []
            self.answers = []

    def status(self) -> dict[str, Any]:
        agent = self.agent
        lake = getattr(agent.registry.get("lakehouse_query"), "lakehouse", None)
        specs = []
        try:
            specs = list(lake.list_datasets()) if lake is not None else []
        except Exception:  # noqa: BLE001
            specs = []
        gold = sum(1 for s in specs if getattr(s, "source", "") == "gold")
        adhoc = sum(1 for s in specs if getattr(s, "source", "") == "adhoc")
        uningested = len(getattr(lake, "_uningested", {}) or {})
        silver_rows = None
        try:
            if lake is not None and hasattr(lake, "execute_sql"):
                res = lake.execute_sql("SELECT count(*) AS n FROM silver.fact_observation")
                frame = getattr(res, "data", None)
                if frame is not None and len(frame):
                    silver_rows = int(frame.iloc[0, 0])
        except Exception:  # noqa: BLE001
            silver_rows = None
        search_tool = agent.registry.get("web_search")
        return {
            "catalog_series": len(specs) - gold - adhoc + uningested,
            "loaded_series": len(specs) - gold - adhoc,
            "gold_tables": gold,
            "silver_rows": silver_rows,
            "retrieval_mode": getattr(lake, "retrieval_mode", None),
            "tools": agent.registry.names(),
            "tool_gate": bool(getattr(agent, "tool_gate", False)),
            "search_budget_remaining": getattr(getattr(search_tool, "search", None), "remaining", None) if search_tool else None,
            "model": getattr(agent.llm, "model", None),
            "history": self.history,
        }


def create_app(agent_factory: Callable[[], Any]) -> FastAPI:
    app = FastAPI(title="Agent Smith", docs_url=None, redoc_url=None)
    session = Session(agent_factory)
    app.state.session = session
    # Yerel dosyalar (three.js vb.); CDN yok, demo çevrimdışı da çalışır (ADR-0047).
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/favicon.ico")
    def favicon():
        from fastapi.responses import FileResponse
        return FileResponse(STATIC_DIR / "agent-smith.svg", media_type="image/svg+xml")

    @app.get("/api/status")
    def status() -> JSONResponse:
        return JSONResponse(_json_safe(session.status()))

    @app.post("/api/ask")
    def ask(req: AskRequest) -> JSONResponse:
        try:
            payload = session.ask(req.question.strip())
        except Exception as exc:  # noqa: BLE001 — arayüz düşmez, hata görünür
            raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc
        return JSONResponse(_json_safe(payload))

    @app.get("/api/answers")
    def answers() -> JSONResponse:
        """Oturumdaki tüm cevaplar (tam yük): sayfa yenilenince sohbet yeniden kurulur."""
        return JSONResponse(_json_safe(session.answers))

    @app.get("/api/answers/{index}")
    def answer(index: int) -> JSONResponse:
        if index < 0 or index >= len(session.answers):
            raise HTTPException(status_code=404, detail="böyle bir cevap yok")
        return JSONResponse(_json_safe(session.answers[index]))

    @app.post("/api/reset")
    def reset() -> JSONResponse:
        session.reset()
        return JSONResponse({"ok": True})

    return app


def build_default_app() -> FastAPI:
    from .cli import build_agent

    return create_app(lambda: build_agent(max_steps=12))


__all__ = ["AskRequest", "Session", "answer_to_dict", "build_default_app", "create_app", "evidence_to_dict", "frame_to_dict"]
