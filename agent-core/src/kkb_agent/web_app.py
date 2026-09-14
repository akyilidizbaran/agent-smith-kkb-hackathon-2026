"""Arayüz — FastAPI ile ajanı saran ince katman (D9, ADR-0044).

Yeni mantık yok: `build_agent` ne üretiyorsa onu JSON'a çevirir. Tek oturum, tek ajan; sorular
sırayla (kilit) çalışır çünkü ajan tek workspace taşır. Cevap nesnesi olduğu gibi serileştirilir:
metin, adımlar (rol, araç, hata), aktif tablo, grafik PNG'leri, kanıt paneli, token kullanımı,
araç kapısı kararı. Arayüz kanıtı ve izi gizlemez; jürinin göreceği şey harness'in kendisidir.

    uv run python -m kkb_agent.serve          # http://127.0.0.1:8765
"""

from __future__ import annotations

from dataclasses import dataclass

import base64
import json
import re
import shutil
import threading
import time
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Literal

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_ROWS = 200

# Dosya girişi (M10, ADR-0054): desteklenen türler ve sınır. Legacy .xls bilerek yok (xlrd yok);
# .html/.htm dosyası web_url ile açılır (tablo çıkarımı orada). Kullanıcının yerel yolu sunucuya gelmez:
# dosya oturuma özel dizine güvenli adla yazılır, ajana verilen yol o kopyadır.
UPLOAD_KINDS = {".csv": "tablo", ".tsv": "tablo", ".txt": "tablo", ".xlsx": "tablo (Excel)", ".xlsm": "tablo (Excel)",
                ".json": "tablo (JSON)", ".pdf": "belge (OCR)", ".png": "görsel (OCR)", ".jpg": "görsel (OCR)",
                ".jpeg": "görsel (OCR)", ".webp": "görsel (OCR)"}
UPLOAD_REFUSED = {".xls": "eski Excel (.xls) desteklenmiyor; dosyayı .xlsx olarak kaydedin",
                  ".html": "HTML dosyası için sayfa adresini verin ya da tabloyu CSV olarak kaydedin",
                  ".htm": "HTML dosyası için sayfa adresini verin ya da tabloyu CSV olarak kaydedin",
                  ".doc": "Word desteklenmiyor; tabloyu CSV/XLSX ya da PDF olarak verin",
                  ".docx": "Word desteklenmiyor; tabloyu CSV/XLSX ya da PDF olarak verin"}
