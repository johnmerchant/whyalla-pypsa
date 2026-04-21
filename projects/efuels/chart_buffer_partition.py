"""Buffer partition: H₂ vs CO₂ vs MeOH store share.

For one scenario-year (default: 2030), solves at three MeOH synthesis
min_pu values (0.3 / 0.5 / 0.7) using the real Whyalla facility (wind/solar/
battery + RLDC merit-order grid price). Stacked bar shows fraction of annual
*store throughput* (∫|dSOC/dt|·dt) passing through each buffer.

Also shows sensitivity to min_pu on the flexibility premium (avg AC price
minus electrolyser realised price — positive means the electrolyser is
buying when prices are below average).

Run:
    python chart_buffer_partition.py [--year 2030]
"""
from __future__ import annotations

import argparse
import copy
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from whyalla_pypsa import build_facility_network, attach_grid_price

from run import default_config
from process_chain import attach_efuels
from efuels_results import extract_lcom_lcof

warnings.filterwarnings("ignore")

MIN_PU_VALUES = [0.3, 0.5, 0.7]
STORE_COLORS = {
    "Hydrogen tank":  "#3498db",
    "Methanol tank":  "#2ecc71",
    "CO₂ tank":       "#e67e22",
}


def _solve_one(year: int, min_pu: float) -> dict:
    cfg = copy.deepcopy(default_config())
    cfg.scenario.model_year = year
    cfg.scenario.snapshot_mode = "representative_weeks"
    cfg.scenario.representative_weeks = 12

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg)
    attach_efuels(
        n,
        wacc=cfg.pypsa_wacc,
        synthesis_min_load=min_pu,
        product_split_mode="asf",
        annual_fuel_mt=0.5,
    )
    status, _ = n.optimize(
        solver_name=cfg.solver,
        solver_options={**cfg.solver_options, "run_crossover": "off"},
    )
    if status not in ("ok", "optimal"):
        return {}

    m = extract_lcom_lcof(n, cfg)
    snap_w = n.snapshot_weightings.generators.iloc[0]

    def _store_throughput(name: str) -> float:
        if name not in n.stores.index:
            return 0.0
        e = n.stores_t.e.get(name, pd.Series(0.0, index=n.snapshots))
        return float(e.diff().abs().fillna(0.0).sum()) * snap_w

    h2_tp   = _store_throughput("h2_store")
    meoh_tp = _store_throughput("meoh_storage")
    co2_tp  = _store_throughput("co2_storage")
    total_tp = h2_tp + meoh_tp + co2_tp

    h2_cap   = float(n.stores.at["h2_store", "e_nom_opt"]) if "h2_store" in n.stores.index else 0.0
    meoh_cap = float(n.stores.at["meoh_storage", "e_nom_opt"]) if "meoh_storage" in n.stores.index else 0.0
    co2_cap  = float(n.stores.at["co2_storage", "e_nom_opt"]) if "co2_storage" in n.stores.index else 0.0

    # Flexibility premium = avg AC price - electrolyser realised price
    ac_price = n.buses_t.marginal_price.get("facility_ac",
                                             pd.Series(0.0, index=n.snapshots))
    ely_p = n.links_t.p0.get("electrolyser", pd.Series(0.0, index=n.snapshots))
    ely_mwh = float(ely_p.sum()) * snap_w
    if ely_mwh > 0:
        ely_realised = float((ely_p * ac_price).sum()) * snap_w / ely_mwh
        avg_ac = float(ac_price.mean())
        flex_premium = avg_ac - ely_realised
    else:
        flex_premium = 0.0

    return {
        "h2_buffer_share":   h2_tp / total_tp if total_tp > 0 else 0.0,
        "meoh_buffer_share": meoh_tp / total_tp if total_tp > 0 else 0.0,
        "co2_buffer_share":  co2_tp / total_tp if total_tp > 0 else 0.0,
        "h2_cap_mwh":   h2_cap,
        "meoh_cap_mwh": meoh_cap,
        "co2_cap_t":    co2_cap,
        "flexibility_premium": flex_premium,
        "lcof": m.get("lcof_per_t_diesel_equivalent", float("nan")),
    }


