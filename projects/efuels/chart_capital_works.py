"""Capital works schedule + Gantt chart from the efuels trajectory output.

Reads ``trajectory.csv``, filters to one scenario branch, and renders:
  • Gantt (top): one row per asset, bars at each tranche's build year with
    capacity + $AUD capex annotation.
  • Stacked bar (bottom): annual programme capex ($M), coloured by asset.

Mirrors ``projects/dri-eaf/chart_capital_works.py`` style/layout so the
two projects read as a single programme.

Assets covered (tranche-extracted by year-on-year diff within a branch):
  Process       : Electrolyser, MeOH synthesis, Refinery (per product),
                  H₂ storage, MeOH storage, CO₂ storage.
  Heat          : Electric heater, H₂ burner, CST solar field, CST turbine.
  Facility VRE  : Wind, Solar, Battery (power+energy combined).
  Biofuels      : HTL (steelworks + Port Bonython sites), HEFA, Pyrolysis,
                  Biomass gasification.

Per-unit capex values are hardcoded here to match the source (process
chain / heat_integration / biofuels/physics / whyalla_pypsa config) —
edit both together if the source changes.

Usage:
    uv run python chart_capital_works.py \\
        --scenario policy_stated \\
        --out chart_capital_works.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd

HERE = Path(__file__).parent
TRAJ_CSV = HERE / "trajectory.csv"
HOURS_PER_YEAR = 8760

# ── Per-unit capex (must track source code) ──────────────────────────────
# whyalla_pypsa/run.py default_config
WIND_CAPEX_PER_KW    = 2_200.0
SOLAR_CAPEX_PER_KW   = 1_100.0
BATTP_CAPEX_PER_KW   = 500.0
BATTE_CAPEX_PER_KWH  = 250.0
H2_STORE_CAPEX_PER_MWH = 20_000.0      # compressed-vessel farm; HJP reference
GRID_LINK_CAPEX_PER_MW = 400_000.0

# process_chain.attach_efuels defaults
SYNTH_CAPEX_PER_T_MEOH_YR = 800.0       # AUD/(t MeOH/yr)
REFINERY_CAPEX_PER_T_YR   = 400.0       # AUD/(t product/yr)
CO2_STORAGE_CAPEX_PER_T   = 150.0       # AUD/t
MEOH_STORAGE_CAPEX_PER_T  = 150.0       # AUD/t
MEOH_LHV_MWH_PER_T        = 19.9 / 3.6  # 5.528

# heat_integration constants
ELECTRIC_HEATER_CAPEX_PER_KW_TH = 400.0
H2_BURNER_CAPEX_PER_KW_TH = 30.0
CST_CAPEX_PER_KW_TH = 4_300.0
STEAM_TURBINE_CAPEX_PER_KW_EL = 2_000.0

SHARED_HCR_CAPEX_PER_T_YR = 150.0    # shared finishing hydrocracker block

# biofuels/physics constants
HTL_CAPEX_PER_T_DRY_YR      = 95_000.0
HEFA_CAPEX_PER_T_OIL_YR     = 3_500.0
PYROLYSIS_CAPEX_PER_T_DRY_YR = 2_000.0
GASIFICATION_CAPEX_PER_T_DRY_YR = 1_500.0

# ASF / hydrocracked-FT product fractions (process_chain._attach_asf_products)
HYDROCRACKED_FT_FRACS = {"naphtha": 0.15, "kero": 0.45, "diesel": 0.35, "wax": 0.05}
HYDROCRACKED_FT_MASS_YIELD = 0.43

# MeOH synthesis capacity conversion: trajectory stores synth_mw in MW H₂
# input. Per-MW H₂ annual MeOH throughput:
#   h2_input_per_t_meoh = (0.1875 × 33.333) / 0.83 = 7.527 MWh H₂/t MeOH
#   t MeOH / yr / MW H₂ = 8760 / 7.527 = 1163.8
_H2_INPUT_PER_T_MEOH = (0.1875 * 33.333) / 0.83
T_MEOH_PER_YR_PER_MW_H2 = HOURS_PER_YEAR / _H2_INPUT_PER_T_MEOH


def _dollars_M(x: float) -> str:
    if abs(x) >= 1e9:
        return f"${x/1e9:.2f} B"
    return f"${x/1e6:.0f} M" if abs(x) >= 1e7 else f"${x/1e6:.1f} M"


# ── Capex resolvers ──────────────────────────────────────────────────────
# Each returns $AUD for a given delta row (one year's new capacity).

def _capex_ely(row, delta_mw):
    # electrolyser capex varies by year (capex_per_kw column)
    return delta_mw * float(row.get("capex_per_kw", 1500.0)) * 1000.0

def _capex_synth_h2_mw(row, delta_mw_h2):
    # delta_mw_h2 = new MW of H₂ input capacity. Convert to t MeOH/yr, × AUD/(t/yr).
    return delta_mw_h2 * T_MEOH_PER_YR_PER_MW_H2 * SYNTH_CAPEX_PER_T_MEOH_YR

def _capex_refinery_mw(_, delta_mw_meoh):
    # Single refinery Link — weighted conditioning capex across the FT
    # slate (non-wax gets the HCR-share deduction; wax bypasses HCR).
    t_prod_per_yr = (
        delta_mw_meoh * HOURS_PER_YEAR / MEOH_LHV_MWH_PER_T
        * HYDROCRACKED_FT_MASS_YIELD
    )
    non_wax = 1.0 - HYDROCRACKED_FT_FRACS["wax"]
    weighted = ((REFINERY_CAPEX_PER_T_YR - SHARED_HCR_CAPEX_PER_T_YR) * non_wax
                + REFINERY_CAPEX_PER_T_YR * HYDROCRACKED_FT_FRACS["wax"])
    return t_prod_per_yr * weighted

def _capex_h2_store(_, delta_mwh):
    return delta_mwh * H2_STORE_CAPEX_PER_MWH

def _capex_meoh_store_mwh(_, delta_mwh):
    # trajectory stores meoh_store_mwh (LHV MWh). Convert to tonnes for AUD/t capex.
    tonnes = delta_mwh / MEOH_LHV_MWH_PER_T
    return tonnes * MEOH_STORAGE_CAPEX_PER_T

def _capex_co2_store(_, delta_t):
    return delta_t * CO2_STORAGE_CAPEX_PER_T

def _capex_eh(_, delta_mw):
    return delta_mw * ELECTRIC_HEATER_CAPEX_PER_KW_TH * 1000.0

def _capex_hb(_, delta_mw):
    return delta_mw * H2_BURNER_CAPEX_PER_KW_TH * 1000.0

def _capex_cst(_, delta_mw):
    return delta_mw * CST_CAPEX_PER_KW_TH * 1000.0

def _capex_turbine(_, delta_mw):
    return delta_mw * STEAM_TURBINE_CAPEX_PER_KW_EL * 1000.0

def _capex_wind(_, delta_mw):
    return delta_mw * WIND_CAPEX_PER_KW * 1000.0

def _capex_solar(_, delta_mw):
    return delta_mw * SOLAR_CAPEX_PER_KW * 1000.0

def _capex_battery(_, delta_p_mw, delta_e_mwh):
    # Combine power + energy into one row — both bought together.
    return delta_p_mw * BATTP_CAPEX_PER_KW * 1000.0 + delta_e_mwh * BATTE_CAPEX_PER_KWH * 1000.0

def _capex_htl_hr(_, delta_t_dry_per_hr):
    # HTL capex is per (t_dry/yr). Convert delta_t/hr × hours_per_year → t/yr.
    return delta_t_dry_per_hr * HOURS_PER_YEAR * HTL_CAPEX_PER_T_DRY_YR

def _capex_hefa_hr(_, delta_t_oil_per_hr):
    return delta_t_oil_per_hr * HOURS_PER_YEAR * HEFA_CAPEX_PER_T_OIL_YR

def _capex_pyrolysis_hr(_, delta_t_dry_per_hr):
    return delta_t_dry_per_hr * HOURS_PER_YEAR * PYROLYSIS_CAPEX_PER_T_DRY_YR

def _capex_gas_hr(_, delta_t_dry_per_hr):
    return delta_t_dry_per_hr * HOURS_PER_YEAR * GASIFICATION_CAPEX_PER_T_DRY_YR

def _capex_shared_hcr_hr(_, delta_t_per_hr):
    # Shared finishing hydrocracker — capex per (t product/yr) × hrs/yr.
    return delta_t_per_hr * HOURS_PER_YEAR * SHARED_HCR_CAPEX_PER_T_YR


# ── Row schema: (label, capacity col, unit, capex_fn, color) ─────────────
# capex_fn takes (row, delta_capacity) and returns $AUD. Some rows need
# multi-argument capex (batteries) — handled inline in build_schedule.
ROWS = [
    # Process
    ("Electrolyser",            "electrolyser_mw",      "MW",     "ely",          "#1f77b4"),
    ("MeOH synthesis",          "synth_mw",             "MW_H₂",  "synth",        "#17becf"),
    ("Refinery (FT+upgrading)", "refinery_mw",          "MW_MeOH","refinery",     "#d62728"),
    ("Shared HCR: naphtha",     "shared_hcr_naphtha_t_per_hr", "t/hr", "shared_hcr", "#f7b6d2"),
    ("Shared HCR: kero",        "shared_hcr_kero_t_per_hr",    "t/hr", "shared_hcr", "#e377c2"),
    ("Shared HCR: diesel",      "shared_hcr_diesel_t_per_hr",  "t/hr", "shared_hcr", "#d62728"),
    ("H₂ storage",              "h2_store_mwh",         "MWh",    "h2_store",     "#9467bd"),
    ("MeOH storage",            "meoh_store_mwh",       "MWh",    "meoh_store",   "#c5b0d5"),
    ("CO₂ storage",             "co2_store_t",          "t",      "co2_store",    "#8c8c00"),
    # Heat integration
    ("Electric heater",         "electric_heater_mw_th","MW_th",  "eh",           "#bcbd22"),
    ("H₂ burner",               "h2_burner_mw_th",      "MW_th",  "hb",           "#ffbf00"),
    ("CST solar field",         "cst_mw_th",            "MW_th",  "cst",          "#ff7f0e"),
    ("CST steam turbine",       "cst_turbine_mw_el",    "MW_el",  "turbine",      "#e377c2"),
    # Facility VRE
    ("Wind",                    "wind_mw",              "MW",     "wind",         "#2ca02c"),
    ("Solar PV",                "solar_mw",             "MW",     "solar",        "#ffd43b"),
    ("Battery",                 "battery_charge_mw",    "MW",     "battery",      "#d62728"),  # special (see build)
    # Biofuels
    ("HTL @ steelworks",        "htl_steelworks_cap_t_dry_per_hr", "t_dry/hr", "htl",  "#2ca02c"),
    ("HTL @ Port Bonython",     "htl_port_bonython_cap_t_dry_per_hr", "t_dry/hr", "htl", "#7fcf6e"),
    ("HEFA (halophyte)",        "hefa_cap_t_oil_per_hr","t_oil/hr", "hefa",       "#1abc9c"),
    ("Pyrolysis (mallee+SB)",   "pyrolysis_cap_t_dry_per_hr", "t_dry/hr", "pyrolysis", "#3498db"),
    ("Biomass gasification",    "gasification_cap_t_dry_per_hr", "t_dry/hr", "gasification", "#34495e"),
]

_CAPEX_FNS = {
    "ely":             _capex_ely,
    "synth":           _capex_synth_h2_mw,
    "refinery":        _capex_refinery_mw,
    "shared_hcr":      _capex_shared_hcr_hr,
    "h2_store":        _capex_h2_store,
    "meoh_store":      _capex_meoh_store_mwh,
    "co2_store":       _capex_co2_store,
    "eh":              _capex_eh,
    "hb":              _capex_hb,
    "cst":             _capex_cst,
    "turbine":         _capex_turbine,
    "wind":            _capex_wind,
    "solar":           _capex_solar,
    # "battery" handled inline (power + energy)
    "htl":             _capex_htl_hr,
    "hefa":            _capex_hefa_hr,
    "pyrolysis":       _capex_pyrolysis_hr,
    "gasification":    _capex_gas_hr,
}


# Minimum capex to register a tranche on the chart (filters LP numerical noise).
MIN_CAPEX_AUD = 500_000.0


def build_schedule(df: pd.DataFrame) -> pd.DataFrame:
    """Return one row per (asset × year) with capacity-delta + $AUD capex."""
    df = df.sort_values("year").reset_index(drop=True)
    records: list[dict] = []

    for label, cap_col, unit, kind, _color in ROWS:
        if cap_col is None or cap_col not in df.columns:
            continue
        cap = pd.to_numeric(df[cap_col], errors="coerce").fillna(0.0).values
        prev = np.concatenate([[0.0], cap[:-1]])
        delta = np.maximum(cap - prev, 0.0)   # monotone irreversibility
        for i, dv in enumerate(delta):
            if dv <= 1e-6:
                continue
            row = df.iloc[i]
            if kind == "battery":
                # Combine battery power + energy on one row.
                dv_e = 0.0
                if "battery_store_mwh" in df.columns:
                    e_cap = pd.to_numeric(df["battery_store_mwh"],
                                          errors="coerce").fillna(0.0).values
                    e_prev = np.concatenate([[0.0], e_cap[:-1]])
                    dv_e = max(e_cap[i] - e_prev[i], 0.0)
                aud = _capex_battery(row, dv, dv_e)
            else:
                fn = _CAPEX_FNS.get(kind)
                if fn is None:
                    continue
                aud = fn(row, dv)
            if aud < MIN_CAPEX_AUD:
                continue
            records.append({
                "asset": label, "year": int(row["year"]),
                "capacity": dv, "unit": unit,
                "capex_aud": aud,
            })

    return pd.DataFrame.from_records(records)


def plot_gantt(schedule: pd.DataFrame, df: pd.DataFrame, title: str, out: Path):
    years = sorted(df["year"].unique().tolist())
    year_min, year_max = min(years), max(years)
    gantt_end = year_max + 3
    rows_display = [r for r in ROWS]
    n_rows = len(rows_display)

    fig = plt.figure(figsize=(17, 14))
    gs = fig.add_gridspec(2, 1, height_ratios=[n_rows, 5], hspace=0.3)
    ax_g = fig.add_subplot(gs[0])
    ax_b = fig.add_subplot(gs[1])

    color_by_label = {label: c for label, _, _, _, c in rows_display}

    for i, (label, cap_col, unit, _kind, color) in enumerate(rows_display):
        y = n_rows - 1 - i
        ax_g.hlines(y, year_min - 1, gantt_end, colors="lightgray",
                    linewidth=0.5, alpha=0.5)
        sub = schedule[schedule["asset"] == label].sort_values("year")
        if not sub.empty:
            first_year = int(sub["year"].min())
            ax_g.hlines(y, first_year, gantt_end,
                        colors=color, linewidth=1.6, alpha=0.45, zorder=2)
        for _, rec in sub.iterrows():
            x = rec["year"]
            ax_g.barh(y, width=0.7, left=x - 0.35, height=0.55,
                      color=color, edgecolor="black", linewidth=0.7, zorder=3)
            # Dollar amount only, above the marker, compact and horizontal.
            ax_g.text(x, y + 0.38, _dollars_M(rec["capex_aud"]),
                      fontsize=7.8, ha="center", va="bottom",
                      fontweight="bold")

        # End-of-programme cumulative capacity annotation at the right margin.
        if cap_col and cap_col in df.columns:
            final_cap = pd.to_numeric(df[cap_col], errors="coerce").fillna(0.0).iloc[-1]
            if final_cap > 1e-3:
                if unit.startswith("t_") or unit == "t":
                    cap_str = f"{final_cap:,.1f} {unit}"
                elif final_cap >= 1000:
                    cap_str = f"{final_cap:,.0f} {unit}"
                else:
                    cap_str = f"{final_cap:,.1f} {unit}"
                ax_g.text(gantt_end - 0.3, y, f"Σ {cap_str}",
                          fontsize=8, ha="right", va="center",
                          color="black", fontweight="bold",
                          bbox=dict(boxstyle="round,pad=0.2",
                                    facecolor="white", edgecolor=color,
                                    linewidth=1.0))

    ax_g.set_yticks(range(n_rows))
    ax_g.set_yticklabels([label for label, *_ in reversed(rows_display)],
                          fontsize=9.5)
    ax_g.set_xlim(year_min - 1, gantt_end)
    ax_g.set_ylim(-0.7, n_rows - 0.3)
    ax_g.set_xticks(years)
    ax_g.tick_params(axis="x", labelsize=10)
    ax_g.set_xlabel("Year")
    ax_g.set_title(title, fontsize=13, fontweight="bold")
    ax_g.grid(axis="x", linestyle=":", color="gray", alpha=0.5)
    ax_g.set_axisbelow(True)

    # Stacked bar: annual capex $M by asset
    capex_pivot = (
        schedule.pivot_table(index="year", columns="asset",
                              values="capex_aud", aggfunc="sum")
        .fillna(0.0).reindex(years, fill_value=0.0) / 1e6
    )
    asset_order = [label for label, *_ in rows_display
                    if label in capex_pivot.columns]
    bottom = np.zeros(len(years))
    for label in asset_order:
        vals = capex_pivot[label].values
        ax_b.bar(years, vals, bottom=bottom, width=0.7,
                 color=color_by_label[label], label=label,
                 edgecolor="white", linewidth=0.5)
        bottom = bottom + vals
    for i, yr in enumerate(years):
        tot = bottom[i]
        if tot > 0:
            ax_b.text(yr, tot + max(bottom.max() * 0.015, 1),
                      f"{_dollars_M(tot*1e6)}",
                      ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax_b.set_xticks(years)
    ax_b.set_ylabel("Annual capex ($M AUD)")
    ax_b.set_xlabel("Year")
    ax_b.grid(axis="y", linestyle=":", alpha=0.5)
    ax_b.set_axisbelow(True)

    handles = [
        mpatches.Patch(facecolor=color_by_label[label], edgecolor="black", label=label)
        for label in asset_order
    ]
    ax_b.legend(handles=handles, loc="upper left", ncol=3,
                fontsize=7.5, frameon=False)

    grand_total = schedule["capex_aud"].sum()
    ax_g.text(0.99, 0.02,
              f"Total programme capex: {_dollars_M(grand_total)}",
              transform=ax_g.transAxes, fontsize=11, fontweight="bold",
              ha="right", va="bottom",
              bbox=dict(boxstyle="round,pad=0.4",
                        facecolor="white", edgecolor="gray"))

    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="policy_stated")
    parser.add_argument("--csv", default=str(TRAJ_CSV))
    parser.add_argument("--out", default=str(HERE / "chart_capital_works.png"))
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    branch = df[df["scenario"] == args.scenario].copy().sort_values("year")
    if branch.empty:
        raise SystemExit(
            f"No rows for scenario={args.scenario!r} in {args.csv}. "
            f"Available scenarios: {sorted(df['scenario'].unique())}"
        )

    schedule = build_schedule(branch)
    biofuels_on = ("biofuels_enabled" in branch.columns
                    and bool(branch["biofuels_enabled"].iloc[0]))
    title = (f"Whyalla e-fuels capital works schedule — "
             f"{args.scenario.replace('_', ' ').title()}"
             f"{' (biofuels on)' if biofuels_on else ''}")
    plot_gantt(schedule, branch, title, Path(args.out))

    out_csv = Path(args.out).with_suffix(".csv")
    schedule.sort_values(["year", "asset"]).to_csv(out_csv, index=False)
    print(f"wrote {out_csv}")


if __name__ == "__main__":
    main()
