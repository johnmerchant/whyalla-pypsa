"""Smoke test: 72-hour synthetic-trace facility, HiGHS solve.

Builds a PyPSA network directly (avoids Draft 2026 data dependency) mirroring
the structure of `build_facility_network` and solves with HiGHS.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

pypsa = pytest.importorskip("pypsa")

try:
    import highspy  # noqa: F401

    HAS_HIGHS = True
except Exception:
    HAS_HIGHS = False


@pytest.mark.skipif(not HAS_HIGHS, reason="HiGHS solver not available")
def test_tiny_facility_solves():
    hours = 72
    snaps = pd.date_range("2030-01-01", periods=hours, freq="1h")

    n = pypsa.Network()
    n.set_snapshots(snaps)
    n.add("Carrier", "electricity")
    n.add("Bus", "facility_ac", carrier="electricity")

    # Synthetic CFs: diurnal solar, slowly-varying wind.
    t = np.arange(hours)
    solar_cf = np.clip(np.sin((t % 24) * math.pi / 12.0), 0, 1) * 0.9
    wind_cf = 0.3 + 0.2 * np.sin(t * math.pi / 18.0)

    n.add(
        "Generator",
        "wind",
        bus="facility_ac",
        p_nom_extendable=True,
        p_max_pu=wind_cf,
        capital_cost=100.0,  # tiny for the smoke test
    )
    n.add(
        "Generator",
        "solar",
        bus="facility_ac",
        p_nom_extendable=True,
        p_max_pu=solar_cf,
        capital_cost=80.0,
    )
    # Constant 50 MW load so the problem is non-trivially feasible.
    n.add("Load", "facility_load", bus="facility_ac", p_set=50.0)

    status, _ = n.optimize(solver_name="highs")
    assert status in {"ok", "optimal"}
    assert n.generators.p_nom_opt.sum() > 0
