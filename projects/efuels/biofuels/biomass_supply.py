"""Biomass supply curves for the Whyalla e-fuels / biofuels model.

Mirrors ``co2_supply.py`` in structure: builds tiered supply tranches
so the LP sees a real marginal-cost curve for each biomass stream.

Four streams, one supply curve each:

    • Lignocellulose  — mallee + saltbush feeding ``biomass_lignocellulose_bus``
                         (used by pyrolysis + gasification pathways).
    • Halophyte oil   — Salicornia feeding ``halophyte_oil_bus`` (HEFA).
    • Algae steelworks — open-pond algae at the steelworks site feeding
                         ``algae_feed_steelworks_bus`` (HTL-steelworks).
    • Algae Port Bonython — same, coastal-flat site near Port Bonython
                         feeding ``algae_feed_port_bonython_bus``.

Each tranche dict is compatible with ``n.add("Generator", name, **td)``.
Pathway modules iterate over ``build_*_curve()`` and add one Generator
per tranche, so the LP picks the cheapest first and climbs the curve
only when demand warrants.

Marginal-cost conventions (AUD/t *delivered to the bus*):
    • Lignocellulose (mallee/saltbush): harvest + chipping + haul +
      annuitised plantation capex + land opportunity cost.
    • Halophyte oil: seed + cultivation + crushing + transport +
      annuitised establishment + land.
    • Algae: nutrients + CO₂ supplementation + pumping + harvesting +
      flocculation + labour (NOT pond capex — that's in the HTL Link).

Values are 2030-era central estimates with bands in the docstrings.
"""
from __future__ import annotations

from dataclasses import dataclass


HOURS_PER_YEAR = 8760


@dataclass
class BiomassTranche:
    name: str
    bus: str
    carrier: str
    area_ha: float
    yield_t_per_ha_yr: float
    marginal_cost: float            # AUD / t delivered (includes annuitised plantation capex)

    @property
    def p_nom_t_per_hr(self) -> float:
        return (self.area_ha * self.yield_t_per_ha_yr) / HOURS_PER_YEAR

    @property
    def annual_t(self) -> float:
        return self.area_ha * self.yield_t_per_ha_yr


# ═══════════════════════════════════════════════════════════════════════
# LIGNOCELLULOSE (mallee + saltbush) → biomass_lignocellulose_bus
# ═══════════════════════════════════════════════════════════════════════
# Eyre Peninsula + Mid-North SA land base. Tiered by yield × accessibility.
#
# Cost components per t_dry delivered (gate price, central 2030):
#   Harvest + chip + haul (<100 km):          AUD  40–80
#   Plantation establishment (A$3,000/ha,
#     annuitised 20y @ 7%, amortised over
#     3-yr coppice cycle yield):              AUD   5–15
#   Land opportunity cost (A$50-200/ha/yr):   AUD   7–40
#   Total (arable best case → marginal):      AUD  60–180
#
# Mallee references: WA Oil Mallee Project (Bartle & Abadi 2010); CSIRO
# MAI/CNRS 2009-2017; AFIRM 2014; 2021 RIRDC oil-mallee update.
# Saltbush references: A. nummularia CSIRO grazing trials; O'Connell 2008
# saline-agriculture studies; Atriplex biomass potential 2015.
_LIGNOCELLULOSE_TRANCHES: list[BiomassTranche] = [
    BiomassTranche(
        name="mallee_tier1",
        bus="biomass_lignocellulose_bus",
        carrier="biomass_lignocellulose",
        area_ha=15_000,         # high-rainfall Eyre Peninsula arable
        yield_t_per_ha_yr=8.0,  # central mallee yield on arable
        marginal_cost=60.0,
    ),
    BiomassTranche(
        name="mallee_tier2",
        bus="biomass_lignocellulose_bus",
        carrier="biomass_lignocellulose",
        area_ha=40_000,         # mid-yield dryland
        yield_t_per_ha_yr=6.0,
        marginal_cost=110.0,
    ),
    BiomassTranche(
        name="mallee_tier3",
        bus="biomass_lignocellulose_bus",
        carrier="biomass_lignocellulose",
        area_ha=150_000,        # marginal / pastoral edge
        yield_t_per_ha_yr=4.0,
        marginal_cost=180.0,
    ),
    BiomassTranche(
        name="saltbush_tier1",
        bus="biomass_lignocellulose_bus",
        carrier="biomass_lignocellulose",
        area_ha=15_000,         # coastal saline, managed cut+carry
        yield_t_per_ha_yr=5.0,
        marginal_cost=90.0,
    ),
    BiomassTranche(
        name="saltbush_tier2",
        bus="biomass_lignocellulose_bus",
        carrier="biomass_lignocellulose",
        area_ha=50_000,         # degraded pastoral, lower yield
        yield_t_per_ha_yr=3.0,
        marginal_cost=140.0,
    ),
]


