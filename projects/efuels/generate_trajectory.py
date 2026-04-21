"""E-fuels trajectory: 3 scenarios × 5 years, myopic rolling-forecast with
irreversibility and vintage tranche accounting (dri-eaf pattern).

Each branch = (scenario). Within a branch, years solve sequentially; a
BranchState carries forward cumulative capacity + per-vintage annuities:

  - **Irreversibility**: every extendable component's p_nom_min / e_nom_min
    is set to the previous year's p_nom_opt / e_nom_opt, so the LP can only
    grow capacity year-to-year (no tear-down).
  - **Vintage tranche accounting**: each year, the new electrolyser capacity
    (p_nom_opt − prior cumulative) is recorded as a Tranche carrying that
    year's CAPEX + the scenario WACC. The LP naïvely charges current-year
    CAPEX to *all* p_nom_opt for extendable components, which overstates
    cost for legacy vintages built when CAPEX was higher. LCOM/LCOF are
    post-corrected by subtracting the LP's charge and adding the tranche-sum.

Scenarios (exogenous input trajectories):
  - policy_stated : fast CAPEX decline, base diesel price, WACC 11%
  - imo_binding   : same CAPEX, +AUD 400/t diesel + AUD 350/t kero from 2032
  - foak_stranded : slow CAPEX decline, no premium, WACC 13%

Outputs trajectory.csv with columns consumed by chart_trajectory.py.

Run:
    python generate_trajectory.py [--workers N]
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from whyalla_pypsa import build_facility_network, attach_grid_price
from whyalla_pypsa.post.annuitise import annuitise

from run import default_config
from process_chain import attach_efuels
from efuels_physics import ELECTROLYSER_LIFE_YR
from efuels_results import extract_lcom_lcof
from co2_supply import build_co2_supply_curve, blended_co2_price

YEARS = [2027, 2028, 2029, 2030, 2032, 2035, 2038, 2040]

# Electrolyser CAPEX paths (AUD/kW). "fast" follows IEA NZE-adjacent decline;
# "slow" is a stranded-tech scenario where 2030 entry never cheapens below ~1200.
# Pre-2030 values extrapolated linearly from the 2030→2032 gradient, consistent
# with IEA/IRENA electrolyser cost outlooks (PEM ~1800-2000 AUD/kW in 2024-25
# easing toward 1500 by 2030).
CAPEX_PATHS = {
    "fast": {2027: 1900, 2028: 1750, 2029: 1600,
             2030: 1500, 2032: 1200, 2035: 900,  2038: 750, 2040: 700},
    "slow": {2027: 2300, 2028: 2100, 2029: 1950,
             2030: 1800, 2032: 1650, 2035: 1400, 2038: 1250, 2040: 1200},
}

# ── Product offtake prices (AUD/t wholesale) ─────────────────────────────
# All four Fischer-Tropsch products anchored to UK DESNZ 2024 Fossil Fuel
# Price Assumptions Scenario C (IEA high-price methodology, USD 110 → 117/bbl
# crude flat from 2040) plus a persistent Middle East risk premium reflecting
# the Q2 2026 Strait-of-Hormuz crisis (Brent spot ~USD 95-96/bbl April 2026,
# retail AUD >3/L at peak, easing). Conversion at AUD/USD = 0.66, 159 L/bbl
# crude. Product-specific refining margins over crude from Platts AU wholesale
# history and IATA Jet Fuel Monitor:
#   diesel:  1.65× crude   (road / off-road / marine distillate)
#   kero:    1.75× crude   (jet premium during supply stress; IATA JFM Q2'26)
#   naphtha: 1.10× crude   (petrochem feedstock, lower yield-cut)
#   wax:     specialty — FT wax market (ICIS / paraffin wax), ~AUD 2,500/t,
#            only weakly crude-coupled; held flat as a conservative floor.
# Pre-2030 values reflect the Q2 2026 Hormuz crisis premium fading linearly
# back toward the DESNZ/IEA-anchored 2030 baseline (retail $2.76/L in Apr 2026
# → wholesale ~AUD 2,400/t diesel; easing ~AUD 100/yr through 2030).
DIESEL_BASE  = {2027: 2400, 2028: 2300, 2029: 2200,
                2030: 2100, 2032: 2125, 2035: 2150, 2038: 2150, 2040: 2150}
KERO_BASE    = {2027: 2550, 2028: 2450, 2029: 2350,
                2030: 2250, 2032: 2280, 2035: 2310, 2038: 2310, 2040: 2310}
NAPHTHA_BASE = {2027: 1600, 2028: 1530, 2029: 1470,
                2030: 1400, 2032: 1420, 2035: 1440, 2038: 1440, 2040: 1440}
WAX_BASE     = {2027: 2500, 2028: 2500, 2029: 2500,
                2030: 2500, 2032: 2500, 2035: 2500, 2038: 2500, 2040: 2500}

# Scenario-specific premia over the base path:
IMO_TIER1_PREMIUM = 400          # AUD/t diesel, from 2032 if imo_premium=True
SAF_MANDATE_KERO_PREMIUM = 350   # AUD/t kero, from 2032 if imo_premium=True
                                 # (SAF blending-mandate shadow price under
                                 #  the same high-ambition shipping/aviation
                                 #  decarbonisation scenario)

SCENARIOS = {
    "policy_stated": {
        "capex_path": "fast",
        "imo_premium": False,
        "wacc": 0.11,
    },
    "imo_binding": {
        "capex_path": "fast",
        "imo_premium": True,
        "wacc": 0.11,
    },
    "foak_stranded": {
        "capex_path": "slow",
        "imo_premium": False,
        "wacc": 0.13,
    },
}

OUT_CSV = Path(__file__).parent / "trajectory.csv"


def _diesel_price(year: int, imo_premium: bool) -> float:
    base = DIESEL_BASE[year]
    if imo_premium and year >= 2032:
        return base + IMO_TIER1_PREMIUM
    return base


def _kero_price(year: int, imo_premium: bool) -> float:
    base = KERO_BASE[year]
    if imo_premium and year >= 2032:
        return base + SAF_MANDATE_KERO_PREMIUM
    return base


def _naphtha_price(year: int) -> float:
    return NAPHTHA_BASE[year]


def _wax_price(year: int) -> float:
    return WAX_BASE[year]


# Components to pin with irreversibility (previous year's opt → p_nom_min /
# e_nom_min). Populated at solve-time from the network; listed here so the
# intent is visible. grid_import / grid_export are excluded because their
# capacity represents the physical interconnect, not a build decision.
_IRREVERSIBILITY_EXCLUDE = {"grid_import", "grid_export"}

# Plant commissioning: FID 2026 + 3-year EPC → plant opens 2029.
# All process components (electrolyser, synth, refinery, process stores)
# are locked at zero pre-2029. Facility base (wind/solar/battery) is free
# to build earlier — represents site preparation during commissioning.
PLANT_COMMISSION_YEAR = 2029
_PROCESS_LINK_NAMES = {"electrolyser", "meoh_synthesis"}   # refinery_* added at run-time
_PROCESS_STORE_NAMES = {"h2_store", "meoh_storage", "co2_storage"}

# Refinery modular build rate: one FT module per product per year ≈ 150 MW
# MeOH input capacity. Reflects realistic modular EPC lead times — a single
# product train cannot scale from 0 to full capacity overnight.
REFINERY_MAX_BUILD_DELTA_MW_PER_YEAR = 150.0


@dataclass
class Tranche:
    """One vintage of electrolyser capacity built in build_year."""
    build_year: int
    mw: float                 # new capacity built this year
    annuity_per_mw: float     # AUD/yr per MW, fixed at build-year CAPEX + WACC
    capex_per_kw: float       # for reporting
    wacc: float               # for reporting

    @property
    def annual_cost(self) -> float:
        return self.mw * self.annuity_per_mw


@dataclass
class BranchState:
    """Carries forward cumulative capacity + tranches across years in one scenario."""
    scenario: str
    ely_tranches: list[Tranche] = field(default_factory=list)
    # Cumulative opt-values for ALL extendable components (for irreversibility).
    # Keyed as "{component_table}/{name}" → previous p_nom_opt or e_nom_opt.
    prior_capacity: dict[str, float] = field(default_factory=dict)
    last_solved_year: int | None = None

    @property
    def cumulative_ely_mw(self) -> float:
        return sum(t.mw for t in self.ely_tranches)

    @property
    def ely_tranche_annuity(self) -> float:
        return sum(t.annual_cost for t in self.ely_tranches)


def _apply_irreversibility(n, prior: dict[str, float]) -> None:
    """Set p_nom_min / e_nom_min to prior year's opt for all extendable components."""
    for name in n.links.index:
        if name in _IRREVERSIBILITY_EXCLUDE:
            continue
        if bool(n.links.at[name, "p_nom_extendable"]):
            n.links.at[name, "p_nom_min"] = prior.get(f"links/{name}", 0.0)
    for name in n.stores.index:
        if bool(n.stores.at[name, "e_nom_extendable"]):
            n.stores.at[name, "e_nom_min"] = prior.get(f"stores/{name}", 0.0)


