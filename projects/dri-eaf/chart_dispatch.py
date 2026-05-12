"""What a week on South Australia's grid looks like with Whyalla steelmaking online.

Two panels per chart:

  (1) A 7-day slice of South Australia's electricity supply and demand:
      - Stacked above zero: SA wind farms, solar farms, gas-fired power,
        and imports from Victoria/New South Wales — the supply side.
      - Stacked below zero: Whyalla's two flexible electric loads —
        the hydrogen electrolysers (large, VRE-following) and the steel
        arc furnace (small, campaign-paced).
      - A black line shows ordinary SA demand (homes, businesses, other
        industry) so the reader can see surplus VRE being soaked up.
      - A red dotted line on the right axis shows the wholesale electricity
        spot price in the Whyalla zone of the grid.

  (2) Iron-reduction furnace fuel mix (the same 7 days):
      - Stacked bar: gas vs hydrogen feeding the iron-reduction shaft furnace.
      - Week-average fuel-split annotation.

The script re-solves one full FY on the South Australian grid for each
scenario year taken from trajectory.csv. Prior-year build-out is locked in
(you cannot "unbuild" an electrolyser or a storage tank), and policy/capex
parameters match the trajectory row for that year.

Two contrasting weeks are rendered per scenario year, **independently per year**
(calendar dates differ — the dispatch response matters, not aligned dates):

  - "clean-energy week" — a sunny, windy stretch this year's fleet exploits
    best. Picked as the week of highest H2 feedstock share (or, in gas-only
    years before the electrolyser is online, the week of lowest mean spot price).
  - "dunkelflaute" — a still, cloudy stretch where wind and solar fall short.
    Picked as the week of lowest H2 feedstock share (or, in gas-only years,
    the week of highest mean spot price), so the reader can see gas covering
    for H2 when renewable supply runs thin.

Solved networks are cached to netcdf under `.dispatch_cache/` so re-running
to tweak terminology or styling is instant (no re-solve).
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pypsa
from matplotlib.gridspec import GridSpec

from whyalla_pypsa import build_facility_network, attach_grid_price

from run import default_config
from process_chain import attach_dri_eaf
from generate_trajectory import (
    ISP_SCENARIOS,
    ISP_NAMES,
    NG_INTENSITY_MWH_PER_T_DRI,
    CO2_INTENSITY_KG_PER_T_DRI,
    FURNACE_OPEN_YEAR,
    GAS_DEAL_VOLUME_PJ_PER_YR,
    GAS_DEAL_LAST_YEAR,
    GAS_SPOT_PRICE_PER_GJ,
    SCRAP_TIER1_CAPACITY_T_PER_YR,
    SCRAP_TIER1_PRICE_PER_T,
    SCRAP_TIER2_CAPACITY_T_PER_YR,
    SCRAP_TIER2_PRICE_PER_T,
)

HERE = Path(__file__).parent
TRAJ_CSV = HERE / "trajectory.csv"
CACHE_DIR = HERE / ".dispatch_cache"

# ── Scenario picks — year / policy / ISP triple on the trajectory grid. ─────
POLICY = "Policy-stated + gas flat"
ISP = "step_change"

# Anchor years can be overridden via CLI; default is every year in trajectory.csv
# for the chosen (POLICY, ISP) branch.
DEFAULT_YEARS: list[int] | None = None

# Minimum electrolyser capacity (MW) for a year to count as "has built" when
# picking transition/dunkelflaute anchor years.
ELY_ANCHOR_MW = 50.0

WEEK_LABELS = {
    "transition": "clean-energy week — sunny, windy stretch",
    "dunkelflaute": "dunkelflaute — still, cloudy stretch where gas covers for H$_2$",
    "first_net_zero": (
        "milestone week — the first 7 days of net-zero-carbon steel "
        "(Scope 1 gas emissions offset by Scope 2 grid-export displacement)"
    ),
    "first_carbon_free_fallback": (
        "milestone week — the first 7 days at ≥90% hydrogen feedstock"
    ),
}

# H2 feedstock share (fraction) fallback threshold when net-zero is unreachable.
CARBON_FREE_FALLBACK_THRESHOLD = 0.90

# SA grid average emission intensity (t CO2 / MWh) for Scope 2 market-based
# accounting. Exports displace thermal generation at roughly this intensity;
# imports cause it. ~0.55 matches SA's current gas-dominated thermal mix.
SA_GRID_CO2_INTENSITY_T_PER_MWH = 0.55


def isp_human(isp: str) -> str:
    return {
        "step_change": "Step Change",
        "slower_growth": "Slower Growth",
        "accelerated_transition": "Accelerated Transition",
    }.get(isp, isp)


def _scenario_label(year: int, row: pd.Series) -> str:
    ely = float(row.electrolyser_mw)
    store = float(row.h2_storage_mwh)
    h2_pct = float(row.h2_fraction) * 100.0
    if ely < ELY_ANCHOR_MW:
        return (
            f"FY{year} — gas-only phase (before the hydrogen furnace opens; "
            f"the electric arc furnace is Whyalla's only flexible load)"
        )
    return (
        f"FY{year} — {h2_pct:.0f}% hydrogen over the year  |  "
        f"{ely:.0f} MW of electrolysers, {store / 1000:.1f} GWh of hydrogen storage"
    )


def _prior_build(traj: pd.DataFrame, year: int) -> dict[str, float]:
    """Cumulative capacities built in years strictly before `year`.

    Keys: electrolyser_mw, h2_storage_mwh, electric_heater_mw, h2_burner_mw.
    Heat-component columns are tolerant of older trajectory CSVs that predate
    the heat_duty bus (missing columns default to 0).
    """
    prior = traj[traj.year < year]
    if prior.empty:
        return {
            "electrolyser_mw": 0.0,
            "h2_storage_mwh": 0.0,
            "electric_heater_mw": 0.0,
            "h2_burner_mw": 0.0,
        }
    last = prior.iloc[-1]
    return {
        "electrolyser_mw": float(last.electrolyser_mw),
        "h2_storage_mwh": float(last.h2_storage_mwh),
        "electric_heater_mw": float(last.get("electric_heater_mw", 0.0) or 0.0),
        "h2_burner_mw": float(last.get("h2_burner_mw", 0.0) or 0.0),
    }


def _cache_path(year: int, policy: str, isp: str, traj_row: pd.Series) -> Path:
    """Stable path-cached key based on inputs that affect the solve."""
    key_blob = json.dumps({
        "year": int(year),
        "policy": policy,
        "isp": isp,
        "capex": round(float(traj_row.capex_per_kw), 3),
        "gas": round(float(traj_row.gas_price), 3),
        "carbon": round(float(traj_row.carbon_price), 3),
        "wacc": round(float(traj_row.discount_rate), 4),
        "prior_ely": round(float(traj_row.get("_prior_ely", 0.0)), 3),
        "prior_store": round(float(traj_row.get("_prior_store", 0.0)), 3),
        "prior_eh": round(float(traj_row.get("_prior_eh", 0.0)), 3),
        "prior_hb": round(float(traj_row.get("_prior_hb", 0.0)), 3),
        # Bump on any model-topology change so prior caches invalidate.
        # Changelog:
        #   v2 — carbon price flows into SA thermal generators' marginal cost
        #   v3 — phase model: pre-2030 DRI off, EAF scrap (cap 30% from 2030)
        #   v4 — thermal buffer dropped (heat balances per snapshot)
        #   v5 — EAF off-gas waste-heat-to-DRI pathway removed
        #   v6 — Santos foundation contract: deal-gas volume cap +
        #        spot-gas tier above the cap; deal expires after 2040
        "model_version": 6,
    }, sort_keys=True)
    digest = hashlib.md5(key_blob.encode()).hexdigest()[:10]
    return CACHE_DIR / f"dispatch_{year}_{digest}.nc"


def solve_scenario(
    year: int,
    traj_row: pd.Series,
    prior: dict[str, float],
    *,
    policy: str = POLICY,
    isp: str = ISP,
    use_cache: bool = True,
):
    """Build + solve a single full-year sa_dispatch scenario from a trajectory row.

    `prior` is the dict returned by `_prior_build(...)`, carrying cumulative
    capacities (electrolyser, h2 store, electric heater, h2 burner, thermal
    buffer) built in years strictly before this one. Those become p_nom_min /
    e_nom_min floors so the solver can upgrade but not un-build.

    Result is cached to netcdf so re-runs (for terminology / styling edits)
    skip the ~5-10 min HiGHS solve.
    """
    ely_capex = float(traj_row.capex_per_kw)
    gas_p = float(traj_row.gas_price)
    carbon_p = float(traj_row.carbon_price)
    wacc_new = float(traj_row.discount_rate)

    cache_row = traj_row.copy()
    cache_row["_prior_ely"] = prior["electrolyser_mw"]
    cache_row["_prior_store"] = prior["h2_storage_mwh"]
    cache_row["_prior_eh"] = prior["electric_heater_mw"]
    cache_row["_prior_hb"] = prior["h2_burner_mw"]
    cache = _cache_path(year, policy, isp, cache_row)
    if use_cache and cache.exists():
        cfg = default_config(
            grid_mode="sa_dispatch", model_year=year, snapshot_mode="full_year"
        )
        cfg = copy.deepcopy(cfg)
        cfg.scenario.file_token = ISP_SCENARIOS[isp]
        cfg.scenario.name = ISP_NAMES[isp]
        cfg.pypsa_wacc = 0.09
        n = pypsa.Network(str(cache))
        print(f"  [cache hit] loaded {cache.name}", flush=True)
        return n, cfg

    cfg = default_config(
        grid_mode="sa_dispatch", model_year=year, snapshot_mode="full_year"
    )
    cfg = copy.deepcopy(cfg)
    cfg.scenario.file_token = ISP_SCENARIOS[isp]
    cfg.scenario.name = ISP_NAMES[isp]
    cfg.pypsa_wacc = 0.09  # NOAK for facility base

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg, carbon_price_per_t_co2=carbon_p)
    # Phase model: pre-2030 = EAF scrap-only (cap=100%); from 2030 = 30% cap.
    scrap_cap_this_year = 1.0 if year < FURNACE_OPEN_YEAR else 0.30
    # Match generate_trajectory.solve_year: deal-gas tier (capped to
    # GAS_DEAL_VOLUME_PJ_PER_YR) until the contract expires; spot-gas tier
    # (uncapped, GAS_SPOT_PRICE_PER_GJ) thereafter.
    gas_volume_pj = GAS_DEAL_VOLUME_PJ_PER_YR if year <= GAS_DEAL_LAST_YEAR else None
    attach_dri_eaf(
        n,
        electrolyser_capex_per_kw=ely_capex,
        wacc=wacc_new,
        dual_fuel=True,
        ng_intensity_mwh_per_t_dri=NG_INTENSITY_MWH_PER_T_DRI,
        ng_price_per_gj=gas_p,
        ng_annual_volume_pj=gas_volume_pj,
        ng_spot_price_per_gj=GAS_SPOT_PRICE_PER_GJ,
        co2_intensity_kg_per_t_dri=CO2_INTENSITY_KG_PER_T_DRI,
        carbon_price_per_t_co2=carbon_p,
        enable_scrap=True,
        scrap_tier1_capacity_t_per_yr=SCRAP_TIER1_CAPACITY_T_PER_YR,
        scrap_tier1_price_per_t=SCRAP_TIER1_PRICE_PER_T,
        scrap_tier2_capacity_t_per_yr=SCRAP_TIER2_CAPACITY_T_PER_YR,
        scrap_tier2_price_per_t=SCRAP_TIER2_PRICE_PER_T,
        scrap_max_share=scrap_cap_this_year,
    )

    # Match trajectory structural constraints. Pre-2030 = no DRI at all; the
    # EAF runs on scrap-only. DRI shaft (both H2 and NG paths) must be zeroed
    # so the closure reads shaft_cap_out=0.
    if year < FURNACE_OPEN_YEAR:
        n.links.at["electrolyser", "p_nom_max"] = 0.0
        n.links.at["dri_plant", "p_nom_max"] = 0.0
        n.links.at["dri_plant", "p_nom"] = 0.0
        if "dri_plant_gas" in n.links.index:
            n.links.at["dri_plant_gas", "p_max_pu"] = 0.0
    n.links.at["electrolyser", "p_nom_min"] = prior["electrolyser_mw"]
    if "h2_store" in n.stores.index:
        n.stores.at["h2_store", "e_nom_min"] = prior["h2_storage_mwh"]
    # Heat-system irreversibility — mirror generate_trajectory.solve_year.
    if "electric_heater" in n.links.index:
        n.links.at["electric_heater", "p_nom_min"] = prior["electric_heater_mw"]
    if "h2_burner" in n.links.index:
        n.links.at["h2_burner", "p_nom_min"] = prior["h2_burner_mw"]

    solver_opts = dict(cfg.solver_options)
    solver_opts["run_crossover"] = "off"
    solver_opts["threads"] = 2
    status, _ = n.optimize(
        solver_name=cfg.solver,
        solver_options=solver_opts,
        extra_functionality=getattr(n, "_dri_shaft_constraint", None),
    )
    if status not in ("ok", "optimal"):
        raise RuntimeError(f"Solve failed for year {year}: {status}")

    CACHE_DIR.mkdir(exist_ok=True)
    n.export_to_netcdf(str(cache))
    print(f"  [cache save] {cache.name}", flush=True)

    return n, cfg


def _sum_series(df: pd.DataFrame, cols: list[str], idx) -> pd.Series:
    present = [c for c in cols if c in df.columns]
    if not present:
        return pd.Series(0.0, index=idx)
    return df[present].loc[idx].sum(axis=1)


def _feedstock_series(n) -> tuple[pd.Series, pd.Series]:
    """Full-year (h2_mw, gas_mw) feedstock series in MWth."""
    snaps = n.snapshots
    h2 = (
        n.links_t.p0["dri_plant"] if "dri_plant" in n.links.index
        else pd.Series(0.0, index=snaps)
    )
    gas = (
        n.links_t.p0["dri_plant_gas"] if "dri_plant_gas" in n.links.index
        else pd.Series(0.0, index=snaps)
    )
    return h2, gas


def _weekly_h2_share(n) -> pd.Series:
    """Rolling 7-day H2 feedstock share indexed by window-start snapshot."""
    h2, gas = _feedstock_series(n)
    total = h2.add(gas, fill_value=0.0)
    # 168-hour forward rolling sum, aligned to window start.
    h2_sum = h2.rolling(window=168, min_periods=168).sum().shift(-167)
    total_sum = total.rolling(window=168, min_periods=168).sum().shift(-167)
    share = h2_sum / total_sum.replace(0.0, np.nan)
    return share.dropna()


def _weekly_vre_share(n) -> pd.Series:
    """Rolling 7-day VRE (wind+solar) share of SA generation, window-start index."""
    gens = n.generators_t.p
    snaps = n.snapshots
    wind = _sum_series(gens, ["NSA_wind", "CSA_wind", "SESA_wind"], snaps)
    solar = _sum_series(gens, ["NSA_solar", "CSA_solar", "SESA_solar"], snaps)
    thermal = _sum_series(gens, ["NSA_thermal", "CSA_thermal", "SESA_thermal"], snaps)
    vre = wind + solar
    num = vre.rolling(168, min_periods=168).sum().shift(-167)
    den = (vre + thermal).rolling(168, min_periods=168).sum().shift(-167).replace(0.0, np.nan)
    return (num / den).dropna()


def _has_h2_dispatch(n) -> bool:
    """True iff the electrolyser / DRI is actually producing H2 (not LP noise)."""
    h2, gas = _feedstock_series(n)
    total = float(h2.sum()) + float(gas.sum())
    if total <= 0:
        return False
    return float(h2.sum()) / total > 0.01  # at least 1% annual H2 share


def pick_transition_week_for(n, cfg) -> pd.Timestamp:
    """Best clean-energy week for this year's own dispatch.

    If H2 is flowing to DRI: argmax of rolling 7-day H2 feedstock share.
    Otherwise (gas-only era): argmax of rolling 7-day VRE share of SA supply.
    """
    if _has_h2_dispatch(n):
        return _weekly_h2_share(n).idxmax()
    return _weekly_vre_share(n).idxmax()


def pick_dunkelflaute_week_for(n, cfg) -> pd.Timestamp:
    """Worst VRE-stressed week for this year's own dispatch.

    If H2 is flowing: argmin of rolling 7-day H2 share (gas covering for H2).
    Otherwise: argmin of rolling 7-day VRE share of SA supply.
    """
    if _has_h2_dispatch(n):
        return _weekly_h2_share(n).idxmin()
    return _weekly_vre_share(n).idxmin()


def _facility_net_import(n) -> pd.Series:
    """Net facility grid draw (MW per snapshot): positive=import, negative=export."""
    snaps = n.snapshots
    imp = (
        n.links_t.p0["grid_import"]
        if "grid_import" in n.links.index
        else pd.Series(0.0, index=snaps)
    )
    exp = (
        n.links_t.p0["grid_export"]
        if "grid_export" in n.links.index
        else pd.Series(0.0, index=snaps)
    )
    return imp - exp


def _hourly_net_emissions(
    n, grid_intensity: float = SA_GRID_CO2_INTENSITY_T_PER_MWH,
) -> pd.Series:
    """Scope 1 + market-based Scope 2 emissions per snapshot (t CO2 / h).

    Scope 1: fossil NG burned in the DRI shaft (dri_plant_gas p0 minus the
    biomethane share, × NG CO2 factor). Biomethane is biogenic (NGER scope 1
    zero) so does not enter Scope 1.
    Scope 2: net facility grid draw × SA grid CO2 intensity. Exports credit the
    same intensity (market-based displacement), so a net-negative hour means
    the facility is sinking more carbon than it emits.
    """
    snaps = n.snapshots
    gas = (
        n.links_t.p0["dri_plant_gas"]
        if "dri_plant_gas" in n.links.index
        else pd.Series(0.0, index=snaps)
    )
    biomethane = (
        n.generators_t.p["biomethane_supply"]
        if "biomethane_supply" in n.generators.index
        else pd.Series(0.0, index=snaps)
    )
    fossil = (gas - biomethane).clip(lower=0)
    # NG emission factor: kg CO2 per MWh_NG = CO2/tDRI ÷ MWh_NG/tDRI.
    ng_factor_t_per_mwh = (
        CO2_INTENSITY_KG_PER_T_DRI / NG_INTENSITY_MWH_PER_T_DRI / 1000.0
    )
    scope1 = fossil * ng_factor_t_per_mwh
    scope2 = _facility_net_import(n) * grid_intensity
    return scope1 + scope2


def _weekly_net_emissions(n) -> pd.Series:
    """Rolling 7-day net Scope 1+2 emissions (t CO2), window-start indexed."""
    hourly = _hourly_net_emissions(n)
    return hourly.rolling(168, min_periods=168).sum().shift(-167).dropna()


def pick_first_net_zero_week(
    solved: dict[int, tuple], years: list[int],
    fallback_threshold: float = CARBON_FREE_FALLBACK_THRESHOLD,
) -> tuple[int, pd.Timestamp, str] | None:
    """Earliest week where net Scope 1+2 emissions over 7 rolling days ≤ 0.

    If no scenario year achieves net-zero, fall back to the first week where
    rolling 7-day H2 feedstock share ≥ fallback_threshold (default 90%).
    Returns (year, week_start, kind) with kind ∈ {"first_net_zero",
    "first_carbon_free_fallback"}, or None if neither condition is met anywhere.
    """
    for year in sorted(years):
        n, _, _ = solved[year]
        if not _has_h2_dispatch(n):
            continue
        weekly = _weekly_net_emissions(n)
        hits = weekly[weekly <= 0]
        if not hits.empty:
            return year, hits.index[0], "first_net_zero"
    for year in sorted(years):
        n, _, _ = solved[year]
        if not _has_h2_dispatch(n):
            continue
        share = _weekly_h2_share(n)
        hits = share[share >= fallback_threshold]
        if not hits.empty:
            return year, hits.index[0], "first_carbon_free_fallback"
    return None


def extract_window(n, cfg, week_start: pd.Timestamp):
    """Slice dispatch + price series to a 7-day window starting at `week_start`."""
    snaps = n.snapshots
    end = week_start + pd.Timedelta(hours=168)
    mask = (snaps >= week_start) & (snaps < end)
    idx = snaps[mask]
    if len(idx) == 0:
        raise ValueError(f"Week start {week_start} not in snapshot range {snaps[0]}..{snaps[-1]}.")

    gens = n.generators_t.p
    wind = _sum_series(gens, ["NSA_wind", "CSA_wind", "SESA_wind"], idx)
    solar = _sum_series(gens, ["NSA_solar", "CSA_solar", "SESA_solar"], idx)
    thermal = _sum_series(gens, ["NSA_thermal", "CSA_thermal", "SESA_thermal"], idx)

    # Net interconnector imports into SA from VIC/NSW slack buses.
    # *_fwd carries SA→slack, *_rev carries slack→SA. Net import = rev - fwd.
    def _net_import(base: str) -> pd.Series:
        fwd = n.links_t.p0.get(f"{base}_fwd", pd.Series(0.0, index=n.snapshots))
        rev = n.links_t.p0.get(f"{base}_rev", pd.Series(0.0, index=n.snapshots))
        return (rev - fwd).reindex(idx).fillna(0.0)

    imports = (_net_import("heywood") + _net_import("murraylink") + _net_import("pec")).clip(lower=0)

    # SA base load (demand across all 3 subregions).
    loads = n.loads_t.p
    base_load = _sum_series(loads, ["NSA_load", "CSA_load", "SESA_load"], idx)

    # Whyalla flex loads on the facility AC bus.
    ely = n.links_t.p0["electrolyser"].loc[idx] if "electrolyser" in n.links.index else pd.Series(0.0, index=idx)
    # EAF: p2 carries AC draw (positive) because efficiency2 < 0.
    eaf_p2 = n.links_t.p2["eaf"].loc[idx] if "eaf" in n.links.index else pd.Series(0.0, index=idx)
    eaf = eaf_p2.clip(lower=0)
    # Electric resistance heater on shaft thermal bus — major load in no-gas branch.
    eh = (
        n.links_t.p0["electric_heater"].loc[idx]
        if "electric_heater" in n.links.index
        else pd.Series(0.0, index=idx)
    )

    # DRI feedstock mix: both p0 values are MWh of thermal fuel (H2 / NG).
    # Gas flow on dri_plant_gas is the sum of fossil NG + biomethane (both feed
    # the `ng` bus). Pull biomethane share separately for chart layering.
    h2_to_dri = n.links_t.p0["dri_plant"].loc[idx] if "dri_plant" in n.links.index else pd.Series(0.0, index=idx)
    gas_to_dri = (
        n.links_t.p0["dri_plant_gas"].loc[idx]
        if "dri_plant_gas" in n.links.index
        else pd.Series(0.0, index=idx)
    )
    biomethane_to_dri = (
        n.generators_t.p["biomethane_supply"].loc[idx]
        if "biomethane_supply" in n.generators.index
        else pd.Series(0.0, index=idx)
    )
    fossil_ng_to_dri = (gas_to_dri - biomethane_to_dri).clip(lower=0)

    # CSA spot price on facility's attached subregion bus.
    sub_bus = f"{cfg.grid.subregion}_ac"
    sub_price = n.buses_t.marginal_price[sub_bus].loc[idx]

    return dict(
        biomethane_to_dri=biomethane_to_dri,
        fossil_ng_to_dri=fossil_ng_to_dri,
        idx=idx,
        wind=wind,
        solar=solar,
        thermal=thermal,
        imports=imports,
        price=sub_price.clip(lower=-200, upper=800),
        ely=ely,
        eaf=eaf,
        eh=eh,
        base_load=base_load,
        gas_to_dri=gas_to_dri,
        h2_to_dri=h2_to_dri,
        sub_bus=sub_bus,
        ely_nom=float(n.links.at["electrolyser", "p_nom_opt"])
        if "electrolyser" in n.links.index
        else 0.0,
    )


def make_chart(data, label: str, week_kind: str, out_path):
    idx = data["idx"]
    n_pts = len(idx)
    price_vals = data["price"].values
    week_start = idx[0]

    fig = plt.figure(figsize=(12, 5.6))
    gs = GridSpec(
        2, 1, height_ratios=[1.25, 0.55], hspace=0.35, figure=fig,
        left=0.065, right=0.945, top=0.90, bottom=0.10,
    )
    ax_top = fig.add_subplot(gs[0])
    ax_mix = fig.add_subplot(gs[1], sharex=ax_top)

    fig.suptitle(
        f"{label}\n"
        f"A {WEEK_LABELS.get(week_kind, week_kind)} — {week_start:%d %b %Y}  |  "
        f"policy: stated carbon prices, flat gas  |  "
        f"grid: AEMO {isp_human(ISP)} transmission build",
        fontsize=11.4, y=0.985,
    )

    # ── Panel 1: SA supply stack + Whyalla flex loads (below zero) + price ────
    supply_layers = [
        ("SA wind farms",       data["wind"].values,    "#2ca25f"),
        ("SA solar farms",      data["solar"].values,   "#f9a825"),
        ("SA gas-fired power",  data["thermal"].values, "#b15928"),
        ("Imports from Vic/NSW", data["imports"].values, "#9e9e9e"),
    ]

    cum_supply = np.zeros(n_pts)
    for layer_label, vals, color in supply_layers:
        ax_top.fill_between(
            idx, cum_supply, cum_supply + vals,
            color=color, alpha=0.70, label=layer_label, linewidth=0,
        )
        cum_supply = cum_supply + vals

    ax_top.plot(
        idx, data["base_load"].values, color="#111",
        lw=1.4, label="SA homes, businesses & other industry (demand)",
    )

    eaf_vals = data["eaf"].values
    ely_vals = data["ely"].values
    eh_vals = data["eh"].values
    ax_top.fill_between(
        idx, 0, -eaf_vals, color="#6a51a3",
        alpha=0.85, label="Whyalla electric arc furnace", linewidth=0,
    )
    ax_top.fill_between(
        idx, -eaf_vals, -eaf_vals - ely_vals,
        color="#2c7fb8", alpha=0.85,
        label="Whyalla hydrogen electrolysers", linewidth=0,
    )
    ax_top.fill_between(
        idx, -eaf_vals - ely_vals, -eaf_vals - ely_vals - eh_vals,
        color="#e07b00", alpha=0.85,
        label="Whyalla shaft electric heater", linewidth=0,
    )

    supply_max = float(cum_supply.max()) if cum_supply.size else 0.0
    flex_max = float((ely_vals + eaf_vals + eh_vals).max()) if n_pts else 0.0
    ax_top.set_ylim(
        -flex_max * 1.25 - 100,
        max(supply_max, float(data["base_load"].max()) if n_pts else 0.0) * 1.05,
    )
    ax_top.axhline(0, color="#555", lw=0.8)
    ax_top.set_ylabel(
        "SA electricity supply (above zero)\nWhyalla flex consumption (below zero)   — MW",
        fontsize=9.5,
    )
    ax_top.grid(alpha=0.25)
    ax_top.xaxis.set_major_locator(mdates.DayLocator())
    ax_top.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))
    ax_top.set_xlim(idx[0], idx[-1])
    ax_top.legend(fontsize=8, loc="upper left", ncol=4, bbox_to_anchor=(0.0, -0.10))

    ax_price = ax_top.twinx()
    ax_price.plot(
        idx, price_vals, color="#d62728", lw=1.5, ls=":",
        label="Whyalla zone wholesale price", alpha=0.9,
    )
    ax_price.set_ylabel(
        "Whyalla-zone wholesale electricity price ($/MWh)",
        color="#d62728", fontsize=9.5,
    )
    ax_price.tick_params(axis="y", labelcolor="#d62728")
    ax_price.set_ylim(
        max(-50, float(price_vals.min()) - 30),
        float(price_vals.max()) * 1.15 + 20,
    )

    # ── Panel 2: DRI feedstock mix (fossil NG vs biomethane vs H2) ───────────
    fossil_mw = data["fossil_ng_to_dri"].values
    bm_mw = data["biomethane_to_dri"].values
    h2_mw = data["h2_to_dri"].values
    total_mw = fossil_mw + bm_mw + h2_mw
    mix_max = max(total_mw.max(), 1.0) * 1.12

    ax_mix.fill_between(
        idx, 0, fossil_mw, color="#b15928", alpha=0.85,
        label="Natural gas (fossil)", linewidth=0,
    )
    ax_mix.fill_between(
        idx, fossil_mw, fossil_mw + bm_mw, color="#27ae60", alpha=0.85,
        label="Biomethane (RGGO)", linewidth=0,
    )
    ax_mix.fill_between(
        idx, fossil_mw + bm_mw, fossil_mw + bm_mw + h2_mw, color="#2c7fb8",
        alpha=0.85, label="Hydrogen (from electrolysers + tanks)", linewidth=0,
    )
    ax_mix.set_ylim(0, mix_max)
    ax_mix.set_ylabel(
        "Iron-reduction\nfurnace fuel (MW)",
        fontsize=9.5,
    )
    ax_mix.grid(alpha=0.25)
    ax_mix.legend(fontsize=8, loc="upper left", ncol=3)
    ax_mix.xaxis.set_major_locator(mdates.DayLocator())
    ax_mix.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))

    fossil_total = fossil_mw.sum()
    bm_total = bm_mw.sum()
    h2_total = h2_mw.sum()
    all_total = fossil_total + bm_total + h2_total
    fossil_share = 100 * fossil_total / all_total if all_total > 0 else 0.0
    bm_share = 100 * bm_total / all_total if all_total > 0 else 0.0
    h2_share = 100 * h2_total / all_total if all_total > 0 else 0.0
    bm_str = f"  ·  {bm_share:.1f}% biomethane" if bm_total > 0 else ""
    ax_mix.text(
        0.995, 0.90,
        f"This week's furnace fuel: "
        f"{fossil_share:.1f}% fossil gas{bm_str}  ·  {h2_share:.1f}% hydrogen",
        transform=ax_mix.transAxes, ha="right", va="top",
        fontsize=10.5, fontweight="bold", color="#0a4a7a",
        bbox=dict(facecolor="white", alpha=0.85, edgecolor="#aaa", pad=3),
    )

    fig.savefig(out_path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    print(f"  saved {out_path.name}")


def main(years: list[int] | None = None, policy: str = POLICY, isp: str = ISP):
    if not TRAJ_CSV.exists():
        raise FileNotFoundError(f"Missing trajectory CSV: {TRAJ_CSV}")
    traj = pd.read_csv(TRAJ_CSV)
    branch = traj[(traj.scenario == policy) & (traj.isp_scenario == isp)].sort_values("year")
    if branch.empty:
        raise RuntimeError(f"No rows in trajectory.csv for {policy} / {isp}")

    if years is None:
        years = [int(y) for y in branch.year.tolist()]
    else:
        missing = [y for y in years if y not in branch.year.values]
        if missing:
            raise ValueError(
                f"Years {missing} not present in trajectory.csv for {policy} / {isp}. "
                f"Available: {branch.year.tolist()}"
            )

    # ── Solve each year once, cache (network, cfg, label, capacity) ──────────
    solved: dict[int, tuple] = {}
    capacities: dict[int, float] = {}
    for year in years:
        row = branch[branch.year == year].iloc[0]
        prior = _prior_build(branch, year)
        print(
            f"\n[{year}] solving: CAPEX=${row.capex_per_kw:.0f}/kW  gas=${row.gas_price:.1f}  "
            f"C=${row.carbon_price:.1f}/t  WACC={row.discount_rate:.2%}  "
            f"prior_ely={prior['electrolyser_mw']:.0f} MW  "
            f"prior_store={prior['h2_storage_mwh']:.0f} MWh  "
            f"prior_eh={prior['electric_heater_mw']:.0f} MW  "
            f"prior_hb={prior['h2_burner_mw']:.0f} MW",
            flush=True,
        )
        n, cfg = solve_scenario(year, row, prior)
        label = _scenario_label(year, row)
        ely_cap = (
            float(n.links.at["electrolyser", "p_nom_opt"])
            if "electrolyser" in n.links.index
            else 0.0
        )
        capacities[year] = ely_cap
        solved[year] = (n, cfg, label)
        print(f"  solved: ely={ely_cap:.0f} MW", flush=True)

    # ── Pick weeks independently per year (dispatch matters, not calendar dates) ─
    week_picks: dict[str, dict[int, pd.Timestamp]] = {"transition": {}, "dunkelflaute": {}}
    for year in years:
        n, cfg, _ = solved[year]
        tr = pick_transition_week_for(n, cfg)
        df = pick_dunkelflaute_week_for(n, cfg)
        week_picks["transition"][year] = tr
        week_picks["dunkelflaute"][year] = df
        basis = "H2 share" if _has_h2_dispatch(n) else "VRE share"
        print(
            f"[{year}] picks by {basis}: "
            f"transition={tr:%d %b}  |  dunkelflaute={df:%d %b}",
            flush=True,
        )

    # ── Milestone: first net-zero-carbon-steel week (Scope 1 + Scope 2) ─────
    # Falls back to "first ≥90% hydrogen feedstock" week when the trajectory
    # never gets below net-zero on a market-based basis.
    milestone = pick_first_net_zero_week(solved, years)
    if milestone is None:
        print("\n[milestone] no net-zero or 90%-H2 week across solved years",
              flush=True)
    else:
        m_year, m_week, m_kind = milestone
        m_n, m_cfg, m_label = solved[m_year]
        if m_kind == "first_net_zero":
            weekly = _weekly_net_emissions(m_n)
            week_net_t = float(weekly.loc[m_week])
            print(
                f"\n[milestone] first net-zero-carbon steel week: FY{m_year} — "
                f"{m_week:%d %b %Y}  (net Scope 1+2 = {week_net_t:,.0f} t CO2/wk)",
                flush=True,
            )
        else:
            share = _weekly_h2_share(m_n)
            week_h2 = float(share.loc[m_week]) * 100.0
            print(
                f"\n[milestone] net-zero unreachable; falling back to first "
                f"≥90% H2 week: FY{m_year} — {m_week:%d %b %Y}  "
                f"(week H2 share = {week_h2:.1f}%)",
                flush=True,
            )
        data = extract_window(m_n, m_cfg, m_week)
        out = HERE / f"chart_dispatch_{m_year}_{m_kind}.png"
        make_chart(data, m_label, m_kind, out)

    # ── Render ────────────────────────────────────────────────────────────────
    for week_kind, ts_by_year in week_picks.items():
        print(f"\n── Rendering {week_kind} week ───────────────────────────────",
              flush=True)
        for year in years:
            n, cfg, label = solved[year]
            week_start = ts_by_year[year]
            data = extract_window(n, cfg, week_start)
            print(
                f"  [{year} / {week_kind}] avg flex draw: "
                f"ely={data['ely'].mean():.0f} MW  eaf={data['eaf'].mean():.0f} MW  "
                f"eh={data['eh'].mean():.0f} MW  "
                f"h2 share={data['h2_to_dri'].sum() / max(data['h2_to_dri'].sum() + data['gas_to_dri'].sum(), 1e-9):.1%}  "
                f"mean price={data['price'].mean():.1f} $/MWh",
                flush=True,
            )
            out = HERE / f"chart_dispatch_{year}_{week_kind}.png"
            make_chart(data, label, week_kind, out)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Render SA dispatch charts for trajectory scenario years.")
    parser.add_argument(
        "--years", type=int, nargs="+", default=None,
        help="Scenario years to render (default: all years in trajectory.csv for the chosen branch).",
    )
    parser.add_argument("--policy", default=POLICY, help=f"Policy scenario name (default: {POLICY!r}).")
    parser.add_argument("--isp", default=ISP, help=f"ISP scenario key (default: {ISP!r}).")
    args = parser.parse_args()
    main(years=args.years, policy=args.policy, isp=args.isp)
