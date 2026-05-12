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
from whyalla_pypsa.assumptions import (
    RENEWABLES_PPA_WACC,
    electrolyser_capex_aud_per_kw,
)

from run import default_config
from process_chain import attach_efuels
from efuels_physics import ELECTROLYSER_LIFE_YR
from efuels_results import extract_lcom_lcof
from co2_supply import build_co2_supply_curve, blended_co2_price
from biofuels import attach_biofuels
from biofuels.attach import extract_biofuels_dispatch, BIOFUEL_LINK_NAMES
from heat_integration import load_aemo_cst_profile

YEARS = [2027, 2028, 2029, 2030, 2032, 2035, 2038, 2040]

# Electrolyser CAPEX paths sourced from whyalla_pypsa.assumptions so this
# project and projects/dri-eaf share one citation chain (RESEARCH.md §2).
# Local "fast"/"slow" names retained as scenario aliases; underlying
# learning-curves are "central" and "conservative" in the shared module.
_CAPEX_PATH_ALIAS = {"fast": "central", "slow": "conservative"}
CAPEX_PATHS = {
    alias: {y: electrolyser_capex_aud_per_kw(y, shared) for y in YEARS}
    for alias, shared in _CAPEX_PATH_ALIAS.items()
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
_PROCESS_LINK_NAMES = {"electrolyser", "meoh_synthesis", "electric_heater",
                       "h2_burner", "cst_steam_turbine", "refinery",
                       "shared_hcr_naphtha", "shared_hcr_kero",
                       "shared_hcr_diesel"}
_PROCESS_STORE_NAMES = {"h2_store", "meoh_storage", "co2_storage"}
_PROCESS_GENERATOR_NAMES = {"cst_solar_thermal"}   # extendable process-side generators

# Utility-scale renewables (wind/solar/battery + H₂ vessels) finance at the
# shared RENEWABLES_PPA_WACC; process side keeps the scenario WACC (11%/13%)
# to carry FOAK risk. See RESEARCH.md §3.
RENEWABLES_WACC = RENEWABLES_PPA_WACC

# Refinery modular build rate: ~1-2 FT modules per product per year ≈ 400 MW
# MeOH input capacity. Reflects realistic modular EPC lead times — a single
# product train cannot scale from 0 to full capacity overnight, but multi-
# module parallel construction is achievable for mature modular designs.
REFINERY_MAX_BUILD_DELTA_MW_PER_YEAR = 400.0

# Mandate-driven offtake path (Mt total liquid fuel per year): ramps up to
# reflect growing SAF/CORSIA/IMO/hydrogen-fuel mandates through the 2030s.
# 2029: first-module commissioning (0.2 Mt/y greenfield, FOAK)
# 2030-2032: Phase 1 — meets early CORSIA Phase II + IMO 2030 obligations
# 2035-2040: Phase 2 — scales with maturing EU ReFuelEU + hypothetical AU
#            federal low-carbon liquid fuel mandate (mid-2030s)
# Pre-2029 values are irrelevant (plant is not commissioned).
MANDATE_PATH_MT: dict[int, float] = {
    # Scaled 5× the minimum-viable baseline (0.24 Mt × 5 = 1.2 Mt peak
    # under the old buggy refinery; post-fix 5× = 10.2 Mt peak) to target
    # a cumulative taxpayer cost between JobKeeper ($7.7k/tp) and the
    # 2024 Coalition nuclear policy ($10.1k/tp) over 2027-2040. At 10.2
    # Mt/yr fuel by 2040 the programme delivers ~175 kbpd diesel+jet,
    # ~31% of AU jet+diesel imports — a "serious programme" scale.
    2027: 0.0,   2028: 0.0,   2029: 1.70,
    2030: 2.55,  2032: 4.25,  2035: 6.80,
    2038: 8.50,  2040: 10.20,
}

# CLI --mandate-scale multiplies every year's mandate by this factor so
# the whole trajectory can be re-sized without touching the schedule.
MANDATE_SCALE = 1.0

# Taxpayer costing: AU federal budget numbers (2024-25) — used for per-capita
# and per-taxpayer framing on the lay-audience chart.
AU_TAXPAYERS_2025 = 11_500_000   # ATO 2024 annual income-tax individual filers


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
    for name in n.generators.index:
        if name in _IRREVERSIBILITY_EXCLUDE:
            continue
        if bool(n.generators.at[name, "p_nom_extendable"]):
            n.generators.at[name, "p_nom_min"] = prior.get(f"generators/{name}", 0.0)


def _apply_commissioning_and_lead_times(n, year: int, state: BranchState) -> None:
    """Pre-commission lock (< 2030) and refinery modular build-rate cap."""
    if year < PLANT_COMMISSION_YEAR:
        # Plant under construction — no process capacity allowed.
        for name in n.links.index:
            if name in _PROCESS_LINK_NAMES:
                n.links.at[name, "p_nom_max"] = 0.0
        for name in n.stores.index:
            if name in _PROCESS_STORE_NAMES:
                n.stores.at[name, "e_nom_max"] = 0.0
        for name in n.generators.index:
            if name in _PROCESS_GENERATOR_NAMES and bool(
                    n.generators.at[name, "p_nom_extendable"]):
                n.generators.at[name, "p_nom_max"] = 0.0
        return

    # Commission year is greenfield — the refinery is sized at FID and reaches
    # full initial capacity on opening. The module rate-limit kicks in for
    # expansions from the year after commissioning onward.
    if year == PLANT_COMMISSION_YEAR:
        return
    gap = max(1, year - (state.last_solved_year or year))
    if "refinery" in n.links.index:
        prior_opt = state.prior_capacity.get("links/refinery", 0.0)
        # The single refinery Link carries ~4× the MeOH throughput of
        # an old per-product Link, so relax the lead-time cap 4× to keep
        # the same module build-rate on a total-fuel-output basis.
        n.links.at["refinery", "p_nom_max"] = (
            prior_opt + REFINERY_MAX_BUILD_DELTA_MW_PER_YEAR * 4 * gap
        )


def _lock_biofuels_pre_commission(n, year: int) -> None:
    """Lock all biofuels upgrading links to zero capacity before PLANT_COMMISSION_YEAR.

    Biofuels plants share the same FID → 3-year EPC window as the e-fuel
    plant, so pre-commission years cannot build capacity.
    """
    if year >= PLANT_COMMISSION_YEAR:
        return
    for name in BIOFUEL_LINK_NAMES:
        if name in n.links.index:
            n.links.at[name, "p_nom_max"] = 0.0


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
    for name in n.generators.index:
        if name in _IRREVERSIBILITY_EXCLUDE:
            continue
        if bool(n.generators.at[name, "p_nom_extendable"]):
            out[f"generators/{name}"] = float(n.generators.at[name, "p_nom_opt"])
    return out


def solve_year(*, scenario: str, year: int, state: BranchState,
               enable_biofuels: bool = False,
               mandate_scale: float = 1.0) -> dict:
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
    # Split WACC: renewables at 7% (PPA-backed), process at scenario WACC.
    cfg.pypsa_wacc = RENEWABLES_WACC

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg)

    try:
        cst_profile = load_aemo_cst_profile(n, cfg)
    except FileNotFoundError:
        cst_profile = None   # fall back to PV-derate in heat_integration

    # Re-bind CO2 supply curve to this year so tranche availability matches.
    co2_fn = lambda yr=year: build_co2_supply_curve(yr)
    attach_efuels(
        n,
        electrolyser_capex_per_kw=capex_kw,
        wacc=wacc,
        cst_profile=cst_profile,
        co2_supply_fn=co2_fn,
        diesel_price_per_t=diesel_p,
        kero_price_per_t=kero_p,
        naphtha_price_per_t=naphtha_p,
        wax_price_per_t=wax_p,
        product_split_mode="hydrocracked_ft",
        annual_fuel_mt=MANDATE_PATH_MT.get(year, 0.0) * mandate_scale,
    )

    # ── Biofuels (optional) ──────────────────────────────────────────────
    # Attach with same WACC as the process side — biofuels plants carry
    # comparable FOAK / technology risk to the e-fuel kit.
    if enable_biofuels:
        attach_biofuels(n, wacc=wacc)

    # ── Irreversibility + commissioning + refinery lead times ────────────
    _apply_irreversibility(n, state.prior_capacity)
    _apply_commissioning_and_lead_times(n, year, state)
    if enable_biofuels:
        _lock_biofuels_pre_commission(n, year)

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

    # ── On-site renewable + grid-import readouts ─────────────────────────
    def _gen_opt(name: str) -> float:
        return float(n.generators.at[name, "p_nom_opt"]) if name in n.generators.index else 0.0
    def _link_opt(name: str) -> float:
        return float(n.links.at[name, "p_nom_opt"]) if name in n.links.index else 0.0
    def _store_opt(name: str) -> float:
        return float(n.stores.at[name, "e_nom_opt"]) if name in n.stores.index else 0.0
    wind_mw = _gen_opt("wind")
    solar_mw = _gen_opt("solar")
    battery_charge_mw = _link_opt("battery_charge")
    battery_store_mwh = _store_opt("battery_store")
    snap_w_hrs = float(n.snapshot_weightings.generators.iloc[0])
    grid_import_twh = (
        float(n.links_t.p0.get("grid_import", 0).sum()) * snap_w_hrs / 1e6
        if "grid_import" in n.links.index else 0.0
    )

    # ── Taxpayer subsidy gap (CfD / mandate-premium-style) ───────────────
    # Cost to produce = LCOF × diesel-equivalent tonnes (energy-basis).
    # Fossil-market revenue = Σ product_tonnes[p] × fossil_price[p]
    # Subsidy_per_year = cost_to_produce − fossil_market_revenue
    # (Positive = taxpayer must plug gap via mandate premium / CfD strike.)
    fossil_prices = {
        "diesel":  diesel_p,
        "kero":    kero_p,
        "naphtha": naphtha_p,
        "wax":     wax_p,
    }
    product_energy_mwh = m.get("product_energy_mwh", {})
    total_energy_mwh = sum(product_energy_mwh.values())
    # Import here so we don't pay the startup cost for pre-2029 empty solves.
    from efuels_physics import DIESEL_LHV_MWH_PER_T
    diesel_equiv_t = total_energy_mwh / DIESEL_LHV_MWH_PER_T if total_energy_mwh > 0 else 0.0
    cost_to_produce = lcof_corr * diesel_equiv_t if diesel_equiv_t > 0 and not pd.isna(lcof_corr) else 0.0
    fossil_market_revenue = sum(
        product_tonnes.get(p, 0.0) * fossil_prices[p] for p in fossil_prices
    )
    annual_subsidy = max(0.0, cost_to_produce - fossil_market_revenue)
    mandated_mt = MANDATE_PATH_MT.get(year, 0.0) * mandate_scale
    subsidy_per_t_mandated = (annual_subsidy / (mandated_mt * 1e6)) if mandated_mt > 0 else 0.0
    subsidy_per_taxpayer = annual_subsidy / AU_TAXPAYERS_2025

    # ── Biofuels dispatch readouts (empty dict if biofuels disabled) ─────
    biofuels_row = extract_biofuels_dispatch(n) if enable_biofuels else {}

    row = {
        "year": year,
        "scenario": scenario,
        "biofuels_enabled": enable_biofuels,
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
        "wind_mw": wind_mw,
        "solar_mw": solar_mw,
        "battery_charge_mw": battery_charge_mw,
        "battery_store_mwh": battery_store_mwh,
        "grid_import_twh_y": grid_import_twh,
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
        "mandated_fuel_mt": mandated_mt,
        "fossil_market_revenue_aud": fossil_market_revenue,
        "cost_to_produce_aud": cost_to_produce,
        "annual_subsidy_aud": annual_subsidy,
        "subsidy_per_t_mandated_aud": subsidy_per_t_mandated,
        "subsidy_per_taxpayer_aud": subsidy_per_taxpayer,
        # Heat + CST capacities (from extract_lcom_lcof)
        "electric_heater_mw_th": m.get("electric_heater_mw_th", 0.0),
        "h2_burner_mw_th": m.get("h2_burner_mw_th", 0.0),
        "cst_mw_th": m.get("cst_mw", 0.0),
        "cst_turbine_mw_el": m.get("cst_turbine_mw_el", 0.0),
        # Refinery capacities per product (MW MeOH input)
        "refinery_mw": m.get("refinery_caps_mw_meoh", {}).get("aggregate", 0.0),
        "shared_hcr_naphtha_t_per_hr": m.get("shared_hcr_caps_t_per_hr", {}).get("naphtha", 0.0),
        "shared_hcr_kero_t_per_hr":    m.get("shared_hcr_caps_t_per_hr", {}).get("kero",    0.0),
        "shared_hcr_diesel_t_per_hr":  m.get("shared_hcr_caps_t_per_hr", {}).get("diesel",  0.0),
        "solve_seconds": round(elapsed, 1),
    }
    row.update(biofuels_row)
    biof_msg = ""
    if enable_biofuels and biofuels_row:
        htl_t  = biofuels_row.get("htl_t_dry_per_yr", 0.0) / 1e3
        hefa_t = biofuels_row.get("hefa_t_oil_per_yr", 0.0) / 1e3
        pyr_t  = biofuels_row.get("pyrolysis_t_dry_per_yr", 0.0) / 1e3
        gas_t  = biofuels_row.get("gasification_t_dry_per_yr", 0.0) / 1e3
        biof_msg = (f"  bio=[htl:{htl_t:.0f}kt hefa:{hefa_t:.0f}kt "
                    f"pyr:{pyr_t:.0f}kt gas:{gas_t:.0f}kt]")
    print(f"  [{scenario} {year}] ely={ely_mw_now:.0f}MW (+{new_ely_mw:.0f})  "
          f"mandate={mandated_mt:.2f}Mt  "
          f"subsidy=${annual_subsidy/1e9:.2f}B ({subsidy_per_taxpayer:.0f}$/taxpayer)  "
          f"lcof={lcof_corr:.0f}{biof_msg}  {elapsed:.0f}s", flush=True)
    return row


