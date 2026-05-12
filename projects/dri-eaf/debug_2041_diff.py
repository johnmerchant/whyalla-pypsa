"""Diff the failing acce_trans/2041 network vs the working step_change/2041 build.

Both diagnostics in Round 2 showed:
  - acce_trans + 2041 → infeasible at presolve in 5s
  - step_change + 2041 → optimal in 811s

So the structural difference between these two networks must contain the
binding infeasibility. We dump the network DataFrames for both and surface:
  1. Any p_nom_min > p_nom_max (or e_nom_min > e_nom_max) in either build.
  2. Generators / links / stores that exist in one but not the other.
  3. Per-component numeric deltas (p_nom, p_nom_max, marginal_cost, etc.).
  4. Demand load totals, VRE trace integrals, thermal capacity totals.

Also writes both LPs to MPS files so we can run HiGHS' presolver / IIS by hand
if the diff alone doesn't pin it down.

Usage:
  uv run python debug_2041_diff.py
"""
from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from debug_2041_infeasible import (
    STATE_PICKLE,
    build_2041_network_with_overrides,
)


HERE = Path(__file__).parent


def load_state():
    if not STATE_PICKLE.exists():
        raise SystemExit(
            "State pickle missing. Run debug_2041_infeasible.py first to "
            "build .debug_2041_state.pkl."
        )
    with STATE_PICKLE.open("rb") as f:
        return pickle.load(f)


def _bounds_check(df: pd.DataFrame, lo: str, hi: str, label: str) -> list[str]:
    """Return rows where lo > hi, formatted for printing."""
    if lo not in df or hi not in df:
        return []
    bad = df[(df[lo] > df[hi]) & (df[hi] < np.inf)]
    if bad.empty:
        return []
    out = [f"  -- {label}: {len(bad)} rows with {lo} > {hi} --"]
    for idx, row in bad.iterrows():
        out.append(f"     {idx}: {lo}={row[lo]:.3g}  {hi}={row[hi]:.3g}")
    return out


def _diff_numeric(
    df_a: pd.DataFrame, df_b: pd.DataFrame, cols: list[str], label: str
) -> list[str]:
    out = []
    common = df_a.index.intersection(df_b.index)
    only_a = df_a.index.difference(df_b.index)
    only_b = df_b.index.difference(df_a.index)
    if len(only_a) or len(only_b):
        out.append(f"  -- {label}: index difference --")
        if len(only_a):
            out.append(f"     only in acce_trans: {sorted(only_a)[:20]}")
        if len(only_b):
            out.append(f"     only in step_change: {sorted(only_b)[:20]}")
    big_diffs = []
    for col in cols:
        if col not in df_a.columns or col not in df_b.columns:
            continue
        a = df_a.loc[common, col]
        b = df_b.loc[common, col]
        if a.dtype == bool or b.dtype == bool:
            mask = a != b
            for idx in a.index[mask][:30]:
                big_diffs.append(
                    f"     {idx:30s}  {col:20s}  acce={a[idx]!s:>12s}  "
                    f"step={b[idx]!s:>12s}"
                )
            continue
        # ignore inf / NaN equality
        delta = (a - b).abs()
        rel = delta / (b.abs() + 1e-9)
        # flag rows where either absolute or relative diff is meaningful
        mask = (delta > 1.0) | (rel > 0.05)
        # exclude inf-on-both rows
        both_inf = np.isinf(a) & np.isinf(b)
        mask = mask & ~both_inf
        if mask.any():
            for idx in a.index[mask][:30]:
                big_diffs.append(
                    f"     {idx:30s}  {col:20s}  acce={a[idx]:>12.4g}  "
                    f"step={b[idx]:>12.4g}"
                )
    if big_diffs:
        out.append(f"  -- {label}: numeric diffs ({len(big_diffs)} rows) --")
        out.extend(big_diffs)
    return out


