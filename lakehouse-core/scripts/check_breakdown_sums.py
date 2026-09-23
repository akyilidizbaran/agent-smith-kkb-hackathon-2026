"""Reconcile additive totals with their maturity buckets in a built lakehouse (ADR-0108).

Read-only. Exit code 1 when any month disagrees beyond the source's rounding, so the check can
gate a build. Incomplete months (a bucket or the total missing) are listed but do not fail the
run: a gap is reported, never filled.

Usage (from lakehouse-core/):

    uv run python scripts/check_breakdown_sums.py --database ../data/lakehouse.duckdb
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.lakehouse.quality.breakdown import check_additive_breakdowns  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--prefix", default="vade_ay=", help="dimension_path öneki (varsayılan: vade kovaları)")
    args = parser.parse_args()

    con = duckdb.connect(str(args.database), read_only=True)
    try:
        report = check_additive_breakdowns(con, dimension_prefix=args.prefix)
    finally:
        con.close()

    print(f"toplam seri: {report.parents_checked} · karşılaştırılan ay: {report.months_compared}")
    print(f"uyumsuz ay: {len(report.mismatches)} · eksik ay: {len(report.incomplete)}")
    for issue in report.mismatches[:20]:
        print(f"  UYUMSUZ {issue.parent_series_id} {issue.observation_date}: toplam={issue.total} "
              f"kovalar={issue.children_sum} fark={issue.difference}")
    for issue in report.incomplete[:20]:
        print(f"  EKSİK   {issue.parent_series_id} {issue.observation_date}: "
              f"{issue.children_present}/{issue.children_expected} kova, toplam={issue.total}")
    return 1 if report.mismatches or report.parents_checked == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
