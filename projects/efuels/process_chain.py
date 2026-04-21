"""Attach the Whyalla e-fuels process chain onto a `build_facility_network` output.

Topology after `attach_efuels()`:

    facility_ac ──► electrolyser ──► facility_h2 ──► (h2 store already present)
                                           │
                             (bus2 = co2 bus, drawn)
                             (bus3 = facility_ac, drawn for aux electricity)
                                           ▼
    co2 ──[tranches]──► meoh_synthesis ──► meoh ──► meoh_storage
                                                 │
                                    ┌────────────┼────────────┬───────────┐
                                    ▼            ▼            ▼           ▼
                                refinery_  refinery_  refinery_  refinery_
                                naphtha    kero       diesel     wax
                                    │            │            │           │
                               [product bus]  ...          ...          ...
                               Load + export Generator per product

ASF product split (disjoint carbon-number buckets, alpha=0.90 default):
    naphtha  n=5..8   ~0.098
    kero     n=9..14  ~0.209
    diesel   n=15..20 ~0.268
    wax      n=21..40 ~0.425
(fractions normalised over the liquid cut n=5..40; see efuels_physics.asf_mass_fractions)
"""
from __future__ import annotations

from typing import Callable

import pypsa

from whyalla_pypsa import crf

from co2_supply import build_co2_supply_curve
from efuels_physics import (
    ELECTROLYSER_EFFICIENCY,
    ELECTROLYSER_LIFE_YR,
    MEOH_LHV_MWH_PER_T,
    MEOH_SYNTHESIS_LHV_EFFICIENCY,
    MEOH_SYNTHESIS_LIFE_YR,
    MEOH_STORAGE_LIFE_YR,
    MEOH_AUX_ELEC_MWH_PER_T,
    T_CO2_PER_T_MEOH,
    T_H2_PER_T_MEOH,
    H2_LHV_MWH_PER_T,
    NAPHTHA_LHV_MWH_PER_T,
    KERO_LHV_MWH_PER_T,
    DIESEL_LHV_MWH_PER_T,
    WAX_LHV_MWH_PER_T,
    asf_mass_fractions,
)

# Mass yield of liquid product per tonne MeOH input in MTG/MTO-style upgrading.
# Stoichiometrically, MeOH (CH3OH, MW=32) loses the O as water → hydrocarbons.
# Practical yield ~0.44–0.50 t liquid HC / t MeOH (Topsoe TIGAS; Ruokonen 2021).
_MEOH_TO_LIQUID_MASS_YIELD = 0.455   # t liquid hydrocarbon per t MeOH input

_PRODUCT_LHV: dict[str, float] = {
    "naphtha": NAPHTHA_LHV_MWH_PER_T,
    "kero":    KERO_LHV_MWH_PER_T,
    "diesel":  DIESEL_LHV_MWH_PER_T,
    "wax":     WAX_LHV_MWH_PER_T,
}


def _default_co2_tranches() -> list[dict]:
    # year=2030 fallback; real callers should pass co2_supply_fn with a year
    return build_co2_supply_curve(2030)


