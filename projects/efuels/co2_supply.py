"""CO₂ supply curve for the Whyalla e-fuels model.

Builds a list of supply tranches (each mapped to a separate PyPSA Generator on
the ``CO2_Whyalla`` bus) reflecting the five-source portfolio described in
RESEARCH.md §4 and the plan workstream B.

Tranche definitions
-------------------
1. Whyalla Steelworks DRI-phase flue CO₂ — cheapest when available, but the
   quantity tapers as the new shaft furnace commissions (2030) and its H₂
   fraction ramps from ~72% at open to ~88% by 2040 (per dri-eaf sibling-
   project LP trajectory). CO₂ availability ∝ (1 − H₂ fraction) × 2 Mt/y
   base NG flue flow. No hard cut-off — fades smoothly.
2. Nyrstar Port Pirie (post-combustion capture) — small, stable, 85 km away.
3. Santos Moomba CCS diversion — large, needs new pipeline, modelled as
   available from 2032 when pipeline lead-time allows.
4. Adbri Birkenhead cement (Adelaide, 370 km by sea) — LEILAC or
   post-combustion; available throughout modelling period.
5. DAC backfill — unbounded, declining price over time.

Each tranche is returned as a ``dict`` compatible with ``pypsa.Network.add()``
for a Generator.  ``attach_efuels()`` in ``efuels_components.py`` iterates
over the list and adds each as a separate Generator so the optimiser can
dispatch them in merit order.
"""
from __future__ import annotations

from dataclasses import dataclass, field


HOURS_PER_YEAR = 8760


@dataclass
class CO2Tranche:
    name: str
    p_nom_annual_t: float  # t CO₂/yr cap (annual tonnage — human-readable)
    marginal_cost: float   # AUD/t CO₂
    available_from: int    # year first available
    available_until: int   # year last available (inclusive); 9999 = unlimited


# ── Tranche library (see RESEARCH.md Table §4) ────────────────────────────

_TRANCHES: list[CO2Tranche] = [
    CO2Tranche(
        name="co2_steelworks",
        # Placeholder — actual value is computed dynamically via
        # _steelworks_co2_t() because availability tracks the shaft furnace
        # H₂ fraction (imported from dri-eaf LP trajectory).
        p_nom_annual_t=2_000_000,
        marginal_cost=80.0,         # AUD/t — captured flue gas, short pipeline
        available_from=2030,        # shaft furnace commissions 2030
        available_until=9999,       # tapers via h2 fraction; never hard-cuts
    ),
    CO2Tranche(
        name="co2_nyrstar",
        p_nom_annual_t=400_000,     # 0.3–0.5 Mt/y Port Pirie post-combustion
        marginal_cost=95.0,         # AUD/t — closest (85 km); cheapest post-steelworks
        available_from=2027,
        available_until=9999,
    ),
    CO2Tranche(
        name="co2_santos_moomba",
        p_nom_annual_t=1_700_000,   # 1.7 Mt/y Santos CCS diversion
        marginal_cost=110.0,        # AUD/t — geological sequestration diversion + long pipeline
        available_from=2032,        # pipeline lead-time
        available_until=9999,
    ),
    CO2Tranche(
        name="co2_adbri_cement",
        p_nom_annual_t=1_000_000,   # ~1 Mt/y Birkenhead LEILAC/post-combustion
        marginal_cost=125.0,        # AUD/t — sea freight 370 km from Adelaide
        available_from=2029,
        available_until=9999,
    ),
    CO2Tranche(
        name="co2_dac",
        p_nom_annual_t=1e12,        # effectively unbounded
        marginal_cost=500.0,        # AUD/t in 2030; declines to 300 by 2040
        available_from=2027,
        available_until=9999,
    ),
]

# DAC cost decline schedule: year → AUD/t CO₂
_DAC_PRICE_SCHEDULE: dict[int, float] = {
    2026: 600.0,
    2027: 560.0,
    2028: 530.0,
    2029: 515.0,
    2030: 500.0,
    2032: 450.0,
    2035: 400.0,
    2038: 350.0,
    2040: 300.0,
}


# ── Whyalla steelworks shaft-furnace H₂-fraction trajectory ───────────────
# Derived from the dri-eaf sibling project's myopic trajectory.csv (mean
# across scenarios; see projects/dri-eaf/generate_trajectory.py). The shaft
# furnace commissions 2030 at ~72% H₂ and ramps toward ~88% by 2040 as
# electrolyser and H₂ storage expand. CO₂ available to the e-fuels plant =
# (1 − h2_frac) × 2 Mt/y base NG flow; pre-2030 blast-furnace CO₂ is too
# dilute to capture, so the tranche is absent before shaft commissioning.
_STEELWORKS_H2_FRAC: dict[int, float] = {
    2030: 0.72,
    2033: 0.75,
    2035: 0.78,
    2037: 0.80,
    2040: 0.88,
}
_STEELWORKS_BASE_CO2_AT_FULL_GAS = 2_000_000   # t/yr