# ═══════════════════════════════════════════════════════════════════════
# HALOPHYTE OIL (Salicornia) → halophyte_oil_bus
# ═══════════════════════════════════════════════════════════════════════
# Cost components per t_oil delivered (gate price, central 2030):
#   Seed + establishment + cultivation:       AUD  300–600
#   Harvest + seed separation + crushing:     AUD  400–800
#   Oil refining (degumming, bleaching):      AUD  200–300
#   Land + irrigation infra (brine free):     AUD  100–400
#   Total:                                    AUD  1,000–2,100
#
# References: Etihad/Masdar SBRC SEAS demonstration (UAE, 2016-2022);
# Salicornia bigelovii agronomic trials; research-grade commercial cost
# estimates are wide-banded.
_HALOPHYTE_TRANCHES: list[BiomassTranche] = [
    BiomassTranche(
        name="halophyte_tier1",
        bus="halophyte_oil_bus",
        carrier="halophyte_oil",
        area_ha=5_000,          # adjacent to Northern Water outfall
        yield_t_per_ha_yr=1.2,  # SBRC high-end commercial target
        marginal_cost=1_200.0,
    ),
    BiomassTranche(
        name="halophyte_tier2",
        bus="halophyte_oil_bus",
        carrier="halophyte_oil",
        area_ha=25_000,         # inland saline flats, less convenient
        yield_t_per_ha_yr=0.8,  # commercial de-rate for lower-grade land
        marginal_cost=1_800.0,
    ),
]


# ═══════════════════════════════════════════════════════════════════════
# ALGAE (open-pond) — site-specific curves
# ═══════════════════════════════════════════════════════════════════════
# Cost components per t_dry algae delivered to HTL inlet:
#   Nutrients (N, P, trace):                  AUD  250–400
#   CO₂ supplementation + aeration:           AUD  100–300
#   Pumping + paddle wheels + mixing (aux
#     elec bundled here, not in Link):        AUD  150–300
#   Harvest + flocculation + dewatering:      AUD  300–500
#   Labour + overhead:                        AUD  150–300
#   Total:                                    AUD  1,000–1,800
#
# Steelworks vs Port Bonython differ mostly in land constraint, not
# operating cost. CO₂ supplementation is cheaper at steelworks (adjacent
# flue source), slightly more at Port Bonython (trucked/piped CO₂),
# reflected in a modest site delta.
#
# References: NREL ATP3 outdoor pond TEA (2017); Muradel Whyalla pilot
# 2014-19 (A$9.90/L pilot vs A$1/L never-achieved commercial target);
# PNNL 2014 HTL biocrude TEA.
_ALGAE_STEELWORKS_TRANCHES: list[BiomassTranche] = [
    BiomassTranche(
        name="algae_steelworks_tier1",
        bus="algae_feed_steelworks_bus",
        carrier="algae_feed",
        area_ha=250,                # industrial-adjacent land
        yield_t_per_ha_yr=73.0,     # 20 g/m²/day open pond
        marginal_cost=1_400.0,      # cheaper CO₂ supply (adjacent flue)
    ),
]

_ALGAE_PORT_BONYTHON_TRANCHES: list[BiomassTranche] = [
    BiomassTranche(
        name="algae_port_bonython_tier1",
        bus="algae_feed_port_bonython_bus",
        carrier="algae_feed",
        area_ha=500,                # coastal flat, larger pond farm
        yield_t_per_ha_yr=73.0,
        marginal_cost=1_600.0,      # CO₂ must be trucked/piped
    ),
    BiomassTranche(
        name="algae_port_bonython_tier2",
        bus="algae_feed_port_bonython_bus",
        carrier="algae_feed",
        area_ha=1_000,              # further afield, lower-quality land
        yield_t_per_ha_yr=65.0,     # slight productivity de-rate (siting)
        marginal_cost=2_000.0,
    ),
]


# ── Curve builders (LP-friendly dict emitters) ───────────────────────────

def _tranche_to_dict(t: BiomassTranche) -> dict:
    """Produce the kwargs needed for ``n.add('Generator', name, **d)``."""
    return {
        "_tranche_name": t.name,
        "bus": t.bus,
        "carrier": t.carrier,
        "p_nom": t.p_nom_t_per_hr,   # t/hr
        "marginal_cost": t.marginal_cost,
    }


def build_lignocellulose_curve() -> list[dict]:
    return [_tranche_to_dict(t) for t in _LIGNOCELLULOSE_TRANCHES]


def build_halophyte_curve() -> list[dict]:
    return [_tranche_to_dict(t) for t in _HALOPHYTE_TRANCHES]


def build_algae_curve(site: str) -> list[dict]:
    if site == "steelworks":
        return [_tranche_to_dict(t) for t in _ALGAE_STEELWORKS_TRANCHES]
    if site == "port_bonython":
        return [_tranche_to_dict(t) for t in _ALGAE_PORT_BONYTHON_TRANCHES]
    raise ValueError(f"Unknown algae site {site!r}")


# ── Tranche-name prefixes used by results extractors to aggregate dispatch.
LIGNOCELLULOSE_TRANCHE_PREFIXES = ("mallee_", "saltbush_")
HALOPHYTE_TRANCHE_PREFIXES = ("halophyte_",)
ALGAE_STEELWORKS_TRANCHE_PREFIXES = ("algae_steelworks_",)
ALGAE_PORT_BONYTHON_TRANCHE_PREFIXES = ("algae_port_bonython_",)
