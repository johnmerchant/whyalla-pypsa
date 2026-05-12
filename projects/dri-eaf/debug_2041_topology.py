"""Topology + supply-demand check at the offending snapshot.

Hypothesis: acce_trans/2041 has higher SA load but the same interconnect
capacity as step_change/2041. On worst-case snapshots, the SA buses can't
reach the slack buses through the limited interconnectors → presolve detects
the loose-load constraint trivially.

We:
  1. Print the link topology (bus0/bus1/p_nom) so we can see how each SA bus
     connects to the slack.
  2. For each snapshot, compute SA-region demand vs. (local VRE p_max_pu *
     p_nom) + (sum of interconnector p_nom). Find the snapshot with the
     biggest deficit and report it.
"""
from __future__ import annotations

import pickle

import numpy as np
import pandas as pd

from debug_2041_infeasible import STATE_PICKLE, build_2041_network_with_overrides


def _load_state():
    with STATE_PICKLE.open("rb") as f:
        return pickle.load(f)


def topology(n, label):
    print(f"\n=== {label}: link topology ===")
    cols = ["bus0", "bus1", "p_nom", "p_min_pu", "p_max_pu", "efficiency"]
    df = n.links[cols].copy()
    print(df.to_string())
    print(f"\n=== {label}: bus list ===")
    print(n.buses[["carrier"]].to_string())


def supply_demand_balance(n, label):
    """For each electricity bus per snapshot: VRE supply potential vs. load."""
    snapshots = n.snapshots
    pmp = n.generators_t.p_max_pu
    p_set = n.loads_t.p_set

    # Map each generator → bus
    gen_bus = n.generators["bus"]
    # For generators that have a p_max_pu time series, supply potential =
    # p_nom * p_max_pu(t). For static (NSW_slack/VIC_slack) it's p_nom.
    print(f"\n=== {label}: per-bus electricity supply potential vs. load ===")
    elec_buses = n.buses[n.buses.carrier == "electricity"].index
    print(f"Buses: {list(elec_buses)}")

    # Per-bus, per-snapshot: VRE supply potential
    rows = []
    for bus in elec_buses:
        gens_on_bus = gen_bus[gen_bus == bus].index
        if not len(gens_on_bus):
            continue
        # Supply potential summed across generators on the bus
        supply = pd.Series(0.0, index=snapshots)
        for g in gens_on_bus:
            p_nom = n.generators.at[g, "p_nom"]
            if g in pmp.columns:
                supply += pmp[g] * p_nom
            else:
                supply += p_nom  # static
        # Load on this bus
        loads_on_bus = n.loads[n.loads.bus == bus].index
        load = pd.Series(0.0, index=snapshots)
        for ld in loads_on_bus:
            if ld in p_set.columns:
                load += p_set[ld]
            else:
                load += n.loads.at[ld, "p_set"]
        # Net = supply - load (positive = export-capable)
        net = supply - load
        rows.append({
            "bus": bus,
            "supply_max": float(supply.max()),
            "supply_min": float(supply.min()),
            "load_max": float(load.max()),
            "load_min": float(load.min()),
            "net_min": float(net.min()),  # most-negative => worst deficit
            "net_min_at": net.idxmin(),
        })
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))


def interconnect_capacity_summary(n, label):
    """Sum link p_nom into / out of each bus."""
    print(f"\n=== {label}: per-bus interconnect capacity ===")
    elec_buses = n.buses[n.buses.carrier == "electricity"].index
    rows = []
    for bus in elec_buses:
        out_cap = n.links[n.links.bus0 == bus]["p_nom"].sum()
        in_cap = n.links[n.links.bus1 == bus]["p_nom"].sum()
        rows.append({"bus": bus, "out_p_nom": out_cap, "in_p_nom": in_cap})
    print(pd.DataFrame(rows).to_string(index=False))


def main():
    state = _load_state()
    print(f"State: ely={state.cumulative_ely_mw:.0f} wind={state.cumulative_wind_mw:.0f} "
          f"solar={state.cumulative_solar_mw:.0f}")
    n_a, _ = build_2041_network_with_overrides(
        state, isp_override="accelerated_transition", year_override=2041
    )
    n_b, _ = build_2041_network_with_overrides(
        state, isp_override="step_change", year_override=2041
    )

    topology(n_a, "ACCE_TRANS/2041")
    interconnect_capacity_summary(n_a, "ACCE_TRANS/2041")
    interconnect_capacity_summary(n_b, "STEP_CHANGE/2041")

    supply_demand_balance(n_a, "ACCE_TRANS/2041")
    supply_demand_balance(n_b, "STEP_CHANGE/2041")


if __name__ == "__main__":
    main()
