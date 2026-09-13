"""Demo kabul testi — tek komut: bootstrap → ingest → silver → gold → senaryo soruları (D4).

    cd agent-core && uv run python scripts/demo_acceptance.py [--root /tmp/kkb_demo_acceptance]
                                                              [--skip-ingest --reuse-db <yol>]

Ne ölçer: sıfırdan bir lakehouse kurulup gerçek kaynaklardan (BDDK, EVDS) demo serileri
çekildiğinde, Silver ve Gold kurulduğunda, agent'ın on bir demo sorusunu geçip geçmediğini —
tablo denetimi, araç yolu, kanıt zinciri, adım ve token ile. Sonuç JSON rapor + çıkış kodu.

Veri ekibinin komutları ayrı süreçte çağrılır (`python -m lakehouse …`,
`scripts/run_catalog_ingestion.py --only …`); agent paketi lakehouse-core'u import etmez.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

_MONTHLY_ITEMS = (1534, 1533, 1535, 1536, 1539, 1543, 1544, 1545, 1546, 1547, 1548,
                  1160, 1676, 1688, 1717, 1357, 1344)
_MONTHLY_RATIOS = (544, 1749, 1746)
_EVDS = ("TP.KTF12", "TP.DK.USD.A.YTL", "TP.DK.EUR.A.YTL", "TP.BISPOLFAIZ.TUR", "TP.APIFON4",
         "TP.TRY.MT02", "TP.KKHARTUT.KT1", "TP.HPBITABLO1.11", "TP.HPBITABLO1.18", "TP.TUKFIY2025.GENEL")
_PROVINCES = ("ISTANBUL", "ANKARA", "IZMIR", "BURSA", "ANTALYA", "KOCAELI", "KONYA", "ADANA",
              "GAZIANTEP", "MERSIN", "KAYSERI", "TEKIRDAG")
_FINTURK_COLUMNS = ("KonutKredisi", "TasitKredisi", "DigerTuketiciKredileri", "KrediliMevduatHesabi",
                    "BireyselKrediKartlari", "TakiptekiTasitKredisi", "TakiptekiKonutKredisi",
                    "TakiptekiDigerTuketiciKredileri")
DEMO_SERIES = (
    *(f"bddk_monthly:{i}_Toplam" for i in _MONTHLY_ITEMS),
    *(f"bddk_monthly:{i}_Rasyo" for i in _MONTHLY_RATIOS),
    "bddk_weekly:5690_3",
    *(f"evds:{c}" for c in _EVDS),
    *(f"bddk_finturk:{p}_{c}" for p in _PROVINCES for c in _FINTURK_COLUMNS),
)
"""Demo serileri (13 Eyl, veri genişliği): 20 BDDK aylık kalem (bakiye + oran), haftalık konut, 10 EVDS
(konut faizi, kur, politika faizi, AOFM, mevduat faizi, kart harcaması, M2/M3, TÜFE) ve 12 ilin 8'er
FinTürk sütunu (bir ilin 8 serisi tek çekiliştir). Toplam 127 seri, ~43 çekiliş grubu."""

SCENARIO_CASES = (
    "G1_tek_deger",          # 1. tek değer, kaynak gösterimi
    "G2_aylik_seri",         # 2. aylık seri, 12 satır
    "G14_tabloyu_bozmadan_gold_sutunu",   # 3. tabloyu bozmadan sütun ekleme (Gold faiz tablosundan; G6 seed'e özgü)
    "G8_ingest_ve_sorgu",    # 4. jüri dosyası: ingest + belge + sorgu (Architect)
    "G9_gold_ceyreklik_ve_red",  # 5. Gold: çeyreklik + yanlış öncül reddi
    "G10_grafik",            # 6. grafik + denetçi
    "G11a_web_var",          # 7. dış kaynak: kullanıcının verdiği sayfa
    "G13_enjeksiyon",        # 8. gömülü talimat: niyet kapısı
    "G15_aykiri_ay",         # 9. anomali aracı (ADR-0040): aylık değişimde IQR, sebep uydurma yok
    "G17_onculuk",           # 10. öncül-ardıl aracı: iki seri tek tabloda, Granger, "nedensellik değil"
    "G18a_pdf_altin_ithalat", # 11. demo slaytı: Borsa İstanbul altın PDF'inden değer (OCR, ADR-0041)
)


@dataclass
class StepResult:
    name: str
    ok: bool
    seconds: float
    detail: str = ""


@dataclass
class Report:
    root: str
    steps: list[StepResult] = field(default_factory=list)
    cases: list[dict] = field(default_factory=list)
    passed: int = 0
    total: int = 0

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps) and self.passed == self.total and self.total > 0


def _run(cmd: list[str], cwd: Path, *, timeout: float = 1800) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout, env=env)
    return proc.returncode, (proc.stdout + proc.stderr)


def build_commands(root: Path, core_dir: Path, *, launcher: str = "uv run python") -> list[tuple[str, list[str]]]:
    """Veri ekibi komutları, sırayla. Test edilebilir: yürütmez, planlar."""
    db, data = root / "data" / "lakehouse.duckdb", root / "data"
    L = launcher.split()
    return [
        ("bootstrap", [*L, "-m", "lakehouse", "bootstrap", "--database", str(db), "--data-root", str(data)]),
        ("ingest (canlı: BDDK + EVDS)", [*L, "scripts/run_catalog_ingestion.py", "--database", str(db),
                                          "--data-root", str(data), "--only", ",".join(DEMO_SERIES)]),
        ("silver", [*L, "-m", "lakehouse", "silver", "--database", str(db), "--data-root", str(data)]),
        ("gold", [*L, "-m", "lakehouse", "gold", "--database", str(db), "--data-root", str(data)]),
    ]


def _stage_incoming(root: Path) -> Path:
    """Jüri dosyası ve web fikstürleri izinli köke: G8 ve G11/G13 bunları okur."""
    incoming = root / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    (incoming / "konut_test.csv").write_text(
        "Tarih;Konut Kredisi (milyon TL)\n31.01.2025;1.234,5\n28.02.2025;1.300,0\n31.03.2025;1.402,75\n"
        "30.04.2025;1.450,1\n31.05.2025;1.500,0\n30.06.2025;1.560,9\n", encoding="utf-8")
    fixtures = ROOT / "tests" / "golden" / "fixtures"
    for f in [*fixtures.glob("*.html"), *fixtures.glob("*.pdf")]:
        shutil.copy(f, incoming / f.name)
    return incoming


def main() -> int:
    ap = argparse.ArgumentParser(description="Demo kabul testi: bootstrap → ingest → silver → gold → 11 senaryo")
    ap.add_argument("--root", type=Path, default=Path("/tmp/kkb_demo_acceptance"))
    ap.add_argument("--core-dir", type=Path, default=Path(os.getenv("LAKEHOUSE_CORE_DIR", ROOT.parent / "lakehouse-core")))
    ap.add_argument("--launcher", default=os.getenv("LAKEHOUSE_CLI", "uv run python"))
    ap.add_argument("--skip-ingest", action="store_true", help="veri adımlarını atla; --reuse-db ile mevcut DB")
    ap.add_argument("--reuse-db", type=Path, default=None, help="mevcut lakehouse.duckdb (skip-ingest ile)")
    ap.add_argument("--fresh", action="store_true", help="--root altını sil ve sıfırdan kur")
    ap.add_argument("--cases", default=",".join(SCENARIO_CASES), help="virgülle vaka kimlikleri")
    args = ap.parse_args()

    root: Path = args.root
    if args.fresh and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    report = Report(root=str(root))
    core_dir: Path = args.core_dir
    print(f"DEMO KABUL — kök {root} · lakehouse-core {core_dir}")

    if not (core_dir / "src" / "lakehouse" / "cli.py").is_file():
        print(f"✗ lakehouse-core bulunamadı: {core_dir} (LAKEHOUSE_CORE_DIR)")
        return 2

    db_path = root / "data" / "lakehouse.duckdb"
    if args.skip_ingest:
        if args.reuse_db:
            db_path = args.reuse_db
        report.steps.append(StepResult("veri adımları", True, 0.0, f"atlandı; DB: {db_path}"))
        print(f"– veri adımları atlandı; DB: {db_path}")
    else:
        # Güvenlik kilidi: veri ekibinin katalog betiği filtre seçeneğini tanımıyorsa bütün
        # kataloğu (1.600+ seri) canlı çekmeye kalkar. Ölçüldü: bir kez oldu, durduruldu.
        code, help_text = _run([*args.launcher.split(), "scripts/run_catalog_ingestion.py", "--help"], core_dir, timeout=120)
        if code != 0 or "--only" not in help_text:
            print("✗ run_catalog_ingestion.py '--only' seçeneğini tanımıyor; filtresiz canlı ingest ÇALIŞTIRILMAZ.")
            report.steps.append(StepResult("ingest güvenlik kilidi", False, 0.0, help_text[-400:]))
            _write(report, root)
            return 2
        for name, cmd in build_commands(root, core_dir, launcher=args.launcher):
            started = time.perf_counter()
            code, out = _run(cmd, core_dir)
            secs = time.perf_counter() - started
            tail = "\n".join(out.strip().splitlines()[-6:])
            ok = code == 0
            report.steps.append(StepResult(name, ok, round(secs, 1), tail[-600:]))
            print(f"{'✓' if ok else '✗'} {name} ({secs:.0f} s)")
            for line in tail.splitlines():
                print(f"    {line}")
            if not ok:
                _write(report, root)
                return 1

    incoming = _stage_incoming(root)
    os.environ["LAKEHOUSE_PATH"] = str(db_path)
    os.environ["LAKEHOUSE_CORE_DIR"] = str(core_dir)
    os.environ["INGEST_ALLOWED_ROOT"] = str(incoming)
    os.environ["CHART_DIR"] = str(root / "charts")

    # Senaryolar: golden koşucusunun kendisi (aynı denetimler, aynı rapor).
    from scripts.run_golden import run_case  # noqa: E402
    from tests.golden import cases as golden_cases  # noqa: E402

    wanted = [c.strip() for c in args.cases.split(",") if c.strip()]
    by_id = {c.id: c for c in golden_cases.CASES}
    missing = [w for w in wanted if w not in by_id]
    if missing:
        print(f"✗ bilinmeyen vaka: {', '.join(missing)}")
        return 2
    print(f"\nSENARYOLAR ({len(wanted)}):")
    for cid in wanted:
        case = by_id[cid]
        # yerel fikstür yolları izinli köke göre yeniden kurulur
        if "_fixture(" in case.question or str(golden_cases._INCOMING) in case.question:
            case.question = case.question.replace(str(golden_cases._INCOMING), str(incoming))
        outcome = run_case(case)
        report.total += 1
        report.passed += int(outcome.passed)
        row = asdict(outcome)
        report.cases.append(row)
        mark = "✓" if outcome.passed else "✗"
        print(f"{mark} {cid}: {outcome.steps} adım, {outcome.duration_s:.0f} s, prompt {outcome.prompt_tokens} token, "
              f"kanıt {outcome.evidence}" + (f" | {'; '.join(outcome.failures)}" if outcome.failures else ""))

    _write(report, root)
    print(f"\nSONUÇ: {report.passed}/{report.total} senaryo geçti · rapor {root / 'acceptance_report.json'}")
    return 0 if report.ok else 1


def _write(report: Report, root: Path) -> None:
    (root / "acceptance_report.json").write_text(
        json.dumps({"root": report.root, "ok": report.ok, "steps": [asdict(s) for s in report.steps],
                    "passed": report.passed, "total": report.total, "cases": report.cases},
                   ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


if __name__ == "__main__":
    sys.exit(main())
