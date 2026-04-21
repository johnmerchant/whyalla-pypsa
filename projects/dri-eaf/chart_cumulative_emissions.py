"""Chart 6: Cumulative CO₂ abatement across scenarios, with carbon cost savings."""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
HERE = Path(__file__).parent

df = pd.read_csv(HERE / "trajectory.csv")
df = df[~df.scenario.str.contains("no furnace limit")]

policy_df = df[df.isp_scenario == "step_change"]

colors = {
    "Policy-stated + gas flat": "#3d85c6",
    "CBAM-binding + gas rising": "#cc4125",
    "Delayed action + gas flat": "#888888",
}

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

# Left: Cumulative CO₂ abated
for scen in policy_df.scenario.unique():
    sub = policy_df[policy_df.scenario == scen].sort_values("year")
    cumulative = sub.emissions_saved_tCO2.cumsum() / 1e6
    ax1.fill_between(sub.year, cumulative, alpha=0.15, color=colors[scen])
    ax1.plot(sub.year, cumulative, "o-", color=colors[scen], linewidth=2,
             markersize=5, label=scen)

ax1.set_xlabel("Year", fontsize=11)
ax1.set_ylabel("Cumulative CO₂ avoided (Mt)", fontsize=11)
ax1.set_title("Cumulative emissions abatement vs pure gas-DRI\n"
              "(earlier action = steeper ramp, more cumulative benefit)", fontsize=11)
ax1.legend(fontsize=9, loc="upper left")
ax1.grid(alpha=0.3)
ax1.set_xlim(2026, 2040)
ax1.set_ylim(bottom=0)

# Right: Implied carbon cost savings per scenario
for scen in policy_df.scenario.unique():
    sub = policy_df[policy_df.scenario == scen].sort_values("year")
    savings = sub.emissions_saved_tCO2 * sub.carbon_price / 1e6
    cumulative_savings = savings.cumsum()
    ax2.plot(sub.year.values, cumulative_savings.values, "o-", color=colors[scen],
             linewidth=2, markersize=5, label=scen)

ax2.set_xlabel("Year", fontsize=11)
ax2.set_ylabel("Cumulative carbon cost avoided ($M)", fontsize=11)
ax2.set_title("Carbon liability avoided by switching to H₂-DRI\n"
              "(emissions avoided × carbon price in each year)", fontsize=11)
ax2.legend(fontsize=9, loc="upper left")
ax2.grid(alpha=0.3)
ax2.set_xlim(2026, 2040)
ax2.set_ylim(bottom=0)

plt.tight_layout()
plt.savefig(HERE / "chart_cumulative_emissions.png", dpi=140, bbox_inches="tight")
plt.close()
print("Saved chart_cumulative_emissions.png")
