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
from heat_integration import (
    attach_process_heat_duty,
    PROCESS_HEAT_DUTY_BUS,
    REFINERY_HEAT_MWH_PER_T_PRODUCT,
)

# ── Shared multi-feed hydrocracker ───────────────────────────────────────
# The finishing hydrocracker (HCR) is the same piece of kit whether it's
# processing FT paraffin, pyrolysis bio-oil post-HDO, HEFA intermediate,
# or HTL biocrude post-HDO. Industrial practice (Neste Porvoo, Eni Venice,
# Shell Pearl) routes blended feeds through a single HCR block. Modelling
# this synergy: each feedstock-specific "conditioning" Link delivers to a
# product-intermediate bus (diesel_intermediate / kero_intermediate /
# naphtha_intermediate), and one shared HCR Link per product picks up the
# pooled feed, with its own extendable capex. The LP sizes the shared HCR
# at the peak aggregate throughput — peak-sharing saves capex when
# multiple pathways run concurrently.
#
# A$150/(t product/yr) is the benchmark for a finishing HCR block alone
# (vs ~A$400/(t product/yr) for a full FT+HCR refinery train). Wax is
# NOT routed via the shared HCR — it's the residual post-HCR FT output,
# sold as specialty wax; keeps the direct refinery_wax → wax_bus path.
SHARED_HCR_CAPEX_PER_T_YR = 150.0
SHARED_HCR_LIFETIME_YEARS = 25
_INTERMEDIATE_BUS = {
    "naphtha": "naphtha_intermediate",
    "kero":    "kero_intermediate",
    "diesel":  "diesel_intermediate",
}
_SHARED_HCR_PRODUCTS = ("naphtha", "kero", "diesel")
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
    renewables_wacc: float = 0.07,
    cst_profile=None,   # pd.Series | None — AEMO REZ_S5_Northern_SA_CST trace
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
    for carrier in ("CO2", "MeOH", "naphtha", "kero", "diesel", "wax", "fuel",
                     "naphtha_int", "kero_int", "diesel_int"):
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier)

    # ── Process heat bus (shared with biofuels) ──────────────────────────
    # Creates process_heat_duty bus + free DRI waste heat + electric heater
    # + h2_burner + CST (PPA-WACC) with molten salt storage.
    # CST + MS finance at the facility's renewables WACC (PPA-backed, lower
    # risk than the FOAK process kit); caller can pin via cst_wacc kwarg.
    attach_process_heat_duty(n, wacc=wacc, ac_bus=ac_bus, h2_bus=h2_bus,
                              cst_wacc=renewables_wacc,
                              cst_profile=cst_profile)

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
    if product_split_mode in ("asf", "hydrocracked_ft"):
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
            split_mode=product_split_mode,
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
    split_mode: str = "asf",
    snap_w: float,
) -> None:
    """Attach per-product buses, refinery Links, and offtake components.

    split_mode = "asf"            → raw ASF distribution from chain growth α
                 "hydrocracked_ft" → ASF + wax hydrocracker (industry standard).
                                     Wax (C21+) is cracked to diesel+kero; fixed
                                     post-hydrocracking fractions reflect Sasol/
                                     Shell Pearl GTL product slate: 45% kero,
                                     35% diesel, 15% naphtha, 5% residual wax.
                                     Mass yield drops slightly (0.455 → 0.43)
                                     to reflect H₂ consumed in hydrocracking.
    """
    if split_mode == "hydrocracked_ft":
        fracs = {"naphtha": 0.15, "kero": 0.45, "diesel": 0.35, "wax": 0.05}
        mass_yield = 0.43  # post-hydrocracking H₂ consumption included
    else:
        fracs = asf_mass_fractions(asf_alpha)
        mass_yield = _MEOH_TO_LIQUID_MASS_YIELD
    product_prices = {
        "naphtha": naphtha_price_per_t,
        "kero":    kero_price_per_t,
        "diesel":  diesel_price_per_t,
        "wax":     wax_price_per_t,
    }

    # Per-product buses (always needed for export/offtake/HCR output)
    for product in fracs:
        bus_name = f"{product}_bus"
        if bus_name not in n.buses.index:
            n.add("Bus", bus_name, carrier=product)
        # Intermediate buses for HCR products
        if product in _INTERMEDIATE_BUS:
            int_bus = _INTERMEDIATE_BUS[product]
            if int_bus not in n.buses.index:
                n.add("Bus", int_bus, carrier=f"{product}_int")

    # ── Single refinery Link: MeOH → full FT slate (proportional) ────────
    # One Link, multi-output. Forces the LP to produce the slate in fixed
    # proportions (matches a real refinery train) rather than dispatching
    # each product through its own independent Link — which was a mass-
    # accounting bug that made the LP consume 4× stoichiometric MeOH.
    #
    # Outputs:
    #   bus1 = diesel_intermediate   (→ shared_hcr_diesel → diesel_bus)
    #   bus2 = kero_intermediate     (→ shared_hcr_kero   → kero_bus)
    #   bus3 = naphtha_intermediate  (→ shared_hcr_naphtha → naphtha_bus)
    #   bus4 = wax_bus (direct; not hydrocracked — residual specialty)
    #   bus5 = process_heat_duty (heat drawn at 0.8 MWh_th/t aggregate)
    if "refinery" not in n.links.index:
        # Mass-flow per MWh MeOH for each product (t/MWh_meoh).
        # t_product_per_mwh_meoh × frac gives this product's contribution.
        per_mwh = (1.0 / MEOH_LHV_MWH_PER_T) * mass_yield
        eff_diesel  = per_mwh * fracs["diesel"]
        eff_kero    = per_mwh * fracs["kero"]
        eff_naphtha = per_mwh * fracs["naphtha"]
        eff_wax     = per_mwh * fracs["wax"]

        # Total net heat drawn per MWh MeOH (scales with total product).
        refinery_heat_per_mwh_meoh = per_mwh * REFINERY_HEAT_MWH_PER_T_PRODUCT

        # Capex: AUD / (t/yr finished product) × t_product/(MW_MeOH × yr).
        # Weighted: non-wax fraction gets conditioning-only rate (HCR is
        # charged separately by shared_hcr Links); wax gets full rate.
        non_wax_sum = 1.0 - fracs["wax"]
        weighted_capex_per_t_yr = (
            (refinery_capex_per_t_yr - SHARED_HCR_CAPEX_PER_T_YR) * non_wax_sum
            + refinery_capex_per_t_yr * fracs["wax"]
        )
        total_t_per_mw_meoh_yr = per_mwh * hours_per_year
        refinery_capex_per_mw_meoh = weighted_capex_per_t_yr * total_t_per_mw_meoh_yr
        refinery_vom_per_mwh_meoh  = refinery_opex_per_t * per_mwh

        n.add("Link", "refinery",
              bus0="meoh",
              bus1="diesel_intermediate",
              bus2="kero_intermediate",
              bus3="naphtha_intermediate",
              bus4="wax_bus",
              bus5=PROCESS_HEAT_DUTY_BUS,
              efficiency =eff_diesel,
              efficiency2=eff_kero,
              efficiency3=eff_naphtha,
              efficiency4=eff_wax,
              efficiency5=-refinery_heat_per_mwh_meoh,
              p_nom_extendable=True,
              capital_cost=refinery_capex_per_mw_meoh * crf(wacc, refinery_lifetime_years),
              marginal_cost=refinery_vom_per_mwh_meoh)

    for product, frac in fracs.items():
        bus_name = f"{product}_bus"

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

    # ── Shared multi-feed hydrocracker (one per intermediate product) ─────
    # Efficiency 1.0 (mass-preserving pass-through); the "finishing" H₂
    # consumption and the 2-3% light-gas mass loss are small and already
    # baked into the upstream conditioning Links' product-slate yield.
    # Capex is the sole economic effect — shared sizing means multiple
    # pathways can peak-share one hydrocracker block.
    for product in _SHARED_HCR_PRODUCTS:
        hcr_name = f"shared_hcr_{product}"
        if hcr_name in n.links.index:
            continue
        # p at bus0 is t/hr of intermediate. capital_cost is AUD / (t/hr)
        # since capacity is sized in the intermediate's native unit.
        capital_per_t_per_hr = SHARED_HCR_CAPEX_PER_T_YR * hours_per_year
        n.add("Link", hcr_name,
              bus0=_INTERMEDIATE_BUS[product],
              bus1=f"{product}_bus",
              efficiency=1.0,
              p_nom_extendable=True,
              capital_cost=capital_per_t_per_hr * crf(wacc, SHARED_HCR_LIFETIME_YEARS),
              marginal_cost=0.0)


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
