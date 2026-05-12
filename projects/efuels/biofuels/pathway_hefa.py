"""Pathway B: halophyte oilseed (Salicornia) → HEFA drop-in fuels.

Topology:

    halophyte_oil_bus ──► hefa_upgrading ──► kero_bus
    (brine-irrigated     (multi-output      ──► diesel_bus
     Salicornia,         Link)              ──► naphtha_bus
     free feedstock                         ◄── facility_h2 (deoxygenation + crack)
     via brine credit)

HEFA is dominantly jet-producing — the 70% kero fraction makes this the
most SAF-aligned of the three pathways.

Aux electricity is bundled into opex (small contribution, ~0.3 MWh/t oil).
H₂ draw comes from the existing electrolyser bus, creating overlap with
the e-fuel H₂ system (the optimiser trades electrolyser capacity between
MeOH synth and HEFA hydrotreating).
"""
from __future__ import annotations

import pypsa

from whyalla_pypsa import crf

from efuels_physics import H2_LHV_MWH_PER_T

from .biomass_supply import build_halophyte_curve
from process_chain import SHARED_HCR_CAPEX_PER_T_YR
from .physics import (
    HEFA_FUEL_T_PER_T_OIL,
    HEFA_PRODUCT_FRACS,
    HEFA_H2_T_PER_T_OIL,
    HEFA_CAPEX_PER_T_OIL_YR,
    HEFA_OPEX_PER_T_OIL,
    HEFA_LIFETIME_YEARS,
)
from .waste_streams import HOURS_PER_YEAR


def attach_hefa(
    n: pypsa.Network,
    *,
    wacc: float,
    h2_bus: str = "facility_h2",
    hours_per_year: float = HOURS_PER_YEAR,
) -> None:
    """Attach HEFA pathway: tranched halophyte-oil supply + HEFA Link."""
    if "halophyte_oil" not in n.carriers.index:
        n.add("Carrier", "halophyte_oil")
    if "halophyte_oil_bus" not in n.buses.index:
        n.add("Bus", "halophyte_oil_bus", carrier="halophyte_oil")

    for td in build_halophyte_curve():
        td = dict(td)
        name = td.pop("_tranche_name")
        if name not in n.generators.index:
            n.add("Generator", name, **td)

    mass_yield = HEFA_FUEL_T_PER_T_OIL
    h2_mwh_per_t_oil = HEFA_H2_T_PER_T_OIL * H2_LHV_MWH_PER_T
    hcr_share_per_t_oil = SHARED_HCR_CAPEX_PER_T_YR * mass_yield
    conditioning_capex_per_t_oil = max(
        HEFA_CAPEX_PER_T_OIL_YR - hcr_share_per_t_oil, 0.0
    )
    capital_per_t_per_hr = conditioning_capex_per_t_oil * hours_per_year

    if "hefa_upgrading" not in n.links.index:
        n.add("Link", "hefa_upgrading",
              bus0="halophyte_oil_bus",
              bus1="kero_intermediate",
              bus2="diesel_intermediate",
              bus3="naphtha_intermediate",
              bus4=h2_bus,
              efficiency =  HEFA_PRODUCT_FRACS["kero"]    * mass_yield,
              efficiency2=  HEFA_PRODUCT_FRACS["diesel"]  * mass_yield,
              efficiency3=  HEFA_PRODUCT_FRACS["naphtha"] * mass_yield,
              efficiency4= -h2_mwh_per_t_oil,
              p_nom_extendable=True,
              capital_cost=capital_per_t_per_hr * crf(wacc, HEFA_LIFETIME_YEARS),
              marginal_cost=HEFA_OPEX_PER_T_OIL)
