"""Shared process-heat bus for e-fuels and biofuels pathways.

Creates a single ``process_heat_duty`` bus that carries MWh_thermal flow
between heat suppliers and heat consumers:

Suppliers (positive efficiency or p_nom generator):
    • ``dri_waste_heat`` — free, fixed 200 GWh_th/yr from EAF off-gas
      (see waste_streams.py rationale).
    • ``electric_heater`` — extendable AC → heat Link at 0.97 efficiency.

Consumers (negative efficiency on their bus slot):
    • ``refinery_{product}`` — 0.8 MWh_th / t product (net external heat
      after internal MeOH-synth exothermic recovery + product-cooling
      credit; covers MTO+MOGD+hydrocracker sequence or FT+HCR in the
      hydrocracked_ft mode).
    • ``htl_upgrading`` (biofuels) — 1.39 MWh_th / t dry algae (350°C
      reactor, high-grade).

Heat-grade caveat: all heat is pooled on a single bus, so low-grade
steam (140-180°C from MeOH synth) can in principle drive high-grade
users (HTL at 350°C, hydrocracker at 300-400°C). For this reason we
*net off* MeOH synth recovery inside the refinery heat draw (0.8 is a
net-external value, not gross) rather than crediting it as a separate
supply. DRI waste heat is high-grade (EAF off-gas ~800°C) and can serve
any consumer without grade-mismatch issues.

Rename from the earlier ``biofuels_heat_duty`` bus: the heat integration
is not biofuels-specific.
"""
from __future__ import annotations

import pypsa

from whyalla_pypsa import crf


# ── Geographic heat-bus split ─────────────────────────────────────────────
# Whyalla Steelworks (DRI-EAF site) and Port Bonython (e-fuels + refinery
# site) are ~15-20 km apart. A 300-800°C heat pipeline at that distance is
# economically infeasible (3-5%/km loss + large insulated-pipe capex), so
# the two sites cannot share a heat bus.
#
# Port Bonython bus — refineries + CST solar field + electric heater +
# H₂ burner + any biofuels pathway colocated here (HEFA, pyrolysis,
# gasification — they don't need steelworks heat).
PROCESS_HEAT_DUTY_BUS = "process_heat_duty"

# Whyalla Steelworks bus — DRI-EAF off-gas waste heat (free) + any
# biofuels pathway that pays to colocate at the steelworks to tap it.
# The HTL (algae → biocrude) pathway is the only default tenant: HTL
# needs high-grade heat AND biogenic CO₂, and the steelworks has both
# onsite (no CO₂ pipeline, no heat pipeline).
STEELWORKS_HEAT_DUTY_BUS = "steelworks_heat_duty"

# Refinery net external heat intensity (after MeOH synth exothermic
# recovery and product-cooling credit). Central 0.8 MWh_th / t product
# covers MTO+MOGD+hydrocracker and FT+hydrocracker slates; plausible
# band 0.5–1.3.
REFINERY_HEAT_MWH_PER_T_PRODUCT = 0.8

# DRI-EAF off-gas waste heat recoverable to the e-fuels site. Fixed
# bound: 1 Mt_steel/yr × 0.20 MWh_th/t (dri-eaf constant). To be refined
# once dri-eaf trajectory.csv stabilises.
DRI_WASTE_HEAT_MWH_PER_YEAR = 200_000.0

# ── Heat supplier options (mirrors dri-eaf/process_chain.py) ─────────────
# Values deliberately aligned with dri-eaf so a future whole-site LP can
# treat heat as a single shared bus with consistent supplier economics.
#
# Electric resistance heater (ceramic / Kanthal elements at refinery-grade
# 300-400°C): high efficiency, high capex. Wins when running many hours
# with cheap electricity.
ELECTRIC_HEATER_CAPEX_PER_KW_TH = 400.0        # dri-eaf: same
ELECTRIC_HEATER_EFFICIENCY = 0.97              # dri-eaf: same
ELECTRIC_HEATER_LIFETIME_YEARS = 20            # dri-eaf: same

