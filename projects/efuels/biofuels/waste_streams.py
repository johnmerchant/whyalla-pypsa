"""Biofuels-side view of the shared process-heat bus.

The bus itself (``process_heat_duty``), the free DRI waste-heat generator,
and the extendable electric heater are now created inside
``heat_integration.attach_process_heat_duty``, which ``attach_efuels``
calls early in the network build. Biofuels pathways simply *connect* to
that existing bus.

This module re-exports the shared constants so biofuel pathways can keep
importing from ``biofuels.waste_streams`` without a second rename pass.
The ``attach_heat_duty_bus`` helper used by the old biofuels-only code
still works (it forwards to the shared helper and is idempotent).

Brine: no bus is created. Brine-irrigated pathways (HTL pond intake,
halophyte cultivation, mallee/saltbush establishment) draw free input
because discharge to Spencer Gulf via NW's outfall is the counterfactual.
See ``physics.BRINE_CREDIT_AUD_PER_KL``.
"""
from __future__ import annotations

import pypsa

from heat_integration import (
    PROCESS_HEAT_DUTY_BUS,
    DRI_WASTE_HEAT_MWH_PER_YEAR,
    HOURS_PER_YEAR,
    attach_process_heat_duty,
)


def attach_heat_duty_bus(
    n: pypsa.Network,
    *,
    wacc: float = 0.11,
    waste_heat_mwh_per_year: float = DRI_WASTE_HEAT_MWH_PER_YEAR,
    heat_duty_bus: str = PROCESS_HEAT_DUTY_BUS,
) -> None:
    """Forward to heat_integration.attach_process_heat_duty (idempotent).

    Kept for backwards compatibility with earlier biofuels-only callers.
    """
    if heat_duty_bus != PROCESS_HEAT_DUTY_BUS:
        raise ValueError(
            f"Custom bus name {heat_duty_bus!r} no longer supported; "
            "use heat_integration.PROCESS_HEAT_DUTY_BUS directly."
        )
    attach_process_heat_duty(
        n, wacc=wacc, waste_heat_mwh_per_year=waste_heat_mwh_per_year,
    )
