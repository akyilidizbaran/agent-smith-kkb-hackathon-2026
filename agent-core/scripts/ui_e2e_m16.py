"""M16-T08/T09 arayüz uçtan uca provası: gerçek tarayıcı, gerçek sunucu, canlı model.

Açık sunucuya (make serve) bağlanır; soru sorar, cevap kutusunu, tabloyu, dışa aktarım bağlantılarını ve
indirilen CSV/XLSX/HTML içeriğini API tablosuyla karşılaştırır; dosya yükler ve yüklenen dosyayı sorar;
anahtarsız profil geçişinin reddini ve oturum sıfırlamayı dener. Her ekran görüntüsünün adı adım, raporda
URL, zaman, commit, model ve veri kökü var. Başarısız adım rapordan çıkarılmaz.

    uv run --with playwright python scripts/ui_e2e_m16.py [--url http://localhost:8765] [--chromium <yol>]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "generic"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8765")
    ap.add_argument("--chromium", default=None, help="önbellekteki Chromium yürütülebilir dosyası (indirme yapılmaz)")
    ap.add_argument("--question", default="2025 yılında aylık konut kredisi bakiyesini göster.")
    args = ap.parse_args()
    stamp = f"{datetime.now():%Y-%m-%d_%H%M}"
    out = ROOT.parent / "docs" / "experiments" / f"ui_e2e_m16_{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    steps: list[dict] = []

    def record(name: str, ok: bool, detail: str, page=None, t0: float | None = None) -> None:
        shot = None
        if page is not None:
            shot = out / f"{len(steps) + 1:02d}_{name}.png"
            page.screenshot(path=str(shot), full_page=True)
        steps.append({"step": name, "ok": bool(ok), "detail": detail, "url": page.url if page else args.url,
                      "at": datetime.now().isoformat(timespec="seconds"),
                      "seconds": round(time.perf_counter() - t0, 1) if t0 else None,
                      "screenshot": shot.name if shot else None})
        print(f"  {'✓' if ok else '✗'} {name}: {detail}", flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.chromium) if args.chromium else pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 960}, accept_downloads=True)
        api = page.request

        t0 = time.perf_counter()
        page.goto(args.url)
        page.wait_for_function("document.querySelector('#pill-model') && document.querySelector('#pill-model').textContent.length > 3", timeout=20000)
        status = api.get(f"{args.url}/api/status").json()
        api.post(f"{args.url}/api/reset")
        page.reload()
        record("acilis", bool(status.get("model")), f"model={status.get('model')} profil={status.get('profile')} "
               f"hazır={status.get('readiness')}", page, t0)

        # 1) soru → cevap kutusu, tablo, dışa aktarım bağlantıları
        t0 = time.perf_counter()
        page.fill("#q", args.question)
        page.click("#btn-ask")
        page.wait_for_selector(".a", timeout=360000)
        page.wait_for_function("!document.querySelector('.busy')", timeout=360000)
        links = page.eval_on_selector_all("a[href^='/api/answers/']", "els => els.map(e => e.getAttribute('href'))")
        ans = api.get(f"{args.url}/api/answers/0").json()
        has_table = page.locator(".a .box table").count() > 0
        record("soru_cevap", has_table and any(l.endswith("table.csv") for l in links),
               f"tablo={has_table} bağlantılar={sorted(set(links))} kanıt={bool(ans.get('evidence'))}", page, t0)

        # 2) indirilen dosyalar gerçekten tam tablo mu (M16-T09)
        t0 = time.perf_counter()
        rows_api = (ans.get("table") or {}).get("row_count") if isinstance(ans.get("table"), dict) else None
        csv_resp = api.get(f"{args.url}/api/answers/0/table.csv")
        text = csv_resp.body().decode("utf-8-sig")
        reader = list(csv.reader(io.StringIO(text), delimiter=";"))
        xlsx = load_workbook(io.BytesIO(api.get(f"{args.url}/api/answers/0/table.xlsx").body()), read_only=True)
        sheets = xlsx.sheetnames
        xrows = xlsx[sheets[0]].max_row
        html = api.get(f"{args.url}/api/answers/0/report.html").text()
        ok = csv_resp.ok and len(reader) >= 13 and rows_api is not None and len(reader) - 1 == rows_api and xrows >= 13 and "<table" in html
        (out / "cevap0.csv").write_text(text, encoding="utf-8")
        (out / "cevap0_report.html").write_text(html, encoding="utf-8")
        record("disa_aktarim", ok, f"csv satır={len(reader) - 1} (başlık hariç) xlsx sayfalar={sheets} satır={xrows - 1} "
               f"api önizleme satır={rows_api} rapor_html={len(html)} bayt", None, t0)

        # 3) dosya yükleme → yüklenen dosyayı sor
        t0 = time.perf_counter()
        page.set_input_files("#file", str(FIX / "nufus_il.csv"))
        page.wait_for_function("[...document.querySelectorAll('#attach .chip')].some(c => c.textContent.includes('📎') || c.className.includes('err'))", timeout=30000)
        chip = page.locator("#attach .chip").last.text_content() or ""
        record("dosya_yukleme", "📎" in chip, chip.strip(), page, t0)

        t0 = time.perf_counter()
        page.fill("#q", "Bu dosyadaki en kalabalık il hangisi?")
        page.click("#btn-ask")
        page.wait_for_function("document.querySelectorAll('.a').length >= 2 && !document.querySelector('.busy')", timeout=360000)
        second = api.get(f"{args.url}/api/answers/1").json()
        txt = str(second.get("text") or second.get("answer") or "")
        # Beklenen, fikstürün kendisinden: en büyük sayısal değerli satırın ilk metin hücresi (ezber yok).
        import pandas as pd
        fx = pd.read_csv(FIX / "nufus_il.csv", sep=";", thousands=".")
        num = fx.select_dtypes("number").columns[0]
        name_col = [c for c in fx.columns if not pd.api.types.is_numeric_dtype(fx[c])][0]
        expected = str(fx.loc[fx[num].idxmax(), name_col])
        record("yuklenen_dosyayi_sor", expected.casefold() in txt.casefold(), f"beklenen={expected} · {txt[:200]}".replace("\n", " "), page, t0)

        # 4) anahtarsız profil geçişi reddedilir (A21)
        t0 = time.perf_counter()
        r = api.post(f"{args.url}/api/profile", data={"profile": "architect", "token": ""})
        record("anahtarsiz_architect_red", r.status in (401, 403), f"HTTP {r.status}", None, t0)

        # 5) oturum sıfırlama arayüzden
        t0 = time.perf_counter()
        page.click("#btn-reset")
        page.wait_for_function("document.querySelectorAll('.a').length === 0", timeout=10000)
        left = api.get(f"{args.url}/api/answers").json()
        record("oturum_sifirlama", len(left) == 0, f"kalan cevap={len(left)}", page, t0)
        browser.close()

    passed = sum(s["ok"] for s in steps)
    report = {"meta": {"commit": commit, "url": args.url, "model": status.get("model"), "data": status.get("lakehouse") or status.get("db"),
                       "at": datetime.now().isoformat(timespec="seconds")}, "passed": passed, "total": len(steps), "steps": steps}
    (out / "rapor.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSONUÇ: {passed}/{len(steps)} adım · {out}")
    return 0 if passed == len(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
