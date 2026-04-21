"""Fossil fuel reference prices & unit conversions for lay-audience charts.

All prices are nominal ~2025 AU. Sources in comments. Used by chart_trajectory,
chart_co2_supply_curve, etc. to put e-fuel cost numbers on the same axis as
what a citizen pays at the pump or an airline pays on a fuel bill.
"""
from __future__ import annotations

# ── Densities (kg/L → L/t via 1000/density) ──────────────────────────────
# Standard AS/NZS fuel-density values; used to convert AUD/t → AUD/L.
_L_PER_T = {
    "diesel":   1_190,   # 0.840 kg/L
    "ulp":      1_333,   # 0.750 kg/L  (petrol, ~RON 95)
    "jet":      1_250,   # 0.800 kg/L  (Jet A-1)
    "meoh":     1_263,   # 0.792 kg/L  (methanol)
}


def aud_per_litre(aud_per_tonne: float, fuel: str = "diesel") -> float:
    """Convert AUD/t → AUD/L for the given fuel (default diesel)."""
    return aud_per_tonne / _L_PER_T[fuel]


def litres_per_tonne(fuel: str = "diesel") -> float:
    return _L_PER_T[fuel]


# ── Reference prices (AUD/L, pump or wholesale) ───────────────────────────
# Retail pump prices: April 2026 AU national average under the Q2 2026 Strait
# of Hormuz fuel crisis (Brent ~USD 95/bbl spot; AU retail peaked >AUD 3/L
# mid-April, easing toward AUD 2.70s by late April). Sources: IBTimes Australia
# "Fuel Crisis Deepens April 2026"; NRMA open-road Apr-2026 price updates.
# Wholesale: Platts TGP Sydney diesel April 2026 ~AUD 2.35/L, ~AUD 2,800/t.
# Pre-crisis (2025) references kept as *_PRE_CRISIS for year-by-year context.
FOSSIL_PRICES_AUD_PER_L = {
    "Diesel retail (pump, Apr 2026)":    2.76,
    "ULP 95 retail (pump, Apr 2026)":    2.45,
    "Diesel wholesale (Apr 2026)":       2.35,
    "Jet A-1 wholesale (Apr 2026)":      1.95,
}
# Pre-crisis 2025 AU averages (ACCC Quarterly Petrol Monitoring, AIP TGP):
FOSSIL_PRICES_PRE_CRISIS = {
    "Diesel retail (pump, 2025)":     2.10,
    "ULP 95 retail (pump, 2025)":     1.95,
    "Diesel wholesale (2025)":        1.30,
    "Jet A-1 wholesale (2025)":       1.20,
}

# Same, keyed by fuel for programmatic access (CURRENT crisis-era values):
DIESEL_RETAIL_AUD_PER_L    = 2.76
ULP_RETAIL_AUD_PER_L       = 2.45
DIESEL_WHOLESALE_AUD_PER_L = 2.35
JET_WHOLESALE_AUD_PER_L    = 1.95

# Pre-crisis (2025) baselines — shown alongside crisis values on charts so
# lay readers can see both "what we pay today" and "what we paid before Hormuz".
DIESEL_RETAIL_AUD_PER_L_2025    = 2.10
ULP_RETAIL_AUD_PER_L_2025       = 1.95
DIESEL_WHOLESALE_AUD_PER_L_2025 = 1.30
JET_WHOLESALE_AUD_PER_L_2025    = 1.20

# Existing import-parity in AUD/t (kept for back-compat with trajectory code):
IMPORT_PARITY_DIESEL_AUD_PER_T = DIESEL_WHOLESALE_AUD_PER_L * _L_PER_T["diesel"]  # ≈ 2,800

# ── Carbon intensity of fossil diesel (t CO₂e / t fuel, lifecycle WTT+TTW) ─
DIESEL_LIFECYCLE_CO2_T_PER_T = 3.16

# ── Rule-of-thumb scaling aids for lay audience ───────────────────────────
# Avg Australian passenger car: 1.9 t CO₂/yr (BITRE 2023, ~14,000 km × ICE).
PASSENGER_CAR_CO2_T_PER_YR = 1.9
