"""Chart 9: EAF + electrolyser co-dispatch. Two flexible loads sharing SA's cheap hours.

The EAF is always present at Whyalla (it is the steelmaking route). This chart
shows how its 111 MW average / 975 GWh-per-year demand is co-optimised with the
electrolyser: both loads avoid peak-hours, both pay well below the SA_N wholesale
average, but they land in different parts of the merit-order.
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

HERE = Path(__file__).parent

df = pd.read_csv(HERE / "trajectory.csv")
df = df[~df.scenario.str.contains("no furnace limit")]
df = df.drop_duplicates(subset=["scenario", "isp_scenario", "year"])

focus = df[(df.scenario == "Policy-stated + gas flat") &
           (df.isp_scenario == "step_change")].sort_values("year").set_index("year")
years = focus.index.tolist()

fig, axes = plt.subplots(2, 2, figsize=(14, 10))

# ── Panel [0,0]: Realised vs wholesale price ────────────────────────────────
ax = axes[0, 0]
ax.plot(years, focus.avg_wholesale_price_sa_n, ":", color="#444", linewidth=1.8,
        label="SA_N average wholesale")
ax.plot(years, focus.electrolyser_realised_price, "o-", color="#2c7fb8",
        linewidth=2.3, markersize=6, label="Electrolyser realised price")
ax.plot(years, focus.eaf_realised_price, "s-", color="#6a51a3",
        linewidth=2.3, markersize=6, label="EAF realised price")
ax.fill_between(years, focus.electrolyser_realised_price,
                focus.avg_wholesale_price_sa_n, alpha=0.12, color="#2c7fb8")
ax.set_ylabel("Realised electricity price ($/MWh)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Both loads pay well below wholesale\n"
             "(electrolyser gets the cheapest hours, EAF the next-cheapest)",
             fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)

# ── Panel [0,1]: Flexibility premium ($/MWh) ────────────────────────────────
ax = axes[0, 1]
ax.plot(years, focus.flexibility_premium, "o-", color="#2c7fb8",
        linewidth=2.3, markersize=6, label="Electrolyser premium")
ax.plot(years, focus.eaf_flexibility_premium, "s-", color="#6a51a3",
        linewidth=2.3, markersize=6, label="EAF premium")
ax.set_ylabel("Flexibility premium ($/MWh)\n(wholesale – realised)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Both assets capture a flexibility premium\n"
             "(the EAF's share is smaller but still substantial)",
             fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)
ax.set_ylim(bottom=0)

# ── Panel [1,0]: Annual electricity consumption split ───────────────────────
ax = axes[1, 0]
# Electrolyser electricity = H2 produced / 0.7 efficiency
ely_mwh = focus.total_h2_mwh / 0.70
eaf_mwh = focus.eaf_total_mwh
ax.stackplot(years, eaf_mwh / 1000, ely_mwh / 1000,
             labels=["EAF steel load (~975 GWh/yr)",
                     "Electrolyser AC draw"],
             colors=["#6a51a3", "#2c7fb8"], alpha=0.85)
ax.set_ylabel("Annual electricity consumption (GWh/yr)", fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Combined flexible load grows with electrolyser buildout\n"
             "(EAF baseload ~975 GWh/yr + electrolyser ramps to 3500+ GWh/yr)",
             fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3)
ax.set_xlim(2026, 2040)

# ── Panel [1,1]: $/yr flexibility value ─────────────────────────────────────
ax = axes[1, 1]
ely_value = focus.flexibility_premium * ely_mwh / 1e6  # $M/yr
eaf_value = focus.eaf_flexibility_premium * eaf_mwh / 1e6
ax.bar(years, eaf_value, color="#6a51a3", alpha=0.85, label="EAF flex value ($M/yr)")
ax.bar(years, ely_value, bottom=eaf_value, color="#2c7fb8", alpha=0.85,
       label="Electrolyser flex value ($M/yr)")
ax.set_ylabel("Annual flexibility savings ($M/yr)\n(premium × MWh consumed)",
              fontsize=11)
ax.set_xlabel("Year")
ax.set_title("Combined flexibility value — $M/yr below wholesale\n"
             "(EAF adds ~$30–45M/yr on top of electrolyser savings)",
             fontsize=11)
ax.legend(fontsize=9, loc="upper left")
ax.grid(alpha=0.3, axis="y")
ax.set_xlim(2025.4, 2040.6)

plt.suptitle("Two flexible loads, one cheap-hours market — EAF and electrolyser "
             "co-dispatch at Whyalla",
             fontsize=13, y=1.01)
plt.tight_layout()
plt.savefig(HERE / "chart_eaf_cannibalisation.png", dpi=140, bbox_inches="tight")
plt.close()
print("Saved chart_eaf_cannibalisation.png")

# ── Summary table ───────────────────────────────────────────────────────────
print("\nEAF + electrolyser co-dispatch — Policy-stated + gas flat, ISP Step Change:")
print("=" * 95)
hdr = (f"{'Year':<6}{'Ely MW':>8}{'Ely CF':>8}{'Ely real$':>11}"
       f"{'EAF real$':>11}{'Ely prem':>10}{'EAF prem':>10}{'Wholesale':>11}")
print(hdr)
for yr in [2028, 2030, 2032, 2035, 2040]:
    if yr in years:
        r = focus.loc[yr]
        print(f"{yr:<6}{r.electrolyser_mw:>8.0f}{r.electrolyser_cf:>8.2f}"
              f"{r.electrolyser_realised_price:>11.1f}{r.eaf_realised_price:>11.1f}"
              f"{r.flexibility_premium:>10.1f}{r.eaf_flexibility_premium:>10.1f}"
              f"{r.avg_wholesale_price_sa_n:>11.1f}")

print("\nAnnual flexibility value (Policy-stated + gas flat, $M/yr):")
for yr in [2030, 2035, 2040]:
    if yr in years:
        r = focus.loc[yr]
        ely_mwh = r.total_h2_mwh / 0.70
        ely_val = r.flexibility_premium * ely_mwh / 1e6
        eaf_val = r.eaf_flexibility_premium * r.eaf_total_mwh / 1e6
        print(f"  {yr}: electrolyser ${ely_val:.0f}M, EAF ${eaf_val:.0f}M, "
              f"total ${ely_val + eaf_val:.0f}M/yr")
