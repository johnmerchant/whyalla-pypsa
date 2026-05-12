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
from whyalla_pypsa.assumptions import (
    ELECTROLYSER_LIFE_YEARS,
    H2_STORE_LIFE_YEARS,
    H2_STORE_CAPEX_AUD_PER_MWH,
    FOAK_WACC,
    NOAK_WACC,
    electrolyser_capex_aud_per_kw,
)

from run import default_config
from process_chain import attach_dri_eaf
from whyalla_results import extract_lcoh_lcos


HERE = Path(__file__).parent
OUT_CSV = HERE / "trajectory.csv"

# ── Process parameters (must match attach_dri_eaf defaults) ─────────────────
NG_INTENSITY_MWH_PER_T_DRI = 3.0
CO2_INTENSITY_KG_PER_T_DRI = 560.0
ELY_LIFETIME_YEARS = ELECTROLYSER_LIFE_YEARS
H2_STORE_LIFETIME_YEARS = H2_STORE_LIFE_YEARS

# Heater and burner capex are held flat (mature technology classes). No
# thermal storage is modelled — see README §11 (thermal storage as an
# unmodelled optimisation lever for 100% H₂ pathways) and project
# RESEARCH.md §3.
ELECTRIC_HEATER_CAPEX_PER_KW_TH = 400.0
ELECTRIC_HEATER_LIFETIME_YEARS = 20
H2_BURNER_CAPEX_PER_KW_TH = 30.0
H2_BURNER_LIFETIME_YEARS = 20

# ── Tier 1 structural constants ─────────────────────────────────────────────
# FOAK_WACC, NOAK_WACC imported from whyalla_pypsa.assumptions. See top-level
# RESEARCH.md §3 for the WACC framework citation.
FOAK_NOAK_THRESHOLD_MW = 100.0
FURNACE_OPEN_YEAR = 2030  # MIDREX Flex commissions with pipeline gas (March 2030).
# Whyalla brownfield: existing site has ~150 MW EAF-era electrical connection.
# Seeded as a zero-capex tranche in BranchState so trajectory additions above
# 150 MW are the only entries in the capital-works schedule.
GRID_LINK_BASELINE_MW = 150.0
# Two-tier scrap supply curve. Tier 1 is Whyalla's contracted share of AU
# domestic HMS 80:20 (BIR World Steel Recycling: AU recovers ~6 Mt/yr;
# ~1 Mt is realistically allocable to a single mill without disrupting
# competing consumers). Tier 2 is premium HMS / shred plus seaborne imports
# (China/India landed ~$700-850/t), the marginal source once domestic is
# exhausted. Per-hour caps imply annual budgets at full utilisation. See
# memory: project_whyalla_scrap_and_phase_model.
SCRAP_TIER1_CAPACITY_T_PER_YR = 1_000_000.0
SCRAP_TIER1_PRICE_PER_T = 500.0
SCRAP_TIER2_CAPACITY_T_PER_YR = 800_000.0
SCRAP_TIER2_PRICE_PER_T = 700.0

# ── Scenario grid ───────────────────────────────────────────────────────────
# 2041–2042 picked up after the Santos foundation gas contract expires so the
# dunkelflaute economics shift from "deal gas covers low-VRE weeks" to
# "spot gas is expensive enough that H2 wins".
YEARS = [2028, 2030, 2033, 2037, 2040, 2041, 2042]

# ── Santos foundation gas contract ──────────────────────────────────────────
# Pipeline first gas March 2030 at 20 PJ/yr (memory: project_whyalla_pipeline_timing).
# Foundation contracts of this size are typically 10-year deals — assume the
# contract runs through FY2040 and expires 2041-01. Post-deal years buy spot
# gas at Asian-LNG netback (≈ AUD 22/GJ in 2025 dollars; sensitivity is the
# key headline for §10 of the README).
GAS_DEAL_VOLUME_PJ_PER_YR = 20.0
GAS_DEAL_LAST_YEAR = 2040
GAS_SPOT_PRICE_PER_GJ = 22.0

