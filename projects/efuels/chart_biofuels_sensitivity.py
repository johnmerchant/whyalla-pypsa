"""Sensitivity heatmaps over the highest-uncertainty biofuels parameters.

Each heatmap is a 2D parameter sweep: at each cell, a single-year 2035
policy_stated solve is run with biofuels enabled, and the reported metric
(LCOF, biofuels dispatch, or electrolyser displacement) is recorded.

Sweeps produced:
  1. algae_productivity × diesel_price  → LCOF
  2. mallee_yield × diesel_price        → biofuels total fuel output
  3. waste_heat_availability × halophyte_oil_yield → HEFA dispatch

Run (fast smoke):
    uv run python chart_biofuels_sensitivity.py --grid-size 3

Run (publication-quality):
    uv run python chart_biofuels_sensitivity.py --grid-size 5 --workers 4
"""
from __future__ import annotations

import argparse
import copy
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from whyalla_pypsa import build_facility_network, attach_grid_price

from run import default_config
from process_chain import attach_efuels
from co2_supply import build_co2_supply_curve
from efuels_results import extract_lcom_lcof
from biofuels import attach_biofuels
from biofuels.attach import extract_biofuels_dispatch


@dataclass
class SweepCell:
    row_label: str
    col_label: str
    row_value: float
    col_value: float
    metric: float
    extra: dict


def _solve_one(*,
               year: int,
               diesel_price: float,
               kero_price: float,
               waste_heat_mwh_per_year: float,
               mandate_mt: float = 0.8,
               wacc: float = 0.11) -> dict:
    cfg = copy.deepcopy(default_config())
    cfg.scenario.model_year = year
    cfg.scenario.snapshot_mode = "representative_weeks"
    cfg.scenario.representative_weeks = 4   # faster solves for sweep
    cfg.pypsa_wacc = 0.07

    n = build_facility_network(cfg)
    attach_grid_price(n, cfg)

    attach_efuels(
        n,
        electrolyser_capex_per_kw=900.0,
        wacc=wacc,
        co2_supply_fn=lambda: build_co2_supply_curve(year),
        diesel_price_per_t=diesel_price,
        kero_price_per_t=kero_price,
        naphtha_price_per_t=1440.0,
        wax_price_per_t=2500.0,
        product_split_mode="hydrocracked_ft",
        annual_fuel_mt=mandate_mt,
    )
    attach_biofuels(
        n,
        wacc=wacc,
        waste_heat_mwh_per_year=waste_heat_mwh_per_year,
    )

    solver_opts = {**cfg.solver_options, "run_crossover": "off"}
    status, _ = n.optimize(solver_name=cfg.solver, solver_options=solver_opts)
    if status not in ("ok", "optimal"):
        return {"lcof": float("nan"), "biofuel_fuel_kt_per_yr": 0.0, "hefa_kt_per_yr": 0.0}

    m = extract_lcom_lcof(n, cfg)
    b = extract_biofuels_dispatch(n)

    # Total biofuel finished-fuel output (all pathways except gasification,
    # which routes through e-fuel refinery).
    biofuel_fuel_t = sum([
        b.get("htl_fuel_diesel_t_per_yr", 0),
        b.get("htl_fuel_kero_t_per_yr", 0),
        b.get("htl_fuel_naphtha_t_per_yr", 0),
        b.get("hefa_fuel_kero_t_per_yr", 0),
        b.get("hefa_fuel_diesel_t_per_yr", 0),
        b.get("hefa_fuel_naphtha_t_per_yr", 0),
        b.get("pyrolysis_fuel_diesel_t_per_yr", 0),
        b.get("pyrolysis_fuel_kero_t_per_yr", 0),
        b.get("pyrolysis_fuel_naphtha_t_per_yr", 0),
    ])
    hefa_fuel_t = sum([
        b.get("hefa_fuel_kero_t_per_yr", 0),
        b.get("hefa_fuel_diesel_t_per_yr", 0),
        b.get("hefa_fuel_naphtha_t_per_yr", 0),
    ])
    return {
        "lcof": m.get("lcof_per_t_diesel_equivalent", float("nan")),
        "ely_mw": m.get("ely_mw", 0.0),
        "biofuel_fuel_kt_per_yr": biofuel_fuel_t / 1000.0,
        "hefa_kt_per_yr": hefa_fuel_t / 1000.0,
    }


