"""Orchestrator: attach all biofuels pathways onto an existing efuels network.

Must be called AFTER ``process_chain.attach_efuels()`` because it assumes
the product buses (diesel_bus, kero_bus, naphtha_bus), the co2 bus, and
the h2_bus already exist.

Usage::

    from biofuels import attach_biofuels
    attach_efuels(n, ...)            # existing e-fuels process chain
    attach_biofuels(n, wacc=0.07,
                    enable_htl=True,
                    enable_hefa=True,
                    enable_pyrolysis=True,
                    enable_gasification=True)

Each pathway can be toggled independently — useful for the worked-example
script (biofuels-on vs biofuels-off) and for isolating which pathway the
optimiser prefers in sensitivity sweeps.
"""
from __future__ import annotations

import pypsa

from .waste_streams import (
    DRI_WASTE_HEAT_MWH_PER_YEAR,
    HOURS_PER_YEAR,
)
from heat_integration import (
    PROCESS_HEAT_DUTY_BUS,
    attach_process_heat_duty,
)
from .pathway_htl import attach_htl
from .pathway_hefa import attach_hefa
from .pathway_biomass import (
    attach_biomass_feedstocks,
    attach_pyrolysis,
    attach_gasification,
)
from .biomass_supply import (
    LIGNOCELLULOSE_TRANCHE_PREFIXES,
    HALOPHYTE_TRANCHE_PREFIXES,
    ALGAE_STEELWORKS_TRANCHE_PREFIXES,
    ALGAE_PORT_BONYTHON_TRANCHE_PREFIXES,
)


def attach_biofuels(
    n: pypsa.Network,
    *,
    wacc: float,
    h2_bus: str = "facility_h2",
    co2_bus: str = "co2",
    # Pathway toggles
    enable_htl: bool = True,
    enable_hefa: bool = True,
    enable_pyrolysis: bool = True,
    enable_gasification: bool = True,
    # Waste streams
    waste_heat_mwh_per_year: float = DRI_WASTE_HEAT_MWH_PER_YEAR,
    # Aux
    grid_price_for_aux: float = 120.0,
    hours_per_year: float = HOURS_PER_YEAR,
) -> pypsa.Network:
    """Attach enabled biofuel pathways onto an efuels network.

    Returns the mutated network (for chaining).

    Any pathway can be disabled by setting its toggle to False — this is
    the mechanism the worked-example script uses to compare biofuels-on
    vs biofuels-off.
    """
    heat_duty_bus = PROCESS_HEAT_DUTY_BUS

    # Process heat bus is created by attach_efuels() (shared with
    # refinery heat draw). Call here too in case biofuels are attached to
    # a bare network without efuels — idempotent either way.
    attach_process_heat_duty(
        n, wacc=wacc,
        waste_heat_mwh_per_year=waste_heat_mwh_per_year,
    )

    if enable_htl:
        attach_htl(n, wacc=wacc, site="steelworks", h2_bus=h2_bus,
                   grid_price_for_aux=grid_price_for_aux,
                   hours_per_year=hours_per_year)
        attach_htl(n, wacc=wacc, site="port_bonython", h2_bus=h2_bus,
                   grid_price_for_aux=grid_price_for_aux,
                   hours_per_year=hours_per_year)

    if enable_hefa:
        attach_hefa(n, wacc=wacc, h2_bus=h2_bus,
                    hours_per_year=hours_per_year)

    if enable_pyrolysis or enable_gasification:
        attach_biomass_feedstocks(n, hours_per_year=hours_per_year)

    if enable_pyrolysis:
        attach_pyrolysis(
            n,
            wacc=wacc,
            h2_bus=h2_bus,
            grid_price_for_aux=grid_price_for_aux,
            hours_per_year=hours_per_year,
        )

    if enable_gasification:
        attach_gasification(
            n,
            wacc=wacc,
            h2_bus=h2_bus,
            co2_bus=co2_bus,
            grid_price_for_aux=grid_price_for_aux,
            hours_per_year=hours_per_year,
        )

    return n