# ── SA biomethane availability + price ──────────────────────────────────────
# Source: BIOMETHANE.md (this project). Three supply-side scenarios driven by
# Federal Renewable Fuel Scheme certificate market liquidity (2028+) and SA
# demand-side mechanisms. We map the three policy scenarios used in the
# DRI-EAF trajectory to those biomethane supply scenarios:
#   Delayed action          → status_quo        (no policy push, SA1 + slow drift)
#   Policy-stated           → policy_enabled    (RFS at moderate price, SA mandate)
#   CBAM-binding            → resource_ceiling  (binding carbon → fastest pull)
#   No gas (100% H2)        → none              (no NG demand to substitute into)
# Annual availability is PJ/yr injected to SA network and serves as the
# `e_sum_max` annual energy cap on the biomethane_supply generator. The
# 2041 entry interpolates linearly between 2040 and 2042 (BIOMETHANE.md skips
# 2041). All other modelled years (2028, 2030, 2033, 2037, 2040, 2042) are
# directly from the spec table.
BIOMETHANE_AVAILABILITY_PJ_PER_YR: dict[str, dict[int, float]] = {
    "status_quo": {
        2028: 0.21, 2030: 0.35, 2033: 0.50, 2037: 0.80,
        2040: 1.10, 2041: 1.20, 2042: 1.30,
    },
    "policy_enabled": {
        2028: 0.25, 2030: 0.60, 2033: 1.30, 2037: 2.60,
        2040: 3.60, 2041: 3.90, 2042: 4.20,
    },
    "resource_ceiling": {
        2028: 0.30, 2030: 0.90, 2033: 2.40, 2037: 5.20,
        2040: 7.50, 2041: 8.00, 2042: 8.50,
    },
}

# Tier-blended delivered prices (A$/GJ, 2026 dollars). Composition reflects
# how each scenario climbs the BIOMETHANE.md supply curve:
#   status_quo       : tier 1 landfill + early tier 2 (SA1) → ~$14/GJ
#   policy_enabled   : balanced tier 1+2+3 (SA1 + follow-on AD)  → ~$17/GJ
#   resource_ceiling : heavy tier 3 crop residues to hit volume → ~$22/GJ
# CPI-escalated 2.77%/yr from 2026 base year (ACIL Allen 2024 IASR), applied
# to the marginal cost in `_biomethane_for_year` below.
BIOMETHANE_BASE_PRICE_2026_PER_GJ: dict[str, float] = {
    "status_quo": 14.0,
    "policy_enabled": 17.0,
    "resource_ceiling": 22.0,
}
BIOMETHANE_CPI_RATE = 0.0277

POLICY_TO_BIOMETHANE_SCENARIO: dict[str, str | None] = {
    "Policy-stated + gas flat": "policy_enabled",
    "CBAM-binding + gas rising": "resource_ceiling",
    "Delayed action + gas flat": "status_quo",
    "No gas (100% H2)": None,
}


def _biomethane_for_year(policy: str, year: int) -> tuple[float | None, float]:
    """Return (annual_volume_PJ, delivered_price_$/GJ) for biomethane this year.

    Volume is None when the policy has no biomethane availability (e.g. the
    no-gas branch never burns gas, so there is nothing to substitute).
    """
    scenario = POLICY_TO_BIOMETHANE_SCENARIO.get(policy)
    if scenario is None:
        return None, 0.0
    table = BIOMETHANE_AVAILABILITY_PJ_PER_YR[scenario]
    pj = table.get(year, 0.0)
    base_price = BIOMETHANE_BASE_PRICE_2026_PER_GJ[scenario]
    price = base_price * (1.0 + BIOMETHANE_CPI_RATE) ** (year - 2026)
    return pj, price

# Electrolyser + H2 storage capex paths sourced from the shared module so both
# this project and projects/efuels reference one citation chain (RESEARCH.md §2).
ELY_CAPEX_BY_YEAR = {y: electrolyser_capex_aud_per_kw(y, "central") for y in YEARS}
H2_STORE_CAPEX_BY_YEAR = {y: H2_STORE_CAPEX_AUD_PER_MWH for y in YEARS}

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
    # 100% H2 mandate: no NG reductant ever (IEEFA-style critique baseline).
    # Modelled as MIDREX H2 — no reformer, electric resistance heater on the
    # shaft, electrolyser must cover 100 % of reductant load. Skipped pre-2030
    # (no shaft commissioned yet). Same carbon / gas signals as Policy-stated
    # so we isolate the no-gas mandate effect from policy-mix effects.
    "No gas (100% H2)": {
        "carbon_2030": 63.0, "carbon_2040": 120.0, "gas_per_gj": 12.0,
        "dual_fuel": False,
    },
}

