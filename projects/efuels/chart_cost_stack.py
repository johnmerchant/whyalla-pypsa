"""LCOF cost-stack waterfall at the 2040 model year, by scenario.

Problem: the LCOF headline number hides where the dollars actually go —
electricity, process capex, CO₂ supply, and the residual (refinery /
HCR / biofuel / heat capex). For a fuel-security investment case we
want a single page that shows the cost decomposition next to the
fossil-diesel benchmark.

What the chart shows: one figure with three vertical stacked bars, one
per scenario (``policy_stated``, ``imo_binding``, ``foak_stranded``).
Each bar is a per-tonne-diesel-equivalent cost stack with components,
bottom up:

  1. Electricity cost      (annual_power_cost / total_fuel_diesel_eq_t)
  2. Process capex          (annual_capex_process / total_fuel_diesel_eq_t)
  3. CO₂ supply cost        (annual_co2_cost / total_fuel_diesel_eq_t)
  4. Residual               (LCOF − sum_of_above; refinery/HCR/biofuel/heat)

Two reference horizontal lines: fossil diesel ($2,150/t) and the
gross fuel revenue (fossil_market_revenue_aud / total_fuel_diesel_eq_t).

Per-bar total label shows total LCOF in $/t and % vs fossil diesel.

Usage:
    uv run python chart_cost_stack.py \\
        --csv trajectory.csv \\
        --out chart_cost_stack.png \\
        --year 2040
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

# LHV (MWh/t) — used to convert mixed product slate to diesel-equivalent tonnes.
LHV_MWH_PER_T = {
    "naphtha": 12.222,
    "kero":    11.944,
    "diesel":  11.889,
    "wax":     11.611,
}
DIESEL_LHV_MWH_PER_T = 11.89
FOSSIL_DIESEL_AUD_PER_T = 2_150.0

SCENARIO_ORDER = ["policy_stated", "imo_binding", "foak_stranded"]
SCENARIO_LABELS = {
    "policy_stated": "Policy Stated",
    "imo_binding":   "IMO Binding",
    "foak_stranded": "FOAK Stranded",
}

# Stacked-component palette (consistent across scenarios).
COMPONENT_COLOURS = {
    "Electricity":   "#2ca02c",
    "Process capex": "#1f77b4",
    "CO₂ supply":    "#8c8c00",
    "Residual":      "#d62728",
}
COMPONENT_ORDER = ["Electricity", "Process capex", "CO₂ supply", "Residual"]


def _dollars_M(x: float) -> str:
    if abs(x) >= 1e9:
        return f"${x/1e9:.2f} B"
    return f"${x/1e6:.0f} M" if abs(x) >= 1e7 else f"${x/1e6:.1f} M"


def _diesel_eq_tonnes(row: pd.Series) -> float:
    """Convert a multi-product fuel slate to diesel-equivalent tonnes via LHV."""
    energy_mwh = (
        float(row.get("naphtha_tonnes", 0.0) or 0.0) * LHV_MWH_PER_T["naphtha"]
        + float(row.get("kero_tonnes",    0.0) or 0.0) * LHV_MWH_PER_T["kero"]
        + float(row.get("diesel_tonnes",  0.0) or 0.0) * LHV_MWH_PER_T["diesel"]
        + float(row.get("wax_tonnes",     0.0) or 0.0) * LHV_MWH_PER_T["wax"]
    )
    return energy_mwh / DIESEL_LHV_MWH_PER_T


def build_stack(df: pd.DataFrame, year: int) -> pd.DataFrame:
    """One row per scenario at ``year`` with $/t-diesel-eq components + totals."""
    rows: list[dict] = []
    for scen in SCENARIO_ORDER:
        sub = df[(df["scenario"] == scen) & (df["year"] == year)]
        if sub.empty:
            raise SystemExit(
                f"No row for scenario={scen!r} year={year} in input CSV."
            )
        r = sub.iloc[0]
        deq_t = _diesel_eq_tonnes(r)
        if deq_t <= 0:
            raise SystemExit(
                f"diesel-equivalent tonnes is zero for {scen} {year}."
            )

        elec_per_t   = float(r["annual_power_cost"])    / deq_t
        capex_per_t  = float(r["annual_capex_process"]) / deq_t
        co2_per_t    = float(r["annual_co2_cost"])      / deq_t
        lcof         = float(r["lcof"])
        residual     = lcof - (elec_per_t + capex_per_t + co2_per_t)
        revenue_per_t = float(r["fossil_market_revenue_aud"]) / deq_t

        rows.append({
            "scenario":      scen,
            "diesel_eq_t":   deq_t,
            "Electricity":   elec_per_t,
            "Process capex": capex_per_t,
            "CO₂ supply":    co2_per_t,
            "Residual":      residual,
            "lcof":          lcof,
            "revenue_per_t": revenue_per_t,
            "annual_power_cost":    float(r["annual_power_cost"]),
            "annual_capex_process": float(r["annual_capex_process"]),
            "annual_co2_cost":      float(r["annual_co2_cost"]),
        })
    return pd.DataFrame.from_records(rows)


def plot_cost_stack(stack: pd.DataFrame, year: int, out: Path) -> None:
    fig, ax = plt.subplots(figsize=(12, 7), dpi=160)

    x_positions = np.arange(len(stack))
    bar_width = 0.55
    x_labels = [SCENARIO_LABELS.get(s, s) for s in stack["scenario"]]

    bottom = np.zeros(len(stack))
    for comp in COMPONENT_ORDER:
        vals = stack[comp].values.astype(float)
        ax.bar(
            x_positions, vals, bottom=bottom, width=bar_width,
            color=COMPONENT_COLOURS[comp], edgecolor="white", linewidth=1.2,
            label=comp, zorder=2,
        )
        # Annotate each segment with its $/t value if > $200/t.
        for i, v in enumerate(vals):
            if v > 200:
                ax.text(
                    x_positions[i], bottom[i] + v / 2.0,
                    f"${v:,.0f}/t",
                    ha="center", va="center", fontsize=9.5,
                    fontweight="bold", color="white", zorder=3,
                )
        bottom = bottom + vals

    # Per-bar total label on top: total LCOF in $/t and % vs fossil.
    ymax_data = float(bottom.max())
    pad = ymax_data * 0.02
    for i, (_, row) in enumerate(stack.iterrows()):
        tot = float(row["lcof"])
        pct = 100.0 * tot / FOSSIL_DIESEL_AUD_PER_T
        ax.text(
            x_positions[i], tot + pad,
            f"${tot:,.0f}/t\n{pct:,.0f}% of fossil",
            ha="center", va="bottom", fontsize=10.5, fontweight="bold",
        )

    # Reference horizontal line: fossil diesel. Labelled in the legend
    # below — keeping a duplicate floating annotation pushed it outside
    # the plot area at this aspect ratio.
    ax.axhline(
        FOSSIL_DIESEL_AUD_PER_T, color="black", linestyle="--",
        linewidth=1.4, alpha=0.85, zorder=4,
    )

    # Reference: gross fuel revenue per bar (fossil-blend product slate).
    rev_label_added = False
    for i, (_, row) in enumerate(stack.iterrows()):
        rev = float(row["revenue_per_t"])
        ax.hlines(
            rev,
            x_positions[i] - bar_width / 2, x_positions[i] + bar_width / 2,
            colors="#555555", linestyles=":", linewidth=2.0, zorder=4,
            label="Gross fuel revenue (fossil-blend)" if not rev_label_added else None,
        )
        rev_label_added = True

    # X axis.
    ax.set_xticks(x_positions)
    ax.set_xticklabels(x_labels, fontsize=11)
    ax.set_xlim(-0.6, len(stack) - 0.4)

    # Y axis.
    ymax = max(ymax_data, FOSSIL_DIESEL_AUD_PER_T) * 1.18
    ax.set_ylim(0, ymax)
    ax.set_ylabel("Levelised cost of fuel (AUD per tonne diesel-equivalent)",
                  fontsize=11)
    ax.grid(axis="y", linestyle=":", color="gray", alpha=0.5)
    ax.set_axisbelow(True)

    # Title.
    ax.set_title(
        f"Where the cost goes — LCOF stack at {year} by scenario",
        fontsize=14, fontweight="bold", pad=16,
    )

    # Legend (components + revenue line).
    handles = [
        mpatches.Patch(facecolor=COMPONENT_COLOURS[c], edgecolor="white",
                       label=c) for c in COMPONENT_ORDER
    ]
    handles.append(plt.Line2D([0], [0], color="#555555", linestyle=":",
                              linewidth=2.0,
                              label="Gross fuel revenue (fossil-blend)"))
    handles.append(plt.Line2D([0], [0], color="black", linestyle="--",
                              linewidth=1.4,
                              label=f"Fossil diesel ${FOSSIL_DIESEL_AUD_PER_T:,.0f}/t"))
    ax.legend(handles=handles, loc="upper left", fontsize=9.5,
              frameon=False, ncol=2)

    # Subtitle (matplotlib fig.text).
    fig.text(
        0.5, 0.005,
        "Bars show per-tonne-diesel-equivalent cost components. "
        f"Reference: fossil diesel ${FOSSIL_DIESEL_AUD_PER_T:,.0f}/t.",
        ha="center", va="bottom", fontsize=10, style="italic",
        color="#444444",
    )

    fig.tight_layout(rect=[0, 0.03, 1, 1])
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default="trajectory.csv")
    ap.add_argument("--out", default="chart_cost_stack.png")
    ap.add_argument("--year", type=int, default=2040)
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = HERE / csv_path
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = HERE / out_path

    df = pd.read_csv(csv_path)
    if "scenario" not in df.columns or "year" not in df.columns:
        raise SystemExit(
            f"Input CSV missing 'scenario' or 'year': {csv_path}"
        )

    stack = build_stack(df, args.year)

    # Pretty-print the per-scenario decomposition for the log.
    print(f"LCOF cost stack at {args.year} (AUD per tonne diesel-equivalent):")
    cols = ["scenario", "Electricity", "Process capex", "CO₂ supply",
            "Residual", "lcof", "revenue_per_t", "diesel_eq_t"]
    with pd.option_context("display.float_format", "{:,.1f}".format):
        print(stack[cols].to_string(index=False))

    plot_cost_stack(stack, args.year, out_path)


if __name__ == "__main__":
    main()
