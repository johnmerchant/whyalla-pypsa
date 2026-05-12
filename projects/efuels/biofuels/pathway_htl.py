"""Pathway A: marine microalgae → HTL biocrude → drop-in fuels.

Two candidate sites compete on the cost surface:

  **steelworks** — small-scale pond + HTL plant adjacent to the DRI-EAF.
    Benefits: free 800°C off-gas waste heat (200 GWh_th/yr cap),
    free biogenic CO₂ from the flue (no pipeline). Land-limited.

  **port_bonython** — larger pond + HTL plant on Cultana / Point Lowly
    coastal flats. Heat must come from the Port Bonython process bus
    (electric heater / CST / h2_burner), paid at bus marginal price.
    CO₂ feedstock trucked/piped from the merit-order (co2_steelworks
    tranche at A$80/t is already cheap, so this isn't a huge
    disadvantage). More land available.

Topology (per site):

    algae_feed_<site>_bus ──► htl_upgrading_<site> ──► diesel_bus
    (free seawater/brine    (multi-output Link)     ──► kero_bus
     intake, free feedstock)                        ──► naphtha_bus
                                                    ◄── facility_h2
                                                    ◄── <site>_heat_duty

The algae feedstock Generator is bounded by pond area × areal
productivity, so the optimiser scales each site continuously up to its
land cap and picks the mix.
"""
from __future__ import annotations

import pypsa

from whyalla_pypsa import crf

from efuels_physics import H2_LHV_MWH_PER_T

from .biomass_supply import build_algae_curve
from process_chain import SHARED_HCR_CAPEX_PER_T_YR
from .physics import (
    HTL_FUEL_T_PER_T_DRY,
    HTL_PRODUCT_FRACS,
    HTL_H2_T_PER_T_DRY,
    HTL_HEAT_MWH_PER_T_DRY,
    HTL_ELEC_MWH_PER_T_DRY,
    HTL_CAPEX_PER_T_DRY_YR,
    HTL_OPEX_PER_T_DRY,
    HTL_LIFETIME_YEARS,
)
from .waste_streams import HOURS_PER_YEAR
from heat_integration import (
    STEELWORKS_HEAT_DUTY_BUS,
    PROCESS_HEAT_DUTY_BUS,
)


_SITE_HEAT_BUS = {
    "steelworks":    STEELWORKS_HEAT_DUTY_BUS,
    "port_bonython": PROCESS_HEAT_DUTY_BUS,
}


def attach_htl(
    n: pypsa.Network,
    *,
    wacc: float,
    site: str = "steelworks",
    h2_bus: str = "facility_h2",
    grid_price_for_aux: float = 120.0,
    hours_per_year: float = HOURS_PER_YEAR,
) -> None:
    """Attach one site's HTL pond supply curve + HTL Link.

    Algae feedstock is now a tranched supply curve (see biomass_supply.py)
    rather than a single fixed Generator. Call twice (once per site) to
    let the LP pick the mix.
    """
    if site not in _SITE_HEAT_BUS:
        raise ValueError(
            f"Unknown HTL site {site!r}; use 'steelworks' or 'port_bonython'"
        )
    heat_duty_bus = _SITE_HEAT_BUS[site]

    feed_bus  = f"algae_feed_{site}_bus"
    link_name = f"htl_upgrading_{site}"

    if "algae_feed" not in n.carriers.index:
        n.add("Carrier", "algae_feed")
    if feed_bus not in n.buses.index:
        n.add("Bus", feed_bus, carrier="algae_feed")

    for td in build_algae_curve(site):
        td = dict(td)
        name = td.pop("_tranche_name")
        if name not in n.generators.index:
            n.add("Generator", name, **td)

    mass_yield = HTL_FUEL_T_PER_T_DRY
    h2_mwh_per_t_dry = HTL_H2_T_PER_T_DRY * H2_LHV_MWH_PER_T
    bundled_aux_aud_per_t_dry = HTL_ELEC_MWH_PER_T_DRY * grid_price_for_aux
    marginal_cost_per_t_dry = HTL_OPEX_PER_T_DRY + bundled_aux_aud_per_t_dry
    hcr_share_per_t_dry = SHARED_HCR_CAPEX_PER_T_YR * mass_yield
    conditioning_capex_per_t_dry = max(
        HTL_CAPEX_PER_T_DRY_YR - hcr_share_per_t_dry, 0.0
    )
    capital_per_t_per_hr = conditioning_capex_per_t_dry * hours_per_year

    if link_name not in n.links.index:
        n.add("Link", link_name,
              bus0=feed_bus,
              bus1="diesel_intermediate",
              bus2="kero_intermediate",
              bus3="naphtha_intermediate",
              bus4=h2_bus,
              bus5=heat_duty_bus,
              efficiency =  HTL_PRODUCT_FRACS["diesel"]  * mass_yield,
              efficiency2=  HTL_PRODUCT_FRACS["kero"]    * mass_yield,
              efficiency3=  HTL_PRODUCT_FRACS["naphtha"] * mass_yield,
              efficiency4= -h2_mwh_per_t_dry,
              efficiency5= -HTL_HEAT_MWH_PER_T_DRY,
              p_nom_extendable=True,
              capital_cost=capital_per_t_per_hr * crf(wacc, HTL_LIFETIME_YEARS),
              marginal_cost=marginal_cost_per_t_dry)
