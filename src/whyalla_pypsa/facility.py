"""Build a Whyalla facility PyPSA network from a FacilityConfig.

Components attached here are the *shared* facility assets: VRE generators,
battery storage, H2 storage, and a bidirectional grid link to the configured
subregion AC bus. Process-chain loads (electrolyser, DRI, EAF, synthesis,
CO2) are intentionally NOT attached here — downstream projects add those.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

from whyalla_pypsa.config import FacilityConfig
from whyalla_pypsa.data.aemo_draft_2026 import load_trace, to_hourly
from whyalla_pypsa.post.annuitise import annuitise


def _snapshots(series: pd.Series, resolution: str) -> pd.DatetimeIndex:
    if resolution == "half_hourly":
        return series.index
    if resolution == "hourly":
        return series.resample("1h").mean().index
    raise ValueError(f"Unknown resolution: {resolution!r}")


def _to_resolution(series: pd.Series, resolution: str) -> pd.Series:
    if resolution == "half_hourly":
        return series
    return to_hourly(series, how="mean")


def _representative_week_index(
    full_index: pd.DatetimeIndex, n_weeks: int
) -> pd.DatetimeIndex:
    """Return a concatenated DatetimeIndex of N evenly-spaced 168-hour windows.

    Windows are picked by dividing the full index into N equal-length bands and
    taking 168 consecutive hours starting at the midpoint of each band. This is
    a simple hand-rolled approach — no tsam dependency needed.
    """
    n_hours = len(full_index)
    band_size = n_hours // n_weeks
    selected: list[pd.DatetimeIndex] = []
    for i in range(n_weeks):
        band_start = i * band_size
        # Mid-point of the band, but ensure we can fit 168 hours after it.
        mid = band_start + band_size // 2
        end = mid + 168
        if end > n_hours:
            # Shift window back so it fits inside the index.
            end = n_hours
            mid = end - 168
        selected.append(full_index[mid:end])
    return selected[0].append(selected[1:])


def _slice_series(series: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    """Reindex series to idx; forward-fill any gaps (should be none in practice)."""
    return series.reindex(idx).ffill().bfill()


def _annuitised_capital_cost(
    capex_per_unit: float, fom_pct: float, wacc: float, lifetime: int
) -> float:
    return annuitise(capex_per_unit, wacc, lifetime) + fom_pct * capex_per_unit


def build_facility_network(config: FacilityConfig) -> pypsa.Network:
    """Assemble the Whyalla facility network (no process chain)."""
    sub = config.grid.subregion
    scenario_token = config.scenario.file_token
    refyear = config.scenario.refyear_file_token
    model_year = config.scenario.model_year

    # Load VRE traces; these files sit outside the scenario folders (weather,
    # not scenario-driven). model_year selects the Australian FY slice.
    wind_cf = load_trace(
        config.data_path, "wind", config.wind.representative_site, refyear,
        model_year=model_year,
    )
    solar_cf = load_trace(
        config.data_path, "solar", config.solar.representative_site, refyear,
        model_year=model_year,
    )

    wind_cf = _to_resolution(wind_cf, config.scenario.resolution)
    solar_cf = _to_resolution(solar_cf, config.scenario.resolution)

    # Align to a common index (first valid intersection).
    idx = wind_cf.index.intersection(solar_cf.index)
    wind_cf = wind_cf.reindex(idx)
    solar_cf = solar_cf.reindex(idx)

    # --- Snapshot mode -------------------------------------------------------
    snapshot_mode = config.scenario.snapshot_mode
    if snapshot_mode not in ("full_year", "representative_weeks"):
        raise ValueError(
            f"Unknown snapshot_mode: {snapshot_mode!r}. "
            "Valid values: 'full_year', 'representative_weeks'."
        )

    if snapshot_mode == "representative_weeks":
        n_weeks = config.scenario.representative_weeks
        rep_idx = _representative_week_index(idx, n_weeks)
        wind_cf = _slice_series(wind_cf, rep_idx)
        solar_cf = _slice_series(solar_cf, rep_idx)
        idx = rep_idx
    # -------------------------------------------------------------------------

    n = pypsa.Network()
    n.set_snapshots(idx)

    # Scale snapshot weightings so N×168 representative hours represent 8760 h.
    if snapshot_mode == "representative_weeks":
        n_weeks = config.scenario.representative_weeks
        weight = 8760.0 / (n_weeks * 168)
        n.snapshot_weightings["generators"] = weight
        n.snapshot_weightings["stores"] = weight
        n.snapshot_weightings["objective"] = weight

    # Carriers.
    n.add("Carrier", "electricity")
    n.add("Carrier", "H2")

    # Buses.
    facility_ac = "facility_ac"
    facility_h2 = "facility_h2"
    grid_ac = f"{sub}_ac"
    n.add("Bus", facility_ac, carrier="electricity")
    n.add("Bus", facility_h2, carrier="H2")
    n.add("Bus", grid_ac, carrier="electricity")

    # ---- VRE generators (capex per kW -> per MW annuitised) ----------------
    wind = config.wind
    wind_cc = _annuitised_capital_cost(
        wind.cost.capex_per_unit * 1000.0,  # kW -> MW
        wind.cost.fom_pct,
        config.pypsa_wacc,
        wind.cost.lifetime_years,
    )
    n.add(
        "Generator",
        "wind",
        bus=facility_ac,
        carrier="electricity",
        p_nom_extendable=True,
        p_nom_max=wind.max_capacity_mw if wind.max_capacity_mw is not None else np.inf,
        p_max_pu=wind_cf.clip(0, 1).values,
        marginal_cost=wind.cost.vom_per_mwh,
        capital_cost=wind_cc,
    )

    solar = config.solar
    solar_cc = _annuitised_capital_cost(
        solar.cost.capex_per_unit * 1000.0,
        solar.cost.fom_pct,
        config.pypsa_wacc,
        solar.cost.lifetime_years,
    )
    n.add(
        "Generator",
        "solar",
        bus=facility_ac,
        carrier="electricity",
        p_nom_extendable=True,
        p_nom_max=solar.max_capacity_mw
        if solar.max_capacity_mw is not None
        else np.inf,
        p_max_pu=solar_cf.clip(0, 1).values,
        marginal_cost=solar.cost.vom_per_mwh,
        capital_cost=solar_cc,
    )

    # ---- Battery (split round-trip efficiency sqrt across charge/discharge) -
    batt = config.battery
    eta = math.sqrt(batt.roundtrip_efficiency)
    batt_p_cc = _annuitised_capital_cost(
        batt.power_cost.capex_per_unit * 1000.0,  # per kW -> per MW
        batt.power_cost.fom_pct,
        config.pypsa_wacc,
        batt.power_cost.lifetime_years,
    )
    batt_e_cc = _annuitised_capital_cost(
        batt.energy_cost.capex_per_unit * 1000.0,  # per kWh -> per MWh
        batt.energy_cost.fom_pct,
        config.pypsa_wacc,
        batt.energy_cost.lifetime_years,
    )
    n.add("Bus", "battery_internal", carrier="electricity")
    n.add(
        "Link",
        "battery_charge",
        bus0=facility_ac,
        bus1="battery_internal",
        efficiency=eta,
        p_nom_extendable=True,
        capital_cost=batt_p_cc,
    )
    n.add(
        "Link",
        "battery_discharge",
        bus0="battery_internal",
        bus1=facility_ac,
        efficiency=eta,
        p_nom_extendable=True,
    )
    n.add(
        "Store",
        "battery_store",
        bus="battery_internal",
        e_nom_extendable=True,
        e_cyclic=True,
        capital_cost=batt_e_cc,
    )
    # duration_hours constraint: energy = duration * power. PyPSA supports this
    # via a linear extra-functionality constraint; for the shared core we
    # approximate by default (None = no constraint) and leave the explicit
    # constraint to downstream solve scripts.
    # TODO: wire `duration_hours` into an extra_functionality constraint once
    # the shared solve wrapper is introduced.

    # ---- H2 storage --------------------------------------------------------
    h2 = config.h2_storage
    h2_cc = _annuitised_capital_cost(
        h2.cost.capex_per_unit,  # already per MWh_LHV
        h2.cost.fom_pct,
        config.pypsa_wacc,
        h2.cost.lifetime_years,
    )
    n.add(
        "Store",
        "h2_store",
        bus=facility_h2,
        carrier="H2",
        e_nom_extendable=True,
        e_cyclic=True,
        capital_cost=h2_cc,
    )

    # ---- Grid link (bidirectional, extendable) -----------------------------
    grid_cc = _annuitised_capital_cost(
        config.grid.link_capex_per_mw,
        0.02,  # default link FOM if not provided via CostAssumption here
        config.pypsa_wacc,
        config.wacc_overlay.grid_link.lifetime_years,
    )
    link_p_max = (
        config.grid.link_max_capacity_mw
        if config.grid.link_max_capacity_mw is not None
        else np.inf
    )
    n.add(
        "Link",
        "grid_import",
        bus0=grid_ac,
        bus1=facility_ac,
        efficiency=config.grid.link_efficiency,
        p_nom_extendable=True,
        p_nom_max=link_p_max,
        capital_cost=grid_cc,
    )
    n.add(
        "Link",
        "grid_export",
        bus0=facility_ac,
        bus1=grid_ac,
        efficiency=config.grid.link_efficiency,
        p_nom_extendable=True,
        p_nom_max=link_p_max,
    )

    return n
