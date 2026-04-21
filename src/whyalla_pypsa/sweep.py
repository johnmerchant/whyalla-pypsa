"""Thin joblib wrapper for parametric sweeps over FacilityConfig.

Overrides are specified as dotted-path assignments (e.g.
"wind.cost.capex_per_unit") into the dataclass tree. A small local setter
handles the walk so we avoid pulling in an external dependency.
"""

from __future__ import annotations

import copy
from dataclasses import is_dataclass, replace
from typing import Any, Callable

import pandas as pd
from joblib import Parallel, delayed

from whyalla_pypsa.config import FacilityConfig


def _set_dotted(obj: Any, dotted: str, value: Any) -> None:
    """Walk a dotted path through dataclasses/dicts and set the final attr."""
    parts = dotted.split(".")
    cursor = obj
    for part in parts[:-1]:
        if isinstance(cursor, dict):
            cursor = cursor[part]
        else:
            cursor = getattr(cursor, part)
    last = parts[-1]
    if isinstance(cursor, dict):
        cursor[last] = value
    else:
        setattr(cursor, last, value)


def _apply_overrides(base: FacilityConfig, overrides: dict[str, Any]) -> FacilityConfig:
    cfg = copy.deepcopy(base)
    for dotted, value in overrides.items():
        _set_dotted(cfg, dotted, value)
    return cfg


def _one(
    base: FacilityConfig,
    overrides: dict[str, Any],
    build_fn: Callable[[FacilityConfig], Any],
    postprocess_fn: Callable[[Any, FacilityConfig], dict[str, Any]],
) -> dict[str, Any]:
    cfg = _apply_overrides(base, overrides)
    network = build_fn(cfg)
    result = postprocess_fn(network, cfg)
    return {**overrides, **result}


def run_sweep(
    base_config: FacilityConfig,
    overrides: list[dict[str, Any]],
    build_fn: Callable[[FacilityConfig], Any],
    postprocess_fn: Callable[[Any, FacilityConfig], dict[str, Any]],
    n_jobs: int = -1,
) -> pd.DataFrame:
    """Run `build_fn` then `postprocess_fn` for each override dict in parallel."""
    rows = Parallel(n_jobs=n_jobs)(
        delayed(_one)(base_config, ov, build_fn, postprocess_fn) for ov in overrides
    )
    return pd.DataFrame(rows)
