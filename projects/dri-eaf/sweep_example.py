"""Parametric sweep: electrolyser_capex x h2_storage_hours x grid_link_max_mw.

Iterates over all combinations and prints a summary DataFrame.

`h2_hours` caps the H2 store size at `h2_hours * avg_h2_demand_MW` MWh_LHV,
where avg_h2_demand = 1.6 Mt/y × 1.9 MWh_H2/t_DRI / 8760 h ≈ 347 MW.
The store remains extendable; the cap just bounds how much the solver
can build.
"""
from __future__ import annotations

import copy
import itertools
import time

import pandas as pd

from whyalla_pypsa import build_facility_network, attach_grid_price

from run import default_config
from process_chain import attach_dri_eaf
from whyalla_results import extract_lcoh_lcos


ELY_CAPEX_VALUES = [1000.0, 1500.0, 2000.0, 2500.0]   # AUD/kW
H2_HOURS_VALUES = [0, 6, 24, 96]                        # storage hours of avg H2 demand
GRID_MW_VALUES = [0, 100, 500]                          # link max MW

# 1.6 Mt/y steel × 1.9 MWh_H2/t_DRI / 8760 h. Process_chain.py defaults:
# annual_steel_mt=1.6, h2_per_t_dri=0.057, H2_LHV=33.33.
AVG_H2_MW: float = 1.6e6 * (0.057 * 33.33) / 8760.0  # ≈ 347 MW


def main(
    *,
    grid_mode: str = "rldc_merit",
    snapshot_mode: str = "full_year",
    representative_weeks: int = 4,
):
    base = default_config(
        grid_mode=grid_mode,
        snapshot_mode=snapshot_mode,
        representative_weeks=representative_weeks,
    )

    rows = []
    for ely_capex, h2_hours, grid_mw in itertools.product(
        ELY_CAPEX_VALUES, H2_HOURS_VALUES, GRID_MW_VALUES
    ):
        cfg = copy.deepcopy(base)
        if grid_mw == 0:
            cfg.grid.link_max_capacity_mw = 1.0  # near-zero grid
        else:
            cfg.grid.link_max_capacity_mw = float(grid_mw)

        t0 = time.perf_counter()
        n = build_facility_network(cfg)
        attach_grid_price(n, cfg)
        attach_dri_eaf(n, electrolyser_capex_per_kw=ely_capex, wacc=cfg.pypsa_wacc)

        # Cap H2 store at h2_hours of average H2 demand. e_nom_extendable stays
        # True so the solver can still pick anything in [0, cap].
        if "h2_store" in n.stores.index:
            n.stores.at["h2_store", "e_nom_max"] = h2_hours * AVG_H2_MW

        status, _ = n.optimize(solver_name=cfg.solver)
        elapsed = time.perf_counter() - t0

        if status not in ("ok", "optimal"):
            lcos = float("nan")
            ely_mw = float("nan")
            h2_mwh = float("nan")
            lcoh = float("nan")
        else:
            metrics = extract_lcoh_lcos(n, cfg)
            lcos = metrics["lcos_per_t_steel"]
            ely_mw = metrics["ely_mw"]
            h2_mwh = metrics["h2_store_mwh"]
            lcoh = metrics["lcoh_per_kg"]

        rows.append({
            "ely_capex": ely_capex,
            "h2_hours": h2_hours,
            "grid_mw": grid_mw,
            "ely_mw": round(ely_mw, 1),
            "h2_store_mwh": round(h2_mwh, 0),
            "lcoh": round(lcoh, 3),
            "lcos": round(lcos, 2),
            "solve_seconds": round(elapsed, 2),
        })

    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--grid-mode", default="rldc_merit", choices=("rldc_merit", "sa_dispatch"))
    parser.add_argument("--snapshots", default="full_year", choices=("full_year", "representative_weeks"))
    parser.add_argument("--rep-weeks", type=int, default=4)
    args = parser.parse_args()

    main(
        grid_mode=args.grid_mode,
        snapshot_mode=args.snapshots,
        representative_weeks=args.rep_weeks,
    )
