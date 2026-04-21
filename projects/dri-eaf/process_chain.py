"""Attach the H2-DRI-EAF process chain onto a Whyalla facility network.

Unit convention for the steel bus
----------------------------------
All buses in the process chain carry **energy** in MW (MWh per snapshot hour).
We treat 1 tonne of steel as 1 unit of output and define the steel bus in
"equivalent MW" where the flow rate equals tonnes/hour:
    p_set [MW] == t_steel/h == annual_steel_mt * 1e6 / 8760

The EAF's electricity consumption (eaf_mwh_per_t_steel) is captured via
efficiency2 on the EAF link (bus2 = ac_bus, efficiency2 < 0 means input).
The DRI-to-steel conversion is 1:1 in these units (1 t DRI produces 1 t steel)
so the EAF link has efficiency=1.0 from dri_solid -> steel, plus
efficiency2=-eaf_mwh_per_t_steel consuming electricity per tonne.

H2 bus carries energy in MWh_LHV (H2 LHV = 33.33 MWh/t).
h2_per_t_dri [t H2/t DRI] * 33.33 [MWh/t H2] = MWh_H2 per t DRI.
The DRI plant link converts MWh_H2 input -> tonnes DRI output (MW_steel units):
    efficiency = 1.0 / (h2_per_t_dri * H2_LHV_MWH_PER_T)
because 1 MWh_H2 in produces (1 / h2_intensity_mwh) t DRI out.
"""
from __future__ import annotations

import pypsa

from whyalla_pypsa import annuitise

# H2 lower heating value: 33.33 MWh/t
H2_LHV_MWH_PER_T: float = 33.33