def plot(results: list[dict], min_pus: list[float],
         year: int, outpath: Path) -> None:
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(17, 6.5))
    fig.suptitle(
        f"How the plant stores energy between cheap and expensive hours ({year})",
        fontsize=14, fontweight="bold", y=0.995,
    )
    fig.text(0.5, 0.955,
             "Sensitivity to how much the methanol reactor can turn down "
             "(30% = very flexible, 70% = needs steady throughput)",
             ha="center", fontsize=10, color="dimgrey")

    labels = [f"{int(v*100)}%" for v in min_pus]
    x = np.arange(len(labels))
    width = 0.55

    # ── Panel 1: throughput share (%) stacked ─────────────────────────────
    h2_shares   = [r.get("h2_buffer_share",   0) * 100 for r in results]
    meoh_shares = [r.get("meoh_buffer_share", 0) * 100 for r in results]
    co2_shares  = [r.get("co2_buffer_share",  0) * 100 for r in results]

    ax1.bar(x, h2_shares,   width, label="Hydrogen tank",
            color=STORE_COLORS["Hydrogen tank"])
    ax1.bar(x, meoh_shares, width, bottom=h2_shares,
            label="Methanol tank", color=STORE_COLORS["Methanol tank"])
    ax1.bar(x, co2_shares,  width,
            bottom=np.array(h2_shares) + np.array(meoh_shares),
            label="CO₂ tank", color=STORE_COLORS["CO₂ tank"])
    ax1.set_xticks(x); ax1.set_xticklabels(labels, fontsize=10)
    ax1.set_xlabel("Methanol reactor minimum load", fontsize=10)
    ax1.set_ylabel("Share of annual tank cycling (%)", fontsize=10)
    ax1.set_title("Where does the cycling happen?", fontsize=11, fontweight="bold")
    ax1.legend(fontsize=9, loc="lower right")
    ax1.grid(axis="y", alpha=0.3)
    ax1.set_ylim(0, 115)

    # ── Panel 2: installed capacity ───────────────────────────────────────
    h2_cap   = [r.get("h2_cap_mwh",   0) / 1000 for r in results]   # GWh
    meoh_cap = [r.get("meoh_cap_mwh", 0) / 1000 for r in results]   # GWh
    co2_cap  = [r.get("co2_cap_t",    0) / 1000 for r in results]   # kt
    ax2.bar(x - width/3, h2_cap,   width/3, label="Hydrogen (GWh)",
            color=STORE_COLORS["Hydrogen tank"])
    ax2.bar(x,           meoh_cap, width/3, label="Methanol (GWh)",
            color=STORE_COLORS["Methanol tank"])
    ax2.bar(x + width/3, co2_cap,  width/3, label="CO₂ (kt)",
            color=STORE_COLORS["CO₂ tank"])
    ax2.set_xticks(x); ax2.set_xticklabels(labels, fontsize=10)
    ax2.set_xlabel("Methanol reactor minimum load", fontsize=10)
    ax2.set_ylabel("Optimal tank size (GWh or kilotonnes)", fontsize=10)
    ax2.set_title("How big do the tanks need to be?",
                  fontsize=11, fontweight="bold")
    ax2.legend(fontsize=9); ax2.grid(axis="y", alpha=0.3)

    # ── Panel 3: flexibility premium ──────────────────────────────────────
    flex_prems = [r.get("flexibility_premium", float("nan")) for r in results]
    bars = ax3.bar(x, flex_prems, width, color="#9b59b6", alpha=0.85)
    for bar, val in zip(bars, flex_prems):
        if not np.isnan(val):
            ax3.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                     f"${val:.1f}", ha="center", va="bottom", fontsize=9)
    ax3.set_xticks(x); ax3.set_xticklabels(labels, fontsize=10)
    ax3.set_xlabel("Methanol reactor minimum load", fontsize=10)
    ax3.set_ylabel("Cheap-power premium (AUD per MWh)", fontsize=10)
    ax3.set_title("How much cheaper than grid average\n"
                  "does the electrolyser buy?",
                  fontsize=11, fontweight="bold")
    ax3.grid(axis="y", alpha=0.3)
    ax3.axhline(0, color="black", linewidth=0.8)
    ax3.text(0.98, 0.02,
             "Positive = plant buys during\ncheaper-than-average hours",
             transform=ax3.transAxes, fontsize=8, color="dimgrey",
             va="bottom", ha="right",
             bbox=dict(facecolor="white", edgecolor="lightgrey", alpha=0.8, pad=3))

    plt.tight_layout(rect=[0, 0, 1, 0.94])
    plt.savefig(outpath, dpi=150, bbox_inches="tight")
    print(f"Saved {outpath}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2030)
    ap.add_argument("--out", default="chart_buffer_partition.png")
    args = ap.parse_args()

    results = []
    for mpu in MIN_PU_VALUES:
        print(f"Solving min_pu={mpu} …", flush=True)
        r = _solve_one(args.year, mpu)
        results.append(r)

    plot(results, MIN_PU_VALUES, args.year, Path(args.out))


if __name__ == "__main__":
    main()
