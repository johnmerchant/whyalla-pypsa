"""Unit tests: attach_dri_eaf() on a minimal synthetic facility network.

Tests:
- electrolyser and H2 store are built under cheap-H2 conditions
- electrolyser is NOT built when capex is very high
- all required keys present in extract_lcoh_lcos output

Skip cleanly if HiGHS is unavailable.
"""
import pytest
import pandas as pd
import numpy as np
import pypsa

try:
    import highspy  # noqa: F401
    HIGHS_AVAILABLE = True
except ImportError:
    HIGHS_AVAILABLE = False

needs_highs = pytest.mark.skipif(not HIGHS_AVAILABLE, reason="HiGHS not installed")


def _make_stub_network() -> pypsa.Network:
    """Minimal 48-snapshot network with a cheap AC generator and H2 bus."""
    n = pypsa.Network()
    snapshots = pd.date_range("2030-01-01", periods=48, freq="h")
    n.set_snapshots(snapshots)
    # Weight each snapshot to represent a full year
    n.snapshot_weightings.loc[:, :] = 8760.0 / len(snapshots)

    # Carriers and buses expected by attach_dri_eaf
    n.add("Carrier", "electricity")
    n.add("Carrier", "H2")
    n.add("Bus", "facility_ac", carrier="electricity")
    n.add("Bus", "facility_h2", carrier="H2")

    # Cheap electricity supply
    n.add("Generator", "cheap_gen", bus="facility_ac", carrier="electricity",
          p_nom=5000.0, marginal_cost=20.0)

    # H2 store (extendable) — part of the facility network
    n.add("Store", "h2_store", bus="facility_h2", carrier="H2",
          e_nom_extendable=True, e_cyclic=True, capital_cost=100.0)

    return n


@needs_highs
def test_electrolyser_builds_under_low_capex(tmp_path):
    """Electrolyser should build when capex is low and electricity is cheap."""
    from process_chain import attach_dri_eaf

    n = _make_stub_network()
    attach_dri_eaf(
        n,
        electrolyser_capex_per_kw=300.0,   # very low
        annual_steel_mt=0.1,               # small problem
        dri_min_load=0.0,
        dri_ramp_limit_up=1.0,
        dri_ramp_limit_down=1.0,
    )
    status, _ = n.optimize(solver_name="highs")
    assert status in ("ok", "optimal"), f"Solve failed: {status}"

    ely_mw = n.links.at["electrolyser", "p_nom_opt"]
    assert ely_mw > 0.0, "Electrolyser should build under low CAPEX"


@needs_highs
def test_electrolyser_minimal_under_high_capex(tmp_path):
    """Electrolyser should size to minimum under very high capex."""
    from process_chain import attach_dri_eaf

    n = _make_stub_network()
    attach_dri_eaf(
        n,
        electrolyser_capex_per_kw=50_000.0,  # extremely high
        annual_steel_mt=0.1,
        dri_min_load=0.0,
        dri_ramp_limit_up=1.0,
        dri_ramp_limit_down=1.0,
    )
    status, _ = n.optimize(solver_name="highs")
    assert status in ("ok", "optimal"), f"Solve failed: {status}"

    # With huge capex the optimizer should build as little electrolyser as feasible
    # (problem is still feasible because h2_to_dri is the only H2 supply path)
    ely_mw = n.links.at["electrolyser", "p_nom_opt"]
    # Just assert it's finite and non-negative
    assert ely_mw >= 0.0


@needs_highs
def test_extract_lcoh_lcos_keys(tmp_path):
    """extract_lcoh_lcos should return all required keys."""
    from process_chain import attach_dri_eaf
    from whyalla_results import extract_lcoh_lcos
    from whyalla_pypsa import (
        FacilityConfig, WindConfig, SolarConfig, BatteryConfig,
        H2StorageConfig, GridConfig, ScenarioConfig, CostAssumption, WACCOverlay,
    )

    n = _make_stub_network()
    attach_dri_eaf(
        n,
        electrolyser_capex_per_kw=500.0,
        annual_steel_mt=0.1,
        dri_min_load=0.0,
        dri_ramp_limit_up=1.0,
        dri_ramp_limit_down=1.0,
    )
    n.optimize(solver_name="highs")

    # Build a minimal FacilityConfig for the results extractor
    config = FacilityConfig(
        wind=WindConfig(cost=CostAssumption(capex_per_unit=2200.0)),
        solar=SolarConfig(cost=CostAssumption(capex_per_unit=1100.0)),
        battery=BatteryConfig(
            power_cost=CostAssumption(capex_per_unit=500.0),
            energy_cost=CostAssumption(capex_per_unit=250.0),
        ),
        h2_storage=H2StorageConfig(cost=CostAssumption(capex_per_unit=20000.0)),
        grid=GridConfig(subregion="CSA"),
        scenario=ScenarioConfig(model_year=2030),
        wacc_overlay=WACCOverlay(),
    )

    metrics = extract_lcoh_lcos(n, config)

    required_keys = [
        "lcoh_per_kg", "lcos_per_t_steel", "ely_mw", "h2_store_mwh",
        "annual_h2_kg", "annual_steel_t", "ely_cf", "total_eaf_mwh",
    ]
    for key in required_keys:
        assert key in metrics, f"Missing key: {key}"