def main() -> None:
    state = load_state()
    print(f"State: ely={state.cumulative_ely_mw:.0f} MW, wind={state.cumulative_wind_mw:.0f}, "
          f"solar={state.cumulative_solar_mw:.0f}, grid={state.cumulative_grid_link_mw:.0f}")

    print("\nBuilding acce_trans / 2041 (failing) ...")
    n_a, _ = build_2041_network_with_overrides(
        state, isp_override="accelerated_transition", year_override=2041,
    )
    print(f"  components: gen={len(n_a.generators)}  link={len(n_a.links)}  "
          f"store={len(n_a.stores)}  load={len(n_a.loads)}  bus={len(n_a.buses)}")

    print("Building step_change / 2041 (working) ...")
    n_b, _ = build_2041_network_with_overrides(
        state, isp_override="step_change", year_override=2041,
    )
    print(f"  components: gen={len(n_b.generators)}  link={len(n_b.links)}  "
          f"store={len(n_b.stores)}  load={len(n_b.loads)}  bus={len(n_b.buses)}")

    print("\n" + "=" * 72)
    print("BOUNDS CHECK: p_nom_min > p_nom_max  (variable bounds violation?)")
    print("=" * 72)
    for label, n in [("acce_trans/2041", n_a), ("step_change/2041", n_b)]:
        print(f"\n[{label}]")
        for line in _bounds_check(n.generators, "p_nom_min", "p_nom_max", "generators"):
            print(line)
        for line in _bounds_check(n.links, "p_nom_min", "p_nom_max", "links"):
            print(line)
        for line in _bounds_check(n.stores, "e_nom_min", "e_nom_max", "stores"):
            print(line)

    print("\n" + "=" * 72)
    print("DATAFRAME DIFFS")
    print("=" * 72)
    print("\n[generators]")
    for line in _diff_numeric(
        n_a.generators, n_b.generators,
        ["p_nom", "p_nom_min", "p_nom_max", "marginal_cost", "capital_cost",
         "p_min_pu", "p_max_pu", "e_sum_min", "e_sum_max"],
        "generators",
    ):
        print(line)
    print("\n[links]")
    for line in _diff_numeric(
        n_a.links, n_b.links,
        ["p_nom", "p_nom_min", "p_nom_max", "marginal_cost", "capital_cost",
         "efficiency", "p_min_pu", "p_max_pu"],
        "links",
    ):
        print(line)
    print("\n[stores]")
    for line in _diff_numeric(
        n_a.stores, n_b.stores,
        ["e_nom", "e_nom_min", "e_nom_max", "marginal_cost", "capital_cost",
         "e_initial", "e_cyclic"],
        "stores",
    ):
        print(line)

    print("\n" + "=" * 72)
    print("DEMAND-SIDE TOTALS (sum of p_set across snapshots)")
    print("=" * 72)
    for label, n in [("acce_trans/2041", n_a), ("step_change/2041", n_b)]:
        load_total = (n.loads_t.p_set.sum().sum() if not n.loads_t.p_set.empty
                      else (n.loads.p_set * len(n.snapshots)).sum())
        print(f"  {label}: total load energy = {load_total:.3g} MWh "
              f"({len(n.snapshots)} snapshots)")

    print("\n[VRE p_nom totals — per-bus rolled up]")
    for label, n in [("acce_trans/2041", n_a), ("step_change/2041", n_b)]:
        gens = n.generators.copy()
        gens["bus"] = gens["bus"].fillna("?")
        print(f"\n  [{label}] by bus & carrier:")
        if "carrier" in gens.columns:
            grp = gens.groupby(["bus", "carrier"])["p_nom"].sum()
        else:
            grp = gens.groupby("bus")["p_nom"].sum()
        # Show only interesting (non-zero, non-AC slack)
        for k, v in grp.items():
            if v > 0:
                print(f"    {str(k):60s} {v:>10.0f} MW")

    print("\n" + "=" * 72)
    print("TIME-VARYING DATA")
    print("=" * 72)

    def _t_summary(label, n):
        print(f"\n[{label}]")
        print(f"  snapshots: n={len(n.snapshots)}  "
              f"first={n.snapshots[0]}  last={n.snapshots[-1]}")
        for attr in ["p_max_pu", "p_min_pu", "p_set", "marginal_cost"]:
            for cls_name, comp_t in [
                ("gens_t", n.generators_t),
                ("links_t", n.links_t),
                ("loads_t", n.loads_t),
            ]:
                df = getattr(comp_t, attr, None)
                if df is None or df.empty:
                    continue
                # column-wise total energy (or mean) per series
                summed = df.sum(axis=0)
                if summed.empty:
                    continue
                print(f"  {cls_name}.{attr}:  cols={list(summed.index)[:10]}"
                      f"{'...' if len(summed) > 10 else ''}")
                for k, v in summed.items():
                    print(f"     {k:35s} sum={v:>14.4g}  mean={v/len(n.snapshots):>10.4g}")

    _t_summary("acce_trans/2041", n_a)
    _t_summary("step_change/2041", n_b)

    # Compare: any p_max_pu series identically zero in one but positive in the other?
    print("\n" + "=" * 72)
    print("TRACE INTEGRITY  (check for all-zero p_max_pu — would block dispatch)")
    print("=" * 72)
    for label, n in [("acce_trans/2041", n_a), ("step_change/2041", n_b)]:
        pmp = n.generators_t.p_max_pu
        if pmp.empty:
            print(f"  [{label}] no p_max_pu time series")
            continue
        all_zero = pmp.columns[pmp.sum(axis=0) == 0.0]
        nan_cols = pmp.columns[pmp.isna().any(axis=0)]
        print(f"  [{label}] all-zero traces: {list(all_zero)}")
        print(f"  [{label}] NaN traces:      {list(nan_cols)}")
        # And check load p_set for NaN:
        if not n.loads_t.p_set.empty:
            nan_loads = n.loads_t.p_set.columns[n.loads_t.p_set.isna().any(axis=0)]
            print(f"  [{label}] NaN loads:       {list(nan_loads)}")

    print("\n" + "=" * 72)
    print("WRITING LP / MPS FILES (for HiGHS IIS analysis)")
    print("=" * 72)
    # PyPSA's optimize.solve_model has a way to dump the LP, but we can also
    # build the model and write directly via linopy.
    for label, n in [("acce_trans_2041", n_a), ("step_change_2041", n_b)]:
        try:
            n.optimize.create_model()
            mps_path = HERE / f".debug_{label}.lp"
            n.model.to_file(str(mps_path))
            print(f"  wrote {mps_path}")
        except Exception as e:
            print(f"  {label}: failed to dump LP: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