def _interp_schedule(schedule: dict[int, float], year: int) -> float:
    """Piecewise-linear interpolation of a year→value schedule."""
    years_sorted = sorted(schedule)
    if year <= years_sorted[0]:
        return schedule[years_sorted[0]]
    if year >= years_sorted[-1]:
        return schedule[years_sorted[-1]]
    for i, y in enumerate(years_sorted):
        if y > year:
            y0, y1 = years_sorted[i - 1], y
            v0, v1 = schedule[y0], schedule[y1]
            return v0 + (v1 - v0) * (year - y0) / (y1 - y0)
    return schedule[years_sorted[-1]]


def steelworks_co2_t(year: int) -> float:
    """Available steelworks CO₂ in t/yr given the shaft H₂ fraction for *year*."""
    h2_frac = _interp_schedule(_STEELWORKS_H2_FRAC, year)
    return _STEELWORKS_BASE_CO2_AT_FULL_GAS * (1.0 - h2_frac)


def _dac_price(year: int) -> float:
    """Interpolated DAC price for *year* (AUD/t CO₂)."""
    years_sorted = sorted(_DAC_PRICE_SCHEDULE)
    if year <= years_sorted[0]:
        return _DAC_PRICE_SCHEDULE[years_sorted[0]]
    if year >= years_sorted[-1]:
        return _DAC_PRICE_SCHEDULE[years_sorted[-1]]
    for i, y in enumerate(years_sorted):
        if y > year:
            y0, y1 = years_sorted[i - 1], y
            p0, p1 = _DAC_PRICE_SCHEDULE[y0], _DAC_PRICE_SCHEDULE[y1]
            return p0 + (p1 - p0) * (year - y0) / (y1 - y0)
    return _DAC_PRICE_SCHEDULE[years_sorted[-1]]  # unreachable


def build_co2_supply_curve(year: int) -> list[dict]:
    """Return a list of PyPSA Generator parameter dicts for CO₂ supply in *year*.

    Each dict can be unpacked directly into ``n.add("Generator", name, **d)``.
    Tranches not available in *year* are excluded so the topology stays minimal.

    Units for ``p_nom`` are tonnes CO₂ **per hour** — PyPSA treats p_nom as a
    per-snapshot power; with snapshot weightings normalised so that
    Σw_generators = 8760 h/yr (both full-year hourly and representative-weeks
    modes honour this), annual volume = p_nom × 8760 reproduces the tranche's
    annual cap. Tranche definitions above use annual tonnes for readability,
    converted here at the API boundary.
    """
    result = []
    for tranche in _TRANCHES:
        if year < tranche.available_from or year > tranche.available_until:
            continue
        mc = _dac_price(year) if tranche.name == "co2_dac" else tranche.marginal_cost
        # Steelworks fades with the shaft furnace's H₂ fraction.
        if tranche.name == "co2_steelworks":
            annual_t = steelworks_co2_t(year)
            if annual_t <= 0:
                continue
        else:
            annual_t = tranche.p_nom_annual_t
        result.append({
            "bus": "CO2_Whyalla",
            "carrier": "CO2",
            "p_nom": annual_t / HOURS_PER_YEAR,  # t/yr → t/h
            "marginal_cost": mc,
            "_tranche_name": tranche.name,  # metadata — stripped before n.add()
        })
    return result


def blended_co2_price(year: int, weights: dict[str, float] | None = None) -> float:
    """Weighted blended CO₂ price (AUD/t) for a given year.

    *weights* maps tranche name → fractional usage (0–1, sum ≤ 1).
    Default: RESEARCH.md base-case blend (~50% steelworks / 25% Nyrstar / 25% DAC,
    adjusted for availability).
    """
    curve = build_co2_supply_curve(year)
    if not curve:
        return _dac_price(year)

    default_weights = {
        "co2_steelworks": 0.50,
        "co2_nyrstar":    0.25,
        "co2_santos_moomba": 0.00,
        "co2_adbri_cement":  0.00,
        "co2_dac":        0.25,
    }
    w = weights if weights is not None else default_weights

    available_names = {d["_tranche_name"] for d in curve}
    total_w = sum(wv for k, wv in w.items() if k in available_names)

    if total_w == 0:
        # Fall back to equal weighting across available tranches
        total_w = len(curve)
        return sum(d["marginal_cost"] / total_w for d in curve)

    price = sum(
        (w.get(d["_tranche_name"], 0) / total_w) * d["marginal_cost"]
        for d in curve
    )
    return price
