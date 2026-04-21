"""Whyalla e-fuels trajectory — lay-audience chart.

Headline question: "Will this fuel cost less than what I pay at the pump?"

2×3 grid:
  [0,0] HERO — production cost in AUD/L vs diesel/ULP/jet fuel references
  [0,1] Annual fuel production (Mt/yr)
  [0,2] Climate benefit — Mt CO₂e avoided (≈ cars off road)
  [1,0] Electrolyser size (MW) — scale of renewable build
  [1,1] Input path — electrolyser cost assumption (AUD/kW)
  [1,2] Input path — CO₂ supply price (AUD/t)

Reads ``trajectory.csv`` produced by ``generate_trajectory.py``.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from fossil_reference import (
    DIESEL_LIFECYCLE_CO2_T_PER_T,
    DIESEL_RETAIL_AUD_PER_L,
    DIESEL_RETAIL_AUD_PER_L_2025,
    DIESEL_WHOLESALE_AUD_PER_L,
    JET_WHOLESALE_AUD_PER_L,
    PASSENGER_CAR_CO2_T_PER_YR,
    ULP_RETAIL_AUD_PER_L,
    aud_per_litre,
)

SCENARIO_COLORS = {
    "policy_stated": "#2980b9",
    "imo_binding":   "#27ae60",
    "foak_stranded": "#e74c3c",
}
SCENARIO_LABELS = {
    "policy_stated": "Policy Stated",
    "imo_binding":   "IMO Binding",
    "foak_stranded": "FOAK Stranded",
}

FOSSIL_REFS = [
    ("Diesel pump — Apr 2026 (crisis)",   DIESEL_RETAIL_AUD_PER_L,      "#c0392b"),
    ("Diesel pump — 2025 (pre-crisis)",   DIESEL_RETAIL_AUD_PER_L_2025, "#7f8c8d"),
]


def load(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv)
    df["year"] = df["year"].astype(int)
    return df


def _scenario_lines(ax, df, col, scale=1.0):
    for sc in df.scenario.unique():
        sub = df[df.scenario == sc].sort_values("year")
        if col not in sub.columns or sub[col].isna().all():
            continue
        ax.plot(sub.year, sub[col] * scale,
                color=SCENARIO_COLORS.get(sc, "grey"),
                linewidth=2.2, marker="o", markersize=5,
                label=SCENARIO_LABELS.get(sc, sc))


def plot(df: pd.DataFrame, outpath: Path) -> None:
    fig, axes = plt.subplots(2, 3, figsize=(17, 10))
    year_span = f"{df.year.min()}–{df.year.max()}"
    fig.suptitle(
        f"Whyalla synthetic-fuels plant — projected performance {year_span}",
        fontsize=15, fontweight="bold", y=0.995,
    )
    fig.text(0.5, 0.958,
             "Fossil-fuel price path: UK DESNZ 2024 Scenario C (IEA high-price "
             "methodology) + Hormuz-crisis risk premium   •   "
             "Scenarios: Policy Stated, IMO Binding, FOAK Stranded",
             ha="center", fontsize=9, color="dimgrey")

    # ── [0,0] HERO — AUD/L vs fossil ──────────────────────────────────────
    ax = axes[0, 0]
    lcof_by_scenario = {}
    for sc in df.scenario.unique():
        sub = df[df.scenario == sc].sort_values("year")
        lcof_per_l = sub["lcof"].apply(lambda v: aud_per_litre(v, "diesel"))
        lcof_by_scenario[sc] = lcof_per_l
        colour = SCENARIO_COLORS.get(sc, "grey")
        ax.plot(sub.year, lcof_per_l,
                color=colour, linewidth=2.5, marker="o", markersize=6,
                label=f"{SCENARIO_LABELS.get(sc, sc)} (e-fuel)")
        # Model's assumed rising fossil-diesel wholesale path (peak-oil + IMO)
        if "diesel_price_per_t" in sub.columns:
            fossil_per_l = sub["diesel_price_per_t"].apply(
                lambda v: aud_per_litre(v, "diesel"))
            ax.plot(sub.year, fossil_per_l,
                    color=colour, linewidth=1.6, linestyle="--",
                    marker="s", markersize=4, alpha=0.75,
                    label=f"{SCENARIO_LABELS.get(sc, sc)} (fossil path)")
    # Today's pump reference lines (crisis vs pre-crisis, for lay orientation)
    for label, price, colour in FOSSIL_REFS:
        ax.axhline(price, color=colour, linestyle=":", linewidth=1.1, alpha=0.7)
        ax.text(df.year.max(), price, f" {label}  ${price:.2f}/L",
                fontsize=7.5, color=colour, va="center", ha="left",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1))
    # Premium callout: best-case e-fuel vs worst-case fossil path in 2040
    df_2040 = df[df.year == df.year.max()]
    cheapest_lcof = aud_per_litre(df_2040["lcof"].min(), "diesel")
    priciest_fossil = aud_per_litre(df_2040["diesel_price_per_t"].max(), "diesel")
    mult_fossil = cheapest_lcof / priciest_fossil
    mult_retail = cheapest_lcof / DIESEL_RETAIL_AUD_PER_L
    ax.text(0.02, 0.97,
            f"In 2040, best-case e-fuel is\n"
            f"~{mult_fossil:.1f}× modelled wholesale diesel\n"
            f"~{mult_retail:.1f}× today's retail pump",
            transform=ax.transAxes, fontsize=8, fontweight="bold",
            color="#c0392b", va="top",
            bbox=dict(facecolor="white", edgecolor="#c0392b", alpha=0.85, pad=4))
    ax.set_title("Synthetic diesel cost vs rising fossil prices\n"
                 "(solid = e-fuel, dashed = model's peak-oil/IMO path)",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("AUD per litre", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, None)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=6.5, loc="center left", ncol=1)

    # ── [0,1] Annual fuel production ──────────────────────────────────────
    ax = axes[0, 1]
    _scenario_lines(ax, df, "diesel_tonnes", scale=1e-6)
    ax.set_title("Synthetic diesel produced per year", fontsize=11, fontweight="bold")
    ax.set_ylabel("Million tonnes per year", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, 1.0)   # fix range so near-identical scenarios don't explode
    ax.yaxis.get_major_formatter().set_useOffset(False)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    ax.text(0.02, 0.98,
            "All scenarios converge to the\n"
            "0.5 Mt/yr dossier target",
            transform=ax.transAxes, fontsize=7.5, color="dimgrey",
            va="top", ha="left",
            bbox=dict(facecolor="white", edgecolor="lightgrey", alpha=0.7, pad=3))

    # ── [0,2] Climate benefit ─────────────────────────────────────────────
    ax = axes[0, 2]
    for sc in df.scenario.unique():
        sub = df[df.scenario == sc].sort_values("year")
        # Total fuel abatement: sum diesel + kero (both displace fossil)
        fuel_t = sub.get("diesel_tonnes", pd.Series(0)).fillna(0) + \
                 sub.get("kero_tonnes", pd.Series(0)).fillna(0)
        co2_abated_mt = fuel_t * DIESEL_LIFECYCLE_CO2_T_PER_T * 1e-6
        ax.plot(sub.year, co2_abated_mt,
                color=SCENARIO_COLORS.get(sc, "grey"),
                linewidth=2.2, marker="o", markersize=5,
                label=SCENARIO_LABELS.get(sc, sc))
    # Annotate one value as "≈ N cars"
    latest = df[df.scenario == "policy_stated"].sort_values("year").iloc[-1]
    co2_example = (latest["diesel_tonnes"] + latest.get("kero_tonnes", 0)) \
                   * DIESEL_LIFECYCLE_CO2_T_PER_T
    cars_example = co2_example / PASSENGER_CAR_CO2_T_PER_YR
    ax.set_title("Avoided CO₂ emissions vs fossil fuels",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("Million tonnes CO₂e per year avoided", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, 1.5)
    ax.yaxis.get_major_formatter().set_useOffset(False)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    ax.text(0.02, 0.97,
            f"≈ {cars_example/1e6:.1f} million passenger\ncars off the road",
            transform=ax.transAxes, fontsize=8.5, fontweight="bold",
            color="#27ae60", va="top",
            bbox=dict(facecolor="white", edgecolor="#27ae60", alpha=0.85, pad=4))

    # ── [1,0] Electrolyser MW ─────────────────────────────────────────────
    ax = axes[1, 0]
    _scenario_lines(ax, df, "electrolyser_mw")
    ax.set_title("Electrolyser size (renewable hydrogen plant)",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("Megawatts", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, None)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="lower right")
    # Reference: a typical AU rooftop PV system is 6.6 kW
    ax.text(0.02, 0.97,
            "For scale: a typical\nhome solar system is 6.6 kW.\n"
            "7,000 MW ≈ 1,000,000 homes' worth of panels.",
            transform=ax.transAxes, fontsize=7.5, color="dimgrey", va="top",
            bbox=dict(facecolor="white", edgecolor="lightgrey", alpha=0.7, pad=3))

    # ── [1,1] Electrolyser CAPEX input path ───────────────────────────────
    ax = axes[1, 1]
    _scenario_lines(ax, df, "capex_per_kw")
    ax.set_title("Assumption: electrolyser installed cost",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("AUD per kilowatt installed", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, None)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    ax.text(0.02, 0.02,
            "Input assumption — drives the cost curve.\n"
            "Lower = cheaper e-fuels.",
            transform=ax.transAxes, fontsize=7.5, color="dimgrey",
            va="bottom",
            bbox=dict(facecolor="white", edgecolor="lightgrey", alpha=0.7, pad=3))

    # ── [1,2] CO₂ supply price input path ─────────────────────────────────
    ax = axes[1, 2]
    _scenario_lines(ax, df, "co2_blended_price")
    ax.set_title("Assumption: CO₂ feedstock price (blended)",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("AUD per tonne CO₂", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, None)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper right")
    ax.text(0.02, 0.02,
            "Weighted avg of CO₂ sources:\nsteelworks, Nyrstar, Santos,\n"
            "Adbri cement, DAC backfill.",
            transform=ax.transAxes, fontsize=7.5, color="dimgrey",
            va="bottom",
            bbox=dict(facecolor="white", edgecolor="lightgrey", alpha=0.7, pad=3))

    plt.tight_layout(rect=[0, 0, 1, 0.945])
    plt.savefig(outpath, dpi=150, bbox_inches="tight")
    print(f"Saved {outpath}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="trajectory.csv")
    ap.add_argument("--out", default="chart_trajectory.png")
    args = ap.parse_args()
    csv = Path(args.csv)
    if not csv.exists():
        print(f"ERROR: {csv} not found — run generate_trajectory.py first")
        raise SystemExit(1)
    df = load(csv)
    plot(df, Path(args.out))


if __name__ == "__main__":
    main()
