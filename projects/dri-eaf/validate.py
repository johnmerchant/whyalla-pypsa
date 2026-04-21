"""Spreadsheet cross-check: analytical LCOS vs PyPSA optimisation result.

The analytical model sums annuitised component capex plus H2 production cost
at average grid price and compares to the PyPSA LCOS. Differences up to ~20%
are expected because PyPSA captures flexibility value (electrolyser dispatching
at low-price windows) while the spreadsheet uses average price.
"""
from __future__ import annotations

from whyalla_pypsa import crf

from run import default_config, main as run_main

# Tolerance: 20% relative
TOLERANCE = 0.20


def _analytical_lcos(config, wind_cf_avg: float = 0.38, solar_cf_avg: float = 0.22,
                     avg_grid_price: float = 80.0) -> float:
    """Compute a simple analytical LCOS using levelised component costs.

    Assumptions:
    - Wind CF = wind_cf_avg, Solar CF = solar_cf_avg (average capacity factors)
    - Grid electricity price = avg_grid_price AUD/MWh (flat)
    - Electrolyser efficiency = 0.70 LHV
    - H2 intensity = 0.057 t H2/t DRI * 33.33 MWh/t H2 ~= 1.9 MWh_H2/t DRI
    - EAF electricity = 0.60 MWh/t steel
    - Annual steel = 1.6 Mt
    """
    annual_steel_t = 1.6e6
    annual_steel_mwh_eaf = annual_steel_t * 0.60  # EAF electricity
    annual_dri_t = annual_steel_t
    h2_intensity_mwh = 0.057 * 33.33  # ~1.9 MWh_H2 / t DRI
    annual_h2_mwh = annual_dri_t * h2_intensity_mwh
    ely_efficiency = 0.70
    annual_ely_mwh = annual_h2_mwh / ely_efficiency

    # Electrolyser capex
    ely_capex_per_kw = 1500.0
    ely_mw_required = annual_ely_mwh / 8760.0  # at 100% CF assumption
    ely_capex_total = ely_capex_per_kw * 1000 * ely_mw_required
    ely_annuity = ely_capex_total * crf(config.wacc_overlay.electrolyser.wacc,
                                        config.wacc_overlay.electrolyser.lifetime_years)

    # H2 storage capex (neglect for simple model — 0 hours = no buffer)
    h2_store_annuity = 0.0

    # Wind capex (size to cover ely + EAF electricity)
    total_annual_mwh = annual_ely_mwh + annual_steel_mwh_eaf
    wind_mw_required = total_annual_mwh / (8760 * wind_cf_avg)
    wind_capex_per_mw = config.wind.cost.capex_per_unit * 1000
    wind_capex_total = wind_mw_required * wind_capex_per_mw
    wind_annuity = wind_capex_total * crf(config.wacc_overlay.wind.wacc,
                                          config.wacc_overlay.wind.lifetime_years)

    # DRI + EAF fixed capex
    dri_capex_annuity = 250.0 * annual_dri_t * crf(0.07, 25)
    eaf_capex_annuity = 300.0 * annual_steel_t * crf(0.07, 30)

    # EAF electricity opex at avg price
    eaf_elec_cost = annual_steel_mwh_eaf * avg_grid_price

    total_annual_cost = (
        ely_annuity + h2_store_annuity + wind_annuity
        + dri_capex_annuity + eaf_capex_annuity + eaf_elec_cost
    )
    return total_annual_cost / annual_steel_t


def main():
    config = default_config()
    print("Running PyPSA optimisation (this may take a few minutes)...")
    n, metrics = run_main(config)

    pypsa_lcos = metrics["lcos_per_t_steel"]
    analytical_lcos = _analytical_lcos(config)

    rel_err = abs(pypsa_lcos - analytical_lcos) / max(abs(analytical_lcos), 1e-9)

    print(f"\nAnalytical LCOS : AUD {analytical_lcos:,.2f} / t steel")
    print(f"PyPSA LCOS      : AUD {pypsa_lcos:,.2f} / t steel")
    print(f"Relative error  : {rel_err:.1%}")
    print()

    assert rel_err <= TOLERANCE, (
        f"LCOS relative error {rel_err:.1%} exceeds tolerance {TOLERANCE:.0%}.\n"
        "Check input assumptions in _analytical_lcos() or run.default_config()."
    )
    print(f"PASS: relative error within {TOLERANCE:.0%} tolerance.")
    return pypsa_lcos, analytical_lcos, rel_err


if __name__ == "__main__":
    main()
