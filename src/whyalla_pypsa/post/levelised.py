"""Unified LCOH/LCOS/LCOF extraction from a solved PyPSA network.

Recomputes levelised cost using *component-specific* WACCs on the PyPSA
optimal capacities. This is deliberately decoupled from the `pypsa_wacc`
used inside the optimisation — we use a single WACC for dispatch-feasible
capex-ordering and a per-component WACC overlay for final cost reporting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from whyalla_pypsa.config import ComponentWACC, WACCOverlay
from whyalla_pypsa.post.annuitise import annuitise


def _overlay_for(overlay: WACCOverlay, key: str) -> ComponentWACC:
    if hasattr(overlay, key):
        return getattr(overlay, key)
    if key in overlay.extra:
        return overlay.extra[key]
    return overlay.default


def _component_capacity(network, component_name: str) -> float:
    """Return optimal capacity (MW for power, MWh for energy) or 0."""
    for attr, col in (
        ("generators", "p_nom_opt"),
        ("links", "p_nom_opt"),
        ("stores", "e_nom_opt"),
        ("storage_units", "p_nom_opt"),
    ):
        df = getattr(network, attr, None)
        if df is not None and component_name in df.index:
            return float(df.at[component_name, col])
    return 0.0


def _component_variable_cost(network, component_name: str) -> float:
    """Annual variable (marginal × dispatch) cost for one component, if solved."""
    # Generators dispatch
    gens_t = getattr(network, "generators_t", None)
    if gens_t is not None and component_name in getattr(network.generators, "index", []):
        p = gens_t.p.get(component_name) if hasattr(gens_t, "p") else None
        mc = network.generators.at[component_name, "marginal_cost"]
        if p is not None:
            mc_series = mc if isinstance(mc, pd.Series) else pd.Series(mc, index=p.index)
            # snapshot weightings
            w = getattr(network, "snapshot_weightings", None)
            weights = w["generators"] if w is not None and "generators" in w else 1.0
            return float((p * mc_series * weights).sum())
    # Links / Stores variable costs are typically zero in this module.
    return 0.0


def levelised_cost(
    network,
    overlay: WACCOverlay,
    component_capex_per_unit: dict[str, float],
    component_overlay_key: dict[str, str],
    annual_product: float,
    product_unit: str = "MWh",
) -> dict[str, Any]:
    """Levelised cost using component-specific WACCs on PyPSA-optimal sizes.

    Parameters
    ----------
    network: a solved `pypsa.Network`.
    overlay: WACCOverlay supplying per-component WACC + lifetime.
    component_capex_per_unit: {component_name: capex_per_unit_AUD}.
        Units must match PyPSA's capacity unit for that component — per MW for
        generators/links, per MWh for stores.
    component_overlay_key: {component_name: overlay_attribute_name}.
        e.g. {"wind": "wind", "battery_store": "battery_energy"}.
    annual_product: annual useful output (MWh_el, kg H2, t steel, MWh_fuel, ...).
    product_unit: label only.

    Returns
    -------
    dict with per-component annuity, total capex annuity, total opex, lcx.
    """
    per_component: dict[str, dict[str, float]] = {}
    total_capex_annuity = 0.0
    total_opex = 0.0

    for comp, capex_per_unit in component_capex_per_unit.items():
        capacity = _component_capacity(network, comp)
        key = component_overlay_key.get(comp, "default")
        cw = _overlay_for(overlay, key)
        total_capex = capacity * capex_per_unit
        annuity = annuitise(total_capex, cw.wacc, cw.lifetime_years)
        var_cost = _component_variable_cost(network, comp)

        per_component[comp] = {
            "capacity": capacity,
            "capex_total": total_capex,
            "wacc": cw.wacc,
            "lifetime_years": cw.lifetime_years,
            "capex_annuity": annuity,
            "variable_cost_annual": var_cost,
        }
        total_capex_annuity += annuity
        total_opex += var_cost

    lcx = (
        (total_capex_annuity + total_opex) / annual_product
        if annual_product > 0
        else float("nan")
    )

    return {
        "per_component": per_component,
        "total_capex_annuity": total_capex_annuity,
        "total_opex": total_opex,
        "annual_product": annual_product,
        "product_unit": product_unit,
        "lcx_per_unit": lcx,
    }
