"""Tests for the GGO Cores workbook reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from whyalla_pypsa.data.isp_ggo import ODP_CDP, list_sheets, load_ggo_capacity

_GGO_PATH = (
    Path.home()
    / "Downloads"
    / "Draft 2026 ISP"
    / "Draft 2026 ISP generation and storage outlook"
    / "Cores"
    / "Draft_2026 ISP - Step Change - Core.xlsx"
)


@pytest.fixture(scope="module")
def ggo_path() -> Path:
    if not _GGO_PATH.exists():
        pytest.skip(f"GGO Cores workbook not found at {_GGO_PATH}")
    return _GGO_PATH


def test_list_sheets_contains_expected(ggo_path: Path) -> None:
    names = list_sheets(ggo_path)
    assert "Capacity" in names
    assert "Storage Capacity" in names
    assert "Electrolyzer Capacity" in names


def test_odp_cdp_literal() -> None:
    # Guardrail — this string is load-bearing and a plain 'CDP4' returns zero rows.
    assert ODP_CDP == "CDP4 (ODP)"


def test_csa_utility_scale_storage_fy2030(ggo_path: Path) -> None:
    """Under CDP4 ODP, CSA utility-scale BESS (Deep+Medium+Shallow) at FY2030
    is ~3713 MW (sanity anchor on AEMO's published trajectory)."""
    df = load_ggo_capacity(ggo_path, subregion="CSA", sheet="Storage Capacity")
    utility_scale = df[
        df["technology"].isin(
            ["Deep utility-scale storage", "Medium utility-scale storage", "Shallow utility-scale storage"]
        )
    ]
    fy30 = utility_scale[utility_scale["fy"] == 2030]["capacity_mw"].sum()
    assert fy30 == pytest.approx(3713.0, abs=10.0)


def test_csa_wind_grows(ggo_path: Path) -> None:
    df = load_ggo_capacity(ggo_path, subregion="CSA", technology="Wind")
    assert not df.empty
    fy31 = df[df["fy"] == 2031]["capacity_mw"].iloc[0]
    fy41 = df[df["fy"] == 2041]["capacity_mw"].iloc[0]
    assert fy41 > fy31


def test_csa_electrolyser_small_under_odp(ggo_path: Path) -> None:
    """ODP does NOT assume a large Whyalla electrolyser — per-subregion CSA
    electrolyser capacity stays well under 100 MW across the horizon."""
    df = load_ggo_capacity(ggo_path, subregion="CSA", sheet="Electrolyzer Capacity")
    assert df["capacity_mw"].max() < 100.0


def test_filter_subregion(ggo_path: Path) -> None:
    df = load_ggo_capacity(ggo_path, subregion="CSA")
    assert (df["subregion"] == "CSA").all()


def test_filter_technology(ggo_path: Path) -> None:
    df = load_ggo_capacity(ggo_path, technology="Wind")
    assert (df["technology"] == "Wind").all()


def test_fy_integer_dtype(ggo_path: Path) -> None:
    df = load_ggo_capacity(ggo_path, subregion="CSA")
    assert df["fy"].dtype.kind == "i"
