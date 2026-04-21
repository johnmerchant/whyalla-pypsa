"""Analytical cross-check: compare hand-computed LCOF to PyPSA result.

Computes a simplified LCOF bottom-up from:
  - electricity cost (assumed flat price × electrolyser hours × consumption)
  - CO2 cost (cheapest available tranche × stoichiometry)
  - annualised CAPEX (electrolyser + synthesis + refinery) via CRF

Asserts within 20% of the PyPSA-optimised result from run.main().
"""
from __future__ import annotations

import math

from whyalla_pypsa import crf

from efuels_physics import (
    ELECTROLYSER_EFFICIENCY,
    ELECTROLYSER_LIFE_YR,
    MEOH_LHV_MWH_PER_T,
    MEOH_SYNTHESIS_LHV_EFFICIENCY,
    T_CO2_PER_T_MEOH,
    T_H2_PER_T_MEOH,
    H2_LHV_MWH_PER_T,
    DIESEL_LHV_MWH_PER_T,
    asf_mass_fractions,
)
from co2_supply import build_co2_supply_curve

# Tolerance for pass/fail
TOLERANCE = 0.20


def analytical_lcof(
    *,
    elec_price_aud_mwh: float = 50.0,
    ely_capex_per_kw: float = 1500.0,
    synthesis_capex_per_t_meoh_yr: float = 800.0,
    refinery_capex_per_t_yr: float = 400.0,
    wacc: float = 0.07,
    alpha: float = 0.90,
    model_year: int = 2030,
) -> float:
    """Return AUD/t diesel-equivalent via simple bottom-up LCOF formula."""
    # --- stoichiometry ---
    h2_input_per_t_meoh = (T_H2_PER_T_MEOH * H2_LHV_MWH_PER_T) / MEOH_SYNTHESIS_LHV_EFFICIENCY
    elec_per_t_meoh = h2_input_per_t_meoh / ELECTROLYSER_EFFICIENCY  # MWh_e / t_MeOH

    # --- cheapest CO2 tranche ---
    tranches = build_co2_supply_curve(model_year)
    co2_price = min(t["marginal_cost"] for t in tranches) if tranches else 150.0

    # --- variable cost per t MeOH ---
    vc_per_t_meoh = elec_per_t_meoh * elec_price_aud_mwh + T_CO2_PER_T_MEOH * co2_price

    # --- annualised CAPEX per t MeOH/yr ---
    ely_crf = crf(wacc, ELECTROLYSER_LIFE_YR)
    ely_capex_per_t_meoh_yr = (
        ely_capex_per_kw * 1_000            # AUD/MW
        * elec_per_t_meoh                   # MWh_e/t → relative to 1 MW running 1 yr
        / 8760                              # t MeOH per MW per year = 8760 / elec_per_t_meoh
    ) * ely_crf
    # Simpler: capex_per_t_meoh_yr = AUD/kW × 1000 × elec/t / 8760 × CRF
    ely_annuity_per_t = ely_capex_per_kw * 1_000 * crf(wacc, ELECTROLYSER_LIFE_YR) * elec_per_t_meoh / 8760
    synth_annuity_per_t = synthesis_capex_per_t_meoh_yr * crf(wacc, 25)

    lcom = vc_per_t_meoh + ely_annuity_per_t + synth_annuity_per_t

    # --- LCOF: meoh → products via ASF ---
    fracs = asf_mass_fractions(alpha)
    meoh_to_liquid = 0.455  # t liquid HC / t MeOH
    # Average refinery annuity weighted by product fracs (uniform capex per t product/yr here)
    refinery_annuity_per_t_meoh = (
        refinery_capex_per_t_yr * crf(wacc, 25) * meoh_to_liquid
    )

    lcom_full = lcom + refinery_annuity_per_t_meoh  # AUD/t MeOH including refinery

    # Convert to AUD/t diesel-equivalent (energy basis)
    # 1 t MeOH → meoh_to_liquid × frac_diesel t diesel + other products
    # Energy weighted: sum(frac_i × LHV_i) per t product out; normalise by diesel LHV
    from efuels_physics import (
        NAPHTHA_LHV_MWH_PER_T, KERO_LHV_MWH_PER_T, WAX_LHV_MWH_PER_T,
    )
    lhv_map = {
        "naphtha": NAPHTHA_LHV_MWH_PER_T,
        "kero": KERO_LHV_MWH_PER_T,
        "diesel": DIESEL_LHV_MWH_PER_T,
        "wax": WAX_LHV_MWH_PER_T,
    }
    avg_lhv = sum(fracs[p] * lhv_map[p] for p in fracs)
    # AUD/t MeOH → AUD/MWh product → AUD/t diesel equiv
    lcof = (lcom_full / MEOH_LHV_MWH_PER_T) * DIESEL_LHV_MWH_PER_T
    return lcof


def run_validation() -> None:
    """Run PyPSA optimisation and compare to analytical LCOF. Assert within TOLERANCE."""
    try:
        from run import main, default_config
    except ImportError as e:
        raise SystemExit(f"Cannot import run.py: {e}")

    print("Running analytical LCOF...")
    a_lcof = analytical_lcof()
    print(f"  Analytical LCOF: AUD {a_lcof:,.0f}/t diesel-equiv")

    print("Running PyPSA optimisation (this may take a few minutes)...")
    try:
        _, metrics = main()
    except Exception as e:
        raise SystemExit(f"PyPSA solve failed: {e}")

    p_lcof = metrics.get("lcof_per_t_diesel_equivalent", float("nan"))
    print(f"  PyPSA LCOF:      AUD {p_lcof:,.0f}/t diesel-equiv")

    if math.isnan(p_lcof):
        raise AssertionError("PyPSA LCOF is NaN — no products dispatched")

    ratio = abs(p_lcof - a_lcof) / max(abs(a_lcof), 1e-9)
    print(f"  Relative difference: {ratio:.1%}  (tolerance: {TOLERANCE:.0%})")
    assert ratio <= TOLERANCE, (
        f"LCOF mismatch too large: analytical={a_lcof:.0f}, pypsa={p_lcof:.0f}, "
        f"ratio={ratio:.1%} > {TOLERANCE:.0%}"
    )
    print("PASS")


if __name__ == "__main__":
    run_validation()
