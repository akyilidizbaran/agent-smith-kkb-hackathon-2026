"""K03-T05 / M14-T11 — demo bilgisayarında ekran düzeni: gerçek sunucu, canlı model, iki dizüstü görünüm alanı.

Açık sunucuya bağlanır (make serve). Her görünüm alanında: üç sütun ve soru kutusu ekranda, yatay kaydırma yok; canlı iki
soru; sol listeden eski cevap açılınca iz ve kanıt o cevaba döner; rol rozeti; dışa aktarım bağlantıları eski cevapta da var.
Ekran görüntüleri ve rapor `docs/experiments/k03_ekran_<zaman>/`. Başarısız adım rapordan çıkarılmaz.

    uv run --with playwright python scripts/k03_ekran_kontrol.py --url http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
VIEWPORTS = [(1512, 982), (1280, 800)]   # 15" MacBook varsayılan ölçekli ekran ve küçük dizüstü


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    args = ap.parse_args()
    out = ROOT.parent / "docs" / "experiments" / f"k03_ekran_{datetime.now():%Y-%m-%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    steps: list[dict] = []

    def record(sid: str, ok: bool, observed, page=None) -> None:
        shot = None
        if page is not None:
            shot = out / f"{len(steps) + 1:02d}_{sid}.png"
            page.screenshot(path=str(shot), full_page=False)
        steps.append({"id": sid, "ok": bool(ok), "gozlenen": observed, "ekran": shot.name if shot else None,
                      "at": datetime.now().isoformat(timespec="seconds")})
        print(f"  {'✓' if ok else '✗'} {sid}: {str(observed)[:220]}", flush=True)

    layout_js = """() => {
      const vis = (id) => { const e = document.getElementById(id); if (!e) return null; const r = e.getBoundingClientRect();
        return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
                icinde: r.width > 0 && r.height > 0 && r.left >= 0 && r.right <= innerWidth + 1 && r.top >= 0 && r.bottom <= innerHeight + 1}; };
      return {genislik: innerWidth, yukseklik: innerHeight, yatay_kaydirma: document.documentElement.scrollWidth > innerWidth + 1,
              soru: vis('q'), gonder: vis('btn-ask'), sohbet: vis('thread'), kanit: vis('ev-body'), oturum: vis('session'),
              rol: document.getElementById('pill-profile')?.textContent || ''};
    }"""

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for w, h in VIEWPORTS:
            tag = f"{w}x{h}"
            page = browser.new_page(viewport={"width": w, "height": h}, accept_downloads=True)
            api = page.request
            api.post(f"{args.url}/api/reset")
            page.goto(args.url)
            page.wait_for_function("document.querySelector('#pill-model') && document.querySelector('#pill-model').textContent.length > 3", timeout=30000)
            lay = page.evaluate(layout_js)
            record(f"{tag}_duzen", not lay["yatay_kaydirma"] and all(lay[k] and lay[k]["icinde"] for k in ("soru", "gonder", "kanit", "oturum"))
                   and "Analyst" in lay["rol"], lay, page)

            questions = ["2025 yılında aylık konut kredisi bakiyesini göster.", "Aynı dönemde konut kredisi faiz oranını da göster."]
            for i, q in enumerate(questions):
                page.fill("#q", q)
                page.click("#btn-ask")
                page.wait_for_function(f"document.querySelectorAll('.a').length >= {i + 1} && !document.querySelector('.busy')", timeout=360000)
            answers = api.get(f"{args.url}/api/answers").json()
            lay2 = page.evaluate(layout_js)
            record(f"{tag}_iki_cevap", len(answers) == 2 and not lay2["yatay_kaydirma"] and lay2["soru"]["icinde"],
                   {"cevap": len(answers), "tablolar": [bool(a.get("table")) for a in answers], "yatay_kaydirma": lay2["yatay_kaydirma"]}, page)

            page.locator("#session .session-item").first.click()
            page.wait_for_timeout(600)
            active = page.eval_on_selector("#session .session-item.active", "e => e.dataset.i")
            ev_text = page.text_content("#ev-body") or ""
            first_summary = ((answers[0].get("evidence") or {}).get("summary") or "")[:40]
            box0 = page.locator(".a[data-i='0']")               # #ans-0 sorunun kutusu; cevap kutusu data-i taşır
            links0 = box0.locator("a[href^='/api/answers/0/']").evaluate_all("els => els.map(e => e.getAttribute('href'))") if box0.count() else []
            in_view = page.evaluate("() => { const e = document.getElementById('ans-0'); if (!e) return false; const r = e.getBoundingClientRect(); return r.top < innerHeight && r.bottom > 0; }")
            record(f"{tag}_eski_cevap", active == "0" and in_view and any(l.endswith("table.csv") for l in links0) and any(l.endswith("report.html") for l in links0),
                   {"aktif": active, "görünür": in_view, "bağlantılar": sorted(set(links0)), "kanıt_paneli_ilk_40": ev_text[:40], "cevap0_kanıt_özeti": first_summary}, page)
            page.close()
        browser.close()

    passed = sum(s["ok"] for s in steps)
    (out / "rapor.json").write_text(json.dumps({"meta": {"commit": commit, "url": args.url, "at": datetime.now().isoformat(timespec="seconds"),
                                                         "gorunum_alanlari": [f"{w}x{h}" for w, h in VIEWPORTS]},
                                                "passed": passed, "total": len(steps), "steps": steps}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSONUÇ: {passed}/{len(steps)} · {out}")
    return 0 if passed == len(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
