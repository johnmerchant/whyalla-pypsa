"""Chart 8: WACC sensitivity — how cost of capital shifts the transition timeline.

The FOAK→NOAK scenario (13% for first tranche, 9% once >100 MW proven) is the
central case, representing realistic project finance for new technology.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
HERE = Path(__file__).parent

df = pd.read_csv(HERE / "wacc_sweep.csv")

wacc_order = [
    "FOAK→NOAK (13%→9%)",
    "Corporate balance sheet (6%)",
    "Utility/regulated (7%)",
    "Project finance NOAK (9%)",
    "FOAK risk-adjusted (13%)",
]

colors = {
    "FOAK→NOAK (13%→9%)":          "#1a1a1a",
    "Corporate balance sheet (6%)": "#2ecc71",
    "Utility/regulated (7%)":       "#3498db",
    "Project finance NOAK (9%)":    "#e67e22",
    "FOAK risk-adjusted (13%)":     "#c0392b",
}
linestyles = {
    "FOAK→NOAK (13%→9%)":          "-",
    "Corporate balance sheet (6%)": "--",
    "Utility/regulated (7%)":       "--",
    "Project finance NOAK (9%)":    "--",
    "FOAK risk-adjusted (13%)":     "--",
}
linewidths = {
    "FOAK→NOAK (13%→9%)":          3.5,
    "Corporate balance sheet (6%)": 1.8,
    "Utility/regulated (7%)":       1.8,
    "Project finance NOAK (9%)":    1.8,
    "FOAK risk-adjusted (13%)":     1.8,
}
markers = {
    "FOAK→NOAK (13%→9%)":          "D",
    "Corporate balance sheet (6%)": "o",
    "Utility/regulated (7%)":       "o",
    "Project finance NOAK (9%)":    "o",
    "FOAK risk-adjusted (13%)":     "o",
}
short_labels = {
    "FOAK→NOAK (13%→9%)":          "13%→9% FOAK→NOAK (central)",
    "Corporate balance sheet (6%)": "6% corporate",
    "Utility/regulated (7%)":       "7% utility",
    "Project finance NOAK (9%)":    "9% NOAK PF",
    "FOAK risk-adjusted (13%)":     "13% FOAK",
}

fig, axes = plt.subplots(1, 3, figsize=(20, 6))

# Panel 1: H₂ share trajectory
ax = axes[0]
for wl in wacc_order:
    sub = df[df.wacc_label == wl].sort_values("year")
    if len(sub) == 0:
        continue
    ax.plot(sub.year, sub.h2_fraction * 100, linestyle=linestyles[wl],
            color=colors[wl], linewidth=linewidths[wl], markersize=5,
            marker=markers[wl], label=short_labels[wl])
ax.axhline(30, color="black", linestyle=":", alpha=0.4, linewidth=1)
ax.annotate("30% shaft furnace cap", xy=(2026.5, 32), fontsize=8, alpha=0.5)
ax.set_ylabel("H₂ share of DRI reductant (%)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("H₂ transition timing across WACC scenarios\n(CBAM-binding carbon, ISP Step Change)", fontsize=11)
ax.legend(fontsize=8, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)
ax.set_ylim(0, 105)

# Panel 2: Electrolyser buildout
ax = axes[1]
for wl in wacc_order:
    sub = df[df.wacc_label == wl].sort_values("year")
    if len(sub) == 0:
        continue
    ax.plot(sub.year, sub.electrolyser_mw, linestyle=linestyles[wl],
            color=colors[wl], linewidth=linewidths[wl], markersize=5,
            marker=markers[wl], label=short_labels[wl])
ax.set_ylabel("Installed electrolyser capacity (MW)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Capital deployment across financing regimes\n(locked-in capacity, monotonically increasing)", fontsize=11)
ax.legend(fontsize=8, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)
ax.set_ylim(bottom=0)

# Panel 3: Summary bar chart — H₂ share at milestones
ax = axes[2]
milestones = [2030, 2035, 2040]
bar_order = wacc_order
x = np.arange(len(milestones))
width = 0.15
for i, wl in enumerate(bar_order):
    sub = df[df.wacc_label == wl].sort_values("year")
    if len(sub) == 0:
        continue
    sub_idx = sub.set_index("year")
    vals = [sub_idx.loc[yr, "h2_fraction"] * 100 for yr in milestones]
    bars = ax.bar(x + (i - 2) * width, vals, width, color=colors[wl],
                  label=short_labels[wl], edgecolor="white", linewidth=0.5,
                  alpha=1.0 if "FOAK→NOAK" in wl else 0.7)
    for bar, v in zip(bars, vals):
        if v > 5:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                    f"{v:.0f}%", ha="center", va="bottom", fontsize=7)

ax.set_xticks(x)
ax.set_xticklabels(milestones, fontsize=11)
ax.set_xlabel("Milestone year", fontsize=11)
ax.set_ylabel("H₂ share (%)", fontsize=11)
ax.set_title("WACC effect on milestone H₂ share\n(FOAK→NOAK central case in bold)", fontsize=11)
ax.legend(fontsize=8, loc="upper left")
ax.grid(alpha=0.3, axis="y")
ax.set_ylim(0, 115)

plt.tight_layout()
plt.savefig(HERE / "chart_wacc_sensitivity.png", dpi=140, bbox_inches="tight")
plt.close()
print("Saved chart_wacc_sensitivity.png")

# Print summary
print("\nWACC sensitivity summary:")
for wl in wacc_order:
    sub = df[df.wacc_label == wl].sort_values("year")
    if len(sub) == 0:
        continue
    first_5 = sub[sub.h2_fraction > 0.05]
    first = first_5.iloc[0].year if len(first_5) > 0 else None
    r30 = sub[sub.year == 2030].iloc[0]
    r35 = sub[sub.year == 2035].iloc[0]
    r40 = sub[sub.year == 2040].iloc[0]
    print(f"  {wl}: first H₂>5% = {first:.0f}  "
          f"2030={r30.h2_fraction:.0%}  2035={r35.h2_fraction:.0%}  2040={r40.h2_fraction:.0%}  "
          f"ely2040={r40.electrolyser_mw:.0f}MW")
