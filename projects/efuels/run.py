"""Top-level runner: build facility network, attach e-fuels chain, solve, extract results."""
from __future__ import annotations

from whyalla_pypsa import (
    FacilityConfig, WindConfig, SolarConfig, BatteryConfig, H2StorageConfig,
    GridConfig, ScenarioConfig, CostAssumption,
    build_facility_network, attach_grid_price,
)

from process_chain import attach_efuels
from efuels_results import extract_lcom_lcof


def default_config() -> FacilityConfig:
    return FacilityConfig(
        wind=WindConfig(cost=CostAssumption(capex_per_unit=2200.0, fom_pct=0.03, lifetime_years=25)),
        solar=SolarConfig(cost=CostAssumption(capex_per_unit=1100.0, fom_pct=0.02, lifetime_years=25)),
        battery=BatteryConfig(
            power_cost=CostAssumption(capex_per_unit=500.0, fom_pct=0.025, lifetime_years=15),
            energy_cost=CostAssumption(capex_per_unit=250.0, fom_pct=0.02, lifetime_years=15),
            roundtrip_efficiency=0.88,
        ),
        h2_storage=H2StorageConfig(cost=CostAssumption(capex_per_unit=20000.0, fom_pct=0.02, lifetime_years=25)),
        grid=GridConfig(subregion="CSA", mode="rldc_merit", link_capex_per_mw=400_000.0),
        scenario=ScenarioConfig(model_year=2030, file_token="STEP_CHANGE", resolution="hourly"),
    )


def main(config: FacilityConfig | None = None):
    config = config or default_config()
    n = build_facility_network(config)
    attach_grid_price(n, config)
    attach_efuels(n, wacc=config.pypsa_wacc, product_split_mode="asf")
    status, _ = n.optimize(solver_name=config.solver, solver_options=config.solver_options)
    if status not in ("ok", "optimal"):
        raise RuntimeError(f"Solve failed: {status}")
    metrics = extract_lcom_lcof(n, config)
    return n, metrics


if __name__ == "__main__":
    n, m = main()
    print(m)
