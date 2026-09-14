"""K01 — iki kritik akış gerçek bileşenlerle (A09, A21a–c; düzeltme planı D04-T05…T07, K01-T01…T06).

Model çağrısı YOK: ajanın gerçek döngüsü, gerçek araçları, gerçek web uygulaması (`build_default_app`) ve gerçek lakehouse
CLI'ı (alt süreç) kullanılır; modelin yerine hangi aracı çağıracağı önceden yazılmış bir betik (`Scripted`) konur. Böylece
harness, politika, CLI ve veri sonuçları modelden bağımsız, tekrarlanabilir biçimde doğrulanır. Canlı model davranışı
ayrıca M16 kabulünde ölçülür.

Her şey `--work` altındaki geçici kökte; asıl `data/` yalnız okunur ve parmak iziyle değişmediği gösterilir.

    uv run python scripts/k01_kabul.py --work /tmp/k01
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
FIX = ROOT / "tests" / "fixtures" / "generic"


@dataclass
class Step:
    id: str
    beklenen: str
    gozlenen: str = ""
    ok: bool = False


@dataclass
class Report:
    meta: dict[str, Any]
    steps: list[Step] = field(default_factory=list)

    def check(self, sid: str, beklenen: str, ok: bool, gozlenen: Any) -> bool:
        self.steps.append(Step(sid, beklenen, str(gozlenen)[:600], bool(ok)))
        print(f"  {'✓' if ok else '✗'} {sid}: {beklenen} — {str(gozlenen)[:220]}", flush=True)
        return bool(ok)


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lakehouse(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["uv", "run", "python", "-m", "lakehouse", *args], cwd=REPO / "lakehouse-core",
                          capture_output=True, text=True, timeout=600, check=False)


def catalog_series_count() -> int:
    """Beklenen başlangıç kataloğu sayısı sabit yazılmaz; lakehouse-core katalog dosyalarından okunur (main entegrasyonunda
    2.214 → 2.216 oldu: iki kümülatif BDDK kalemi eklendi)."""
    code = ("from pathlib import Path; from src.lakehouse.catalog.series import load_catalog_files; "
            "print(len({s.series_id for s in load_catalog_files(Path('catalog/series'))}))")
    out = subprocess.run(["uv", "run", "python", "-c", code], cwd=REPO / "lakehouse-core", capture_output=True, text=True, timeout=300, check=True)
    return int(out.stdout.strip().splitlines()[-1])


def db_query(db: Path, sql: str, params: list | None = None) -> list[tuple]:
    """Ayrı süreçte salt okunur sorgu: ajanın sertleştirilmiş bağlantısı aynı süreçte açıkken DuckDB farklı ayarlı ikinci
    bağlantıya izin vermez ("same database file with a different configuration")."""
    code = ("import duckdb, json, sys; a = json.load(sys.stdin); con = duckdb.connect(a['db'], read_only=True); "
            "rows = con.execute(a['sql'], a['params']).fetchall(); con.close(); print(json.dumps(rows, default=str))")
    out = subprocess.run([sys.executable, "-c", code], input=json.dumps({"db": str(db), "sql": sql, "params": params or []}),
                         capture_output=True, text=True, check=False)
    if out.returncode != 0:
        raise RuntimeError(f"sorgu başarısız: {out.stderr[-400:]}")
    return [tuple(r) for r in json.loads(out.stdout)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    data = work / "data"
    (data / "incoming").mkdir(parents=True)
    control = work / "koru" / "kontrol.txt"
    control.parent.mkdir(parents=True)
    control.write_text("K01 kontrol dosyası: veri kökü dışında, dokunulmamalı", encoding="utf-8")
    db = data / "lakehouse.duckdb"

    os.environ.update({
        "DATA_ROOT": str(data), "LAKEHOUSE_PATH": str(db), "INGEST_ALLOWED_ROOT": str(data / "incoming"),
        "CHART_DIR": str(data / "charts"), "EMBEDDING_CACHE_DIR": str(data / "cache" / "embeddings"),
        "ARCHITECT_TOKEN": "k01-anahtar", "AGENT_PROFILE": "analyst", "LAKEHOUSE_MODE": "demo", "EMBEDDING_MODEL": "",
        "VISION_MODEL": "", "TOOL_GATE": "off", "LLM_NARRATE_TEMPERATURE": "0",
    })
    sys.path.insert(0, str(ROOT / "src"))
    import pandas as pd
    from fastapi.testclient import TestClient
    from openpyxl import load_workbook

    from kkb_agent.llm.base import LLMResponse, ToolCall
    from kkb_agent.web_app import build_default_app

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    demo_db = REPO / "data" / "lakehouse.duckdb"
    rep = Report(meta={"commit": commit, "work": str(work), "at": datetime.now().isoformat(timespec="seconds"),
                       "model": "betikli (LLM çağrısı yok)", "demo_db_sha256_once": sha256(demo_db)})
    print(f"K01 — commit {commit} · kök {work}")

    class Scripted:
        model = "k01-betik"

        def __init__(self, turns: list):
            self.turns = list(turns)

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            if self.turns:
                return self.turns.pop(0)
            return LLMResponse(content="Tamam.")

    n = 0

    def call(_tool: str, /, **arguments) -> LLMResponse:
        nonlocal n
        n += 1
        return LLMResponse(content="", tool_calls=[ToolCall(id=f"c{n}", name=_tool, arguments=arguments)])

    def say(text: str) -> LLMResponse:
        return LLMResponse(content=text)

    def ask(client, app, question: str, turns: list) -> dict:
        app.state.session.agent.llm = Scripted(turns)
        r = client.post("/api/ask", json={"question": question})
        return r.json() if r.status_code == 200 else {"error": r.status_code, "detail": r.text[:300]}

    def upload(client, fixture: Path) -> str:
        r = client.post("/api/upload", files={"file": (fixture.name, fixture.read_bytes(), "text/csv")})
        return r.json()["path"]

    def tool_ok(payload: dict, tool: str) -> list[dict]:
        return [s for s in payload.get("steps", []) if s.get("tool") == tool]

    # ---------------------------------------------------------------- K01-T01: kök ve başlangıç kataloğu
    boot = lakehouse("bootstrap", "--database", str(db), "--data-root", str(data), "--catalog", "default")
    expected_catalog = catalog_series_count()
    rep.check("T01-kurulum", f"geçici kökte DB başlangıç kataloğuyla kurulur ({expected_catalog} seri, katalog dosyalarından)",
              boot.returncode == 0 and f"catalog_series_count: {expected_catalog}" in boot.stdout,
              boot.stdout.strip().replace("\n", " · ") or boot.stderr[-300:])
    catalog_before = db_query(db, "SELECT count(*), md5(string_agg(series_id || coalesce(status,''), ',' ORDER BY series_id)) FROM meta.series")[0]

    app = build_default_app()
    client = TestClient(app)
    st = client.get("/api/status").json()
    rep.check("T01-uygulama", "web uygulaması geçici DB ile açılır (Analyst)", st.get("profile") == "analyst", {k: st.get(k) for k in ("profile", "model")})

    # ---------------------------------------------------------------- K01-T02/T03: Analyst iki dosya, anahtarla birleştirme, hesap, indirme
    p_nufus, p_hastane = upload(client, FIX / "nufus_il.csv"), upload(client, FIX / "hastane_il.csv")
    q1 = f"Bu iki dosyayı il üzerinden birleştir ve milyon kişi başına hastane sayısını hesapla.\n\nDosya: {p_nufus}\nDosya: {p_hastane}"
    a0 = ask(client, app, q1, [
        call("web_url", url=p_nufus, purpose="nüfus tablosu", table_index=0),
        call("web_url", url=p_hastane, purpose="hastane tablosu", table_index=0),
        call("workspace_query", sql="SELECT DISTINCT * FROM t", purpose="yinelenen Van satırını tekilleştir", as_active_table=True),
        call("workspace_join", left="k1", right="k3", left_key="il_adi", right_key="il", purpose="nüfus ve hastane"),
        say("İki dosyada il adları farklı yazılmış (büyük/küçük harf). Bunlar aynı il sayılsın mı?"),
    ])
    join_steps = tool_ok(a0, "workspace_join")
    rep.check("T02-kural-sorusu", "birebir eşitlik sonucu değiştiriyor: birleştirme yapılmaz, kural sorulur",
              join_steps and not join_steps[-1]["ok"] and "metin_normal" in (join_steps[-1].get("result") or join_steps[-1].get("summary") or json.dumps(join_steps[-1], ensure_ascii=False)),
              join_steps[-1] if join_steps else a0)
    ws = app.state.session.agent.workspace
    rep.check("T02-kaynaklar", "iki dosya ayrı kaynak kimliğiyle oturumda (k1 nüfus, k2 hastane, k3 tekil)",
              [s.id for s in ws.sources()][:3] == ["k1", "k2", "k3"], [(s.id, s.title) for s in ws.sources()])

    q2 = "Evet, büyük/küçük harf ve boşluk farkı aynı il sayılsın; birleştir ve milyon kişi başına hastane sayısını hesapla."
    a1 = ask(client, app, q2, [
        call("workspace_join", left="k1", right="k3", left_key="il_adi", right_key="il", key_policy="metin_normal", purpose="nüfus ve hastane"),
        call("workspace_compute_column", expression="hastane_sayisi / nufus_bin * 1000", column_name="milyon_kisi_basina_hastane",
             purpose="milyon kişi başına hastane"),
        say("Birleşik tabloda her il için milyon kişi başına hastane sayısı hesaplandı; Trabzon hastane dosyasında yok."),
    ])
    t = ws.table
    expected = {"ankara": 96 / 5864 * 1000, "ADANA": 41 / 2274 * 1000, "İzmir": 73 / 4462 * 1000}
    got = {} if t is None or "milyon_kisi_basina_hastane" not in t.columns else dict(zip(t["il_adi"], t["milyon_kisi_basina_hastane"]))
    values_ok = bool(got) and all(abs(float(got[k]) - v) < 1e-9 for k, v in expected.items()) and pd.isna(got.get("Trabzon"))
    rep.check("T03-degerler", "birleşim + takip hesabı beklenen değerler (ankara 16,371…, ADANA 18,029…, İzmir 16,360…, Trabzon boş)",
              values_ok and len(t) == 4, {k: (round(float(v), 4) if pd.notna(v) else None) for k, v in got.items()})
    prov_ok = t is not None and "nufus" in " ".join(ws.column_provenance("nufus_bin").sources) \
        and "hastane" in " ".join(ws.column_provenance("hastane_sayisi").sources) and "kural: metin_normal" in ws.column_provenance("hastane_sayisi").sql
    rep.check("T03-kaynak", "her kolon kendi dosyasının provenance'ını ve anahtar kuralını taşır", prov_ok,
              {c: ws.column_provenance(c).sources for c in ("nufus_bin", "hastane_sayisi")} if t is not None else None)
    idx = a1.get("index")
    csv = client.get(f"/api/answers/{idx}/table.csv")
    back = pd.read_csv(io.BytesIO(csv.content), sep=";", decimal=",", encoding="utf-8-sig") if csv.status_code == 200 else None
    xl = client.get(f"/api/answers/{idx}/table.xlsx")
    xrows = load_workbook(io.BytesIO(xl.content), read_only=True)["tablo"].max_row - 1 if xl.status_code == 200 else None
    html = client.get(f"/api/answers/{idx}/report.html")
    export_ok = back is not None and len(back) == 4 and abs(float(back.loc[back["il_adi"] == "ADANA", "milyon_kisi_basina_hastane"].iloc[0]) - expected["ADANA"]) < 1e-6 \
        and xrows == 4 and html.status_code == 200 and "milyon_kisi_basina_hastane" in html.text
    rep.check("T02-indirme", "tam tablo CSV/XLSX ve HTML rapor aynı 4 satırı ve hesap kolonunu taşır", export_ok,
              {"csv_satir": None if back is None else len(back), "xlsx_satir": xrows, "rapor": html.status_code})
    catalog_after = db_query(db, "SELECT count(*), md5(string_agg(series_id || coalesce(status,''), ',' ORDER BY series_id)) FROM meta.series")[0]
    rep.check("T03-ortak-katalog", "Analyst oturumu ortak kataloğu değiştirmez (sayı ve içerik parmak izi)", catalog_before == catalog_after,
              {"önce": catalog_before, "sonra": catalog_after})

    # ---------------------------------------------------------------- K01-T04: Architect taslak, geçersiz onay retleri, geçerli yayın, Gold
    r = client.post("/api/profile", json={"profile": "architect", "token": "k01-anahtar"})
    rep.check("T04-profil", "anahtarla Architect'e geçiş; oturum temizlenir", r.status_code == 200 and client.get("/api/answers").json() == [], r.json())
    p_acil = upload(client, FIX / "acil_basvuru_aylik.csv")
    # Aylık başvuru sayısı bir dönemlik AKIMDIR: flow_periodic + sum. (İlk koşuda "count" beyan edildi; Gold adet tipinde güvenli
    # toplama kuralı olmadığı için UNSUPPORTED_MEASURE_TYPE ile doğru biçimde reddetti.)
    a2 = ask(client, app, f"acil_basvuru_aylik.csv dosyasını taslak seri olarak ekle; birim kişi, ölçüm tipi flow_periodic, aylık kural sum.\n\nDosya: {p_acil}", [
        call("ingest_from_url", locator=p_acil, name="Acil başvuru (aylık)", series_key="acil_basvuru", unit="kişi", measure_type="flow_periodic", default_agg="sum"),
        say("Dosya taslak seri olarak eklendi; kataloğa almak için onayını bekliyorum."),
    ])
    ing = tool_ok(a2, "ingest_from_url")
    draft = db_query(db, "SELECT series_id, status FROM meta.series WHERE series_id = 'adhoc:acil_basvuru'")
    rep.check("T04-taslak", "gerçek CLI ile taslak seri yazılır (status draft)", bool(ing) and ing[-1]["ok"] and draft and draft[0][1] == "draft",
              {"adım": ing[-1] if ing else None, "db": draft})

    def fingerprint() -> tuple:
        return (db_query(db, "SELECT status FROM meta.series WHERE series_id = 'adhoc:acil_basvuru'"),
                db_query(db, "SELECT count(*) FROM silver.fact_observation WHERE series_id = 'adhoc:acil_basvuru'")[0][0], sha256(db))
    fp0 = fingerprint()
    a3 = ask(client, app, "acil_basvuru taslağına bir bakalım.", [call("promote_draft", series_id="adhoc:acil_basvuru", purpose="terfi"),
                                                                  say("Bu taslağı kataloğa almamı onaylıyor musun?")])
    fp1 = fingerprint()
    a4 = ask(client, app, "Şimdi acil_basvuru yayınlama.", [call("promote_draft", series_id="adhoc:acil_basvuru", purpose="terfi"),
                                                            say("Tamam, yayınlamadım.")])
    fp2 = fingerprint()
    rets = [tool_ok(a, "promote_draft") for a in (a3, a4)]
    rep.check("T04-gecersiz-onay", "onaysız ve 'yayınlama' turlarında terfi reddedilir; DB (satır, Silver sayısı, dosya özeti) değişmez",
              all(x and not x[-1]["ok"] and x[-1].get("error_code") == "INTENT_REQUIRED" for x in rets) and fp0 == fp1 == fp2,
              {"retler": [x[-1].get("error_code") if x else None for x in rets], "parmak_izi_aynı": fp0 == fp1 == fp2})
    a5 = ask(client, app, "acil_basvuru taslağını onaylıyorum, kataloğa al.", [call("promote_draft", series_id="adhoc:acil_basvuru", purpose="terfi"),
                                                                              say("Taslak kataloğa aktif seri olarak alındı.")])
    fp3 = fingerprint()
    rep.check("T04-yayin", "güncel açık onayla yalnız bu işlem: aktif seri ve Silver'da 12 satır", fp3[0] and fp3[0][0][0] == "active" and fp3[1] == 12,
              {"durum": fp3[0], "silver": fp3[1], "adım_ok": tool_ok(a5, "promote_draft")[-1]["ok"] if tool_ok(a5, "promote_draft") else None})
    fixture = pd.read_csv(FIX / "acil_basvuru_aylik.csv", sep=None, engine="python")
    date_col = [c for c in fixture.columns if "donem" in c.lower() or "tarih" in c.lower() or "ay" == c.lower()][0]
    val_col = [c for c in fixture.columns if c != date_col][0]
    fixture[date_col] = pd.to_datetime(fixture[date_col])
    exp_q = fixture.groupby(fixture[date_col].dt.to_period("Q"))[val_col].sum().astype(float).tolist()
    a6 = ask(client, app, "acil_basvuru serisini doğrulanmamış olsa da kullan ve çeyreklik topla.", [
        call("gold_align", series_id="adhoc:acil_basvuru", target_frequency="quarterly", purpose="çeyreklik toplam"),
        say("Çeyreklik tablo hazır."),
    ])
    gt = app.state.session.agent.workspace.table
    gold_steps = tool_ok(a6, "gold_align")
    obs_q = [] if gt is None else sorted(float(x) for c in gt.columns if str(c).endswith("value") or str(c) == "value" for x in gt[c].dropna())
    rep.check("T04-gold", "finans dışı yayımlanmış seride Gold çeyreklik toplam modelden bağımsız beklenenle aynı",
              bool(gold_steps) and gold_steps[-1]["ok"] and obs_q == sorted(exp_q),
              {"beklenen": exp_q, "gözlenen": obs_q, "adım": (gold_steps[-1].get("summary") or "")[:200] if gold_steps else a6.get("detail")})

    # ---------------------------------------------------------------- K01-T05: önizleme → onay → fiziksel sıfırlama → boş katalog → yeni alan
    (data / "charts").mkdir(exist_ok=True)
    (data / "charts" / "eski.png").write_bytes(b"png")
    preview = client.post("/api/architect/reset", json={}).json()
    rep.check("T05-onizleme", "önizleme kapsamı (DB, RAW/Bronze, yüklemeler, grafikler) ve boş katalog seçimi gösterir",
              preview.get("catalog") == "bos" and not preview.get("refused") and {"veritabanı", "grafikler"} <= {d["label"] for d in preview.get("target_details", [])},
              {"hedefler": [d["label"] for d in preview.get("target_details", [])], "not": preview.get("note")})
    done = client.post("/api/architect/reset", json={"confirm": preview.get("confirm")}).json()
    series_after_reset = db_query(db, "SELECT count(*) FROM meta.series")[0][0] if db.exists() else None
    rep.check("T05-sifirlama", "fiziksel sıfırlama tamamlandı; şema var, meta.series 0, kip none; eski grafik ve yüklemeler yok",
              done.get("status") == "tamamlandı" and series_after_reset == 0 and not (data / "charts" / "eski.png").exists()
              and not Path(p_acil).exists() and done.get("verify", {}).get("catalog_mode") == "none",
              {"durum": done.get("status"), "doğrulama": done.get("verify"), "ajan": done.get("agent"), "seri": series_after_reset})
    rep.check("T05-korunan", "veri kökü dışındaki kontrol dosyası ve asıl demo DB değişmedi",
              control.read_text(encoding="utf-8").startswith("K01 kontrol") and sha256(demo_db) == rep.meta["demo_db_sha256_once"],
              {"kontrol": control.exists(), "demo_db_aynı": sha256(demo_db) == rep.meta["demo_db_sha256_once"]})
    p_ziyaret = upload(client, FIX / "web_ziyaret_kirilma.csv")
    a7 = ask(client, app, f"web_ziyaret_kirilma.csv dosyasını taslak seri olarak ekle; birim ziyaret, ölçüm tipi count, aylık kural avg.\n\nDosya: {p_ziyaret}", [
        call("ingest_from_url", locator=p_ziyaret, name="Günlük web ziyareti (aylık)", series_key="web_ziyaret", unit="ziyaret", measure_type="count", default_agg="avg"),
        say("Taslak eklendi."),
    ])
    a8 = ask(client, app, "web_ziyaret taslağını onaylıyorum, kataloğa al.", [call("promote_draft", series_id="adhoc:web_ziyaret", purpose="terfi"),
                                                                             say("Kataloğa alındı.")])
    catalog_new = db_query(db, "SELECT series_id, status FROM meta.series ORDER BY 1")
    rep.check("T05-yeni-alan", "boş katalogdan yeni alan: yalnız adhoc:web_ziyaret aktif; finans serisi geri gelmedi",
              catalog_new == [("adhoc:web_ziyaret", "active")], {"katalog": catalog_new, "ingest_ok": [s["ok"] for s in tool_ok(a7, "ingest_from_url")],
                                                                  "promote_ok": [s["ok"] for s in tool_ok(a8, "promote_draft")]})
    a9 = ask(client, app, "web_ziyaret serisinde davranış ne zaman değişti?", [
        call("lakehouse_query", sql="SELECT observation_date, value FROM silver.fact_observation WHERE series_id = 'adhoc:web_ziyaret' ORDER BY observation_date",
             purpose="ziyaret serisi", as_active_table=True),
        call("change_points", column="value", purpose="kırılma"),
        say("Seride belirgin bir düzey değişimi var; ayrıntı karttaki tarihte."),
    ])
    cp = tool_ok(a9, "change_points")
    wt = app.state.session.agent.workspace.table
    breaks = []
    if wt is not None and "value_rejim" in wt.columns:
        dates = pd.to_datetime(wt["observation_date"]).dt.strftime("%Y-%m-%d").tolist()
        regimes = wt["value_rejim"].tolist()
        breaks = [dates[i] for i in range(1, len(regimes)) if regimes[i] != regimes[i - 1]]
    rep.check("T05-analiz", "yeni alanda analiz: rejim 2025-01-31'de değişir (düzey sıçraması), araç başarılı",
              bool(cp) and cp[-1]["ok"] and "2025-01-31" in breaks,
              {"kırılmalar": breaks, "adım_ok": cp[-1]["ok"] if cp else None,
               "adımlar": [(s.get("role"), s.get("tool"), s.get("ok"), s.get("error_code"), (s.get("thought") or "")[:80]) for s in a9.get("steps", [])],
               "cevap": (a9.get("text") or "")[:200]})

    # ---------------------------------------------------------------- K01-T06: yeniden başlatma, profil, katalog/cache sızıntısı, Analyst yazamaz
    from kkb_agent.web_app import _close_agent_readers
    _close_agent_readers(app.state.session.agent, db)      # üründe bootstrap yalnız sıfırlamada, okuyucular kapandıktan sonra koşar
    again = lakehouse("bootstrap", "--database", str(db), "--data-root", str(data))
    rep.check("T06-yeniden-bootstrap", "bayraksız bootstrap kayıtlı boş kipi korur (1 seri, finans kataloğu yok)",
              again.returncode == 0 and "catalog_mode: none" in again.stdout and "catalog_series_count: 1" in again.stdout,
              again.stdout.strip().replace("\n", " · ") or again.stderr.strip()[-300:])
    app2 = build_default_app()                                   # süreç yeniden başlamış gibi: yeni oturum, yeni ajan
    client2 = TestClient(app2)
    agent2 = app2.state.session.agent
    search = agent2.registry.execute("lakehouse_search", {"query": "konut kredisi bakiyesi"})
    domain = agent2.profile.domain
    leak = [w for w in ("bddk", "evds", "konut", "kredi") if w in (search.content or "").lower() or w in domain.lower()]
    rep.check("T06-sizinti", "yeniden başlatmada alan profili yalnız yeni katalogdan; arama eski finans serisi döndürmez",
              not leak and "adhoc" in domain, {"alan": domain, "sızan": leak, "arama": (search.content or "")[:200]})
    cache_dir = data / "cache"
    rep.check("T06-onbellek", "sıfırlama sonrası eski embedding önbelleği yok", not any(cache_dir.rglob("*")) if cache_dir.exists() else True,
              sorted(str(p) for p in cache_dir.rglob("*"))[:5] if cache_dir.exists() else "önbellek dizini yok")
    names = set(agent2.registry.names())
    rep.check("T06-analyst-yazamaz", "Analyst profilinde kalıcı yazma araçları kayıtlı değil",
              client2.get("/api/status").json().get("profile") == "analyst" and not ({"ingest_from_url", "promote_draft"} & names),
              sorted(names & {"ingest_from_url", "promote_draft", "web_url", "workspace_join"}))

    passed = sum(s.ok for s in rep.steps)
    out = REPO / "docs" / "experiments" / f"k01_kabul_{datetime.now():%Y-%m-%d_%H%M}.json"
    rep.meta["demo_db_sha256_sonra"] = sha256(demo_db)
    out.write_text(json.dumps({"meta": rep.meta, "passed": passed, "total": len(rep.steps),
                               "steps": [s.__dict__ for s in rep.steps]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSONUÇ: {passed}/{len(rep.steps)} · rapor {out}")
    return 0 if passed == len(rep.steps) else 1


if __name__ == "__main__":
    sys.exit(main())
