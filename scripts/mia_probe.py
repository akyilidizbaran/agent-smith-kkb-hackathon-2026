"""MIA capability probe — measures what the deployment actually supports (see docs/ARCHITECTURE_V3.md §5, E1–E3).

Usage:
    MIA_API_KEY=... python scripts/mia_probe.py --out docs/mia_capability_matrix.md
    python scripts/mia_probe.py --only parallel_tools,thinking_tools,prefix_cache
    python scripts/mia_probe.py --image sample.png --ocr page1.png

Rules:
  * Nothing is assumed; every row is measured.
  * Raw HTTP (httpx) so unsupported parameters surface as real API errors.
  * The key is read from MIA_API_KEY (or LLM_API_KEY) and never printed.
  * OCR call follows the MIA Hackathon Rehberi verbatim (prompt "<image>\\ndocument parsing",
    skip_special_tokens=False, vllm_xargs ngram_size/window_size, base64 only).
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    print("pip install httpx", file=sys.stderr)
    raise

BASE_URL = os.getenv("MIA_BASE_URL", os.getenv("LLM_BASE_URL", "https://mia.csp.kloudeks.com/v1")).rstrip("/")
API_KEY = os.getenv("MIA_API_KEY") or os.getenv("LLM_API_KEY")
CHAT_MODEL = os.getenv("LLM_MODEL", "kkbhackathon2026/Qwen3.8-27B")
EMB_MODEL = os.getenv("EMBEDDING_MODEL", "kkbhackathon2026/Qwen3-Embedding-8B")
OCR_MODEL = os.getenv("OCR_MODEL", "kkbhackathon2026/Unlimited-OCR")
TIMEOUT = float(os.getenv("MIA_TIMEOUT", "180"))

THINK_RE = re.compile(r"<think>.*?</think>", re.S)
TOOL_XML_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)
NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}


@dataclass
class Row:
    capability: str
    result: str
    detail: str = ""
    impact: str = ""


@dataclass
class Report:
    rows: list[Row] = field(default_factory=list)

    def add(self, cap: str, result: str, detail: str = "", impact: str = "") -> None:
        self.rows.append(Row(cap, result, detail, impact))
        print(f"[{result:^8}] {cap} — {detail}")

    def markdown(self) -> str:
        out = ["# MIA Capability Matrix (measured)", "", f"- base_url: `{BASE_URL}`", f"- chat: `{CHAT_MODEL}`",
               f"- embedding: `{EMB_MODEL}`", f"- ocr: `{OCR_MODEL}`", f"- generated: {time.strftime('%Y-%m-%d %H:%M:%S')}", "",
               "| Capability | Result | Detail | Architecture impact |", "|---|---|---|---|"]
        for r in self.rows:
            out.append(f"| {r.capability} | {r.result} | {r.detail.replace('|', '/')} | {r.impact} |")
        return "\n".join(out) + "\n"


def client() -> httpx.Client:
    if not API_KEY:
        sys.exit("MIA_API_KEY (or LLM_API_KEY) is not set. Put it in .env, never in code.")
    return httpx.Client(base_url=BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=TIMEOUT)


def chat(c: httpx.Client, messages: list[dict], **extra: Any) -> tuple[int, dict, float]:
    body = {"model": CHAT_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 800}
    body.update(extra)
    t0 = time.perf_counter()
    r = c.post("/chat/completions", json=body)
    dt = time.perf_counter() - t0
    try:
        payload = r.json()
    except Exception:
        payload = {"_raw": r.text[:500]}
    return r.status_code, payload, dt


def msg_of(payload: dict) -> dict:
    try:
        return payload["choices"][0]["message"]
    except Exception:
        return {}


def content_of(payload: dict) -> str:
    return msg_of(payload).get("content") or ""


def reasoning_of(payload: dict) -> str | None:
    m = msg_of(payload)
    return m.get("reasoning_content") or m.get("reasoning")


def extract_json(text: str) -> Any:
    text = THINK_RE.sub("", text).strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no json object")
    return json.loads(text[start:end + 1])


TOOLS = [
    {"type": "function", "function": {"name": "get_series", "description": "Katalogdan bir zaman serisini getirir.",
                                      "parameters": {"type": "object", "properties": {"series_id": {"type": "string"},
                                                                                       "start": {"type": "string"}, "end": {"type": "string"}},
                                                     "required": ["series_id", "start", "end"]}}},
    {"type": "function", "function": {"name": "search_web", "description": "İnternette kaynak arar.",
                                      "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["new_analysis", "extend_workspace", "explain", "external_lookup", "ingest_url", "out_of_scope", "clarify"]},
        "goal": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "tool": {"type": "string"}, "args": {"type": "object"}}, "required": ["id", "tool", "args"]}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent", "goal", "steps", "assumptions"],
}

SYSTEM_JSON = (
    "Sen bir veri analizi planlayıcısısın. YALNIZCA geçerli bir JSON nesnesi döndür; açıklama, markdown, kod bloğu yok. "
    "Şema: {intent: string, goal: string, steps: [{id, tool, args}], assumptions: [string]}. "
    "Kullanılabilir tool'lar: search_series, get_series, align, deflate, pct_change, plot_timeseries."
)

QUESTIONS = [
    "2021-2025 arasında aylık konut kredisi bakiyesi ile konut kredisi faiz oranını karşılaştır.",
    "Tabloyu bozmadan konut kredisi tutarlarını enflasyondan arındır.",
    "Konut fiyat endeksini yeni sütun olarak ekle.",
    "Katılım bankalarının KOBİ kredileri 2024'te yıllık ne kadar büyüdü?",
    "BIST100 endeksinin son 12 aylık değişimini göster.",
    "Kredi kartı harcamalarında mevsimsellik var mı?",
    "Bugün hava nasıl?",
    "Faiz düştüğü halde kredilerin artmadığı dönemler var mı?",
    "'Kredi bakiyesi'ni göster.",
    "TL mevduat faizi ile politika faizi arasındaki gecikmeli ilişkiyi incele.",
]


# ----------------------------------------------------------------------------- tests

def test_models(c: httpx.Client, rep: Report) -> None:
    r = c.get("/models")
    if r.status_code != 200:
        rep.add("GET /models", "FAIL", f"HTTP {r.status_code}: {r.text[:120]}", "Model adlarını env'den oku")
        return
    ids = [m.get("id") for m in r.json().get("data", [])]
    rep.add("GET /models", "OK", ", ".join(map(str, ids))[:200], "Model adları doğrulandı" if CHAT_MODEL in ids else "LLM_MODEL adı listede yok!")


def test_thinking(c: httpx.Client, rep: Report) -> None:
    msgs = [{"role": "user", "content": "Türkiye'nin başkenti neresidir? Tek kelime."}]
    code, p, dt = chat(c, msgs)
    if code != 200:
        rep.add("Basic chat", "FAIL", f"HTTP {code}: {json.dumps(p)[:200]}", "Endpoint/anahtar kontrol")
        return
    txt = content_of(p)
    rep.add("Basic chat", "OK", f"{dt:.1f}s usage={p.get('usage')}", "")
    rep.add("Thinking default", "OK", f"<think> in content={'<think>' in txt}; reasoning field={reasoning_of(p) is not None}",
            "Varsayılan davranış kaydedildi")
    for label, extra in [("chat_template_kwargs.enable_thinking=false", NO_THINK),
                         ("reasoning_effort=none", {"reasoning_effort": "none"}),
                         ("reasoning_effort=low", {"reasoning_effort": "low"})]:
        code2, p2, dt2 = chat(c, msgs, **extra)
        if code2 != 200:
            rep.add(label, "REJECT", f"HTTP {code2}: {json.dumps(p2)[:140]}", "Alternatif anahtarı kullan")
        else:
            t2 = content_of(p2)
            off = "<think>" not in t2 and not reasoning_of(p2)
            rep.add(label, "OK", f"{dt2:.1f}s thinking_off={off} usage={p2.get('usage')}", "Araç turları için kullanılabilir" if off else "Thinking kapanmadı")


def test_second_system(c: httpx.Client, rep: Report) -> None:
    msgs = [{"role": "system", "content": "Kısa cevap ver."}, {"role": "user", "content": "Merhaba."},
            {"role": "system", "content": "Workspace: v2, kolonlar: period_end, bakiye."}, {"role": "user", "content": "Kaç kolon var?"}]
    code, p, _ = chat(c, msgs, **NO_THINK)
    rep.add("Second system message", "OK" if code == 200 else "REJECT", f"HTTP {code}: {json.dumps(p)[:120]}",
            "Workspace durumu ilk system mesajına gömülmeli" if code != 200 else "Çoklu system kabul ediliyor")


def test_tools(c: httpx.Client, rep: Report) -> None:
    code, p, dt = chat(c, [{"role": "user", "content": "evds:TP.KTF10 serisini 2021-01-01..2025-12-31 getir. get_series aracını kullan."}],
                       tools=TOOLS, tool_choice="auto", **NO_THINK)
    if code != 200:
        rep.add("tools / tool_choice", "REJECT", f"HTTP {code}: {json.dumps(p)[:160]}", "Prompt-tabanlı action")
        return
    tc = msg_of(p).get("tool_calls")
    xml = TOOL_XML_RE.findall(content_of(p))
    if tc:
        rep.add("tools / tool_choice", "OK", f"{dt:.1f}s tool_calls={json.dumps(tc)[:160]}", "Native tool calling kullanılabilir")
    elif xml:
        rep.add("tools / tool_choice", "WEAK", f"tool_calls boş; content'te {len(xml)} <tool_call> XML", "Gateway XML fallback parse etmeli")
    else:
        rep.add("tools / tool_choice", "WEAK", f"tool_calls yok; content={content_of(p)[:120]!r}", "Prompt-tabanlı action")


def test_parallel_tools(c: httpx.Client, rep: Report) -> None:
    """E1: does one turn return several tool_calls?"""
    sysmsg = ("Bir veri analizi ajanısın. Birbirinden bağımsız tüm araç çağrılarını AYNI turda, ayrı tool_call'lar olarak ver; "
              "önce birini çağırıp sonucu beklemek yerine hepsini birden çağır.")
    q = ("Konut kredisi bakiyesi (bddk_monthly:KONUT:10001:TL) ve konut kredisi faizi (evds:TP.KTF10) serilerini 2021-01-01..2025-12-31 "
         "için getir ve aynı anda 'TCMB kredi büyüme sınırı 2024' konusunu web'de ara.")
    counts = []
    for _ in range(3):
        code, p, dt = chat(c, [{"role": "system", "content": sysmsg}, {"role": "user", "content": q}], tools=TOOLS, tool_choice="auto", **NO_THINK)
        if code != 200:
            rep.add("Parallel tool_calls (E1)", "FAIL", f"HTTP {code}", "")
            return
        tc = msg_of(p).get("tool_calls") or []
        xml = TOOL_XML_RE.findall(content_of(p))
        counts.append(len(tc) or len(xml))
    rep.add("Parallel tool_calls (E1)", "OK" if min(counts) >= 2 else "WEAK", f"calls per turn over 3 runs={counts}",
            "Paralel executor tur sayısını düşürür" if min(counts) >= 2 else "Tek çağrı/tur → kompozit araçlara yaslan")


def test_thinking_tools(c: httpx.Client, rep: Report) -> None:
    """E2: thinking on + tools → are tool_calls still parsed?"""
    q = "evds:TP.KTF10 serisini 2022-01-01..2022-12-31 getir. get_series aracını kullan."
    for label, extra in [("thinking=false", NO_THINK), ("thinking=default", {})]:
        code, p, dt = chat(c, [{"role": "user", "content": q}], tools=TOOLS, tool_choice="auto", **extra)
        if code != 200:
            rep.add(f"Thinking+tools ({label})", "FAIL", f"HTTP {code}", "")
            continue
        tc = msg_of(p).get("tool_calls") or []
        xml = TOOL_XML_RE.findall(content_of(p))
        rep.add(f"Thinking+tools ({label})", "OK" if tc else ("WEAK" if xml else "FAIL"),
                f"{dt:.1f}s tool_calls={len(tc)} xml_in_content={len(xml)} reasoning={reasoning_of(p) is not None}",
                "Araç turlarında thinking kapalı kuralı" if not tc and label == "thinking=default" else "")


def test_prefix_cache(c: httpx.Client, rep: Report) -> None:
    """E3: same ~6k-token prefix, different suffix → does prefill time drop after the first call?"""
    prefix = "".join(f"series_id: evds:TP.X{i} | name_tr: Örnek seri {i} | unit: pct | frequency: monthly | coverage: 2021-01..2026-06\n"
                     for i in range(220))
    lat = []
    for i in range(5):
        code, p, dt = chat(c, [{"role": "system", "content": "Katalogdan soruya en uygun series_id'yi tek satırda döndür.\n" + prefix},
                               {"role": "user", "content": f"Soru {i}: örnek seri {17 + i}"}], max_tokens=20, **NO_THINK)
        if code == 200:
            lat.append(dt)
    if len(lat) < 3:
        rep.add("Prefix caching (E3)", "FAIL", "yeterli ölçüm yok", "")
        return
    first, rest = lat[0], statistics.median(lat[1:])
    gain = 1 - rest / first
    rep.add("Prefix caching (E3)", "OK" if gain >= 0.3 else "WEAK", f"first={first:.2f}s median_rest={rest:.2f}s gain={gain:.0%}",
            "Sabit önek düzeni değerli" if gain >= 0.3 else "Prefix caching kapalı görünüyor; prompt'u kısalt")


def test_system_message(c: httpx.Client, rep: Report) -> None:
    ok, n = 0, 10
    for i in range(n):
        code, p, _ = chat(c, [{"role": "system", "content": "Yalnızca büyük harfle ve tek kelimeyle cevap ver."},
                              {"role": "user", "content": f"{i + 3} artı {i + 4} kaç eder? Sayıyı yazıyla yaz."}], **NO_THINK)
        txt = THINK_RE.sub("", content_of(p)).strip()
        if code == 200 and txt and txt == txt.upper() and len(txt.split()) <= 2:
            ok += 1
    rep.add("System message adherence", "OK" if ok >= 9 else "WEAK", f"{ok}/{n}", "Prompt tasarımı")


def test_json_reliability(c: httpx.Client, rep: Report, trials: int = 30) -> None:
    raw_ok = repaired_ok = 0
    latencies = []
    for i in range(trials):
        q = QUESTIONS[i % len(QUESTIONS)]
        code, p, dt = chat(c, [{"role": "system", "content": SYSTEM_JSON}, {"role": "user", "content": q}], **NO_THINK)
        latencies.append(dt)
        if code != 200:
            continue
        txt = content_of(p)
        try:
            json.loads(THINK_RE.sub("", txt).strip())
            raw_ok += 1
            repaired_ok += 1
            continue
        except Exception:
            pass
        try:
            obj = extract_json(txt)
            if isinstance(obj, dict) and "steps" in obj:
                repaired_ok += 1
        except Exception:
            pass
    med = statistics.median(latencies) if latencies else 0
    rep.add("JSON reliability (prompt-only)", "OK" if repaired_ok / trials >= 0.93 else "WEAK",
            f"raw {raw_ok}/{trials}, after extract {repaired_ok}/{trials}, median {med:.1f}s", "Prompt-only JSON fallback kalitesi")


def test_response_format(c: httpx.Client, rep: Report) -> None:
    msgs = [{"role": "system", "content": SYSTEM_JSON}, {"role": "user", "content": QUESTIONS[0]}]
    for label, rf in [("response_format=json_object", {"type": "json_object"}),
                      ("response_format=json_schema", {"type": "json_schema", "json_schema": {"name": "AnalysisPlan", "schema": PLAN_SCHEMA, "strict": True}})]:
        code, p, dt = chat(c, msgs, response_format=rf, **NO_THINK)
        if code != 200:
            rep.add(label, "REJECT", f"HTTP {code}: {json.dumps(p)[:140]}", "Prompt-only JSON")
            continue
        try:
            obj = json.loads(THINK_RE.sub("", content_of(p)).strip())
            good = all(k in obj for k in PLAN_SCHEMA["required"]) if "schema" in label else True
            rep.add(label, "OK" if good else "WEAK", f"{dt:.1f}s keys={list(obj)[:6]}", "Structured output kullanılabilir" if good else "Şema zorlanmıyor")
        except Exception:
            rep.add(label, "WEAK", "kabul edildi ama JSON değil", "Yok sayılıyor")


def test_long_prompt(c: httpx.Client, rep: Report, approx_tokens: int = 30000) -> None:
    line = "series_id: evds:TP.X{i} | name_tr: Örnek seri {i} | unit: pct | frequency: monthly | coverage: 2021-01..2026-06\n"
    catalog = "".join(line.format(i=i) for i in range(approx_tokens // 30))
    catalog += "series_id: evds:TP.KTF10 | name_tr: Konut kredisi faiz oranı (haftalık, ağırlıklı ort.) | unit: pct | frequency: weekly\n"
    code, p, dt = chat(c, [{"role": "system", "content": "Aşağıdaki katalogda soruya en uygun series_id'yi tek satırda döndür."},
                           {"role": "user", "content": catalog + "\nSoru: konut kredisi faizi"}], max_tokens=50, **NO_THINK)
    if code != 200:
        rep.add("Long prompt (~30k tok)", "FAIL", f"HTTP {code}: {json.dumps(p)[:160]}", "Retrieval şart")
    else:
        found = "TP.KTF10" in content_of(p)
        rep.add("Long prompt (~30k tok)", "OK" if found else "WEAK", f"{dt:.1f}s usage={p.get('usage')} found={found}", "Katalog özeti token eşiği (E8) buradan kalibre edilir")


def test_latency_concurrency(c: httpx.Client, rep: Report) -> None:
    msgs = [{"role": "user", "content": "1'den 5'e kadar say."}]
    lat = []
    for _ in range(5):
        code, _, dt = chat(c, msgs, max_tokens=40, **NO_THINK)
        if code == 200:
            lat.append(dt)
    rep.add("Latency short (n=5)", "OK" if lat else "FAIL", f"p50={statistics.median(lat):.2f}s max={max(lat):.2f}s" if lat else "no success", "Tur sabit maliyeti")

    def one(_: int) -> tuple[int, float]:
        code, _, dt = chat(c, msgs, max_tokens=40, **NO_THINK)
        return code, dt

    with cf.ThreadPoolExecutor(5) as ex:
        res = list(ex.map(one, range(5)))
    codes = [r[0] for r in res]
    rep.add("Concurrency 5 parallel", "OK" if all(x == 200 for x in codes) else "WEAK", f"codes={codes} max={max(r[1] for r in res):.2f}s",
            "429 varsa semafor 2")


def test_determinism(c: httpx.Client, rep: Report) -> None:
    outs = set()
    for _ in range(5):
        code, p, _ = chat(c, [{"role": "user", "content": "Bir finansal zaman serisi için üç kalite kontrolü listele, her biri en fazla 5 kelime."}],
                          temperature=0, seed=42, max_tokens=80, **NO_THINK)
        if code == 200:
            outs.add(THINK_RE.sub("", content_of(p)).strip())
    rep.add("Determinism (T=0, seed=42, n=5)", "OK" if len(outs) == 1 else "WEAK", f"{len(outs)} distinct outputs", "pass^k ölçümünde tolerans")


def test_error_format(c: httpx.Client, rep: Report) -> None:
    r = c.post("/chat/completions", json={"model": "does-not-exist", "messages": [{"role": "user", "content": "x"}]})
    rep.add("Error format (bad model)", "OK", f"HTTP {r.status_code}: {r.text[:160]} headers={ {k: v for k, v in r.headers.items() if 'limit' in k.lower()} }",
            "Error taxonomy; rate-limit header var mı")


def test_embeddings(c: httpx.Client, rep: Report) -> None:
    texts = ["Instruct: Türkçe finansal veri sorusu için eşleşen zaman serisi metadata'sını bul\nQuery: konut kredisi faizi",
             "series: Konut kredisi faiz oranı (TL, haftalık, ağırlıklı ortalama) | aliases: mortgage faizi, ev kredisi faizi",
             "series: Konut fiyat endeksi (2023=100) | aliases: KFE, ev fiyatları"]
    t0 = time.perf_counter()
    r = c.post("/embeddings", json={"model": EMB_MODEL, "input": texts, "encoding_format": "float"})
    dt = time.perf_counter() - t0
    if r.status_code != 200:
        rep.add("Embeddings basic", "FAIL", f"HTTP {r.status_code}: {r.text[:160]}", "Lexical-only; lokal bge-m3 fallback")
        return
    vecs = [d["embedding"] for d in r.json()["data"]]

    def cos(a, b):
        num = sum(x * y for x, y in zip(a, b))
        return num / ((sum(x * x for x in a) ** 0.5) * (sum(x * x for x in b) ** 0.5))

    s1, s2 = cos(vecs[0], vecs[1]), cos(vecs[0], vecs[2])
    rep.add("Embeddings basic", "OK", f"dim={len(vecs[0])} {dt:.1f}s sim(faiz)={s1:.3f} sim(KFE)={s2:.3f}", "Doğru seri daha yakın" if s1 > s2 else "Ayrım zayıf → alias/reranker")
    r2 = c.post("/embeddings", json={"model": EMB_MODEL, "input": texts[:1], "dimensions": 1024})
    if r2.status_code == 200:
        d = len(r2.json()["data"][0]["embedding"])
        rep.add("Embeddings dimensions=1024 (MRL)", "OK" if d == 1024 else "WEAK", f"dim={d}", "Depolama 4x küçülür")
    else:
        rep.add("Embeddings dimensions=1024 (MRL)", "REJECT", f"HTTP {r2.status_code}", "4096 sakla ya da client-side kes+normalize")
    r3 = c.post("/embeddings", json={"model": EMB_MODEL, "input": [f"series {i}: örnek seri açıklaması {i}" for i in range(64)]})
    rep.add("Embeddings batch=64", "OK" if r3.status_code == 200 else "WEAK", f"HTTP {r3.status_code}", "Index build batch boyutu")


def _img_b64(path: str) -> str:
    data = Path(path).read_bytes()
    ext = Path(path).suffix.lower().lstrip(".") or "png"
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def test_vision(c: httpx.Client, rep: Report, image: str) -> None:
    code, p, dt = chat(c, [{"role": "user", "content": [{"type": "text", "text": "Bu görselde ne var? Bir cümle."},
                                                        {"type": "image_url", "image_url": {"url": _img_b64(image)}}]}], max_tokens=120, **NO_THINK)
    rep.add("Vision (1 image, base64)", "OK" if code == 200 else "FAIL", f"HTTP {code} {dt:.1f}s {content_of(p)[:100]!r}", "Görsel yorum opsiyonel")


def test_ocr(c: httpx.Client, rep: Report, image: str) -> None:
    """Verbatim MIA Hackathon Rehberi format: images first, then '<image>\\ndocument parsing'; extra_body per guide."""
    body = {"model": OCR_MODEL, "temperature": 0.0, "max_tokens": 8192,
            "skip_special_tokens": False, "vllm_xargs": {"ngram_size": 35, "window_size": 128},
            "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": _img_b64(image)}},
                                                      {"type": "text", "text": "<image>\ndocument parsing"}]}]}
    t0 = time.perf_counter()
    r = c.post("/chat/completions", json=body)
    dt = time.perf_counter() - t0
    if r.status_code != 200:
        rep.add("OCR (Unlimited-OCR, 1 page)", "FAIL", f"HTTP {r.status_code}: {r.text[:160]}", "Rehber formatını kontrol et")
        return
    txt = content_of(r.json())
    rep.add("OCR (Unlimited-OCR, 1 page)", "OK" if txt else "WEAK", f"{dt:.1f}s chars={len(txt)} ref={txt.count('<|ref|>')} det={txt.count('<|det|>')}",
            "Yerleşim etiketleri konum bilgisidir; tablo kurarken kullan")


def test_streaming(c: httpx.Client, rep: Report) -> None:
    body = {"model": CHAT_MODEL, "messages": [{"role": "user", "content": "1'den 3'e say."}], "stream": True, "max_tokens": 30, **NO_THINK}
    chunks = 0
    try:
        with c.stream("POST", "/chat/completions", json=body) as r:
            if r.status_code != 200:
                rep.add("Streaming (SSE)", "REJECT", f"HTTP {r.status_code}", "UI non-stream")
                return
            for line in r.iter_lines():
                if line.startswith("data:"):
                    chunks += 1
        rep.add("Streaming (SSE)", "OK" if chunks > 1 else "WEAK", f"{chunks} chunks", "Cevap turu UI'da akıtılabilir (algılanan hız)")
    except Exception as e:  # noqa: BLE001
        rep.add("Streaming (SSE)", "FAIL", str(e)[:120], "UI non-stream")


TESTS = {
    "models": test_models,
    "thinking": test_thinking,
    "second_system": test_second_system,
    "tools": test_tools,
    "parallel_tools": test_parallel_tools,
    "thinking_tools": test_thinking_tools,
    "prefix_cache": test_prefix_cache,
    "system": test_system_message,
    "json": test_json_reliability,
    "response_format": test_response_format,
    "long": test_long_prompt,
    "latency": test_latency_concurrency,
    "determinism": test_determinism,
    "errors": test_error_format,
    "embeddings": test_embeddings,
    "streaming": test_streaming,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/mia_capability_matrix.md")
    ap.add_argument("--only", default="", help="comma-separated subset of: " + ",".join(TESTS))
    ap.add_argument("--image", default="", help="image file for the vision test")
    ap.add_argument("--ocr", default="", help="page image (PNG) for the OCR test")
    args = ap.parse_args()

    rep = Report()
    selected = [s.strip() for s in args.only.split(",") if s.strip()] or list(TESTS)
    with client() as c:
        for name in selected:
            try:
                TESTS[name](c, rep)
            except Exception as e:  # noqa: BLE001
                rep.add(name, "ERROR", f"{type(e).__name__}: {str(e)[:140]}", "İncele")
        if args.image:
            test_vision(c, rep, args.image)
        if args.ocr:
            test_ocr(c, rep, args.ocr)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(rep.markdown(), encoding="utf-8")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