def _run_cell(kwargs: dict) -> dict:
    """Top-level wrapper for ProcessPoolExecutor (must be picklable)."""
    t0 = time.perf_counter()
    out = _solve_one(**kwargs)
    out["seconds"] = time.perf_counter() - t0
    return out


def _sweep(*, row_name: str, row_values: np.ndarray,
              col_name: str, col_values: np.ndarray,
              base_kwargs: dict, workers: int) -> np.ndarray:
    """Run a 2D sweep. Returns dict of numpy arrays shape (len(row), len(col))."""
    n_rows, n_cols = len(row_values), len(col_values)
    grid_tasks = []
    for i, rv in enumerate(row_values):
        for j, cv in enumerate(col_values):
            kw = dict(base_kwargs)
            kw[row_name] = rv
            kw[col_name] = cv
            grid_tasks.append((i, j, kw))

    results: dict[tuple[int,int], dict] = {}
    print(f"\n▶ sweep {row_name} × {col_name}: {n_rows}×{n_cols} = {len(grid_tasks)} solves")
    t0 = time.perf_counter()
    if workers <= 1:
        for i, j, kw in grid_tasks:
            results[(i, j)] = _run_cell(kw)
            print(f"  [{i},{j}] {row_name}={kw[row_name]:.2f} {col_name}={kw[col_name]:.2f} "
                  f"→ LCOF={results[(i,j)]['lcof']:.0f} "
                  f"biofuel={results[(i,j)]['biofuel_fuel_kt_per_yr']:.0f}kt "
                  f"({results[(i,j)]['seconds']:.1f}s)", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_run_cell, kw): (i, j) for i, j, kw in grid_tasks}
            for fut in as_completed(futures):
                i, j = futures[fut]
                results[(i, j)] = fut.result()
                print(f"  [{i},{j}] done LCOF={results[(i,j)]['lcof']:.0f} "
                      f"biofuel={results[(i,j)]['biofuel_fuel_kt_per_yr']:.0f}kt "
                      f"({results[(i,j)]['seconds']:.1f}s)", flush=True)
    print(f"  sweep done in {time.perf_counter()-t0:.0f}s")
    return results


