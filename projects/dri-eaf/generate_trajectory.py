"""Tier 1 trajectory: rigorous myopic year-by-year on sa_dispatch.

Each (policy × ISP) branch runs a serial year loop that carries state from
one year to the next:

  - **Irreversibility**: electrolyser.p_nom_min and h2_store.e_nom_min are
    set to the prior cumulative build. Investment is one-way.
  - **Pre-2030 furnace cap**: electrolyser.p_nom_max = 0 for year < 2030,
    reflecting that the existing blast furnace can't reduce with H2. The
    new shaft furnace commissions 2030.
  - **FOAK→NOAK WACC switch**: new electrolyser investment finances at 13%
    (FOAK) until cumulative site capacity crosses 100 MW, then 9% (NOAK)
    thereafter. Legacy tranches retain their build-year WACC.
  - **Legacy CAPEX locking**: capex annuity for electrolyser and h2_store is
    rebuilt post-solve from a tranche list (each tranche at its build-year
    capex + WACC), not from the LP's current-year-applied-to-all figure.

Facility base (wind, solar, battery) always finances at NOAK 9% and is not
subject to irreversibility — single-year decisions per the myopic frame.

Asymmetric grid: all 3 policies × step_change + Policy-stated × {slower_growth,
accelerated_transition}. 5 years × 5 branches = 25 solves ≈ ~2 h compute.
Progress flushed after every solve so partial runs are recoverable.
"""
from __future__ import annotations

import copy
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from whyalla_pypsa import build_facility_network, attach_grid_price, annuitise

from run import default_config
from process_chain import attach_dri_eaf
from whyalla_results import extract_lcoh_lcos


HERE = Path(__file__).parent
OUT_CSV = HERE / "trajectory.csv"

# ── Process parameters (must match attach_dri_eaf defaults) ─────────────────
NG_INTENSITY_MWH_PER_T_DRI = 3.0
CO2_INTENSITY_KG_PER_T_DRI = 560.0
ELY_LIFETIME_YEARS = 20
H2_STORE_LIFETIME_YEARS = 25

# ── Tier 1 structural constants ─────────────────────────────────────────────
FOAK_WACC = 0.13
NOAK_WACC = 0.09
FOAK_NOAK_THRESHOLD_MW = 100.0
FURNACE_OPEN_YEAR = 2030  # Existing blast furnace can't run H2 before this.

# ── Scenario grid ───────────────────────────────────────────────────────────
YEARS = [2028, 2030, 2033, 2037, 2040]

# Electrolyser capex ($/kW) by year — IEA/BNEF-style learning curve proxy.
ELY_CAPEX_BY_YEAR = {
    2028: 1800.0,
    2030: 1440.0,
    2033: 1100.0,
    2037: 850.0,
    2040: 700.0,
}
# H2 storage capex ($/MWh) by year — steady; storage is a mature tank-tech line.
H2_STORE_CAPEX_BY_YEAR = {yr: 20_000.0 for yr in YEARS}

POLICY_SCENARIOS = {
    "Policy-stated + gas flat": {
        "carbon_2030": 63.0, "carbon_2040": 120.0, "gas_per_gj": 12.0,
    },
    "CBAM-binding + gas rising": {
        "carbon_2030": 100.0, "carbon_2040": 200.0, "gas_per_gj": 14.0,
    },
    "Delayed action + gas flat": {
        "carbon_2030": 43.0, "carbon_2040": 100.0, "gas_per_gj": 12.0,
    },
}

ISP_SCENARIOS = {
    "slower_growth": "SLOWER_GROWTH",
    "step_change": "STEP_CHANGE",
    "accelerated_transition": "ACCELERATED_TRANSITION",
}


@dataclass
class Tranche:
    """One vintage of capacity: MW (or MWh) built in build_year at build-year params."""
    build_year: int
    capacity: float               # MW for ely, MWh for h2_store
    annuity_per_unit: float       # $/yr per MW (or per MWh)
    wacc: float                   # for bookkeeping only
    capex_per_unit: float         # $/kW or $/MWh — for reporting

    @property
    def annual_cost(self) -> float:
        return self.capacity * self.annuity_per_unit


