"""Config dataclasses for a Whyalla facility network.

`FacilityConfig` is the single entry point; nested dataclasses are round-tripped
to YAML via `from_yaml` / `to_yaml` which walk the dataclass tree generically.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields, is_dataclass, asdict
from pathlib import Path
from typing import Any

import yaml


@dataclass
class CostAssumption:
    capex_per_unit: float
    fom_pct: float = 0.02
    vom_per_mwh: float = 0.0
    lifetime_years: int = 25


@dataclass
class WindConfig:
    cost: CostAssumption
    rez: str = "S5"
    # NOTE: spec listed "LKBONNY2" as default but that site sits in REZ S3
    # (Mid-North SA), not S5. S5_WH_Northern_SA is the Draft 2026 REZ S5
    # representative wind trace; LKBONNY2 is retained as an explicit override
    # option and still resolvable via the Wind traces folder.
    representative_site: str = "S5_WH_Northern_SA"
    max_capacity_mw: float | None = None


@dataclass
class SolarConfig:
    cost: CostAssumption
    rez: str = "S5"
    # NOTE: spec listed "BNGSF1" but no such file exists in Draft 2026 Solar
    # traces. The REZ S5 SAT trace is the correct aggregate representative.
    representative_site: str = "REZ_S5_Northern_SA_SAT"
    max_capacity_mw: float | None = None


@dataclass
class BatteryConfig:
    power_cost: CostAssumption
    energy_cost: CostAssumption
    roundtrip_efficiency: float = 0.88
    duration_hours: float | None = None


@dataclass
class H2StorageConfig:
    cost: CostAssumption
    storage_type: str = "tank"


@dataclass
class GridConfig:
    subregion: str = "CSA"
    mode: str = "rldc_merit"
    link_capex_per_mw: float = 400_000.0
    link_efficiency: float = 0.98
    link_max_capacity_mw: float | None = None


@dataclass
class ScenarioConfig:
    name: str = "Step Change"
    file_token: str = "STEP_CHANGE"
    # CDP variant placeholder. Draft 2026 top-level folders are just the three
    # scenarios; CDPx selection is not yet wired into filename resolution.
    # TODO: wire once AEMO publishes CDP-split folders in Draft 2026.
    cdp: str = "CDP4"
    reference_year: int = 2011
    refyear_file_token: int = 5000
    model_year: int = 2030
    resolution: str = "hourly"
    # Snapshot mode: "full_year" uses all 8760 hourly snapshots (default,
    # backward-compatible). "representative_weeks" slices N evenly-spaced
    # 168-hour windows and re-weights snapshot_weightings so totals scale to
    # a full year. Good for ~30× LP-size reduction in sizing sweeps.
    snapshot_mode: str = "full_year"
    representative_weeks: int = 4


@dataclass
class ComponentWACC:
    wacc: float
    lifetime_years: int


@dataclass
class WACCOverlay:
    """Component-specific WACC applied in post-processing. NOT fed into PyPSA."""

    wind: ComponentWACC = field(default_factory=lambda: ComponentWACC(0.06, 25))
    solar: ComponentWACC = field(default_factory=lambda: ComponentWACC(0.06, 25))
    battery_power: ComponentWACC = field(default_factory=lambda: ComponentWACC(0.07, 15))
    battery_energy: ComponentWACC = field(default_factory=lambda: ComponentWACC(0.07, 15))
    h2_storage: ComponentWACC = field(default_factory=lambda: ComponentWACC(0.08, 25))
    electrolyser: ComponentWACC = field(default_factory=lambda: ComponentWACC(0.09, 20))
    grid_link: ComponentWACC = field(default_factory=lambda: ComponentWACC(0.06, 40))
    extra: dict[str, ComponentWACC] = field(default_factory=dict)
    default: ComponentWACC = field(default_factory=lambda: ComponentWACC(0.08, 25))


@dataclass
class FacilityConfig:
    wind: WindConfig
    solar: SolarConfig
    battery: BatteryConfig
    h2_storage: H2StorageConfig
    grid: GridConfig
    scenario: ScenarioConfig
    data_path: Path = Path("/Users/johnmerchant/Downloads/Draft 2026 ISP")
    pypsa_wacc: float = 0.07
    wacc_overlay: WACCOverlay = field(default_factory=WACCOverlay)
    solver: str = "highs"
    # HiGHS solver options. Defaults to IPM (interior-point) with parallel
    # solve and presolve enabled — typically 2-5× faster than simplex on large
    # facility LPs. Override per-run for debugging (e.g. {"solver": "simplex"}).
    solver_options: dict = field(
        default_factory=lambda: {"solver": "ipm", "parallel": "on", "presolve": "on"}
    )

    def to_yaml(self, path: str | Path) -> None:
        """Serialise this config to YAML, converting Path objects to strings."""
        payload = _to_serialisable(self)
        Path(path).write_text(yaml.safe_dump(payload, sort_keys=False))

    @classmethod
    def from_yaml(cls, path: str | Path) -> "FacilityConfig":
        """Reconstruct a FacilityConfig (and nested dataclasses) from YAML."""
        raw = yaml.safe_load(Path(path).read_text())
        return _from_dict(cls, raw)


# ---- (de)serialisation helpers ----------------------------------------------


def _to_serialisable(obj: Any) -> Any:
    if is_dataclass(obj):
        return {f.name: _to_serialisable(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _to_serialisable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serialisable(v) for v in obj]
    return obj


def _from_dict(cls: type, data: Any) -> Any:
    """Recursively build dataclass instances from a nested dict."""
    if data is None:
        return None
    if not is_dataclass(cls):
        # Leaf: coerce Path if the annotation says so.
        if cls is Path and isinstance(data, str):
            return Path(data)
        return data

    kwargs: dict[str, Any] = {}
    type_hints = {f.name: f.type for f in fields(cls)}
    for name, value in data.items():
        ftype = type_hints.get(name)
        kwargs[name] = _coerce(ftype, value)
    return cls(**kwargs)


def _coerce(ftype: Any, value: Any) -> Any:
    # Handle typing.Optional / unions of the form "T | None" as strings in 3.11.
    import types
    import typing

    if isinstance(ftype, str):
        try:
            ftype = eval(ftype, {**globals(), **vars(typing)})
        except Exception:
            return value

    origin = typing.get_origin(ftype)
    args = typing.get_args(ftype)

    if origin is dict:
        if len(args) == 2 and is_dataclass(args[1]):
            return {k: _from_dict(args[1], v) for k, v in (value or {}).items()}
        return value or {}

    # Unwrap Optional / X | None: pick first dataclass or return raw value.
    if origin is typing.Union or origin is types.UnionType:
        for arg in args:
            if is_dataclass(arg):
                return _from_dict(arg, value) if value is not None else None
            if arg is Path:
                return Path(value) if value is not None else None
        return value

    if is_dataclass(ftype):
        return _from_dict(ftype, value)
    if ftype is Path:
        return Path(value) if value is not None else None
    return value