def _plot_heatmap(results, row_values, col_values, *,
                  metric_key: str, title: str, subtitle: str,
                  cbar_label: str, xlabel: str, ylabel: str,
                  outpath: Path, cmap: str = "viridis", fmt: str = "{:.0f}") -> None:
    data = np.array([[results[(i, j)][metric_key]
                      for j in range(len(col_values))]
                     for i in range(len(row_values))])
    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(data, aspect="auto", cmap=cmap, origin="lower")
    ax.set_xticks(range(len(col_values)))
    ax.set_xticklabels([f"{v:g}" for v in col_values])
    ax.set_yticks(range(len(row_values)))
    ax.set_yticklabels([f"{v:g}" for v in row_values])
    for i in range(len(row_values)):
        for j in range(len(col_values)):
            ax.text(j, i, fmt.format(data[i, j]),
                    ha="center", va="center", fontsize=8,
                    color="white" if data[i, j] > (data.mean() + data.std()/3) else "black")
    cb = fig.colorbar(im, ax=ax)
    cb.set_label(cbar_label, fontsize=10)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    fig.suptitle(title, fontsize=13, fontweight="bold")
    fig.text(0.5, 0.92, subtitle, ha="center", fontsize=9, color="dimgrey")
    plt.tight_layout(rect=[0, 0, 1, 0.90])
    plt.savefig(outpath, dpi=150, bbox_inches="tight")
    print(f"  saved {outpath}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid-size", type=int, default=5, help="NxN cells per heatmap")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--year", type=int, default=2035)
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()
    N = args.grid_size
    outdir = Path(args.outdir)

    # Baseline aligned with the trajectory at the sweep year — see
    # MANDATE_PATH_MT in generate_trajectory.py (2035 mandate is 6.8 Mt).
    base_kwargs = dict(
        year=args.year,
        diesel_price=2150.0,
        kero_price=2310.0,
        waste_heat_mwh_per_year=200_000.0,
        mandate_mt=6.8,
        wacc=0.11,
    )

    # ── Sweep 1: diesel price × kero price → LCOF ────────────────────────
    diesel_prices = np.linspace(1500, 3200, N)
    kero_prices   = np.linspace(1700, 3400, N)
    r1 = _sweep(
        row_name="kero_price",
        row_values=kero_prices,
        col_name="diesel_price",
        col_values=diesel_prices,
        base_kwargs=base_kwargs, workers=args.workers,
    )
    _plot_heatmap(
        r1, kero_prices, diesel_prices, metric_key="lcof",
        title="Fuel prices vs LCOF",
        subtitle=f"{args.year} policy_stated, "
                 f"{base_kwargs['mandate_mt']:.1f} Mt mandate. Cells: AUD/t diesel-eq.",
        cbar_label="LCOF (AUD/t diesel-eq)",
        xlabel="Fossil diesel price (AUD/t)",
        ylabel="Fossil kero (jet) price (AUD/t)",
        outpath=outdir / "chart_biofuels_sweep_prices_lcof.png",
        cmap="viridis_r",
    )

    # ── Sweep 2: mandate × diesel price → biofuel output ─────────────────
    # Mandate range straddles the trajectory's 2035 mid-point so the sweep
    # reads against the post-fix 10.2 Mt peak path rather than the legacy
    # sub-Mt scale.
    mandates = np.linspace(2.0, 10.0, N)
    r2 = _sweep(
        row_name="mandate_mt",
        row_values=mandates,
        col_name="diesel_price",
        col_values=diesel_prices,
        base_kwargs=base_kwargs, workers=args.workers,
    )
    _plot_heatmap(
        r2, mandates, diesel_prices, metric_key="biofuel_fuel_kt_per_yr",
        title="Mandate × diesel price — biofuels output",
        subtitle=f"{args.year} policy_stated. Cells: kt finished biofuel / yr.",
        cbar_label="Biofuels output (kt/yr)",
        xlabel="Fossil diesel price (AUD/t)",
        ylabel="Mandate (Mt finished fuel / yr)",
        outpath=outdir / "chart_biofuels_sweep_mandate_output.png",
        cmap="viridis",
    )

    # ── Sweep 3: waste heat × mandate → LCOF ─────────────────────────────
    # Heat range widened (0 → 2 TWh/yr) so the sensitivity actually exposes
    # the shadow value of waste heat once total heat duty exceeds the
    # alternative supplies (electric heater + H₂ burner).
    waste_heat = np.linspace(0.0, 2_000_000.0, N)
    r3 = _sweep(
        row_name="waste_heat_mwh_per_year",
        row_values=waste_heat,
        col_name="mandate_mt",
        col_values=mandates,
        base_kwargs=base_kwargs, workers=args.workers,
    )
    _plot_heatmap(
        r3, waste_heat / 1000.0, mandates, metric_key="lcof",
        title="DRI waste heat vs mandate — LCOF",
        subtitle=f"{args.year} policy_stated. Cells: AUD/t diesel-eq.",
        cbar_label="LCOF (AUD/t diesel-eq)",
        xlabel="Mandate (Mt / yr)",
        ylabel="DRI waste heat available (GWh_th/yr)",
        outpath=outdir / "chart_biofuels_sweep_heat_lcof.png",
        cmap="viridis_r",
    )


if __name__ == "__main__":
    main()
