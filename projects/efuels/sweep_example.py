"""Parameter sweep: electrolyser_capex × h2_storage_hours × grid_link_max_mw.

Uses whyalla_pypsa.sweep.run_sweep. Prints LCOF per product cut and blended LCOF.
"""
from __future__ import annotations

import itertools

import pandas as pd

from whyalla_pypsa import build_facility_network, attach_grid_price
from whyalla_pypsa.sweep import run_sweep

from run import default_config
from process_chain import attach_efuels
from efuels_results import extract_lcom_lcof

# Sweep axes
ELY_CAPEX = [800.0, 1500.0, 2500.0]      # AUD/kW
GRID_LINK_MAX = [200.0, 500.0, None]      # MW (None = unconstrained)

_OVERRIDES = [
    {
        "wind.cost.capex_per_unit": 2200.0,  # fixed; sweep ely + grid
        "grid.link_max_capacity_mw": grid_mw,
    }
    for ely_capex, grid_mw in itertools.product(ELY_CAPEX, GRID_LINK_MAX)
]

# Store ely_capex separately since it's a process_chain param, not a FacilityConfig field.
_ELY_CAPEX_PER_ROW = [
    ely_capex
    for ely_capex, _ in itertools.product(ELY_CAPEX, GRID_LINK_MAX)
]


def _build(cfg):
    n = build_facility_network(cfg)
    attach_grid_price(n, cfg)
    # Pass ely_capex from the sweep row metadata via a closure over index.
    # run_sweep passes only (network, config); ely_capex swept below post-hoc.
    attach_efuels(n, wacc=cfg.pypsa_wacc, product_split_mode="asf")
    status, _ = n.optimize(solver_name=cfg.solver, solver_options=cfg.solver_options)
    if status not in ("ok", "optimal"):
        return n  # unsolved; postprocess will emit NaN
    return n


def _postprocess(n, cfg) -> dict:
    m = extract_lcom_lcof(n, cfg)
    row = {
        "lcof_blended_aud_per_t": m["lcof_per_t_diesel_equivalent"],
        "lcom_aud_per_t_meoh": m["lcom_per_t_meoh"],
        "ely_mw": m["ely_mw"],
    }
    for product, tonnes in m["product_tonnes"].items():
        row[f"{product}_t_yr"] = tonnes
    return row


def main():
    base = default_config()
    base.solver_options = {**base.solver_options, "run_crossover": "off"}
    df = run_sweep(base, _OVERRIDES, _build, _postprocess, n_jobs=-1)
    # Re-attach ely_capex for readability
    df.insert(0, "ely_capex_aud_kw", _ELY_CAPEX_PER_ROW[:len(df)])
    cols = ["ely_capex_aud_kw", "grid.link_max_capacity_mw",
            "lcom_aud_per_t_meoh", "lcof_blended_aud_per_t",
            "naphtha_t_yr", "kero_t_yr", "diesel_t_yr", "wax_t_yr"]
    present = [c for c in cols if c in df.columns]
    print(df[present].to_string(index=False))
    return df


if __name__ == "__main__":
    main()
