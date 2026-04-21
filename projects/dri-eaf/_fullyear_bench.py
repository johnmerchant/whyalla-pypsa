"""Full-year solve for both grid modes; print side-by-side + also dump to CSV."""
from __future__ import annotations

import time

import pandas as pd

from run import default_config, main

OUT_CSV = "_fullyear_bench_results.csv"

rows = []
for mode in ("rldc_merit", "sa_dispatch"):
    print(f"\n════════════════ {mode} full year ════════════════", flush=True)
    cfg = default_config(grid_mode=mode, snapshot_mode="full_year")
    t0 = time.perf_counter()
    n, m = main(cfg)
    elapsed = time.perf_counter() - t0
    print(f"  solve_seconds: {elapsed:.1f}", flush=True)
    for k, v in m.items():
        if isinstance(v, float):
            print(f"  {k:30s}: {v:,.4f}")
        elif isinstance(v, (int, str)):
            print(f"  {k:30s}: {v}")
    rows.append({
        "mode": mode,
        "solve_seconds": round(elapsed, 1),
        "lcos_per_t_steel": m["lcos_per_t_steel"],
        "lcos_objective_basis": m["lcos_objective_basis"],
        "lcoh_per_kg": m["lcoh_per_kg"],
        "ely_mw": m["ely_mw"],
        "ely_cf": m["ely_cf"],
        "h2_store_mwh": m["h2_store_mwh"],
        "avg_fac_price": m["avg_fac_price"],
        "ely_realised_price": m["ely_realised_price"],
        "flexibility_premium": m["flexibility_premium"],
        "annual_h2_kg": m["annual_h2_kg"],
        "annual_steel_t": m["annual_steel_t"],
    })

df = pd.DataFrame(rows)
df.to_csv(OUT_CSV, index=False)
print(f"\nWrote {OUT_CSV}", flush=True)
print(df.T.to_string())
