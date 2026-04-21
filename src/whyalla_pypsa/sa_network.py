"""3-subregion SA dispatch overlay for the Whyalla facility network.

Builds a CSA/NSA/SESA topology connected to VIC/NSW slack buses via staged
interconnectors (PEC, Heywood, Murraylink), seeded from Draft 2026 ISP GGO ODP
capacities and PLEXOS interconnector flow stages. Runs *after* `build_facility_network`,
which has already created the `{sub}_ac` bus and the facility<->subregion Links.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from whyalla_pypsa.config import FacilityConfig
from whyalla_pypsa.data.aemo_draft_2026 import (
    load_demand,
    load_subregion_vre_aggregate,
    load_trace,
    to_hourly,
)
from whyalla_pypsa.data.isp_ggo import load_ggo_capacity
from whyalla_pypsa.data.plexos_xml import (
    FlowStage,
    list_interconnectors,
    load_interconnector_flows,
)
from whyalla_pypsa.grid import _residual_price


# ---------------------------------------------------------------------------
# Static facts
# ---------------------------------------------------------------------------

SA_SUBREGIONS = ("CSA", "NSA", "SESA")

# PLEXOS canonical names (verified in Wave 1 tests).
PEC_NAME = "EnergyConnect"
HEYWOOD_NAME = "V-SA"
MURRAYLINK_NAME = "V-S-MNSP1"

# Intra-SA interconnectors: name discovered at runtime from the PLEXOS model.
# If none match, we fall back to DEFAULT_INTRA_SA_MW with a runtime note.
DEFAULT_INTRA_SA_MW = 500.0

# Heywood upgrades from 650 -> 750 MW on 2027-11-30 alongside PEC commissioning.
# A financial-year-start (1 July) comparison date is used when picking the
# applicable stage for a given `model_year`.

# BESS: assume 4-hour duration, 0.88 round-trip efficiency.
BESS_DURATION_HOURS = 4.0
BESS_ROUNDTRIP = 0.88

# Marginal cost proxy for SA thermal fleet (gas peakers + mid-merit, AUD/MWh).
DEFAULT_THERMAL_MARGINAL_COST = 100.0

# Default representative REZ trace site per subregion.
_WIND_SITE_BY_SUB: dict[str, str] = {
    "CSA": "S3_WH_Mid-North_SA",
    "NSA": "S5_WH_Northern_SA",
    "SESA": "S1_WH_South_East_SA",
}
_SOLAR_SITE_BY_SUB: dict[str, str] = {
    "CSA": "REZ_S3_Mid-North_SA_SAT",
    "NSA": "REZ_S5_Northern_SA_SAT",
    "SESA": "REZ_S1_South_East_SA_SAT",
}

# Slack-bus demand proxy subregions (chosen for availability in AEMO traces).
# TODO: replace CSA fallback once a cleaner VIC/NSW aggregate trace is wired.
_SLACK_DEMAND_SUB: dict[str, str] = {"VIC": "MEL", "NSW": "SNW"}

# GGO technology labels used for the fixed-capacity SA fleet.
_WIND_TECH = "Wind"
_SOLAR_TECH = "Utility-scale solar"
_THERMAL_TECHS = ("Mid-merit gas", "Flexible gas")
_UTILITY_STORAGE_TECHS = (
    "Deep utility-scale storage",
    "Medium utility-scale storage",
    "Shallow utility-scale storage",
)


# ---------------------------------------------------------------------------
# Override payloads (test-facing)
# ---------------------------------------------------------------------------


@dataclass
class _DemandOverride:
    """Stubs demand/rooftop lookups: per-sub hourly Series keyed by subregion."""

    demand: dict[str, pd.Series]
    rooftop: dict[str, pd.Series] | None = None


@dataclass
class _GGOOverride:
    """Stubs GGO capacity lookups: per-sub MW by technology family."""

    # Each inner dict keyed by: 'wind', 'solar', 'thermal', 'bess'.
    mw_by_sub: dict[str, dict[str, float]]


@dataclass
class _InterconnectorOverride:
    """Stubs PLEXOS flow-stage lookups: per-name list[FlowStage] and intra-SA names."""

    stages_by_name: dict[str, list[FlowStage]]
    csa_nsa_name: str | None = None
    sesa_csa_name: str | None = None


# ---------------------------------------------------------------------------
# Stage-picking helper
# ---------------------------------------------------------------------------


def _stage_cutoff(model_year: int) -> date:
    """Comparison date when picking a staged interconnector capacity.

    `model_year-07-01` — Jul 1 of the model_year itself. This matches the
    expectation that e.g. model_year=2028 (post the 2027-11-30 PEC/Heywood
    commissioning) sees the upgraded capacity.
    """
    return date(model_year, 7, 1)


def pick_stage_for_year(stages: Iterable[FlowStage], model_year: int) -> FlowStage:
    """Return the applicable FlowStage at the FY-start of `model_year`.

    Latest dated stage with date_from <= cutoff wins; otherwise baseline
    (date_from=None). Raises ValueError if no stages at all.
    """
    stages = list(stages)
    if not stages:
        raise ValueError("No stages provided")
    cutoff = _stage_cutoff(model_year)
    dated = [s for s in stages if s.date_from is not None and s.date_from <= cutoff]
    if dated:
        return max(dated, key=lambda s: s.date_from)
    baseline = [s for s in stages if s.date_from is None]
    if baseline:
        return baseline[0]
    # If only future-dated stages exist, use the earliest future stage as the
    # least-bad fallback (shouldn't happen with real AEMO data).
    return min(stages, key=lambda s: s.date_from)


# ---------------------------------------------------------------------------
# Data-fetching helpers (respect overrides)
# ---------------------------------------------------------------------------


def _fetch_demand_and_rooftop(
    config: FacilityConfig,
    sub: str,
    override: _DemandOverride | None,
) -> tuple[pd.Series, pd.Series]:
    """Return (demand, rooftop) half-hourly or hourly Series for the subregion."""
    if override is not None and sub in override.demand:
        demand = override.demand[sub]
        rooftop_map = override.rooftop or {}
        rooftop = rooftop_map.get(sub, pd.Series(0.0, index=demand.index))
        return demand, rooftop

    demand = load_demand(
        config.data_path,
        sub,
        config.scenario.file_token,
        config.scenario.refyear_file_token,
        model_year=config.scenario.model_year,
    )
    try:
        rooftop = load_subregion_vre_aggregate(
            config.data_path,
            sub,
            "rooftop_pv",
            config.scenario.file_token,
            config.scenario.refyear_file_token,
            model_year=config.scenario.model_year,
        )
    except FileNotFoundError:
        rooftop = pd.Series(0.0, index=demand.index)
    return demand, rooftop


def _fetch_vre_trace(
    config: FacilityConfig, kind: str, site: str
) -> pd.Series | None:
    """Load a wind/solar CF trace; None if not available on disk."""
    try:
        return load_trace(
            config.data_path,
            kind,
            site,
            config.scenario.refyear_file_token,
            model_year=config.scenario.model_year,
        )
    except FileNotFoundError:
        return None


def _fetch_ggo_mw(
    config: FacilityConfig,
    sub: str,
    override: _GGOOverride | None,
    ggo_path: Path | None,
) -> dict[str, float]:
    """Return installed-MW dict {'wind','solar','thermal','bess'} for subregion."""
    if override is not None and sub in override.mw_by_sub:
        row = override.mw_by_sub[sub]
        return {k: float(row.get(k, 0.0)) for k in ("wind", "solar", "thermal", "bess")}

    if ggo_path is None:
        raise FileNotFoundError(
            "GGO workbook path not resolved; pass ggo_path= or provide _override_ggo."
        )
    model_year = config.scenario.model_year

    def _sum_mw(df: pd.DataFrame) -> float:
        slice_ = df[df["fy"] == model_year]["capacity_mw"]
        return float(slice_.sum()) if not slice_.empty else 0.0

    cap = load_ggo_capacity(ggo_path, subregion=sub, sheet="Capacity")
    wind_mw = _sum_mw(cap[cap["technology"] == _WIND_TECH])
    solar_mw = _sum_mw(cap[cap["technology"] == _SOLAR_TECH])
    thermal_mw = _sum_mw(cap[cap["technology"].isin(_THERMAL_TECHS)])

    stor = load_ggo_capacity(ggo_path, subregion=sub, sheet="Storage Capacity")
    bess_mw = _sum_mw(stor[stor["technology"].isin(_UTILITY_STORAGE_TECHS)])

    return {"wind": wind_mw, "solar": solar_mw, "thermal": thermal_mw, "bess": bess_mw}


def _fetch_stages(
    override: _InterconnectorOverride | None,
    xml_path: Path | None,
    name: str,
) -> list[FlowStage] | None:
    """Return list[FlowStage] for `name`, or None if not resolvable."""
    if override is not None:
        return override.stages_by_name.get(name)
    if xml_path is None or not Path(xml_path).exists():
        return None
    try:
        return load_interconnector_flows(xml_path, name, "Max Flow")
    except KeyError:
        return None


def _resolve_intra_sa_name(
    override: _InterconnectorOverride | None,
    xml_path: Path | None,
    side_a: str,
    side_b: str,
) -> str | None:
    """Best-effort match a Line name connecting two SA subregions, e.g. CSA-NSA."""
    if override is not None:
        if {side_a, side_b} == {"CSA", "NSA"}:
            return override.csa_nsa_name
        if {side_a, side_b} == {"SESA", "CSA"}:
            return override.sesa_csa_name
        return None
    if xml_path is None or not Path(xml_path).exists():
        return None
    try:
        names = list_interconnectors(xml_path)
    except Exception:
        return None
    # Accept either "A-B" or "B-A"; match on exact segments separated by '-'.
    wanted = {f"{side_a}-{side_b}", f"{side_b}-{side_a}"}
    for n in names:
        if n in wanted:
            return n
    # Fuzzier: both tokens appear.
    for n in names:
        if side_a in n and side_b in n:
            return n
    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _default_xml_path(config: FacilityConfig) -> Path:
    folder = {
        "STEP_CHANGE": "Draft 2026 ISP Step Change",
        "ACCELERATED_TRANSITION": "Draft 2026 ISP Accelerated Transition",
        "SLOWER_GROWTH": "Draft 2026 ISP Slower Growth",
    }.get(config.scenario.file_token, "Draft 2026 ISP Step Change")
    return config.data_path / "Draft 2026 ISP Model" / folder / f"{folder} Model.xml"


def _default_ggo_path(config: FacilityConfig) -> Path:
    scenario_name = config.scenario.name  # e.g. "Step Change"
    return (
        config.data_path
        / "Draft 2026 ISP generation and storage outlook"
        / "Cores"
        / f"Draft_2026 ISP - {scenario_name} - Core.xlsx"
    )


def _align_to_snapshots(series: pd.Series, snapshots: pd.DatetimeIndex) -> pd.Series:
    return series.reindex(snapshots).ffill().bfill()


def _to_resolution(series: pd.Series, resolution: str) -> pd.Series:
    if resolution == "hourly":
        return to_hourly(series, how="mean")
    return series


def attach_sa_dispatch(
    network,
    config: FacilityConfig,
    *,
    thermal_marginal_cost: float = DEFAULT_THERMAL_MARGINAL_COST,
    xml_path: Path | None = None,
    ggo_path: Path | None = None,
    _override_demand: _DemandOverride | None = None,
    _override_ggo: _GGOOverride | None = None,
    _override_interconnectors: _InterconnectorOverride | None = None,
):
    """Attach a 3-subregion SA dispatch overlay with VIC/NSW slack buses.

    Assumes `build_facility_network` has already created `{sub}_ac` (default
    CSA_ac). Adds NSA_ac, SESA_ac, VIC_slack_ac, NSW_slack_ac plus per-subregion
    loads, fixed-capacity generators seeded from GGO ODP, and staged Links.
    """
    snapshots = network.snapshots
    resolution = config.scenario.resolution
    model_year = config.scenario.model_year
    xml_path = Path(xml_path) if xml_path is not None else _default_xml_path(config)
    ggo_path = Path(ggo_path) if ggo_path is not None else _default_ggo_path(config)

    # --- 1. Buses -----------------------------------------------------------
    configured_sub_bus = f"{config.grid.subregion}_ac"
    all_sa_buses = [f"{s}_ac" for s in SA_SUBREGIONS]
    slack_buses = ["VIC_slack_ac", "NSW_slack_ac"]

    for bus in all_sa_buses + slack_buses:
        if bus == configured_sub_bus:
            continue  # facility.py already created this one
        if bus not in network.buses.index:
            network.add("Bus", bus, carrier="electricity")

    # --- 2. Per-subregion load + VRE + thermal + BESS -----------------------
    for sub in SA_SUBREGIONS:
        bus = f"{sub}_ac"

        demand, rooftop = _fetch_demand_and_rooftop(config, sub, _override_demand)
        demand = _to_resolution(demand, resolution)
        rooftop = _to_resolution(rooftop, resolution)
        rooftop = rooftop.reindex(demand.index, fill_value=0.0)
        net_demand = demand.subtract(rooftop).clip(lower=0.0)
        net_demand = _align_to_snapshots(net_demand, snapshots)

        network.add("Load", f"{sub}_load", bus=bus, p_set=net_demand.values)

        ggo_mw = _fetch_ggo_mw(config, sub, _override_ggo, ggo_path)

        # Wind
        wind_site = _WIND_SITE_BY_SUB[sub]
        wind_cf = _fetch_vre_trace(config, "wind", wind_site)
        if wind_cf is not None:
            wind_cf = _to_resolution(wind_cf, resolution)
            wind_cf = _align_to_snapshots(wind_cf.clip(0, 1), snapshots)
            p_max_pu_wind: Any = wind_cf.values
        else:
            p_max_pu_wind = 1.0
        network.add(
            "Generator",
            f"{sub}_wind",
            bus=bus,
            carrier="electricity",
            p_nom=ggo_mw["wind"],
            p_max_pu=p_max_pu_wind,
            marginal_cost=0.0,
        )

        # Solar
        solar_site = _SOLAR_SITE_BY_SUB[sub]
        solar_cf = _fetch_vre_trace(config, "solar", solar_site)
        if solar_cf is not None:
            solar_cf = _to_resolution(solar_cf, resolution)
            solar_cf = _align_to_snapshots(solar_cf.clip(0, 1), snapshots)
            p_max_pu_solar: Any = solar_cf.values
        else:
            p_max_pu_solar = 1.0
        network.add(
            "Generator",
            f"{sub}_solar",
            bus=bus,
            carrier="electricity",
            p_nom=ggo_mw["solar"],
            p_max_pu=p_max_pu_solar,
            marginal_cost=0.0,
        )

        # Thermal (gas mid-merit + flexible)
        network.add(
            "Generator",
            f"{sub}_thermal",
            bus=bus,
            carrier="electricity",
            p_nom=ggo_mw["thermal"],
            marginal_cost=thermal_marginal_cost,
        )

        # BESS: Bus + charge Link + discharge Link + Store (4h, 0.88 round-trip).
        p_nom_bess = ggo_mw["bess"]
        if p_nom_bess > 0:
            bess_bus = f"{sub}_bess"
            eta = math.sqrt(BESS_ROUNDTRIP)
            network.add("Bus", bess_bus, carrier="electricity")
            network.add(
                "Link",
                f"{sub}_bess_charge",
                bus0=bus,
                bus1=bess_bus,
                p_nom=p_nom_bess,
                efficiency=eta,
            )
            network.add(
                "Link",
                f"{sub}_bess_discharge",
                bus0=bess_bus,
                bus1=bus,
                p_nom=p_nom_bess,
                efficiency=eta,
            )
            network.add(
                "Store",
                f"{sub}_bess_store",
                bus=bess_bus,
                e_nom=p_nom_bess * BESS_DURATION_HOURS,
                e_cyclic=True,
            )

    # --- 3. Slack-bus price-taker generators --------------------------------
    for region in ("VIC", "NSW"):
        slack_bus = f"{region}_slack_ac"
        price = _slack_price_series(config, region, snapshots, _override_demand)
        network.add(
            "Generator",
            f"{region}_slack_supply",
            bus=slack_bus,
            carrier="electricity",
            p_nom=1e6,
            marginal_cost=price.values,
        )

    # --- 4. Interconnectors -------------------------------------------------
    # Intra-SA: CSA<->NSA, SESA<->CSA.
    csa_nsa = _resolve_intra_sa_name(_override_interconnectors, xml_path, "CSA", "NSA")
    if csa_nsa:
        stages = _fetch_stages(_override_interconnectors, xml_path, csa_nsa) or []
        p_nom = pick_stage_for_year(stages, model_year).value if stages else DEFAULT_INTRA_SA_MW
    else:
        # TODO: confirm the exact PLEXOS name for CSA<->NSA in Draft 2026.
        p_nom = DEFAULT_INTRA_SA_MW
    _add_bidirectional(network, "csa_nsa", "CSA_ac", "NSA_ac", p_nom)

    sesa_csa = _resolve_intra_sa_name(_override_interconnectors, xml_path, "SESA", "CSA")
    if sesa_csa:
        stages = _fetch_stages(_override_interconnectors, xml_path, sesa_csa) or []
        p_nom = pick_stage_for_year(stages, model_year).value if stages else DEFAULT_INTRA_SA_MW
    else:
        # TODO: confirm the exact PLEXOS name for SESA<->CSA in Draft 2026.
        p_nom = DEFAULT_INTRA_SA_MW
    _add_bidirectional(network, "sesa_csa", "SESA_ac", "CSA_ac", p_nom)

    # Heywood: SESA <-> VIC_slack (staged; 650 -> 750 MW on 2027-11-30).
    heywood_stages = _fetch_stages(_override_interconnectors, xml_path, HEYWOOD_NAME)
    heywood_mw = (
        pick_stage_for_year(heywood_stages, model_year).value
        if heywood_stages
        else 650.0
    )
    _add_bidirectional(network, "heywood", "SESA_ac", "VIC_slack_ac", heywood_mw)

    # Murraylink: SESA <-> VIC_slack (flat ~220 MW, no staging).
    murraylink_stages = _fetch_stages(
        _override_interconnectors, xml_path, MURRAYLINK_NAME
    )
    if murraylink_stages:
        murraylink_mw = pick_stage_for_year(murraylink_stages, model_year).value
    else:
        murraylink_mw = 220.0
    _add_bidirectional(
        network, "murraylink", "SESA_ac", "VIC_slack_ac", murraylink_mw
    )

    # PEC / EnergyConnect: NSA <-> NSW_slack (staged; 150 -> 800 MW on 2027-11-30).
    pec_stages = _fetch_stages(_override_interconnectors, xml_path, PEC_NAME)
    pec_mw = (
        pick_stage_for_year(pec_stages, model_year).value if pec_stages else 150.0
    )
    _add_bidirectional(network, "pec", "NSA_ac", "NSW_slack_ac", pec_mw)

    return network


# ---------------------------------------------------------------------------
# Helpers used by the main entry point
# ---------------------------------------------------------------------------


def _add_bidirectional(network, base_name: str, bus_a: str, bus_b: str, p_nom: float):
    """Two explicit Links (a->b, b->a), same p_nom, efficiency 1.0."""
    network.add(
        "Link",
        f"{base_name}_fwd",
        bus0=bus_a,
        bus1=bus_b,
        p_nom=float(p_nom),
        efficiency=1.0,
    )
    network.add(
        "Link",
        f"{base_name}_rev",
        bus0=bus_b,
        bus1=bus_a,
        p_nom=float(p_nom),
        efficiency=1.0,
    )


def _slack_price_series(
    config: FacilityConfig,
    region: str,
    snapshots: pd.DatetimeIndex,
    override: _DemandOverride | None,
) -> pd.Series:
    """Residual-load-derived AUD/MWh price for a VIC/NSW slack bus."""
    proxy_sub = _SLACK_DEMAND_SUB.get(region, "CSA")
    try:
        demand, rooftop = _fetch_demand_and_rooftop(config, proxy_sub, override)
    except FileNotFoundError:
        # TODO: wire a dedicated VIC/NSW wholesale-demand trace once available;
        # for now fall back to CSA so the slack bus still has a time-varying price.
        demand, rooftop = _fetch_demand_and_rooftop(config, "CSA", override)

    demand = _to_resolution(demand, config.scenario.resolution)
    rooftop = _to_resolution(rooftop, config.scenario.resolution)
    rooftop = rooftop.reindex(demand.index, fill_value=0.0)
    residual = demand.subtract(rooftop).clip(lower=0.0)
    residual = _align_to_snapshots(residual, snapshots)
    return _residual_price(residual)
