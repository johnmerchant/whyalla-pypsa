"""Chart 5: Santos gas deal timeline — gas price, H₂ fraction, and contract periods."""
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
HERE = Path(__file__).parent

df = pd.read_csv(HERE / "trajectory.csv")
df = df[~df.scenario.str.contains("no furnace limit")]

sub = df[(df.scenario == "CBAM-binding + gas rising") &
         (df.isp_scenario == "step_change")].sort_values("year")

fig, ax1 = plt.subplots(figsize=(12, 5.5))

ax1.axvspan(2027.5, 2029.5, alpha=0.10, color="#95a5a6",
            label="Pre-DRI (BF-BOS, no NG demand)")
ax1.axvspan(2029.5, 2040.5, alpha=0.15, color="#2ecc71",
            label="Santos foundation contract (20 PJ/yr @ $12/GJ)")
ax1.axvspan(2040.5, 2042.5, alpha=0.15, color="#e74c3c",
            label="Spot LNG netback (~$22/GJ)")

ax1.plot(sub.year, sub.gas_price, "D-", color="#c0392b", linewidth=2.5,
         markersize=7, label="Gas price ($/GJ)", zorder=5)
ax1.set_ylabel("Gas price ($/GJ)", fontsize=12, color="#c0392b")
ax1.tick_params(axis="y", labelcolor="#c0392b")
ax1.set_ylim(0, 26)

ax2 = ax1.twinx()
ax2.fill_between(sub.year, sub.h2_fraction * 100, alpha=0.25, color="#3498db")
ax2.plot(sub.year, sub.h2_fraction * 100, "o-", color="#2c3e50", linewidth=2.5,
         markersize=7, label="H₂ share (%)", zorder=5)
ax2.set_ylabel("H₂ share of DRI reductant (%)", fontsize=12, color="#2c3e50")
ax2.tick_params(axis="y", labelcolor="#2c3e50")
ax2.set_ylim(0, 105)

ax1.axvline(2030, color="black", linestyle=":", alpha=0.5, linewidth=1.5)
ax1.annotate("Santos first gas\n1 March 2030", xy=(2030, 23), fontsize=9,
             ha="center", style="italic", color="#555")

ax1.axvline(2040.5, color="black", linestyle=":", alpha=0.5, linewidth=1.5)
ax1.annotate("Foundation contract ends\n→ spot LNG netback", xy=(2040.5, 23),
             fontsize=9, ha="center", style="italic", color="#555")

ax1.set_xlabel("Year", fontsize=12)
ax1.set_title("Santos gas deal shapes the transition timeline\n"
              "(CBAM-binding scenario, ISP Step Change)", fontsize=13)
ax1.set_xlim(2027.5, 2042.5)
ax1.set_xticks(range(2028, 2043))
ax1.tick_params(axis="x", rotation=45)
ax1.grid(alpha=0.2)

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="center left", fontsize=9,
           framealpha=0.95)

plt.tight_layout()
plt.savefig(HERE / "chart_santos_gas.png", dpi=140, bbox_inches="tight")
plt.close()
print("Saved chart_santos_gas.png")
