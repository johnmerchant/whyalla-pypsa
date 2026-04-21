"""CO₂ supply stacked dispatch by source over time.

Reads ``trajectory.csv`` (must have ``co2_by_source`` JSON column, or falls
back to re-solving a parametric stub if the column is absent).

Shows: stacked bar of annual CO₂ dispatch by tranche (steelworks / Nyrstar /
Santos / Adbri / DAC) per year × scenario, plus a blended-price line.

Run:
    python chart_co2_supply_curve.py [--scenario policy_stated]
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from co2_supply import HOURS_PER_YEAR, build_co2_supply_curve, blended_co2_price

TRANCHE_COLORS = {
    "co2_steelworks":    "#2ecc71",
    "co2_nyrstar":       "#3498db",
    "co2_santos_moomba": "#9b59b6",
    "co2_adbri_cement":  "#e67e22",
    "co2_dac":           "#e74c3c",
    "co2_supply":        "#95a5a6",   # legacy fallback
}
TRANCHE_LABELS = {
    "co2_steelworks":    "Whyalla Steelworks DRI",
    "co2_nyrstar":       "Nyrstar Port Pirie",
    "co2_santos_moomba": "Santos Moomba CCS",
    "co2_adbri_cement":  "Adbri Birkenhead cement",
    "co2_dac":           "DAC backfill",
    "co2_supply":        "Aggregated CO₂",
}
# Years to plot when no trajectory.csv is available (fallback parametric path).
FALLBACK_YEARS = list(range(2030, 2041))


def _parse_co2_by_source(row: pd.Series) -> dict[str, float]:
    """Parse the co2_by_source column from a trajectory CSV row."""
    raw = row.get("co2_by_source", "{}")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(raw)
            except Exception:
                return {}
    return {}


def _parametric_co2(year: int, scenario: str = "policy_stated") -> dict[str, float]:
    """Estimate CO₂ dispatch from supply curve when trajectory CSV is unavailable.

    Uses the build_co2_supply_curve merit order and assumes full utilisation
    up to 3.5 Mt/y total CO₂ demand (base case).
    """
    tranches = build_co2_supply_curve(year)
    total_demand = 3_500_000  # t/y (3 Mt/y MeOH × 1.375 t CO2/t MeOH ≈ 4 Mt but cap to dossier)
    result = {}
    remaining = total_demand
    for t in sorted(tranches, key=lambda x: x["marginal_cost"]):
        name = t["_tranche_name"]
        annual_cap = t["p_nom"] * HOURS_PER_YEAR  # t/h → t/y
        dispatch = min(remaining, annual_cap)
        result[name] = dispatch
        remaining -= dispatch
        if remaining <= 0:
            break
    return result


def plot(scenario: str, csv: Path | None, outpath: Path) -> None:
    # ── Load or synthesise CO₂ dispatch by year ───────────────────────────
    if csv and csv.exists():
        df = pd.read_csv(csv)
        df = df[df.scenario == scenario].sort_values("year") if "scenario" in df.columns else df
        co2_by_year = {
            int(row.year): _parse_co2_by_source(row)
            for _, row in df.iterrows()
        }
    else:
        co2_by_year = {
            y: _parametric_co2(y, scenario)
            for y in FALLBACK_YEARS
        }

    years = sorted(co2_by_year)
    all_tranches = sorted(set(k for d in co2_by_year.values() for k in d))

    # ── Build stacked bar data ─────────────────────────────────────────────
    data = {t: [co2_by_year.get(y, {}).get(t, 0) / 1e6 for y in years]
            for t in all_tranches}

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9),
                                   gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle(
        "Where does the CO₂ come from?",
        fontsize=14, fontweight="bold", y=0.995,
    )
    fig.text(0.5, 0.965,
             "Annual sourcing of captured CO₂ used to make synthetic fuel"
             f" — scenario: {scenario.replace('_', ' ').title()}",
             ha="center", fontsize=10, color="dimgrey")

    bottom = np.zeros(len(years))
    for tranche, vals in data.items():
        vals_arr = np.array(vals, dtype=float)
        ax1.bar(years, vals_arr, bottom=bottom,
                color=TRANCHE_COLORS.get(tranche, "grey"),
                label=TRANCHE_LABELS.get(tranche, tranche),
                width=0.7, edgecolor="white", linewidth=0.5)
        bottom += vals_arr

    # Annotate 1 Mt/y reference line (scale aid)
    ax1.axhline(1.0, color="black", linestyle=":", linewidth=1.0, alpha=0.5)
    ax1.text(years[0] - 0.4, 1.0, "1 Mt/yr",
             fontsize=7.5, color="dimgrey", va="center", ha="right")

    ax1.set_ylabel("CO₂ captured each year (million tonnes)", fontsize=10)
    ax1.set_title("Sources of CO₂ used by the plant", fontsize=11, fontweight="bold")
    ax1.legend(fontsize=9, loc="upper left", title="CO₂ source")
    ax1.grid(axis="y", alpha=0.3)

    # ── Blended price line ─────────────────────────────────────────────────
    blend_prices = [blended_co2_price(y) for y in years]
    ax2.plot(years, blend_prices, color="darkred", linewidth=2.0,
             marker="o", markersize=5, label="Average CO₂ price paid")
    ax2.fill_between(years, blend_prices, alpha=0.15, color="darkred")
    ax2.set_ylabel("AUD per tonne of CO₂", fontsize=10)
    ax2.set_xlabel("Year", fontsize=10)
    ax2.set_title("Average price of CO₂ feedstock", fontsize=11, fontweight="bold")
    ax2.grid(alpha=0.3)
    ax2.legend(fontsize=9)
    ax2.set_ylim(0, None)

    plt.tight_layout(rect=[0, 0, 1, 0.955])
    plt.savefig(outpath, dpi=150, bbox_inches="tight")
    print(f"Saved {outpath}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="policy_stated")
    ap.add_argument("--csv", default="trajectory.csv")
    ap.add_argument("--out", default="chart_co2_supply_curve.png")
    args = ap.parse_args()
    csv = Path(args.csv) if Path(args.csv).exists() else None
    plot(args.scenario, csv, Path(args.out))


if __name__ == "__main__":
    main()
