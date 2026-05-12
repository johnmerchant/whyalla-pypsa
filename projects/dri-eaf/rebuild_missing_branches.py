"""Rebuild the 2 trajectory branches that were lost / wrong due to the
GGO-workbook bug (cfg.scenario.name was hardcoded "Step Change" while
file_token was overridden to ACCELERATED_TRANSITION / SLOWER_GROWTH).

The 4 step_change branches in the existing trajectory.csv are correct
(name == "Step Change" matched the file_token) — we keep those and append
the rebuilt acce_trans + slower_growth rows.

Usage:
  uv run python rebuild_missing_branches.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from generate_trajectory import YEARS, run_branch


HERE = Path(__file__).parent
OUT_CSV = HERE / "trajectory.csv"

MISSING_BRANCHES = [
    ("Policy-stated + gas flat", "slower_growth"),
    ("Policy-stated + gas flat", "accelerated_transition"),
]


def main() -> None:
    if not OUT_CSV.exists():
        sys.exit(f"Existing {OUT_CSV} not found — run full generate_trajectory.py instead.")
    existing = pd.read_csv(OUT_CSV)
    print(f"Existing trajectory: {len(existing)} rows")
    print(existing.groupby(["scenario", "isp_scenario"]).size().to_string())

    workers = min(len(MISSING_BRANCHES), os.cpu_count() or 1, 2)
    print(f"\nRebuilding {len(MISSING_BRANCHES)} branches × {len(YEARS)} years "
          f"with {workers} workers")
    for p, i in MISSING_BRANCHES:
        print(f"  • {p}  /  {i}")

    new_rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(run_branch, policy, isp, YEARS): (policy, isp)
            for policy, isp in MISSING_BRANCHES
        }
        for future in as_completed(futures):
            policy, isp = futures[future]
            try:
                branch_rows = future.result()
                new_rows.extend(branch_rows)
                print(f"\n[done] {policy}  /  {isp}: {len(branch_rows)} rows")
            except Exception as e:
                print(f"\n[FAIL] {policy} / {isp}: {type(e).__name__}: {e}")

    if not new_rows:
        sys.exit("No new rows produced — nothing to merge.")

    new_df = pd.DataFrame(new_rows)
    merged = pd.concat([existing, new_df], ignore_index=True)
    merged = merged.sort_values(["isp_scenario", "scenario", "year"]).reset_index(drop=True)
    merged.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV} — {len(merged)} rows total "
          f"(was {len(existing)}, added {len(new_df)})")
    print(merged.groupby(["scenario", "isp_scenario"]).size().to_string())


if __name__ == "__main__":
    main()
