"""Trajectory visualisation: H2 fraction over time across scenarios."""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
HERE = Path(__file__).parent

df = pd.read_csv(HERE / "trajectory.csv")

# Drop the duplicate "no furnace limit" scenario (identical to CBAM-binding in result)
df = df[~df.scenario.str.contains("no furnace limit")]

fig, axes = plt.subplots(2, 3, figsize=(20, 10))

# Filter to policy scenario rows (step_change ISP fleet) for the 3 scenario-loop panels
policy_df = df[df.isp_scenario == "step_change"]

colors = {
    "Policy-stated + gas flat": "#3d85c6",
    "CBAM-binding + gas rising": "#cc4125",
    "Delayed action + gas flat": "#888888",
}

isp_colors = {
    "slower_growth": "#888888",
    "step_change": "#3d85c6",
    "accelerated_transition": "#cc4125",
}
isp_labels = {
    "slower_growth": "ISP: Slower growth (no NTx North)",
    "step_change": "ISP: Step change (NTx North 2031)",
    "accelerated_transition": "ISP: Accelerated transition (NTx North 2030)",
}
policy_isp = df[(df.scenario == "Policy-stated + gas flat") & (df.isp_scenario != "synthetic")]

# ── Panel [0,0]: H₂ trajectory ──────────────────────────────────────────────
ax = axes[0, 0]
for scen in policy_df.scenario.unique():
    sub = policy_df[policy_df.scenario == scen].sort_values("year")
    ax.plot(sub.year, sub.h2_fraction * 100, "o-", color=colors[scen],
            linewidth=2, markersize=5, label=scen)
ax.axhline(30, color="black", linestyle=":", alpha=0.4,
           label="30% — shaft furnace upgrade threshold")
ax.axhline(100, color="black", linestyle="--", alpha=0.2, linewidth=1)
ax.set_ylabel("H₂ share of DRI reductant (%)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Optimal H₂ blend trajectory\n(myopic year-by-year, ISP Step Change fleet)", fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)
ax.set_ylim(0, 105)

# ── Panel [0,1]: Cumulative electrolyser buildout ────────────────────────────
ax = axes[0, 1]
for scen in policy_df.scenario.unique():
    sub = policy_df[policy_df.scenario == scen].sort_values("year")
    ax.plot(sub.year, sub.electrolyser_mw, "o-", color=colors[scen],
            linewidth=2, markersize=5, label=scen)
ax.set_ylabel("Installed electrolyser capacity (MW)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Cumulative electrolyser capacity\n(monotonically increasing — locked-in prior investment)", fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)
ax.set_ylim(bottom=0)

# ── Panel [0,2]: ISP sensitivity — electrolyser buildout ─────────────────────
ax = axes[0, 2]
for isp in ["slower_growth", "step_change", "accelerated_transition"]:
    sub = policy_isp[policy_isp.isp_scenario == isp].sort_values("year")
    if len(sub) == 0:
        continue
    ax.plot(sub.year, sub.electrolyser_mw, "o-",
            color=isp_colors[isp], linewidth=2, markersize=5, label=isp_labels[isp])
ax.set_ylabel("Installed electrolyser capacity (MW)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Policy-stated base case: ISP fleet sensitivity — electrolyser sizing\n(lower renewable CF → larger electrolyser to compensate)", fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)
ax.set_ylim(bottom=0)

# ── Panel [1,0]: Annual CO₂ abatement ───────────────────────────────────────
ax = axes[1, 0]
for scen in policy_df.scenario.unique():
    sub = policy_df[policy_df.scenario == scen].sort_values("year")
    ax.plot(sub.year, sub.emissions_saved_tCO2 / 1000, "o-", color=colors[scen],
            linewidth=2, markersize=5, label=scen)
ax.axhline(1050, color="black", linestyle="--", alpha=0.3, linewidth=1,
           label="1,050 kt/yr — full decarbonisation")
ax.set_ylabel("Annual CO₂ abated (kt/yr)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Emissions abatement vs pure gas-DRI\n(max 1,050 kt CO₂/yr if fully decarbonised)", fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)
ax.set_ylim(bottom=0)

