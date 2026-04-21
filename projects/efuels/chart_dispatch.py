"""Representative dispatch week at 30-min resolution — lay audience chart.

For three years (2030, 2035, 2040), plot how the plant actually runs over one
week at half-hourly resolution, showing that it follows the grid price signal.

Panels (top to bottom):
  1. Grid electricity price (AUD/MWh)
  2. Electrolyser power draw (MW) — when does it run?
  3. Hydrogen storage level (MWh) — how full is the tank?
  4. Methanol storage level (MWh)
  5. Methanol reactor throughput (MW)

Run:
    python chart_dispatch.py
"""
from __future__ import annotations

import argparse
import copy
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import pypsa

from whyalla_pypsa import build_facility_network, attach_grid_price

from run import default_config
from process_chain import attach_efuels

warnings.filterwarnings("ignore")

SNAPSHOT_YEARS = [2030, 2035, 2040]

# CAPEX trajectory (AUD/kW) — matches generate_trajectory.py "fast" path
_CAPEX_PATH = {2030: 1500, 2032: 1200, 2035: 900, 2038: 750, 2040: 700}
_WACC = 0.11


def _solve_year(year: int) -> pypsa.Network:
    cfg = copy.deepcopy(default_config())
    cfg.scenario.model_year = year
    cfg.scenario.resolution = "half_hourly"
    cfg.scenario.snapshot_mode = "representative_weeks"
    cfg.scenario.representative_weeks = 1   # single contiguous week for clean plotting
    cfg.pypsa_wacc = _WACC

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg)
    attach_efuels(
        n,
        electrolyser_capex_per_kw=_CAPEX_PATH.get(year, 1000),
        wacc=_WACC,
        product_split_mode="asf",
        annual_fuel_mt=0.5,
    )
    status, _ = n.optimize(
        solver_name=cfg.solver,
        solver_options={**cfg.solver_options, "run_crossover": "off"},
    )
    if status not in ("ok", "optimal"):
        raise RuntimeError(f"dispatch solve failed for {year}: {status}")
    return n


def _first_week_slice(n: pypsa.Network) -> pd.DatetimeIndex:
    """Return snapshots for the first 7 days × 48 half-hours = 336."""
    return n.snapshots[:336]


def _sum_refinery_throughput(n: pypsa.Network, snaps: pd.Index) -> pd.Series:
    total = pd.Series(0.0, index=snaps)
    for name in n.links.index:
        if name.startswith("refinery_"):
            s = n.links_t.p0.get(name, pd.Series(0.0, index=n.snapshots))
            total = total + s.reindex(snaps).fillna(0.0)
    return total


def plot(networks: dict[int, pypsa.Network], outpath: Path) -> None:
    n_years = len(networks)
    fig, axes = plt.subplots(5, n_years, figsize=(5.5 * n_years, 12),
                             sharey="row", sharex="col")
    if n_years == 1:
        axes = axes.reshape(-1, 1)
    fig.suptitle(
        "One week at the plant: how the plant follows grid electricity prices",
        fontsize=14, fontweight="bold", y=0.995,
    )
    fig.text(0.5, 0.965,
             "The electrolyser ramps up when power is cheap; "
             "storage tanks buffer the intermittency to keep the refinery steady",
             ha="center", fontsize=10, color="dimgrey")

    panel_titles = [
        "Grid electricity price\n(AUD per MWh)",
        "Electrolyser power draw\n(MW)",
        "Hydrogen tank level\n(MWh stored)",
        "Methanol tank level\n(MWh stored)",
        "Methanol reactor throughput\n(MW)",
    ]

    for col, (year, n) in enumerate(sorted(networks.items())):
        snaps = _first_week_slice(n)

        price = n.buses_t.marginal_price.get(
            "facility_ac", pd.Series(0, index=n.snapshots)).reindex(snaps)
        axes[0, col].plot(snaps, price, color="#e74c3c", linewidth=1.0)
        axes[0, col].axhline(float(price.mean()), color="black",
                             linestyle="--", linewidth=0.8, alpha=0.6)

        ely_p = n.links_t.p0.get(
            "electrolyser", pd.Series(0, index=n.snapshots)).reindex(snaps)
        axes[1, col].fill_between(snaps, ely_p, alpha=0.7, color="#3498db",
                                  step="post")

        h2_soc = n.stores_t.e.get(
            "h2_store", pd.Series(0, index=n.snapshots)).reindex(snaps)
        axes[2, col].fill_between(snaps, h2_soc, alpha=0.7, color="#2ecc71",
                                  step="post")

        meoh_soc = n.stores_t.e.get(
            "meoh_storage", pd.Series(0, index=n.snapshots)).reindex(snaps)
        axes[3, col].fill_between(snaps, meoh_soc, alpha=0.7, color="#f39c12",
                                  step="post")

        ref_p = _sum_refinery_throughput(n, snaps)
        axes[4, col].fill_between(snaps, ref_p, alpha=0.7, color="#9b59b6",
                                  step="post")

        axes[0, col].set_title(f"{year}", fontsize=13, fontweight="bold")
        for row in range(5):
            ax = axes[row, col]
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%a"))
            ax.xaxis.set_major_locator(mdates.DayLocator())
            ax.grid(alpha=0.25)
            if col == 0:
                ax.set_ylabel(panel_titles[row], fontsize=9)
            if row == 4:
                ax.set_xlabel("Day of week", fontsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.955])
    plt.savefig(outpath, dpi=150, bbox_inches="tight")
    print(f"Saved {outpath}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="chart_dispatch.png")
    args = ap.parse_args()

    networks: dict[int, pypsa.Network] = {}
    for yr in SNAPSHOT_YEARS:
        print(f"Solving dispatch year={yr} …", flush=True)
        networks[yr] = _solve_year(yr)

    plot(networks, Path(args.out))


if __name__ == "__main__":
    main()