def attach_dri_eaf(
    network: pypsa.Network,
    *,
    h2_bus: str = "facility_h2",
    ac_bus: str = "facility_ac",
    annual_steel_mt: float = 1.6,
    electrolyser_capex_per_kw: float = 1500.0,
    electrolyser_efficiency: float = 0.70,
    electrolyser_min_load: float = 0.0,
    h2_per_t_dri: float = 0.057,
    dri_energy_mwh_per_t: float = 2.917,
    eaf_mwh_per_t_steel: float = 0.60,
    dri_pile_buffer_hours: float = 24.0,
    dri_ramp_limit_up: float = 0.2,
    dri_ramp_limit_down: float = 0.2,
    dri_min_load: float = 0.4,
    eaf_min_load: float = 0.0,
    eaf_campaign_buffer_hours: float = 8.0,
    wacc: float = 0.07,
    dri_lifetime_years: int = 25,
    eaf_lifetime_years: int = 30,
    dri_capex_per_t_yr: float = 250.0,
    eaf_capex_per_t_yr: float = 300.0,
    dual_fuel: bool = False,
    ng_intensity_mwh_per_t_dri: float = 3.0,
    ng_price_per_gj: float = 12.0,
    co2_intensity_kg_per_t_dri: float = 560.0,
    carbon_price_per_t_co2: float = 0.0,
) -> pypsa.Network:
    """Attach H2-DRI + EAF process chain onto a Whyalla facility network.

    Adds: Bus 'dri_reductant' (carrier 'H2'), Bus 'dri_solid', Bus 'steel';
    Link 'electrolyser' (ac_bus -> h2_bus); Link 'h2_to_dri' (h2_bus -> dri_reductant);
    Link 'dri_plant' (dri_reductant + ac_bus -> dri_solid);
    optional Store 'dri_pile' on dri_solid (e_cyclic, e_nom from dri_pile_buffer_hours);
    Link 'eaf' (dri_solid + ac_bus -> steel);
    optional Store 'eaf_campaign' on steel (e_cyclic, e_nom from eaf_campaign_buffer_hours);
    Load 'steel_offtake' on steel (constant).

    Returns the same network (mutated).
    """
    # ── Derived sizing ──────────────────────────────────────────────────────
    # Average steel production rate in t/h (== MW on steel bus)
    avg_steel_t_per_h = annual_steel_mt * 1e6 / 8760.0

    # Average DRI production rate (1:1 DRI->steel, but DRI feed > steel out
    # if yield < 1. Here we use 1:1 for bus flow balance; yield losses are
    # implicit in the capex sizing parameter dri_capex_per_t_yr).
    avg_dri_t_per_h = avg_steel_t_per_h

    # H2 intensity: MWh_H2 per tonne DRI
    h2_intensity_mwh_per_t = h2_per_t_dri * H2_LHV_MWH_PER_T  # ~1.9 MWh/t

    # Average H2 reductant power (MWh_H2/h = MW_H2)
    avg_h2_mw = avg_dri_t_per_h * h2_intensity_mwh_per_t

    # DRI plant nominal flow (t DRI/h == MW on dri_solid bus)
    # Over-size by 2x so the optimizer can dispatch above average
    dri_nom = avg_dri_t_per_h * 2.0

    # ── Carriers ────────────────────────────────────────────────────────────
    for carrier in ("DRI_solid", "steel"):
        if carrier not in network.carriers.index:
            network.add("Carrier", carrier)

    # ── Buses ───────────────────────────────────────────────────────────────
    # dri_reductant: H2 reductant stream, same carrier as facility_h2
    if "dri_reductant" not in network.buses.index:
        network.add("Bus", "dri_reductant", carrier="H2")
    if "dri_solid" not in network.buses.index:
        network.add("Bus", "dri_solid", carrier="DRI_solid")
    if "steel" not in network.buses.index:
        network.add("Bus", "steel", carrier="steel")

    # ── Electrolyser ────────────────────────────────────────────────────────
    ely_cc = annuitise(electrolyser_capex_per_kw * 1000.0, wacc, 20)
    network.add(
        "Link",
        "electrolyser",
        bus0=ac_bus,
        bus1=h2_bus,
        efficiency=electrolyser_efficiency,
        p_nom_extendable=True,
        p_min_pu=electrolyser_min_load,
        capital_cost=ely_cc,
        marginal_cost=1.0,
    )

    # ── H2 to DRI reductant feed ─────────────────────────────────────────────
    # Passes H2 from the main H2 bus to the dri_reductant bus (1:1).
    network.add(
        "Link",
        "h2_to_dri",
        bus0=h2_bus,
        bus1="dri_reductant",
        p_nom=avg_h2_mw * 2.0,
        efficiency=1.0,
    )

    # ── DRI plant ────────────────────────────────────────────────────────────
    # bus0: dri_reductant [MWh_H2]; bus1: dri_solid [t DRI = MW]; bus2: ac_bus [MWh electricity]
    # efficiency = (t DRI / h) per (MWh_H2 / h) = 1 / h2_intensity_mwh_per_t
    # efficiency2 = -dri_energy_mwh_per_t (auxiliary electricity consumption per t DRI input)
    # Note: efficiency2 is negative because it's a consumption on ac_bus.
    dri_eff = 1.0 / h2_intensity_mwh_per_t  # t DRI per MWh_H2
    dri_aux_eff2 = -dri_energy_mwh_per_t * dri_eff  # MWh_el per MWh_H2 input

    annual_dri_t = annual_steel_mt * 1e6
    dri_total_capex = dri_capex_per_t_yr * annual_dri_t
    dri_cc = annuitise(dri_total_capex, wacc, dri_lifetime_years)

    network.add(
        "Link",
        "dri_plant",
        bus0="dri_reductant",
        bus1="dri_solid",
        bus2=ac_bus,
        efficiency=dri_eff,
        efficiency2=dri_aux_eff2,
        p_nom=avg_h2_mw * 2.0,
        p_nom_min=avg_h2_mw,  # must at minimum run at average rate
        p_min_pu=dri_min_load,
        ramp_limit_up=dri_ramp_limit_up,
        ramp_limit_down=dri_ramp_limit_down,
        capital_cost=dri_cc,
        marginal_cost=0.5,
    )

    # ── Dual-fuel (NG) DRI path ──────────────────────────────────────────────
    # Optional parallel path: natural-gas reduction alongside H2. Shares the
    # physical DRI plant capacity in reality, so we give the gas link zero
    # capital_cost and let the H2 link carry the full capex (option A).
    # TODO: enforce a per-snapshot constraint that flow(dri_plant) +
    # flow(dri_plant_gas) <= p_nom(dri_plant) so the two paths can't
    # simultaneously exceed a single plant's throughput.
    if dual_fuel:
        if "gas" not in network.carriers.index:
            network.add("Carrier", "gas")
        if "ng" not in network.buses.index:
            network.add("Bus", "ng", carrier="gas")

        # NG supply: unlimited at a fixed $/MWh_NG price (LHV basis).
        # ng_price_per_gj [$/GJ] * 3.6 [GJ/MWh] = $/MWh_NG
        network.add(
            "Generator",
            "ng_supply",
            bus="ng",
            carrier="gas",
            p_nom_extendable=False,
            p_nom=1e5,
            marginal_cost=ng_price_per_gj * 3.6,
        )

        # Gas DRI link: MWh_NG -> t DRI, with electrical aux on ac_bus.
        ng_eff = 1.0 / ng_intensity_mwh_per_t_dri  # t DRI per MWh_NG
        ng_aux_eff2 = -dri_energy_mwh_per_t * ng_eff  # MWh_el per MWh_NG input

        # Carbon cost folded into marginal_cost on the gas link.
        # Emissions per MWh_NG = (co2_intensity / ng_intensity) kg CO2 / MWh_NG
        # [$/tCO2] * [kgCO2/tDRI] / [1000 kg/t] / [MWh_NG/tDRI] = $/MWh_NG
        ng_carbon_mc = (
            carbon_price_per_t_co2
            * co2_intensity_kg_per_t_dri
            / 1000.0
            / ng_intensity_mwh_per_t_dri
        )

        network.add(
            "Link",
            "dri_plant_gas",
            bus0="ng",
            bus1="dri_solid",
            bus2=ac_bus,
            efficiency=ng_eff,
            efficiency2=ng_aux_eff2,
            p_nom_extendable=True,
            capital_cost=0.0,  # shared with dri_plant to avoid double-counting capex
            marginal_cost=ng_carbon_mc,
        )

    # ── DRI pile buffer ───────────────────────────────────────────────────────
    if dri_pile_buffer_hours > 0:
        dri_pile_mwh = avg_dri_t_per_h * dri_pile_buffer_hours
        network.add(
            "Store",
            "dri_pile",
            bus="dri_solid",
            e_nom=dri_pile_mwh,
            e_cyclic=True,
        )

    # ── EAF ──────────────────────────────────────────────────────────────────
    # bus0: dri_solid [t DRI = MW]; bus1: steel [t steel = MW]; bus2: ac_bus [MWh electricity]
    # 1 t DRI -> 1 t steel (1:1 yield assumed in bus flow)
    # efficiency2 = -eaf_mwh_per_t_steel (electricity input per tonne steel out)
    annual_steel_t = annual_steel_mt * 1e6
    eaf_total_capex = eaf_capex_per_t_yr * annual_steel_t
    eaf_cc = annuitise(eaf_total_capex, wacc, eaf_lifetime_years)

    network.add(
        "Link",
        "eaf",
        bus0="dri_solid",
        bus1="steel",
        bus2=ac_bus,
        efficiency=1.0,
        efficiency2=-eaf_mwh_per_t_steel,
        p_nom=avg_steel_t_per_h * 2.5,  # allow peak above average
        p_min_pu=eaf_min_load,
        capital_cost=eaf_cc,
        marginal_cost=0.5,
    )

    # ── EAF campaign buffer ───────────────────────────────────────────────────
    if eaf_campaign_buffer_hours > 0:
        eaf_campaign_mwh = avg_steel_t_per_h * eaf_campaign_buffer_hours
        network.add(
            "Store",
            "eaf_campaign",
            bus="steel",
            e_nom=eaf_campaign_mwh,
            e_cyclic=True,
        )

    # ── Steel offtake load ────────────────────────────────────────────────────
    # Constant demand at average production rate (t/h == MW on steel bus)
    network.add(
        "Load",
        "steel_offtake",
        bus="steel",
        p_set=avg_steel_t_per_h,
    )

    return network
