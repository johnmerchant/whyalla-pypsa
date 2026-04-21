"""Nominal Whyalla-area site -> REZ mapping.

Used to route a configured `representative_site` to a Draft 2026 REZ code.
Extend as needed when new sites are added to FacilityConfig.
"""

from __future__ import annotations


SITE_TO_REZ: dict[str, str] = {
    # REZ S5 — Northern SA (Whyalla / Port Augusta area).
    "S5_WH_Northern_SA": "S5",
    "S5_WM_Northern_SA": "S5",
    "REZ_S5_Northern_SA_SAT": "S5",
    "REZ_S5_Northern_SA_CST": "S5",
    "Port_Augusta_FFP": "S5",
    # REZ S4 — Yorke Peninsula.
    "S4_WH_Yorke_Peninsula": "S4",
    "S4_WM_Yorke_Peninsula": "S4",
    "REZ_S4_Yorke_Peninsula_SAT": "S4",
    "REZ_S4_Yorke_Peninsula_CST": "S4",
    # REZ S6 — Roxby Downs.
    "S6_WH_Roxby_Downs": "S6",
    "S6_WM_Roxby_Downs": "S6",
    # Commonly-referenced plant-level wind sites in SA.
    "LKBONNY1": "S3",
    "LKBONNY2": "S3",
    "LKBONNY3": "S3",
    "PORTWF": "S5",
}


def rez_for_site(site: str) -> str | None:
    """Return REZ code for a site, or None if unknown."""
    return SITE_TO_REZ.get(site)
