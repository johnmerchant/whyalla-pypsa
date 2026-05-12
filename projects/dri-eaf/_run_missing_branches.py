"""One-shot helper: run only the 2 ISP-sensitivity branches that failed
in the prior trajectory run, append to trajectory.csv."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import pandas as pd

from generate_trajectory import run_branch, YEARS

HERE = Path(__file__).parent
PARTIAL = HERE / "trajectory_partial.csv"
OUT = HERE / "trajectory.csv"

MISSING = [
    ("Policy-stated + gas flat", "slower_growth"),
    ("Policy-stated + gas flat", "accelerated_transition"),
]

if __name__ == "__main__":
    existing = pd.read_csv(PARTIAL)
    print(f"Existing rows: {len(existing)}")

    new_rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_branch, p, i, YEARS) for p, i in MISSING]
        for future in as_completed(futures):
            new_rows.extend(future.result())

    df_new = pd.DataFrame(new_rows)
    print(f"New rows: {len(df_new)}")
    combined = pd.concat([existing, df_new], ignore_index=True)
    combined.to_csv(OUT, index=False)
    print(f"Wrote {OUT} ({len(combined)} rows)")
