"""Strategic substitution — fuel-security investment case for Whyalla synthetic fuels.

Anchors the abstract "175 kbpd / ~31% of imports" headline number to *who actually
uses Australian liquid fuel* and *how much of their demand domestic synthetic
production would secure*.

Two stacked panels:

  Top: how Australia uses ~40 Mt/yr of jet + diesel
       (sectors: road freight, mining, aviation, agriculture, marine bunker,
        rail, defence, other), plus a second bar showing the 2040 imported
        portion (which flows through Singapore + Malacca chokepoints).

  Bottom: 2027-2040 time-series area chart of the Whyalla programme's domestic
          synthetic supply (diesel + kero), overlaid with horizontal reference
          lines for ADF (~1 Mt/yr), Mining diesel (~6 Mt/yr) and Aviation jet
          (~8 Mt/yr) so the reader sees when synthetic supply "covers" each
          category in volume terms.

Sources for sectoral breakdown (central FY2024-25 estimates):
  - BITRE Yearbook 2024-25 (Table 3.10 road freight; rail freight stats)
  - ABARES Energy Update 2024 (mining diesel; agriculture + fisheries diesel)
  - DFR (Department of Industry — Australian Petroleum Statistics)
  - IATA Jet Fuel Monitor + Avstats (aviation kerosene)
  - AMSA bunker fuel statistics (domestic marine bunker)
  - Defence Annual Report (ADF fuel ~$1B/yr split diesel/jet ~60/40)

Reads ``trajectory.csv`` produced by ``generate_trajectory.py``.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

# ── Sectoral breakdown of AU jet + diesel consumption (Mt/yr, FY24-25) ───
# Diesel + jet only — gasoline/petrol excluded (assumed electrified through 2030s
# via federal fuel-efficiency standards + EV uptake). Hard-to-electrify cuts.
SECTORS = [
    # (label, diesel_Mt, jet_Mt, colour)
    ("Road freight + commercial",   18.0, 0.0, "#4a6fa5"),  # steel-blue
    ("Aviation (commercial + GA)",   0.0, 8.0, "#7eb6d9"),  # sky-blue
    ("Mining diesel",                6.0, 0.0, "#8b5a3c"),  # earthy brown
    ("Agriculture + fisheries",      3.5, 0.0, "#6a8d4f"),  # muted green
    ("Marine bunker (domestic)",     2.0, 0.0, "#3d6b7a"),  # marine teal
    ("Other (constr., gen.)",        1.5, 0.0, "#a89a7d"),  # tan
    ("Rail freight + passenger",     0.8, 0.0, "#7a6855"),  # olive-brown
    ("ADF (Defence)",                0.6, 0.4, "#5a5a5a"),  # gunmetal grey
]

# Australian domestic refining (Lytton + Geelong) covers ~8 Mt/yr of diesel +
# jet between them; the remainder (~32.6 Mt/yr) is imported, mostly through
# Singapore and the Strait of Malacca. Imports therefore reflect ~80% of demand.
DOMESTIC_REFINING_MT_YR = 8.0  # combined diesel + jet output of Lytton + Geelong

# ── Domestic synthetic supply trajectory --------------------------------
SCENARIO_COLOURS = {
    "policy_stated": "#2980b9",
    "imo_binding":   "#27ae60",
    "foak_stranded": "#e74c3c",
}

# Reference horizontal lines for the bottom panel (Mt/yr of total demand).
DEMAND_REFERENCE_LINES = [
    ("ADF total fuel (~1 Mt/yr)",      1.0, "#5a5a5a"),
    ("Marine bunker (~2 Mt/yr)",       2.0, "#3d6b7a"),
    ("Agriculture + fisheries (~3.5)", 3.5, "#6a8d4f"),
    ("Mining diesel (~6 Mt/yr)",       6.0, "#8b5a3c"),
    ("Aviation jet (~8 Mt/yr)",        8.0, "#7eb6d9"),
]


def load(csv: Path, scenario: str) -> pd.DataFrame:
    df = pd.read_csv(csv)
    df["year"] = df["year"].astype(int)
    sub = df[df.scenario == scenario].sort_values("year").reset_index(drop=True)
    if sub.empty:
        raise SystemExit(f"ERROR: scenario '{scenario}' not in {csv}")
    return sub


def _draw_stacked_bar(ax, y_pos: float, segments: list[tuple], total: float,
                      bar_height: float = 0.55, label_threshold_pct: float = 3.0,
                      show_inline_labels: bool = True) -> None:
    """Draw one horizontal stacked bar at y_pos with segment labels.

    segments: list of (label, value, colour)
    """
    left = 0.0
    for label, value, colour in segments:
        if value <= 0:
            continue
        ax.barh(y_pos, value, left=left, height=bar_height,
                color=colour, edgecolor="white", linewidth=0.8)
        pct = 100.0 * value / total if total > 0 else 0.0
        if show_inline_labels and pct >= label_threshold_pct:
            text_colour = "white" if _is_dark(colour) else "#1a1a1a"
            ax.text(left + value / 2, y_pos,
                    f"{label}\n{value:.1f} Mt ({pct:.0f}%)",
                    ha="center", va="center",
                    fontsize=8.0, color=text_colour, fontweight="bold")
        left += value


def _is_dark(hex_colour: str) -> bool:
    """Rough luminance check for white-vs-black inline label text."""
    h = hex_colour.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # Rec. 709 luminance
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return lum < 130


def plot(df: pd.DataFrame, outpath: Path, scenario: str) -> None:
    fig = plt.figure(figsize=(14, 9.5))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 1.25],
                          hspace=0.50, top=0.86, bottom=0.07,
                          left=0.07, right=0.96)
    ax_top = fig.add_subplot(gs[0])
    ax_bot = fig.add_subplot(gs[1])

    fig.suptitle(
        "What this programme actually buys — fuel security by sector",
        fontsize=15, fontweight="bold", y=0.97,
    )
    fig.text(0.5, 0.925,
             "Top: how Australia uses ~40 Mt/yr of jet + diesel.   "
             "Bottom: the Whyalla programme's domestic synthetic supply "
             "growing 2027-2040, in context of major sector demand.",
             ha="center", fontsize=9.5, color="dimgrey")

    # ════════════════════════════════════════════════════════════════════
    # TOP PANEL — sector breakdown bars
    # ════════════════════════════════════════════════════════════════════
    # Combine diesel+jet into a single Mt for each sector for the headline bar.
    total_segments = [(lbl, d + j, col) for lbl, d, j, col in SECTORS]
    total_demand = sum(v for _, v, _ in total_segments)

    # Imported portion = consumption minus domestic refining (8 Mt/yr Lytton+Geelong).
    # Apportion the domestic refining shortfall pro-rata across sectors so the
    # imports bar still tells a sectoral story.
    import_share = max(0.0, 1.0 - DOMESTIC_REFINING_MT_YR / total_demand)
    import_segments = [(lbl, v * import_share, col)
                       for lbl, v, col in total_segments]
    import_total = sum(v for _, v, _ in import_segments)

    # Two bars: total consumption (top), imported portion (bottom)
    _draw_stacked_bar(ax_top, y_pos=1.0, segments=total_segments,
                      total=total_demand)
    _draw_stacked_bar(ax_top, y_pos=0.0, segments=import_segments,
                      total=import_total, label_threshold_pct=4.5)

    ax_top.set_yticks([1.0, 0.0])
    ax_top.set_yticklabels(
        [f"AU consumption\n(~{total_demand:.0f} Mt/yr)",
         f"AU imports — Singapore /\nMalacca chokepoint\n(~{import_total:.0f} Mt/yr)"],
        fontsize=9.5,
    )
    ax_top.set_xlabel("Million tonnes per year (jet + diesel only — gasoline excluded)",
                      fontsize=10)
    ax_top.set_xlim(0, total_demand * 1.02)
    ax_top.set_ylim(-0.55, 1.55)
    ax_top.set_title("Australia's annual liquid-fuel consumption by sector "
                     "(diesel + jet, FY24-25)",
                     fontsize=11.5, fontweight="bold", loc="left")
    ax_top.grid(axis="x", alpha=0.25)
    ax_top.set_axisbelow(True)
    for spine in ("top", "right"):
        ax_top.spines[spine].set_visible(False)

    # Annotation: domestic refining baseline
    ax_top.text(0.99, 0.02,
                f"Domestic refineries (Lytton + Geelong) supply\n"
                f"~{DOMESTIC_REFINING_MT_YR:.0f} Mt/yr — the rest "
                f"(~{import_total:.0f} Mt/yr, {100*import_share:.0f}% of demand)\n"
                f"is imported, almost entirely through\n"
                f"Singapore and the Strait of Malacca.",
                transform=ax_top.transAxes, fontsize=8, color="#2c3e50",
                va="bottom", ha="right",
                bbox=dict(facecolor="white", edgecolor="#2c3e50",
                          alpha=0.85, pad=4))

    # ════════════════════════════════════════════════════════════════════
    # BOTTOM PANEL — synthetic supply trajectory vs sector demand
    # ════════════════════════════════════════════════════════════════════
    years = df["year"].to_numpy()
    diesel_mt = df["diesel_tonnes"].fillna(0).to_numpy() / 1e6
    kero_mt = df["kero_tonnes"].fillna(0).to_numpy() / 1e6

    # Densify: trajectory has gaps (2031, 2033-34, 2036-37, 2039) — interpolate.
    yr_dense = np.arange(years.min(), years.max() + 1)
    diesel_dense = np.interp(yr_dense, years, diesel_mt)
    kero_dense = np.interp(yr_dense, years, kero_mt)

    # Stacked area: diesel (bottom) + kero (top)
    ax_bot.fill_between(yr_dense, 0, diesel_dense,
                        color="#8b5a3c", alpha=0.85, edgecolor="#5a3a25",
                        linewidth=1.6, label="Synthetic diesel (Whyalla)")
    ax_bot.fill_between(yr_dense, diesel_dense, diesel_dense + kero_dense,
                        color="#7eb6d9", alpha=0.85, edgecolor="#3a6f8f",
                        linewidth=1.6, label="Synthetic jet (Whyalla)")

    # Heavy edge on the total
    total_dense = diesel_dense + kero_dense
    ax_bot.plot(yr_dense, total_dense,
                color="#1a3540", linewidth=2.0, zorder=3)

    # Sector demand reference lines
    x_right = years.max()
    for label, level, colour in DEMAND_REFERENCE_LINES:
        ax_bot.axhline(level, color=colour, linestyle="--",
                       linewidth=1.2, alpha=0.85, zorder=2)
        ax_bot.text(x_right + 0.15, level, f"  {label}",
                    fontsize=8, color=colour, va="center", ha="left",
                    bbox=dict(facecolor="white", edgecolor="none",
                              alpha=0.85, pad=1.2))

    ax_bot.set_xlim(years.min(), years.max() + 2.6)
    ymax = max(total_dense.max() * 1.15, 10.0)
    ax_bot.set_ylim(0, ymax)
    ax_bot.set_xlabel("Year", fontsize=10)
    ax_bot.set_ylabel("Million tonnes per year (synthetic supply)", fontsize=10)
    ax_bot.set_title(
        f"Whyalla domestic synthetic supply 2027–2040 vs sector demand "
        f"(scenario: {scenario})",
        fontsize=11.5, fontweight="bold", loc="left",
    )
    ax_bot.xaxis.set_major_locator(MaxNLocator(integer=True, nbins=14))
    ax_bot.grid(alpha=0.3)
    ax_bot.set_axisbelow(True)
    ax_bot.legend(fontsize=9, loc="upper left", frameon=True)

    # Endpoint callout
    end_diesel = diesel_dense[-1]
    end_kero = kero_dense[-1]
    end_total = total_dense[-1]

    # Identify cross-over years for headline lines (mining diesel = 6, aviation jet = 8)
    def _crossing_year(arr: np.ndarray, level: float) -> int | None:
        for i, v in enumerate(arr):
            if v >= level:
                return int(yr_dense[i])
        return None

    yr_cross_mining = _crossing_year(diesel_dense, 6.0)
    yr_cross_aviation = _crossing_year(kero_dense, 8.0)
    yr_cross_adf = _crossing_year(total_dense, 1.0)

    cross_lines = []
    if yr_cross_adf:
        cross_lines.append(f"  ADF total demand (1 Mt) covered by {yr_cross_adf}")
    if yr_cross_mining:
        cross_lines.append(f"  Mining diesel (6 Mt) covered by {yr_cross_mining}")
    else:
        cross_lines.append("  Mining diesel (6 Mt) not fully covered by 2040")
    if yr_cross_aviation:
        cross_lines.append(f"  Aviation jet (8 Mt) covered by {yr_cross_aviation}")
    else:
        cross_lines.append("  Aviation jet (8 Mt) not fully covered by 2040")

    callout = (
        f"By {int(yr_dense[-1])}: {end_total:.1f} Mt/yr synthetic\n"
        f"  diesel {end_diesel:.1f} Mt + jet {end_kero:.1f} Mt\n"
        f"≈ {100 * end_total / 40.8:.0f}% of total AU jet+diesel demand\n"
        + "\n".join(cross_lines)
    )
    ax_bot.text(0.015, 0.97, callout,
                transform=ax_bot.transAxes, fontsize=8.5, fontweight="bold",
                color="#1a3540", va="top", ha="left",
                bbox=dict(facecolor="white", edgecolor="#1a3540",
                          alpha=0.88, pad=5))

    for spine in ("top", "right"):
        ax_bot.spines[spine].set_visible(False)

    # Caption
    fig.text(
        0.5, 0.012,
        "Sources: BITRE Yearbook 2024-25, ABARES Energy Update, "
        "IATA Jet Fuel Monitor, DFR Australian Petroleum Statistics, "
        "AMSA bunker stats, Defence AAR.   "
        "Domestic supply trajectory from trajectory.csv policy_stated scenario.",
        ha="center", fontsize=8, color="dimgrey", style="italic",
    )

    plt.savefig(outpath, dpi=160, bbox_inches="tight")
    print(f"Saved {outpath}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="trajectory.csv")
    ap.add_argument("--out", default="chart_strategic_substitution.png")
    ap.add_argument("--scenario", default="policy_stated")
    args = ap.parse_args()

    csv = Path(args.csv)
    if not csv.exists():
        print(f"ERROR: {csv} not found — run generate_trajectory.py first")
        raise SystemExit(1)

    df = load(csv, args.scenario)
    plot(df, Path(args.out), args.scenario)


if __name__ == "__main__":
    main()
