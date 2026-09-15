"""Bağlam senaryoları: çok turlu sohbette kullanım/kimlik sorusu önceki soruya kayıyor mu? (15 Eyl, ADR-0081)

Gerçek web uygulaması (`/api/ask`), gerçek harness ve araçlar, GERÇEK model; demo DB'nin geçici kopyası (asıl DB'ye dokunulmaz).
Web araması kapalı (dış arama yapılmaz, sonuçlar karşılaştırılabilir). Her senaryo `--tekrar` kez, aralarında oturum sıfırlanır.
Her tur için otomatik denetim + cevap metni rapora yazılır (elle okuma için).

    uv run python scripts/baglam_senaryolari.py --work /tmp/baglam [--tekrar 3]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

from scripts.k01_kabul import sha256  # noqa: E402


def nudged(p: dict) -> bool:
    return any("veri çekilmeden" in (s.get("thought") or "") for s in p.get("steps", []))


def tools(p: dict) -> list[str]:
    return [s["tool"] for s in p.get("steps", []) if s.get("tool")]


def llm_called(p: dict) -> bool:
    return not any("LLM çağrılmadı" in (s.get("thought") or "") for s in p.get("steps", []))


def columns(p: dict) -> list[str]:
    return list((p.get("table") or {}).get("columns") or [])


_AMOUNT = re.compile(r"(?<![\d.,])\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\d.,])")


def amounts_only(p: dict, allowed: set[str]) -> bool:
    """Cevaptaki binlik ayraçlı her tutar izin verilen (veriden bilinen) tutarlardan biri mi?"""
    return all(a in allowed for a in _AMOUNT.findall(p.get("text", "")))


DATASET_LISTING = ("BDDK FinTürk (il bazında):", "Veri havuzunda şu kaynaklardan yüklü seriler var")


def not_dataset_listing(p: dict) -> bool:
    """Önceki 'elimizde hangi veriler var' cevabının tekrarı değil (kullanıcının gördüğü kayma)."""
    text = p.get("text", "")
    return not any(m in text for m in DATASET_LISTING) and "| Kaynak |" not in text


SCENARIOS: list[tuple[str, list[tuple[str, str, object]]]] = [
    ("S1_kullanici_akisi", [
        ("naber", "selamlaşma, model çağrılmaz", lambda p: not llm_called(p)),
        ("elimizde hangi veriler var", "veri setleri katalogdan", lambda p: "BDDK" in p["text"] and not llm_called(p)),
        ("architect rolüne nasıl geçebilirim", "rol cevabı; önceki soruya kaymaz, geri gönderilmez, veri aracı yok",
         lambda p: "Profil rozetine" in p["text"] and not_dataset_listing(p) and not nudged(p) and not tools(p)),
    ]),
    ("S2_kullanim_arasi_sonra_takip", [
        ("2025 yılında aylık konut kredisi bakiyesini göster.", "12 aylık tablo araçla",
         lambda p: bool(tools(p)) and (p.get("table") or {}).get("row_count", 0) >= 12),
        ("Bunu nasıl indirebilirim?", "indirme cevabı (CSV/XLSX); tablo sorgusu yok",
         lambda p: "CSV" in p["text"] and not tools(p)),
        ("Peki aynı dönemin konut kredisi faiz oranını da ekle.", "bağlam korunur: 2025 tablosuna faiz kolonu",
         lambda p: bool(tools(p)) and any("faiz" in c.lower() or "rate" in c.lower() for c in columns(p))),
    ]),
    ("S3_modele_giden_kullanim_sonra_takip", [
        ("2025 Aralık ayında konut kredisi bakiyesi ne kadar?", "sayı araçla", lambda p: bool(tools(p))),
        ("Kanıt zincirini nasıl okurum?", "kanıt zinciri anlatılır; bakiye tekrar sorgulanmaz",
         lambda p: "kanıt" in p["text"].lower() and "lakehouse_query" not in tools(p) and not nudged(p)),
        # İlk koşunun zayıf denetimi yalnız "kasım/fark" sözcüğüne bakıyordu ve uydurma "677.970 / +1.000" cevabını geçirdi (15 Eyl).
        # Tutarlar demo DB'den: Kasım 658.770, Aralık 678.970, fark 20.200 milyon TL. Cevaptaki her tutar bunlardan biri olmalı.
        ("Bir önceki aya göre farkı ne?", "bağlam korunur; tutarlar gerçek (Kasım 658.770, fark 20.200), uydurma sayı yok",
         lambda p: not nudged(p) and amounts_only(p, {"678.970", "658.770", "20.200"})
         and ("20.200" in p["text"] or "üretemedim" in p["text"])),
    ]),
    ("S4_tablosuz_kimlik_ve_belirsiz", [
        ("Sen kimsin?", "kimlik; geri gönderilmez", lambda p: not nudged(p) and "önceki mesaj" not in p["text"].lower()),
        ("Bu sistemi kim geliştirdi?", "önceki soruya kaymaz (kimlik cevabını ya da veri listesini tekrarlamaz)",
         lambda p: not_dataset_listing(p) and "önceki mesaj" not in p["text"].lower()),
        ("Grafiği nasıl indiririm?", "indirme cevabı (PNG)", lambda p: "PNG" in p["text"] and not tools(p)),
    ]),
    ("S5_veri_listesi_sonrasi_kullanim", [
        ("elimizde hangi veriler var", "veri setleri katalogdan", lambda p: "BDDK" in p["text"]),
        ("Oturumu nasıl sıfırlarım?", "sıfırlama cevabı: 'Oturumu sıfırla' düğmesi; veri listesini tekrarlamaz, sorgu yok",
         lambda p: "'Oturumu sıfırla' düğmesi" in p["text"] and not_dataset_listing(p) and not nudged(p) and not tools(p)),
        ("Dosyayı nasıl yüklerim?", "yükleme cevabı (türler, 25 MB)", lambda p: "25 MB" in p["text"] and not tools(p)),
    ]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--tekrar", type=int, default=3)
    ap.add_argument("--senaryo", action="append", help="yalnız bu senaryo(lar), ör. S3_modele_giden_kullanim_sonra_takip")
    args = ap.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    data = work / "data"
    (data / "incoming").mkdir(parents=True)
    demo_db = REPO / "data" / "lakehouse.duckdb"
    demo_before = sha256(demo_db)
    db = data / "lakehouse.duckdb"
    shutil.copy2(demo_db, db)
    os.environ.update({
        "DATA_ROOT": str(data), "LAKEHOUSE_PATH": str(db), "INGEST_ALLOWED_ROOT": str(data / "incoming"),
        "CHART_DIR": str(data / "charts"), "EMBEDDING_CACHE_DIR": str(data / "cache"), "AGENT_PROFILE": "analyst",
        "LAKEHOUSE_MODE": "demo", "VISION_MODEL": "", "TAVILY_API_KEY": "", "ARCHITECT_TOKEN": "",
    })
    sys.path.insert(0, str(ROOT / "src"))
    from fastapi.testclient import TestClient

    from kkb_agent.web_app import build_default_app

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPO).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "agent-core/src"], capture_output=True, text=True, cwd=REPO).stdout.strip())
    client = TestClient(build_default_app())
    model = client.get("/api/status").json().get("model")
    print(f"Bağlam senaryoları — commit {commit}{' (kaynak ağacı kirli)' if dirty else ''} · model {model}")
    runs, passed, total = [], 0, 0
    for name, turns in SCENARIOS:
        if args.senaryo and name not in args.senaryo:
            continue
        for rep in range(1, args.tekrar + 1):
            client.post("/api/reset")
            rows = []
            for question, expected, check in turns:
                started = time.perf_counter()
                r = client.post("/api/ask", json={"question": question})
                p = r.json() if r.status_code == 200 else {"text": f"HTTP {r.status_code}: {r.text[:200]}", "steps": []}
                try:
                    ok = bool(r.status_code == 200 and check(p))
                except Exception as exc:  # noqa: BLE001 — denetim hatası da kırmızıdır
                    ok = False
                    expected += f" (denetim hatası {type(exc).__name__})"
                total += 1
                passed += ok
                rows.append({"soru": question, "beklenen": expected, "ok": ok, "sure_s": round(time.perf_counter() - started, 1),
                             "llm": llm_called(p), "geri_gonderildi": nudged(p), "araclar": tools(p), "tablo_kolonlari": columns(p),
                             "adimlar": [(s.get("role"), s.get("tool"), (s.get("thought") or "")[:80]) for s in p.get("steps", [])],
                             # Hata kodu ve kart özeti de: S3 ikinci koşusunda reddedilen lakehouse_query'nin sebebi okunamıyordu.
                             "arac_sonuclari": [{"arac": s.get("tool"), "ok": s.get("ok"), "kod": s.get("error_code"),
                                                 "detay": s.get("detail"), "ozet": (s.get("summary") or "")[:240]}
                                                for s in p.get("steps", []) if s.get("tool")],
                             "cevap": p.get("text", "")[:900]})
                print(f"  {'✓' if ok else '✗'} {name} #{rep} · {question} — {expected} ({rows[-1]['sure_s']} s, araç {tools(p)})", flush=True)
                if not ok:
                    print(f"      cevap: {p.get('text', '')[:300]!r}", flush=True)
            runs.append({"senaryo": name, "tekrar": rep, "turlar": rows})
    demo_after = sha256(demo_db)
    # Saniye ve senaryo seçimi adda: aynı dakikada biten iki koşu (tümü ×3 ve S3 ×5, 15 Eyl 17:56) aynı dosyaya yazıp birini ezdi.
    stamp = f"{datetime.now():%Y-%m-%d_%H%M%S}"
    tag = ("_" + "-".join(s.split("_", 1)[0] for s in args.senaryo)) if args.senaryo else ""
    out = REPO / "docs" / "experiments" / f"baglam_senaryolari_{stamp}{tag}_x{args.tekrar}.json"
    out.write_text(json.dumps({"meta": {"commit": commit, "kaynak_agac_temiz": not dirty, "model": model, "tekrar": args.tekrar,
                                        "web_aramasi": "kapalı", "demo_db_degismedi": demo_after == demo_before,
                                        "at": datetime.now().isoformat(timespec="seconds")},
                               "passed": passed, "total": total, "kosular": runs}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSONUÇ: {passed}/{total} · rapor {out} · demo DB değişmedi: {demo_after == demo_before}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
