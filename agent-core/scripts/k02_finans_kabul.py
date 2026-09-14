"""K02-T02…T05 — finans akışı gerçek demo lakehouse'ta, gerçek araçlarla (A02, A03, A04, A05, A06, A07, A26).

Model çağrısı YOK: `build_default_app` ile gerçek web uygulaması, ajan döngüsü, araçlar, kanıt paneli ve dışa aktarım;
modelin yerine hangi aracı çağıracağı önceden yazılmış betik (`Scripted`, K01 ile aynı yöntem). Araç çağrıları M16 canlı
koşusunda modelin bu sorulara verdiği çağrıların aynısıdır (docs/experiments/acceptance_m16_2026-09-14_0219.json).
Beklenen değerler ajandan bağımsız olarak Silver'dan ayrı süreçte okunur. Asıl `data/` yalnız okunur: DB özeti önce/sonra.

    uv run python scripts/k02_finans_kabul.py --work /tmp/k02
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from scripts.k01_kabul import Report, db_query, sha256  # noqa: E402

LOAN, RATE, KFE, TUFE = "bddk_monthly:1534_Toplam", "evds:TP.KTF12", "evds:TP.KFE.TR", "evds:TP.TUKFIY2025.GENEL"
START, END = "2021-01-01", "2025-12-31"


def tr(v: float, d: int) -> str:
    return f"{v:,.{d}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    (work / "incoming").mkdir(parents=True)
    demo_db = REPO / "data" / "lakehouse.duckdb"
    os.environ.update({
        "DATA_ROOT": str(REPO / "data"), "LAKEHOUSE_PATH": str(demo_db), "INGEST_ALLOWED_ROOT": str(work / "incoming"),
        "CHART_DIR": str(work / "charts"), "EMBEDDING_CACHE_DIR": str(work / "cache"), "AGENT_PROFILE": "analyst",
        "LAKEHOUSE_MODE": "demo", "EMBEDDING_MODEL": "", "VISION_MODEL": "", "TOOL_GATE": "off", "LLM_NARRATE_TEMPERATURE": "0",
        "TAVILY_API_KEY": "k02-sahte-anahtar",       # web_search kayıtlı olsun ama gerçek anahtar süreçte olmasın; arama oturumu sahte
    })
    sys.path.insert(0, str(ROOT / "src"))
    import numpy as np
    import pandas as pd
    from fastapi.testclient import TestClient
    from openpyxl import load_workbook

    from kkb_agent.llm.base import LLMResponse, ToolCall
    from kkb_agent.web.search import TavilySearch
    from kkb_agent.web_app import build_default_app

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "agent-core/src"], capture_output=True, text=True, cwd=REPO).stdout.strip())
    rep = Report(meta={"commit": commit, "kaynak_agac_temiz": not dirty, "work": str(work), "at": datetime.now().isoformat(timespec="seconds"),
                       "model": "betikli (LLM çağrısı yok)", "demo_db": str(demo_db), "demo_db_sha256_once": sha256(demo_db)})
    print(f"K02 finans — commit {commit}{' (kaynak ağacı kirli)' if dirty else ''} · kök {work}")

    # ---------------------------------------------------------------- bağımsız beklenenler (ayrı süreç, salt okunur)
    def silver(sid: str, start: str, end: str) -> pd.Series:
        rows = db_query(demo_db, "SELECT CAST(observation_date AS VARCHAR), value FROM silver.fact_observation "
                                 "WHERE series_id = ? AND observation_date BETWEEN ? AND ? ORDER BY 1", [sid, start, end])
        return pd.Series([float(v) for _, v in rows], index=pd.to_datetime([d for d, _ in rows]))

    def month_end(s: pd.Series) -> pd.Series:
        return pd.Series(s.to_numpy(), index=s.index.to_timestamp(how="end").normalize())

    loan = silver(LOAN, START, END)
    weekly = silver(RATE, START, END)
    rate = month_end(weekly.groupby(weekly.index.to_period("M")).mean())
    tufe_all = silver(TUFE, "2000-01-01", "2100-01-01")
    tufe = pd.Series(tufe_all.to_numpy(), index=tufe_all.index.to_period("M"))
    kfe = silver(KFE, START, END)
    gold_meta = db_query(demo_db, "SELECT count(*), min(aggregation), max(aggregation), min(source_frequency), max(source_frequency) "
                                  "FROM gold.konut_faizi_aylik WHERE period_end BETWEEN ? AND ?", [START, END])[0]

    class Scripted:
        model = "k02-betik"

        def __init__(self, turns: list):
            self.turns = list(turns)

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            # Betik bittiyse görünür biçimde bitir: sessiz "Tamam." boş geçen kanıt denetimini gizler (ilk koşu bulgusu).
            return self.turns.pop(0) if self.turns else LLMResponse(content="BETIK_BITTI")

    n = 0

    def call(_tool: str, /, **arguments) -> LLMResponse:
        nonlocal n
        n += 1
        return LLMResponse(content="", tool_calls=[ToolCall(id=f"c{n}", name=_tool, arguments=arguments)])

    def say(text: str) -> LLMResponse:
        return LLMResponse(content=text)

    app = build_default_app()
    client = TestClient(app)
    agent = app.state.session.agent
    full: list[tuple[str, object]] = []                  # kart özeti arayüzde 400 karakterde kesilir; tam araç sonucu burada
    _execute = agent.registry.execute

    def spy(name, arguments, *a, **k):
        result = _execute(name, arguments, *a, **k)
        full.append((name, result))
        return result
    agent.registry.execute = spy

    def ask(question: str, turns: list) -> dict:
        agent.llm = Scripted(turns)
        r = client.post("/api/ask", json={"question": question})
        return r.json() if r.status_code == 200 else {"error": r.status_code, "detail": r.text[:300], "steps": []}

    def steps(payload: dict, tool: str) -> list[dict]:
        return [s for s in payload.get("steps", []) if s.get("tool") == tool]

    def active() -> pd.DataFrame | None:
        return agent.workspace.table

    def col(frame: pd.DataFrame, name: str) -> pd.Series:
        return pd.Series(frame[name].to_numpy(dtype="float64"), index=pd.to_datetime(frame["observation_date"]))

    def states(payload: dict) -> dict:
        return (payload.get("evidence") or {}).get("states") or {}

    def ev_column(payload: dict, name: str) -> dict:
        return next((c for c in (payload.get("evidence") or {}).get("columns") or [] if c.get("column") == name), {})

    # ---------------------------------------------------------------- A02: 60 ay konut kredisi
    A02_TEXT = (f"Tabloda 2021 Ocak ile 2025 Aralık arasındaki 60 ayın konut kredisi bakiyesi var; Ocak 2021 bakiyesi {tr(loan.iloc[0], 0)} "
                f"milyon TL, Aralık 2025 bakiyesi {tr(loan.iloc[-1], 0)} milyon TL.")
    q1 = "2021-2025 yılları arasındaki 60 aylık veriden konut kredilerinin aylık dağılımını göster."
    a1 = ask(q1, [
        call("lakehouse_query", sql=(f"SELECT observation_date, value AS konut_kredisi FROM silver.fact_observation WHERE series_id = '{LOAN}' "
                                     f"AND observation_date BETWEEN DATE '{START}' AND DATE '{END}' ORDER BY observation_date"),
             purpose="2021-2025 aylık konut kredisi bakiyesi", as_active_table=True),
        call("workspace_query", sql="SELECT * FROM t ORDER BY observation_date DESC LIMIT 1", purpose="son ayın bakiyesi"),
        say(A02_TEXT),
    ])
    t = active()
    dates = pd.to_datetime(t["observation_date"]) if t is not None else pd.Series(dtype="datetime64[ns]")
    months = dates.dt.to_period("M")
    consecutive = bool(len(months) > 1 and all(int((b - a).n) == 1 for a, b in zip(months.iloc[:-1], months.iloc[1:])))
    rep.check("A02-satir-donem", "tablo 60 satır, 2021-01-31 → 2025-12-31, ay başına tek satır, ardışık", t is not None and len(t) == 60
              and str(dates.min().date()) == "2021-01-31" and str(dates.max().date()) == "2025-12-31" and months.is_unique and consecutive,
              {"satır": None if t is None else len(t), "ilk": str(dates.min())[:10], "son": str(dates.max())[:10], "ardışık": consecutive})
    rep.check("A02-deger", "her ayın bakiyesi Silver'dan bağımsız okunanla birebir", t is not None and col(t, "konut_kredisi").equals(loan),
              {"beklenen_son": loan.iloc[-1], "gözlenen_son": None if t is None else float(t["konut_kredisi"].iloc[-1])})
    matched1 = [x.get("text") for x in (a1.get("evidence") or {}).get("numbers") or [] if x.get("matched")]
    rep.check("A02-kanit", "betikteki cevap değişmeden gider; iki bakiye sayısı tabloda eşleşir (sayılar ✓, sorgu izi ✓)",
              a1.get("text") == A02_TEXT and len(matched1) >= 2 and states(a1).get("sayılar") is True and states(a1).get("sorgu izi") is True,
              {"durum": states(a1), "eşleşen": matched1, "özet": (a1.get("evidence") or {}).get("summary"), "cevap": a1.get("text", "")[:160]})
    snap1 = None if t is None else t.copy()

    # ---------------------------------------------------------------- A03: faiz ekleme ve hizalama
    a2 = ask("Bu tabloya konut kredisi faiz oranlarını da ekle.", [
        call("workspace_add_column", dataset_id="gold.konut_faizi_aylik", key_column="period_end", value_column="value",
             column_name="konut_faizi", join_on="observation_date", purpose="konut kredisi faizi, haftalıktan takvim ayına ortalamayla hizalı"),
        say(f"Faiz sütunu eklendi; haftalık faiz takvim ayına ortalamayla hizalandı. Aralık 2025 ortalaması %{tr(rate.iloc[-1], 2)}."),
    ])
    t = active()
    add = steps(a2, "workspace_add_column")
    kept = t is not None and snap1 is not None and t[list(snap1.columns)].equals(snap1)
    rep.check("A03-tablo-bozulmadi", "60 satır korunur; önceki kolonlar birebir aynı; yalnız konut_faizi eklenir",
              kept and len(t) == 60 and list(t.columns) == ["observation_date", "konut_kredisi", "konut_faizi"],
              {"kolonlar": None if t is None else list(t.columns), "önceki_aynı": kept})
    got_rate = None if t is None or "konut_faizi" not in t.columns else col(t, "konut_faizi")
    rate_ok = got_rate is not None and got_rate.notna().all() and np.allclose(got_rate.to_numpy(), rate.reindex(got_rate.index).to_numpy(), atol=1e-9)
    rep.check("A03-hizalama-deger", "her ay faiz = o takvim ayındaki haftalık Silver gözlemlerinin ortalaması (bağımsız hesap, 60/60)", rate_ok,
              {"beklenen_ilk_son": [rate.iloc[0], rate.iloc[-1]], "gözlenen_ilk_son": None if got_rate is None else [got_rate.iloc[0], got_rate.iloc[-1]]})
    fc = ev_column(a2, "konut_faizi")
    visible = bool(add) and add[-1]["ok"] and "Dönem eşleşmesi: 60/60 satır" in add[-1]["summary"] and "konut_faizi_aylik" in (fc.get("sql") or "") \
        and tuple(gold_meta) == (60, "avg", "avg", "weekly", "weekly")
    rep.check("A03-hizalama-gorunur", "kart dönem eşleşmesini (60/60) yazar; kanıt kolonu hizalı Gold tablosuna bağlı (haftalık → aylık, avg)", visible,
              {"kart": add[-1]["summary"][:300] if add else None, "kanıt_sql": (fc.get("sql") or "")[:160], "gold": gold_meta})
    snap2 = None if t is None else t.copy()

    # ---------------------------------------------------------------- A06: faiz düşerken kredi artmayan dönemler
    frame = pd.DataFrame({"k": loan, "r": rate})
    diff = frame.diff()
    expected_periods = [d.strftime("%Y-%m-%d") for d in frame.index[(diff["r"] < 0) & (diff["k"] <= 0)]]
    sql6 = ("SELECT observation_date, konut_faizi, konut_kredisi, faiz_degisim, kredi_degisim FROM ("
            "SELECT observation_date, konut_faizi, konut_kredisi, konut_faizi - LAG(konut_faizi) OVER (ORDER BY observation_date) AS faiz_degisim, "
            "konut_kredisi - LAG(konut_kredisi) OVER (ORDER BY observation_date) AS kredi_degisim FROM t) "
            "WHERE faiz_degisim < 0 AND kredi_degisim <= 0 ORDER BY observation_date")
    listed = ", ".join(expected_periods)
    first_rate = f" İlk dönemde aylık ortalama faiz %{tr(float(rate[pd.Timestamp(expected_periods[0])]), 2)}." if expected_periods else ""
    clean = (f"Faizin bir önceki aya göre düştüğü ve kredi bakiyesinin artmadığı {len(expected_periods)} dönem var: {listed}.{first_rate} "
             if expected_periods else "60 ayın hiçbirinde faiz bir önceki aya göre düşerken kredi bakiyesi artmamış değil: böyle bir dönem yok. ") \
        + "Bu yalnız eşzamanlılıktır; veriden bir neden-sonuç ilişkisi çıkarılamaz."
    a3 = ask("Faiz oranlarının düştüğü halde kredi miktarının yükselmediği dönemler olmuş mu?", [
        call("workspace_query", sql=sql6, purpose="faiz düşerken kredi bakiyesinin artmadığı aylar"),
        say("Faiz düşüşü bu dönemlerde kredi talebinin durmasına neden oldu."),
        say(clean),
    ])
    q = steps(a3, "workspace_query")
    rerun = agent.registry.execute("workspace_query", {"sql": sql6, "purpose": "doğrulama"})
    tool_periods = [] if rerun.data is None else [str(x)[:10] for x in rerun.data["observation_date"]]
    rep.check("A06-arac-hesabi", "dönemler araçla (workspace_query) hesaplanır; bağımsız pandas hesabıyla aynı liste",
              bool(q) and q[-1]["ok"] and tool_periods == expected_periods,
              {"beklenen": expected_periods, "araç": tool_periods, "kart": q[-1]["summary"][:160] if q else None})
    rep.check("A06-tablo-degismedi", "bakış modu: aktif tablo değişmez (60 satır, 3 kolon)",
              active() is not None and snap2 is not None and active().equals(snap2), {"kolonlar": None if active() is None else list(active().columns)})
    validate = [s for s in a3.get("steps", []) if s.get("role") == "validate" and "CAUSAL" in (s.get("thought") or "")]
    rep.check("A06-nedensellik", "nedensellik dili geri gönderilir; giden cevap eşzamanlılık der, neden-sonuç kurmaz",
              bool(validate) and a3.get("text", "").startswith(clean[:40]) and "neden oldu" not in a3.get("text", ""),
              {"geri_gönderme": [s.get("thought") for s in validate], "cevap": a3.get("text", "")[:200]})
    matched3 = [x.get("text") for x in (a3.get("evidence") or {}).get("numbers") or [] if x.get("matched")]
    rep.check("A06-kanit", "giden cevaptaki faiz sayısı (üç ondalıklı Gold değerinin Türkçe yuvarlaması) tabloda eşleşir (sayılar ✓)",
              states(a3).get("sayılar") is True and len(matched3) >= 1,
              {"durum": states(a3), "eşleşen": matched3, "özet": (a3.get("evidence") or {}).get("summary")})

    # Dış bağlam: arama sonucu veri kaynaklarından ayrı, "bağlam, veri değil" diye kaynaklanır. Ağ yok: sahte Tavily oturumu.
    ctx_urls = ["https://ornek-tcmb.example/ppk-2023", "https://ornek-haber.example/konut-talebi"]

    class FakeSearchSession:
        def post(self, url, json=None, headers=None, timeout=None):
            return SimpleNamespace(status_code=200, json=lambda: {"results": [
                {"title": "Para Politikası Kurulu kararları 2023", "url": ctx_urls[0], "content": "Kurul Aralık 2023'te politika faizini artırdı."},
                {"title": "Konut kredisi talebi değerlendirmesi", "url": ctx_urls[1], "content": "Yüksek faiz ortamında talep zayıfladı."}]})
    search_tool = agent.registry.get("web_search")
    if search_tool is not None:
        search_tool.search = TavilySearch(environ={"TAVILY_API_KEY": "k02-sahte-anahtar"}, session=FakeSearchSession(), budget=3)
    context_text = ("Genel bağlam için web aramasında Para Politikası Kurulu kararları (ornek-tcmb.example) ve bir konut kredisi talebi "
                    "değerlendirmesi (ornek-haber.example) bulundu. Bunlar bağlamdır: dönem listesi tablodan hesaplandı, arama sonucu veri "
                    "olarak kullanılmadı ve bir neden-sonuç ilişkisi çıkarılamaz.")
    a3c = ask("Bu dönemlerde para politikası tarafında ne oluyordu? İnternette ara ve kaynağını ver.", [
        call("web_search", query="2023 Aralık Para Politikası Kurulu kararı konut kredisi", max_results=2),
        say(context_text),
    ])
    ctx = (a3c.get("evidence") or {}).get("context_sources") or []
    r3c = client.get(f"/api/answers/{a3c.get('index')}/report.html")
    rep.check("A06-dis-baglam", "dış bağlam kanıtta ve raporda veri kaynaklarından ayrı 'bağlam, veri değil' diye kaynaklanır; tablo ve dönem hesabı değişmez",
              search_tool is not None and [c.get("url") for c in ctx] == ctx_urls and all("veri değil" in (c.get("note") or "") for c in ctx)
              and f"bağlam (web araması, veri değil): {ctx_urls[0]}" in r3c.text and not (a3c.get("evidence") or {}).get("web_sources")
              and a3c.get("text") == context_text and active() is not None and active().equals(snap2),
              {"bağlam": [(c.get("url"), c.get("note")) for c in ctx], "rapor": r3c.status_code, "cevap_aynı": a3c.get("text") == context_text})

    # ---------------------------------------------------------------- A04: reel değer (doğrulanmış TÜFE)
    a4 = ask("Tabloyu bozmadan sadece konut kredisi tutarlarını enflasyondan arındırıp göster.", [
        call("workspace_real_value", value_column="konut_kredisi", index_dataset_id=TUFE, base_period="2025-12",
             column_name="reel_konut_kredisi", purpose="Aralık 2025 fiyatlarıyla konut kredisi"),
        say("Konut kredisi Aralık 2025 fiyatlarıyla reel değere çevrildi; nominal sütun olduğu gibi duruyor."),
    ])
    t = active()
    base = float(tufe[pd.Period("2025-12", "M")])
    exp_real = loan * base / pd.Series(tufe.reindex(loan.index.to_period("M")).to_numpy(), index=loan.index)
    real_ok = t is not None and "reel_konut_kredisi" in t.columns and np.allclose(col(t, "reel_konut_kredisi").to_numpy(), exp_real.to_numpy(), atol=1e-3)
    rep.check("A04-reel", "reel = nominal × TÜFE(2025-12) / TÜFE(ay), bağımsız hesapla aynı; önceki kolonlar birebir, 60 satır",
              real_ok and len(t) == 60 and t[list(snap2.columns)].equals(snap2),
              {"kolonlar": None if t is None else list(t.columns), "beklenen_ilk": round(float(exp_real.iloc[0]), 4),
               "gözlenen_ilk": None if not real_ok else float(t["reel_konut_kredisi"].iloc[0])})
    snap4 = None if t is None else t.copy()

    # ---------------------------------------------------------------- A05: KFE — anlam, baz, dönem denetimi
    a5 = ask("Konut kredisini konut fiyat endeksiyle de reel değere çevir.", [
        call("workspace_real_value", value_column="konut_kredisi", index_dataset_id=KFE, base_period="2025-12",
             column_name="kfe_reel_kredi", purpose="KFE ile reel kredi"),
        say("KFE'nin baz yılı doğrulanmamış; doğrulanmış TÜFE ile yapabilirim ya da doğrulanmamış olsa da kullanmamı söyleyebilirsin."),
    ])
    rv = steps(a5, "workspace_real_value")
    rep.check("A05-baz-dogrulanmamis", "KFE (semantic_confidence=derived) rızasız reel dönüşümde reddedilir; doğrulanmış endeks aday; tablo aynı",
              bool(rv) and rv[-1].get("error_code") == "UNVERIFIED_SEMANTICS" and TUFE in (rv[-1].get("candidates") or []) and active().equals(snap4),
              {"kod": rv[-1].get("error_code") if rv else None, "adaylar": rv[-1].get("candidates") if rv else None, "cevap": a5.get("text", "")[:200]})
    a5b = ask("KFE'yi doğrulanmamış olsa da kullan; 2015-06 fiyatlarıyla reel değere çevir.", [
        call("workspace_real_value", value_column="konut_kredisi", index_dataset_id=KFE, base_period="2015-06",
             column_name="kfe_reel_kredi", purpose="KFE ile 2015-06 fiyatlarıyla reel kredi"),
        say("KFE 2016 Ocak'ta başlıyor; 2015-06 baz alınamaz."),
    ])
    rv2 = steps(a5b, "workspace_real_value")
    rep.check("A05-baz-kapsam", "rızayla bile KFE kapsamı dışındaki baz (2015-06) reddedilir, kapsam söylenir; tablo aynı",
              bool(rv2) and rv2[-1].get("error_code") == "OUT_OF_COVERAGE" and "2016-01" in rv2[-1].get("summary", "") and active().equals(snap4),
              {"kod": rv2[-1].get("error_code") if rv2 else None, "kart": rv2[-1].get("summary", "")[:200] if rv2 else None})
    a6 = ask("Tabloyu hiç bozmadan yeni bir sütun olarak konut fiyat endeksini getir.", [
        call("workspace_add_column", dataset_id=KFE, key_column="observation_date", value_column="value",
             column_name="konut_fiyat_endeksi", join_on="observation_date", purpose="TCMB konut fiyat endeksi (Türkiye)"),
        say("Konut fiyat endeksi yeni sütun olarak eklendi; endeksin baz yılı katalogda doğrulanmamış, bu yüzden reel hesapta kullanılmadı."),
    ])
    t = active()
    kadd = steps(a6, "workspace_add_column")
    summary = next((r.content for name, r in reversed(full) if name == "workspace_add_column"), "") or ""
    rep.check("A05-kaynak-kolonlar", "60 satır; önceki dört kolon birebir; KFE değerleri Silver'la 60/60 aynı",
              t is not None and len(t) == 60 and t[list(snap4.columns)].equals(snap4) and "konut_fiyat_endeksi" in t.columns
              and col(t, "konut_fiyat_endeksi").equals(kfe), {"kolonlar": None if t is None else list(t.columns)})
    rep.check("A05-kart", "kart birim/ölçüm tipi, kaynak frekansı, dönem eşleşmesi 60/60 ve baz yılının DOĞRULANMAMIŞ olduğunu yazar",
              all(p in summary for p in ("ölçüm tipi: index", "kaynak frekansı: monthly", "Dönem eşleşmesi: 60/60 satır", "baz yılı DOĞRULANMAMIŞ")),
              summary[:400])
    kc = ev_column(a6, "konut_fiyat_endeksi")
    xl = client.get(f"/api/answers/{a6.get('index')}/table.xlsx")
    xl_text = ""
    if xl.status_code == 200:
        wb = load_workbook(io.BytesIO(xl.content), read_only=True)
        xl_text = " ".join(str(c) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for c in row if c is not None)
    rep.check("A05-uyari-disa-aktarim", "anlam uyarısı kanıt kolonunda ve XLSX dışa aktarımında (semantic_confidence=derived)",
              any("semantic_confidence=derived" in w for w in kc.get("warnings") or []) and "semantic_confidence=derived" in xl_text,
              {"kanıt_uyarı": kc.get("warnings"), "xlsx": xl.status_code})

    # ---------------------------------------------------------------- A07: karşılaştırmalı grafik
    a7 = ask("Bunu bana karşılaştırmalı grafik olarak göster.", [
        call("chart", chart_type="line", y_columns=["konut_kredisi", "konut_faizi"], title="Konut kredisi ve konut kredisi faizi"),
        say("Konut kredisi bakiyesi ile faiz, farklı birimde oldukları için ilk dönemde 100'e çevrilerek aynı grafikte gösterildi."),
    ])
    charts = a7.get("charts") or []
    png = client.get(f"/api/answers/{a7.get('index')}/chart/0.png")
    title = charts[0].get("title") if charts else ""
    ch = steps(a7, "chart")
    chart_card = next((r.content for name, r in reversed(full) if name == "chart"), "") or ""
    rep.check("A07-grafik", "PNG üretilir ve indirilir; başlık dönemi ve 'ilk dönem = 100' ölçeğini yazar; denetçi geçti; kart birim notu",
              bool(charts) and png.status_code == 200 and png.content[:4] == b"\x89PNG" and base64.b64decode(charts[0]["png"]) == png.content
              and "ilk dönem = 100" in (title or "") and "2021" in (title or "") and "2025" in (title or "") and charts[0].get("lint_ok") is True
              and "farklı birimde" in chart_card,
              {"başlık": title, "png": png.status_code, "bayt": len(png.content), "lint_ok": charts[0].get("lint_ok") if charts else None,
               "birim_notu": "farklı birimde" in chart_card, "adım_ok": ch[-1]["ok"] if ch else None})

    # ---------------------------------------------------------------- A26: eski cevabın raporu ve tablosu cevabın sürümüne bağlı
    r0 = client.get(f"/api/answers/{a1.get('index')}/report.html")
    csv0 = client.get(f"/api/answers/{a1.get('index')}/table.csv")
    back0 = pd.read_csv(io.BytesIO(csv0.content), sep=";", decimal=",", encoding="utf-8-sig") if csv0.status_code == 200 else None
    rep.check("A26-eski-cevap", "altı tur sonra 1. cevabın raporu ve CSV'si hâlâ o cevabın tablosu: 60 satır, 2 kolon, faiz/KFE yok; sürüm ve kaynak yazılı",
              r0.status_code == 200 and "Tablo (60 satır" in r0.text and "konut_faizi" not in r0.text and f"sürüm {commit}" in r0.text
              and "cevap #0" in r0.text and back0 is not None and list(back0.columns) == ["observation_date", "konut_kredisi"] and len(back0) == 60,
              {"rapor": r0.status_code, "csv_kolon": None if back0 is None else list(back0.columns), "csv_satır": None if back0 is None else len(back0),
               "sürüm_yazılı": f"sürüm {commit}" in r0.text})
    r6 = client.get(f"/api/answers/{a6.get('index')}/report.html")
    rep.check("A26-kfe-raporu", "KFE cevabının raporu kendi tablosunu (60 satır, 5 kolon) ve anlam uyarısını taşır",
              r6.status_code == 200 and "Tablo (60 satır" in r6.text and "konut_fiyat_endeksi" in r6.text and "semantic_confidence=derived" in r6.text,
              {"rapor": r6.status_code, "uyarı": "semantic_confidence=derived" in r6.text})
    r7 = client.get(f"/api/answers/{a7.get('index')}/report.html")
    rep.check("A26-grafik-raporu", "grafik cevabının raporu gömülü grafiği, başlıktaki dönem/ölçeği, kaynağı ve sürümü taşır",
              r7.status_code == 200 and "<figure>" in r7.text and "ilk dönem = 100" in r7.text and f"sürüm {commit}" in r7.text and "Kaynaklar" in r7.text,
              {"rapor": r7.status_code, "figür": "<figure>" in r7.text, "kaynaklar": "Kaynaklar" in r7.text})

    rep.meta["demo_db_sha256_sonra"] = sha256(demo_db)
    rep.check("salt-okunur", "asıl demo DB değişmedi (sha256 önce = sonra)", rep.meta["demo_db_sha256_sonra"] == rep.meta["demo_db_sha256_once"],
              {"önce": rep.meta["demo_db_sha256_once"][:16], "sonra": rep.meta["demo_db_sha256_sonra"][:16]})
    passed = sum(s.ok for s in rep.steps)
    out = REPO / "docs" / "experiments" / f"k02_finans_kabul_{datetime.now():%Y-%m-%d_%H%M}.json"
    out.write_text(json.dumps({"meta": rep.meta, "passed": passed, "total": len(rep.steps), "steps": [s.__dict__ for s in rep.steps]},
                              ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nSONUÇ: {passed}/{len(rep.steps)} · rapor {out}")
    return 0 if passed == len(rep.steps) else 1


if __name__ == "__main__":
    sys.exit(main())