def run_branch(scenario: str, years: list[int],
               enable_biofuels: bool = False,
               mandate_scale: float = 1.0) -> list[dict]:
    state = BranchState(scenario=scenario)
    rows: list[dict] = []
    for year in years:
        rows.append(solve_year(scenario=scenario, year=year, state=state,
                                enable_biofuels=enable_biofuels,
                                mandate_scale=mandate_scale))
    return rows


def main(*, workers: int | None = None,
         scenarios: list[str] | None = None,
         years: list[int] | None = None,
         enable_biofuels: bool = False,
         mandate_scale: float = 1.0,
         out_csv: Path | None = None) -> pd.DataFrame:
    scenarios = scenarios or list(SCENARIOS)
    years = years or YEARS
    out_path = out_csv or OUT_CSV
    total = len(scenarios) * len(years)
    if workers is None:
        workers = min(len(scenarios), os.cpu_count() or 1, 4)
    biof = "ON" if enable_biofuels else "off"
    print(f"Scenarios: {len(scenarios)} | years per scenario: {len(years)} | "
          f"total solves: {total} | workers: {workers} | biofuels: {biof}",
          flush=True)

    all_rows: list[dict] = []
    if workers == 1:
        for scenario in scenarios:
            print(f"\n══ {scenario} ══", flush=True)
            all_rows.extend(run_branch(scenario, years, enable_biofuels, mandate_scale))
            pd.DataFrame(all_rows).to_csv(out_path, index=False)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(run_branch, sc, years, enable_biofuels, mandate_scale): sc
                       for sc in scenarios}
            for future in as_completed(futures):
                rows = future.result()
                all_rows.extend(rows)
                pd.DataFrame(all_rows).to_csv(out_path, index=False)

    df = pd.DataFrame(all_rows).sort_values(["scenario", "year"]).reset_index(drop=True)
    df.to_csv(out_path, index=False)
    print(f"\nWrote {out_path} ({len(df)} rows)")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=None,
                    help="Parallel workers (default: min(scenarios, cpu, 4))")
    ap.add_argument("--serial", action="store_true", help="Force workers=1")
    ap.add_argument("--biofuels", action="store_true",
                    help="Enable biofuels pathways (HTL, HEFA, pyrolysis, gasification)")
    ap.add_argument("--scenarios", nargs="+", default=None,
                    help="Subset of scenarios to run (default: all)")
    ap.add_argument("--out", default=None,
                    help="Output CSV path (default: trajectory.csv)")
    ap.add_argument("--mandate-scale", type=float, default=1.0,
                    help="Multiplier on MANDATE_PATH_MT (default: 1.0)")
    args = ap.parse_args()
    workers = 1 if args.serial else args.workers
    main(workers=workers,
         scenarios=args.scenarios,
         enable_biofuels=args.biofuels,
         mandate_scale=args.mandate_scale,
         out_csv=Path(args.out) if args.out else None)
