"""Debug accelerated_transition / 2041 / Policy-stated infeasibility.

Strategy:
  1. Replay the branch 2028→2040 to build state. State is pickled so we can
     re-run diagnostics without paying the ~30-min replay cost again.
  2. Build the 2041 network with the prior state, then attempt the solve under
     a series of diagnostic relaxations to localise the binding infeasibility:
       - baseline (replicate the failure)
       - drop biomethane generator
       - drop electrolyser irreversibility (allow downsize)
       - drop heat-system irreversibility
       - drop facility-base irreversibility (wind/solar/battery)
       - drop grid-link irreversibility
  3. Report which relaxation(s) flip the solve to optimal.

Usage:
  uv run python debug_2041_infeasible.py [--rebuild-state]
"""
from __future__ import annotations

import argparse
import copy
import pickle
import time
from pathlib import Path

from generate_trajectory import (
    BranchState,
    POLICY_SCENARIOS,
    ISP_SCENARIOS,
    ISP_NAMES,
    NG_INTENSITY_MWH_PER_T_DRI,
    CO2_INTENSITY_KG_PER_T_DRI,
    GAS_DEAL_LAST_YEAR,
    GAS_DEAL_VOLUME_PJ_PER_YR,
    GAS_SPOT_PRICE_PER_GJ,
    NOAK_WACC,
    SCRAP_TIER1_CAPACITY_T_PER_YR,
    SCRAP_TIER1_PRICE_PER_T,
    SCRAP_TIER2_CAPACITY_T_PER_YR,
    SCRAP_TIER2_PRICE_PER_T,
    ELY_CAPEX_BY_YEAR,
    FURNACE_OPEN_YEAR,
    _biomethane_for_year,
    carbon_price,
    ely_wacc_for_new_investment,
    solve_year,
)
from run import default_config
from process_chain import attach_dri_eaf
from whyalla_pypsa import build_facility_network, attach_grid_price


HERE = Path(__file__).parent
STATE_PICKLE = HERE / ".debug_2041_state.pkl"

POLICY = "Policy-stated + gas flat"
ISP = "accelerated_transition"
PRIOR_YEARS = [2028, 2030, 2033, 2037, 2040]


def replay_state(force: bool = False) -> BranchState:
    if STATE_PICKLE.exists() and not force:
        print(f"Loading cached state from {STATE_PICKLE}")
        with STATE_PICKLE.open("rb") as f:
            return pickle.load(f)

    print("Replaying accelerated_transition / Policy-stated 2028→2040...")
    state = BranchState(policy=POLICY, isp=ISP)
    for year in PRIOR_YEARS:
        t0 = time.perf_counter()
        row = solve_year(policy=POLICY, isp=ISP, year=year, state=state)
        dt = time.perf_counter() - t0
        print(
            f"  {year}: {dt:.0f}s  ely={row['electrolyser_mw']:.0f} MW  "
            f"h2={row['h2_fraction']:.1%}  bm={row.get('total_biomethane_mwh', 0)*3.6/1e6:.2f} PJ"
        )
    with STATE_PICKLE.open("wb") as f:
        pickle.dump(state, f)
    print(f"Cached state to {STATE_PICKLE}")
    return state


def build_2041_network(
    state: BranchState,
    *,
    apply_ely_irrev: bool = True,
    apply_heat_irrev: bool = True,
    apply_base_irrev: bool = True,
    apply_grid_irrev: bool = True,
    drop_biomethane: bool = False,
):
    """Build the 2041 network with optional relaxations."""
    year = 2041
    params = POLICY_SCENARIOS[POLICY]
    ely_capex = ELY_CAPEX_BY_YEAR[year]
    carbon_p = carbon_price(params, year)

    # Year > GAS_DEAL_LAST_YEAR: spot only, no cap.
    gas_p = GAS_SPOT_PRICE_PER_GJ
    gas_volume_pj = None

    biomethane_pj, biomethane_price_per_gj = _biomethane_for_year(POLICY, year)
    if drop_biomethane:
        biomethane_pj = None

    wacc_new = ely_wacc_for_new_investment(state)
    cfg = default_config(grid_mode="sa_dispatch", model_year=year)
    cfg = copy.deepcopy(cfg)
    cfg.scenario.file_token = ISP_SCENARIOS[ISP]
    cfg.scenario.name = ISP_NAMES[ISP]
    cfg.pypsa_wacc = NOAK_WACC

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg, carbon_price_per_t_co2=carbon_p)
    attach_dri_eaf(
        n,
        electrolyser_capex_per_kw=ely_capex,
        wacc=wacc_new,
        dual_fuel=True,
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
        scrap_max_share=0.30,
    )

    if apply_ely_irrev:
        n.links.at["electrolyser", "p_nom_min"] = state.cumulative_ely_mw
        if "h2_store" in n.stores.index:
            n.stores.at["h2_store", "e_nom_min"] = state.cumulative_h2_store_mwh
    if apply_heat_irrev:
        if "electric_heater" in n.links.index:
            n.links.at["electric_heater", "p_nom_min"] = state.cumulative_electric_heater_mw
        if "h2_burner" in n.links.index:
            n.links.at["h2_burner", "p_nom_min"] = state.cumulative_h2_burner_mw
    if apply_base_irrev:
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
    if apply_grid_irrev:
        if "grid_import" in n.links.index:
            n.links.at["grid_import", "p_nom_min"] = state.cumulative_grid_link_mw
        if "grid_export" in n.links.index:
            n.links.at["grid_export", "p_nom_min"] = state.cumulative_grid_link_mw

    return n, cfg


