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

Two contrasting weeks are rendered per scenario year:

  - "clean-energy week" — a sunny, windy stretch the storage build-out is
    designed for. Picked to maximise (late-year H2 share − early-year H2 share).
  - "dunkelflaute" — a still, cloudy stretch where wind and solar fall short.
    Picked to minimise the H2 share in the most-mature scenario year so the
    reader can see gas stepping in as the reliability backstop.

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
    NG_INTENSITY_MWH_PER_T_DRI,
    CO2_INTENSITY_KG_PER_T_DRI,
    FURNACE_OPEN_YEAR,
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
}


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
            f"{year} — gas-only phase (before the hydrogen furnace opens; "
            f"the electric arc furnace is Whyalla's only flexible load)"
        )
    return (
        f"{year} — {h2_pct:.0f}% hydrogen over the year  |  "
        f"{ely:.0f} MW of electrolysers, {store / 1000:.1f} GWh of hydrogen storage"
    )


def _prior_build(traj: pd.DataFrame, year: int) -> tuple[float, float]:
    """Cumulative (electrolyser_mw, h2_storage_mwh) built in years strictly before `year`."""
    prior = traj[traj.year < year]
    if prior.empty:
        return 0.0, 0.0
    last = prior.iloc[-1]
    return float(last.electrolyser_mw), float(last.h2_storage_mwh)


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
    }, sort_keys=True)
    digest = hashlib.md5(key_blob.encode()).hexdigest()[:10]
    return CACHE_DIR / f"dispatch_{year}_{digest}.nc"


def solve_scenario(
    year: int,
    traj_row: pd.Series,
    prior_ely: float,
    prior_store: float,
    *,
    policy: str = POLICY,
    isp: str = ISP,
    use_cache: bool = True,
):
    """Build + solve a single full-year sa_dispatch scenario from a trajectory row.

    Result is cached to netcdf so re-runs (for terminology / styling edits)
    skip the ~5-10 min HiGHS solve.
    """
    ely_capex = float(traj_row.capex_per_kw)
    gas_p = float(traj_row.gas_price)
    carbon_p = float(traj_row.carbon_price)
    wacc_new = float(traj_row.discount_rate)

    cache_row = traj_row.copy()
    cache_row["_prior_ely"] = prior_ely
    cache_row["_prior_store"] = prior_store
    cache = _cache_path(year, policy, isp, cache_row)
    if use_cache and cache.exists():
        cfg = default_config(
            grid_mode="sa_dispatch", model_year=year, snapshot_mode="full_year"
        )
        cfg = copy.deepcopy(cfg)
        cfg.scenario.file_token = ISP_SCENARIOS[isp]
        cfg.pypsa_wacc = 0.09
        n = pypsa.Network(str(cache))
        print(f"  [cache hit] loaded {cache.name}", flush=True)
        return n, cfg

    cfg = default_config(
        grid_mode="sa_dispatch", model_year=year, snapshot_mode="full_year"
    )
    cfg = copy.deepcopy(cfg)
    cfg.scenario.file_token = ISP_SCENARIOS[isp]
    cfg.pypsa_wacc = 0.09  # NOAK for facility base

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg)
    attach_dri_eaf(
        n,
        electrolyser_capex_per_kw=ely_capex,
        wacc=wacc_new,
        dual_fuel=True,
        ng_intensity_mwh_per_t_dri=NG_INTENSITY_MWH_PER_T_DRI,
        ng_price_per_gj=gas_p,
        co2_intensity_kg_per_t_dri=CO2_INTENSITY_KG_PER_T_DRI,
        carbon_price_per_t_co2=carbon_p,
    )

    # Match trajectory structural constraints.
    if year < FURNACE_OPEN_YEAR:
        n.links.at["electrolyser", "p_nom_max"] = 0.0
        n.links.at["dri_plant", "p_min_pu"] = 0.0
    n.links.at["electrolyser", "p_nom_min"] = prior_ely
    if "h2_store" in n.stores.index:
        n.stores.at["h2_store", "e_nom_min"] = prior_store

    solver_opts = dict(cfg.solver_options)
    solver_opts["run_crossover"] = "off"
    solver_opts["threads"] = 2
    status, _ = n.optimize(solver_name=cfg.solver, solver_options=solver_opts)
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


def _calendar_key(ts) -> str:
    return f"{ts.month:02d}-{ts.day:02d}-{ts.hour:02d}"