def _apply_commissioning_and_lead_times(n, year: int, state: BranchState) -> None:
    """Pre-commission lock (< 2030) and refinery modular build-rate cap."""
    if year < PLANT_COMMISSION_YEAR:
        # Plant under construction — no process capacity allowed.
        for name in n.links.index:
            if name in _PROCESS_LINK_NAMES or name.startswith("refinery_"):
                n.links.at[name, "p_nom_max"] = 0.0
        for name in n.stores.index:
            if name in _PROCESS_STORE_NAMES:
                n.stores.at[name, "e_nom_max"] = 0.0
        return

    # Commission year is greenfield — the refinery is sized at FID and reaches
    # full initial capacity on opening. The module rate-limit kicks in for
    # expansions from the year after commissioning onward.
    if year == PLANT_COMMISSION_YEAR:
        return
    gap = max(1, year - (state.last_solved_year or year))
    for name in n.links.index:
        if name.startswith("refinery_"):
            prior_opt = state.prior_capacity.get(f"links/{name}", 0.0)
            n.links.at[name, "p_nom_max"] = (
                prior_opt + REFINERY_MAX_BUILD_DELTA_MW_PER_YEAR * gap
            )


def _snapshot_opt_values(n) -> dict[str, float]:
    """Capture p_nom_opt / e_nom_opt of all extendable components into a dict."""
    out: dict[str, float] = {}
    for name in n.links.index:
        if name in _IRREVERSIBILITY_EXCLUDE:
            continue
        if bool(n.links.at[name, "p_nom_extendable"]):
            out[f"links/{name}"] = float(n.links.at[name, "p_nom_opt"])
    for name in n.stores.index:
        if bool(n.stores.at[name, "e_nom_extendable"]):
            out[f"stores/{name}"] = float(n.stores.at[name, "e_nom_opt"])
    return out


