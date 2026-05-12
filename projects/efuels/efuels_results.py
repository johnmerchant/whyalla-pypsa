"""Results extraction for the Whyalla e-fuels model (refactored for whyalla-pypsa).

LCOM (AUD/t MeOH) and LCOF (AUD/t diesel-equivalent, energy-weighted across ASF
products) are extracted from a solved PyPSA network built by process_chain.attach_efuels().

Bug fixed: diesel LHV previously used MeOH LHV as proxy (~2.15× error).
Now uses DIESEL_LHV_MWH_PER_T = 11.89 MWh/t per efuels_physics constants.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pypsa

from whyalla_pypsa import levelised_cost
from whyalla_pypsa.config import WACCOverlay

from efuels_physics import (
    MEOH_LHV_MWH_PER_T,
    DIESEL_LHV_MWH_PER_T,
    NAPHTHA_LHV_MWH_PER_T,
    KERO_LHV_MWH_PER_T,
    WAX_LHV_MWH_PER_T,
    asf_mass_fractions,
)

_CO2_TRANCHE_PREFIXES = ("co2_steelworks", "co2_nyrstar", "co2_santos_moomba",
                          "co2_adbri_cement", "co2_doc_spencer_gulf",
                          "co2_dac", "co2_supply")

_PRODUCT_LHV: dict[str, float] = {
    "naphtha": NAPHTHA_LHV_MWH_PER_T,
    "kero":    KERO_LHV_MWH_PER_T,
    "diesel":  DIESEL_LHV_MWH_PER_T,
    "wax":     WAX_LHV_MWH_PER_T,
}

# Biofuel upgrading Links. Map link_name → {product: bus_slot_index} so
# the LP's p_N series can be summed into per-product tonnes alongside
# the existing refinery_{product} outputs. biomass_gasification is
# captured via the existing MeOH synth path (it emits biogenic H₂+CO₂
# onto shared buses) — NOT listed here.
_BIOFUEL_PRODUCT_LINKS: dict[str, dict[str, int]] = {
    "htl_upgrading_steelworks":    {"diesel": 1, "kero": 2, "naphtha": 3},
    "htl_upgrading_port_bonython": {"diesel": 1, "kero": 2, "naphtha": 3},
    "hefa_upgrading":              {"kero":   1, "diesel": 2, "naphtha": 3},
    "pyrolysis_upgrading":         {"diesel": 1, "kero": 2, "naphtha": 3},
}

# Biofuel Links that contribute capex but don't output directly on
# product buses (routed through existing MeOH synth via bus1=h2, bus2=co2).
_BIOFUEL_UPSTREAM_LINKS = ("biomass_gasification",)


def _opt_capacity(n: pypsa.Network, component: str, name: str) -> float:
    tbl = getattr(n, component)
    if name not in tbl.index:
        return 0.0
    col = "e_nom_opt" if component == "stores" else "p_nom_opt"
    return float(tbl.at[name, col]) if col in tbl.columns else 0.0


def extract_lcom_lcof(network: pypsa.Network, config) -> dict:
    """Post-process solved network.

    Returns:
        lcom_per_t_meoh              -- AUD/t MeOH (if synthesis built)
        lcof_per_t_diesel_equivalent -- blended across ASF products, energy-weighted
        per_product_revenue          -- AUD/yr per product
        ely_mw, h2_store_mwh, synth_mw, ...
    """
    n = network
    snap_w = n.snapshot_weightings.generators.iloc[0]

    # ── Electrolyser ──────────────────────────────────────────────────────
    ely_mw = _opt_capacity(n, "links", "electrolyser")
    ely_p = n.links_t.p0.get("electrolyser", pd.Series(0.0, index=n.snapshots))
    ely_mwh = float(ely_p.sum()) * snap_w
    ely_cf = (ely_mwh / (ely_mw * 8760)) if ely_mw > 0 else 0.0

    # ── MeOH synthesis ────────────────────────────────────────────────────
    synth_mw = _opt_capacity(n, "links", "meoh_synthesis")
    # PyPSA sign convention: p1 is negative when flow is delivered INTO bus1,
    # so negate to get a positive production quantity.
    meoh_p1 = n.links_t.p1.get("meoh_synthesis", pd.Series(0.0, index=n.snapshots))
    meoh_mwh = float((-meoh_p1).sum()) * snap_w
    meoh_tonnes = meoh_mwh / MEOH_LHV_MWH_PER_T

    # ── CO2 dispatch ──────────────────────────────────────────────────────
    co2_by_source: dict[str, float] = {}
    for gname in n.generators.index:
        if any(gname.startswith(p) for p in _CO2_TRANCHE_PREFIXES):
            p_series = n.generators_t.p.get(gname, pd.Series(0.0, index=n.snapshots))
            co2_by_source[gname] = float(p_series.sum()) * snap_w
    co2_tonnes = sum(co2_by_source.values())
    if co2_tonnes > 0:
        co2_blended_price = sum(
            co2_by_source[g] * n.generators.at[g, "marginal_cost"]
            for g in co2_by_source
        ) / co2_tonnes
    else:
        co2_blended_price = float("nan")

    # ── Storage sizes ─────────────────────────────────────────────────────
    h2_store_mwh = _opt_capacity(n, "stores", "h2_store")
    meoh_store_mwh = _opt_capacity(n, "stores", "meoh_storage")
    co2_store_t = _opt_capacity(n, "stores", "co2_storage")

    # ── Per-product revenue and quantities ────────────────────────────────
    per_product_revenue: dict[str, float] = {}
    product_energy_mwh: dict[str, float] = {}
    product_tonnes: dict[str, float] = {}

    # Product-bus output aggregation:
    #   • naphtha/kero/diesel come through shared_hcr_{product} now (which
    #     aggregates MeOH-refinery, pyrolysis, HEFA, HTL intermediate
    #     streams through one shared hydrocracker per product).
    #   • wax is the residual post-FT specialty product — still delivered
    #     directly by refinery_wax.
    for product, lhv in _PRODUCT_LHV.items():
        tonnes_annual = 0.0
        if product == "wax":
            # Wax is delivered directly from the single refinery Link on
            # bus4 (not via shared HCR).
            if "refinery" in n.links.index and hasattr(n.links_t, "p4"):
                p4 = n.links_t.p4.get("refinery",
                                       pd.Series(0.0, index=n.snapshots))
                tonnes_annual += float((-p4).sum()) * snap_w
        else:
            hcr_name = f"shared_hcr_{product}"
            if hcr_name in n.links.index:
                p1 = n.links_t.p1.get(hcr_name,
                                       pd.Series(0.0, index=n.snapshots))
                tonnes_annual += float((-p1).sum()) * snap_w

        if tonnes_annual == 0.0:
            continue
        product_tonnes[product] = tonnes_annual
        product_energy_mwh[product] = tonnes_annual * lhv

        export_gen = f"{product}_export"
        if export_gen in n.generators.index:
            price_per_t = abs(n.generators.at[export_gen, "marginal_cost"])
            # mc = -price_per_t; revenue = price_per_t × dispatch × snap_w (annual tonnes)
            per_product_revenue[product] = (
                n.generators_t.p.get(export_gen, pd.Series(0.0, index=n.snapshots))
                .abs().sum() * snap_w * price_per_t
            )

    # ── LCOM ──────────────────────────────────────────────────────────────
    # Annualised CAPEX from PyPSA-stored capital_cost × p_nom_opt / e_nom_opt.
    def _capex_annual(component: str, name: str) -> float:
        tbl = getattr(n, component)
        if name not in tbl.index:
            return 0.0
        cap_col = "e_nom_opt" if component == "stores" else "p_nom_opt"
        cap = float(tbl.at[name, cap_col]) if cap_col in tbl.columns else 0.0
        return cap * float(tbl.at[name, "capital_cost"])

    annual_capex = sum(_capex_annual(c, nm) for c, nm in [
        ("links",     "electrolyser"),
        ("links",     "meoh_synthesis"),
        ("links",     "electric_heater"),
        ("links",     "h2_burner"),
        ("links",     "cst_steam_turbine"),
        ("generators","cst_solar_thermal"),
        ("stores",    "h2_store"),
        ("stores",    "meoh_storage"),
        ("stores",    "co2_storage"),
    ])

    # Power cost: sum AC draw across all links that consume from facility_ac.
    # Electrolyser draws on bus0; electric_heater draws on bus0; meoh_synthesis
    # draws aux on bus3 (efficiency3<0). Each weighted by the AC bus marginal
    # price so renewable + grid dispatch cost is captured consistently.
    ac_bus_candidates = [b for b in n.buses.index if "facility_ac" in b or b == "facility_ac"]
    if ac_bus_candidates:
        ac_price = n.buses_t.marginal_price.get(ac_bus_candidates[0],
                                                 pd.Series(0.0, index=n.snapshots))
        power_cost = float((ely_p * ac_price).sum()) * snap_w
        # Electric heater (process heat — AC → heat)
        if "electric_heater" in n.links.index:
            heater_p = n.links_t.p0.get("electric_heater",
                                         pd.Series(0.0, index=n.snapshots))
            power_cost += float((heater_p * ac_price).sum()) * snap_w
        # MeOH synth auxiliary electricity (bus3 draw; p3 is negative when
        # link draws, so negate to positive consumption)
        if "meoh_synthesis" in n.links.index and hasattr(n.links_t, "p3"):
            synth_p3 = n.links_t.p3.get("meoh_synthesis",
                                         pd.Series(0.0, index=n.snapshots))
            power_cost += float((-synth_p3 * ac_price).sum()) * snap_w
    else:
        power_cost = 0.0

    co2_variable_cost = sum(
        co2_by_source[g] * n.generators.at[g, "marginal_cost"]
        for g in co2_by_source
    )
    total_variable = power_cost + co2_variable_cost

    lcom = (annual_capex + total_variable) / meoh_tonnes if meoh_tonnes > 0 else float("nan")

    # ── LCOF: blended across ASF products, energy-weighted ────────────────
    # Also add refinery CAPEX to the product-side cost.
    # LCOF_blend = (total_system_cost_allocated_to_products) / (sum_energy_output_MWh)
    # expressed as AUD per MWh_diesel_equivalent, then ×DIESEL_LHV → AUD/t.
    refinery_capex = _capex_annual("links", "refinery")
    # Shared hydrocracker — one Link per non-wax product, sized at the LP's
    # peak aggregate intermediate throughput. Belongs on the product side.
    for product in ("naphtha", "kero", "diesel"):
        refinery_capex += _capex_annual("links", f"shared_hcr_{product}")
    # Biofuel pathway capex also on the product side (these are the
    # conditioning Links — feedstock-specific pre-processing).
    for biof_name in (*_BIOFUEL_PRODUCT_LINKS, *_BIOFUEL_UPSTREAM_LINKS):
        refinery_capex += _capex_annual("links", biof_name)
    total_energy = sum(product_energy_mwh.values())
    lcof_per_mwh: float
    if total_energy > 0:
        lcof_per_mwh = (annual_capex + refinery_capex + total_variable) / total_energy
    else:
        lcof_per_mwh = float("nan")
    lcof_per_t_diesel_equivalent = lcof_per_mwh * DIESEL_LHV_MWH_PER_T

    # ── Heat + CST dispatch readouts ─────────────────────────────────────
    cst_mw  = _opt_capacity(n, "generators", "cst_solar_thermal")
    cst_mwh = 0.0
    if "cst_solar_thermal" in n.generators.index:
        cst_p = n.generators_t.p.get("cst_solar_thermal",
                                     pd.Series(0.0, index=n.snapshots))
        cst_mwh = float(cst_p.sum()) * snap_w
    turb_mw = _opt_capacity(n, "links", "cst_steam_turbine")
    turb_mwh = 0.0
    if "cst_steam_turbine" in n.links.index:
        turb_p1 = n.links_t.p1.get("cst_steam_turbine",
                                    pd.Series(0.0, index=n.snapshots))
        turb_mwh = float((-turb_p1).sum()) * snap_w
    eh_mw  = _opt_capacity(n, "links", "electric_heater")
    eh_mwh = 0.0
    if "electric_heater" in n.links.index:
        eh_p = n.links_t.p0.get("electric_heater",
                                 pd.Series(0.0, index=n.snapshots))
        eh_mwh = float(eh_p.sum()) * snap_w
    hb_mw  = _opt_capacity(n, "links", "h2_burner")
    hb_mwh = 0.0
    if "h2_burner" in n.links.index:
        hb_p = n.links_t.p0.get("h2_burner",
                                 pd.Series(0.0, index=n.snapshots))
        hb_mwh = float(hb_p.sum()) * snap_w

    # Refinery capacities per product (MW MeOH input). Useful for
    # capital-works reporting — the chart converts via capex_per_mw_meoh.
    # Single refinery Link — its p_nom_opt is MW MeOH input. Report the
    # single capacity plus the per-product annual output inferred from
    # dispatch for reporting compatibility.
    refinery_mw_meoh = _opt_capacity(n, "links", "refinery")
    refinery_caps_mw_meoh = {"aggregate": refinery_mw_meoh}
    # Shared hydrocracker capacities (t/hr intermediate input) per product.
    shared_hcr_caps_t_per_hr = {
        p: _opt_capacity(n, "links", f"shared_hcr_{p}")
        for p in ("naphtha", "kero", "diesel")
    }

    return {
        "lcom_per_t_meoh": lcom,
        "lcof_per_t_diesel_equivalent": lcof_per_t_diesel_equivalent,
        "per_product_revenue": per_product_revenue,
        "ely_mw": ely_mw,
        "ely_cf": ely_cf,
        "h2_store_mwh": h2_store_mwh,
        "synth_mw": synth_mw,
        "meoh_tonnes": meoh_tonnes,
        "meoh_store_mwh": meoh_store_mwh,
        "co2_tonnes": co2_tonnes,
        "co2_blended_price": co2_blended_price,
        "co2_by_source": co2_by_source,
        "co2_store_t": co2_store_t,
        "product_tonnes": product_tonnes,
        "product_energy_mwh": product_energy_mwh,
        "annual_capex_process": annual_capex,
        "annual_power_cost": power_cost,
        "annual_co2_cost": co2_variable_cost,
        "cst_mw": cst_mw,
        "cst_mwh_per_yr": cst_mwh,
        "cst_turbine_mw_el": turb_mw,
        "cst_turbine_mwh_el_per_yr": turb_mwh,
        "electric_heater_mw_th": eh_mw,
        "electric_heater_mwh_per_yr": eh_mwh,
        "h2_burner_mw_th": hb_mw,
        "h2_burner_mwh_h2_per_yr": hb_mwh,
        "refinery_caps_mw_meoh": refinery_caps_mw_meoh,
        "shared_hcr_caps_t_per_hr": shared_hcr_caps_t_per_hr,
        "objective": float(n.objective) if hasattr(n, "objective") else float("nan"),
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
