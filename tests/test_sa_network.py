"""Tests for the 3-subregion SA dispatch overlay (`attach_sa_dispatch`).

These tests avoid real AEMO data by injecting override payloads for demand,
GGO capacities, and PLEXOS interconnector stages. A small solve smoke test
checks optimisation reaches `optimal` on a 24-hour synthetic network.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

pypsa = pytest.importorskip("pypsa")

try:
    import highspy  # noqa: F401

    HAS_HIGHS = True
except Exception:
    HAS_HIGHS = False

from whyalla_pypsa.config import (
    BatteryConfig,
    CostAssumption,
    FacilityConfig,
    GridConfig,
    H2StorageConfig,
    ScenarioConfig,
    SolarConfig,
    WindConfig,
)
from whyalla_pypsa.data.plexos_xml import FlowStage
from whyalla_pypsa.sa_network import (
    _DemandOverride,
    _GGOOverride,
    _InterconnectorOverride,
    attach_sa_dispatch,
    pick_stage_for_year,
)


# ---------------------------------------------------------------------------
# Shared fixtures — hand-rolled so no AEMO data is read.
# ---------------------------------------------------------------------------


def _make_config(model_year: int = 2030) -> FacilityConfig:
    return FacilityConfig(
        wind=WindConfig(cost=CostAssumption(capex_per_unit=2000.0)),
        solar=SolarConfig(cost=CostAssumption(capex_per_unit=1300.0)),
        battery=BatteryConfig(
            power_cost=CostAssumption(capex_per_unit=400.0, lifetime_years=15),
            energy_cost=CostAssumption(capex_per_unit=250.0, lifetime_years=15),
        ),
        h2_storage=H2StorageConfig(cost=CostAssumption(capex_per_unit=15_000.0)),
        grid=GridConfig(subregion="CSA", mode="sa_dispatch"),
        scenario=ScenarioConfig(model_year=model_year),
        data_path=Path("/nonexistent"),  # overrides supply data
    )


def _skeleton_network(hours: int = 24, start: str = "2030-01-01") -> pypsa.Network:
    """A facility-like network with a CSA_ac bus and facility<->CSA links."""
    snaps = pd.date_range(start, periods=hours, freq="1h")
    n = pypsa.Network()
    n.set_snapshots(snaps)
    n.add("Carrier", "electricity")
    n.add("Bus", "facility_ac", carrier="electricity")
    n.add("Bus", "CSA_ac", carrier="electricity")
    # Minimal grid links so the CSA_ac bus isn't an island when the facility is
    # present. Tests below either leave these unused or exercise them trivially.
    n.add(
        "Link",
        "grid_import",
        bus0="CSA_ac",
        bus1="facility_ac",
        efficiency=1.0,
        p_nom=1e6,
    )
    n.add(
        "Link",
        "grid_export",
        bus0="facility_ac",
        bus1="CSA_ac",
        efficiency=1.0,
        p_nom=1e6,
    )
    return n


def _demand_override(snaps: pd.DatetimeIndex, mw: float) -> _DemandOverride:
    """Flat `mw` demand for every SA + slack-proxy subregion."""
    demand = {sub: pd.Series(mw, index=snaps) for sub in ("CSA", "NSA", "SESA")}
    # Slack-proxy subs (MEL, SNW) also get flat demand so price derivation works.
    for sub in ("MEL", "SNW"):
        demand[sub] = pd.Series(mw, index=snaps)
    return _DemandOverride(demand=demand, rooftop=None)


def _ggo_override() -> _GGOOverride:
    # Small, non-zero fleet so nothing divides by zero and the BESS branch runs.
    return _GGOOverride(
        mw_by_sub={
            "CSA": {"wind": 200.0, "solar": 150.0, "thermal": 80.0, "bess": 100.0},
            "NSA": {"wind": 300.0, "solar": 100.0, "thermal": 40.0, "bess": 50.0},
            "SESA": {"wind": 150.0, "solar": 120.0, "thermal": 60.0, "bess": 80.0},
        }
    )


def _ix_override_for_year(model_year: int) -> _InterconnectorOverride:
    """Build staged FlowStage lists for PEC + Heywood + Murraylink.

    Staging: 2027-11-30 is the PEC/Heywood upgrade date.
    """
    upgrade = date(2027, 11, 30)
    return _InterconnectorOverride(
        stages_by_name={
            "EnergyConnect": [
                FlowStage(date_from=None, date_to=None, value=150.0),
                FlowStage(date_from=upgrade, date_to=None, value=800.0),
            ],
            "V-SA": [
                FlowStage(date_from=None, date_to=None, value=650.0),
                FlowStage(date_from=upgrade, date_to=None, value=750.0),
            ],
            "V-S-MNSP1": [
                FlowStage(date_from=None, date_to=None, value=220.0),
            ],
            # Intra-SA — optional. Leave empty to trigger default p_nom.
        },
        csa_nsa_name=None,
        sesa_csa_name=None,
    )


# ---------------------------------------------------------------------------
# 1. Structural tests
# ---------------------------------------------------------------------------


def test_adds_all_buses():
    config = _make_config(model_year=2030)
    n = _skeleton_network(hours=24)
    attach_sa_dispatch(
        n,
        config,
        _override_demand=_demand_override(n.snapshots, mw=200.0),
        _override_ggo=_ggo_override(),
        _override_interconnectors=_ix_override_for_year(2030),
    )
    expected = {"CSA_ac", "NSA_ac", "SESA_ac", "VIC_slack_ac", "NSW_slack_ac"}
    assert expected.issubset(set(n.buses.index))


def test_pec_staging_pre_2027():
    """model_year=2027 -> cutoff 2027-07-01 < 2027-11-30 upgrade -> baseline 150 MW."""
    config = _make_config(model_year=2027)
    n = _skeleton_network(hours=24)
    attach_sa_dispatch(
        n,
        config,
        _override_demand=_demand_override(n.snapshots, mw=200.0),
        _override_ggo=_ggo_override(),
        _override_interconnectors=_ix_override_for_year(2027),
    )
    # PEC is the NSA<->NSW_slack pair; forward link named "pec_fwd".
    pec_fwd = n.links.loc["pec_fwd"]
    assert pec_fwd.bus0 == "NSA_ac" and pec_fwd.bus1 == "NSW_slack_ac"
    assert pec_fwd.p_nom == pytest.approx(150.0)


def test_pec_staging_post_2028():
    """model_year=2028 -> cutoff 2028-07-01 > 2027-11-30 upgrade -> 800 MW."""
    config = _make_config(model_year=2028)
    n = _skeleton_network(hours=24)
    attach_sa_dispatch(
        n,
        config,
        _override_demand=_demand_override(n.snapshots, mw=200.0),
        _override_ggo=_ggo_override(),
        _override_interconnectors=_ix_override_for_year(2028),
    )
    assert n.links.loc["pec_fwd"].p_nom == pytest.approx(800.0)
    assert n.links.loc["pec_rev"].p_nom == pytest.approx(800.0)


def test_heywood_staging_post_2028():
    """model_year=2028 -> cutoff 2028-07-01 > 2027-11-30 upgrade -> 750 MW."""
    config = _make_config(model_year=2028)
    n = _skeleton_network(hours=24)
    attach_sa_dispatch(
        n,
        config,
        _override_demand=_demand_override(n.snapshots, mw=200.0),
        _override_ggo=_ggo_override(),
        _override_interconnectors=_ix_override_for_year(2028),
    )
    assert n.links.loc["heywood_fwd"].p_nom == pytest.approx(750.0)
    assert n.links.loc["heywood_rev"].p_nom == pytest.approx(750.0)


# ---------------------------------------------------------------------------
# 2. Direct helper test
# ---------------------------------------------------------------------------


def test_pick_stage_picks_baseline_before_upgrade():
    stages = [
        FlowStage(date_from=None, date_to=None, value=150.0),
        FlowStage(date_from=date(2027, 11, 30), date_to=None, value=800.0),
    ]
    # model_year=2027 cutoff = 2027-07-01 < 2027-11-30 -> baseline wins.
    assert pick_stage_for_year(stages, 2027).value == 150.0
    # model_year=2028 cutoff = 2028-07-01 > 2027-11-30 -> upgrade wins.
    assert pick_stage_for_year(stages, 2028).value == 800.0


# ---------------------------------------------------------------------------
# 3. Solve smoke test
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_HIGHS, reason="HiGHS solver not available")
def test_solve_smoke():
    config = _make_config(model_year=2030)
    n = _skeleton_network(hours=24)

    # Demand sized to exceed local (wind+solar+thermal) so slack imports kick in.
    demand_override = _demand_override(n.snapshots, mw=600.0)
    attach_sa_dispatch(
        n,
        config,
        _override_demand=demand_override,
        _override_ggo=_ggo_override(),
        _override_interconnectors=_ix_override_for_year(2030),
    )
    status, condition = n.optimize(solver_name="highs")
    assert status in {"ok", "optimal"}, f"Solve failed: {status=} {condition=}"
    # Some generation should have occurred — at minimum loads were served.
    gen_total = n.generators_t.p.sum().sum()
    assert gen_total > 0
    # Slack buses should have supplied some energy since local capacity is tight.
    slack_flow = (
        n.generators_t.p.get("VIC_slack_supply", pd.Series(0.0)).sum()
        + n.generators_t.p.get("NSW_slack_supply", pd.Series(0.0)).sum()
    )
    assert slack_flow > 0