def solve_year(*, scenario: str, year: int, state: BranchState) -> dict:
    """Build + solve one year, mutating state to record new tranches."""
    params = SCENARIOS[scenario]
    capex_kw = CAPEX_PATHS[params["capex_path"]][year]
    diesel_p  = _diesel_price(year, params["imo_premium"])
    kero_p    = _kero_price(year, params["imo_premium"])
    naphtha_p = _naphtha_price(year)
    wax_p     = _wax_price(year)
    wacc = params["wacc"]

    cfg = copy.deepcopy(default_config())
    cfg.scenario.model_year = year
    cfg.scenario.snapshot_mode = "representative_weeks"
    cfg.scenario.representative_weeks = 8
    cfg.pypsa_wacc = wacc

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg)

    # Re-bind CO2 supply curve to this year so tranche availability matches.
    co2_fn = lambda yr=year: build_co2_supply_curve(yr)
    attach_efuels(
        n,
        electrolyser_capex_per_kw=capex_kw,
        wacc=wacc,
        co2_supply_fn=co2_fn,
        diesel_price_per_t=diesel_p,
        kero_price_per_t=kero_p,
        naphtha_price_per_t=naphtha_p,
        wax_price_per_t=wax_p,
        product_split_mode="asf",
        annual_fuel_mt=0.0,     # free economic sizing — no contracted offtake floor
    )

    # ── Irreversibility + commissioning + refinery lead times ────────────
    _apply_irreversibility(n, state.prior_capacity)
    _apply_commissioning_and_lead_times(n, year, state)

    t0 = time.perf_counter()
    solver_opts = {**cfg.solver_options, "run_crossover": "off"}
    status, _ = n.optimize(solver_name=cfg.solver, solver_options=solver_opts)
    elapsed = time.perf_counter() - t0
    if status not in ("ok", "optimal"):
        raise RuntimeError(f"Solve failed ({scenario}, {year}): {status}")

    m = extract_lcom_lcof(n, cfg)

    # ── Record new electrolyser tranche ──────────────────────────────────
    ely_mw_now = m.get("ely_mw", 0.0)
    new_ely_mw = max(0.0, ely_mw_now - state.cumulative_ely_mw)
    if new_ely_mw > 1e-3:
        # Per-MW annuity: capex_per_kw is AUD/kW, so ×1000 → AUD/MW.
        annuity_per_mw = annuitise(
            capex_kw * 1000.0, wacc, ELECTROLYSER_LIFE_YR
        )
        state.ely_tranches.append(Tranche(
            build_year=year,
            mw=new_ely_mw,
            annuity_per_mw=annuity_per_mw,
            capex_per_kw=capex_kw,
            wacc=wacc,
        ))

    # ── Tranche-corrected LCOF / LCOM ────────────────────────────────────
    # The LP charges current-year capex_kw to ALL ely_mw_now; subtract that
    # and add the per-vintage tranche sum instead.
    lp_ely_annuity = ely_mw_now * annuitise(
        capex_kw * 1000.0, wacc, ELECTROLYSER_LIFE_YR
    )
    tranche_correction = state.ely_tranche_annuity - lp_ely_annuity

    lcof_lp = m.get("lcof_per_t_diesel_equivalent", float("nan"))
    lcom_lp = m.get("lcom_per_t_meoh", float("nan"))
    meoh_t = m.get("meoh_tonnes", 0.0)
    # Product-side allocation: LCOF divides by total product energy; reuse
    # by converting correction AUD/yr → per-tonne-diesel-equivalent via LP ratio
    # (since tonne/energy relations don't change, a direct numerator add works).
    product_energy_mwh = m.get("product_energy_mwh", {})
    total_energy = sum(product_energy_mwh.values())
    if total_energy > 0 and not pd.isna(lcof_lp):
        from efuels_physics import DIESEL_LHV_MWH_PER_T
        lcof_corr = lcof_lp + tranche_correction * DIESEL_LHV_MWH_PER_T / total_energy
    else:
        lcof_corr = lcof_lp
    if meoh_t > 0 and not pd.isna(lcom_lp):
        lcom_corr = lcom_lp + tranche_correction / meoh_t
    else:
        lcom_corr = lcom_lp

    # ── Snapshot opt values for next year's irreversibility bounds ───────
    state.prior_capacity = _snapshot_opt_values(n)
    state.last_solved_year = year

    product_tonnes = m.get("product_tonnes", {})
    row = {
        "year": year,
        "scenario": scenario,
        "capex_per_kw": capex_kw,
        "wacc": wacc,
        "diesel_price_per_t": diesel_p,
        "kero_price_per_t": kero_p,
        "naphtha_price_per_t": naphtha_p,
        "wax_price_per_t": wax_p,
        "imo_premium": params["imo_premium"],
        "electrolyser_mw": ely_mw_now,
        "new_electrolyser_mw": new_ely_mw,
        "cumulative_ely_mw": state.cumulative_ely_mw,
        "electrolyser_cf": m.get("ely_cf", 0.0),
        "synth_mw": m.get("synth_mw", 0.0),
        "h2_store_mwh": m.get("h2_store_mwh", 0.0),
        "meoh_store_mwh": m.get("meoh_store_mwh", 0.0),
        "co2_store_t": m.get("co2_store_t", 0.0),
        "meoh_tonnes": meoh_t,
        "co2_tonnes": m.get("co2_tonnes", 0.0),
        "co2_blended_price": m.get("co2_blended_price", blended_co2_price(year)),
        "co2_by_source": json.dumps(m.get("co2_by_source", {})),
        "naphtha_tonnes": product_tonnes.get("naphtha", 0.0),
        "kero_tonnes": product_tonnes.get("kero", 0.0),
        "diesel_tonnes": product_tonnes.get("diesel", 0.0),
        "wax_tonnes": product_tonnes.get("wax", 0.0),
        "lcom": lcom_corr,
        "lcof": lcof_corr,
        "lcom_lp": lcom_lp,           # uncorrected (LP's current-year-all view)
        "lcof_lp": lcof_lp,
        "ely_tranche_annuity": state.ely_tranche_annuity,
        "annual_capex_process": m.get("annual_capex_process", 0.0),
        "annual_power_cost": m.get("annual_power_cost", 0.0),
        "annual_co2_cost": m.get("annual_co2_cost", 0.0),
        "solve_seconds": round(elapsed, 1),
    }
    print(f"  [{scenario} {year}] ely={ely_mw_now:.0f}MW (+{new_ely_mw:.0f})  "
          f"lcof={lcof_corr:.0f} (lp={lcof_lp:.0f})  "
          f"meoh={meoh_t/1e3:.0f}kt  {elapsed:.0f}s", flush=True)
    return row


