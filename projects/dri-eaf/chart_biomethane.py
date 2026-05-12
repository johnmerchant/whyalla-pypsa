"""Biomethane uptake by scenario — what does the SA biomethane pool actually
displace once H2 is doing the heavy lifting?

Three panels:
  [0]  PJ/yr available vs. PJ/yr taken up by the LP, per policy (step_change ISP)
  [1]  Stacked feedstock split (fossil NG / biomethane / H2) by year, central case
  [2]  Scope-1 emissions saved by biomethane (kt CO2/yr), by policy

Source data: trajectory.csv columns
  - biomethane_pj_available, total_biomethane_mwh, total_fossil_ng_mwh, total_h2_mwh
  - emissions_scope1_tCO2 (already excludes biomethane combustion)

Output: chart_biomethane.png
"""
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

HERE = Path(__file__).parent

df = pd.read_csv(HERE / "trajectory.csv")
df = df[df.isp_scenario == "step_change"]

POLICY_ORDER = [
    "Policy-stated + gas flat",
    "CBAM-binding + gas rising",
    "Delayed action + gas flat",
]
COLORS = {
    "Policy-stated + gas flat":  "#3d85c6",
    "CBAM-binding + gas rising": "#cc4125",
    "Delayed action + gas flat": "#888888",
}

PJ_PER_MWH = 3.6 / 1e6  # multiply MWh × this to get PJ
CO2_KG_PER_MWH_NG = 560.0 / 3.0 / 1000.0  # tCO2/MWh_NG (matches process_chain)

fig, axes = plt.subplots(1, 3, figsize=(20, 5.5))

# ── Panel 0: biomethane available vs taken-up, per policy ────────────────────
ax = axes[0]
for scen in POLICY_ORDER:
    sub = df[df.scenario == scen].sort_values("year")
    if sub.empty:
        continue
    avail_pj = sub.biomethane_pj_available
    used_pj = sub.total_biomethane_mwh * PJ_PER_MWH
    ax.plot(sub.year, avail_pj, ":", color=COLORS[scen], linewidth=1.4,
            alpha=0.65, label=f"{scen}  (available)")
    ax.plot(sub.year, used_pj, "o-", color=COLORS[scen], linewidth=2.0,
            markersize=5, label=f"{scen}  (taken up)")
ax.set_ylabel("Biomethane (PJ/yr)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Biomethane: SA-network availability vs Whyalla LP uptake\n"
             "(dotted = supply ceiling; solid = LP dispatch)", fontsize=11)
ax.legend(fontsize=8, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2028, 2042)
ax.set_ylim(bottom=0)

# ── Panel 1: stacked DRI feedstock split, central case (Policy-stated) ───────
ax = axes[1]
central = df[df.scenario == "Policy-stated + gas flat"].sort_values("year")
years = central.year.values
fossil_pj = central.total_fossil_ng_mwh.values * PJ_PER_MWH
bm_pj = central.total_biomethane_mwh.values * PJ_PER_MWH
h2_pj = central.total_h2_mwh.values * PJ_PER_MWH

ax.fill_between(years, 0, fossil_pj, color="#b15928", alpha=0.85,
                label="Fossil NG", linewidth=0)
ax.fill_between(years, fossil_pj, fossil_pj + bm_pj, color="#27ae60",
                alpha=0.85, label="Biomethane (RGGO)", linewidth=0)
ax.fill_between(years, fossil_pj + bm_pj, fossil_pj + bm_pj + h2_pj,
                color="#2c7fb8", alpha=0.85, label="Hydrogen", linewidth=0)
ax.set_ylabel("DRI reductant feed (PJ/yr)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Whyalla DRI reductant — fossil / biomethane / H2 split\n"
             "(Policy-stated + gas flat, ISP Step Change)", fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2028, 2042)
ax.set_ylim(bottom=0)

# ── Panel 2: Scope-1 saved by biomethane (kt CO2/yr) ─────────────────────────
ax = axes[2]
for scen in POLICY_ORDER:
    sub = df[df.scenario == scen].sort_values("year")
    if sub.empty:
        continue
    bm_mwh = sub.total_biomethane_mwh.values
    saved_kt = bm_mwh * CO2_KG_PER_MWH_NG / 1000.0
    ax.plot(sub.year, saved_kt, "o-", color=COLORS[scen], linewidth=2.0,
            markersize=5, label=scen)
ax.set_ylabel("Scope-1 abated by biomethane (kt CO₂/yr)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Scope-1 abatement contribution from biomethane\n"
             "(displaces fossil NG molecule-for-molecule on the ng bus)", fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2028, 2042)
ax.set_ylim(bottom=0)

plt.tight_layout()
plt.savefig(HERE / "chart_biomethane.png", dpi=140, bbox_inches="tight")
plt.close()
print("Saved chart_biomethane.png")

# ── Console summary ──────────────────────────────────────────────────────────
print("\nBiomethane uptake summary (step_change ISP):")
for scen in POLICY_ORDER:
    sub = df[df.scenario == scen].sort_values("year")
    if sub.empty:
        continue
    print(f"\n  {scen}:")
    print(f"    {'year':>4}  {'avail':>6}  {'used':>6}  {'used%':>6}  "
          f"{'fossil':>7}  {'H2 share':>8}  {'Scope1':>7}")
    for _, r in sub.iterrows():
        used_pj = r.total_biomethane_mwh * PJ_PER_MWH
        used_pct = (used_pj / r.biomethane_pj_available * 100
                    if r.biomethane_pj_available > 0 else 0.0)
        fossil_pj = r.total_fossil_ng_mwh * PJ_PER_MWH
        scope1_kt = r.emissions_scope1_tCO2 / 1000.0
        print(f"    {int(r.year):>4}  {r.biomethane_pj_available:>5.2f}  "
              f"{used_pj:>5.2f}  {used_pct:>5.0f}%  {fossil_pj:>6.2f}  "
              f"{r.h2_fraction*100:>7.1f}%  {scope1_kt:>6.0f}")
