"""Unit tests: attach_efuels() on a minimal stub facility network.

Solves with HiGHS. Tests:
  - plant builds under favourable economics (cheap ely, high fuel price, cheap CO2)
  - plant does NOT build under hostile economics
  - ASF product buses are created in asf mode
  - single_fuel mode attaches meoh_export generator

Usage:
    pytest test_attach_efuels.py -v
"""
import pytest
import pandas as pd
import pypsa

pytest.importorskip("highspy", reason="HiGHS not installed")


@pytest.fixture
def stub_network():
    """Minimal facility-like network: facility_ac + facility_h2 buses, cheap generator."""
    n = pypsa.Network()
    snapshots = pd.date_range("2030-01-01", periods=48, freq="h")
    n.set_snapshots(snapshots)
    # Weight so sum = 1 FY (8760 h); each snapshot represents 8760/48 hours
    n.snapshot_weightings.loc[:, :] = 8760 / len(snapshots)

    for carrier in ("AC", "H2"):
        if carrier not in n.carriers.index:
            n.add("Carrier", carrier)

    n.add("Bus", "facility_ac", carrier="AC")
    n.add("Bus", "facility_h2", carrier="H2")

    # Cheap electricity source on AC bus
    n.add("Generator", "cheap_gen", bus="facility_ac", carrier="AC",
          p_nom=10_000, marginal_cost=20)
    # Background electrical load to keep the network non-trivial
    n.add("Load", "bg_load", bus="facility_ac", p_set=500)

    # H2 bus needs a source or a link — electrolyser provides that,
    # but we also need a slack to allow zero-build scenarios.
    # Add a very expensive H2 generator as slack so the network is always feasible.
    n.add("Generator", "h2_slack", bus="facility_h2", carrier="H2",
          p_nom=1e6, marginal_cost=99_999)
    return n


def _solve(n: pypsa.Network) -> str:
    status, _ = n.optimize(solver_name="highs")
    return status


# ── Favourable economics ───────────────────────────────────────────────────

def test_plant_builds_under_favourable_economics(stub_network):
    """Low CAPEX + cheap CO2 + high fuel price → electrolyser and synthesis build."""
    from process_chain import attach_efuels
    from efuels_results import extract_lcom_lcof

    n = stub_network
    attach_efuels(
        n,
        electrolyser_capex_per_kw=300.0,
        synthesis_capex_per_t_meoh_yr=200.0,
        co2_supply_fn=lambda: [{"_tranche_name": "co2_cheap", "p_nom": 1e9,
                                 "marginal_cost": 30.0}],
        diesel_price_per_t=3000.0,
        kero_price_per_t=3000.0,
        naphtha_price_per_t=3000.0,
        wax_price_per_t=3000.0,
        annual_fuel_mt=0.0,       # export-only; no rigid load
        wacc=0.07,
        product_split_mode="asf",
    )
    status = _solve(n)
    assert status in ("ok", "optimal"), f"Solve failed: {status}"

    m = extract_lcom_lcof(n, None)
    assert m["ely_mw"] > 0, "Electrolyser should build"
    assert m["meoh_tonnes"] > 0, "Methanol synthesis should run"


# ── Hostile economics ──────────────────────────────────────────────────────

def test_no_plant_under_hostile_economics(stub_network):
    """Very high CAPEX + expensive CO2 + low fuel price → nothing builds."""
    from process_chain import attach_efuels
    from efuels_results import extract_lcom_lcof

    n = stub_network
    attach_efuels(
        n,
        electrolyser_capex_per_kw=15_000.0,
        synthesis_capex_per_t_meoh_yr=5_000.0,
        co2_supply_fn=lambda: [{"_tranche_name": "co2_exp", "p_nom": 1e9,
                                 "marginal_cost": 800.0}],
        diesel_price_per_t=200.0,
        kero_price_per_t=200.0,
        naphtha_price_per_t=200.0,
        wax_price_per_t=100.0,
        annual_fuel_mt=0.0,
        wacc=0.15,
        product_split_mode="asf",
    )
    status = _solve(n)
    assert status in ("ok", "optimal"), f"Solve failed: {status}"

    m = extract_lcom_lcof(n, None)
    assert m["ely_mw"] < 1.0, "Electrolyser should not build under hostile economics"


# ── ASF product buses ──────────────────────────────────────────────────────

def test_asf_mode_creates_product_buses(stub_network):
    """attach_efuels in asf mode should add naphtha/kero/diesel/wax buses."""
    from process_chain import attach_efuels

    n = stub_network
    attach_efuels(n, product_split_mode="asf", annual_fuel_mt=0.0)

    for product in ("naphtha", "kero", "diesel", "wax"):
        assert f"{product}_bus" in n.buses.index, f"Missing bus: {product}_bus"
        assert f"refinery_{product}" in n.links.index, f"Missing link: refinery_{product}"


# ── Single-fuel mode ───────────────────────────────────────────────────────

def test_single_fuel_mode(stub_network):
    """single_fuel mode should attach meoh_export generator on the meoh bus."""
    from process_chain import attach_efuels

    n = stub_network
    attach_efuels(n, product_split_mode="single_fuel",
                  methanol_price_per_t=900.0, annual_fuel_mt=0.0)

    assert "meoh_export" in n.generators.index
    assert "meoh" in n.buses.index


# ── CO2 merit-order dispatch ───────────────────────────────────────────────

def test_co2_tranches_added(stub_network):
    """All tranches returned by co2_supply_fn should appear as generators."""
    from process_chain import attach_efuels

    tranches = [
        {"_tranche_name": "co2_a", "p_nom": 1000.0, "marginal_cost": 50.0},
        {"_tranche_name": "co2_b", "p_nom": 500.0,  "marginal_cost": 120.0},
    ]
    n = stub_network
    attach_efuels(n, co2_supply_fn=lambda: tranches, annual_fuel_mt=0.0)

    assert "co2_a" in n.generators.index
    assert "co2_b" in n.generators.index