@dataclass
class BranchState:
    policy: str
    isp: str
    ely_tranches: list[Tranche] = field(default_factory=list)
    h2_store_tranches: list[Tranche] = field(default_factory=list)

    @property
    def cumulative_ely_mw(self) -> float:
        return sum(t.capacity for t in self.ely_tranches)

    @property
    def cumulative_h2_store_mwh(self) -> float:
        return sum(t.capacity for t in self.h2_store_tranches)

    @property
    def ely_tranche_annuity(self) -> float:
        return sum(t.annual_cost for t in self.ely_tranches)

    @property
    def h2_store_tranche_annuity(self) -> float:
        return sum(t.annual_cost for t in self.h2_store_tranches)


def carbon_price(scenario_params: dict, year: int) -> float:
    c30 = scenario_params["carbon_2030"]
    c40 = scenario_params["carbon_2040"]
    slope = (c40 - c30) / 10.0
    return c30 + slope * (year - 2030)


def ely_wacc_for_new_investment(state: BranchState) -> float:
    """FOAK until >100 MW proven at site, NOAK thereafter."""
    return NOAK_WACC if state.cumulative_ely_mw > FOAK_NOAK_THRESHOLD_MW else FOAK_WACC


def solve_year(*, policy: str, isp: str, year: int, state: BranchState) -> dict:
    """Solve one year given the branch's prior state; mutates state to record new tranches."""
    params = POLICY_SCENARIOS[policy]
    ely_capex = ELY_CAPEX_BY_YEAR[year]
    h2_store_capex = H2_STORE_CAPEX_BY_YEAR[year]
    carbon_p = carbon_price(params, year)
    gas_p = params["gas_per_gj"]

    # New-investment WACC this year (FOAK or NOAK).
    wacc_new = ely_wacc_for_new_investment(state)

    cfg = default_config(grid_mode="sa_dispatch", model_year=year)
    cfg = copy.deepcopy(cfg)
    if year < FURNACE_OPEN_YEAR:
        cfg.scenario.snapshot_mode = "representative_weeks"
        cfg.scenario.representative_weeks = 12
    cfg.scenario.file_token = ISP_SCENARIOS[isp]
    # Facility base (wind/solar/battery/h2_storage capex via attach_grid) always NOAK.
    cfg.pypsa_wacc = NOAK_WACC

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg)
    attach_dri_eaf(
        n,
        electrolyser_capex_per_kw=ely_capex,
        wacc=wacc_new,
        dual_fuel=True,
        ng_intensity_mwh_per_t_dri=NG_INTENSITY_MWH_PER_T_DRI,
        ng_price_per_gj=gas_p,
        co2_intensity_kg_per_t_dri=CO2_INTENSITY_KG_PER_T_DRI,
        carbon_price_per_t_co2=carbon_p,
    )

    # ── Tier 1 constraints ──────────────────────────────────────────────────
    if year < FURNACE_OPEN_YEAR:
        # Pre-shaft-furnace: existing blast furnace has no H2 pathway, so the
        # electrolyser is blocked and the H2-DRI link must be allowed to idle.
        # dri_plant_gas carries 100% of reductant load.
        n.links.at["electrolyser", "p_nom_max"] = 0.0
        n.links.at["dri_plant", "p_min_pu"] = 0.0
    # Irreversibility: can only add capacity.
    n.links.at["electrolyser", "p_nom_min"] = state.cumulative_ely_mw
    if "h2_store" in n.stores.index:
        n.stores.at["h2_store", "e_nom_min"] = state.cumulative_h2_store_mwh

    t0 = time.perf_counter()
    solver_opts = dict(cfg.solver_options)
    solver_opts["run_crossover"] = "off"
    solver_opts["threads"] = 2
    status, _ = n.optimize(solver_name=cfg.solver, solver_options=solver_opts)
    elapsed = time.perf_counter() - t0
    if status not in ("ok", "optimal"):
        raise RuntimeError(f"Solve failed ({policy}, {isp}, {year}): {status}")

    m = extract_lcoh_lcos(
        n, cfg,
        ng_intensity_mwh_per_t_dri=NG_INTENSITY_MWH_PER_T_DRI,
        co2_intensity_kg_per_t_dri=CO2_INTENSITY_KG_PER_T_DRI,
    )

    # ── Record new tranches ─────────────────────────────────────────────────
    new_ely_mw = max(0.0, m["ely_mw"] - state.cumulative_ely_mw)
    if new_ely_mw > 1e-3:
        state.ely_tranches.append(Tranche(
            build_year=year,
            capacity=new_ely_mw,
            annuity_per_unit=annuitise(ely_capex * 1000.0, wacc_new, ELY_LIFETIME_YEARS),
            wacc=wacc_new,
            capex_per_unit=ely_capex,
        ))
    new_h2_store_mwh = max(0.0, m["h2_store_mwh"] - state.cumulative_h2_store_mwh)
    if new_h2_store_mwh > 1e-3:
        state.h2_store_tranches.append(Tranche(
            build_year=year,
            capacity=new_h2_store_mwh,
            annuity_per_unit=annuitise(h2_store_capex, wacc_new, H2_STORE_LIFETIME_YEARS),
            wacc=wacc_new,
            capex_per_unit=h2_store_capex,
        ))

    # ── Tranche-corrected LCOS (replaces LP's current-year-all LCOS) ────────
    # The LP charges current-year capex to all of p_nom_opt for extendable
    # components; for ely and h2_store that's wrong because legacy tranches
    # were built at different prices. Subtract the LP's figure and add the
    # tranche-sum.
    lp_ely_capex_annuity = (
        m["ely_mw"] * annuitise(ely_capex * 1000.0, wacc_new, ELY_LIFETIME_YEARS)
    )
    lp_h2_store_capex_annuity = (
        m["h2_store_mwh"]
        * annuitise(h2_store_capex, NOAK_WACC, H2_STORE_LIFETIME_YEARS)
        if m["h2_store_mwh"] > 0 else 0.0
    )
    tranche_correction = (
        state.ely_tranche_annuity
        + state.h2_store_tranche_annuity
        - lp_ely_capex_annuity
        - lp_h2_store_capex_annuity
    )
    corrected_facility_capex = m["lcos_facility_capex_annuity"] + tranche_correction
    lcos_tier1 = (
        (corrected_facility_capex + m["lcos_facility_opex"] + m["lcos_net_boundary_cost"])
        / m["annual_steel_t"]
    )
    # LCOH corrected by the same tranche delta, allocated to H2 by load share.
    lcoh_numerator_correction = tranche_correction * m["ely_load_share"]
    lcoh_tier1 = (
        m["lcoh_per_kg"]
        + lcoh_numerator_correction / m["annual_h2_kg"]
        if m["annual_h2_kg"] > 0 else float("nan")
    )

    return {
        "year": year,
        "scenario": policy,
        "isp_scenario": isp,
        "h2_fraction": m["h2_fraction"],
        "total_gas_mwh": m["total_gas_mwh"],
        "total_h2_mwh": m["annual_h2_mwh"],
        "electrolyser_mw": m["ely_mw"],
        "new_electrolyser_mw": new_ely_mw,
        "h2_storage_mwh": m["h2_store_mwh"],
        "new_h2_storage_mwh": new_h2_store_mwh,
        "ely_wacc_new": wacc_new,
        "emissions_saved_tCO2": m["emissions_saved_tCO2"],
        "emissions_tCO2": m["emissions_tCO2"],
        "annual_system_cost": m["objective"],
        "electrolyser_cf": m["ely_cf"],
        "electrolyser_realised_price": m["ely_realised_price"],
        "avg_wholesale_price_sa_n": m["avg_fac_price"],
        "flexibility_premium": m["flexibility_premium"],
        "eaf_total_mwh": m["total_eaf_mwh"],
        "eaf_realised_price": m["eaf_realised_price"],
        "eaf_flexibility_premium": m["eaf_flexibility_premium"],
        "lcoh_per_kg": lcoh_tier1,
        "lcos_per_t_steel": lcos_tier1,
        "lcoh_lp_per_kg": m["lcoh_per_kg"],
        "lcos_lp_per_t_steel": m["lcos_per_t_steel"],
        "ely_tranche_annuity": state.ely_tranche_annuity,
        "h2_store_tranche_annuity": state.h2_store_tranche_annuity,
        "capex_per_kw": ely_capex,
        "gas_price": gas_p,
        "carbon_price": carbon_p,
        "discount_rate": wacc_new,
        "subregion": cfg.grid.subregion,
        "solve_seconds": round(elapsed, 1),
    }


