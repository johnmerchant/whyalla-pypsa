"""Shared pytest fixtures for whyalla-pypsa tests."""

from __future__ import annotations

from pathlib import Path

import pytest

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


DATA_PATH = Path("/Users/johnmerchant/Downloads/Draft 2026 ISP")


@pytest.fixture
def data_path() -> Path:
    return DATA_PATH


@pytest.fixture
def default_config() -> FacilityConfig:
    return FacilityConfig(
        wind=WindConfig(cost=CostAssumption(capex_per_unit=2000.0)),
        solar=SolarConfig(cost=CostAssumption(capex_per_unit=1300.0)),
        battery=BatteryConfig(
            power_cost=CostAssumption(capex_per_unit=400.0, lifetime_years=15),
            energy_cost=CostAssumption(capex_per_unit=250.0, lifetime_years=15),
        ),
        h2_storage=H2StorageConfig(cost=CostAssumption(capex_per_unit=15_000.0)),
        grid=GridConfig(),
        scenario=ScenarioConfig(),
        data_path=DATA_PATH,
    )
