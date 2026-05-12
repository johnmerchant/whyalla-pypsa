"""Capital works schedule + Gantt chart from the trajectory output.

Reads `trajectory.csv`, filters to a (policy, ISP) branch, and renders:
  - Gantt chart: one row per asset line item, bars anchored at each tranche's
    build year with capacity and $AUD capex annotations.
  - Summary table under the chart: total $M by year, cumulative MW/MWh by
    asset, grand total.

Assets covered (tranche-extractable from trajectory.csv):
  Electrolyser, H2 storage, Electric heater, H2 burner,
  Wind, Solar, Battery power, Battery energy, Grid link.

Plus one-shot installs (fixed-capex, not tranched), placed per phase model:
  EAF + auxiliaries         at EAF_OPEN_YEAR    (scrap-only pre-2030)
  MIDREX Flex DRI shaft     at FURNACE_OPEN_YEAR (gas arrives March 2030)

Usage:
    uv run python chart_capital_works.py \
        --policy "Policy-stated + gas flat" \
        --isp step_change \
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

# One-shot commissioning dates (phase model: EAF-scrap first, DRI on gas arrival).
EAF_OPEN_YEAR = 2028
FURNACE_OPEN_YEAR = 2030
ANNUAL_STEEL_MT = 1.6
DRI_CAPEX_PER_T_YR = 250.0
EAF_CAPEX_PER_T_YR = 300.0

# Heat-system capex defaults (mirror generate_trajectory.py — must track).
ELECTRIC_HEATER_CAPEX_PER_KW_TH = 400.0
H2_BURNER_CAPEX_PER_KW_TH = 30.0


def _dollars_M(x: float) -> str:
    """Format $AUD as $X M / $X.Y M / $X B."""
    if abs(x) >= 1e9:
        return f"${x/1e9:.2f} B"
    return f"${x/1e6:.0f} M" if abs(x) >= 1e7 else f"${x/1e6:.1f} M"


# Rows displayed on the Gantt. Order = top-to-bottom.
# Each entry: (label, new_col, unit, capex_resolver, cat_color)
#   new_col         : trajectory.csv column with new capacity delta
#   unit            : "MW" or "MWh" for annotation
#   capex_resolver  : function(row) -> $AUD capex for that tranche
#   cat_color       : matplotlib color

def _resolve_capex(kind: str):
    """Return a function(row) -> $AUD capex for a new tranche of this kind."""
    def ely(row):
        return row["new_electrolyser_mw"] * row["capex_per_kw"] * 1000.0
    def h2_store(row):
        # capex_per_kw is ely; h2 store capex baked into trajectory as a
        # flat $20k/MWh — read constant to keep this chart self-contained.
        return row["new_h2_storage_mwh"] * 20_000.0
    def eh(row):
        return row["new_electric_heater_mw"] * ELECTRIC_HEATER_CAPEX_PER_KW_TH * 1000.0
    def hb(row):
        return row["new_h2_burner_mw"] * H2_BURNER_CAPEX_PER_KW_TH * 1000.0
    def wind(row):
        return row["new_wind_mw"] * row["wind_capex_per_kw"] * 1000.0
    def solar(row):
        return row["new_solar_mw"] * row["solar_capex_per_kw"] * 1000.0
    def batt_p(row):
        return row["new_battery_power_mw"] * row["battery_power_capex_per_kw"] * 1000.0
    def batt_e(row):
        return row["new_battery_energy_mwh"] * row["battery_energy_capex_per_kwh"] * 1000.0
    def gl(row):
        return row["new_grid_link_mw"] * row["grid_link_capex_per_mw"]
    return {
        "ely": ely, "h2_store": h2_store, "eh": eh, "hb": hb,
        "wind": wind, "solar": solar, "batt_p": batt_p, "batt_e": batt_e, "gl": gl,
    }[kind]


# (label, new_col, unit, kind, color)
ROWS = [
    ("DRI shaft (MIDREX Flex)",  None,                      "t/yr", None,    "#8c564b"),
    ("EAF + aux",                None,                      "t/yr", None,    "#9467bd"),
    ("Electrolyser",             "new_electrolyser_mw",     "MW",   "ely",   "#1f77b4"),
    ("H2 storage",               "new_h2_storage_mwh",      "MWh",  "h2_store", "#17becf"),
    ("Wind",                     "new_wind_mw",             "MW",   "wind",  "#2ca02c"),
    ("Solar",                    "new_solar_mw",            "MW",   "solar", "#ff7f0e"),
    ("Battery (power)",          "new_battery_power_mw",    "MW",   "batt_p","#d62728"),
    ("Battery (energy)",         "new_battery_energy_mwh",  "MWh",  "batt_e","#e377c2"),
    ("Grid link",                "new_grid_link_mw",        "MW",   "gl",    "#7f7f7f"),
    ("Electric heater",          "new_electric_heater_mw",  "MW",   "eh",    "#bcbd22"),
    ("H2 burner",                "new_h2_burner_mw",        "MW",   "hb",    "#ffbf00"),
]


def build_schedule(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (asset × year) with capacity added + capex_$AUD."""
    records: list[dict] = []
    years = sorted(df["year"].unique().tolist())

    # One-shot EAF at EAF_OPEN_YEAR (scrap-only phase), DRI at FURNACE_OPEN_YEAR.
    annual_t = ANNUAL_STEEL_MT * 1e6
    if EAF_OPEN_YEAR in years:
        records.append({
            "asset": "EAF + aux", "year": EAF_OPEN_YEAR,
            "capacity": annual_t, "unit": "t/yr",
            "capex_aud": annual_t * EAF_CAPEX_PER_T_YR,
        })
    if FURNACE_OPEN_YEAR in years:
        records.append({
            "asset": "DRI shaft (MIDREX Flex)", "year": FURNACE_OPEN_YEAR,
            "capacity": annual_t, "unit": "t/yr",
            "capex_aud": annual_t * DRI_CAPEX_PER_T_YR,
        })

    # Tranche-extractable rows.
    for label, new_col, unit, kind, _ in ROWS:
        if new_col is None:
            continue
        if new_col not in df.columns:
            continue
        cap_fn = _resolve_capex(kind)
        for _, row in df.iterrows():
            cap = float(row.get(new_col, 0.0) or 0.0)
            if cap <= 1e-3:
                continue
            records.append({
                "asset": label, "year": int(row["year"]),
                "capacity": cap, "unit": unit,
                "capex_aud": cap_fn(row),
            })
    return pd.DataFrame.from_records(records)