def run_branch(policy: str, isp: str, years: list[int]) -> list[dict]:
    state = BranchState(policy=policy, isp=isp)
    rows: list[dict] = []
    for year in years:
        print(f"  {policy} / {isp} / {year} "
              f"(prior ely={state.cumulative_ely_mw:.0f} MW, "
              f"WACC_new={ely_wacc_for_new_investment(state):.2f})", flush=True)
        row = solve_year(policy=policy, isp=isp, year=year, state=state)
        print(
            f"    solved in {row['solve_seconds']}s  "
            f"ely={row['electrolyser_mw']:.0f} MW (+{row['new_electrolyser_mw']:.0f}), "
            f"h2_frac={row['h2_fraction']:.2%}, "
            f"LCOS=${row['lcos_per_t_steel']:.0f}/t, "
            f"emissions_saved={row['emissions_saved_tCO2']:,.0f} t",
            flush=True,
        )
        rows.append(row)
    return rows


def trajectory_branches() -> list[tuple[str, str]]:
    """Asymmetric grid: all policies × step_change + Policy-stated × {slower,accel}."""
    branches: list[tuple[str, str]] = []
    for policy in POLICY_SCENARIOS:
        branches.append((policy, "step_change"))
    for isp in ("slower_growth", "accelerated_transition"):
        branches.append(("Policy-stated + gas flat", isp))
    return branches


