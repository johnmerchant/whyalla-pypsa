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

# ── Imports-displacement conversions ─────────────────────────────────────
# The plant's output is benchmarked against AU's diesel + jet fuel imports
# specifically. Gasoline/petrol is excluded on the assumption that road
# passenger transport electrifies through the 2030s (EV uptake + AU federal
# fuel-efficiency standard from 2025). Diesel and jet are the "hard to
# electrify" cuts — heavy haul, rail, mining, shipping, aviation.
# bbl/t conversion weighted for plant's kero+diesel output (0.35/0.45 split):
#   (0.35/0.80)×7.33 + (0.45/0.80)×7.86 = 7.63 bbl/t
BBL_PER_T_TRANSPORT_FUEL = 7.63

# AU diesel + jet imports baseline (DCCEEW Fuel Security statistics, 2024):
#   Diesel consumption ~29 Mt/y ≈ 580 kbpd, ~80% imported → ~465 kbpd
#   Jet consumption   ~8 Mt/y ≈ 170 kbpd, ~75% imported → ~130 kbpd
#   Combined diesel+jet imports ≈ 595 kbpd
AU_DIESEL_JET_IMPORTS_KBPD = 595.0
AU_DIESEL_CONSUMPTION_KBPD = 580.0
AU_JET_CONSUMPTION_KBPD = 170.0

# ── Familiar government-program benchmarks (per-taxpayer cumulative) ─────
# 14-year cumulative figures (AUD/taxpayer, 11.5M taxpayers — ATO 2024).
# Selected for credibility with a fiscally-conservative reader: programs
# the Coalition has championed (AUKUS, 2024 nuclear policy, JobKeeper),
# funded (Inland Rail, NBN) or actively defends (Diesel Fuel Tax Credits).
AU_TAXPAYERS = 11_500_000
_TRAJECTORY_YEARS = 14  # 2027 → 2040

# AUKUS: ~$368B AUD over 30y (AU DoD 2023 outlook); 14y pro-rata share
AUKUS_CUMULATIVE_PER_TAXPAYER = (368_000_000_000 * _TRAJECTORY_YEARS / 30) / AU_TAXPAYERS
# 2024 Coalition nuclear policy: 7-reactor build — capital cost central
# estimate $116B (AEMO / CSIRO GenCost-adjacent independent modelling).
# Coalition's own Frontier Economics 2024 analysis cited up to $211B on
# gross build; conservative AEMO figure used here for defensibility.
COALITION_NUCLEAR_CUMULATIVE_PER_TAXPAYER = 116_000_000_000 / AU_TAXPAYERS
# Diesel Fuel Tax Credits Scheme: ~$10B/y (ATO 2024 published refunds,
# mostly mining + agriculture). Direct fossil-diesel subsidy baseline.
DIESEL_REBATE_CUMULATIVE_PER_TAXPAYER = (10_000_000_000 * _TRAJECTORY_YEARS) / AU_TAXPAYERS
# JobKeeper: $89B total (Treasury 2021 final cost) — one-off
JOBKEEPER_CUMULATIVE_PER_TAXPAYER = 89_000_000_000 / AU_TAXPAYERS
# NBN rollout total cost: ~$51B (ANAO 2020) — one-off
NBN_CUMULATIVE_PER_TAXPAYER = 51_000_000_000 / AU_TAXPAYERS
# Inland Rail: ~$31B (ARTC 2024 revised estimate) — one-off Coalition project
INLAND_RAIL_CUMULATIVE_PER_TAXPAYER = 31_000_000_000 / AU_TAXPAYERS