def plot_gantt(schedule: pd.DataFrame, df: pd.DataFrame, title: str, out: Path):
    """Render Gantt + annual-spend subplot."""
    years = sorted(df["year"].unique().tolist())
    year_min, year_max = min(years), max(years)
    # Extend Gantt a bit past final year so the last-vintage bar has room.
    gantt_end = year_max + 3
    rows_display = [r for r in ROWS]
    n_rows = len(rows_display)

    fig = plt.figure(figsize=(16, 10))
    gs = fig.add_gridspec(2, 1, height_ratios=[n_rows, 4], hspace=0.25)
    ax_g = fig.add_subplot(gs[0])
    ax_b = fig.add_subplot(gs[1])

    color_by_label = {label: color for label, _, _, _, color in rows_display}

    # Gantt: one horizontal lane per asset, tranche bars pegged at build year
    # extending to gantt_end. Width is cosmetic here (asset keeps operating),
    # annotation shows capacity + $.
    for i, (label, _new_col, _unit, _kind, color) in enumerate(rows_display):
        y = n_rows - 1 - i
        ax_g.hlines(y, year_min - 1, gantt_end, colors="lightgray", linewidth=0.5, alpha=0.6)
        sub = schedule[schedule["asset"] == label].sort_values("year")
        for _, rec in sub.iterrows():
            x = rec["year"]
            # Bar: short colored block = commissioning year. Dashed tail = ongoing op.
            ax_g.barh(
                y, width=gantt_end - x, left=x, height=0.62,
                color=color, alpha=0.30, edgecolor="none", zorder=2,
            )
            ax_g.barh(
                y, width=0.9, left=x - 0.45, height=0.78,
                color=color, edgecolor="black", linewidth=0.8, zorder=3,
            )
            cap_str = (
                f"{rec['capacity']/1e6:.2f} Mt/yr" if rec["unit"] == "t/yr"
                else f"{rec['capacity']:,.0f} {rec['unit']}"
            )
            ax_g.text(
                x + 0.7, y, f"+{cap_str} · {_dollars_M(rec['capex_aud'])}",
                fontsize=9, va="center", ha="left",
            )

    ax_g.set_yticks(range(n_rows))
    ax_g.set_yticklabels([label for label, *_ in reversed(rows_display)], fontsize=10)
    ax_g.set_xlim(year_min - 1, gantt_end)
    ax_g.set_ylim(-0.7, n_rows - 0.3)
    ax_g.set_xticks(years)
    ax_g.tick_params(axis="x", labelsize=10)
    ax_g.set_xlabel("Year")
    ax_g.set_title(title, fontsize=13, fontweight="bold")
    ax_g.grid(axis="x", linestyle=":", color="gray", alpha=0.5)
    ax_g.set_axisbelow(True)

    # Bottom: stacked bar of $M by year, asset-colored.
    capex_pivot = (
        schedule.pivot_table(
            index="year", columns="asset", values="capex_aud", aggfunc="sum",
        ).fillna(0.0).reindex(years, fill_value=0.0) / 1e6
    )
    asset_order = [label for label, *_ in rows_display if label in capex_pivot.columns]
    bottom = np.zeros(len(years))
    for label in asset_order:
        vals = capex_pivot[label].values
        ax_b.bar(
            years, vals, bottom=bottom, width=0.7,
            color=color_by_label[label], label=label, edgecolor="white", linewidth=0.6,
        )
        bottom = bottom + vals
    # Total annotations on top of stacks.
    for i, yr in enumerate(years):
        tot = bottom[i]
        if tot > 0:
            ax_b.text(yr, tot + bottom.max() * 0.015, f"{_dollars_M(tot*1e6)}",
                      ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax_b.set_xticks(years)
    ax_b.set_ylabel("Capex ($M AUD)")
    ax_b.set_xlabel("Year")
    ax_b.grid(axis="y", linestyle=":", alpha=0.5)
    ax_b.set_axisbelow(True)

    # Shared legend on bottom panel; compact 2-column layout.
    handles = [
        mpatches.Patch(facecolor=color_by_label[label], edgecolor="black", label=label)
        for label in asset_order
    ]
    ax_b.legend(
        handles=handles, loc="upper left", ncol=2, fontsize=8, frameon=False,
    )

    # Grand-total text in the bottom-right of the Gantt panel.
    grand_total = schedule["capex_aud"].sum()
    ax_g.text(
        0.99, 0.02, f"Total programme capex: {_dollars_M(grand_total)}",
        transform=ax_g.transAxes, fontsize=11, fontweight="bold",
        ha="right", va="bottom",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="gray"),
    )

    fig.tight_layout()
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default="Policy-stated + gas flat")
    parser.add_argument("--isp", default="step_change")
    parser.add_argument("--csv", default=str(TRAJ_CSV))
    parser.add_argument("--out", default=str(HERE / "chart_capital_works.png"))
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    branch = df[(df["scenario"] == args.policy) & (df["isp_scenario"] == args.isp)].copy()
    branch = branch.sort_values("year")
    if branch.empty:
        raise SystemExit(f"No rows for policy={args.policy!r}, isp={args.isp!r}")

    schedule = build_schedule(branch)
    title = (
        f"Whyalla DRI-EAF capital works schedule — {args.policy} · "
        f"{args.isp.replace('_', ' ').title()}"
    )
    plot_gantt(schedule, branch, title, Path(args.out))

    # Also write the schedule CSV next to the chart.
    out_csv = Path(args.out).with_suffix(".csv")
    schedule.sort_values(["year", "asset"]).to_csv(out_csv, index=False)
    print(f"wrote {out_csv}")


if __name__ == "__main__":
    main()