def main(*, smoke_test: bool = False, workers: int | None = None) -> pd.DataFrame:
    branches = trajectory_branches()
    if smoke_test:
        branches = [("Policy-stated + gas flat", "step_change")]
    total_solves = len(branches) * len(YEARS)
    if workers is None:
        workers = min(len(branches), os.cpu_count() or 1, 4)
    print(f"Branches: {len(branches)}  |  years per branch: {len(YEARS)}  |  total solves: {total_solves}", flush=True)
    print(f"Workers: {workers}", flush=True)

    all_rows: list[dict] = []
    if workers == 1:
        for bi, (policy, isp) in enumerate(branches, 1):
            print(f"\n══════ [{bi}/{len(branches)}] {policy} / {isp} ══════", flush=True)
            branch_rows = run_branch(policy, isp, YEARS)
            all_rows.extend(branch_rows)
            # Flush partial CSV after every branch (safer than per-row).
            pd.DataFrame(all_rows).to_csv(OUT_CSV, index=False)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(run_branch, policy, isp, YEARS)
                for policy, isp in branches
            ]
            for future in as_completed(futures):
                branch_rows = future.result()
                all_rows.extend(branch_rows)
                # Flush partial CSV after every branch (safer than per-row).
                pd.DataFrame(all_rows).to_csv(OUT_CSV, index=False)

    df = pd.DataFrame(all_rows)
    print(f"\nWrote {OUT_CSV} ({len(df)} rows)")
    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Tier 1 trajectory: myopic + irreversibility + FOAK/NOAK.")
    parser.add_argument(
        "--smoke-test", action="store_true",
        help="Run only Policy-stated × step_change (1 branch × 5 years, ~25 min).",
    )
    parser.add_argument("--workers", type=int, default=None, help="Parallel branches. Default: auto (min(branches, cpu, 4)).")
    parser.add_argument("--serial", action="store_true", help="Force serial execution (workers=1).")
    args = parser.parse_args()
    workers = 1 if args.serial else args.workers
    main(smoke_test=args.smoke_test, workers=workers)
