"""Worked-example smoke run: biofuels on vs off, one year, policy_stated.

Runs two greenfield 2035 solves:
  1) E-fuels only (existing process_chain)
  2) E-fuels + biofuels (adds HTL + HEFA + pyrolysis + gasification)

Prints a concise summary of what the optimiser picks in each configuration
so the marginal value of the biofuels option falls out.

Run:
    uv run python run_biofuels_smoke.py
"""
from __future__ import annotations

import argparse
import copy
import time

from whyalla_pypsa import build_facility_network, attach_grid_price

from run import default_config
from process_chain import attach_efuels
from co2_supply import build_co2_supply_curve
from efuels_results import extract_lcom_lcof
from biofuels import attach_biofuels
from biofuels.attach import extract_biofuels_dispatch
from heat_integration import load_aemo_cst_profile


def _solve(year: int, *, enable_biofuels: bool,
           wacc: float = 0.11, mandate_mt: float = 0.8) -> tuple[dict, dict]:
    cfg = copy.deepcopy(default_config())
    cfg.scenario.model_year = year
    cfg.scenario.snapshot_mode = "representative_weeks"
    cfg.scenario.representative_weeks = 8
    cfg.pypsa_wacc = 0.07  # renewables WACC (matches generate_trajectory)

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg)
    try:
        cst_profile = load_aemo_cst_profile(n, cfg)
    except FileNotFoundError:
        cst_profile = None   # fall back to PV-derate in heat_integration

    attach_efuels(
        n,
        electrolyser_capex_per_kw=900.0,    # 2035 fast-decline baseline
        wacc=wacc,
        cst_profile=cst_profile,
        co2_supply_fn=lambda: build_co2_supply_curve(year),
        diesel_price_per_t=2150.0,
        kero_price_per_t=2310.0,
        naphtha_price_per_t=1440.0,
        wax_price_per_t=2500.0,
        product_split_mode="hydrocracked_ft",
        annual_fuel_mt=mandate_mt,
    )

    if enable_biofuels:
        attach_biofuels(n, wacc=wacc)

    t0 = time.perf_counter()
    solver_opts = {**cfg.solver_options, "run_crossover": "off"}
    status, _ = n.optimize(solver_name=cfg.solver, solver_options=solver_opts)
    elapsed = time.perf_counter() - t0
    if status not in ("ok", "optimal"):
        raise RuntimeError(f"solve failed: {status}")

    m = extract_lcom_lcof(n, cfg)
    b = extract_biofuels_dispatch(n) if enable_biofuels else {}
    m["_solve_seconds"] = elapsed
    return m, b