PROGRAM_BENCHMARKS = [
    ("AUKUS (share over 14y)",             AUKUS_CUMULATIVE_PER_TAXPAYER,            "#2c3e50"),
    ("Diesel Fuel Rebate (14y)",           DIESEL_REBATE_CUMULATIVE_PER_TAXPAYER,    "#7f8c8d"),
    ("2024 Coalition nuclear policy",      COALITION_NUCLEAR_CUMULATIVE_PER_TAXPAYER, "#34495e"),
    ("JobKeeper (one-off, 2020-21)",       JOBKEEPER_CUMULATIVE_PER_TAXPAYER,         "#95a5a6"),
    ("NBN rollout (one-off)",              NBN_CUMULATIVE_PER_TAXPAYER,               "#bdc3c7"),
    ("Inland Rail (one-off)",              INLAND_RAIL_CUMULATIVE_PER_TAXPAYER,       "#d5dbdb"),
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
    # Today's pump reference lines (crisis vs pre-crisis, for lay orientation).
    # Anchor the labels to the right edge so they sit clear of the legend at
    # the top-left of the panel.
    x_label = df.year.max() + 0.4
    for label, price, colour in FOSSIL_REFS:
        ax.axhline(price, color=colour, linestyle=":", linewidth=1.1, alpha=0.7)
        ax.text(x_label, price, f" {label}  ${price:.2f}/L",
                fontsize=7.0, color=colour, va="center", ha="left",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.75, pad=1))
    # Premium callout: best-case e-fuel vs worst-case fossil path in 2040
    df_2040 = df[df.year == df.year.max()]
    cheapest_lcof = aud_per_litre(df_2040["lcof"].min(), "diesel")
    priciest_fossil = aud_per_litre(df_2040["diesel_price_per_t"].max(), "diesel")
    mult_fossil = cheapest_lcof / priciest_fossil
    mult_retail = cheapest_lcof / DIESEL_RETAIL_AUD_PER_L
    ax.text(0.98, 0.03,
            f"In 2040, best-case e-fuel is\n"
            f"~{mult_fossil:.1f}× modelled wholesale diesel\n"
            f"~{mult_retail:.1f}× today's retail pump",
            transform=ax.transAxes, fontsize=8, fontweight="bold",
            color="#c0392b", va="bottom", ha="right",
            bbox=dict(facecolor="white", edgecolor="#c0392b", alpha=0.85, pad=4))
    ax.set_title("Synthetic diesel cost vs rising fossil prices\n"
                 "(solid = e-fuel, dashed = model's peak-oil/IMO path)",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("AUD per litre", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, None)
    # Reserve right-edge space for the fossil-pump annotations.
    ax.set_xlim(df.year.min() - 0.3, df.year.max() + 6.5)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=6.5, loc="upper left", ncol=1)

    # ── [0,1] Mandate-driven total fuel production ────────────────────────
    ax = axes[0, 1]
    _scenario_lines(ax, df, "mandated_fuel_mt")
    ax.set_title("Synthetic fuel delivered (mandated volume)",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("Million tonnes per year", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, None)
    ax.yaxis.get_major_formatter().set_useOffset(False)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    ax.text(0.98, 0.02,
            "Ramp driven by SAF / IMO /\n"
            "hypothetical AU federal low-carbon\n"
            "liquid fuel mandate",
            transform=ax.transAxes, fontsize=7.5, color="dimgrey",
            va="bottom", ha="right",
            bbox=dict(facecolor="white", edgecolor="lightgrey", alpha=0.7, pad=3))

    # ── [0,2] Diesel + jet imports displaced (hard-to-electrify cuts) ─────
    ax = axes[0, 2]
    for sc in df.scenario.unique():
        sub = df[df.scenario == sc].sort_values("year")
        # Only count the plant's diesel + kero output (aviation + heavy-haul)
        transport_t = sub.get("kero_tonnes", pd.Series(0)).fillna(0) + \
                      sub.get("diesel_tonnes", pd.Series(0)).fillna(0)
        kbpd_displaced = transport_t * BBL_PER_T_TRANSPORT_FUEL / 365 / 1e3
        ax.plot(sub.year, kbpd_displaced,
                color=SCENARIO_COLORS.get(sc, "grey"),
                linewidth=2.5, marker="o", markersize=5,
                label=SCENARIO_LABELS.get(sc, sc))
    latest = df[df.scenario == "policy_stated"].sort_values("year").iloc[-1]
    latest_kbpd = (latest.get("kero_tonnes", 0) + latest.get("diesel_tonnes", 0)) \
                   * BBL_PER_T_TRANSPORT_FUEL / 365 / 1e3
    pct_imports = latest_kbpd / AU_DIESEL_JET_IMPORTS_KBPD * 100
    ax.set_title("Diesel + aviation fuel imports displaced\n"
                 "(hard-to-electrify transport cuts)",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("Thousand barrels per day (kbpd)", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, None)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    ax.text(0.98, 0.02,
            f"By 2040 (policy-stated): ~{latest_kbpd:.0f} kbpd kero+diesel onshore\n"
            f"≈ {pct_imports:.1f}% of AU's ~{AU_DIESEL_JET_IMPORTS_KBPD:.0f} kbpd diesel+jet imports\n"
            f"(gasoline excluded — assumed electrified by 2035)\n"
            f"Aviation + heavy haul cannot easily electrify",
            transform=ax.transAxes, fontsize=7.5, fontweight="bold",
            color="#2c3e50", va="bottom", ha="right",
            bbox=dict(facecolor="white", edgecolor="#2c3e50", alpha=0.85, pad=4))

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

    # ── [1,1] Annual taxpayer subsidy (AUD billion) ───────────────────────
    ax = axes[1, 1]
    for sc in df.scenario.unique():
        sub = df[df.scenario == sc].sort_values("year")
        ax.plot(sub.year, sub["annual_subsidy_aud"] / 1e9,
                color=SCENARIO_COLORS.get(sc, "grey"),
                linewidth=2.2, marker="o", markersize=5,
                label=SCENARIO_LABELS.get(sc, sc))
    latest = df[df.scenario == "policy_stated"].sort_values("year").iloc[-1]
    ax.set_title("What this costs the taxpayer (per year)",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("AUD billions per year", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, None)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")
    ax.text(0.98, 0.02,
            f"2040: ~AUD ${latest['annual_subsidy_aud']/1e9:.0f}B/yr\n"
            "(≈ federal road budget)\n"
            "gap between LCOF and fossil-fuel\n"
            "wholesale revenue at mandate volume",
            transform=ax.transAxes, fontsize=7.5, color="#c0392b",
            va="bottom", ha="right",
            bbox=dict(facecolor="white", edgecolor="#c0392b", alpha=0.85, pad=3))

    # ── [1,2] Cumulative per-taxpayer cost vs familiar program benchmarks ───
    ax = axes[1, 2]
    cum_totals: dict[str, float] = {}
    for sc in df.scenario.unique():
        sub = df[df.scenario == sc].sort_values("year")
        years = sub.year.to_numpy()
        annual = sub.annual_subsidy_aud.to_numpy()
        cum = [0.0]
        for i in range(1, len(years)):
            gap = years[i] - years[i-1]
            avg_subsidy = 0.5 * (annual[i] + annual[i-1])
            cum.append(cum[-1] + avg_subsidy * gap)
        cum_per_tp = [c / AU_TAXPAYERS for c in cum]
        cum_totals[sc] = cum_per_tp[-1]
        ax.plot(years, cum_per_tp,
                color=SCENARIO_COLORS.get(sc, "grey"),
                linewidth=2.5, marker="o", markersize=5,
                label=SCENARIO_LABELS.get(sc, sc),
                zorder=3)

    # Reference lines against familiar government programs.
    xmin, xmax = df.year.min(), df.year.max()
    for label, val, colour in PROGRAM_BENCHMARKS:
        ax.axhline(val, color=colour, linestyle="--", linewidth=1.2,
                   alpha=0.85, zorder=1)
        ax.text(xmax, val, f"  {label}: ${val:,.0f}",
                fontsize=7.5, color=colour, va="center", ha="left",
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1))

    ax.set_title("Cumulative cost per Australian taxpayer\n"
                 "vs familiar government programs (2027-2040)",
                 fontsize=11, fontweight="bold")
    ax.set_ylabel("AUD per taxpayer (cumulative)", fontsize=10)
    ax.set_xlabel("Year", fontsize=9)
    ax.set_ylim(0, None)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=8, loc="upper left")

    worst = max(cum_totals.values())
    best = min(cum_totals.values())
    pct_aukus = worst / AUKUS_CUMULATIVE_PER_TAXPAYER * 100
    pct_diesel_rebate = worst / DIESEL_REBATE_CUMULATIVE_PER_TAXPAYER * 100
    pct_nuclear = worst / COALITION_NUCLEAR_CUMULATIVE_PER_TAXPAYER * 100
    ax.text(0.02, 0.97,
            f"Whyalla 2027-2040:\n"
            f"${best:,.0f}–${worst:,.0f} per taxpayer\n"
            f"≈ {pct_nuclear:.0f}% of 2024 Coalition nuclear policy\n"
            f"≈ {pct_aukus:.0f}% of AUKUS share\n"
            f"≈ {pct_diesel_rebate:.0f}% of existing diesel rebate",
            transform=ax.transAxes, fontsize=7.5, fontweight="bold",
            color="#2c3e50", va="top", ha="left",
            bbox=dict(facecolor="white", edgecolor="#2c3e50", alpha=0.85, pad=4))

    # Force integer year ticks everywhere
    from matplotlib.ticker import MaxNLocator
    for ax in axes.flat:
        ax.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=8))

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
