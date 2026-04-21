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
                          "co2_adbri_cement", "co2_dac", "co2_supply")

_PRODUCT_LHV: dict[str, float] = {
    "naphtha": NAPHTHA_LHV_MWH_PER_T,
    "kero":    KERO_LHV_MWH_PER_T,
    "diesel":  DIESEL_LHV_MWH_PER_T,
    "wax":     WAX_LHV_MWH_PER_T,
}


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

    for product, lhv in _PRODUCT_LHV.items():
        link_name = f"refinery_{product}"
        if link_name not in n.links.index:
            continue
        # p1 is negative by PyPSA sign convention (flow delivered into bus1),
        # so negate to get a positive production quantity.
        p1 = n.links_t.p1.get(link_name, pd.Series(0.0, index=n.snapshots))
        tonnes_annual = float((-p1).sum()) * snap_w
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
        ("links",  "electrolyser"),
        ("links",  "meoh_synthesis"),
        ("stores", "h2_store"),
        ("stores", "meoh_storage"),
        ("stores", "co2_storage"),
    ])

    # Power cost (electrolyser only; price from AC bus marginal price)
    ac_bus_candidates = [b for b in n.buses.index if "facility_ac" in b or b == "facility_ac"]
    if ac_bus_candidates:
        ac_price = n.buses_t.marginal_price.get(ac_bus_candidates[0],
                                                 pd.Series(0.0, index=n.snapshots))
        power_cost = float((ely_p * ac_price).sum()) * snap_w
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
    refinery_capex = sum(_capex_annual("links", f"refinery_{p}") for p in _PRODUCT_LHV)
    total_energy = sum(product_energy_mwh.values())
    lcof_per_mwh: float
    if total_energy > 0:
        lcof_per_mwh = (annual_capex + refinery_capex + total_variable) / total_energy
    else:
        lcof_per_mwh = float("nan")
    lcof_per_t_diesel_equivalent = lcof_per_mwh * DIESEL_LHV_MWH_PER_T

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
