"""Orchestrator: build facility network, attach DRI-EAF chain, solve, extract metrics."""
from __future__ import annotations

from whyalla_pypsa import (
    FacilityConfig,
    WindConfig,
    SolarConfig,
    BatteryConfig,
    H2StorageConfig,
    GridConfig,
    ScenarioConfig,
    CostAssumption,
    build_facility_network,
    attach_grid_price,
)

from process_chain import attach_dri_eaf
from whyalla_results import extract_lcoh_lcos


def default_config(
    *,
    grid_mode: str = "sa_dispatch",
    model_year: int = 2030,
    snapshot_mode: str = "full_year",
    representative_weeks: int = 4,
) -> FacilityConfig:
    return FacilityConfig(
        wind=WindConfig(cost=CostAssumption(capex_per_unit=2200.0, fom_pct=0.03, lifetime_years=25)),
        solar=SolarConfig(cost=CostAssumption(capex_per_unit=1100.0, fom_pct=0.02, lifetime_years=25)),
        battery=BatteryConfig(
            power_cost=CostAssumption(capex_per_unit=500.0, fom_pct=0.025, lifetime_years=15),
            energy_cost=CostAssumption(capex_per_unit=250.0, fom_pct=0.02, lifetime_years=15),
            roundtrip_efficiency=0.88,
        ),
        h2_storage=H2StorageConfig(cost=CostAssumption(capex_per_unit=20000.0, fom_pct=0.02, lifetime_years=25)),
        grid=GridConfig(subregion="CSA", mode=grid_mode, link_capex_per_mw=400_000.0),
        scenario=ScenarioConfig(
            model_year=model_year,
            file_token="STEP_CHANGE",
            resolution="hourly",
            snapshot_mode=snapshot_mode,
            representative_weeks=representative_weeks,
        ),
    )


def main(config: FacilityConfig | None = None):
    config = config or default_config()
    n = build_facility_network(config)
    attach_grid_price(n, config)
    attach_dri_eaf(n, wacc=config.pypsa_wacc)
    status, _ = n.optimize(solver_name=config.solver, solver_options=config.solver_options)
    if status not in ("ok", "optimal"):
        raise RuntimeError(f"Solve failed: {status}")
    metrics = extract_lcoh_lcos(n, config)
    return n, metrics


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Solve Whyalla H2-DRI-EAF and print metrics.")
    parser.add_argument(
        "--grid-mode", default="sa_dispatch", choices=("rldc_merit", "sa_dispatch"),
        help="Grid pricing mode: sa_dispatch (default, co-solve 3-sub SA network) "
             "or rldc_merit (faster price-taker proxy for sweeps).",
    )
    parser.add_argument("--model-year", type=int, default=2030)
    parser.add_argument(
        "--snapshots", default="full_year", choices=("full_year", "representative_weeks"),
        help="Snapshot resolution (representative_weeks speeds up sa_dispatch by ~30x).",
    )
    parser.add_argument("--rep-weeks", type=int, default=4)
    args = parser.parse_args()

    cfg = default_config(
        grid_mode=args.grid_mode,
        model_year=args.model_year,
        snapshot_mode=args.snapshots,
        representative_weeks=args.rep_weeks,
    )
    n, metrics = main(cfg)
    _keys = (
        "lcoh_per_kg", "lcos_per_t_steel", "lcos_objective_basis",
        "ely_mw", "ely_cf", "h2_store_mwh",
        "annual_steel_t", "annual_h2_kg",
        "avg_fac_price", "ely_realised_price", "flexibility_premium",
    )
    for k in _keys:
        v = metrics.get(k)
        if isinstance(v, float):
            print(f"  {k:28s}: {v:,.3f}")
        else:
            print(f"  {k:28s}: {v}")
