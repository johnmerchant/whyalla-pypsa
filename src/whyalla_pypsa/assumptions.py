"""Shared techno-economic assumptions for Whyalla PyPSA projects.

Numerical constants and learning-curve helpers consumed by both
`projects/dri-eaf` and `projects/efuels`. Citation chain lives in the
top-level `RESEARCH.md`; this module is the single source of truth for
the numbers themselves.
"""
from __future__ import annotations

# ── Component lifetimes (years) ─────────────────────────────────────────────
ELECTROLYSER_LIFE_YEARS = 20
H2_STORE_LIFE_YEARS = 25

# ── WACC framework (real, pre-tax) ──────────────────────────────────────────
# CEFC's FOAK hydrogen/e-fuel band is 11–13%; we anchor FOAK at the upper
# bound. NOAK 9% applies once a technology category has 100+ MW of operating
# reference. Renewables PPA financing clears at 7% nominal in current AU
# market (BRC-A 2025 signings).
FOAK_WACC = 0.13
NOAK_WACC = 0.09
RENEWABLES_PPA_WACC = 0.07

# ── H2 storage (AUD/MWh installed) ──────────────────────────────────────────
# Compressed-vessel literature midpoint (ARENA, IEA, HJP-derived ~AUD 800-
# 1500/kg). Held flat real — mature tank line, not a learning curve.
# Whyalla has no salt or LRC option (Gawler Craton; nearest geology is
# Polda Basin ~250-300 km south), so cavern pricing is not a modelled path.
H2_STORE_CAPEX_AUD_PER_MWH = 20_000.0

# ── Electrolyser installed CAPEX (AUD/kW, 100+ MW project) ──────────────────
# Two paths bracket the policy / cost-decline uncertainty:
#   "central"      — IEA-NZE-adjacent learning curve, alkaline/PEM convergence
#   "conservative" — FOAK-stranded; first plants don't trigger the next cohort
# Anchor years span both project grids (efuels: 2027–2040 with 2032/2035/2038
# anchors; dri-eaf: 2028/2030/2033/2037/2040). Off-grid years interpolate.

ELECTROLYSER_CAPEX_CENTRAL_AUD_PER_KW: dict[int, float] = {
    2027: 1980.0,
    2028: 1800.0,
    2029: 1620.0,
    2030: 1440.0,
    2032: 1210.0,
    2033: 1100.0,
    2035: 975.0,
    2037: 850.0,
    2038: 800.0,
    2040: 700.0,
}

ELECTROLYSER_CAPEX_CONSERVATIVE_AUD_PER_KW: dict[int, float] = {
    2027: 2300.0,
    2028: 2100.0,
    2029: 1950.0,
    2030: 1800.0,
    2032: 1650.0,
    2033: 1570.0,
    2035: 1400.0,
    2037: 1300.0,
    2038: 1250.0,
    2040: 1200.0,
}


def electrolyser_capex_aud_per_kw(year: int, path: str = "central") -> float:
    """Installed electrolyser CAPEX for a given year on the named learning path.

    Linear interpolation between anchor years; clamped at endpoints.
    """
    table = {
        "central": ELECTROLYSER_CAPEX_CENTRAL_AUD_PER_KW,
        "conservative": ELECTROLYSER_CAPEX_CONSERVATIVE_AUD_PER_KW,
    }[path]
    if year in table:
        return table[year]
    yrs = sorted(table.keys())
    if year <= yrs[0]:
        return table[yrs[0]]
    if year >= yrs[-1]:
        return table[yrs[-1]]
    for lo, hi in zip(yrs[:-1], yrs[1:]):
        if lo <= year <= hi:
            frac = (year - lo) / (hi - lo)
            return table[lo] + frac * (table[hi] - table[lo])
    raise AssertionError("unreachable")