BIOFUEL_LINK_NAMES = (
    "htl_upgrading_steelworks",
    "htl_upgrading_port_bonython",
    "hefa_upgrading",
    "pyrolysis_upgrading",
    "biomass_gasification",
)

BIOFUEL_FEED_GENERATOR_PREFIXES = (
    *LIGNOCELLULOSE_TRANCHE_PREFIXES,
    *HALOPHYTE_TRANCHE_PREFIXES,
    *ALGAE_STEELWORKS_TRANCHE_PREFIXES,
    *ALGAE_PORT_BONYTHON_TRANCHE_PREFIXES,
)


def extract_biofuels_dispatch(n: pypsa.Network) -> dict:
    """Pull per-pathway annual dispatch + capacity from a solved network.

    Returns dict with keys:
        htl_cap_t_dry_per_hr, htl_t_dry_per_yr, htl_fuel_t_per_yr
        hefa_cap_t_oil_per_hr, hefa_t_oil_per_yr, hefa_fuel_t_per_yr
        pyrolysis_cap_t_dry_per_hr, pyrolysis_t_dry_per_yr, pyrolysis_fuel_t_per_yr
        gasification_cap_t_dry_per_hr, gasification_t_dry_per_yr
        gasification_biogenic_h2_t_per_yr, gasification_biogenic_co2_t_per_yr
        waste_heat_used_mwh_per_yr
    """
    import pandas as pd

    snap_w = n.snapshot_weightings.generators.iloc[0]
    out: dict[str, float] = {}

    def _opt(component: str, name: str, col: str) -> float:
        tbl = getattr(n, component)
        if name not in tbl.index or col not in tbl.columns:
            return 0.0
        return float(tbl.at[name, col])

    def _link_p0_sum(name: str) -> float:
        if name not in n.links.index:
            return 0.0
        p0 = n.links_t.p0.get(name, pd.Series(0.0, index=n.snapshots))
        return float(p0.sum()) * snap_w

    def _link_p_out(name: str, bus_idx: int) -> float:
        """Annual outflow on busN (positive quantity)."""
        if name not in n.links.index:
            return 0.0
        col = f"p{bus_idx}"
        tbl = getattr(n.links_t, col, None)
        if tbl is None or name not in tbl.columns:
            return 0.0
        # Flow into bus_idx > 0 is represented by negative p_N in PyPSA sign
        # convention; negate to positive quantity.
        return float((-tbl[name]).sum()) * snap_w

    # ── HTL (per site) ──
    htl_total_t_dry = 0.0
    htl_total_diesel = 0.0
    htl_total_kero = 0.0
    htl_total_naphtha = 0.0
    for site in ("steelworks", "port_bonython"):
        link = f"htl_upgrading_{site}"
        site_t_dry = _link_p0_sum(link)
        site_diesel = _link_p_out(link, 1)
        site_kero = _link_p_out(link, 2)
        site_naphtha = _link_p_out(link, 3)
        out[f"htl_{site}_cap_t_dry_per_hr"] = _opt("links", link, "p_nom_opt")
        out[f"htl_{site}_t_dry_per_yr"]     = site_t_dry
        out[f"htl_{site}_fuel_diesel_t_per_yr"]  = site_diesel
        out[f"htl_{site}_fuel_kero_t_per_yr"]    = site_kero
        out[f"htl_{site}_fuel_naphtha_t_per_yr"] = site_naphtha
        htl_total_t_dry += site_t_dry
        htl_total_diesel += site_diesel
        htl_total_kero += site_kero
        htl_total_naphtha += site_naphtha
    # Aggregate (for back-compat chart code)
    out["htl_t_dry_per_yr"] = htl_total_t_dry
    out["htl_fuel_diesel_t_per_yr"]  = htl_total_diesel
    out["htl_fuel_kero_t_per_yr"]    = htl_total_kero
    out["htl_fuel_naphtha_t_per_yr"] = htl_total_naphtha

    # ── HEFA ──
    hefa_t_oil = _link_p0_sum("hefa_upgrading")
    out["hefa_cap_t_oil_per_hr"] = _opt("links", "hefa_upgrading", "p_nom_opt")
    out["hefa_t_oil_per_yr"] = hefa_t_oil
    out["hefa_fuel_kero_t_per_yr"]    = _link_p_out("hefa_upgrading", 1)
    out["hefa_fuel_diesel_t_per_yr"]  = _link_p_out("hefa_upgrading", 2)
    out["hefa_fuel_naphtha_t_per_yr"] = _link_p_out("hefa_upgrading", 3)

    # ── Pyrolysis ──
    pyr_t_dry = _link_p0_sum("pyrolysis_upgrading")
    out["pyrolysis_cap_t_dry_per_hr"] = _opt("links", "pyrolysis_upgrading", "p_nom_opt")
    out["pyrolysis_t_dry_per_yr"] = pyr_t_dry
    out["pyrolysis_fuel_diesel_t_per_yr"]  = _link_p_out("pyrolysis_upgrading", 1)
    out["pyrolysis_fuel_kero_t_per_yr"]    = _link_p_out("pyrolysis_upgrading", 2)
    out["pyrolysis_fuel_naphtha_t_per_yr"] = _link_p_out("pyrolysis_upgrading", 3)

    # ── Gasification ──
    gas_t_dry = _link_p0_sum("biomass_gasification")
    out["gasification_cap_t_dry_per_hr"] = _opt("links", "biomass_gasification", "p_nom_opt")
    out["gasification_t_dry_per_yr"] = gas_t_dry
    # bus1 = h2 (MWh H₂ delivered), bus2 = co2 (t delivered)
    out["gasification_biogenic_h2_mwh_per_yr"] = _link_p_out("biomass_gasification", 1)
    out["gasification_biogenic_co2_t_per_yr"]  = _link_p_out("biomass_gasification", 2)

    # ── Waste heat dispatch ──
    if "dri_waste_heat" in n.generators.index:
        wh = n.generators_t.p.get("dri_waste_heat", pd.Series(0.0, index=n.snapshots))
        out["waste_heat_used_mwh_per_yr"] = float(wh.sum()) * snap_w
    else:
        out["waste_heat_used_mwh_per_yr"] = 0.0

    # ── Biomass supply curve dispatch by tranche (roll-up + per-tranche) ──
    def _sum_gen_dispatch(prefixes) -> tuple[float, dict[str, float]]:
        total = 0.0
        per: dict[str, float] = {}
        for gname in n.generators.index:
            if any(gname.startswith(p) for p in prefixes):
                d = float(n.generators_t.p.get(gname,
                         pd.Series(0.0, index=n.snapshots)).sum()) * snap_w
                per[gname] = d
                total += d
        return total, per

    lc_total, lc_per = _sum_gen_dispatch(LIGNOCELLULOSE_TRANCHE_PREFIXES)
    ha_total, ha_per = _sum_gen_dispatch(HALOPHYTE_TRANCHE_PREFIXES)
    as_total, as_per = _sum_gen_dispatch(ALGAE_STEELWORKS_TRANCHE_PREFIXES)
    ap_total, ap_per = _sum_gen_dispatch(ALGAE_PORT_BONYTHON_TRANCHE_PREFIXES)
    out["lignocellulose_dispatched_t_per_yr"]       = lc_total
    out["halophyte_oil_dispatched_t_per_yr"]        = ha_total
    out["algae_steelworks_dispatched_t_per_yr"]     = as_total
    out["algae_port_bonython_dispatched_t_per_yr"]  = ap_total
    # Per-tranche dispatch for merit-order reporting
    for tranche_name, dispatch in {**lc_per, **ha_per, **as_per, **ap_per}.items():
        out[f"tranche_{tranche_name}_t_per_yr"] = dispatch

    return out
