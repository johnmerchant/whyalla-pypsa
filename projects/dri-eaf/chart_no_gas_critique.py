"""The "No gas" critique: what does mandating 100% H2 from day one actually cost?

IEEFA argues gas is the wrong choice for Whyalla. This chart compares two LP
runs, both starting from the same March-2030 DRI commissioning date:

  - Policy-stated + gas flat  : LP picks the H2/NG blend. Dual-fuel MIDREX Flex.
  - No gas (100% H2)          : NG reductant banned. MIDREX H2 shaft, all-electric.

Both branches pay the same carbon price and face the same ISP Step Change
fleet. The only difference is whether the LP may burn pipeline gas in the
shaft. This isolates the no-gas *mandate* effect from policy-mix effects.

Four panels:
  [0,0] LCOS per tonne, year-by-year
  [0,1] Cumulative CO₂ abated vs BF-BOS baseline
  [1,0] Electrolyser + H2 storage buildout
  [1,1] Annual system cost (opex + annuity) — the "is gas the cheaper path?" answer

Output: chart_no_gas_critique.png
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).parent
TRAJ_CSV = HERE / "trajectory.csv"

DUAL_FUEL_LABEL = "Policy-stated + gas flat"
NO_GAS_LABEL = "No gas (100% H2)"

COLOR_DUAL = "#3d85c6"    # blue — LP-picked blend
COLOR_NOGAS = "#cc4125"   # red — 100% H2 mandate


def main():
    df = pd.read_csv(TRAJ_CSV)
    df = df[df.isp_scenario == "step_change"]

    dual = df[df.scenario == DUAL_FUEL_LABEL].sort_values("year").reset_index(drop=True)
    nogas = df[df.scenario == NO_GAS_LABEL].sort_values("year").reset_index(drop=True)

    if dual.empty or nogas.empty:
        raise SystemExit(
            f"Missing branches in {TRAJ_CSV}: dual={len(dual)} nogas={len(nogas)}"
        )

    fig, axes = plt.subplots(2, 2, figsize=(14, 9))

    # ── [0,0] LCOS per tonne ────────────────────────────────────────────────
    ax = axes[0, 0]
    ax.plot(dual.year, dual.lcos_per_t_steel, "o-", color=COLOR_DUAL,
            linewidth=2.2, markersize=7, label="Dual-fuel (LP picks blend)")
    ax.plot(nogas.year, nogas.lcos_per_t_steel, "s-", color=COLOR_NOGAS,
            linewidth=2.2, markersize=7, label="100% H2 mandate")
    ax.set_ylabel("LCOS ($AUD / t steel)", fontsize=11)
    ax.set_xlabel("Year")
    ax.set_title("Levelised cost of steel\n(myopic year-by-year, with irreversibility)", fontsize=12)
    ax.legend(fontsize=10, loc="upper right")
    ax.grid(alpha=0.3)
    ax.set_ylim(bottom=0)

    # Cost penalty annotation — $/t premium for no-gas, averaged.
    merged = dual[["year", "lcos_per_t_steel"]].merge(
        nogas[["year", "lcos_per_t_steel"]],
        on="year", suffixes=("_dual", "_nogas"), how="inner",
    )
    if not merged.empty:
        avg_premium = (merged.lcos_per_t_steel_nogas - merged.lcos_per_t_steel_dual).mean()
        ax.text(
            0.98, 0.05,
            f"Avg no-gas premium: +${avg_premium:,.0f}/t",
            transform=ax.transAxes, fontsize=10, fontweight="bold",
            ha="right", va="bottom",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff7d0", edgecolor="gray"),
        )

    # ── [0,1] Cumulative CO₂ abated ────────────────────────────────────────
    ax = axes[0, 1]
    dual["cum_abated_Mt"] = dual.emissions_saved_tCO2.cumsum() / 1e6
    nogas["cum_abated_Mt"] = nogas.emissions_saved_tCO2.cumsum() / 1e6
    ax.fill_between(dual.year, dual.cum_abated_Mt, alpha=0.15, color=COLOR_DUAL)
    ax.plot(dual.year, dual.cum_abated_Mt, "o-", color=COLOR_DUAL,
            linewidth=2.2, markersize=7, label="Dual-fuel")
    ax.fill_between(nogas.year, nogas.cum_abated_Mt, alpha=0.15, color=COLOR_NOGAS)
    ax.plot(nogas.year, nogas.cum_abated_Mt, "s-", color=COLOR_NOGAS,
            linewidth=2.2, markersize=7, label="100% H2")
    ax.set_ylabel("Cumulative CO₂ abated (Mt, vs BF-BOS)", fontsize=11)
    ax.set_xlabel("Year")
    ax.set_title("Abatement progress\n(both branches reach deep cuts — difference is in how fast)",
                 fontsize=12)
    ax.legend(fontsize=10, loc="upper left")
    ax.grid(alpha=0.3)
    ax.set_ylim(bottom=0)

    # ── [1,0] Electrolyser + H2 storage ─────────────────────────────────────
    ax = axes[1, 0]
    ax.plot(dual.year, dual.electrolyser_mw, "o-", color=COLOR_DUAL,
            linewidth=2.2, markersize=7, label="Dual-fuel electrolyser")
    ax.plot(nogas.year, nogas.electrolyser_mw, "s-", color=COLOR_NOGAS,
            linewidth=2.2, markersize=7, label="100% H2 electrolyser")
    ax.set_ylabel("Installed electrolyser (MW)", color="black", fontsize=11)
    ax.set_xlabel("Year")
    ax.set_title("Electrolyser + H2 storage buildout\n(100% H2 forces a ~10× larger ely fleet than LP-optimal blend)",
                 fontsize=12)
    ax.grid(alpha=0.3)

    ax2 = ax.twinx()
    ax2.plot(dual.year, dual.h2_storage_mwh / 1000, "o:", color=COLOR_DUAL,
             linewidth=1.5, markersize=5, alpha=0.7, label="Dual-fuel H2 store")
    ax2.plot(nogas.year, nogas.h2_storage_mwh / 1000, "s:", color=COLOR_NOGAS,
             linewidth=1.5, markersize=5, alpha=0.7, label="100% H2 store")
    ax2.set_ylabel("H2 storage (GWh_H2)", fontsize=10, color="gray")
    ax2.tick_params(axis="y", labelcolor="gray")

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, fontsize=9, loc="upper left")

    # ── [1,1] Annual system cost ────────────────────────────────────────────
    ax = axes[1, 1]
    ax.plot(dual.year, dual.annual_system_cost / 1e6, "o-", color=COLOR_DUAL,
            linewidth=2.2, markersize=7, label="Dual-fuel")
    ax.plot(nogas.year, nogas.annual_system_cost / 1e6, "s-", color=COLOR_NOGAS,
            linewidth=2.2, markersize=7, label="100% H2")
    ax.set_ylabel("Annual system cost ($M AUD)", fontsize=11)
    ax.set_xlabel("Year")
    ax.set_title("Total annual cost: opex + tranche annuities\n(the blue-red gap is what the gas option is worth)",
                 fontsize=12)
    ax.legend(fontsize=10, loc="upper left")
    ax.grid(alpha=0.3)
    ax.set_ylim(bottom=0)

    # Footnote: what the comparison means.
    fig.text(
        0.5, -0.01,
        "Both branches: March-2030 DRI commissioning, 2028 EAF scrap phase identical, "
        "same ISP Step Change grid, same carbon-price trajectory. "
        "Only difference: dual-fuel may burn pipeline gas at the shaft.",
        ha="center", va="top", fontsize=9, style="italic", color="gray",
    )

    fig.suptitle("Is gas the wrong choice for Whyalla? — A dispatch-model answer",
                 fontsize=14, fontweight="bold", y=1.00)
    fig.tight_layout()
    out = HERE / "chart_no_gas_critique.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")

    # Console summary for the critique write-up.
    print("\n─── No-gas critique summary ───")
    for yr in sorted(set(dual.year) & set(nogas.year)):
        d = dual[dual.year == yr].iloc[0]
        n = nogas[nogas.year == yr].iloc[0]
        print(
            f"  {yr}:  dual LCOS=${d.lcos_per_t_steel:,.0f}/t ely={d.electrolyser_mw:.0f} MW  |  "
            f"100% H2 LCOS=${n.lcos_per_t_steel:,.0f}/t ely={n.electrolyser_mw:.0f} MW  "
            f"(Δ=+${n.lcos_per_t_steel - d.lcos_per_t_steel:,.0f}/t)"
        )


if __name__ == "__main__":
    main()
