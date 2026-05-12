"""Electrification split — what synthetic fuel actually replaces.

Strengthens the fuel-security investment case for the Whyalla synthetic-fuels
precinct by showing that domestic synthetic fuel is targeting *genuinely*
hard-to-electrify sectors -- not competing with sectors that battery-electric
(BEV), overhead-catenary, or short-range marine electrification will already
solve by 2035-2040.

Two stacked panels:

  Top:    2024 baseline -- horizontal stacked bar of Australia's jet + diesel
          demand by sector, coloured by electrification feasibility category
          (GREEN: readily electrifiable; AMBER: partially electrifiable;
          RED: must-have liquid fuel through 2040+).

  Bottom: 2040 projection -- same horizontal stacked bar, but with sector
          volumes adjusted for plausible electrification penetration. Overlay
          a horizontal reference band for the Whyalla programme's domestic
          synthetic supply (10.2 Mt/yr at 2040, from trajectory.csv
          policy_stated). The reader sees that GREEN sectors shrink
          dramatically, AMBER sectors moderately, RED sectors stay roughly
          flat -- and the synthetic-supply line lands neatly in the RED+AMBER
          zone, NOT competing with GREEN.

Sector defaults (FY24-25 central) extrapolated from:
  - BITRE Yearbook 2024-25 (road freight, rail freight)
  - ABARES Energy Update 2024 (mining diesel; agriculture; fisheries)
  - AU MMA Battery-Electric Trucks Roadmap 2024 (LCV / urban-bus shares)
  - BHP Operational Decarbonisation Plan 2023 (haul-truck BEV/trolley share)
  - IATA Net Zero by 2050 (aviation jet demand growth, no electric pathway)
  - AMSA bunker fuel statistics (deep-sea vs domestic marine split)
  - Defence Annual Report (ADF total fuel ~$1B/yr, ~60/40 diesel/jet)

Reads ``trajectory.csv`` produced by ``generate_trajectory.py``.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pandas as pd

# ─── Sector definitions ────────────────────────────────────────────────────
# Each entry: (label, diesel_2024_Mt, jet_2024_Mt, total_2040_Mt, category, colour)
#
# Categories:
#   GREEN  -- readily electrifiable by 2035 (-75% to -90% by 2040)
#   AMBER  -- partially electrifiable by 2040 (-30% to -50%)
#   RED    -- must-have liquid fuel (~ -5% to -10%; some sectors grow)
#
# 2040 totals are after applying plausible electrification penetration.
# Comments below each sector explain the defensible default chosen.

SECTORS = [
    # ── RED: must-have liquid fuel ─────────────────────────────────────
    # Long-haul road freight: B-doubles + road trains across remote AU.
    # MMA Roadmap 2024: BEV trucks economic <500 km; long-haul (>1000 km
    # remote) requires liquid fuel through 2040+. Slight efficiency gain.
    ("Long-haul heavy road freight",   10.5, 0.0,  9.5, "RED",   "#c0392b"),

    # Commercial aviation: IATA NZ50 -- no electric/H2 narrow-body option
    # at scale before 2040; SAF is the only drop-in path. Demand grows.
    ("Commercial aviation (jet)",       0.0, 7.5,  8.0, "RED",   "#e74c3c"),

    # General / regional aviation: small share, very slight decline
    # (battery-electric possible for small aircraft, but tiny volume).
    ("General / regional aviation",     0.0, 0.5,  0.4, "RED",   "#a93226"),

    # Deep-sea marine bunker: IMO trajectory points to e-methanol /
    # e-ammonia / drop-in synthetic fuels. Volume essentially flat.
    ("Deep-sea marine bunker",          1.5, 0.0,  1.5, "RED",   "#922b21"),

    # Heavy agriculture + fisheries: large tractors, harvesters, fishing
    # fleet. Battery weight/duty cycle prohibitive; slight efficiency.
    ("Heavy agriculture + fisheries",   3.0, 0.0,  2.7, "RED",   "#cd5c5c"),

    # Remote / off-grid mining: pits without grid connection, drilling.
    # No realistic electrification path; remains diesel.
    ("Remote / off-grid mining",        2.0, 0.0,  1.9, "RED",   "#7b241c"),

    # ADF deployment fuel: F-35 / heavy transport / armoured vehicles.
    # Force structure plan implies slight growth, no electric pathway.
    ("ADF deployment fuel",             1.0, 0.4,  1.5, "RED",   "#641e16"),

    # ── AMBER: partially electrifiable ──────────────────────────────────
    # Large open-pit mining haul trucks: BHP/Rio committed to BEV +
    # trolley-assist for grid-connected pits by 2030. Assume 50%
    # electrified at large pits by 2040.
    ("Large open-pit mining (haul)",    4.0, 0.0,  2.0, "AMBER", "#d35400"),

    # Long-haul rail freight: not yet electrified outside metro corridors;
    # progressive overhead-catenary on heavy haul lines + battery-locos.
    ("Long-haul rail freight",          0.3, 0.0,  0.2, "AMBER", "#e67e22"),

    # Heavy construction equipment: excavators, large dozers, mobile
    # cranes. Some BEV options emerging; mostly liquid-fuelled to 2040.
    ("Heavy construction equipment",    1.5, 0.0,  1.2, "AMBER", "#f39c12"),

    # ── GREEN: readily electrifiable ────────────────────────────────────
    # Light commercial / last-mile delivery: vans, courier fleets. MMA
    # Roadmap: 80%+ BEV penetration by 2040 economically rational.
    ("Light commercial / last-mile",    4.5, 0.0,  0.9, "GREEN", "#16a085"),

    # Urban + suburban buses: TfNSW + VicGov fleet electrification;
    # most major-city operators committed to 100% BEV new-bus by 2030.
    ("Urban / suburban buses",          0.5, 0.0,  0.1, "GREEN", "#27ae60"),

    # Short-haul rail freight: metro/intermodal corridors, mostly
    # already electrifiable; battery-loco for last-mile.
    ("Short-haul rail freight",         0.5, 0.0,  0.1, "GREEN", "#2ecc71"),

    # Domestic marine / ferries: Sydney + Brisbane CityCats already
    # electrifying; battery-electric short routes mainstream by 2035.
    ("Domestic marine / ferries",       0.5, 0.0,  0.1, "GREEN", "#1abc9c"),

    # Light agriculture: ATVs, small tractors, orchard equipment.
    # Battery-electric mainstream by 2035 (Kubota/John Deere ranges).
    ("Light agriculture (ATV / small)", 0.5, 0.0,  0.1, "GREEN", "#52be80"),
]

# Compact inline labels used for narrow stacked-bar segments. Full sector
# names overflow segments below ~12% of bar width; short forms fit cleanly
# while the full name still appears in external callouts and the legend.
SHORT_LABEL = {
    "Long-haul heavy road freight":    "Long-haul road",
    "Commercial aviation (jet)":       "Commercial aviation",
    "General / regional aviation":     "Regional aviation",
    "Deep-sea marine bunker":          "Deep-sea marine",
    "Heavy agriculture + fisheries":   "Heavy ag.",
    "Remote / off-grid mining":        "Off-grid mining",
    "ADF deployment fuel":             "ADF deployment",
    "Large open-pit mining (haul)":    "Open-pit haul",
    "Long-haul rail freight":          "Long-haul rail",
    "Heavy construction equipment":    "Heavy construction",
    "Light commercial / last-mile":    "Light commercial",
    "Urban / suburban buses":          "Urban buses",
    "Short-haul rail freight":         "Short-haul rail",
    "Domestic marine / ferries":       "Ferries",
    "Light agriculture (ATV / small)": "Light ag.",
    "Other small electrifiable":       "Other electrifiable",
}

# Category metadata for the legend.
CATEGORY_META = [
    ("GREEN",
     "Readily electrifiable by 2035",
     "Battery-electric / overhead-catenary / urban-electric solutions are\n"
     "already commercial. Synthetic fuel is NOT targeting these sectors.",
     "#27ae60"),
    ("AMBER",
     "Partially electrifiable by 2040",
     "Hybrid / trolley-assist / mixed BEV pathways. Residual liquid\n"
     "demand for the unelectrified share.",
     "#e67e22"),
    ("RED",
     "Must-have liquid fuel through 2040+",
     "Physical/operational reasons preclude electrification. This is the\n"
     "addressable market for domestic synthetic fuel.",
     "#c0392b"),
]


# ─── Helpers ───────────────────────────────────────────────────────────────

def _is_dark(hex_colour: str) -> bool:
    """Rough luminance check for white-vs-black inline label text."""
    h = hex_colour.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return lum < 130


def _aggregate_tiny(sectors: list[tuple],
                    threshold_2024: float = 0.6,
                    threshold_2040: float = 0.6) -> list[tuple]:
    """Pool same-category sectors that are sub-threshold in BOTH years.

    Reduces label-cluster at the narrow right end of each bar where five
    GREEN sectors at 0.5 Mt sit on top of each other. Only categories
    with two or more pool-eligible members are merged; singletons stay.
    """
    keep: list[tuple] = []
    pools: dict[str, list[tuple]] = {}
    for s in sectors:
        _label, d, j, t40, cat, _col = s
        if (d + j) < threshold_2024 and t40 < threshold_2040:
            pools.setdefault(cat, []).append(s)
        else:
            keep.append(s)

    other_meta = {
        "GREEN": ("Other small electrifiable", "#2ecc71"),
        "AMBER": ("Other partially electrifiable", "#e67e22"),
        "RED":   ("Other liquid-fuel sectors", "#cd5c5c"),
    }
    for cat, members in pools.items():
        if len(members) >= 2:
            d_sum = sum(m[1] for m in members)
            j_sum = sum(m[2] for m in members)
            t40_sum = sum(m[3] for m in members)
            label, colour = other_meta[cat]
            keep.append((label, d_sum, j_sum, t40_sum, cat, colour))
        else:
            keep.extend(members)
    return keep


def _draw_stacked_bar(ax, y_pos: float, segments: list[tuple],
                      total: float, bar_height: float = 0.55,
                      label_threshold_pct: float = 3.5,
                      narrow_pct: float = 12.0) -> None:
    """Draw one horizontal stacked bar with inline labels above threshold.

    Narrow segments (below ``narrow_pct`` of total width) use the
    short-form label so the inline text fits within the segment.

    segments: list of (label, value, colour)
    """
    left = 0.0
    for label, value, colour in segments:
        if value <= 0:
            continue
        ax.barh(y_pos, value, left=left, height=bar_height,
                color=colour, edgecolor="white", linewidth=0.6)
        pct = 100.0 * value / total if total > 0 else 0.0
        if pct >= label_threshold_pct:
            text_colour = "white" if _is_dark(colour) else "#1a1a1a"
            disp = SHORT_LABEL.get(label, label) if pct < narrow_pct else label
            ax.text(left + value / 2, y_pos,
                    f"{disp}\n{value:.1f} Mt ({pct:.0f}%)",
                    ha="center", va="center",
                    fontsize=7.6, color=text_colour, fontweight="bold")
        left += value


def _draw_external_labels(ax, y_pos: float, segments: list[tuple],
                          total: float, label_threshold_pct: float = 3.5,
                          y_offsets: tuple[float, float] = (0.55, 0.95)) -> None:
    """External leader-style labels for thin segments below threshold.

    Cycles through 4 slots — (above-near, below-near, above-far, below-far) —
    so adjacent thin segments never share a y-tier. Resolves the cluster
    at the narrow right end where multiple sub-threshold segments compete.
    """
    left = 0.0
    thin: list[tuple[str, float, str, float]] = []
    for label, value, colour in segments:
        if value > 0:
            pct = 100.0 * value / total if total > 0 else 0.0
            if pct < label_threshold_pct:
                thin.append((label, value, colour, left + value / 2))
        left += value

    thin.sort(key=lambda t: t[3])

    slots = [
        (+1, y_offsets[0]),
        (-1, y_offsets[0]),
        (+1, y_offsets[1]),
        (-1, y_offsets[1]),
    ]
    for idx, (label, value, colour, x_mid) in enumerate(thin):
        side, off = slots[idx % len(slots)]
        y_text = y_pos + side * off
        ax.annotate(
            f"{label}\n{value:.1f} Mt",
            xy=(x_mid, y_pos + (0.28 if side > 0 else -0.28)),
            xytext=(x_mid, y_text),
            ha="center", va="bottom" if side > 0 else "top",
            fontsize=7.0, color=colour, fontweight="bold",
            arrowprops=dict(arrowstyle="-", color=colour,
                            lw=0.6, alpha=0.8),
        )


# ─── Data loaders ──────────────────────────────────────────────────────────

def load_synthetic_supply(csv: Path, scenario: str, year: int = 2040) -> float:
    """Read mandated_fuel_mt for the given scenario+year from trajectory.csv."""
    df = pd.read_csv(csv)
    df["year"] = df["year"].astype(int)
    row = df[(df.scenario == scenario) & (df.year == year)]
    if row.empty:
        raise SystemExit(
            f"ERROR: scenario '{scenario}' year {year} not in {csv}"
        )
    return float(row.iloc[0]["mandated_fuel_mt"])


# ─── Plot ──────────────────────────────────────────────────────────────────

def plot(synth_mt_2040: float, outpath: Path, scenario: str) -> None:
    fig = plt.figure(figsize=(14, 10.5))
    gs = fig.add_gridspec(2, 1, height_ratios=[1.0, 1.0],
                          hspace=0.85, top=0.84, bottom=0.08,
                          left=0.06, right=0.97)
    ax_top = fig.add_subplot(gs[0])
    ax_bot = fig.add_subplot(gs[1])

    fig.suptitle(
        "What electrifies, what doesn't — and where synthetic fuel actually fits",
        fontsize=15, fontweight="bold", y=0.965,
    )

    # Pool sub-0.6-Mt same-category sectors before plotting so the right
    # end of the bar isn't crowded with five 0.5-Mt segments.
    sectors_pooled = _aggregate_tiny(SECTORS)

    # Compute totals for both years (totals match SECTORS sums; aggregation
    # only re-distributes within categories).
    total_2024 = sum(d + j for _, d, j, _, _, _ in sectors_pooled)
    total_2040 = sum(t40 for _, _, _, t40, _, _ in sectors_pooled)

    # Sort each panel: RED first (left), AMBER, GREEN -- so the reader's
    # eye lands on the must-have-liquid block first.
    cat_order = {"RED": 0, "AMBER": 1, "GREEN": 2}
    sectors_sorted = sorted(sectors_pooled,
                            key=lambda s: (cat_order[s[4]], -s[1] - s[2]))

    segments_2024 = [(lbl, d + j, col)
                     for lbl, d, j, _, _, col in sectors_sorted]
    segments_2040 = [(lbl, t40, col)
                     for lbl, _, _, t40, _, col in sectors_sorted]

    # Subtitle / explainer line.
    fig.text(
        0.5, 0.918,
        f"Top: 2024 jet + diesel demand ({total_2024:.1f} Mt/yr) by sector and "
        "electrification feasibility.   "
        f"Bottom: 2040 projection ({total_2040:.1f} Mt/yr) after plausible "
        "electrification penetration.\n"
        "The Whyalla programme targets the residual liquid-fuel demand that "
        "physically cannot electrify.",
        ha="center", fontsize=9.5, color="dimgrey",
    )

    # Compute residual RED + AMBER for 2040 (the addressable market).
    residual_red_amber_2040 = sum(
        t40 for _, _, _, t40, cat, _ in SECTORS if cat in ("RED", "AMBER")
    )
    residual_green_2040 = sum(
        t40 for _, _, _, t40, cat, _ in SECTORS if cat == "GREEN"
    )

    # ════════════════════════════════════════════════════════════════════
    # TOP PANEL — 2024 baseline
    # ════════════════════════════════════════════════════════════════════
    _draw_stacked_bar(ax_top, y_pos=0.0, segments=segments_2024,
                      total=total_2024, label_threshold_pct=7.5)
    _draw_external_labels(ax_top, y_pos=0.0, segments=segments_2024,
                          total=total_2024, label_threshold_pct=7.5,
                          y_offsets=(0.55, 0.95))

    ax_top.set_yticks([0.0])
    ax_top.set_yticklabels(
        [f"2024 baseline\n{total_2024:.1f} Mt/yr"], fontsize=10,
        fontweight="bold",
    )
    ax_top.set_xlim(0, max(total_2024, total_2040) * 1.02)
    ax_top.set_ylim(-1.45, 1.45)
    ax_top.set_xlabel("Million tonnes per year (jet + diesel only — gasoline excluded)",
                      fontsize=9.5)
    ax_top.set_title(
        "Australia's annual jet + diesel consumption by sector (FY24-25)",
        fontsize=11.5, fontweight="bold", loc="left",
    )
    ax_top.grid(axis="x", alpha=0.25)
    ax_top.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax_top.spines[spine].set_visible(False)
    ax_top.tick_params(axis="y", length=0)

    # ════════════════════════════════════════════════════════════════════
    # BOTTOM PANEL — 2040 projection + Whyalla overlay
    # ════════════════════════════════════════════════════════════════════
    _draw_stacked_bar(ax_bot, y_pos=0.0, segments=segments_2040,
                      total=total_2040, label_threshold_pct=7.5)
    _draw_external_labels(ax_bot, y_pos=0.0, segments=segments_2040,
                          total=total_2040, label_threshold_pct=7.5,
                          y_offsets=(0.55, 0.95))

    # Whyalla synthetic-supply overlay band: translucent rectangle [0, synth].
    band_height = 0.95  # taller than the 0.55 bar to clearly span/overlap
    rect = mpatches.Rectangle(
        (0.0, -band_height / 2), synth_mt_2040, band_height,
        facecolor="#2980b9", alpha=0.22, edgecolor="#1b4f72",
        linewidth=1.4, linestyle="--", zorder=4,
    )
    ax_bot.add_patch(rect)

    # Vertical right edge of the band -- emphasised dashed line.
    ax_bot.axvline(synth_mt_2040, color="#1b4f72", linestyle="--",
                   linewidth=1.6, alpha=0.85, zorder=5,
                   ymin=0.5 - band_height / 2.2 / 2, ymax=0.5 + band_height / 2.2 / 2)

    # Label callout above the band.
    pct_of_residual = 100.0 * synth_mt_2040 / residual_red_amber_2040
    ax_bot.annotate(
        f"Whyalla domestic supply {synth_mt_2040:.1f} Mt/yr\n"
        f"(= {pct_of_residual:.0f}% of residual 2040 RED+AMBER demand)",
        xy=(synth_mt_2040, 0.48),
        xytext=(synth_mt_2040 * 0.50, 0.92),
        ha="center", va="bottom",
        fontsize=9.0, fontweight="bold", color="#1b4f72",
        bbox=dict(facecolor="white", edgecolor="#1b4f72",
                  alpha=0.92, pad=4, boxstyle="round,pad=0.4"),
        arrowprops=dict(arrowstyle="->", color="#1b4f72",
                        lw=1.0, alpha=0.85),
        zorder=6,
    )

    ax_bot.set_yticks([0.0])
    ax_bot.set_yticklabels(
        [f"2040 projection\n{total_2040:.1f} Mt/yr"], fontsize=10,
        fontweight="bold",
    )
    ax_bot.set_xlim(0, max(total_2024, total_2040) * 1.02)
    ax_bot.set_ylim(-1.45, 1.45)
    ax_bot.set_xlabel("Million tonnes per year (jet + diesel only — gasoline excluded)",
                      fontsize=9.5)
    ax_bot.set_title(
        f"2040 projection after plausible electrification penetration "
        f"(synthetic supply: {scenario} scenario)",
        fontsize=11.5, fontweight="bold", loc="left",
    )
    ax_bot.grid(axis="x", alpha=0.25)
    ax_bot.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax_bot.spines[spine].set_visible(False)
    ax_bot.tick_params(axis="y", length=0)

    # ── Inset legend (category meaning) ─────────────────────────────────
    # Place at top-right of the top axes (free space because RED is at the
    # left of each bar).
    legend_handles = [
        mpatches.Patch(facecolor=col, edgecolor="white",
                       label=f"{cat} — {short}")
        for cat, short, _long, col in CATEGORY_META
    ]
    legend = ax_top.legend(
        handles=legend_handles,
        loc="upper right", fontsize=8.0, frameon=True, framealpha=0.92,
        edgecolor="#888", title="Electrification feasibility",
        title_fontsize=8.5,
    )
    legend.get_title().set_fontweight("bold")

    # ── Headline numbers callout (bottom panel) ─────────────────────────
    callout = (
        f"By 2040 (after electrification):\n"
        f"  Total residual liquid demand:  {total_2040:.1f} Mt/yr\n"
        f"  RED + AMBER (addressable):      {residual_red_amber_2040:.1f} Mt/yr\n"
        f"  GREEN residual (already solved): {residual_green_2040:.1f} Mt/yr\n"
        f"  Whyalla synthetic supply:       {synth_mt_2040:.1f} Mt/yr"
    )
    ax_bot.text(
        0.985, 0.96, callout,
        transform=ax_bot.transAxes, fontsize=8.0,
        fontfamily="monospace", color="#1a3540",
        va="top", ha="right",
        bbox=dict(facecolor="white", edgecolor="#1a3540",
                  alpha=0.92, pad=5, boxstyle="round,pad=0.5"),
    )

    # ── Caption ─────────────────────────────────────────────────────────
    fig.text(
        0.5, 0.018,
        "Demand projections: extrapolated from BITRE Yearbook 2024-25, "
        "ABARES Energy Update, AU MMA Battery-Electric Trucks Roadmap 2024, "
        "BHP Operational Decarbonisation Plan 2023, IATA Net Zero by 2050.   "
        "Synthetic supply trajectory from trajectory.csv "
        f"{scenario} scenario.",
        ha="center", fontsize=8, color="dimgrey", style="italic",
    )

    plt.savefig(outpath, dpi=160, bbox_inches="tight")
    print(f"Saved {outpath}")


# ─── Entrypoint ────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="trajectory.csv")
    ap.add_argument("--out", default="chart_electrification_split.png")
    ap.add_argument("--scenario", default="policy_stated")
    args = ap.parse_args()

    csv = Path(args.csv)
    if not csv.exists():
        print(f"ERROR: {csv} not found — run generate_trajectory.py first")
        raise SystemExit(1)

    synth_mt_2040 = load_synthetic_supply(csv, args.scenario, year=2040)
    plot(synth_mt_2040, Path(args.out), args.scenario)


if __name__ == "__main__":
    main()