def _ts_by_key(n, key: str):
    """Return the first snapshot in n matching month-day-hour key."""
    snaps = n.snapshots
    month, day, hour = (int(p) for p in key.split("-"))
    hit = snaps[
        (snaps.month == month) & (snaps.day == day) & (snaps.hour == hour)
    ]
    if len(hit):
        return hit[0]
    # Fall back: closest same-day match, or just the first snapshot.
    fallback = snaps[(snaps.month == month) & (snaps.day == day)]
    return fallback[0] if len(fallback) else snaps[0]


def _keyed_weekly_df(s: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({
        "ts": s.index,
        "key": [_calendar_key(t) for t in s.index],
        "h2_share": s.values,
    })


def _anchor_years(
    networks: dict[int, "pypsa.Network"], capacities: dict[int, float]
) -> tuple[int | None, int | None]:
    """(earliest, latest) year with electrolyser p_nom_opt > ELY_ANCHOR_MW."""
    eligible = sorted(y for y, mw in capacities.items() if mw > ELY_ANCHOR_MW)
    if len(eligible) < 2:
        return (eligible[0] if eligible else None), (eligible[0] if eligible else None)
    return eligible[0], eligible[-1]


def pick_transition_week(
    networks: dict[int, "pypsa.Network"], capacities: dict[int, float]
) -> tuple[str, dict[int, pd.Timestamp]] | None:
    """Calendar week maximising (late-year H2 share − early-year H2 share).

    Returns (calendar_key, {year: week_start_ts}) or None if only one (or zero)
    scenario years actually built electrolyser capacity.
    """
    early, late = _anchor_years(networks, capacities)
    if early is None or late is None or early == late:
        return None

    share_early = _keyed_weekly_df(_weekly_h2_share(networks[early]))
    share_late = _keyed_weekly_df(_weekly_h2_share(networks[late]))
    merged = share_early.rename(columns={"ts": "ts_e", "h2_share": "h2_e"}).merge(
        share_late.rename(columns={"ts": "ts_l", "h2_share": "h2_l"}), on="key"
    )
    merged["delta"] = merged["h2_l"] - merged["h2_e"]
    viable = merged[(merged["h2_e"] > 0.4) & (merged["h2_l"] > 0.4)]
    pool = viable if not viable.empty else merged
    best = pool.sort_values("delta", ascending=False).iloc[0]

    print(
        f"\n[transition] {best['key']}: "
        f"{early} H2={best['h2_e']:.1%}  →  {late} H2={best['h2_l']:.1%}  "
        f"(Δ={best['delta']:+.1%})",
        flush=True,
    )

    ts_by_year = {y: _ts_by_key(networks[y], best["key"]) for y in networks}
    return best["key"], ts_by_year


def pick_dunkelflaute_week(
    networks: dict[int, "pypsa.Network"], capacities: dict[int, float]
) -> tuple[str, dict[int, pd.Timestamp]] | None:
    """Calendar week minimising H2 share in the latest-built scenario.

    Gas backs up H2 when VRE + storage fall short. We locate that in the most
    mature build year (highest electrolyser capacity), then pin the same
    calendar week on every other scenario so the chart compares like-for-like.
    """
    eligible = sorted(y for y, mw in capacities.items() if mw > ELY_ANCHOR_MW)
    if not eligible:
        return None
    anchor = eligible[-1]

    share_anchor = _keyed_weekly_df(_weekly_h2_share(networks[anchor]))
    # Lowest H2 share = highest gas share = reliability stress.
    worst = share_anchor.sort_values("h2_share", ascending=True).iloc[0]

    print(
        f"\n[dunkelflaute] {worst['key']}: "
        f"{anchor} H2 share={worst['h2_share']:.1%} "
        f"(gas share={1.0 - worst['h2_share']:.1%}) — most stressed week",
        flush=True,
    )

    ts_by_year = {y: _ts_by_key(networks[y], worst["key"]) for y in networks}
    return worst["key"], ts_by_year


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

    # DRI feedstock mix: both p0 values are MWh of thermal fuel (H2 / NG).
    h2_to_dri = n.links_t.p0["dri_plant"].loc[idx] if "dri_plant" in n.links.index else pd.Series(0.0, index=idx)
    gas_to_dri = (
        n.links_t.p0["dri_plant_gas"].loc[idx]
        if "dri_plant_gas" in n.links.index
        else pd.Series(0.0, index=idx)
    )

    # CSA spot price on facility's attached subregion bus.
    sub_bus = f"{cfg.grid.subregion}_ac"
    sub_price = n.buses_t.marginal_price[sub_bus].loc[idx]

    return dict(
        idx=idx,
        wind=wind,
        solar=solar,
        thermal=thermal,
        imports=imports,
        price=sub_price.clip(lower=-200, upper=800),
        ely=ely,
        eaf=eaf,
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
    ax_top.fill_between(
        idx, 0, -eaf_vals, color="#6a51a3",
        alpha=0.85, label="Whyalla electric arc furnace", linewidth=0,
    )
    ax_top.fill_between(
        idx, -eaf_vals, -eaf_vals - ely_vals,
        color="#2c7fb8", alpha=0.85,
        label="Whyalla hydrogen electrolysers", linewidth=0,
    )

    supply_max = float(cum_supply.max()) if cum_supply.size else 0.0
    flex_max = float((ely_vals + eaf_vals).max()) if n_pts else 0.0
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

    # ── Panel 2: DRI feedstock mix (gas vs H2) ────────────────────────────────
    gas_mw = data["gas_to_dri"].values
    h2_mw = data["h2_to_dri"].values
    total_mw = gas_mw + h2_mw
    mix_max = max(total_mw.max(), 1.0) * 1.12

    ax_mix.fill_between(
        idx, 0, gas_mw, color="#b15928", alpha=0.85,
        label="Natural gas", linewidth=0,
    )
    ax_mix.fill_between(
        idx, gas_mw, gas_mw + h2_mw, color="#2c7fb8",
        alpha=0.85, label="Hydrogen (from electrolysers + tanks)", linewidth=0,
    )
    ax_mix.set_ylim(0, mix_max)
    ax_mix.set_ylabel(
        "Iron-reduction\nfurnace fuel (MW)",
        fontsize=9.5,
    )
    ax_mix.grid(alpha=0.25)
    ax_mix.legend(fontsize=8, loc="upper left", ncol=2)
    ax_mix.xaxis.set_major_locator(mdates.DayLocator())
    ax_mix.xaxis.set_major_formatter(mdates.DateFormatter("%a %d %b"))

    gas_total = gas_mw.sum()
    h2_total = h2_mw.sum()
    all_total = gas_total + h2_total
    h2_share = 100 * h2_total / all_total if all_total > 0 else 0.0
    ax_mix.text(
        0.995, 0.90,
        f"This week's furnace fuel: "
        f"{100 - h2_share:.1f}% natural gas  ·  {h2_share:.1f}% hydrogen",
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
        prior_ely, prior_store = _prior_build(branch, year)
        print(
            f"\n[{year}] solving: CAPEX=${row.capex_per_kw:.0f}/kW  gas=${row.gas_price:.1f}  "
            f"C=${row.carbon_price:.1f}/t  WACC={row.discount_rate:.2%}  "
            f"prior_ely={prior_ely:.0f} MW  prior_store={prior_store:.0f} MWh",
            flush=True,
        )
        n, cfg = solve_scenario(year, row, prior_ely, prior_store)
        label = _scenario_label(year, row)
        ely_cap = (
            float(n.links.at["electrolyser", "p_nom_opt"])
            if "electrolyser" in n.links.index
            else 0.0
        )
        capacities[year] = ely_cap
        solved[year] = (n, cfg, label)
        print(f"  solved: ely={ely_cap:.0f} MW", flush=True)

    networks = {y: solved[y][0] for y in years}

    # ── Pick weeks ────────────────────────────────────────────────────────────
    week_picks: dict[str, dict[int, pd.Timestamp] | None] = {}
    transition = pick_transition_week(networks, capacities)
    week_picks["transition"] = transition[1] if transition else None

    dunkelflaute = pick_dunkelflaute_week(networks, capacities)
    week_picks["dunkelflaute"] = dunkelflaute[1] if dunkelflaute else None

    # ── Render ────────────────────────────────────────────────────────────────
    for week_kind, ts_by_year in week_picks.items():
        if ts_by_year is None:
            print(f"\n[skip {week_kind}] not enough scenarios with electrolyser built",
                  flush=True)
            continue
        print(f"\n── Rendering {week_kind} week ───────────────────────────────",
              flush=True)
        for year in years:
            n, cfg, label = solved[year]
            week_start = ts_by_year[year]
            data = extract_window(n, cfg, week_start)
            print(
                f"  [{year} / {week_kind}] avg flex draw: "
                f"ely={data['ely'].mean():.0f} MW  eaf={data['eaf'].mean():.0f} MW  "
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
