"""Golden set koşucusu.

Kullanım:
    python scripts/run_golden.py                  # tümü, tek geçiş
    python scripts/run_golden.py G2 G4            # seçili vakalar
    python scripts/run_golden.py --repeat 5       # KARARLILIK ölçümü
    python scripts/run_golden.py --json out.json

Neden --repeat: LLM tabanlı bir sistemde tek koşu bir ŞANS örneğidir. Aynı vaka
bir koşuda geçip diğerinde kalabiliyor; "düzeldi" demek için geçme ORANINA
bakmak gerekir. Demo günü jüri önünde tek deneme hakkımız olacak, dolayısıyla
%60 geçen bir vaka geçmiş sayılmaz.

Çıktı: vaka bazında geçti/kaldı + neden, ve toplu metrikler (süre, adım sayısı,
araç kullanımı, hata oranı). Her değişiklikten sonra koşulup önceki sonuçla
karşılaştırılmalıdır — "iyileştirdim" iddiasının tek objektif kanıtı budur.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.golden.cases import CASES, GoldenCase  # noqa: E402

from kkb_agent.cli import build_agent  # noqa: E402


@dataclass
class StabilityReport:
    """Bir vakanın N tekrardaki davranışı."""

    id: str
    runs: int
    passed: int
    durations: list[float] = field(default_factory=list)
    step_counts: list[int] = field(default_factory=list)
    failure_reasons: dict[str, int] = field(default_factory=dict)
    tool_paths: set[str] = field(default_factory=set)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.runs if self.runs else 0.0

    @property
    def verdict(self) -> str:
        r = self.pass_rate
        if r == 1.0:
            return "KARARLI"
        if r == 0.0:
            return "BAŞARISIZ"
        return "KARARSIZ"


@dataclass
class CaseOutcome:
    id: str
    passed: bool
    duration_s: float
    steps: int
    tools_used: list[str] = field(default_factory=list)
    tool_errors: int = 0
    failures: list[str] = field(default_factory=list)
    answer_preview: str = ""


def run_case(case: GoldenCase) -> CaseOutcome:
    agent = build_agent(max_steps=12)  # her vaka temiz durumla başlar
    started = time.perf_counter()

    answer = agent.ask(case.question)
    steps = list(answer.steps)
    if case.follow_up:
        answer = agent.ask(case.follow_up)
        steps += answer.steps

    duration = time.perf_counter() - started
    tools = [s.tool_name for s in steps if s.tool_name]
    errors = sum(1 for s in steps if s.tool_name and not s.ok)
    failures: list[str] = []

    table = agent.workspace.table
    if case.expect_no_table:
        # Halüsinasyon testi: veri yoksa uydurulmuş bir tablo da olmamalı.
        if table is not None and not table.empty:
            failures.append("kapsam dışı soruya rağmen tablo üretildi")
    else:
        if table is None or table.empty:
            failures.append("analiz tablosu üretilmedi")
        else:
            for label, check in case.table_checks:
                try:
                    if not check(table):
                        failures.append(f"tablo kontrolü başarısız: {label}")
                except Exception as exc:
                    failures.append(f"tablo kontrolü hata verdi ({label}): {exc}")

    for needed in case.must_use_tools:
        if needed not in tools:
            failures.append(f"'{needed}' aracı hiç kullanılmadı (kullanılanlar: {', '.join(tools)})")

    low = answer.text.lower()
    for needle in case.answer_must_contain:
        if needle.lower() not in low:
            failures.append(f"cevapta '{needle}' geçmiyor")
    for needle in case.answer_must_not_contain:
        if needle.lower() in low:
            failures.append(f"cevapta olmaması gereken '{needle}' geçiyor")

    tool_steps = len([s for s in steps if s.tool_name])
    if tool_steps > case.max_steps_used:
        failures.append(f"çok fazla adım: {tool_steps} > {case.max_steps_used}")

    return CaseOutcome(
        id=case.id,
        passed=not failures,
        duration_s=round(duration, 1),
        steps=tool_steps,
        tools_used=tools,
        tool_errors=errors,
        failures=failures,
        answer_preview=answer.text[:200].replace("\n", " "),
    )


def run_stability(cases: list[GoldenCase], repeat: int) -> list[StabilityReport]:
    """Her vakayı N kez koşup geçme oranını ölçer."""
    reports: list[StabilityReport] = []
    for case in cases:
        rep = StabilityReport(id=case.id, runs=repeat, passed=0)
        print(f"\n▶ {case.id} — {repeat} tekrar")
        for i in range(1, repeat + 1):
            try:
                o = run_case(case)
            except Exception as exc:
                o = CaseOutcome(
                    id=case.id, passed=False, duration_s=0.0, steps=0,
                    failures=[f"çalıştırma hatası: {type(exc).__name__}"],
                )
            rep.durations.append(o.duration_s)
            rep.step_counts.append(o.steps)
            rep.tool_paths.add(" → ".join(o.tools_used) or "(araç yok)")
            if o.passed:
                rep.passed += 1
            for f in o.failures:
                # Sayısal ayrıntıyı kırp ki aynı hata tek satırda toplansın
                key = f.split(":")[0].strip()
                rep.failure_reasons[key] = rep.failure_reasons.get(key, 0) + 1
            print(f"   {i}/{repeat} {'✓' if o.passed else '✗'} {o.duration_s:.0f}s {o.steps} adım")
        reports.append(rep)
    return reports


def print_stability(reports: list[StabilityReport]) -> None:
    print("\n" + "=" * 72)
    print("KARARLILIK RAPORU")
    print("=" * 72)
    for r in reports:
        avg = sum(r.durations) / max(len(r.durations), 1)
        print(
            f"\n{r.id:26} {r.passed}/{r.runs} ({r.pass_rate:.0%})  {r.verdict}"
            f"  | ort. {avg:.0f}s | adımlar: {r.step_counts}"
        )
        for reason, n in sorted(r.failure_reasons.items(), key=lambda x: -x[1]):
            print(f"     ✗ {n}x {reason}")
        if len(r.tool_paths) > 1:
            print(f"     ⚠ {len(r.tool_paths)} FARKLI araç yolu izlendi:")
            for path in sorted(r.tool_paths):
                print(f"        {path}")

    stable = sum(1 for r in reports if r.verdict == "KARARLI")
    flaky = sum(1 for r in reports if r.verdict == "KARARSIZ")
    broken = sum(1 for r in reports if r.verdict == "BAŞARISIZ")
    print("\n" + "=" * 72)
    print(f"KARARLI: {stable} | KARARSIZ: {flaky} | BAŞARISIZ: {broken}")


def main() -> None:
    argv = sys.argv[1:]
    repeat = 1
    if "--repeat" in argv:
        i = argv.index("--repeat")
        repeat = int(argv[i + 1])
        del argv[i : i + 2]
    json_out = None
    if "--json" in argv:
        i = argv.index("--json")
        json_out = Path(argv[i + 1])
        del argv[i : i + 2]  # değerini de çıkar, yoksa vaka filtresi sanılır
    args = [a for a in argv if not a.startswith("--")]

    selected = [c for c in CASES if not args or any(a in c.id for a in args)]

    if repeat > 1:
        print(f"Kararlılık ölçümü: {len(selected)} vaka × {repeat} tekrar\n" + "=" * 72)
        reports = run_stability(selected, repeat)
        print_stability(reports)
        if json_out:
            json_out.write_text(
                json.dumps(
                    [{**asdict(r), "tool_paths": sorted(r.tool_paths),
                      "pass_rate": r.pass_rate, "verdict": r.verdict} for r in reports],
                    ensure_ascii=False, indent=2,
                ),
                encoding="utf-8",
            )
            print(f"Ayrıntılı sonuç: {json_out}")
        return

    print(f"Golden set: {len(selected)} vaka\n" + "=" * 72)

    outcomes: list[CaseOutcome] = []
    for case in selected:
        print(f"\n▶ {case.id}: {case.question}")
        print(f"  ölçtüğü: {case.why.splitlines()[0]}")
        try:
            outcome = run_case(case)
        except Exception as exc:
            outcome = CaseOutcome(
                id=case.id, passed=False, duration_s=0.0, steps=0,
                failures=[f"çalıştırma hatası: {type(exc).__name__}: {exc}"],
            )
        outcomes.append(outcome)
        mark = "✓ GEÇTİ" if outcome.passed else "✗ KALDI"
        print(
            f"  {mark} | {outcome.duration_s}s | {outcome.steps} adım | "
            f"{outcome.tool_errors} araç hatası | araçlar: {', '.join(outcome.tools_used) or '—'}"
        )
        for f in outcome.failures:
            print(f"    - {f}")

    print("\n" + "=" * 72)
    passed = sum(1 for o in outcomes if o.passed)
    total_time = sum(o.duration_s for o in outcomes)
    avg_steps = sum(o.steps for o in outcomes) / max(len(outcomes), 1)
    print(
        f"SONUÇ: {passed}/{len(outcomes)} geçti | toplam {total_time:.0f}s | "
        f"vaka başına ort. {total_time / max(len(outcomes), 1):.0f}s, {avg_steps:.1f} adım | "
        f"toplam araç hatası: {sum(o.tool_errors for o in outcomes)}"
    )
    if json_out:
        json_out.write_text(
            json.dumps([asdict(o) for o in outcomes], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Ayrıntılı sonuç: {json_out}")


if __name__ == "__main__":
    main()
