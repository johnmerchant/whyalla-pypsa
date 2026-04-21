"""Attach a grid-price generator to the subregion AC bus.

Two modes:

- `price_trace`: reserved for direct wholesale-price CSVs from AEMO. Raises
  NotImplementedError today — Draft 2026 may or may not publish these.
- `rldc_merit`: residual-load-duration-curve merit-order proxy. Builds a
  time-varying marginal cost from residual load (demand minus available VRE).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from whyalla_pypsa.config import FacilityConfig
from whyalla_pypsa.data.aemo_draft_2026 import (
    load_demand,
    load_subregion_vre_aggregate,
    to_hourly,
)


def _residual_price(
    residual: pd.Series,
    floor: float = 40.0,
    ceiling: float = 300.0,
    span: float = 260.0,
    exponent: float = 2.0,
) -> pd.Series:
    """RLDC merit-order proxy: quadratic ramp of price in residual load.

    price = floor + span * (residual / peak_residual)**exponent,
    clipped to [floor, ceiling] AUD/MWh.
    """
    peak = float(np.nanmax(residual.values))
    if not np.isfinite(peak) or peak <= 0:
        return pd.Series(np.full(len(residual), floor), index=residual.index)
    ratio = (residual / peak).clip(lower=0.0)
    price = floor + span * ratio.pow(exponent)
    return price.clip(lower=floor, upper=ceiling)


def attach_grid_price(network, config: FacilityConfig):
    """Add a grid-supply Generator at `{subregion}_ac` with time-varying cost."""
    if config.grid.mode == "sa_dispatch":
        # 3-subregion SA overlay with VIC/NSW slacks. Kept in a separate module
        # to keep this file lean; lazy-import to avoid circular dependency.
        from whyalla_pypsa.sa_network import attach_sa_dispatch

        return attach_sa_dispatch(network, config)
    if config.grid.mode == "price_trace":
        # TODO: wire once confirmed available in Draft 2026.
        raise NotImplementedError(
            "Draft 2026 price traces not yet wired — use rldc_merit fallback."
        )
    if config.grid.mode != "rldc_merit":
        raise ValueError(f"Unknown grid mode: {config.grid.mode!r}")

    sub = config.grid.subregion
    token = config.scenario.file_token
    refyear = config.scenario.refyear_file_token
    model_year = config.scenario.model_year

    demand = load_demand(
        config.data_path, sub, token, refyear, model_year=model_year
    )
    # Rooftop PV is the only subregion-level VRE aggregate available. We
    # subtract it from demand so the residual roughly reflects what thermal +
    # large-scale VRE must meet. This is a stub; future work pulls a proper
    # subregion-aggregate wind/solar generation trace.
    try:
        rooftop = load_subregion_vre_aggregate(
            config.data_path, sub, "rooftop_pv", token, refyear,
            model_year=model_year,
        )
    except FileNotFoundError:
        rooftop = pd.Series(0.0, index=demand.index)

    residual = demand.subtract(rooftop.reindex(demand.index, fill_value=0.0))

    if config.scenario.resolution == "hourly":
        residual = to_hourly(residual, how="mean")

    # Align to network snapshots (trim/reindex if needed).
    snapshots = network.snapshots
    residual = residual.reindex(snapshots).ffill().bfill()

    price = _residual_price(residual)

    grid_bus = f"{sub}_ac"
    if grid_bus not in network.buses.index:
        network.add("Bus", grid_bus, carrier="electricity")

    network.add(
        "Generator",
        "grid_supply",
        bus=grid_bus,
        carrier="electricity",
        p_nom=1e6,
        marginal_cost=price.values,
    )
    return network
