"""Biofuels submodule for the Whyalla e-fuels network.

Adds three liquid-fuel pathways that compete with (and complement) the
existing electro-methanol → upgrading route in ``process_chain.py``:

    A) Marine microalgae → HTL biocrude → drop-in diesel + jet + naphtha
    B) Halophyte oil (Salicornia) → HEFA jet + diesel
    C) Lignocellulose (mallee + saltbush) → pyrolysis bio-oil OR
       gasification → biogenic H₂ + CO₂ (feeds the existing MeOH synth)

Two waste streams are modelled:
    • Northern Water desal brine — treated as free (disposal to Spencer
      Gulf is the counterfactual).
    • DRI-EAF off-gas waste heat — bounded free source on ``heat_duty``
      bus. See ``waste_streams.DRI_WASTE_HEAT_MWH_PER_YEAR``.

Topology: pathways write into the *existing* product buses
(diesel_bus, kero_bus, naphtha_bus) and into the existing h2_bus / co2
bus where applicable, so the optimiser trades e-fuel vs biofuel per
product in one LP.

Entry point: ``attach_biofuels(n, ...)``.
"""
from __future__ import annotations

from .attach import attach_biofuels

__all__ = ["attach_biofuels"]