def attach_efuels(
    network: pypsa.Network,
    *,
    ac_bus: str = "facility_ac",
    h2_bus: str = "facility_h2",
    # --- electrolyser -----
    electrolyser_capex_per_kw: float = 1500.0,
    electrolyser_efficiency: float = ELECTROLYSER_EFFICIENCY,
    electrolyser_min_load: float = 0.0,
    # --- CO2 supply -----
    co2_supply_fn: Callable[[], list[dict]] | None = None,
    co2_storage_capex_per_t: float = 150.0,
    # --- synthesis (methanol) -----
    synthesis_capex_per_t_meoh_yr: float = 800.0,
    synthesis_min_load: float = 0.3,
    synthesis_ramp_limit: float = 0.25,
    synthesis_vom_per_t: float = 30.0,
    # --- product split (ASF / pathway) -----
    product_split_mode: str = "asf",
    asf_alpha: float = 0.90,
    # --- refinery / upgrading -----
    refinery_capex_per_t_yr: float = 400.0,
    refinery_opex_per_t: float = 50.0,
    # --- product prices (offtake) -----
    naphtha_price_per_t: float = 800.0,
    kero_price_per_t: float = 1200.0,
    diesel_price_per_t: float = 1100.0,
    wax_price_per_t: float = 600.0,
    methanol_price_per_t: float = 650.0,
    # --- target production -----
    annual_fuel_mt: float = 0.5,
    wacc: float = 0.07,
    synthesis_lifetime_years: int = 25,
    refinery_lifetime_years: int = 25,
    electrolyser_lifetime_years: int = ELECTROLYSER_LIFE_YR,
) -> pypsa.Network:
    """Attach e-fuels process chain onto a Whyalla facility network.

    See module docstring for topology. Returns mutated network.
    """
    n = network
    snap_w = n.snapshot_weightings.generators.iloc[0]
    n_snapshots = len(n.snapshots)
    hours_per_year = n_snapshots * snap_w

    # ── Carriers ─────────────────────────────────────────────────────────
    for carrier in ("CO2", "MeOH", "naphtha", "kero", "diesel", "wax", "fuel"):
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier)

    # ── Buses ─────────────────────────────────────────────────────────────
    for bus, carrier in [
        ("co2",     "CO2"),
        ("meoh",    "MeOH"),
    ]:
        if bus not in n.buses.index:
            n.add("Bus", bus, carrier=carrier)

    # ── CO2 supply tranches ───────────────────────────────────────────────
    get_tranches = co2_supply_fn if co2_supply_fn is not None else _default_co2_tranches
    tranches = get_tranches()
    for td in tranches:
        td = dict(td)
        name = td.pop("_tranche_name")
        td.pop("bus", None)
        td.pop("carrier", None)
        if name not in n.generators.index:
            n.add("Generator", name, bus="co2", carrier="CO2", **td)

    # CO2 buffer store (short-cycle liquid tank)
    if "co2_storage" not in n.stores.index:
        n.add("Store", "co2_storage",
              bus="co2",
              e_nom_extendable=True,
              capital_cost=co2_storage_capex_per_t * crf(wacc, 25),
              e_cyclic=True)

    # ── Electrolyser (AC → H2) ────────────────────────────────────────────
    ely_capital = electrolyser_capex_per_kw * 1_000 * crf(wacc, electrolyser_lifetime_years)
    if "electrolyser" not in n.links.index:
        n.add("Link", "electrolyser",
              bus0=ac_bus,
              bus1=h2_bus,
              efficiency=electrolyser_efficiency,
              p_nom_extendable=True,
              p_min_pu=electrolyser_min_load,
              capital_cost=ely_capital,
              marginal_cost=1.0)

    # ── Methanol synthesis (multi-bus Link) ───────────────────────────────
    # Flow variable p is MWh H2 consumed at bus0 (h2_bus).
    # The synthesis link is sized on H2 input capacity (MW H2).
    #
    # Efficiencies (all relative to p, the H2 input flow):
    #   bus1 (meoh out):  +efficiency1 = (MWh MeOH / MWh H2)
    #                     = MEOH_SYNTHESIS_LHV_EFFICIENCY × (MeOH LHV / H2_required_per_meoh)
    #                     Derived: 1 t MeOH needs T_H2_PER_T_MEOH t H2 = 0.1875 × 33.333 MWh
    #                     = 6.25 MWh H2/t MeOH (ideal); practical = /MEOH_SYNTHESIS_LHV_EFFICIENCY
    #                     h2_mwh_input_per_t_meoh = (T_H2_PER_T_MEOH × H2_LHV) / synth_eff
    #                     MeOH_MWh per H2_MWh = MEOH_LHV / h2_input_per_t_meoh
    #   bus2 (co2, drawn): -efficiency2 = -(t CO2 / MWh H2 input)
    #                     = -(T_CO2_PER_T_MEOH / h2_mwh_input_per_t_meoh)
    #   bus3 (AC, drawn):  -efficiency3 = -(MWh_elec / MWh_H2)
    #                     = -(MEOH_AUX_ELEC / h2_mwh_input_per_t_meoh)

    h2_input_per_t_meoh = (T_H2_PER_T_MEOH * H2_LHV_MWH_PER_T) / MEOH_SYNTHESIS_LHV_EFFICIENCY
    meoh_mwh_per_h2_mwh = MEOH_LHV_MWH_PER_T / h2_input_per_t_meoh
    co2_t_per_h2_mwh = T_CO2_PER_T_MEOH / h2_input_per_t_meoh
    aux_elec_per_h2_mwh = MEOH_AUX_ELEC_MWH_PER_T / h2_input_per_t_meoh

    # Synthesis CAPEX: AUD/(t MeOH/yr) → AUD/MW H2 input capacity
    # MW H2 input = (t MeOH/yr × h2_input_per_t_meoh) / hours_per_year
    # AUD/MW H2 = AUD/(t/yr) × (t/yr per MW H2) = synthesis_capex × (hours_per_year / h2_input_per_t_meoh)
    synth_capex_per_mw_h2 = synthesis_capex_per_t_meoh_yr * (hours_per_year / h2_input_per_t_meoh)
    synth_vom_per_mwh_h2 = synthesis_vom_per_t / h2_input_per_t_meoh  # AUD/MWh H2

    if "meoh_synthesis" not in n.links.index:
        n.add("Link", "meoh_synthesis",
              bus0=h2_bus,
              bus1="meoh",
              bus2="co2",
              bus3=ac_bus,
              efficiency=meoh_mwh_per_h2_mwh,
              efficiency2=-co2_t_per_h2_mwh,
              efficiency3=-aux_elec_per_h2_mwh,
              p_nom_extendable=True,
              p_min_pu=synthesis_min_load,
              ramp_limit_up=synthesis_ramp_limit,
              ramp_limit_down=synthesis_ramp_limit,
              capital_cost=synth_capex_per_mw_h2 * crf(wacc, synthesis_lifetime_years),
              marginal_cost=synth_vom_per_mwh_h2)

    # ── MeOH storage ─────────────────────────────────────────────────────
    meoh_storage_capex_mwh = 150.0 / MEOH_LHV_MWH_PER_T  # AUD/MWh (tank farm ~150 AUD/t)
    if "meoh_storage" not in n.stores.index:
        n.add("Store", "meoh_storage",
              bus="meoh",
              e_nom_extendable=True,
              capital_cost=meoh_storage_capex_mwh * crf(wacc, MEOH_STORAGE_LIFE_YR),
              e_cyclic=True)

    # ── Product buses + refineries ────────────────────────────────────────
    if product_split_mode == "asf":
        _attach_asf_products(
            n, ac_bus=ac_bus, asf_alpha=asf_alpha,
            refinery_capex_per_t_yr=refinery_capex_per_t_yr,
            refinery_opex_per_t=refinery_opex_per_t,
            naphtha_price_per_t=naphtha_price_per_t,
            kero_price_per_t=kero_price_per_t,
            diesel_price_per_t=diesel_price_per_t,
            wax_price_per_t=wax_price_per_t,
            annual_fuel_mt=annual_fuel_mt,
            wacc=wacc,
            refinery_lifetime_years=refinery_lifetime_years,
            hours_per_year=hours_per_year,
            snap_w=snap_w,
        )
    elif product_split_mode == "single_fuel":
        _attach_single_fuel(
            n, ac_bus=ac_bus,
            methanol_price_per_t=methanol_price_per_t,
            annual_fuel_mt=annual_fuel_mt,
            hours_per_year=hours_per_year,
        )
    elif product_split_mode == "mto_mogd":
        # TODO: implement MTO+MOGD mode with explicit distillate/gasoline split
        raise NotImplementedError("mto_mogd mode not yet implemented; use asf or single_fuel")
    else:
        raise ValueError(f"Unknown product_split_mode: {product_split_mode!r}")

    return n


