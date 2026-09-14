"""K01-T07 — iki kritik akış arayüzden (A09, A21): gerçek tarayıcı, gerçek HTTP sunucusu, gerçek harness/araçlar/lakehouse CLI.

Model yerine betik (K01 ile aynı yöntem): sunucu bu süreçte çalışır, `cli.OpenAICompatClient` tek bir betikli yönlendiriciye
bağlanır; profil geçişi ve sıfırlama ajanı yeniden kursa da aynı betik kullanılır. Tarayıcı dosya yükler, soru sorar, profil
geçer, sıfırlama penceresinde onay kodunu yazar. Her adımda ekrandaki durum, indirilen dosyalar ve DB (ayrı süreç) denetlenir.
Her şey `--work` altındaki geçici kökte; asıl `data/` yalnız okunur (özet önce/sonra).

    uv run --with playwright python scripts/k01_ui_kabul.py --work /tmp/k01ui
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
FIX = ROOT / "tests" / "fixtures" / "generic"
sys.path.insert(0, str(ROOT))

from scripts.k01_kabul import catalog_series_count, db_query, lakehouse, sha256  # noqa: E402


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    data = work / "data"
    (data / "incoming").mkdir(parents=True)
    control = work / "koru" / "kontrol.txt"
    control.parent.mkdir(parents=True)
    control.write_text("K01-T07 kontrol dosyası: veri kökü dışında, dokunulmamalı", encoding="utf-8")
    db = data / "lakehouse.duckdb"
    demo_db = REPO / "data" / "lakehouse.duckdb"
    stamp = f"{datetime.now():%Y-%m-%d_%H%M}"
    out = REPO / "docs" / "experiments" / f"k01_ui_kabul_{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    os.environ.update({
        "DATA_ROOT": str(data), "LAKEHOUSE_PATH": str(db), "INGEST_ALLOWED_ROOT": str(data / "incoming"),
        "CHART_DIR": str(data / "charts"), "EMBEDDING_CACHE_DIR": str(data / "cache" / "embeddings"),
        "ARCHITECT_TOKEN": "k01-anahtar", "AGENT_PROFILE": "analyst", "LAKEHOUSE_MODE": "demo", "EMBEDDING_MODEL": "",
        "VISION_MODEL": "", "TOOL_GATE": "off", "LLM_NARRATE_TEMPERATURE": "0", "TAVILY_API_KEY": "k01-ui-sahte-anahtar",
    })
    sys.path.insert(0, str(ROOT / "src"))
    import pandas as pd
    import uvicorn
    from openpyxl import load_workbook
    from playwright.sync_api import sync_playwright

    import kkb_agent.cli as cli_mod
    from kkb_agent.llm.base import LLMResponse, ToolCall
    from kkb_agent.web_app import build_default_app

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "agent-core/src"], capture_output=True, text=True, cwd=REPO).stdout.strip())
    meta = {"commit": commit, "kaynak_agac_temiz": not dirty, "work": str(work), "at": datetime.now().isoformat(timespec="seconds"),
            "model": "betikli (LLM çağrısı yok)", "demo_db_sha256_once": sha256(demo_db)}
    steps: list[dict] = []
    print(f"K01-T07 arayüz — commit {commit}{' (kaynak ağacı kirli)' if dirty else ''} · kök {work}")

    def record(sid: str, expected: str, ok: bool, observed, page=None) -> bool:
        shot = None
        if page is not None:
            shot = out / f"{len(steps) + 1:02d}_{sid}.png"
            page.screenshot(path=str(shot), full_page=True)
        steps.append({"id": sid, "beklenen": expected, "ok": bool(ok), "gozlenen": str(observed)[:700],
                      "at": datetime.now().isoformat(timespec="seconds"), "ekran": shot.name if shot else None})
        print(f"  {'✓' if ok else '✗'} {sid}: {expected} — {str(observed)[:200]}", flush=True)
        return bool(ok)

    class Router:
        model = "k01-ui-betik"

        def __init__(self) -> None:
            self.turns: list = []

        def supports_native_tools(self) -> bool:
            return True

        def chat(self, messages, *, tools=None, temperature=0.0, max_tokens=None):
            return self.turns.pop(0) if self.turns else LLMResponse(content="BETIK_BITTI")

    router = Router()
    cli_mod.OpenAICompatClient = lambda *a, **k: router          # yeniden kurulan ajanlar da aynı betiği alır

    n = 0

    def call(_tool: str, /, **arguments) -> LLMResponse:
        nonlocal n
        n += 1
        return LLMResponse(content="", tool_calls=[ToolCall(id=f"u{n}", name=_tool, arguments=arguments)])

    def say(text: str) -> LLMResponse:
        return LLMResponse(content=text)

    boot = lakehouse("bootstrap", "--database", str(db), "--data-root", str(data), "--catalog", "default")
    if boot.returncode != 0:
        print(boot.stdout, boot.stderr)
        return 2
    app = build_default_app()
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"

    def catalog_fp() -> tuple:
        return tuple(db_query(db, "SELECT count(*), md5(string_agg(series_id || coalesce(status,''), ',' ORDER BY series_id)) FROM meta.series")[0])

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not args.headed)
        meta["tarayici"] = f"chromium {browser.version}"
        page = browser.new_page(viewport={"width": 1440, "height": 960}, accept_downloads=True)
        api = page.request

        def answers() -> list:
            return api.get(f"{url}/api/answers").json()

        def upload(fixture: Path) -> str:
            before = len(api.get(f"{url}/api/uploads").json())
            page.set_input_files("#file", str(fixture))
            page.wait_for_function(f"fetch('/api/uploads').then(r => r.json()).then(u => u.length > {before})", timeout=30000)
            page.wait_for_function("[...document.querySelectorAll('#attach .chip')].some(c => c.textContent.includes('📎'))", timeout=30000)
            return api.get(f"{url}/api/uploads").json()[-1]["path"]

        def ask(question: str, turns: list) -> dict:
            router.turns = list(turns)
            shown = page.locator(".a").count()
            page.fill("#q", question)
            page.click("#btn-ask")
            page.wait_for_function(f"document.querySelectorAll('.a').length > {shown} && !document.querySelector('.busy')", timeout=180000)
            return answers()[-1]

        def tool_steps(payload: dict, tool: str) -> list[dict]:
            return [s for s in payload.get("steps", []) if s.get("tool") == tool]

        def download(link_suffix: str) -> bytes:
            with page.expect_download() as d:
                page.locator(".a").last.locator(f"a[href$='{link_suffix}']").first.click()
            return Path(d.value.path()).read_bytes()

        # ------------------------------------------------------------ açılış
        page.goto(url)
        page.wait_for_function("document.querySelector('#pill-model') && document.querySelector('#pill-model').textContent.length > 3", timeout=30000)
        status = api.get(f"{url}/api/status").json()
        expected_catalog = catalog_series_count(active_only=True)
        record("acilis", f"arayüz geçici DB ile açılır; Analyst; başlangıç kataloğu ({expected_catalog} etkin seri, katalog dosyalarından)",
               status.get("profile") == "analyst"
               and "Analyst" in (page.text_content("#pill-profile") or "") and status.get("catalog_series") == expected_catalog,
               {"profil": status.get("profile"), "katalog": status.get("catalog_series"), "rozet": page.text_content("#pill-profile")}, page)
        catalog_before = catalog_fp()

        # ------------------------------------------------------------ A09: iki dosya, kural sorusu, birleşim ve hesap, indirme
        p_nufus, p_hastane = upload(FIX / "nufus_il.csv"), upload(FIX / "hastane_il.csv")
        chips = page.locator("#attach .chip").all_text_contents()
        record("a09-yukleme", "iki dosya arayüzden yüklenir, ek çipleri görünür", len([c for c in chips if "📎" in c]) >= 2, chips, page)
        a0 = ask("Bu iki dosyayı il üzerinden birleştir ve milyon kişi başına hastane sayısını hesapla.", [
            call("web_url", url=p_nufus, purpose="nüfus tablosu", table_index=0),
            call("web_url", url=p_hastane, purpose="hastane tablosu", table_index=0),
            call("workspace_query", sql="SELECT DISTINCT * FROM t", purpose="yinelenen Van satırını tekilleştir", as_active_table=True),
            call("workspace_join", left="k1", right="k3", left_key="il_adi", right_key="il", purpose="nüfus ve hastane"),
            say("İki dosyada il adları farklı yazılmış (büyük/küçük harf). Bunlar aynı il sayılsın mı?"),
        ])
        join = tool_steps(a0, "workspace_join")
        last_text = page.locator(".a").last.text_content() or ""
        record("a09-kural-sorusu", "birebir eşitlik sonucu değiştirir: birleşim yapılmaz, soru ekranda; kural adayları adımda",
               bool(join) and not join[-1]["ok"] and "metin_normal" in json.dumps(join[-1], ensure_ascii=False) and "aynı il sayılsın mı" in last_text,
               {"adım": join[-1] if join else None, "ekran": last_text[:160]}, page)
        a1 = ask("Evet, büyük/küçük harf ve boşluk farkı aynı il sayılsın; birleştir ve milyon kişi başına hastane sayısını hesapla.", [
            call("workspace_join", left="k1", right="k3", left_key="il_adi", right_key="il", key_policy="metin_normal", purpose="nüfus ve hastane"),
            call("workspace_compute_column", expression="hastane_sayisi / nufus_bin * 1000", column_name="milyon_kisi_basina_hastane",
                 purpose="milyon kişi başına hastane"),
            say("Birleşik tabloda her il için milyon kişi başına hastane sayısı hesaplandı; Trabzon hastane dosyasında yok."),
        ])
        box = page.locator(".a").last
        headers = box.locator("table.data th").all_text_contents()
        rows_ui = box.locator("table.data tbody tr").count()
        record("a09-tablo-ekranda", "ekrandaki tablo 4 satır ve hesap kolonunu gösterir", "milyon_kisi_basina_hastane" in headers and rows_ui == 4,
               {"kolonlar": headers, "satır": rows_ui}, page)
        expected = {"ankara": 96 / 5864 * 1000, "ADANA": 41 / 2274 * 1000, "İzmir": 73 / 4462 * 1000}
        csv_bytes = download("table.csv")
        back = pd.read_csv(io.BytesIO(csv_bytes), sep=";", decimal=",", encoding="utf-8-sig")
        got = dict(zip(back["il_adi"], back["milyon_kisi_basina_hastane"]))
        values_ok = len(back) == 4 and all(abs(float(got[k]) - v) < 1e-6 for k, v in expected.items()) and pd.isna(got.get("Trabzon"))
        xl = load_workbook(io.BytesIO(download("table.xlsx")), read_only=True)
        xrows = xl["tablo"].max_row - 1
        record("a09-indirme", "arayüzden indirilen CSV/XLSX tam tablo; değerler modelden bağımsız beklenenle aynı (Trabzon boş)",
               values_ok and xrows == 4, {"csv": {k: (round(float(v), 4) if pd.notna(v) else None) for k, v in got.items()}, "xlsx_satır": xrows})
        record("a09-ortak-katalog", "Analyst akışı ortak kataloğu değiştirmez (DB parmak izi)", catalog_fp() == catalog_before,
               {"önce": catalog_before, "sonra": catalog_fp(), "cevap": a1.get("index")})

        # ------------------------------------------------------------ A21: profil geçişi, taslak, geçersiz/ geçerli onay
        page.click("#pill-profile")
        page.select_option("#pf-sel", "architect")
        page.fill("#pf-tok", "k01-anahtar")
        page.click("#pf-go")
        page.wait_for_function("document.querySelector('#pill-profile').textContent.includes('Architect')", timeout=30000)
        st = api.get(f"{url}/api/status").json()
        record("a21-profil", "anahtarla Architect; oturum temizlenir; sıfırlama düğmesi görünür",
               st.get("profile") == "architect" and answers() == [] and page.locator(".a").count() == 0 and page.is_visible("#btn-wipe"),
               {"profil": st.get("profile"), "cevap": len(answers()), "sıfırla_görünür": page.is_visible("#btn-wipe")}, page)
        p_acil = upload(FIX / "acil_basvuru_aylik.csv")
        a2 = ask("acil_basvuru_aylik.csv dosyasını taslak seri olarak ekle; birim kişi, ölçüm tipi flow_periodic, aylık kural sum.", [
            call("ingest_from_url", locator=p_acil, name="Acil başvuru (aylık)", series_key="acil_basvuru", unit="kişi",
                 measure_type="flow_periodic", default_agg="sum"),
            say("Dosya taslak seri olarak eklendi; kataloğa almak için onayını bekliyorum."),
        ])
        draft = db_query(db, "SELECT series_id, status FROM meta.series WHERE series_id = 'adhoc:acil_basvuru'")
        record("a21-taslak", "arayüzden gelen istekle gerçek CLI taslak yazar (status draft)", draft == [("adhoc:acil_basvuru", "draft")],
               {"db": draft, "adım_ok": [s["ok"] for s in tool_steps(a2, "ingest_from_url")]}, page)

        def fp() -> tuple:
            return (db_query(db, "SELECT status FROM meta.series WHERE series_id = 'adhoc:acil_basvuru'"),
                    db_query(db, "SELECT count(*) FROM silver.fact_observation WHERE series_id = 'adhoc:acil_basvuru'")[0][0], sha256(db))
        fp0 = fp()
        a3 = ask("acil_basvuru taslağına bir bakalım.", [call("promote_draft", series_id="adhoc:acil_basvuru", purpose="terfi"),
                                                          say("Bu taslağı kataloğa almamı onaylıyor musun?")])
        a4 = ask("Şimdi acil_basvuru yayınlama.", [call("promote_draft", series_id="adhoc:acil_basvuru", purpose="terfi"), say("Tamam, yayınlamadım.")])
        codes = [(tool_steps(a, "promote_draft") or [{}])[-1].get("error_code") for a in (a3, a4)]
        record("a21-gecersiz-onay", "onaysız ve 'yayınlama' turlarında terfi reddedilir; DB satırı, Silver sayısı ve dosya özeti değişmez",
               codes == ["INTENT_REQUIRED", "INTENT_REQUIRED"] and fp() == fp0, {"retler": codes, "parmak_izi_aynı": fp() == fp0}, page)
        ask("acil_basvuru taslağını onaylıyorum, kataloğa al.", [call("promote_draft", series_id="adhoc:acil_basvuru", purpose="terfi"),
                                                                 say("Taslak kataloğa aktif seri olarak alındı.")])
        fp3 = fp()
        record("a21-yayin", "güncel açık onayla aktif seri ve Silver'da 12 satır", fp3[0] == [("active",)] and fp3[1] == 12,
               {"durum": fp3[0], "silver": fp3[1]}, page)

        # ------------------------------------------------------------ A21: arayüzden tam sıfırlama → boş katalog → yeni alan
        (data / "charts").mkdir(exist_ok=True)
        (data / "charts" / "eski.png").write_bytes(b"png")
        page.click("#btn-wipe")
        page.wait_for_selector("#wp-code", timeout=30000)
        code = page.eval_on_selector("#wp-code", "e => e.previousElementSibling.textContent")
        modal = page.text_content("#gm-body") or ""
        record("a21-onizleme", "pencere hedefleri (veritabanı, grafikler), korunanı, boş katalog seçimini ve onay kodunu gösterir",
               bool(code) and "veritabanı" in modal and "grafikler" in modal and not page.is_checked("#wp-cat"),
               {"kod_var": bool(code), "boş_katalog": not page.is_checked("#wp-cat"), "metin": modal[:240]}, page)
        page.fill("#wp-code", code)
        page.click("#wp-go")
        page.wait_for_function("document.querySelector('#gm-body').textContent.includes('Durum') && !document.querySelector('#wp-go')", timeout=180000)
        result = page.text_content("#gm-body") or ""
        series_after = db_query(db, "SELECT count(*) FROM meta.series")[0][0]
        setting = db_query(db, "SELECT * FROM meta.lakehouse_setting")
        record("a21-sifirlama", "arayüzde 'tamamlandı'; DB'de seri 0 ve katalog kipi none; eski grafik ve yüklemeler yok; ekran temiz",
               "tamamlandı" in result and series_after == 0 and "none" in json.dumps(setting) and not (data / "charts" / "eski.png").exists()
               and not Path(p_acil).exists() and page.locator(".a").count() == 0,
               {"sonuç": result[:300], "seri": series_after, "ayar": setting}, page)
        record("a21-korunan", "veri kökü dışındaki kontrol dosyası ve asıl demo DB değişmedi",
               control.read_text(encoding="utf-8").startswith("K01-T07 kontrol") and sha256(demo_db) == meta["demo_db_sha256_once"],
               {"kontrol": control.exists(), "demo_db_aynı": sha256(demo_db) == meta["demo_db_sha256_once"]})
        page.keyboard.press("Escape")
        if page.is_visible("#gm-body"):
            page.evaluate("document.getElementById('gmodal').hidden = true")
        p_ziyaret = upload(FIX / "web_ziyaret_kirilma.csv")
        ask("web_ziyaret_kirilma.csv dosyasını taslak seri olarak ekle; birim ziyaret, ölçüm tipi count, aylık kural avg.", [
            call("ingest_from_url", locator=p_ziyaret, name="Günlük web ziyareti (aylık)", series_key="web_ziyaret", unit="ziyaret",
                 measure_type="count", default_agg="avg"),
            say("Taslak eklendi."),
        ])
        ask("web_ziyaret taslağını onaylıyorum, kataloğa al.", [call("promote_draft", series_id="adhoc:web_ziyaret", purpose="terfi"),
                                                                say("Kataloğa alındı.")])
        catalog_new = db_query(db, "SELECT series_id, status FROM meta.series ORDER BY 1")
        st2 = api.get(f"{url}/api/status").json()
        record("a21-yeni-alan", "boş katalogdan yeni alan arayüzden: yalnız adhoc:web_ziyaret aktif, durum sayacı buna göre",
               catalog_new == [("adhoc:web_ziyaret", "active")] and st2.get("catalog_series") == 1 and st2.get("loaded_series") == 1,
               {"katalog": catalog_new, "durum_katalog": st2.get("catalog_series"), "durum_yüklü": st2.get("loaded_series"),
                                                                  "ekran_katalog": page.text_content("#st-catalog")}, page)
        shown = page.locator(".a").count()
        page.reload()
        page.wait_for_function("document.querySelector('#pill-model') && document.querySelector('#pill-model').textContent.length > 3", timeout=30000)
        page.wait_for_function(f"document.querySelectorAll('.a').length === {len(answers())}", timeout=30000)
        record("sayfa-yenileme", "sayfa yenilenince oturumdaki cevaplar sunucudan yeniden kurulur; profil korunur",
               page.locator(".a").count() == len(answers()) == shown and "Architect" in (page.text_content("#pill-profile") or ""),
               {"önce": shown, "sonra": page.locator(".a").count(), "api": len(answers())}, page)
        browser.close()

    server.should_exit = True
    thread.join(timeout=10)
    passed = sum(s["ok"] for s in steps)
    meta["demo_db_sha256_sonra"] = sha256(demo_db)
    (out / "rapor.json").write_text(json.dumps({"meta": meta, "passed": passed, "total": len(steps), "steps": steps},
                                               ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSONUÇ: {passed}/{len(steps)} · {out}")
    return 0 if passed == len(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
