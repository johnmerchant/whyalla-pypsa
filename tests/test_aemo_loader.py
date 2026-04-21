"""AEMO Draft 2026 loader tests. Skip cleanly if data path is absent."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from whyalla_pypsa.data.aemo_draft_2026 import (
    load_demand,
    load_trace,
    to_hourly,
)

_raw = os.environ.get("AEMO_DRAFT_2026_PATH")
DATA_PATH = Path(_raw) if _raw else None


pytestmark = pytest.mark.skipif(
    DATA_PATH is None or not DATA_PATH.exists(),
    reason="Set AEMO_DRAFT_2026_PATH to the Draft 2026 ISP directory to run these tests.",
)


def test_load_csa_demand():
    s = load_demand(DATA_PATH, "CSA", "STEP_CHANGE", refyear=5000)
    assert len(s) == 17520
    assert (s > 0).any()
    assert s.index.freqstr in {"30min", "30T"} or (s.index[1] - s.index[0]).seconds == 1800


def test_load_wind_site():
    # S5_WH_Northern_SA is the Draft 2026 REZ S5 wind trace.
    s = load_trace(DATA_PATH, "wind", "S5_WH_Northern_SA", refyear=5000)
    assert len(s) == 17520
    assert s.min() >= 0.0
    assert s.max() <= 1.0


def test_load_solar_site():
    s = load_trace(DATA_PATH, "solar", "REZ_S5_Northern_SA_SAT", refyear=5000)
    assert len(s) == 17520
    assert s.min() >= 0.0
    assert s.max() <= 1.0


def test_to_hourly():
    s = load_trace(DATA_PATH, "wind", "S5_WH_Northern_SA", refyear=5000)
    hourly = to_hourly(s, how="mean")
    assert len(hourly) == 8760