def _print_row(label: str, m: dict, b: dict) -> None:
    pt = m.get("product_tonnes", {})
    print(f"\n── {label} ── ({m['_solve_seconds']:.1f}s)")
    print(f"  LCOF:                {m.get('lcof_per_t_diesel_equivalent', float('nan')):>8.0f} AUD/t diesel-eq")
    print(f"  LCOM:                {m.get('lcom_per_t_meoh', float('nan')):>8.0f} AUD/t MeOH")
    print(f"  Electrolyser:        {m.get('ely_mw', 0.0):>8.0f} MW")
    print(f"  MeOH synthesis:      {m.get('synth_mw', 0.0):>8.0f} MW (H₂ in)")
    print(f"  Process heat:")
    print(f"    Electric heater:   {m.get('electric_heater_mw_th',0):>8.0f} MW_th  {m.get('electric_heater_mwh_per_yr',0)/1e3:.0f} GWh/y")
    print(f"    H₂ burner:         {m.get('h2_burner_mw_th',0):>8.0f} MW_th  {m.get('h2_burner_mwh_h2_per_yr',0)/1e3:.0f} GWh/y (H₂ in)")
    print(f"    CST solar field:   {m.get('cst_mw',0):>8.0f} MW_th  {m.get('cst_mwh_per_yr',0)/1e3:.0f} GWh/y")
    print(f"    CST steam turbine: {m.get('cst_turbine_mw_el',0):>8.0f} MW_el  {m.get('cst_turbine_mwh_el_per_yr',0)/1e3:.0f} GWh_el/y")
    print(f"  E-fuel production:")
    print(f"    diesel:            {pt.get('diesel',  0)/1000:>8.0f} kt/yr")
    print(f"    kero:              {pt.get('kero',    0)/1000:>8.0f} kt/yr")
    print(f"    naphtha:           {pt.get('naphtha', 0)/1000:>8.0f} kt/yr")
    print(f"    wax:               {pt.get('wax',     0)/1000:>8.0f} kt/yr")
    if b:
        print(f"  Biofuels chosen:")
        htl_sw_fuel = (b.get('htl_steelworks_fuel_diesel_t_per_yr',0)
                       + b.get('htl_steelworks_fuel_kero_t_per_yr',0)
                       + b.get('htl_steelworks_fuel_naphtha_t_per_yr',0)) / 1000
        htl_pb_fuel = (b.get('htl_port_bonython_fuel_diesel_t_per_yr',0)
                       + b.get('htl_port_bonython_fuel_kero_t_per_yr',0)
                       + b.get('htl_port_bonython_fuel_naphtha_t_per_yr',0)) / 1000
        print(f"    HTL steelworks:      {b.get('htl_steelworks_t_dry_per_yr', 0)/1000:>8.0f} kt_dry/yr  "
              f"→ {htl_sw_fuel:.0f} kt fuel (uses free DRI heat)")
        print(f"    HTL Port Bonython:   {b.get('htl_port_bonython_t_dry_per_yr', 0)/1000:>8.0f} kt_dry/yr  "
              f"→ {htl_pb_fuel:.0f} kt fuel")
        print(f"    HEFA (halophyte):    {b.get('hefa_t_oil_per_yr', 0)/1000:>8.0f} kt_oil/yr  "
              f"→ {b.get('hefa_fuel_kero_t_per_yr',0)/1000 + b.get('hefa_fuel_diesel_t_per_yr',0)/1000 + b.get('hefa_fuel_naphtha_t_per_yr',0)/1000:.0f} kt fuel")
        print(f"    Pyrolysis:           {b.get('pyrolysis_t_dry_per_yr', 0)/1000:>8.0f} kt_dry/yr  "
              f"→ {b.get('pyrolysis_fuel_diesel_t_per_yr',0)/1000 + b.get('pyrolysis_fuel_kero_t_per_yr',0)/1000 + b.get('pyrolysis_fuel_naphtha_t_per_yr',0)/1000:.0f} kt fuel")
        print(f"    Gasification:        {b.get('gasification_t_dry_per_yr', 0)/1000:>8.0f} kt_dry/yr  "
              f"(biogenic H₂+CO₂ → existing MeOH synth)")
        print(f"    Waste heat used:     {b.get('waste_heat_used_mwh_per_yr', 0)/1000:>8.0f} GWh_th/yr "
              f"(cap 200 GWh/yr)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2035)
    ap.add_argument("--mandate-mt", type=float, default=0.8)
    args = ap.parse_args()

    print(f"═══ Biofuels smoke: policy_stated, year={args.year}, "
          f"mandate={args.mandate_mt} Mt ═══")

    m_off, _ = _solve(args.year, enable_biofuels=False, mandate_mt=args.mandate_mt)
    _print_row("E-fuels ONLY", m_off, {})

    m_on, b_on = _solve(args.year, enable_biofuels=True, mandate_mt=args.mandate_mt)
    _print_row("E-fuels + Biofuels", m_on, b_on)

    # Delta summary
    d_lcof = (m_on.get("lcof_per_t_diesel_equivalent", float("nan"))
              - m_off.get("lcof_per_t_diesel_equivalent", float("nan")))
    d_ely = m_on.get("ely_mw", 0.0) - m_off.get("ely_mw", 0.0)
    print(f"\n── Δ (biofuels − efuels-only) ──")
    print(f"  LCOF:                {d_lcof:+.0f} AUD/t diesel-eq")
    print(f"  Electrolyser:        {d_ely:+.0f} MW")


if __name__ == "__main__":
    main()
