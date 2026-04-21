"""Config dataclass instantiation and YAML round-trip."""

from __future__ import annotations

from pathlib import Path

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


def _make() -> FacilityConfig:
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
    )


def test_instantiate_defaults():
    cfg = _make()
    assert cfg.wind.cost.capex_per_unit == 2000.0
    assert cfg.battery.roundtrip_efficiency == 0.88
    assert cfg.scenario.file_token == "STEP_CHANGE"
    assert cfg.wacc_overlay.wind.wacc == 0.06
    assert cfg.wacc_overlay.default.wacc == 0.08


def test_yaml_roundtrip(tmp_path: Path):
    cfg = _make()
    out = tmp_path / "cfg.yaml"
    cfg.to_yaml(out)

    restored = FacilityConfig.from_yaml(out)
    assert restored.wind.cost.capex_per_unit == cfg.wind.cost.capex_per_unit
    assert restored.battery.energy_cost.lifetime_years == 15
    assert restored.scenario.file_token == "STEP_CHANGE"
    assert restored.wacc_overlay.battery_power.wacc == 0.07
    assert isinstance(restored.data_path, Path)
