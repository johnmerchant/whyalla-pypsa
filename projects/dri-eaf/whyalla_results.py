"""Results extraction for the Whyalla H2-DRI-EAF model.

Reads from a solved pypsa.Network produced by run.main().
LCOH denominator: annual H2 production in kg (kg = MWh_H2 * 1000 / 33.33).
LCOS denominator: annual steel tonnes (= steel_offtake.p_set * 8760).

LCOH numerator includes allocated grid-import cost: the primary
`lcoh_per_kg` adds the electrolyser's share of net boundary cost
(imports × grid_ac shadow price − exports × grid_ac shadow price) to
the facility-asset annuity. Without this allocation, LCOH is biased
low under sa_dispatch (facility under-builds wind/solar because it
can import cheap, and the import cost doesn't otherwise flow through).
The assets-only number is still exposed as
`lcoh_facility_assets_only_per_kg` for reference.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypsa

from whyalla_pypsa import levelised_cost, WACCOverlay, crf
from whyalla_pypsa.config import FacilityConfig

# H2 LHV
H2_LHV_MWH_PER_T: float = 33.33


def extract_lcoh_lcos(
    network: pypsa.Network,
    config: FacilityConfig,
    *,
    ng_intensity_mwh_per_t_dri: float = 3.0,
    co2_intensity_kg_per_t_dri: float = 560.0,
) -> dict:
    """Post-process solved network -> {lcoh_per_kg, lcos_per_t_steel, ...}.

    Uses component-specific WACCs from config.wacc_overlay where applicable.

    `ng_intensity_mwh_per_t_dri` and `co2_intensity_kg_per_t_dri` must match
    the values passed to `attach_dri_eaf` — they're used here to back out
    tCO2 emissions from the solved gas flow and to compute the all-gas
    counterfactual for `emissions_saved_tCO2`.
    """
    snap_w = network.snapshot_weightings.generators.iloc[0]
    _zero = pd.Series(0.0, index=network.snapshots)

    overlay: WACCOverlay = config.wacc_overlay

    # ── Electrolyser ──────────────────────────────────────────────────────
    ely_mw = network.links.at["electrolyser", "p_nom_opt"]
    ely_flow = network.links_t.p0.get("electrolyser", _zero)
    total_ely_mwh = float((ely_flow * snap_w).sum())

    # H2 produced (MWh_LHV at facility_h2 bus).
    # PyPSA sign convention: p1 is negative when flow is delivered INTO bus1,
    # so negate to get a positive production quantity.
    h2_out = network.links_t.p1.get("electrolyser", _zero)
    total_h2_mwh = float((-h2_out * snap_w).sum())
    total_h2_kg = total_h2_mwh * 1000.0 / H2_LHV_MWH_PER_T

    # ── H2 store ──────────────────────────────────────────────────────────
    h2_store_mwh = float(network.stores.at["h2_store", "e_nom_opt"]) if "h2_store" in network.stores.index else 0.0

    # ── Steel production ──────────────────────────────────────────────────
    # steel_offtake p_set == avg t/h == MW on steel bus
    if "steel_offtake" in network.loads.index:
        steel_rate_t_per_h = float(network.loads.at["steel_offtake", "p_set"])
    else:
        steel_rate_t_per_h = 0.0
    annual_steel_t = steel_rate_t_per_h * 8760.0

    # ── Electrolyser capacity factor ──────────────────────────────────────
    ely_cf = (total_ely_mwh / (ely_mw * 8760.0)) if ely_mw > 0 else 0.0

    # ── Grid import price (facility_ac marginal price weighted by ely dispatch)
    fac_price = network.buses_t.marginal_price.get("facility_ac", _zero)
    ely_realised_price = (
        float((ely_flow * fac_price * snap_w).sum() / total_ely_mwh)
        if total_ely_mwh > 0 else float("nan")
    )
    avg_fac_price = float(fac_price.mean())

    # ── EAF + DRI plant aux electricity draw ─────────────────────────────
    # bus2 flows are stored in links_t.p2; positive when efficiency2<0 (link
    # drawing FROM bus2). Both eaf and dri_plant pull aux electricity from
    # facility_ac this way.
    _links_p2 = getattr(network.links_t, "p2", pd.DataFrame())
    if "eaf" in _links_p2.columns:
        eaf_elec = _links_p2["eaf"].abs()
    else:
        eaf_elec = _zero
    total_eaf_mwh = float((eaf_elec * snap_w).sum())

    if "dri_plant" in _links_p2.columns:
        dri_aux_elec = _links_p2["dri_plant"].abs()
    else:
        dri_aux_elec = _zero
    total_dri_aux_mwh = float((dri_aux_elec * snap_w).sum())

    # EAF realised electricity price (weighted by dispatch on facility_ac).
    eaf_realised_price = (
        float((eaf_elec * fac_price * snap_w).sum() / total_eaf_mwh)
        if total_eaf_mwh > 0 else float("nan")
    )

    # ── Gas DRI path (dual-fuel) and emissions ────────────────────────────
    # total_gas_mwh = MWh_NG consumed at dri_plant_gas.bus0. Emissions scale
    # linearly with gas throughput: (co2_intensity/ng_intensity) kgCO2/MWh_NG.
    # Counterfactual = all-gas DRI: annual_steel_t × co2_intensity / 1000.
    if "dri_plant_gas" in network.links.index:
        gas_flow = network.links_t.p0.get("dri_plant_gas", _zero)
        total_gas_mwh = float((gas_flow * snap_w).sum())
    else:
        total_gas_mwh = 0.0

    co2_per_mwh_ng_t = co2_intensity_kg_per_t_dri / ng_intensity_mwh_per_t_dri / 1000.0
    emissions_tCO2 = total_gas_mwh * co2_per_mwh_ng_t
    counterfactual_tCO2 = annual_steel_t * co2_intensity_kg_per_t_dri / 1000.0
    emissions_saved_tCO2 = counterfactual_tCO2 - emissions_tCO2

    # H2 fraction on thermal (MWh_LHV) basis at the DRI reductant inlet.
    h2_fraction = (
        total_h2_mwh / (total_h2_mwh + total_gas_mwh)
        if (total_h2_mwh + total_gas_mwh) > 0 else 0.0
    )

    # ── LCOH via levelised_cost helper ───────────────────────────────────
    # Electrolyser capex is not stored in FacilityConfig; back-calculate from
    # the capital_cost embedded in the network by process_chain.py.
    ely_wacc_cw = overlay.electrolyser
    ely_cc_pypsa = float(network.links.at["electrolyser", "capital_cost"]) if "electrolyser" in network.links.index else 0.0
    # capital_cost in PyPSA = annuity per MW/yr; reverse to total capex per MW
    ely_crf_val = crf(ely_wacc_cw.wacc, ely_wacc_cw.lifetime_years)
    ely_capex_per_mw_reconstructed = ely_cc_pypsa / ely_crf_val if ely_crf_val > 0 else 0.0

    h2_store_capex_per_mwh = config.h2_storage.cost.capex_per_unit

    lc_result = levelised_cost(
        network,
        overlay=overlay,
        component_capex_per_unit={
            "electrolyser": ely_capex_per_mw_reconstructed,
            "h2_store": h2_store_capex_per_mwh,
            "wind": config.wind.cost.capex_per_unit * 1000.0,
            "solar": config.solar.cost.capex_per_unit * 1000.0,
        },
        component_overlay_key={
            "electrolyser": "electrolyser",
            "h2_store": "h2_storage",
            "wind": "wind",
            "solar": "solar",
        },
        annual_product=total_h2_kg,
        product_unit="kg_H2",
    )
    lcoh_assets_only_per_kg = lc_result["lcx_per_unit"]

    # ── LCOS (objective basis) — valid only under rldc_merit ───────────────
    # network.objective is total annualised system cost. Under rldc_merit the
    # network only contains facility items, so objective / steel is LCOS.
    # Under sa_dispatch the objective also pays for all SA-wide thermal +
    # slack generation, so this number is polluted.
    lcos_objective_basis = (
        network.objective / annual_steel_t if annual_steel_t > 0 else float("nan")
    )

    # ── LCOS (facility basis) — comparable across grid modes ───────────────
    # Sum only facility-owned capex annuities + facility opex + the net
    # electricity cost at the grid boundary (valued at the subregion AC
    # shadow price). PyPSA-WACC basis (not overlay) — consistent with the
    # objective-basis figure so they agree under rldc_merit.
    _facility_links = [
        "electrolyser", "h2_to_dri", "dri_plant", "dri_plant_gas",
        "eaf", "battery_charge", "battery_discharge",
        "grid_import", "grid_export",
    ]
    _facility_gens = ["wind", "solar"]
    _facility_stores = ["battery_store", "h2_store", "dri_pile", "eaf_campaign"]

    # Only sum capex for extendable components — PyPSA excludes fixed-size
    # components from the objective, so including them here would add ghost
    # capex (e.g. dri_plant / eaf have stored capital_cost but fixed p_nom
    # and never enter the LP). Opex (marginal_cost) applies regardless.
    facility_capex_annuity = 0.0
    facility_opex = 0.0
    for name in _facility_links:
        if name in network.links.index:
            if bool(network.links.at[name, "p_nom_extendable"]):
                facility_capex_annuity += float(
                    network.links.at[name, "p_nom_opt"]
                    * network.links.at[name, "capital_cost"]
                )
            mc = network.links.at[name, "marginal_cost"]
            if mc:
                p0 = network.links_t.p0.get(name, _zero)
                facility_opex += float((p0 * mc * snap_w).sum())
    for name in _facility_gens:
        if name in network.generators.index:
            if bool(network.generators.at[name, "p_nom_extendable"]):
                facility_capex_annuity += float(
                    network.generators.at[name, "p_nom_opt"]
                    * network.generators.at[name, "capital_cost"]
                )
            mc = network.generators.at[name, "marginal_cost"]
            if mc:
                p = network.generators_t.p.get(name, _zero)
                facility_opex += float((p * mc * snap_w).sum())
    for name in _facility_stores:
        if name in network.stores.index:
            if bool(network.stores.at[name, "e_nom_extendable"]):
                facility_capex_annuity += float(
                    network.stores.at[name, "e_nom_opt"]
                    * network.stores.at[name, "capital_cost"]
                )

    # Net cost at the grid_ac boundary: facility buys at grid_ac shadow price
    # through grid_import (link bus0=grid_ac), sells back through grid_export
    # (link bus1=grid_ac; p1 < 0 when flowing into bus1).
    grid_ac = f"{config.grid.subregion}_ac"
    grid_price = network.buses_t.marginal_price.get(grid_ac, _zero)
    imp_p0 = network.links_t.p0.get("grid_import", _zero) if "grid_import" in network.links.index else _zero
    exp_p1 = network.links_t.p1.get("grid_export", _zero) if "grid_export" in network.links.index else _zero
    net_boundary_cost = float(
        (imp_p0 * grid_price * snap_w).sum()
        - (-exp_p1 * grid_price * snap_w).sum()
    )

    lcos_facility_basis = (
        (facility_capex_annuity + facility_opex + net_boundary_cost) / annual_steel_t
        if annual_steel_t > 0 else float("nan")
    )

    # ── LCOH with allocated grid-import cost ──────────────────────────────
    # Split net_boundary_cost between H2 and steel by each load's share of
    # total facility electricity consumption (ely vs eaf+dri_aux). Adding
    # the H2 share to the assets-only LCOH makes the metric mode-invariant —
    # under sa_dispatch the facility shifts cost from wind/solar capex to
    # imports, which the assets-only LCOH doesn't see.
    facility_load_mwh = total_ely_mwh + total_eaf_mwh + total_dri_aux_mwh
    ely_load_share = (
        total_ely_mwh / facility_load_mwh if facility_load_mwh > 0 else 0.0
    )
    boundary_cost_allocated_h2 = net_boundary_cost * ely_load_share
    lcoh_per_kg = (
        lcoh_assets_only_per_kg + boundary_cost_allocated_h2 / total_h2_kg
        if total_h2_kg > 0 else float("nan")
    )

    return {
        "lcoh_per_kg": lcoh_per_kg,
        "lcoh_facility_assets_only_per_kg": lcoh_assets_only_per_kg,
        "lcoh_boundary_cost_allocated": boundary_cost_allocated_h2,
        "ely_load_share": ely_load_share,
        "lcos_per_t_steel": lcos_facility_basis,
        "lcos_objective_basis": lcos_objective_basis,
        "lcos_facility_capex_annuity": facility_capex_annuity,
        "lcos_facility_opex": facility_opex,
        "lcos_net_boundary_cost": net_boundary_cost,
        "ely_mw": ely_mw,
        "h2_store_mwh": h2_store_mwh,
        "annual_h2_mwh": total_h2_mwh,
        "annual_h2_kg": total_h2_kg,
        "annual_steel_t": annual_steel_t,
        "ely_cf": ely_cf,
        "ely_realised_price": ely_realised_price,
        "avg_fac_price": avg_fac_price,
        "total_ely_mwh": total_ely_mwh,
        "total_eaf_mwh": total_eaf_mwh,
        "total_dri_aux_mwh": total_dri_aux_mwh,
        "eaf_realised_price": eaf_realised_price,
        "eaf_flexibility_premium": avg_fac_price - eaf_realised_price,
        "total_gas_mwh": total_gas_mwh,
        "h2_fraction": h2_fraction,
        "emissions_tCO2": emissions_tCO2,
        "emissions_saved_tCO2": emissions_saved_tCO2,
        "counterfactual_tCO2": counterfactual_tCO2,
        "flexibility_premium": avg_fac_price - ely_realised_price,
        "objective": network.objective,
        "lcoh_detail": lc_result,
    }


def extract_bus_prices(
    n: pypsa.Network,
    bus_names: list[str],
    outpath: Path | str,
) -> pd.DataFrame:
    """Save marginal price timeseries for bus_names to outpath (parquet)."""
    prices = n.buses_t.marginal_price[bus_names]
    outpath = Path(outpath)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    prices.to_parquet(outpath)
    return prices