ISP_SCENARIOS = {
    "slower_growth": "SLOWER_GROWTH",
    "step_change": "STEP_CHANGE",
    "accelerated_transition": "ACCELERATED_TRANSITION",
}

# scenario.name picks the GGO workbook ("Draft_2026 ISP - {name} - Core.xlsx" in
# sa_network._default_ggo_path); demand traces and PLEXOS XML use file_token.
# Set both together — a mismatch silently loads Step Change capacity with the
# requested demand traces, which can pass for years where buildout is sufficient
# and trip presolve infeasibility at high-demand years (see acce_trans/2041).
ISP_NAMES = {
    "slower_growth": "Slower Growth",
    "step_change": "Step Change",
    "accelerated_transition": "Accelerated Transition",
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
    # Heat system — monotone-additive capacity trajectory. Each year's solve
    # picks p_nom / e_nom given prior-year floors; delta becomes a new tranche.
    electric_heater_tranches: list[Tranche] = field(default_factory=list)
    h2_burner_tranches: list[Tranche] = field(default_factory=list)
    # Facility base (VRE + battery + grid link) — monotone-additive. Needed
    # for a truthful capital-works schedule; a wind farm can be built but
    # not un-built between years.
    wind_tranches: list[Tranche] = field(default_factory=list)
    solar_tranches: list[Tranche] = field(default_factory=list)
    battery_power_tranches: list[Tranche] = field(default_factory=list)
    battery_energy_tranches: list[Tranche] = field(default_factory=list)
    # Pre-seeded with the Whyalla brownfield baseline (150 MW, $0 capex) —
    # represents the existing EAF-era site electrical connection. Only
    # additions above baseline appear in the capital-works schedule.
    grid_link_tranches: list[Tranche] = field(
        default_factory=lambda: [Tranche(
            build_year=0,
            capacity=GRID_LINK_BASELINE_MW,
            annuity_per_unit=0.0,
            wacc=0.0,
            capex_per_unit=0.0,
        )],
    )

    @property
    def cumulative_ely_mw(self) -> float:
        return sum(t.capacity for t in self.ely_tranches)

    @property
    def cumulative_h2_store_mwh(self) -> float:
        return sum(t.capacity for t in self.h2_store_tranches)

    @property
    def cumulative_electric_heater_mw(self) -> float:
        return sum(t.capacity for t in self.electric_heater_tranches)

    @property
    def cumulative_h2_burner_mw(self) -> float:
        return sum(t.capacity for t in self.h2_burner_tranches)

    @property
    def cumulative_wind_mw(self) -> float:
        return sum(t.capacity for t in self.wind_tranches)

    @property
    def cumulative_solar_mw(self) -> float:
        return sum(t.capacity for t in self.solar_tranches)

    @property
    def cumulative_battery_power_mw(self) -> float:
        return sum(t.capacity for t in self.battery_power_tranches)

    @property
    def cumulative_battery_energy_mwh(self) -> float:
        return sum(t.capacity for t in self.battery_energy_tranches)

    @property
    def cumulative_grid_link_mw(self) -> float:
        return sum(t.capacity for t in self.grid_link_tranches)

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
    # Clip at 2040: scenarios are anchored 2030/2040, so post-2040 the carbon
    # trajectory holds flat rather than extrapolating linearly into territory
    # the source doesn't anchor.
    eff_year = min(year, 2040)
    return c30 + slope * (eff_year - 2030)


def ely_wacc_for_new_investment(state: BranchState) -> float:
    """FOAK until >100 MW proven at site, NOAK thereafter."""
    return NOAK_WACC if state.cumulative_ely_mw > FOAK_NOAK_THRESHOLD_MW else FOAK_WACC


def solve_year(*, policy: str, isp: str, year: int, state: BranchState) -> dict:
    """Solve one year given the branch's prior state; mutates state to record new tranches."""
    params = POLICY_SCENARIOS[policy]
    ely_capex = ELY_CAPEX_BY_YEAR[year]
    h2_store_capex = H2_STORE_CAPEX_BY_YEAR[year]
    carbon_p = carbon_price(params, year)
    deal_gas_p = params["gas_per_gj"]
    # Gas-supply structure flips at the Santos foundation contract expiry.
    # In-deal years: deal price + 20 PJ/yr volume cap, spot above the cap.
    # Post-deal years: spot only (no volume cap, single tier at spot price).
    if year <= GAS_DEAL_LAST_YEAR:
        gas_p = deal_gas_p
        gas_volume_pj = GAS_DEAL_VOLUME_PJ_PER_YR
    else:
        gas_p = GAS_SPOT_PRICE_PER_GJ
        gas_volume_pj = None

    biomethane_pj, biomethane_price_per_gj = _biomethane_for_year(policy, year)

    # New-investment WACC this year (FOAK or NOAK).
    wacc_new = ely_wacc_for_new_investment(state)

    cfg = default_config(grid_mode="sa_dispatch", model_year=year)
    cfg = copy.deepcopy(cfg)
    if year < FURNACE_OPEN_YEAR:
        cfg.scenario.snapshot_mode = "representative_weeks"
        cfg.scenario.representative_weeks = 12
    cfg.scenario.file_token = ISP_SCENARIOS[isp]
    cfg.scenario.name = ISP_NAMES[isp]
    # Facility base (wind/solar/battery/h2_storage capex via attach_grid) always NOAK.
    cfg.pypsa_wacc = NOAK_WACC

    dual_fuel = bool(params.get("dual_fuel", True))

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg, carbon_price_per_t_co2=carbon_p)
    # Pre-DRI (pre-2030) phase: EAF commissions early and runs 100% scrap
    # until the pipeline arrives (see memory: project_whyalla_pipeline_timing).
    # In this phase the scrap-share cap is lifted (scrap_max_share=1.0) and
    # both DRI paths are blocked downstream.
    scrap_cap_this_year = 1.0 if year < FURNACE_OPEN_YEAR else 0.30
    attach_dri_eaf(
        n,
        electrolyser_capex_per_kw=ely_capex,
        wacc=wacc_new,
        dual_fuel=dual_fuel,
        ng_intensity_mwh_per_t_dri=NG_INTENSITY_MWH_PER_T_DRI,
        ng_price_per_gj=gas_p,
        ng_annual_volume_pj=gas_volume_pj,
        ng_spot_price_per_gj=GAS_SPOT_PRICE_PER_GJ,
        biomethane_annual_volume_pj=biomethane_pj,
        biomethane_price_per_gj=biomethane_price_per_gj,
        co2_intensity_kg_per_t_dri=CO2_INTENSITY_KG_PER_T_DRI,
        carbon_price_per_t_co2=carbon_p,
        enable_scrap=True,
        scrap_tier1_capacity_t_per_yr=SCRAP_TIER1_CAPACITY_T_PER_YR,
        scrap_tier1_price_per_t=SCRAP_TIER1_PRICE_PER_T,
        scrap_tier2_capacity_t_per_yr=SCRAP_TIER2_CAPACITY_T_PER_YR,
        scrap_tier2_price_per_t=SCRAP_TIER2_PRICE_PER_T,
        scrap_max_share=scrap_cap_this_year,
    )

    # ── Tier 1 constraints ──────────────────────────────────────────────────
    if year < FURNACE_OPEN_YEAR:
        # Pre-DRI phase: electrolyser blocked (no shaft to consume H2), both
        # DRI paths offline (no shaft built, no pipeline gas). EAF meets
        # steel_offtake via 100% scrap. Zero out dri_plant.p_nom as well so
        # the shaft-must-run constraint reads shaft_cap_out == 0 (the
        # constraint closure reads net.links.at["dri_plant", "p_nom"] which
        # otherwise stays at its pre-solve hint, making the ≥40% floor
        # infeasible against a zero p_nom_max upper bound).
        n.links.at["electrolyser", "p_nom_max"] = 0.0
        n.links.at["dri_plant", "p_nom_max"] = 0.0
        n.links.at["dri_plant", "p_nom"] = 0.0
        if "dri_plant_gas" in n.links.index:
            n.links.at["dri_plant_gas", "p_max_pu"] = 0.0
    # Irreversibility: can only add capacity.
    n.links.at["electrolyser", "p_nom_min"] = state.cumulative_ely_mw
    if "h2_store" in n.stores.index:
        n.stores.at["h2_store", "e_nom_min"] = state.cumulative_h2_store_mwh
    # Heat-system irreversibility — solver can grow but not shrink the heater
    # and H2 burner as fuel mixes and prices change across years.
    if "electric_heater" in n.links.index:
        n.links.at["electric_heater", "p_nom_min"] = state.cumulative_electric_heater_mw
    if "h2_burner" in n.links.index:
        n.links.at["h2_burner", "p_nom_min"] = state.cumulative_h2_burner_mw
    # Facility-base irreversibility — wind, solar, battery, grid link. Physical
    # assets, once built, stay. grid_export tracks grid_import (same physical
    # interconnector), so the max of either side is the installed link MW.
    if "wind" in n.generators.index:
        n.generators.at["wind", "p_nom_min"] = state.cumulative_wind_mw
    if "solar" in n.generators.index:
        n.generators.at["solar", "p_nom_min"] = state.cumulative_solar_mw
    if "battery_charge" in n.links.index:
        n.links.at["battery_charge", "p_nom_min"] = state.cumulative_battery_power_mw
    if "battery_discharge" in n.links.index:
        n.links.at["battery_discharge", "p_nom_min"] = state.cumulative_battery_power_mw
    if "battery_store" in n.stores.index:
        n.stores.at["battery_store", "e_nom_min"] = state.cumulative_battery_energy_mwh
    if "grid_import" in n.links.index:
        n.links.at["grid_import", "p_nom_min"] = state.cumulative_grid_link_mw
    if "grid_export" in n.links.index:
        n.links.at["grid_export", "p_nom_min"] = state.cumulative_grid_link_mw

    t0 = time.perf_counter()
    solver_opts = dict(cfg.solver_options)
    solver_opts["run_crossover"] = "off"
    solver_opts["threads"] = 2
    status, condition = n.optimize(
        solver_name=cfg.solver,
        solver_options=solver_opts,
        extra_functionality=getattr(n, "_dri_shaft_constraint", None),
    )
    if status == "warning" and condition != "optimal":
        # IPM didn't reach absolute tolerance, or PyPSA flagged false-infeasible
        # from a tiny constraint violation. Re-solve with crossover (basis
        # purification step) — usually clears the post-IPM consistency check.
        solver_opts["run_crossover"] = "on"
        status, condition = n.optimize(
            solver_name=cfg.solver,
            solver_options=solver_opts,
            extra_functionality=getattr(n, "_dri_shaft_constraint", None),
        )
    if status == "warning" and condition != "optimal":
        # Last-resort fallback: dual simplex. Slower but more numerically
        # robust on degenerate/poorly-scaled instances. Triggered for
        # accelerated_transition/2041 where IPM ± crossover both reported
        # spurious infeasibility despite the IPM finding an interior optimum.
        solver_opts["solver"] = "simplex"
        solver_opts.pop("run_crossover", None)
        status, condition = n.optimize(
            solver_name=cfg.solver,
            solver_options=solver_opts,
            extra_functionality=getattr(n, "_dri_shaft_constraint", None),
        )
    elapsed = time.perf_counter() - t0
    # Accept "warning" status when the termination condition is "optimal"
    # (IPM converged; warning is just an absolute-tolerance message).
    if condition != "optimal" and status not in ("ok", "optimal"):
        raise RuntimeError(f"Solve failed ({policy}, {isp}, {year}): {status}/{condition}")

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

    # Heat-system tranches — read LP's p_nom_opt directly since the results
    # extractor doesn't surface these fields yet.
    eh_mw_now = float(n.links.at["electric_heater", "p_nom_opt"]) if "electric_heater" in n.links.index else 0.0
    hb_mw_now = float(n.links.at["h2_burner", "p_nom_opt"]) if "h2_burner" in n.links.index else 0.0

    new_electric_heater_mw = max(0.0, eh_mw_now - state.cumulative_electric_heater_mw)
    if new_electric_heater_mw > 1e-3:
        state.electric_heater_tranches.append(Tranche(
            build_year=year,
            capacity=new_electric_heater_mw,
            annuity_per_unit=annuitise(
                ELECTRIC_HEATER_CAPEX_PER_KW_TH * 1000.0, NOAK_WACC, ELECTRIC_HEATER_LIFETIME_YEARS,
            ),
            wacc=NOAK_WACC,
            capex_per_unit=ELECTRIC_HEATER_CAPEX_PER_KW_TH,
        ))
    new_h2_burner_mw = max(0.0, hb_mw_now - state.cumulative_h2_burner_mw)
    if new_h2_burner_mw > 1e-3:
        state.h2_burner_tranches.append(Tranche(
            build_year=year,
            capacity=new_h2_burner_mw,
            annuity_per_unit=annuitise(
                H2_BURNER_CAPEX_PER_KW_TH * 1000.0, NOAK_WACC, H2_BURNER_LIFETIME_YEARS,
            ),
            wacc=NOAK_WACC,
            capex_per_unit=H2_BURNER_CAPEX_PER_KW_TH,
        ))

    # Facility-base tranches — wind / solar / battery / grid link. Capex &
    # lifetime come from the FacilityConfig for this solve year (flat today;
    # trivially year-indexable later). NOAK WACC throughout; these are mature
    # asset classes, not FOAK like the first site electrolyser.
    wind_mw_now = float(n.generators.at["wind", "p_nom_opt"]) if "wind" in n.generators.index else 0.0
    solar_mw_now = float(n.generators.at["solar", "p_nom_opt"]) if "solar" in n.generators.index else 0.0
    batt_charge_mw = float(n.links.at["battery_charge", "p_nom_opt"]) if "battery_charge" in n.links.index else 0.0
    batt_discharge_mw = float(n.links.at["battery_discharge", "p_nom_opt"]) if "battery_discharge" in n.links.index else 0.0
    batt_power_mw_now = max(batt_charge_mw, batt_discharge_mw)
    batt_energy_mwh_now = float(n.stores.at["battery_store", "e_nom_opt"]) if "battery_store" in n.stores.index else 0.0
    grid_imp_mw = float(n.links.at["grid_import", "p_nom_opt"]) if "grid_import" in n.links.index else 0.0
    grid_exp_mw = float(n.links.at["grid_export", "p_nom_opt"]) if "grid_export" in n.links.index else 0.0
    grid_link_mw_now = max(grid_imp_mw, grid_exp_mw)

    new_wind_mw = max(0.0, wind_mw_now - state.cumulative_wind_mw)
    if new_wind_mw > 1e-3:
        state.wind_tranches.append(Tranche(
            build_year=year,
            capacity=new_wind_mw,
            annuity_per_unit=annuitise(
                cfg.wind.cost.capex_per_unit * 1000.0, NOAK_WACC, cfg.wind.cost.lifetime_years,
            ),
            wacc=NOAK_WACC,
            capex_per_unit=cfg.wind.cost.capex_per_unit,
        ))
    new_solar_mw = max(0.0, solar_mw_now - state.cumulative_solar_mw)
    if new_solar_mw > 1e-3:
        state.solar_tranches.append(Tranche(
            build_year=year,
            capacity=new_solar_mw,
            annuity_per_unit=annuitise(
                cfg.solar.cost.capex_per_unit * 1000.0, NOAK_WACC, cfg.solar.cost.lifetime_years,
            ),
            wacc=NOAK_WACC,
            capex_per_unit=cfg.solar.cost.capex_per_unit,
        ))
    new_battery_power_mw = max(0.0, batt_power_mw_now - state.cumulative_battery_power_mw)
    if new_battery_power_mw > 1e-3:
        state.battery_power_tranches.append(Tranche(
            build_year=year,
            capacity=new_battery_power_mw,
            annuity_per_unit=annuitise(
                cfg.battery.power_cost.capex_per_unit * 1000.0,
                NOAK_WACC, cfg.battery.power_cost.lifetime_years,
            ),
            wacc=NOAK_WACC,
            capex_per_unit=cfg.battery.power_cost.capex_per_unit,
        ))
    new_battery_energy_mwh = max(0.0, batt_energy_mwh_now - state.cumulative_battery_energy_mwh)
    if new_battery_energy_mwh > 1e-3:
        state.battery_energy_tranches.append(Tranche(
            build_year=year,
            capacity=new_battery_energy_mwh,
            annuity_per_unit=annuitise(
                cfg.battery.energy_cost.capex_per_unit * 1000.0,
                NOAK_WACC, cfg.battery.energy_cost.lifetime_years,
            ),
            wacc=NOAK_WACC,
            capex_per_unit=cfg.battery.energy_cost.capex_per_unit,
        ))
    new_grid_link_mw = max(0.0, grid_link_mw_now - state.cumulative_grid_link_mw)
    if new_grid_link_mw > 1e-3:
        # Grid link lifetime lives under wacc_overlay.grid_link (see facility.py).
        state.grid_link_tranches.append(Tranche(
            build_year=year,
            capacity=new_grid_link_mw,
            annuity_per_unit=annuitise(
                cfg.grid.link_capex_per_mw, NOAK_WACC,
                cfg.wacc_overlay.grid_link.lifetime_years,
            ),
            wacc=NOAK_WACC,
            capex_per_unit=cfg.grid.link_capex_per_mw / 1000.0,  # store as $/kW for CSV consistency
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
        "total_fossil_ng_mwh": m["total_fossil_ng_mwh"],
        "total_biomethane_mwh": m["total_biomethane_mwh"],
        "biomethane_pj_available": (biomethane_pj or 0.0),
        "biomethane_price_per_gj": biomethane_price_per_gj,
        "total_h2_mwh": m["annual_h2_mwh"],
        "scrap_t": m["scrap_t"],
        "scrap_share": m["scrap_share"],
        "electrolyser_mw": m["ely_mw"],
        "new_electrolyser_mw": new_ely_mw,
        "h2_storage_mwh": m["h2_store_mwh"],
        "new_h2_storage_mwh": new_h2_store_mwh,
        "electric_heater_mw": eh_mw_now,
        "new_electric_heater_mw": new_electric_heater_mw,
        "h2_burner_mw": hb_mw_now,
        "new_h2_burner_mw": new_h2_burner_mw,
        "wind_mw": wind_mw_now,
        "new_wind_mw": new_wind_mw,
        "wind_capex_per_kw": cfg.wind.cost.capex_per_unit,
        "solar_mw": solar_mw_now,
        "new_solar_mw": new_solar_mw,
        "solar_capex_per_kw": cfg.solar.cost.capex_per_unit,
        "battery_power_mw": batt_power_mw_now,
        "new_battery_power_mw": new_battery_power_mw,
        "battery_power_capex_per_kw": cfg.battery.power_cost.capex_per_unit,
        "battery_energy_mwh": batt_energy_mwh_now,
        "new_battery_energy_mwh": new_battery_energy_mwh,
        "battery_energy_capex_per_kwh": cfg.battery.energy_cost.capex_per_unit,
        "grid_link_mw": grid_link_mw_now,
        "new_grid_link_mw": new_grid_link_mw,
        "grid_link_capex_per_mw": cfg.grid.link_capex_per_mw,
        "ely_wacc_new": wacc_new,
        "emissions_saved_tCO2": m["emissions_saved_tCO2"],
        "emissions_tCO2": m["emissions_tCO2"],
        "emissions_scope1_tCO2": m["emissions_scope1_tCO2"],
        "emissions_scope2_tCO2": m["emissions_scope2_tCO2"],
        "total_import_mwh": m["total_import_mwh"],
        "total_export_mwh_delivered": m["total_export_mwh_delivered"],
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
    dual_fuel = POLICY_SCENARIOS[policy].get("dual_fuel", True)
    for year in years:
        # No-gas branches: skip pre-shaft-furnace years. Steel comes off the
        # existing blast furnace outside the model; the 100% H2 path only
        # begins from the MIDREX H2 commissioning year (FURNACE_OPEN_YEAR).
        if not dual_fuel and year < FURNACE_OPEN_YEAR:
            print(f"  {policy} / {isp} / {year}  (skipped: no-gas path "
                  f"requires shaft furnace, opens {FURNACE_OPEN_YEAR})", flush=True)
            continue
        print(f"  {policy} / {isp} / {year} "
              f"(prior ely={state.cumulative_ely_mw:.0f} MW, "
              f"WACC_new={ely_wacc_for_new_investment(state):.2f})", flush=True)
        row = solve_year(policy=policy, isp=isp, year=year, state=state)
        bm_pj = row.get("total_biomethane_mwh", 0.0) * 3.6 / 1e6
        print(
            f"    solved in {row['solve_seconds']}s  "
            f"ely={row['electrolyser_mw']:.0f} MW (+{row['new_electrolyser_mw']:.0f}), "
            f"h2_frac={row['h2_fraction']:.2%}, "
            f"bm={bm_pj:.2f} PJ, "
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
