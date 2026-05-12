"""Programme-timeline Gantt: Whyalla synthetic fuels vs comparable
Australian Federal commitments.

Renders a single horizontal-bar Gantt with one row per programme and
year on the x-axis. Each bar carries:
  - a *spend window* (solid colour) marking when budget commitments
    are/were active;
  - an *operational window* (same colour, lower alpha + hatch) marking
    when the asset/programme delivers value;
  - a right-edge annotation showing cumulative $/taxpayer over the
    2027-2040 modelling horizon (the same window used elsewhere in
    the README).

Bars are colour-graded by per-taxpayer cumulative cost (cool blues
for cheap, hot reds for expensive). The Whyalla proposal row carries
a thick black border so it reads as the subject of the comparison.

Sources (all hardcoded — verify against README "comparable programmes"
table):
  - JobKeeper one-off:                    $7,739   (~$89 B FY20-21)
  - AUKUS 14-yr share of $368 B / 30 yr:  $14,943
  - Diesel Fuel Rebate 14 × $10 B/yr:     $12,174
  - 2024 Coalition nuclear policy:        $10,087  (~$116 B, 7 reactors)
  - Whyalla synthetic fuels (policy_stated): $8,267 (175 kbpd by 2040)

Usage:
    uv run python chart_programme_timeline.py \\
        --out chart_programme_timeline.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.patches import FancyArrowPatch

HERE = Path(__file__).parent


# ── Programmes (top-down order on the chart) ─────────────────────────
# Each entry: label, spend window, operational window, perpetual flag,
#             $/taxpayer (2027-2040 cumulative), description, highlight.
PROGRAMMES = [
    {
        "label": "AUKUS",
        "spend": (2024, 2055),
        "operational": (2032, 2055),
        "perpetual": False,
        "per_taxpayer": 14_943,
        "description": "Up to 8 nuclear submarines, ~$368 B, deliveries from early 2030s",
        "highlight": False,
    },
    {
        "label": "Diesel Fuel Rebate",
        "spend": (2020, 2055),
        "operational": (2020, 2055),
        "perpetual": True,
        "per_taxpayer": 12_174,
        "description": "Excise rebate to mining, ag, fisheries, transport — ~$10 B/yr, no asset created",
        "highlight": False,
    },
    {
        "label": "2024 Coalition nuclear policy",
        "spend": (2024, 2038),
        "operational": (2037, 2055),
        "perpetual": False,
        "per_taxpayer": 10_087,
        "description": "7 reactors, ~$116 B, first power 2037",
        "highlight": False,
    },
    {
        "label": "Whyalla synthetic fuels (this proposal)",
        "spend": (2027, 2040),
        "operational": (2029, 2055),
        "perpetual": False,
        "per_taxpayer": 8_267,
        "description": "175 kbpd domestic synthetic-fuel capacity by 2040, 25-30 yr operating life",
        "highlight": True,
    },
    {
        "label": "JobKeeper",
        "spend": (2020, 2021),
        "operational": (2020, 2021),
        "perpetual": False,
        "per_taxpayer": 7_739,
        "description": "Wage subsidy — $89 B, no asset created",
        "highlight": False,
    },
]


# Cool-to-hot colour ramp used to grade bars by per-taxpayer cost.
_COST_CMAP = LinearSegmentedColormap.from_list(
    "cost_ramp",
    ["#2c7fb8", "#7fcdbb", "#fed976", "#fd8d3c", "#bd0026"],
)


def _fmt_dollars(x: float) -> str:
    return f"${x:,.0f}"


def _bar_color(per_taxpayer: float, vmin: float, vmax: float) -> tuple:
    norm = Normalize(vmin=vmin, vmax=vmax)
    return _COST_CMAP(norm(per_taxpayer))


def plot(out: Path) -> None:
    x_min, x_max = 2020, 2055
    n = len(PROGRAMMES)

    costs = [p["per_taxpayer"] for p in PROGRAMMES]
    vmin, vmax = min(costs), max(costs)

    fig, ax = plt.subplots(figsize=(16, 6), dpi=160)

    # Reserve a band on the right for the per-taxpayer annotations.
    annot_x = x_max + 1.2
    right_edge = x_max + 11.0

    bar_height = 0.55

    for i, p in enumerate(PROGRAMMES):
        y = n - 1 - i
        color = _bar_color(p["per_taxpayer"], vmin, vmax)
        edge_lw = 2.4 if p["highlight"] else 0.8
        edge_color = "black" if p["highlight"] else "#333333"

        spend_start, spend_end = p["spend"]
        op_start, op_end = p["operational"]

        # Operational window (drawn first, behind spend window where they overlap).
        if op_end > op_start:
            ax.barh(
                y,
                width=op_end - op_start,
                left=op_start,
                height=bar_height,
                color=color,
                alpha=0.32,
                hatch="//",
                edgecolor=edge_color,
                linewidth=edge_lw * 0.7,
                zorder=2,
            )

        # Spend window — solid colour on top.
        if spend_end > spend_start:
            ax.barh(
                y,
                width=spend_end - spend_start,
                left=spend_start,
                height=bar_height,
                color=color,
                alpha=0.95,
                edgecolor=edge_color,
                linewidth=edge_lw,
                zorder=3,
            )
        elif spend_end == spend_start:
            # One-shot one-year programme — render a thin vertical band.
            ax.barh(
                y,
                width=0.6,
                left=spend_start - 0.3,
                height=bar_height,
                color=color,
                alpha=0.95,
                edgecolor=edge_color,
                linewidth=edge_lw,
                zorder=3,
            )

        # Perpetual programme — arrow extending past the right edge of
        # the time axis to convey "no end date".
        if p["perpetual"]:
            arrow = FancyArrowPatch(
                (x_max - 0.5, y),
                (x_max + 0.9, y),
                arrowstyle="-|>",
                mutation_scale=18,
                color=color,
                linewidth=2.5,
                zorder=4,
            )
            ax.add_patch(arrow)

        # Description label inside (or just above) the bar.
        desc_x = max(spend_start, x_min) + 0.3
        ax.text(
            desc_x,
            y + bar_height / 2 + 0.08,
            p["description"],
            fontsize=8.2,
            ha="left",
            va="bottom",
            color="#222222",
            zorder=5,
        )

        # Right-edge per-taxpayer annotation.
        is_top = p["highlight"]
        ax.text(
            annot_x,
            y,
            _fmt_dollars(p["per_taxpayer"]),
            fontsize=11,
            ha="left",
            va="center",
            family="monospace",
            fontweight="bold",
            color="black",
            bbox=dict(
                boxstyle="round,pad=0.35",
                facecolor=color,
                edgecolor="black" if is_top else "#444444",
                linewidth=2.0 if is_top else 0.8,
                alpha=0.85,
            ),
            zorder=6,
        )

    # Y axis: programme labels.
    labels = [p["label"] for p in PROGRAMMES]
    ax.set_yticks(range(n))
    ax.set_yticklabels(list(reversed(labels)), fontsize=10)

    # Bold the highlighted row's tick label.
    for tick, p in zip(reversed(ax.get_yticklabels()), PROGRAMMES):
        if p["highlight"]:
            tick.set_fontweight("bold")

    # X axis configuration.
    ax.set_xlim(x_min - 0.5, right_edge)
    ax.set_ylim(-0.7, n - 0.3)
    ax.set_xticks(range(x_min, x_max + 1, 5))
    ax.tick_params(axis="x", labelsize=10)
    ax.set_xlabel("Year")
    ax.grid(axis="x", linestyle=":", color="gray", alpha=0.5)
    ax.set_axisbelow(True)

    # Hide the right-margin region from the spine so annotations
    # visually sit "outside" the timeline.
    ax.axvline(x_max + 0.4, color="#bbbbbb", linewidth=0.8, linestyle="--", zorder=1)

    # Header: column-style annotation for the per-taxpayer band.
    ax.text(
        annot_x,
        n - 0.4,
        "$ / taxpayer\n(2027-2040)",
        fontsize=9.5,
        ha="left",
        va="bottom",
        fontweight="bold",
        color="#222222",
    )

    # Title + subtitle.
    fig.suptitle(
        "Australian Federal commitments — comparable scale and duration",
        fontsize=14,
        fontweight="bold",
        x=0.5,
        y=0.98,
    )
    ax.set_title(
        "Per-taxpayer figures are cumulative over 2027-2040 (the modelling horizon for the "
        "Whyalla proposal). Hatched portion = operational window after spending ends.",
        fontsize=9.5,
        color="#333333",
        loc="left",
        pad=10,
    )

    # Legend — solid vs hatched.
    legend_handles = [
        mpatches.Patch(facecolor="#888888", edgecolor="black",
                       label="Spend window (budget commitments active)"),
        mpatches.Patch(facecolor="#888888", edgecolor="black", alpha=0.32,
                       hatch="//", label="Operational window (asset delivers value)"),
        mpatches.Patch(facecolor="white", edgecolor="black", linewidth=2.4,
                       label="This proposal (highlighted)"),
    ]
    ax.legend(
        handles=legend_handles,
        loc="lower right",
        bbox_to_anchor=(1.0, -0.22),
        ncol=3,
        fontsize=9,
        frameon=False,
    )

    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="chart_programme_timeline.png")
    args = ap.parse_args()

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = HERE / out_path
    plot(out_path)


if __name__ == "__main__":
    main()