# ── Panel [1,1]: ISP scenario H₂ fraction comparison under CBAM ─────────────
ax = axes[1, 1]
for isp in ["slower_growth", "step_change", "accelerated_transition"]:
    sub = policy_isp[policy_isp.isp_scenario == isp].sort_values("year")
    if len(sub) == 0:
        continue
    ax.plot(sub.year, sub.h2_fraction * 100, "o-",
            color=isp_colors[isp], linewidth=2, markersize=5, label=isp_labels[isp])
ax.axhline(30, color="black", linestyle=":", alpha=0.4,
           label="30% — shaft furnace upgrade threshold")
ax.axhline(100, color="black", linestyle="--", alpha=0.2, linewidth=1)
ax.set_ylabel("H₂ share (%)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Policy-stated base case: ISP fleet sensitivity — H₂ share\n(slower renewable build slows H₂ uptake, not ceiling)", fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)
ax.set_ylim(0, 105)

# ── Panel [1,2]: CAPEX decline + carbon price (step_change only) ─────────────
ax = axes[1, 2]
sub = df[(df.scenario == "Policy-stated + gas flat") &
         (df.isp_scenario == "step_change")].sort_values("year")
ax2 = ax.twinx()
l1 = ax.plot(sub.year, sub.capex_per_kw, "o-", color="#e69138",
             linewidth=2, markersize=5, label="Electrolyser CAPEX ($/kW)")
ax.set_ylabel("Electrolyser CAPEX ($/kW)", color="#e69138", fontsize=11)
ax.tick_params(axis="y", labelcolor="#e69138")

l2 = ax2.plot(sub.year, sub.carbon_price, "s-", color="#674ea7",
              linewidth=2, markersize=5, label="Carbon price ($/t CO₂)")
ax2.set_ylabel("Carbon price ($/t CO₂)", color="#674ea7", fontsize=11)
ax2.tick_params(axis="y", labelcolor="#674ea7")

# Shade where H₂ investment actually happens
investment_years = sub[sub.electrolyser_mw > 10].year
if len(investment_years) > 0:
    ax.axvspan(investment_years.min(), 2040, alpha=0.15, color="green",
               label="H₂ investment era")

ax.set_xlabel("Year")
ax.set_title("Policy-stated base case: input trajectories\n(green = electrolyser investment era, ISP Step Change)", fontsize=11)
lns = l1 + l2
ax.legend(lns, [l.get_label() for l in lns], fontsize=9, loc="center right")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)

plt.tight_layout()
plt.savefig(HERE / "chart4_trajectory.png", dpi=140, bbox_inches="tight")
plt.close()
print(f"Saved chart4_trajectory.png to {HERE}")

# Summary table
print("\nScenario summary: H2 share and electrolyser buildout by milestone year")
print("=" * 80)
for scen in policy_df.scenario.unique():
    sub = policy_df[policy_df.scenario == scen].drop_duplicates(subset=["year"]).set_index("year")
    print(f"\n{scen}:")
    for yr in [2028, 2030, 2035, 2040]:
        if yr in sub.index:
            r = sub.loc[yr]
            print(f"  {yr}: H2={r.h2_fraction:.1%}  electrolyser={r.electrolyser_mw:.0f} MW  "
                  f"storage={r.h2_storage_mwh:.0f} MWh  CO2 abated={r.emissions_saved_tCO2/1000:.0f} kt/yr")

# When does first meaningful H₂ investment happen?
print("\nFirst year H₂ fraction exceeds 5%:")
for scen in policy_df.scenario.unique():
    sub = policy_df[policy_df.scenario == scen].sort_values("year")
    first = sub[sub.h2_fraction > 0.05]
    if len(first) > 0:
        print(f"  {scen}: {first.iloc[0].year:.0f} (at CAPEX=${first.iloc[0].capex_per_kw:.0f}/kW, carbon=${first.iloc[0].carbon_price:.0f}/t)")
    else:
        print(f"  {scen}: never in trajectory")

# ISP sensitivity summary
print("\nISP sensitivity (Policy-stated + gas flat) — H₂ share 2035 and 2040:")
for isp in ["slower_growth", "step_change", "accelerated_transition"]:
    sub = policy_isp[policy_isp.isp_scenario == isp].drop_duplicates(subset=["year"]).set_index("year")
    for yr in [2035, 2040]:
        if yr in sub.index:
            r = sub.loc[yr]
            print(f"  {isp_labels[isp]}: {yr} H2={r.h2_fraction:.1%}  electrolyser={r.electrolyser_mw:.0f} MW")