def _attach_asf_products(
    n: pypsa.Network,
    *,
    ac_bus: str,
    asf_alpha: float,
    refinery_capex_per_t_yr: float,
    refinery_opex_per_t: float,
    naphtha_price_per_t: float,
    kero_price_per_t: float,
    diesel_price_per_t: float,
    wax_price_per_t: float,
    annual_fuel_mt: float,
    wacc: float,
    refinery_lifetime_years: int,
    hours_per_year: float,
    snap_w: float,
) -> None:
    """Attach per-product buses, refinery Links, and offtake components."""
    fracs = asf_mass_fractions(asf_alpha)
    product_prices = {
        "naphtha": naphtha_price_per_t,
        "kero":    kero_price_per_t,
        "diesel":  diesel_price_per_t,
        "wax":     wax_price_per_t,
    }

    for product, frac in fracs.items():
        bus_name = f"{product}_bus"
        if bus_name not in n.buses.index:
            n.add("Bus", bus_name, carrier=product)

        # Refinery Link: MeOH (LHV MWh) → product (mass tonnes on product bus).
        # PyPSA flow variable p is in MeOH bus units (MWh LHV).
        # efficiency = product mass flow per MWh MeOH input:
        #   t_product / MWh_MeOH = (t_meoh / MWh_MeOH) × mass_yield × product_frac
        #                         = (1/MEOH_LHV) × _MEOH_TO_LIQUID_MASS_YIELD × frac
        # This bakes the ASF split into the link efficiency so the LP sees
        # per-product revenue directly.
        t_product_per_mwh_meoh = (1.0 / MEOH_LHV_MWH_PER_T) * _MEOH_TO_LIQUID_MASS_YIELD * frac
        link_name = f"refinery_{product}"

        # Refinery CAPEX: AUD/(t product/yr) → AUD/MW MeOH input
        # MW MeOH to produce (frac * annual_fuel_mt t/yr):
        #   but we size extendably, so we just need AUD/MW MeOH (input capacity basis).
        # Annual t product per MW MeOH input = t_product_per_mwh_meoh × hours_per_year
        t_product_per_mw_meoh_yr = t_product_per_mwh_meoh * hours_per_year
        refinery_capex_per_mw_meoh = (
            refinery_capex_per_t_yr * t_product_per_mw_meoh_yr
        )
        refinery_vom_per_mwh_meoh = refinery_opex_per_t * t_product_per_mwh_meoh

        if link_name not in n.links.index:
            n.add("Link", link_name,
                  bus0="meoh",
                  bus1=bus_name,
                  efficiency=t_product_per_mwh_meoh,
                  p_nom_extendable=True,
                  capital_cost=refinery_capex_per_mw_meoh * crf(wacc, refinery_lifetime_years),
                  marginal_cost=refinery_vom_per_mwh_meoh)

        # Export generator: sign=-1, revenue = -price/t × dispatch (t/period)
        price = product_prices[product]
        export_name = f"{product}_export"
        if export_name not in n.generators.index:
            n.add("Generator", export_name,
                  bus=bus_name,
                  carrier=product,
                  p_nom=1e9,
                  p_min_pu=0.0,
                  sign=-1,
                  marginal_cost=-price)
            # PyPSA objective: sum(mc × p × w). sign=-1 so revenue = -mc × p × w.
            # mc = -price_per_t → revenue = price_per_t × p × w = price × annual_tonnes.
            # TODO: confirm PyPSA bus unit consistency for non-energy carriers;
            # p is in the bus's native unit (tonnes here), so price_per_t is correct.

        # Contracted offtake Load (only if annual_fuel_mt > 0)
        if annual_fuel_mt > 0:
            # t/hr = (Mt/yr × 1e6 × frac) / hours_per_year
            load_t_per_hr = (annual_fuel_mt * 1e6 * frac) / hours_per_year
            load_name = f"{product}_offtake"
            if load_name not in n.loads.index:
                n.add("Load", load_name,
                      bus=bus_name,
                      p_set=load_t_per_hr)


def _attach_single_fuel(
    n: pypsa.Network,
    *,
    ac_bus: str,
    methanol_price_per_t: float,
    annual_fuel_mt: float,
    hours_per_year: float,
) -> None:
    """Direct methanol export mode: no upgrading, MeOH sold as fuel."""
    # Revenue generator on meoh bus (sign=-1, unit: MWh MeOH LHV)
    price_per_mwh = methanol_price_per_t / MEOH_LHV_MWH_PER_T
    if "meoh_export" not in n.generators.index:
        n.add("Generator", "meoh_export",
              bus="meoh",
              carrier="MeOH",
              p_nom=1e9,
              p_min_pu=0.0,
              sign=-1,
              marginal_cost=-price_per_mwh)

    if annual_fuel_mt > 0:
        load_mwh_per_hr = (annual_fuel_mt * 1e6 * MEOH_LHV_MWH_PER_T) / hours_per_year
        if "meoh_offtake" not in n.loads.index:
            n.add("Load", "meoh_offtake",
                  bus="meoh",
                  p_set=load_mwh_per_hr)
