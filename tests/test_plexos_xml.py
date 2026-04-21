"""Tests for the PLEXOS XML interconnector flow parser.

The tests skip cleanly when the ISP XML file is not present on disk.
Run with the default Step Change scenario file at:
  ~/Downloads/Draft 2026 ISP/Draft 2026 ISP Model/
    Draft 2026 ISP Step Change/Draft 2026 ISP Step Change Model.xml
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from whyalla_pypsa.data.plexos_xml import FlowStage, list_interconnectors, load_interconnector_flows

# ---------------------------------------------------------------------------
# Fixture — resolves the XML path and skips if absent.
# ---------------------------------------------------------------------------

_DEFAULT_XML = (
    Path.home()
    / "Downloads"
    / "Draft 2026 ISP"
    / "Draft 2026 ISP Model"
    / "Draft 2026 ISP Step Change"
    / "Draft 2026 ISP Step Change Model.xml"
)


@pytest.fixture(scope="module")
def xml_path() -> Path:
    if not _DEFAULT_XML.exists():
        pytest.skip(
            f"ISP XML not found at {_DEFAULT_XML}. "
            "Place the AEMO Draft 2026 ISP files under ~/Downloads to run these tests."
        )
    return _DEFAULT_XML


# ---------------------------------------------------------------------------
# list_interconnectors
# ---------------------------------------------------------------------------


def test_list_interconnectors_non_empty(xml_path: Path):
    names = list_interconnectors(xml_path)
    assert len(names) > 5, f"Expected >5 interconnectors, got {len(names)}"


def test_list_interconnectors_includes_sa_heywood(xml_path: Path):
    names = list_interconnectors(xml_path)
    lower = [n.lower() for n in names]
    assert any("sa" in n or "south australia" in n for n in lower), (
        f"No SA/Heywood interconnector found. Names: {names}"
    )


# ---------------------------------------------------------------------------
# EnergyConnect (PEC / NSW-SA link) — staged Max Flow
# ---------------------------------------------------------------------------

# PEC canonical name discovered via list_interconnectors exploration.
_PEC_NAME = "EnergyConnect"


def test_energyconnect_max_flow_has_800mw_stage(xml_path: Path):
    """Exactly one deduplicated stage should be 800 MW from 2027-11-30."""
    stages = load_interconnector_flows(xml_path, _PEC_NAME, "Max Flow")
    assert len(stages) >= 1, "Expected at least one flow stage"

    matching = [s for s in stages if s.value == 800.0 and s.date_from == date(2027, 11, 30)]
    assert len(matching) == 1, (
        f"Expected exactly one 800 MW stage dated 2027-11-30; got {matching}. "
        f"Full stages: {stages}"
    )


def test_energyconnect_max_flow_has_150mw_baseline(xml_path: Path):
    """There should be a baseline (None-dated) stage at 150 MW."""
    stages = load_interconnector_flows(xml_path, _PEC_NAME, "Max Flow")
    baseline = [s for s in stages if s.date_from is None and s.value == 150.0]
    assert len(baseline) >= 1, (
        f"Expected a 150 MW baseline (date_from=None); got stages: {stages}"
    )


def test_energyconnect_max_flow_sorted(xml_path: Path):
    """None-dated stage must come first; subsequent stages in ascending date order."""
    stages = load_interconnector_flows(xml_path, _PEC_NAME, "Max Flow")
    assert stages[0].date_from is None, "First stage should be the baseline (date_from=None)"
    dated = [s for s in stages if s.date_from is not None]
    assert dated == sorted(dated, key=lambda s: s.date_from), "Dated stages not in ascending order"


# ---------------------------------------------------------------------------
# Heywood (V-SA, SA-VIC link) — baseline 650 MW, upgrade to 750 MW on PEC date
# ---------------------------------------------------------------------------

_HEYWOOD_NAME = "V-SA"


def test_heywood_max_flow_baseline_650(xml_path: Path):
    """Heywood baseline Max Flow is 650 MW (pre-PEC)."""
    stages = load_interconnector_flows(xml_path, _HEYWOOD_NAME, "Max Flow")
    values = {s.value for s in stages}
    assert 650.0 in values, f"Expected 650 MW baseline for Heywood; got {stages}"


def test_heywood_upgrades_on_pec_date(xml_path: Path):
    """Draft 2026 ISP pairs a Heywood upgrade with PEC commissioning on
    2027-11-30 (650 → 750 MW)."""
    from datetime import date as _date

    stages = load_interconnector_flows(xml_path, _HEYWOOD_NAME, "Max Flow")
    upgrade = [s for s in stages if s.date_from == _date(2027, 11, 30)]
    assert len(upgrade) == 1, f"Expected one 2027-11-30 upgrade stage; got {stages}"
    assert upgrade[0].value == pytest.approx(750.0)


# ---------------------------------------------------------------------------
# Negative test
# ---------------------------------------------------------------------------


def test_nonexistent_interconnector_raises(xml_path: Path):
    with pytest.raises(KeyError):
        load_interconnector_flows(xml_path, "Nonexistent", "Max Flow")
