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
    dri_energy_mwh_per_t: float = 0.10,
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
    # ── Reducing-gas heat system (heat_duty bus) ─────────────────────────────
    heat_per_t_dri: float = 0.90,
    electric_heater_efficiency: float = 0.97,
    electric_heater_capex_per_kw_th: float = 400.0,
    electric_heater_lifetime_years: int = 20,
    h2_burner_efficiency: float = 0.85,
    h2_burner_capex_per_kw_th: float = 30.0,
    h2_burner_lifetime_years: int = 20,
    # ── Dual-fuel (MIDREX Flex) ──────────────────────────────────────────────
    dual_fuel: bool = False,
    ng_intensity_mwh_per_t_dri: float = 3.0,
    ng_min_share: float = 0.0,
    min_h2_share: float = 0.0,
    ng_price_per_gj: float = 12.0,
    # Optional Santos-style foundation contract: cap on annual deal-gas volume,
    # with uncapped spot supply available above the cap at a higher price.
    # When `ng_annual_volume_pj` is None the historical single-tier behaviour
    # holds (ng_supply at ng_price_per_gj, no volume cap).
    ng_annual_volume_pj: float | None = None,
    ng_spot_price_per_gj: float = 22.0,
    co2_intensity_kg_per_t_dri: float = 560.0,
    carbon_price_per_t_co2: float = 0.0,
    # ── Biomethane (drop-in to ng bus, zero combustion CO2) ──────────────────
    # When `biomethane_annual_volume_pj` is set, a parallel generator on the
    # `ng` bus supplies up to that annual volume (`e_sum_max`) at
    # biomethane_price_per_gj. It is consumed transparently by the same
    # `dri_plant_gas` link as fossil NG. Carbon cost is *not* applied to
    # biomethane — see the carbon cost relocation below.
    biomethane_annual_volume_pj: float | None = None,
    biomethane_price_per_gj: float = 17.0,
    # ── Scrap feed to EAF ────────────────────────────────────────────────────
    # Two-tier supply curve. Tier 1 is Whyalla's contracted share of AU
    # domestic HMS 80:20 (BIR World Steel Recycling: AU recovers ~6 Mt/yr,
    # ~1 Mt realistically allocable to a single mill). Tier 2 is premium
    # HMS / shred and seaborne imports (China/India landed ~$700-850/t),
    # the marginal source once domestic is exhausted. The peak-rate caps
    # (capacity_t_per_yr / 8760) double as annual budgets at 100 %
    # utilisation, so the LP can use less but never more.
    enable_scrap: bool = True,
    scrap_tier1_capacity_t_per_yr: float = 1_000_000.0,
    scrap_tier1_price_per_t: float = 500.0,
    scrap_tier2_capacity_t_per_yr: float = 800_000.0,
    scrap_tier2_price_per_t: float = 700.0,
    scrap_max_share: float = 0.30,
) -> pypsa.Network:
    """Attach H2-DRI + EAF process chain onto a Whyalla facility network.

    Adds: Bus 'dri_reductant' (carrier 'H2'), Bus 'dri_solid', Bus 'steel',
    Bus 'heat_duty' (carrier 'heat');
    Link 'electrolyser' (ac_bus -> h2_bus); Link 'h2_to_dri' (h2_bus -> dri_reductant);
    Link 'dri_plant' (dri_reductant + ac_bus -> dri_solid, draws heat_duty);
    optional Store 'dri_pile' on dri_solid;
    Link 'eaf' (dri_solid + ac_bus -> steel);
    optional Store 'eaf_campaign' on steel;
    Link 'electric_heater' (ac_bus -> heat_duty, extendable, capex);
    Link 'h2_burner'       (h2_bus -> heat_duty, extendable, capex);
    Load 'steel_offtake' on steel (constant).

    In dual_fuel mode additionally: Bus 'ng', Carrier 'gas', Generator 'ng_supply'
    (deal price; capped to ng_annual_volume_pj if set), optional Generator
    'ng_supply_spot' (uncapped, ng_spot_price_per_gj — only when a deal cap is
    set), Link 'dri_plant_gas' (ng -> dri_solid, supplies heat_duty via
    reformer burners).

    The heat_duty bus coordinates reducing-gas preheat (0.90 MWh_thermal/t DRI).
    Supply options compete on levelised $/MWh_heat: NG reformer self-heat (free,
    bundled in ng_intensity), H2 combustion burner (cheap capex, 2×-ish electricity
    via electrolyser losses), and electric resistance heater (high efficiency,
    higher capex). The solver sizes each and picks dispatch per snapshot. Heat
    must balance per-snapshot — no thermal storage modelled (see README §11).
    EAF off-gas waste heat is not piped to the DRI shaft (no operating plant
    does this); it leaves via the EAF stack.

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
    for carrier in ("DRI_solid", "steel", "heat"):
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
    # heat_duty: thermal bus for reducing-gas preheat. Sinks: dri_plant (H2 path)
    # via efficiency3. Sources: dri_plant_gas (reformer burners), electric_heater,
    # h2_burner. Heat must balance per-snapshot — no thermal storage modelled.
    # See README §11 (thermal storage as an unmodelled optimisation lever) and
    # project RESEARCH.md §3.
    if "heat_duty" not in network.buses.index:
        network.add("Bus", "heat_duty", carrier="heat")

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
    # bus0: dri_reductant [MWh_H2]; bus1: dri_solid [t DRI = MW];
    # bus2: ac_bus [MWh_el aux]; bus3: heat_duty [MWh_thermal for reducing-gas preheat]
    # efficiency  = 1 / h2_intensity_mwh_per_t  (t DRI per MWh_H2)
    # efficiency2 = -dri_energy_mwh_per_t × dri_eff  (plant auxiliaries only —
    #               compressors, fans, controls ~0.1 MWh_el/t DRI; NO embedded
    #               heater load, that's now a separate link on heat_duty bus).
    # efficiency3 = -heat_per_t_dri × dri_eff  (heat drawn from heat_duty bus
    #               per MWh_H2 input; equals -0.90/tDRI of thermal preheat).
    dri_eff = 1.0 / h2_intensity_mwh_per_t  # t DRI per MWh_H2
    dri_aux_eff2 = -dri_energy_mwh_per_t * dri_eff  # MWh_el per MWh_H2
    dri_heat_eff3 = -heat_per_t_dri * dri_eff       # MWh_heat per MWh_H2

    annual_dri_t = annual_steel_mt * 1e6
    dri_total_capex = dri_capex_per_t_yr * annual_dri_t
    dri_cc = annuitise(dri_total_capex, wacc, dri_lifetime_years)

    # Shaft capacity = avg_dri_t_per_h × 2.0 (oversize factor). Kept here so the
    # gas-path link can be sized to match and the shared-shaft constraint below
    # can reference it by name.
    shaft_cap_t_per_h = avg_dri_t_per_h * 2.0

    # p_min_pu: in 100% H2 mode the H2 link IS the shaft, so dri_min_load is the
    # shaft must-run floor. In dual-fuel, either fuel can supply the shaft, so
    # we set H2 p_min_pu=0 and enforce the shaft must-run as a per-snapshot
    # constraint on (h2_out + gas_out) below.
    dri_plant_p_min_pu = 0.0 if dual_fuel else dri_min_load
    network.add(
        "Link",
        "dri_plant",
        bus0="dri_reductant",
        bus1="dri_solid",
        bus2=ac_bus,
        bus3="heat_duty",
        efficiency=dri_eff,
        efficiency2=dri_aux_eff2,
        efficiency3=dri_heat_eff3,
        p_nom=shaft_cap_t_per_h * h2_intensity_mwh_per_t,  # == avg_h2_mw * 2.0
        p_nom_min=avg_h2_mw if not dual_fuel else 0.0,  # must run at ≥avg only in pure-H2
        p_min_pu=dri_plant_p_min_pu,
        ramp_limit_up=dri_ramp_limit_up,
        ramp_limit_down=dri_ramp_limit_down,
        capital_cost=dri_cc,
        marginal_cost=0.5,
    )

    # ── Dual-fuel (NG) DRI path ──────────────────────────────────────────────
    # MIDREX Flex is one physical shaft that can run any NG / H2 blend (brochure
    # p.6-7, "Maintain full plant capacity across the full transition range").
    # Both reduction paths share the same shaft throughput, so:
    #   - dri_plant_gas.p_nom is pinned to match the shaft DRI-output ceiling
    #     (same t DRI/h as dri_plant); not extendable.
    #   - dri_plant_gas.capital_cost = 0 (shaft capex already on dri_plant).
    #   - A per-snapshot constraint (attached below as extra_functionality)
    #     enforces   -p1[dri_plant] + -p1[dri_plant_gas] <= shaft_cap_t_per_h
    #     so the combined DRI output can't exceed the single shaft's capacity.
    if dual_fuel:
        if "gas" not in network.carriers.index:
            network.add("Carrier", "gas")
        if "ng" not in network.buses.index:
            network.add("Bus", "ng", carrier="gas")

        # NG supply at a fixed $/MWh_NG price (LHV basis).
        # ng_price_per_gj [$/GJ] * 3.6 [GJ/MWh] = $/MWh_NG.
        # If `ng_annual_volume_pj` is set, the deal-gas generator is capped via
        # e_sum_max and a parallel spot-gas generator (ng_supply_spot) supplies
        # any above-cap demand at ng_spot_price_per_gj. This represents the
        # Santos foundation contract (20 PJ/yr) ending and the LP having to buy
        # spot gas (Asian LNG netback ~$22/GJ) thereafter.
        #
        # Carbon cost is charged on the *supply* generators (per MWh_NG fossil
        # input), not on the dri_plant_gas link, so that biomethane on the same
        # ng bus does not pay carbon. ng_carbon_mc is reused in dri_plant_gas
        # below for the link's marginal_cost (now 0).
        ng_carbon_mc_per_mwh_ng = (
            carbon_price_per_t_co2
            * co2_intensity_kg_per_t_dri
            / 1000.0
            / ng_intensity_mwh_per_t_dri
        )
        ng_supply_kwargs = dict(
            bus="ng",
            carrier="gas",
            p_nom_extendable=False,
            p_nom=1e5,
            marginal_cost=ng_price_per_gj * 3.6 + ng_carbon_mc_per_mwh_ng,
        )
        if ng_annual_volume_pj is not None:
            # 1 PJ = 277,777.78 MWh (LHV basis: GJ/3.6 MWh = MWh, ×1e6 GJ/PJ).
            ng_supply_kwargs["e_sum_max"] = ng_annual_volume_pj * 1e6 / 3.6
        network.add("Generator", "ng_supply", **ng_supply_kwargs)
        if ng_annual_volume_pj is not None:
            network.add(
                "Generator",
                "ng_supply_spot",
                bus="ng",
                carrier="gas",
                p_nom_extendable=False,
                p_nom=1e5,
                marginal_cost=ng_spot_price_per_gj * 3.6 + ng_carbon_mc_per_mwh_ng,
            )

        # Biomethane: zero combustion CO2 (NGER scope-1 biogenic; see
        # BIOMETHANE.md §5). Sits on the same `ng` bus so dri_plant_gas
        # consumes it transparently. The annual volume cap (`e_sum_max`)
        # represents the SA-network biomethane available to a single Whyalla
        # offtaker via RGGOs in a given year.
        if biomethane_annual_volume_pj is not None and biomethane_annual_volume_pj > 0:
            network.add(
                "Generator",
                "biomethane_supply",
                bus="ng",
                carrier="gas",
                p_nom_extendable=False,
                p_nom=1e5,
                marginal_cost=biomethane_price_per_gj * 3.6,
                e_sum_max=biomethane_annual_volume_pj * 1e6 / 3.6,
            )

        # Gas DRI link: MWh_NG -> t DRI, with electrical aux on ac_bus and
        # reformer self-heat supplied to heat_duty bus.
        # efficiency  = 1 / ng_intensity_mwh_per_t_dri      (t DRI per MWh_NG)
        # efficiency2 = -dri_energy_mwh_per_t × ng_eff      (aux electricity)
        # efficiency3 = +heat_per_t_dri × ng_eff            (reformer burners
        #               self-heat the reducing gas; at 100% NG this supplies
        #               the full 0.90 MWh_thermal/tDRI duty).
        ng_eff = 1.0 / ng_intensity_mwh_per_t_dri  # t DRI per MWh_NG
        ng_aux_eff2 = -dri_energy_mwh_per_t * ng_eff
        ng_heat_eff3 = heat_per_t_dri * ng_eff

        # Carbon cost lives on the supply generators (ng_supply / ng_supply_spot),
        # not here, so biomethane (also on the `ng` bus) is not charged carbon.
        network.add(
            "Link",
            "dri_plant_gas",
            bus0="ng",
            bus1="dri_solid",
            bus2=ac_bus,
            bus3="heat_duty",
            efficiency=ng_eff,
            efficiency2=ng_aux_eff2,
            efficiency3=ng_heat_eff3,
            # Single shaft: size gas path so it can individually hit full DRI
            # throughput; joint constraint (see extra_functionality below)
            # prevents the two paths from summing above shaft capacity.
            p_nom=shaft_cap_t_per_h * ng_intensity_mwh_per_t_dri,
            p_nom_extendable=False,
            capital_cost=0.0,  # shared with dri_plant to avoid double-counting capex
            marginal_cost=0.0,
        )

    # ── Scrap supply (feeds EAF via the shared metallic-feed bus) ────────────
    # Commissions with the EAF; pre-DRI years carry 100 % scrap. Post-DRI the
    # LP picks the DRI/scrap mix subject to `scrap_max_share` (metallurgical
    # cap on residual copper for structural-grade steel).
    if enable_scrap:
        if "scrap" not in network.carriers.index:
            network.add("Carrier", "scrap")
        if "scrap_bus" not in network.buses.index:
            network.add("Bus", "scrap_bus", carrier="scrap")
        network.add(
            "Generator",
            "scrap_tier1_domestic",
            bus="scrap_bus",
            carrier="scrap",
            p_nom=scrap_tier1_capacity_t_per_yr / 8760.0,
            marginal_cost=scrap_tier1_price_per_t,
        )
        network.add(
            "Generator",
            "scrap_tier2_premium",
            bus="scrap_bus",
            carrier="scrap",
            p_nom=scrap_tier2_capacity_t_per_yr / 8760.0,
            marginal_cost=scrap_tier2_price_per_t,
        )
        # Scrap → dri_solid (metallic-feed) bus. 1 t scrap == 1 t metallic
        # equivalent into the EAF. No aux electricity or heat here (handled
        # by the EAF link, which charges eaf_mwh_per_t_steel regardless of
        # feed type).
        network.add(
            "Link",
            "scrap_to_metallic",
            bus0="scrap_bus",
            bus1="dri_solid",
            efficiency=1.0,
            p_nom=avg_steel_t_per_h * 3.0,
        )

    # ── Per-snapshot process constraints for extra_functionality ─────────────
    # Shaft capacity + must-run + NG/H2 share constraints (dual-fuel only).
    # Scrap-share cap attaches whenever the scrap pathway exists, regardless
    # of fuel mode.
    _ng_min_share = ng_min_share
    _min_h2_share = min_h2_share
    _shaft_min_load = dri_min_load
    _scrap_max_share = scrap_max_share

    def _process_constraints(net, _snapshots):
        link_p = net.model["Link-p"]  # dims: (snapshot, name)
        _eff_h2 = float(net.links.at["dri_plant", "efficiency"])
        _shaft_cap_out = float(net.links.at["dri_plant", "p_nom"]) * _eff_h2
        h2_out = link_p.sel(name="dri_plant") * _eff_h2

        has_gas = "dri_plant_gas" in net.links.index
        if has_gas:
            _eff_ng = float(net.links.at["dri_plant_gas", "efficiency"])
            gas_out = link_p.sel(name="dri_plant_gas") * _eff_ng
            dri_total = h2_out + gas_out
            # Shared single-shaft capacity ceiling.
            net.model.add_constraints(
                dri_total <= _shaft_cap_out,
                name="dri_shaft_capacity",
            )
        else:
            dri_total = h2_out

        # Shaft must-run (≥40 % of nominal to preserve burden). Trivially
        # satisfied when shaft_cap_out == 0 (pre-commissioning years).
        if _shaft_min_load > 0:
            net.model.add_constraints(
                dri_total >= _shaft_min_load * _shaft_cap_out,
                name="dri_shaft_must_run",
            )

        if has_gas and _ng_min_share > 0:
            # MIDREX Flex catalyst/gas-quality floor (brochure p.6-7).
            net.model.add_constraints(
                (1.0 - _ng_min_share) * gas_out - _ng_min_share * h2_out >= 0,
                name="dri_ng_min_share",
            )
        if has_gas and _min_h2_share > 0:
            # Abatement-curve policy knob; sweep to build $/tCO₂.
            net.model.add_constraints(
                (1.0 - _min_h2_share) * h2_out - _min_h2_share * gas_out >= 0,
                name="dri_min_h2_share",
            )

        # Scrap ≤ s × (scrap + DRI_total) → (1-s) scrap ≤ s × DRI_total.
        # With s=0.30 this gives scrap ≤ 0.429 × DRI_total per snapshot.
        # Metallurgical cap: EAF residual copper in scrap bounds structural-
        # grade steel production. Pre-2030 (shaft blocked) dri_total==0 so
        # this constraint is infeasible — caller must relax `scrap_max_share`
        # to 1.0 in scrap-only phase.
        if "scrap_to_metallic" in net.links.index and _scrap_max_share < 1.0:
            scrap_flow = link_p.sel(name="scrap_to_metallic")
            net.model.add_constraints(
                (1.0 - _scrap_max_share) * scrap_flow
                - _scrap_max_share * dri_total <= 0,
                name="scrap_max_share",
            )

    network._dri_shaft_constraint = _process_constraints

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
    # bus0: dri_solid [t DRI = MW]; bus1: steel [t steel = MW];
    # bus2: ac_bus [MWh electricity].
    # efficiency  = 1.0 (1 t DRI -> 1 t steel in bus-flow units)
    # efficiency2 = -eaf_mwh_per_t_steel (electricity input per t steel)
    # No connection to heat_duty — EAF off-gas leaves via the stack rather
    # than being piped to the DRI shaft (no operating DRI-EAF plant does this).
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

    # ── Electric resistance heater (facility_ac -> heat_duty) ────────────────
    # High efficiency (97%) but higher capex. Wins when heater runs many hours
    # and cheap electricity is abundant. Extendable; caller may pin p_nom_min
    # from prior-year build for monotone capacity trajectory.
    eh_cc = annuitise(
        electric_heater_capex_per_kw_th * 1000.0, wacc, electric_heater_lifetime_years
    )
    network.add(
        "Link",
        "electric_heater",
        bus0=ac_bus,
        bus1="heat_duty",
        efficiency=electric_heater_efficiency,
        p_nom_extendable=True,
        capital_cost=eh_cc,
    )

    # ── H2 combustion burner (facility_h2 -> heat_duty) ──────────────────────
    # Low capex (drop-in on existing MIDREX reformer housing) but ~1.6× worse
    # electric-to-heat efficiency end-to-end (via electrolyser losses). Wins for
    # part-time operation where capex dominates over running cost.
    hb_cc = annuitise(
        h2_burner_capex_per_kw_th * 1000.0, wacc, h2_burner_lifetime_years
    )
    network.add(
        "Link",
        "h2_burner",
        bus0=h2_bus,
        bus1="heat_duty",
        efficiency=h2_burner_efficiency,
        p_nom_extendable=True,
        capital_cost=hb_cc,
    )

    # ── Waste-heat vent on heat_duty ─────────────────────────────────────────
    # Free sink for surplus reformer self-heat. The NG path co-produces heat
    # (efficiency3 > 0) tied to its DRI throughput; if the LP runs the gas
    # path harder than the shaft preheat duty needs, the surplus has to go
    # somewhere — physically it leaves via the stack. Heat must balance
    # per-snapshot (no thermal storage), so this vent makes the LP feasible.
    network.add(
        "Generator",
        "heat_vent",
        bus="heat_duty",
        carrier="heat",
        p_nom=1e5,
        sign=-1,
        marginal_cost=0.0,
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