def try_solve(label: str, n, cfg) -> tuple[str, str, float]:
    t0 = time.perf_counter()
    solver_opts = dict(cfg.solver_options)
    solver_opts["run_crossover"] = "off"
    solver_opts["threads"] = 4
    status, condition = n.optimize(
        solver_name=cfg.solver,
        solver_options=solver_opts,
        extra_functionality=getattr(n, "_dri_shaft_constraint", None),
    )
    dt = time.perf_counter() - t0
    print(f"  [{label}] {status}/{condition}  ({dt:.0f}s)")
    return status, condition, dt


def build_2041_network_with_overrides(
    state: BranchState,
    *,
    isp_override: str | None = None,
    year_override: int = 2041,
    use_deal_gas: bool = False,
    drop_extra_func: bool = False,
):
    """Build 2041 network with all irrev DROPPED + targeted overrides."""
    year = year_override
    isp = isp_override or ISP
    params = POLICY_SCENARIOS[POLICY]
    ely_capex = ELY_CAPEX_BY_YEAR[year]
    carbon_p = carbon_price(params, year)

    if use_deal_gas:
        gas_p = params["gas_per_gj"]
        gas_volume_pj = GAS_DEAL_VOLUME_PJ_PER_YR
    else:
        if year > GAS_DEAL_LAST_YEAR:
            gas_p = GAS_SPOT_PRICE_PER_GJ
            gas_volume_pj = None
        else:
            gas_p = params["gas_per_gj"]
            gas_volume_pj = GAS_DEAL_VOLUME_PJ_PER_YR

    biomethane_pj, biomethane_price_per_gj = _biomethane_for_year(POLICY, year)
    wacc_new = ely_wacc_for_new_investment(state)
    cfg = default_config(grid_mode="sa_dispatch", model_year=year)
    cfg = copy.deepcopy(cfg)
    cfg.scenario.file_token = ISP_SCENARIOS[isp]
    cfg.scenario.name = ISP_NAMES[isp]
    cfg.pypsa_wacc = NOAK_WACC

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg, carbon_price_per_t_co2=carbon_p)
    attach_dri_eaf(
        n,
        electrolyser_capex_per_kw=ely_capex,
        wacc=wacc_new,
        dual_fuel=True,
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
        scrap_max_share=0.30,
    )
    if drop_extra_func and hasattr(n, "_dri_shaft_constraint"):
        n._dri_shaft_constraint = None
    return n, cfg


def main(rebuild: bool = False) -> None:
    state = replay_state(force=rebuild)
    print(
        f"\nState at end of 2040: ely={state.cumulative_ely_mw:.0f} MW, "
        f"h2_store={state.cumulative_h2_store_mwh:.0f} MWh, "
        f"eh={state.cumulative_electric_heater_mw:.0f} MW, "
        f"hb={state.cumulative_h2_burner_mw:.0f} MW, "
        f"wind={state.cumulative_wind_mw:.0f} MW, "
        f"solar={state.cumulative_solar_mw:.0f} MW, "
        f"batt_p={state.cumulative_battery_power_mw:.0f} MW, "
        f"batt_e={state.cumulative_battery_energy_mwh:.0f} MWh, "
        f"grid={state.cumulative_grid_link_mw:.0f} MW"
    )

    diagnostics = [
        # Round 2: 2041 problem itself (irrev already shown not to be the cause)
        ("R2 baseline (acce_trans, 2041, spot gas)",
         dict(isp_override="accelerated_transition")),
        ("R2 swap to step_change ISP",
         dict(isp_override="step_change")),
        ("R2 swap to slower_growth ISP",
         dict(isp_override="slower_growth")),
        ("R2 use deal gas (acce_trans, 2041)",
         dict(isp_override="accelerated_transition", use_deal_gas=True)),
        ("R2 drop dri_shaft constraint",
         dict(isp_override="accelerated_transition", drop_extra_func=True)),
        ("R2 use 2040 instead of 2041 (acce_trans)",
         dict(isp_override="accelerated_transition", year_override=2040)),
        ("R2 step_change + 2041",
         dict(isp_override="step_change", year_override=2041)),
    ]
    use_overrides = True

    diagnostics_orig = [
        ("baseline (all irrev applied)", dict()),
        ("drop biomethane", dict(drop_biomethane=True)),
        ("drop ely irrev", dict(apply_ely_irrev=False)),
        ("drop heat irrev", dict(apply_heat_irrev=False)),
        ("drop base irrev (VRE/batt)", dict(apply_base_irrev=False)),
        ("drop grid irrev", dict(apply_grid_irrev=False)),
        ("drop ALL irrev", dict(
            apply_ely_irrev=False, apply_heat_irrev=False,
            apply_base_irrev=False, apply_grid_irrev=False,
        )),
    ]
    if not use_overrides:
        diagnostics = diagnostics_orig

    print("\nDiagnostic relaxations (Round 2 — probe 2041 problem itself):")
    print("=" * 60)
    results: list[tuple[str, str, str, float]] = []
    for label, kwargs in diagnostics:
        if use_overrides:
            n, cfg = build_2041_network_with_overrides(state, **kwargs)
        else:
            n, cfg = build_2041_network(state, **kwargs)
        status, condition, dt = try_solve(label, n, cfg)
        results.append((label, status, condition, dt))

    print("\nSummary:")
    for label, status, condition, dt in results:
        print(f"  {status}/{condition:>12}  {dt:>4.0f}s  {label}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild-state", action="store_true",
                        help="Force replay of 2028→2040 even if cached.")
    args = parser.parse_args()
    main(rebuild=args.rebuild_state)