UPLOAD_MAX_BYTES = 25 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    base = Path(name or "dosya").name
    base = _SAFE_NAME.sub("_", base).strip("._") or "dosya"
    return base[:80]


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.date().isoformat() if (value.hour, value.minute, value.second) == (0, 0, 0) else value.isoformat(timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None   # NaN ve ±sonsuz: JSON'da yeri yok; "hesaplanamadı" olarak boş (M14-T08)
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
        "states": panel.states() if hasattr(panel, "states") else {},
        "inspected_rows": int(getattr(panel, "inspected_rows", 0) or 0),
        "numbers": [_json_safe(n) for n in getattr(panel, "numbers", [])],
        "columns": [_json_safe(c) for c in getattr(panel, "columns", [])],
        "observations": [{**_json_safe(o), "chain_state": getattr(o, "chain_state", None), "raw_present": getattr(o, "raw_present", None),
                          "bronze_present": getattr(o, "bronze_present", None)} if isinstance(_json_safe(o), dict) else _json_safe(o)
                         for o in list(getattr(panel, "observations", []))[:12]],
        "chain_breakdown": panel.chain_breakdown() if hasattr(panel, "chain_breakdown") else {},
        "observation_count": len(getattr(panel, "observations", [])),
        "artifacts": _json_safe(getattr(panel, "artifacts", {})),
        "web_sources": _json_safe(getattr(panel, "web_sources", [])),
        "web_unused": _json_safe(getattr(panel, "web_unused", [])),
        "context_sources": _json_safe(getattr(panel, "context_sources", [])),
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


ACCESS_CODES = frozenset({"NEEDS_CREDENTIAL", "ACCESS_BLOCKED", "SOURCE_NOT_FOUND"})
ACCESS_KINDS = ("upload_file", "use_credential", "alternative_source", "retry_later")


def access_options(answer: Any) -> list[str]:
    """Son erişim hatasının seçenekleri (M06-T10): arayüz bunları eyleme bağlar; seçenek sunmak yetki vermez."""
    for s in reversed(getattr(answer, "steps", []) or []):
        if getattr(s, "error_code", None) in ACCESS_CODES:
            return [k for k in dict.fromkeys(getattr(s, "candidates", []) or []) if k in ACCESS_KINDS]
    return []


def answer_to_dict(answer: Any, agent: Any, *, table_before: Any = None) -> dict[str, Any]:
    steps = []
    for s in getattr(answer, "steps", []):
        steps.append({
            "index": s.index, "role": s.role, "thought": s.thought, "tool": s.tool_name,
            "args": _json_safe(s.tool_args), "ok": bool(s.ok), "error_code": s.error_code,
            "summary": (s.result_summary or "")[:400], "duration_ms": round(float(getattr(s, "duration_ms", 0.0) or 0.0)),
            "candidates": list(getattr(s, "candidates", []) or []),
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
    ev = getattr(answer, "evidence", None)
    sources = [str(src) for c in (getattr(ev, "columns", []) or []) for src in (getattr(c, "sources", []) or [])]
    if not sources:
        scope = None
    elif any(src.startswith("web") for src in sources):
        scope = "oturum verisi (dosya/sayfa; ortak havuza yazılmadı)"
    else:
        scope = "ortak veri havuzu"
    gate = getattr(agent, "last_gate", None)
    search = getattr(getattr(agent.registry.get("web_search"), "search", None), "remaining", None) if agent.registry.get("web_search") else None
    return {
        "text": answer.text,
        "steps": steps,
        "table": frame_to_dict(table) if show_table else None,
        "table_title": (getattr(agent.workspace, "title", "") or "") if show_table else "",
        "table_scope": scope if show_table else None,
        "access_options": access_options(answer),
        "charts": charts,
        "evidence": evidence_to_dict(getattr(answer, "evidence", None)),
        "usage": dict(getattr(answer, "usage", {}) or {}),
        "context": getattr(answer, "context", "") or "",
        "grounding": getattr(answer, "grounding", "") or "",
        "hit_step_limit": bool(getattr(answer, "hit_step_limit", False)),
        "gate": {"allowed": sorted(gate.allowed), "opened": list(gate.opened), "closed": list(gate.closed)} if gate else None,
        "search_budget_remaining": search,
    }


# ---------------------------------------------------------------- dışa aktarım (M14, ADR-0055)
def table_csv_bytes(frame: pd.DataFrame) -> bytes:
    """Türkçe Excel'in doğrudan açtığı biçim: UTF-8 BOM, ';' ayraç, ',' ondalık; tarih ISO. Tam tablo."""
    out = frame.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    return ("\ufeff" + out.to_csv(index=False, sep=";", decimal=",", lineterminator="\n")).encode("utf-8")


def table_xlsx_bytes(frame: pd.DataFrame, *, title: str = "Tablo", warnings: list[str] | None = None) -> bytes:
    """Gerçek sayı ve tarih hücreleri; ikinci sayfada uyarılar ve kaynak notu (formül hücresi yazılmaz)."""
    import io
    buf = io.BytesIO()
    out = frame.copy()
    for c in out.columns:   # ±sonsuz Excel'e giremez; boş bırakılır
        if pd.api.types.is_numeric_dtype(out[c]):
            out[c] = out[c].replace([float("inf"), float("-inf")], None)
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        out.to_excel(w, sheet_name="tablo", index=False)
        notes = pd.DataFrame({"not": [title, *(warnings or []), f"dışa aktarım {datetime.now():%Y-%m-%d %H:%M}"]})
        notes.to_excel(w, sheet_name="notlar", index=False)
    return buf.getvalue()


def _md_to_html(md: str) -> str:
    """Küçük ve kaçırılmış Markdown → HTML (paragraf, kalın, madde, boru tablosu); rapor için."""
    import html as _h
    lines = _h.escape(md or "").split("\n")
    out: list[str] = []
    i = 0
    def inline(t: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    while i < len(lines):
        l = lines[i]
        if l.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
            head, body = rows[0], rows[2:]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(h)}</th>" for h in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body) + "</tbody></table>")
            continue
        if re.match(r"^\s*[-*]\s", l):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s", "", lines[i])); i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
            continue
        if not l.strip():
            i += 1; continue
        para = []
        while i < len(lines) and lines[i].strip() and not re.match(r"^\s*[-*]\s|^\s*\|", lines[i]):
            para.append(lines[i]); i += 1
        out.append(f"<p>{inline(' '.join(para))}</p>")
    return "".join(out)


def report_html(payload: dict[str, Any], frame: pd.DataFrame | None, *, model: str = "", version: str = "") -> str:
    """Tek dosya HTML rapor: soru, cevap, varsayım/uyarılar, TAM tablo, grafikler (gömülü), kanıt durumu,
    kaynaklar. Rapor cevabın sürümüne bağlıdır; uyarılar dışa aktarımda kaybolmaz (M14-T06/T07)."""
    import html as _h
    ev = payload.get("evidence") or {}
    q = _h.escape(payload.get("question", "").split("\n\nDosya:")[0])
    warns: list[str] = list(ev.get("gaps") or [])
    for c in ev.get("columns") or []:
        warns += list(c.get("warnings") or [])
    for n in ev.get("numbers") or []:
        if n.get("sign_warning"):
            warns.append(f"{n.get('text')}: tabloda ters işaret")
        if n.get("from_question") and not n.get("matched"):
            warns.append(f"{n.get('text')}: sorudan geliyor, tabloda yok (doğrulanmadı)")
    states = ev.get("states") or {}
    charts = "".join(f'<figure><img alt="grafik" src="data:image/png;base64,{c["png"]}"><figcaption>{_h.escape(c.get("title") or "")}</figcaption></figure>'
                     for c in payload.get("charts") or [] if c.get("png"))
    table_html = ""
    if frame is not None and len(frame):
        show = frame.copy()
        for c in show.columns:
            if pd.api.types.is_datetime64_any_dtype(show[c]):
                show[c] = show[c].dt.strftime("%Y-%m-%d")
        table_html = show.to_html(index=False, na_rep="", border=0, classes="data", float_format=lambda v: f"{v:,.4f}".rstrip("0").rstrip("."))
    srcs = []
    for c in ev.get("columns") or []:
        srcs += [str(x) for x in (c.get("sources") or [])]
    for w in ev.get("web_sources") or []:
        srcs.append(f"{w.get('url')} · sha256 {str(w.get('sha256') or '')[:16]}… · {w.get('fetched_at') or ''}")
    for w in ev.get("context_sources") or []:
        srcs.append(f"bağlam (web araması, veri değil): {w.get('url')} · {w.get('title') or ''} · arama '{w.get('query') or ''}'")
    obs = ev.get("observations") or []
    if obs:
        o = obs[0]
        srcs.append(f"{ev.get('observation_count', len(obs))} gözlem → artifact {str(o.get('artifact_sha256') or '')[:16]}… · {o.get('locator') or ''} · çekim {o.get('fetched_at') or ''}")
    srcs = list(dict.fromkeys(srcs))
    css = ("body{font-family:'IBM Plex Sans',Arial,sans-serif;max-width:960px;margin:32px auto;padding:0 20px;color:#1f1d1a;background:#fff}"
           "h1{font-size:20px}h2{font-size:15px;letter-spacing:.06em;text-transform:uppercase;color:#6b665d;margin-top:28px}"
           "table.data{border-collapse:collapse;font-size:13px}table.data th,table.data td{border:1px solid #e3ded4;padding:4px 10px;text-align:right}"
           "table.data th:first-child,table.data td:first-child{text-align:left}.warn{background:#fff8e8;border:1px solid #e3c98f;padding:10px 12px;border-radius:6px}"
           ".ok{color:#0a4f49}.gap{color:#a35a00}figure{margin:12px 0}img{max-width:100%}.meta{font-size:12px;color:#8a8478}")
    state_html = " · ".join(f'<span class="{"ok" if v else "gap"}">{_h.escape(k)} {"✓" if v else "✗"}</span>' for k, v in states.items())
    return (f"<!doctype html><html lang='tr'><head><meta charset='utf-8'><title>Agent Smith raporu</title><style>{css}</style></head><body>"
            f"<h1>Agent Smith — analiz raporu</h1><div class='meta'>{_h.escape(datetime.now().strftime('%Y-%m-%d %H:%M'))} · cevap #{payload.get('index')} · model {_h.escape(model)} · sürüm {_h.escape(version)}</div>"
            f"<h2>Soru</h2><p>{q}</p>"
            f"<h2>Cevap</h2>{_md_to_html(payload.get('text', ''))}"
            + (f"<h2>Uyarılar ve varsayımlar</h2><div class='warn'><ul>{''.join(f'<li>{_h.escape(w)}</li>' for w in warns)}</ul></div>" if warns else "")
            + (f"<h2>Tablo ({len(frame)} satır{' · ' + _h.escape(payload.get('table_scope') or '') if payload.get('table_scope') else ''})</h2>{table_html}" if table_html else "")
            + (f"<h2>Grafik</h2>{charts}" if charts else "")
            + (f"<h2>Kanıt zinciri</h2><p>{_h.escape(ev.get('summary', ''))}</p><p>{state_html}</p>" if ev else "")
            + (f"<h2>Kaynaklar</h2><ul>{''.join(f'<li>{_h.escape(x)}</li>' for x in srcs)}</ul>" if srcs else "")
            + "</body></html>")


def _git_version() -> str:
    try:
        import subprocess
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5,
                              cwd=str(Path(__file__).resolve().parents[2])).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)


class ProfileRequest(BaseModel):
    profile: str = Field(pattern="^(analyst|architect)$")
    token: str = Field(default="", max_length=200)


class ResetRequest(BaseModel):
    confirm: str = Field(default="", max_length=64)
    # D04 (ADR-0069): sıfırlama sonrası katalog; varsayılan BOŞ. Başlangıç kataloğunu geri yüklemek ayrı açık seçimdir.
    catalog: Literal["bos", "varsayilan"] = "bos"


# ---------------------------------------------------------------- Architect tam sıfırlama (M04-T06, ADR-0056; D04/D05, ADR-0069)
@dataclass
class ResetPaths:
    """Sıfırlamanın bildiği bütün veri yolları — sabit liste değil, yapılandırmadan (D05-T01). Kod, kurulum ve .env yok."""

    data_root: Path
    db_path: Path
    upload_root: Path | None = None       # oturum yüklemeleri (INGEST_ALLOWED_ROOT/uploads)
    chart_dir: Path | None = None         # CHART_DIR
    cache_dir: Path | None = None         # EMBEDDING_CACHE_DIR'in bulunduğu önbellek kökü

    @classmethod
    def from_settings(cls, s: Any) -> "ResetPaths":
        cache = Path(s.embedding_cache_dir)
        return cls(data_root=Path(s.data_root), db_path=Path(s.lakehouse_path), upload_root=Path(s.ingest_allowed_root) / "uploads",
                   chart_dir=Path(s.chart_dir), cache_dir=cache.parent if cache.name == "embeddings" else cache)

    def candidates(self) -> list[tuple[str, Path]]:
        root = self.data_root
        items = [
            ("veritabanı", self.db_path), ("veritabanı WAL", Path(str(self.db_path) + ".wal")),
            ("RAW", root / "raw"), ("Bronze", root / "bronze"), ("Silver dosyaları", root / "silver"), ("karantina", root / "quarantine"),
            ("oturum yüklemeleri", self.upload_root or root / "incoming" / "uploads"),
            ("grafikler", self.chart_dir or root / "charts"), ("önbellek", self.cache_dir or root / "cache"),
        ]
        seen: set[str] = set()
        out = []
        for label, path in items:
            key = str(path.resolve()) if path.exists() else str(path.absolute())
            if key not in seen:
                seen.add(key)
                out.append((label, path))
        return out


@dataclass
class ResetPlan:
    targets: list[tuple[str, Path]]       # veri kökü altında ve mevcut → silinecek
    absent: list[tuple[str, Path]]        # veri kökü altında, şu an yok
    outside: list[tuple[str, Path]]       # yapılandırma veri kökü DIŞINI gösteriyor → sıfırlama reddedilir (D05-T02)
    catalog: str = "bos"

    def token(self) -> str:
        import hashlib
        body = "\n".join([*(str(p) for _, p in self.targets), "--dış--", *(str(p) for _, p in self.outside), "--katalog--", self.catalog])
        return hashlib.sha256(body.encode()).hexdigest()[:12]

    def to_json(self) -> dict[str, Any]:
        def rows(items):
            return [{"label": label, "path": str(p)} for label, p in items]
        return {"targets": [str(p) for _, p in self.targets], "target_details": rows(self.targets), "absent": rows(self.absent),
                "outside": rows(self.outside), "catalog": self.catalog}


def plan_reset(paths: ResetPaths, *, catalog: str = "bos") -> ResetPlan:
    root = paths.data_root.resolve()
    targets, absent, outside = [], [], []
    for label, p in paths.candidates():
        try:
            p.resolve().relative_to(root)
        except ValueError:
            if p.exists():
                outside.append((label, p))       # veri kökü dışındaki hiçbir şey silinmez; sessizce atlanmaz da
            continue
        (targets if (p.exists() or p.is_symlink()) else absent).append((label, p))
    return ResetPlan(targets=targets, absent=absent, outside=outside, catalog=catalog)


def plan_full_reset(data_root: Path, db_path: Path) -> list[Path]:
    """Geriye uyum: veri kökü altındaki mevcut hedefler (ADR-0056 imzası)."""
    return [p for _, p in plan_reset(ResetPaths(data_root=data_root, db_path=db_path)).targets]


def reset_token(targets: list[Path]) -> str:
    import hashlib
    return hashlib.sha256("\n".join(str(t) for t in targets).encode()).hexdigest()[:12]


def _verify_rebuilt(db_path: Path, catalog: str) -> dict[str, Any]:
    """D05-T06: yeniden kurulan DB boş/yeni mi? Seri sayısı ve kalıcı katalog kipi okunur; okunamazsa doğrulandı denmez."""
    if not db_path.exists():
        return {"ok": False, "detail": "veritabanı yeniden kurulmadı"}
    try:
        import duckdb
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            series = int(con.execute("SELECT count(*) FROM meta.series").fetchone()[0])
            try:
                row = con.execute("SELECT value FROM meta.lakehouse_setting WHERE key = 'series_catalog'").fetchone()
                mode = None if row is None else str(row[0])
            except Exception:  # noqa: BLE001 — eski şema: kip tablosu yok
                mode = None
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"yeni veritabanı okunamadı: {exc}"}
    expected_empty = catalog == "bos"
    ok = (series == 0 and mode == "none") if expected_empty else series > 0
    return {"ok": ok, "series": series, "catalog_mode": mode,
            "detail": ("boş katalog doğrulandı" if ok and expected_empty else "başlangıç kataloğu yüklendi" if ok
                       else f"beklenen {'boş' if expected_empty else 'dolu'} katalog değil (seri {series}, kip {mode})")}


