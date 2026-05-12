"""Pathway C: lignocellulose (mallee + saltbush) → pyrolysis OR gasification.

Two conversion branches share a common feedstock bus (biomass_lignocellulose_bus):

    mallee_supply, saltbush_supply  ──► biomass_lignocellulose_bus
                                              │
            ┌─────────────────────────────────┴─────────────────────────┐
            ▼                                                            ▼
    pyrolysis_upgrading                                          biomass_gasification
    ──► diesel_bus                                               ──► facility_h2  (biogenic)
    ──► kero_bus                                                 ──► co2           (biogenic)
    ──► naphtha_bus
    ◄── facility_h2 (hydrotreating)

The gasification branch deliberately re-uses the existing facility_h2
and co2 buses — that's the "shared downstream infrastructure" overlap
the user asked for. Biogenic H₂ displaces electrolyser output; biogenic
CO₂ displaces captured-CO₂ tranches (see co2_supply.py merit order).

Both branches are independently extendable; the optimiser picks either
or both per year based on the cost surface.
"""
from __future__ import annotations

import pypsa

from whyalla_pypsa import crf

from .biomass_supply import build_lignocellulose_curve
from process_chain import SHARED_HCR_CAPEX_PER_T_YR
from .physics import (
    PYROLYSIS_FUEL_T_PER_T_DRY,
    PYROLYSIS_PRODUCT_FRACS,
    PYROLYSIS_H2_T_PER_T_DRY,
    PYROLYSIS_CAPEX_PER_T_DRY_YR,
    PYROLYSIS_OPEX_PER_T_DRY,
    PYROLYSIS_LIFETIME_YEARS,
    GASIFICATION_H2_T_PER_T_DRY,
    GASIFICATION_CO2_T_PER_T_DRY,
    GASIFICATION_AUX_ELEC_MWH_PER_T_DRY,
    GASIFICATION_CAPEX_PER_T_DRY_YR,
    GASIFICATION_OPEX_PER_T_DRY,
    GASIFICATION_LIFETIME_YEARS,
)
from .waste_streams import HOURS_PER_YEAR
from efuels_physics import H2_LHV_MWH_PER_T


def attach_biomass_feedstocks(
    n: pypsa.Network,
    *,
    hours_per_year: float = HOURS_PER_YEAR,
) -> None:
    """Create biomass_lignocellulose_bus + tranche-based supply curve.

    The LP sees ascending-marginal-cost tranches (mallee + saltbush tiers)
    rather than a flat, fixed-p_nom Generator, so pyrolysis/gasification
    scale-out responds to demand until biomass gets priced out.
    """
    if "biomass_lignocellulose" not in n.carriers.index:
        n.add("Carrier", "biomass_lignocellulose")
    if "biomass_lignocellulose_bus" not in n.buses.index:
        n.add("Bus", "biomass_lignocellulose_bus", carrier="biomass_lignocellulose")

    for td in build_lignocellulose_curve():
        td = dict(td)
        name = td.pop("_tranche_name")
        if name not in n.generators.index:
            n.add("Generator", name, **td)


def attach_pyrolysis(
    n: pypsa.Network,
    *,
    wacc: float,
    h2_bus: str = "facility_h2",
    grid_price_for_aux: float = 120.0,   # AUD/MWh — bundled opex
    hours_per_year: float = HOURS_PER_YEAR,
) -> None:
    """Fast pyrolysis + two-stage hydrotreating branch."""
    mass_yield = PYROLYSIS_FUEL_T_PER_T_DRY
    h2_mwh_per_t_dry = PYROLYSIS_H2_T_PER_T_DRY * H2_LHV_MWH_PER_T

    # Small aux electricity (~0.3 MWh/t_dry) bundled into opex.
    bundled_aux = 0.3 * grid_price_for_aux
    marginal_cost = PYROLYSIS_OPEX_PER_T_DRY + bundled_aux
    # Strip the shared-HCR finishing capex out of this Link; the shared
    # hydrocracker charges it once in process_chain. Mass-share × HCR A$/t.
    hcr_share_per_t_dry = SHARED_HCR_CAPEX_PER_T_YR * mass_yield
    conditioning_capex_per_t_dry = max(
        PYROLYSIS_CAPEX_PER_T_DRY_YR - hcr_share_per_t_dry, 0.0
    )
    capital_per_t_per_hr = conditioning_capex_per_t_dry * hours_per_year

    if "pyrolysis_upgrading" not in n.links.index:
        # Conditioning Link delivers to intermediate buses so the shared
        # hydrocracker can peak-share its capex across pathways.
        n.add("Link", "pyrolysis_upgrading",
              bus0="biomass_lignocellulose_bus",
              bus1="diesel_intermediate",
              bus2="kero_intermediate",
              bus3="naphtha_intermediate",
              bus4=h2_bus,
              efficiency =  PYROLYSIS_PRODUCT_FRACS["diesel"]  * mass_yield,
              efficiency2=  PYROLYSIS_PRODUCT_FRACS["kero"]    * mass_yield,
              efficiency3=  PYROLYSIS_PRODUCT_FRACS["naphtha"] * mass_yield,
              efficiency4= -h2_mwh_per_t_dry,
              p_nom_extendable=True,
              capital_cost=capital_per_t_per_hr * crf(wacc, PYROLYSIS_LIFETIME_YEARS),
              marginal_cost=marginal_cost)


def attach_gasification(
    n: pypsa.Network,
    *,
    wacc: float,
    h2_bus: str = "facility_h2",
    co2_bus: str = "co2",
    grid_price_for_aux: float = 120.0,
    hours_per_year: float = HOURS_PER_YEAR,
) -> None:
    """Biomass gasification + water-gas shift → biogenic H₂ and biogenic CO₂.

    Feeds the existing e-fuel MeOH synth and upgrading kit (that's the
    "shared downstream" overlap).
    """
    h2_mwh_per_t_dry_out = GASIFICATION_H2_T_PER_T_DRY * H2_LHV_MWH_PER_T

    bundled_aux = GASIFICATION_AUX_ELEC_MWH_PER_T_DRY * grid_price_for_aux
    marginal_cost = GASIFICATION_OPEX_PER_T_DRY + bundled_aux
    capital_per_t_per_hr = GASIFICATION_CAPEX_PER_T_DRY_YR * hours_per_year

    if "biomass_gasification" not in n.links.index:
        # efficiency = +MWh H₂ / t_dry (delivered to h2_bus)
        # efficiency2 = +t CO₂ / t_dry (delivered to co2 bus — biogenic feedstock)
        n.add("Link", "biomass_gasification",
              bus0="biomass_lignocellulose_bus",
              bus1=h2_bus,
              bus2=co2_bus,
              efficiency =  h2_mwh_per_t_dry_out,
              efficiency2=  GASIFICATION_CO2_T_PER_T_DRY,
              p_nom_extendable=True,
              capital_cost=capital_per_t_per_hr * crf(wacc, GASIFICATION_LIFETIME_YEARS),
              marginal_cost=marginal_cost)
