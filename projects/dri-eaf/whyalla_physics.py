"""Shared physical constants and formulae for the Whyalla H₂-DRI-EAF model.

Ported from dual_fuel_network.py so that whyalla_components.py and
whyalla_results.py can import them without pulling in the full legacy
network-builder.
"""

# ── Reductant energy intensity ─────────────────────────────────────────────
# 10.5 GJ/t DRI gas-equivalent (Midrex gas-DRI data [^20]).
# NOTE: this treats gas and H₂ as energy-equivalent at 10.5 GJ/t on the
# reductant bus, which overestimates H₂ consumption by ~40-50% vs pure-H₂
# DRI (~6.6-7.5 GJ H₂/t).  Conservative (pessimistic) on H₂ economics.
GJ_PER_T_DRI = 10.5
MWH_PER_T_DRI = GJ_PER_T_DRI / 3.6  # ≈ 2.917 MWh/t

# ── Gas emissions factor ────────────────────────────────────────────────────
# 0.0561 t CO₂/GJ LHV (IPCC 2006) × 3.6 GJ/MWh = 0.202 t CO₂/MWh [^23]
GAS_CO2_T_PER_MWH = 3.6 * 0.0561  # ≈ 0.2020

# ── EAF electricity intensity ──────────────────────────────────────────────
# 0.60 MWh/t steel — high-grade Middleback magnetite [^20]
EAF_MWH_PER_T_STEEL = 0.60

# ── DRI → steel yield ──────────────────────────────────────────────────────
# 1.05 t DRI → 1 t steel (Midrex/HYBRIT typical yield) [^20]
DRI_T_PER_T_STEEL = 1.05

# ── Default annual production ──────────────────────────────────────────────
# Santos gas cap: 20 PJ/yr at 10.5 GJ/t → 1,904,762 t DRI/yr [^27]
DEFAULT_DRI_TONNES_PER_YEAR = 1_904_762
# Derived steel: DRI / 1.05
DEFAULT_STEEL_TONNES_PER_YEAR = 1_814_059

# ── Electrolyser ───────────────────────────────────────────────────────────
# PEM LHV efficiency 70% (upper-end current commercial; IEA GHR 2024) [^24]
ELECTROLYSER_EFFICIENCY = 0.70
ELECTROLYSER_LIFE_YR = 20

# ── H₂ storage ─────────────────────────────────────────────────────────────
H2_STORAGE_LIFE_YR = 25


def crf(discount_rate: float, lifetime_yr: int) -> float:
    """Capital Recovery Factor.

    CRF = r(1+r)^n / ((1+r)^n - 1)
    """
    r, n = discount_rate, lifetime_yr
    return (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def annual_capex_per_mw(capex_per_kw: float, discount_rate: float,
                        lifetime_yr: int = ELECTROLYSER_LIFE_YR) -> float:
    """Annualised electrolyser CAPEX in $/MW/yr."""
    return capex_per_kw * 1_000 * crf(discount_rate, lifetime_yr)


def annual_reductant_mwh(dri_tonnes_per_year: float = DEFAULT_DRI_TONNES_PER_YEAR) -> float:
    """Total annual reductant demand in MWh (gas-equivalent)."""
    return dri_tonnes_per_year * MWH_PER_T_DRI


def reductant_mw(dri_tonnes_per_year: float = DEFAULT_DRI_TONNES_PER_YEAR) -> float:
    """Average reductant power demand in MW."""
    return annual_reductant_mwh(dri_tonnes_per_year) / 8760
