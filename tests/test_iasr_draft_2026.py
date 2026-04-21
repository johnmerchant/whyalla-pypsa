"""Tests for the Draft 2026 IASR workbook reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from whyalla_pypsa.data.iasr_draft_2026 import (
    list_sheets,
    load_fuel_price,
    load_gencost,
)

_IASR_PATH = (
    Path.home()
    / "Downloads"
    / "Draft 2026 ISP"
    / "Draft 2026 ISP Inputs and Assumptions workbook.xlsx"
)


@pytest.fixture(scope="module")
def iasr_path() -> Path:
    if not _IASR_PATH.exists():
        pytest.skip(f"Draft 2026 IASR workbook not found at {_IASR_PATH}")
    return _IASR_PATH


def test_list_sheets_long(iasr_path: Path) -> None:
    names = list_sheets(iasr_path)
    assert len(names) > 50


def test_list_sheets_contains_cost_sheet(iasr_path: Path) -> None:
    names = [n.lower() for n in list_sheets(iasr_path)]
    assert any("cost" in n or "capex" in n or "build" in n for n in names)


def test_load_gencost_wind(iasr_path: Path) -> None:
    row = load_gencost(iasr_path, "Wind")
    assert len(row) > 3
    # Should contain at least one FY column with a numeric value.
    assert any(isinstance(v, (int, float)) for v in row.values())


def test_load_gencost_missing_raises(iasr_path: Path) -> None:
    with pytest.raises(KeyError):
        load_gencost(iasr_path, "Nonexistent-xyz-tech")


def test_load_fuel_price_not_yet_implemented(iasr_path: Path) -> None:
    with pytest.raises(NotImplementedError):
        load_fuel_price(iasr_path, "gas", 2030)
