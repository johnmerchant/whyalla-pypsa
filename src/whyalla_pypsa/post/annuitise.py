"""Capital recovery factor and simple annuitisation."""

from __future__ import annotations


def crf(wacc: float, lifetime: int) -> float:
    """Capital recovery factor. Degenerates to 1/lifetime when wacc == 0."""
    if wacc > 0:
        return wacc / (1 - (1 + wacc) ** -lifetime)
    return 1.0 / lifetime


def annuitise(capex_total: float, wacc: float, lifetime: int) -> float:
    """Annualised capex = total capex × CRF(wacc, lifetime)."""
    return capex_total * crf(wacc, lifetime)