# H₂ combustion burner (drop-in on existing burner housings; oxy-H₂ or
# air-H₂): low capex, ~1.6× worse electric-to-heat efficiency end-to-end
# via electrolyser losses. Wins for part-time operation where capex
# amortisation dominates.
H2_BURNER_CAPEX_PER_KW_TH = 30.0               # dri-eaf: same
H2_BURNER_EFFICIENCY = 0.85                    # dri-eaf: same (MWh_th/MWh_H2)
H2_BURNER_LIFETIME_YEARS = 20                  # dri-eaf: same

# ── Concentrated solar thermal (CST) with bundled molten-salt storage ────
# Power-tower with central receiver + heliostat field + molten-salt HTF.
# Whyalla at 32°S has world-class DNI (~2400 kWh/m²/yr, comparable to
# southern Spain + better than Port Augusta's proposed Aurora site).
#
# Dispatch profile: AEMO Draft 2026 ISP publishes a dedicated
# ``REZ_S5_Northern_SA_CST`` trace (mean CF ~0.51) representing a
# reference CST plant configuration with integrated ~8h molten-salt
# storage. We use that trace directly as ``p_max_pu`` — it already
# bakes in the thermal-storage dispatch shape, so we do NOT add a
# separate molten-salt Store (would double-count).
#
# Capex anchor: Port Augusta Aurora proposal (SolarReserve, cancelled
# 2019) — A$650M for 150 MW_th with 8h storage → A$4,330/kW_th all-in.
# Central figure: A$4,300/kW_th (field + tower + receiver + salt + tanks).
CST_CAPEX_PER_KW_TH = 4_300.0
CST_LIFETIME_YEARS = 30
# PV-derate fallback if the AEMO CST trace is unavailable (diffuse-fraction
# loss × field-cosine × receiver-thermal ≈ 0.65 on top of a GHI PV profile).
# Results in mean CF ~0.19 vs AEMO's published 0.51 — under-values CST
# materially. Pass an AEMO CST trace via ``cst_profile`` whenever possible.
CST_DNI_DERATE_VS_PV = 0.65
# AEMO REZ trace name for the CST profile (Draft 2026 ISP).
CST_AEMO_TRACE_SITE = "REZ_S5_Northern_SA_CST"

# Rankine steam turbine + generator: optional Link from process_heat_duty
# → facility_ac. Lets the LP route CST/molten-salt heat into electricity
# (competes with PV/wind to supply the AC bus). Mature off-the-shelf
# equipment at the 30-200 MW scale (fossil-class steam turbines repurposed
# for molten-salt CST).
#   Capex: A$1,800-2,500/kW_el (NREL SAM 2024, GE/Siemens reference)
#   Efficiency 565°C molten salt source → gross electric: 38-42% LHV.
#     Central 0.40; parasitics (aux cooling, pumps) ~5% of gross → net 0.38.
STEAM_TURBINE_CAPEX_PER_KW_EL = 2_000.0
STEAM_TURBINE_EFFICIENCY = 0.38                # net heat → electric
STEAM_TURBINE_LIFETIME_YEARS = 30

HOURS_PER_YEAR = 8760


def load_aemo_cst_profile(
    n: pypsa.Network,
    cfg,
    *,
    site: str = CST_AEMO_TRACE_SITE,
) -> "pd.Series":
    """Load the AEMO CST trace aligned to the network's snapshots.

    Reads REZ_S5_Northern_SA_CST (or override via *site*) from the Draft
    2026 ISP solar-traces folder using the same refyear and model_year as
    the solar PV trace already on ``n``. Reindexes to ``n.snapshots`` so
    representative-week slicing and resolution resampling match.

    Returns a pd.Series of hourly capacity factors (0-1) indexed by
    ``n.snapshots``. Raises FileNotFoundError if the trace isn't found.
    """
    import pandas as pd
    from whyalla_pypsa.data.aemo_draft_2026 import load_trace

    refyear = getattr(cfg.scenario, "reference_year", 5000)
    model_year = cfg.scenario.model_year
    cst_full = load_trace(cfg.data_path, "solar", site,
                           refyear=refyear, model_year=model_year)
    # Match the facility network's resolution + snapshot selection by
    # reindexing onto n.snapshots (the facility loader has already done
    # both of those reshaping steps).
    return cst_full.reindex(n.snapshots).astype(float).clip(0.0, 1.0)