def execute_full_reset(plan: ResetPlan | list[Path], data_root: Path, *, bootstrap: Callable[..., tuple[int, str]] | None = None,
                       db_path: Path | None = None, close_readers: Callable[[], None] | None = None) -> dict[str, Any]:
    """Onaylanmış planı uygular ve HER hedefin gerçek sonucunu döner (D05-T05): silindi / zaten yok / silinemedi / korunuyor."""
    if isinstance(plan, list):                           # geriye uyum
        plan = ResetPlan(targets=[("hedef", p) for p in plan], absent=[], outside=[])
    results: list[dict[str, Any]] = [{"label": label, "path": str(p), "status": "korunuyor", "detail": "veri kökü dışında"}
                                     for label, p in plan.outside]
    if plan.outside:
        return {"status": "reddedildi", "results": results, "removed": [], "failed": [],
                "bootstrap": {"ok": False, "detail": "çalıştırılmadı"}, "verify": {"ok": False, "detail": "çalıştırılmadı"},
                "catalog": plan.catalog}
    if close_readers is not None:
        close_readers()                                  # D05-T04: açık DuckDB okuyucuları silmeden önce kapanır
    for label, p in plan.targets:
        row = {"label": label, "path": str(p)}
        if not p.exists() and not p.is_symlink():
            results.append({**row, "status": "zaten yok"})
            continue
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as exc:
            results.append({**row, "status": "silinemedi", "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if p.exists():
            results.append({**row, "status": "silinemedi", "detail": "silme sonrası hâlâ var"})
        else:
            results.append({**row, "status": "silindi"})
    for label, p in plan.absent:
        results.append({"label": label, "path": str(p), "status": "zaten yok"})
    data_root.mkdir(parents=True, exist_ok=True)
    boot: dict[str, Any] = {"ok": True, "detail": "bootstrap çalıştırılmadı"}
    verify: dict[str, Any] = {"ok": True, "detail": "doğrulama yapılmadı (bootstrap yok)"}
    if bootstrap is not None:
        mode = "none" if plan.catalog == "bos" else "default"
        try:
            code, out = bootstrap(mode)
        except TypeError:                                # eski imza: katalog seçimi almayan geri çağrı
            code, out = bootstrap()
        boot = {"ok": code == 0, "detail": out.strip()[-400:], "catalog_mode": mode}
        if boot["ok"] and db_path is not None:
            verify = _verify_rebuilt(db_path, plan.catalog)
        elif not boot["ok"]:
            verify = {"ok": False, "detail": "bootstrap başarısız; veritabanı yeni durumda değil"}
    failed = [r for r in results if r["status"] == "silinemedi"]
    status = "tamamlandı" if not failed and boot["ok"] and verify["ok"] else "kısmi"
    return {"status": status, "results": results, "removed": [r["path"] for r in results if r["status"] == "silindi"],
            "failed": failed, "bootstrap": boot, "verify": verify, "catalog": plan.catalog}


def _close_agent_readers(agent: Any, db_path: Path | None) -> None:
    registry = getattr(agent, "registry", None)
    seen: set[int] = set()
    for tool in (list(registry) if registry is not None else []):
        lake = getattr(tool, "lakehouse", None)
        if lake is not None and id(lake) not in seen and hasattr(lake, "close"):
            seen.add(id(lake))
            try:
                lake.close()
            except Exception:  # noqa: BLE001
                pass
    try:
        from .adapters.duckdb_lakehouse import release_connections
        release_connections(db_path)
    except Exception:  # noqa: BLE001
        pass
    import gc
    gc.collect()


class Session:
    """Tek ajan, sıralı sorular. `reset` ajanı yeniden kurar (temiz workspace)."""

    def __init__(self, agent_factory: Callable[..., Any], *, profile: str = "analyst", architect_token: str = "") -> None:
        self._factory = agent_factory
        self._lock = threading.Lock()
        self.profile = profile
        self.architect_token = architect_token
        self.agent = self._build(profile)
        self.history: list[dict[str, Any]] = []
        self.answers: list[dict[str, Any]] = []   # tam cevap yükleri; sayfa yenilenince yeniden çizilir
        self.id = uuid.uuid4().hex[:8]
        self.uploads: list[dict[str, Any]] = []
        self.tables: dict[int, pd.DataFrame] = {}   # cevap sürümü → tam tablo (dışa aktarım önizlemeden değil)

    def _build(self, profile: str) -> Any:
        try:
            return self._factory(profile=profile)
        except TypeError:                 # sahte ajan fabrikaları profil almayabilir
            return self._factory()

    def switch_profile(self, profile: str, token: str) -> None:
        """Profil başlatmada seçilir; oturumda geçiş yalnız operatör anahtarıyla (istek parametresi yetki vermez)."""
        if not self.architect_token:
            raise HTTPException(status_code=403, detail="profil geçişi kapalı: ARCHITECT_TOKEN tanımlı değil; profil başlatmada seçilir (AGENT_PROFILE)")
        if profile == "architect" and token != self.architect_token:
            raise HTTPException(status_code=403, detail="Architect anahtarı yanlış")
        with self._lock:
            self.profile = profile
            self.agent = self._build(profile)
            self.history, self.answers, self.tables = [], [], {}

    @property
    def upload_dir(self) -> Path:
        root = getattr(self.agent, "upload_root", None)
        if root is None:
            tool = self.agent.registry.get("web_url")
            root = getattr(tool, "allowed_local_root", None)
        if root is None:
            root = Path.cwd() / "data" / "incoming"
        return Path(root) / "uploads" / self.id

    def save_upload(self, name: str, content: bytes) -> dict[str, Any]:
        suffix = Path(name or "").suffix.lower()
        if suffix in UPLOAD_REFUSED:
            raise HTTPException(status_code=415, detail=UPLOAD_REFUSED[suffix])
        if suffix not in UPLOAD_KINDS:
            raise HTTPException(status_code=415, detail=f"desteklenmeyen tür {suffix or '(uzantısız)'}; "
                                f"kabul: {', '.join(sorted(UPLOAD_KINDS))}")
        if not content:
            raise HTTPException(status_code=400, detail="dosya boş")
        if len(content) > UPLOAD_MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"dosya {UPLOAD_MAX_BYTES // (1024 * 1024)} MB sınırını aşıyor; "
                                "PDF ise yalnız gerekli sayfaları, tabloysa yalnız gerekli kolonları verin")
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        safe = safe_filename(name)
        target = self.upload_dir / f"{uuid.uuid4().hex[:8]}_{safe}"
        target.write_bytes(content)
        info = {"name": safe, "path": str(target), "size": len(content), "kind": UPLOAD_KINDS[suffix], "session": self.id}
        self.uploads.append(info)
        return info

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
            if payload.get("table") is not None and getattr(self.agent.workspace, "table", None) is not None:
                self.tables[payload["index"]] = self.agent.workspace.table.copy()
            return payload

    def reset(self) -> None:
        with self._lock:
            self.agent = self._build(self.profile)
            self.history = []
            self.answers = []
            shutil.rmtree(self.upload_dir, ignore_errors=True)   # oturum dosyaları geçicidir (M10-T12)
            self.uploads = []
            self.tables = {}
            self.id = uuid.uuid4().hex[:8]

    def status(self) -> dict[str, Any]:
        agent = self.agent
        lake = getattr(agent.registry.get("lakehouse_query"), "lakehouse", None)
        specs = []
        try:
            specs = list(lake.list_datasets()) if lake is not None else []
        except Exception:  # noqa: BLE001
            specs = []
        gold = sum(1 for s in specs if getattr(s, "source", "") == "gold")
        # K01-T07 bulgusu: onaylanıp aktif olan adhoc seri kataloğun parçasıdır; yalnız TASLAKLAR sayaç dışında kalır
        # (boş katalogdan yeni alan kurulunca sayaç 0 gösteriyordu).
        adhoc = sum(1 for s in specs if getattr(s, "source", "") == "adhoc"
                    and any("TASLAK" in str(n) for n in (getattr(s, "notes", None) or [])))
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
        ready = {}
        try:
            ready = lake.readiness() if lake is not None and hasattr(lake, "readiness") else {}
        except Exception:  # noqa: BLE001
            ready = {}
        return {
            "readiness": ready,
            "profile": self.profile,
            "profile_switch": bool(self.architect_token),
            "uploads": len(self.uploads),
            "upload_kinds": sorted(UPLOAD_KINDS),
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


def create_app(agent_factory: Callable[..., Any], *, profile: str = "analyst", architect_token: str = "",
               reset_paths: "ResetPaths | tuple[Path, Path] | None" = None, bootstrap: Callable[..., tuple[int, str]] | None = None) -> FastAPI:
    app = FastAPI(title="Agent Smith", docs_url=None, redoc_url=None)
    session = Session(agent_factory, profile=profile, architect_token=architect_token)
    app.state.session = session
    pending_reset: dict[str, str] = {}

    @app.post("/api/profile")
    def set_profile(req: ProfileRequest) -> JSONResponse:
        session.switch_profile(req.profile, req.token)
        return JSONResponse({"ok": True, "profile": session.profile})

    @app.post("/api/architect/reset")
    def architect_reset(req: ResetRequest) -> JSONResponse:
        """İki adım: önce kapsam önizlemesi + onay kodu (hedefler ve katalog seçimine bağlı); sonra aynı kodla silme,
        doğrulama ve boş katalogla yeniden kurulum. Yalnız Architect. (ADR-0056, ADR-0069)"""
        if session.profile != "architect":
            raise HTTPException(status_code=403, detail="tam sıfırlama yalnız Architect profilinde")
        if reset_paths is None:
            raise HTTPException(status_code=400, detail="sıfırlama yolları tanımlı değil")
        paths = reset_paths if isinstance(reset_paths, ResetPaths) else ResetPaths(data_root=reset_paths[0], db_path=reset_paths[1])
        plan = plan_reset(paths, catalog=req.catalog)
        token = plan.token()
        if not req.confirm:
            pending_reset["token"] = token
            return JSONResponse({**plan.to_json(), "confirm": token, "refused": bool(plan.outside),
                                 "excluded": "kod, kurulum dosyaları, .env ve sırlar kapsam dışı",
                                 "note": ("Silme geri alınamaz; eski cevapların kanıt zinciri kopar. "
                                          + ("Katalog BOŞ kurulacak; başlangıç kataloğu yüklenmez." if plan.catalog == "bos"
                                             else "Başlangıç kataloğu yeniden yüklenecek.")
                                          + (" Veri kökü dışını gösteren ayar var: sıfırlama yapılmaz." if plan.outside else ""))})
        if req.confirm != token or pending_reset.get("token") != token:
            raise HTTPException(status_code=409, detail="onay kodu eşleşmiyor ya da hedef listesi/katalog seçimi değişti; önizlemeyi yeniden al")
        if plan.outside:
            raise HTTPException(status_code=409, detail="veri kökü dışını gösteren ayar var: " + ", ".join(f"{l} {p}" for l, p in plan.outside))
        pending_reset.clear()
        with session._lock:                              # D05-T04: soru/yükleme ile eşzamanlı silme yok
            report = execute_full_reset(plan, paths.data_root, bootstrap=bootstrap, db_path=paths.db_path,
                                        close_readers=lambda: _close_agent_readers(session.agent, paths.db_path))
            session.history, session.answers, session.tables, session.uploads = [], [], {}, []
            session.id = uuid.uuid4().hex[:8]             # D05-T07: eski grafik/cevap bağlantıları geçersiz
            try:
                session.agent = session._build(session.profile)
                report["agent"] = {"ok": True, "detail": "ajan yeni veriyle kuruldu"}
            except Exception as exc:  # noqa: BLE001 — yeniden kurulum hatası başarı diye sunulmaz
                report["agent"] = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
                report["status"] = "kısmi"
        return JSONResponse(_json_safe(report))
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

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)) -> JSONResponse:
        """Dosya girişi: tür/boyut denetimi, oturuma özel güvenli ad; kullanıcının yerel yolu hiç görülmez."""
        content = await file.read()
        info = session.save_upload(file.filename or "", content)
        return JSONResponse(_json_safe(info))

    @app.get("/api/uploads")
    def uploads() -> JSONResponse:
        return JSONResponse(_json_safe(session.uploads))

    def _answer_or_404(index: int) -> dict[str, Any]:
        if index < 0 or index >= len(session.answers):
            raise HTTPException(status_code=404, detail="böyle bir cevap yok")
        return session.answers[index]

    @app.get("/api/answers/{index}/table.csv")
    def table_csv(index: int) -> Response:
        _answer_or_404(index)
        frame = session.tables.get(index)
        if frame is None:
            raise HTTPException(status_code=404, detail="bu cevabın tablosu yok")
        return Response(table_csv_bytes(frame), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="agent-smith-cevap-{index}.csv"'})

    @app.get("/api/answers/{index}/table.xlsx")
    def table_xlsx(index: int) -> Response:
        p = _answer_or_404(index)
        frame = session.tables.get(index)
        if frame is None:
            raise HTTPException(status_code=404, detail="bu cevabın tablosu yok")
        ev = p.get("evidence") or {}
        warns = list(ev.get("gaps") or []) + [w for c in ev.get("columns") or [] for w in (c.get("warnings") or [])]
        data = table_xlsx_bytes(frame, title=p.get("table_title") or p.get("question", "")[:120], warnings=warns)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="agent-smith-cevap-{index}.xlsx"'})

    @app.get("/api/answers/{index}/chart/{k}.png")
    def chart_png(index: int, k: int) -> Response:
        p = _answer_or_404(index)
        charts = [c for c in p.get("charts") or [] if c.get("png")]
        if k < 0 or k >= len(charts):
            raise HTTPException(status_code=404, detail="grafik yok")
        return Response(base64.b64decode(charts[k]["png"]), media_type="image/png",
                        headers={"Content-Disposition": f'attachment; filename="agent-smith-cevap-{index}-grafik-{k}.png"'})

    @app.get("/api/answers/{index}/report.html")
    def report(index: int) -> HTMLResponse:
        p = _answer_or_404(index)
        st = session.status()
        return HTMLResponse(report_html(p, session.tables.get(index), model=str(st.get("model") or ""), version=_git_version()))

    @app.post("/api/reset")
    def reset() -> JSONResponse:
        session.reset()
        return JSONResponse({"ok": True})

    return app


def build_default_app() -> FastAPI:
    from .cli import build_agent
    from .config import load_settings

    s = load_settings()

    def bootstrap(catalog_mode: str = "none") -> tuple[int, str]:
        import subprocess
        cmd = [*s.lakehouse_cli.split(), "-m", "lakehouse", "bootstrap", "--database", str(s.lakehouse_path), "--data-root", str(s.data_root),
               "--catalog", catalog_mode]
        proc = subprocess.run(cmd, cwd=str(s.lakehouse_core_dir), capture_output=True, text=True, timeout=600, check=False)
        return proc.returncode, proc.stdout + proc.stderr

    return create_app(lambda profile="analyst": build_agent(max_steps=12, profile=profile), profile=s.agent_profile,
                      architect_token=s.architect_token, reset_paths=ResetPaths.from_settings(s), bootstrap=bootstrap)


__all__ = ["AskRequest", "Session", "answer_to_dict", "build_default_app", "create_app", "evidence_to_dict", "frame_to_dict",
           "report_html", "table_csv_bytes", "table_xlsx_bytes"]