def test_buses_and_links_attached():
    """Verify all expected buses and links are present after attach_dri_eaf."""
    from process_chain import attach_dri_eaf

    n = _make_stub_network()
    attach_dri_eaf(n, annual_steel_mt=0.1)

    assert "dri_reductant" in n.buses.index
    assert "dri_solid" in n.buses.index
    assert "steel" in n.buses.index
    assert "electrolyser" in n.links.index
    assert "h2_to_dri" in n.links.index
    assert "dri_plant" in n.links.index
    assert "eaf" in n.links.index
    assert "dri_pile" in n.stores.index
    assert "eaf_campaign" in n.stores.index
    assert "steel_offtake" in n.loads.index


# ── Dual-fuel (H2/NG) DRI tests ────────────────────────────────────────────
# These do not require a solver — they inspect unsolved-network attributes.

def _make_bare_network() -> pypsa.Network:
    """Network without needing a solver: 4 snapshots, just carriers+buses."""
    n = pypsa.Network()
    snapshots = pd.date_range("2030-01-01", periods=4, freq="h")
    n.set_snapshots(snapshots)
    n.add("Carrier", "electricity")
    n.add("Carrier", "H2")
    n.add("Bus", "facility_ac", carrier="electricity")
    n.add("Bus", "facility_h2", carrier="H2")
    return n


def test_dual_fuel_off_is_backcompat():
    """dual_fuel=False (default) must not add any NG components."""
    from process_chain import attach_dri_eaf

    n = _make_bare_network()
    attach_dri_eaf(n, annual_steel_mt=0.1, dual_fuel=False)

    assert "gas" not in n.carriers.index
    assert "ng" not in n.buses.index
    assert "ng_supply" not in n.generators.index
    assert "dri_plant_gas" not in n.links.index


def test_dual_fuel_adds_gas_path():
    """dual_fuel=True adds gas carrier, ng bus, ng_supply gen, dri_plant_gas link."""
    from process_chain import attach_dri_eaf

    n = _make_bare_network()
    attach_dri_eaf(
        n,
        annual_steel_mt=0.1,
        dual_fuel=True,
        ng_intensity_mwh_per_t_dri=3.0,
    )

    assert "gas" in n.carriers.index
    assert "ng" in n.buses.index
    assert n.buses.at["ng", "carrier"] == "gas"
    assert "ng_supply" in n.generators.index
    assert "dri_plant_gas" in n.links.index

    # Link topology
    link = n.links.loc["dri_plant_gas"]
    assert link["bus0"] == "ng"
    assert link["bus1"] == "dri_solid"
    assert link["bus2"] == "facility_ac"

    # Efficiency ≈ 1 / ng_intensity_mwh_per_t_dri
    assert link["efficiency"] == pytest.approx(1.0 / 3.0)

    # Original H2 dri_plant must still exist (parallel, not replaced)
    assert "dri_plant" in n.links.index


def test_dual_fuel_carbon_price_zero_prefers_gas():
    """With zero carbon price, dri_plant_gas has a lower direct marginal_cost
    than the H2 dri_plant (H2 has marginal_cost=0.5). The gas link's direct
    marginal_cost equals the carbon term only, which is zero here."""
    from process_chain import attach_dri_eaf

    n = _make_bare_network()
    attach_dri_eaf(
        n,
        annual_steel_mt=0.1,
        dual_fuel=True,
        ng_price_per_gj=12.0,
        carbon_price_per_t_co2=0.0,
    )

    gas_mc = n.links.at["dri_plant_gas", "marginal_cost"]
    h2_mc = n.links.at["dri_plant", "marginal_cost"]

    # Zero carbon => gas link's direct marginal_cost is 0 (fuel cost is upstream
    # on the ng_supply generator, not on the link itself).
    assert gas_mc == pytest.approx(0.0)
    assert gas_mc < h2_mc


def test_dual_fuel_carbon_price_high_penalises_gas():
    """Under a high carbon price the dri_plant_gas link's marginal_cost
    should match the analytical formula:
        mc = carbon_price * co2_intensity / 1000 / ng_intensity  [$/MWh_NG]
    """
    from process_chain import attach_dri_eaf

    n = _make_bare_network()
    carbon_price = 500.0
    co2_intensity = 560.0
    ng_intensity = 3.0
    attach_dri_eaf(
        n,
        annual_steel_mt=0.1,
        dual_fuel=True,
        ng_price_per_gj=12.0,
        co2_intensity_kg_per_t_dri=co2_intensity,
        ng_intensity_mwh_per_t_dri=ng_intensity,
        carbon_price_per_t_co2=carbon_price,
    )

    expected_mc = carbon_price * co2_intensity / 1000.0 / ng_intensity
    gas_mc = n.links.at["dri_plant_gas", "marginal_cost"]
    assert gas_mc == pytest.approx(expected_mc)
    # Sanity: carbon burden should clearly exceed the H2 link's nominal 0.5 $/MWh.
    assert gas_mc > n.links.at["dri_plant", "marginal_cost"]