def attach_process_heat_duty(
    n: pypsa.Network,
    *,
    wacc: float,
    ac_bus: str = "facility_ac",
    h2_bus: str = "facility_h2",
    waste_heat_mwh_per_year: float = DRI_WASTE_HEAT_MWH_PER_YEAR,
    electric_heater_capex_per_kw_th: float = ELECTRIC_HEATER_CAPEX_PER_KW_TH,
    electric_heater_lifetime_years: int = ELECTRIC_HEATER_LIFETIME_YEARS,
    electric_heater_efficiency: float = ELECTRIC_HEATER_EFFICIENCY,
    h2_burner_capex_per_kw_th: float = H2_BURNER_CAPEX_PER_KW_TH,
    h2_burner_lifetime_years: int = H2_BURNER_LIFETIME_YEARS,
    h2_burner_efficiency: float = H2_BURNER_EFFICIENCY,
    enable_cst: bool = True,
    cst_capex_per_kw_th: float = CST_CAPEX_PER_KW_TH,
    cst_lifetime_years: int = CST_LIFETIME_YEARS,
    cst_profile=None,  # pd.Series | None — AEMO CST trace aligned to snapshots
    cst_dni_derate: float = CST_DNI_DERATE_VS_PV,
    enable_steam_turbine: bool = True,
    steam_turbine_capex_per_kw_el: float = STEAM_TURBINE_CAPEX_PER_KW_EL,
    steam_turbine_efficiency: float = STEAM_TURBINE_EFFICIENCY,
    steam_turbine_lifetime_years: int = STEAM_TURBINE_LIFETIME_YEARS,
    cst_wacc: float | None = None,
    hours_per_year: float = HOURS_PER_YEAR,
) -> None:
    """Attach process_heat_duty bus + free DRI waste heat + heater suppliers.

    Two heater suppliers compete in merit order (mirrors dri-eaf):
      • ``electric_heater`` (ac_bus → heat, 0.97 eff, A$400/kW_th) — wins
        on running cost when cheap electricity is abundant.
      • ``h2_burner``       (h2_bus → heat, 0.85 eff, A$30/kW_th) — wins
        on capex for peaking / part-time operation.

    Idempotent: safe to call multiple times (e.g., if both attach_efuels
    and attach_biofuels invoke it in the same network build).
    """
    if "heat" not in n.carriers.index:
        n.add("Carrier", "heat")

    # Port Bonython heat bus — refineries, CST, heaters, most biofuels.
    if PROCESS_HEAT_DUTY_BUS not in n.buses.index:
        n.add("Bus", PROCESS_HEAT_DUTY_BUS, carrier="heat")

    # Whyalla Steelworks heat bus — hosts DRI waste heat + colocated HTL.
    # Geographically separate from Port Bonython (no 15 km heat pipeline).
    if STEELWORKS_HEAT_DUTY_BUS not in n.buses.index:
        n.add("Bus", STEELWORKS_HEAT_DUTY_BUS, carrier="heat")

    # Free DRI waste heat lives ONLY on the steelworks bus. Unused waste
    # heat is discarded (no credit) unless an onsite consumer is built.
    waste_heat_p_nom = waste_heat_mwh_per_year / hours_per_year
    if "dri_waste_heat" not in n.generators.index:
        n.add("Generator", "dri_waste_heat",
              bus=STEELWORKS_HEAT_DUTY_BUS,
              carrier="heat",
              p_nom=waste_heat_p_nom,
              marginal_cost=0.0)

    # Electric resistance heater — AC → heat (high eff, high capex).
    heater_capital = (
        electric_heater_capex_per_kw_th * 1_000
        * crf(wacc, electric_heater_lifetime_years)
    )
    if "electric_heater" not in n.links.index:
        n.add("Link", "electric_heater",
              bus0=ac_bus,
              bus1=PROCESS_HEAT_DUTY_BUS,
              efficiency=electric_heater_efficiency,
              p_nom_extendable=True,
              capital_cost=heater_capital,
              marginal_cost=0.0)

    # H₂ combustion burner — H₂ → heat (lower eff but drop-in-cheap capex).
    # Flow variable p at bus0 is MWh H₂ consumed; efficiency is MWh_th/MWh_H2.
    burner_capital = (
        h2_burner_capex_per_kw_th * 1_000
        * crf(wacc, h2_burner_lifetime_years)
    )
    if "h2_burner" not in n.links.index:
        n.add("Link", "h2_burner",
              bus0=h2_bus,
              bus1=PROCESS_HEAT_DUTY_BUS,
              efficiency=h2_burner_efficiency,
              p_nom_extendable=True,
              capital_cost=burner_capital,
              marginal_cost=0.0)

    # ── Concentrated solar thermal (CST) + molten salt storage ───────────
    # CST financed at the renewables WACC (PPA-backed, lower risk) — not
    # the process-side scenario WACC. Caller can override via cst_wacc.
    if enable_cst and "cst_solar_thermal" not in n.generators.index:
        cst_w = cst_wacc if cst_wacc is not None else wacc
        cst_capital = (
            cst_capex_per_kw_th * 1_000 * crf(cst_w, cst_lifetime_years)
        )
        # Prefer the AEMO REZ_S5_Northern_SA_CST ISP trace (passed by the
        # caller, mean CF ~0.51 with bundled ~8h salt storage dispatch).
        # Fall back to a DNI-derated PV profile when the trace isn't
        # available — noisier but keeps the smoke runnable.
        if cst_profile is None:
            if ("solar" in n.generators.index
                    and "solar" in n.generators_t.p_max_pu.columns):
                cst_profile = n.generators_t.p_max_pu["solar"] * cst_dni_derate
            else:
                import pandas as pd
                cst_profile = pd.Series(0.28 * cst_dni_derate,
                                        index=n.snapshots)
        else:
            # Normalise whatever the caller passed (pd.Series / ndarray)
            # to the network's snapshot index.
            import pandas as pd
            if not isinstance(cst_profile, pd.Series):
                cst_profile = pd.Series(cst_profile, index=n.snapshots)
            else:
                cst_profile = cst_profile.reindex(n.snapshots)
        n.add("Generator", "cst_solar_thermal",
              bus=PROCESS_HEAT_DUTY_BUS,
              carrier="heat",
              p_nom_extendable=True,
              p_max_pu=cst_profile.clip(0, 1).values,
              capital_cost=cst_capital,
              marginal_cost=0.0)

        # NOTE: no separate molten_salt_store — the AEMO CST trace already
        # represents a bundled tower + receiver + ~8h salt-storage
        # dispatch profile. Adding an independent Store would double-count.

        # Optional Rankine steam turbine — routes CST heat to AC bus as
        # dispatchable electricity. Competes with PV/wind on a
        # capex-per-kW-el basis plus the thermal efficiency penalty.
        if enable_steam_turbine and "cst_steam_turbine" not in n.links.index:
            st_capital = (
                steam_turbine_capex_per_kw_el * 1_000
                * crf(cst_w, steam_turbine_lifetime_years)
            )
            n.add("Link", "cst_steam_turbine",
                  bus0=PROCESS_HEAT_DUTY_BUS,
                  bus1=ac_bus,
                  efficiency=steam_turbine_efficiency,
                  p_nom_extendable=True,
                  capital_cost=st_capital,
                  marginal_cost=0.0)
