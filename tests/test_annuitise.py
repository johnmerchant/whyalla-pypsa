"""Annuity + toy levelised_cost."""

from __future__ import annotations

import math

import pytest

from whyalla_pypsa.config import ComponentWACC, WACCOverlay
from whyalla_pypsa.post.annuitise import annuitise, crf
from whyalla_pypsa.post.levelised import levelised_cost


def test_crf_hand_computed():
    # CRF(0.07, 25) = 0.07 / (1 - 1.07^-25) ≈ 0.08581
    assert crf(0.07, 25) == pytest.approx(0.0858, abs=1e-3)


def test_crf_zero_wacc():
    assert crf(0.0, 10) == pytest.approx(0.1)


def test_annuitise_matches_crf():
    assert annuitise(1_000_000.0, 0.07, 25) == pytest.approx(1_000_000.0 * crf(0.07, 25))


class _FakeDF:
    def __init__(self, data: dict[str, float], col: str):
        self._data = data
        self._col = col

    @property
    def index(self):
        return list(self._data.keys())

    def __contains__(self, key):
        return key in self._data

    class _Loc:
        def __init__(self, parent):
            self._parent = parent

        def __getitem__(self, key):
            name, col = key
            assert col == self._parent._col
            return self._parent._data[name]

    @property
    def at(self):
        return _FakeDF._Loc(self)


class _FakeNetwork:
    """Minimal network stub for levelised_cost — just generators with p_nom_opt."""

    def __init__(self, sizes: dict[str, float]):
        self.generators = _FakeDF(sizes, "p_nom_opt")
        self.links = _FakeDF({}, "p_nom_opt")
        self.stores = _FakeDF({}, "e_nom_opt")
        self.storage_units = _FakeDF({}, "p_nom_opt")


def test_levelised_cost_toy():
    overlay = WACCOverlay(
        wind=ComponentWACC(0.06, 25),
        solar=ComponentWACC(0.06, 25),
    )
    net = _FakeNetwork({"wind": 100.0, "solar": 50.0})  # MW

    result = levelised_cost(
        net,
        overlay,
        component_capex_per_unit={"wind": 2_000_000.0, "solar": 1_300_000.0},
        component_overlay_key={"wind": "wind", "solar": "solar"},
        annual_product=500_000.0,  # MWh
    )

    # 100 MW × 2 M AUD/MW × CRF(0.06, 25)
    expected_wind = 100.0 * 2_000_000.0 * crf(0.06, 25)
    expected_solar = 50.0 * 1_300_000.0 * crf(0.06, 25)
    assert result["per_component"]["wind"]["capex_annuity"] == pytest.approx(
        expected_wind
    )
    assert result["per_component"]["solar"]["capex_annuity"] == pytest.approx(
        expected_solar
    )
    assert result["total_capex_annuity"] == pytest.approx(
        expected_wind + expected_solar
    )
    assert math.isfinite(result["lcx_per_unit"])