def run_branch(scenario: str, years: list[int]) -> list[dict]:
    state = BranchState(scenario=scenario)
    rows: list[dict] = []
    for year in years:
        rows.append(solve_year(scenario=scenario, year=year, state=state))
    return rows


def main(*, workers: int | None = None) -> pd.DataFrame:
    scenarios = list(SCENARIOS)
    total = len(scenarios) * len(YEARS)
    if workers is None:
        workers = min(len(scenarios), os.cpu_count() or 1, 4)
    print(f"Scenarios: {len(scenarios)} | years per scenario: {len(YEARS)} | "
          f"total solves: {total} | workers: {workers}", flush=True)

    all_rows: list[dict] = []
    if workers == 1:
        for scenario in scenarios:
            print(f"\n══ {scenario} ══", flush=True)
            all_rows.extend(run_branch(scenario, YEARS))
            pd.DataFrame(all_rows).to_csv(OUT_CSV, index=False)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(run_branch, sc, YEARS): sc for sc in scenarios}
            for future in as_completed(futures):
                rows = future.result()
                all_rows.extend(rows)
                pd.DataFrame(all_rows).to_csv(OUT_CSV, index=False)

    df = pd.DataFrame(all_rows).sort_values(["scenario", "year"]).reset_index(drop=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV} ({len(df)} rows)")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=None,
                    help="Parallel workers (default: min(scenarios, cpu, 4))")
    ap.add_argument("--serial", action="store_true", help="Force workers=1")
    args = ap.parse_args()
    workers = 1 if args.serial else args.workers
    main(workers=workers)
