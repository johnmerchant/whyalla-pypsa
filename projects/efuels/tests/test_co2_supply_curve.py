"""Tests for the CO2 supply curve (co2_supply.py)."""
import pytest

from co2_supply import build_co2_supply_curve, blended_co2_price


def test_supply_curve_2030_includes_steelworks():
    """Steelworks is available in 2030 (window 2028–2035)."""
    curve = build_co2_supply_curve(2030)
    names = [d["_tranche_name"] for d in curve]
    assert "co2_steelworks" in names


def test_steelworks_co2_tapers_with_h2_fraction():
    """Steelworks CO2 should decline as shaft H₂ fraction rises (dri-eaf path)."""
    curve_2030 = {d["_tranche_name"]: d for d in build_co2_supply_curve(2030)}
    curve_2040 = {d["_tranche_name"]: d for d in build_co2_supply_curve(2040)}
    # Present in both years, no hard cut-off.
    assert "co2_steelworks" in curve_2030
    assert "co2_steelworks" in curve_2040
    # 2040 availability (~0.24 Mt/y at 88% H2) < 2030 (~0.56 Mt/y at 72% H2).
    assert curve_2040["co2_steelworks"]["p_nom"] < curve_2030["co2_steelworks"]["p_nom"]


def test_supply_curve_dac_price_declines():
    """DAC price in 2040 should be lower than in 2030."""
    curve_2030 = {d["_tranche_name"]: d for d in build_co2_supply_curve(2030)}
    curve_2040 = {d["_tranche_name"]: d for d in build_co2_supply_curve(2040)}
    assert curve_2040["co2_dac"]["marginal_cost"] < curve_2030["co2_dac"]["marginal_cost"]


def test_blended_co2_price_2030_near_195():
    """2030 blended price with default RESEARCH.md weights ≈ AUD 195/t."""
    price = blended_co2_price(2030)
    assert 150 < price < 250, f"Expected ~190–200 AUD/t, got {price:.1f}"
