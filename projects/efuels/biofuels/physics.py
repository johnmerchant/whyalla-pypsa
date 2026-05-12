"""Biofuels pathway constants: yields, conversion efficiencies, capex bands.

Every default below is documented with its provenance and a plausible
uncertainty band. Values are central-estimate defaults — callers override
via ``attach_biofuels`` kwargs or via sensitivity sweeps in
``chart_biofuels_sensitivity.py``.

All mass flows in tonnes; energy in MWh (LHV); currency in AUD (2024 real).
"""
from __future__ import annotations


# ═══════════════════════════════════════════════════════════════════════
# A) MARINE MICROALGAE → HTL → DROP-IN FUELS
# ═══════════════════════════════════════════════════════════════════════
# Anchor: Muradel Whyalla demonstration (2014-2019, Tetraselmis spp.,
# A$10.7M for 30 kL/yr target, A$1/L stretch goal never achieved — pilot
# was ~A$9.90/L on commissioning). Productivity and yields reflect a
# successor commercial-scale open-pond facility, NOT the pilot.

# Areal productivity of open-pond marine algae at Point Lowly latitude
# (32°S, ~2800 kWh/m²/yr GHI): 15-25 g/m²/day is the defensible band for
# Tetraselmis / Nannochloropsis in seawater or dilute brine (NREL ATP3
# 2017 outdoor ATP3 ponds; Muradel Whyalla 2014-19 pilot reported
# 10-22 g/m²/day). Central = 20.
ALGAE_PRODUCTIVITY_G_PER_M2_DAY = 20.0
ALGAE_PRODUCTIVITY_LOW  = 15.0
ALGAE_PRODUCTIVITY_HIGH = 25.0
# Derived: 20 g/m²/day × 365 × 10 (m²/ha×10⁻³) = 73 t_dry_algae/ha/yr
ALGAE_T_DRY_PER_HA_YR = ALGAE_PRODUCTIVITY_G_PER_M2_DAY * 365 * 10 / 1000.0

# HTL (hydrothermal liquefaction, 300-370°C, 20-25 MPa, ~30 min residence):
# biocrude yield per t dry algae. PNNL NWL-25464 and Jazrawi 2013 Muradel
# pilot converge on 0.30-0.40 t biocrude / t dry; central 0.35.
HTL_BIOCRUDE_YIELD_T_PER_T_DRY = 0.35

# Hydrotreating / upgrading: biocrude → drop-in fuels. Typical 0.85-0.95
# mass yield (water + light gas losses); central 0.90.
HTL_UPGRADING_YIELD_T_PER_T_BIOCRUDE = 0.90

# Net pathway: ~0.315 t finished fuel / t dry algae.
HTL_FUEL_T_PER_T_DRY = (
    HTL_BIOCRUDE_YIELD_T_PER_T_DRY * HTL_UPGRADING_YIELD_T_PER_T_BIOCRUDE
)

# Product slate (PNNL hydrocarbon-range distribution for hydroprocessed HTL
# biocrude; ~10% light naphtha, 60% distillate, 30% jet cut).
HTL_PRODUCT_FRACS = {"diesel": 0.60, "kero": 0.30, "naphtha": 0.10}
# (Wax is absent from HTL upgrading — cracking takes C21+ fractions into
# lighter distillate range.)

# H₂ consumption in HTL-oil hydrotreating: 4-5 wt% of biocrude
# (PNNL 2014 HTL hydrotreater data). Central 0.045.
HTL_H2_T_PER_T_BIOCRUDE = 0.045
HTL_H2_T_PER_T_DRY = HTL_H2_T_PER_T_BIOCRUDE * HTL_BIOCRUDE_YIELD_T_PER_T_DRY

# Aux electricity: dewatering dominates (filter press / centrifuge) plus
# HTL pumping + upgrading compression. ~3 MWh / t biocrude typical.
HTL_ELEC_MWH_PER_T_BIOCRUDE = 3.0
HTL_ELEC_MWH_PER_T_DRY = HTL_ELEC_MWH_PER_T_BIOCRUDE * HTL_BIOCRUDE_YIELD_T_PER_T_DRY

# Process heat: ~5 GJ/t dry algae for HTL reactor heat-up at 350°C. This
# is the single largest thermal draw — and the key link to DRI waste
# heat. Central 1.39 MWh_th / t dry.
HTL_HEAT_MWH_PER_T_DRY = 5.0 * 1000.0 / 3600.0  # GJ→MWh

# Capex: NREL ATP3 TEA (2014, updated 2019) gives US$8-15/gal finished
# fuel at scale, ~70% attributable to capex. Muradel target was A$1/L
# (~A$1,300/t fuel from capex+opex combined). Defensible central for a
# commercial-scale integrated facility: A$30,000 / (t fuel / yr) all-in.
# Expressed per t-dry-biomass-feedstock capacity:
#   A$30,000 / 0.315 = A$95,238 / (t_dry / yr)
# Round to A$95,000 for documentation clarity.
HTL_CAPEX_PER_T_DRY_YR = 95_000.0   # AUD / (t dry algae / yr)
HTL_OPEX_PER_T_DRY = 120.0          # AUD / t dry algae (fertiliser, labour, CO₂ supplementation)
HTL_LIFETIME_YEARS = 20

# Land availability for open-pond cultivation. Two candidate sites with
# different trade-offs:
#
#   • Steelworks-adjacent: small (~150-300 ha plausible on industrial-
#     zoned land close enough to pipe flue CO₂ + waste heat, ≤2 km from
#     the EAF). Land is the binding constraint, but steelworks heat and
#     CO₂ are free-onsite.
#   • Port Bonython / Cultana coastal flats: larger (~500-1000 ha of
#     coastal saline flats with seawater + brine access). No free heat
#     credit — heat draw competes with the refineries for electric
#     heater / CST / H₂ burner on the Port Bonython bus.
#
# Central defaults below — the optimiser picks per-site based on the
# trade-off between free heat (steelworks) and scale (Port Bonython).
HTL_DEFAULT_STEELWORKS_POND_AREA_HA = 250.0
HTL_DEFAULT_PORT_BONYTHON_POND_AREA_HA = 500.0
# Backwards-compat alias (callers passing the single-site kwarg still work;
# treated as the steelworks area for site="steelworks", else Port Bonython).
HTL_DEFAULT_POND_AREA_HA = 500.0


# ═══════════════════════════════════════════════════════════════════════
# B) HALOPHYTE OILSEED → HEFA
# ═══════════════════════════════════════════════════════════════════════
# Anchor: Etihad/Masdar SBRC Seawater Energy and Agriculture System (SEAS,
# UAE). Salicornia bigelovii field trials 2016-2022. Commercial-scale yield
# data is research-grade.

# Salicornia seed oil yield: SBRC UAE demonstration reported ~2 t/ha/yr
# in optimal conditions; commercial de-rating to 1.0-1.5 t/ha/yr at
# Whyalla-scale saline land. Central 1.2.
HALOPHYTE_OIL_T_PER_HA_YR = 1.2
HALOPHYTE_OIL_LOW  = 0.8
HALOPHYTE_OIL_HIGH = 1.8

# HEFA conversion (UOP/Honeywell Ecofining, Neste NEXBTL): 0.82-0.88 t
# fuel / t oil. Central 0.85.
HEFA_FUEL_T_PER_T_OIL = 0.85

# Product slate: HEFA is heavily jet-biased (UOP process tuning). Typical
# 70% kero / 25% diesel / 5% naphtha (UOP Honeywell HEFA-SPK data).
HEFA_PRODUCT_FRACS = {"kero": 0.70, "diesel": 0.25, "naphtha": 0.05}

# H₂ consumption: hydrotreating deoxygenates triglycerides (~11 wt% O₂
# removed) plus hydrocracking. Central 0.045 t H₂ / t oil.
HEFA_H2_T_PER_T_OIL = 0.045

# Aux electricity bundled into opex (small contribution, ~0.3 MWh/t oil at
# ~A$120/MWh PPA → ~A$36/t oil → folded into opex).
HEFA_CAPEX_PER_T_OIL_YR = 3_500.0   # AUD / (t oil / yr) — HEFA plant + harvesting
HEFA_OPEX_PER_T_OIL = 280.0         # AUD / t oil (seed, cultivation, aux elec, catalysts)
HEFA_LIFETIME_YEARS = 25

# Land availability: saline flats and marginal coastal land south/west of
# Whyalla. Halophyte cultivation is compatible with Cultana / Cowleds
# Landing / Port Augusta salinised zones. Central 5000 ha; upper 15000 ha.
HALOPHYTE_DEFAULT_AREA_HA = 5_000.0


# ═══════════════════════════════════════════════════════════════════════
# C) LIGNOCELLULOSE → PYROLYSIS OR GASIFICATION
# ═══════════════════════════════════════════════════════════════════════
# Anchor: WA Oil Mallee Project (integrated wood-processing model, CSIRO
# 2009-2017). Species: E. polybractea / E. loxophleba (mallee coppice),
# Atriplex nummularia (old man saltbush).

# Mallee dry biomass yield: coppice on 3-year harvest cycle yields
# 5-15 t_dry/ha/yr at 300-450mm rainfall (WA Oil Mallee data +
# Eyre Peninsula trials). Central 8.
MALLEE_T_DRY_PER_HA_YR = 8.0
MALLEE_YIELD_LOW  = 5.0
MALLEE_YIELD_HIGH = 15.0

# Saltbush dry biomass yield: old man saltbush managed grazing/cut system,
# 3-8 t_dry/ha/yr on saline marginal land. Central 5.
SALTBUSH_T_DRY_PER_HA_YR = 5.0
SALTBUSH_YIELD_LOW  = 3.0
SALTBUSH_YIELD_HIGH = 8.0

# Default land areas (Eyre Peninsula + Mid-North SA marginal/saline land):
# mallee targets arable but rainfall-limited land; saltbush targets saline.
MALLEE_DEFAULT_AREA_HA   = 30_000.0
SALTBUSH_DEFAULT_AREA_HA = 15_000.0

# Biomass LHV (air-dried, 10% moisture): ~18 GJ/t = 5.0 MWh/t.
BIOMASS_LHV_MWH_PER_T = 5.0

# ── Pyrolysis pathway ──────────────────────────────────────────────────
# Fast pyrolysis (500°C, <2s vapour residence): bio-oil yield
# 0.60-0.75 t / t_dry (Ensyn RTP, BTG, VTT). Central 0.65.
PYROLYSIS_BIO_OIL_T_PER_T_DRY = 0.65

# Upgrading: hydrotreating of pyrolysis bio-oil (high O, acidic, thermally
# unstable) — two-stage with HDO catalysts. Mass yield 0.45-0.55 t fuel /
# t bio-oil. Central 0.50.
PYROLYSIS_UPGRADING_YIELD = 0.50
PYROLYSIS_FUEL_T_PER_T_DRY = (
    PYROLYSIS_BIO_OIL_T_PER_T_DRY * PYROLYSIS_UPGRADING_YIELD
)

# Product slate after pyrolysis bio-oil upgrading: fuel is heavier-leaning
# than HTL (higher diesel, more residuals). 60/25/15 diesel/kero/naphtha.
PYROLYSIS_PRODUCT_FRACS = {"diesel": 0.60, "kero": 0.25, "naphtha": 0.15}

# H₂ consumption: bio-oil is ~40 wt% oxygen; hydrotreating removes most.
# Literature 0.05-0.07 t H₂ / t bio-oil; central 0.055.
PYROLYSIS_H2_T_PER_T_BIO_OIL = 0.055
PYROLYSIS_H2_T_PER_T_DRY = (
    PYROLYSIS_H2_T_PER_T_BIO_OIL * PYROLYSIS_BIO_OIL_T_PER_T_DRY
)

# Capex: integrated fast pyrolyser + two-stage upgrader; Shell IH²,
# Ensyn RFO, BTG benchmarks converge ~A$1,800-2,500 / (t_dry / yr).
# Central A$2,000.
PYROLYSIS_CAPEX_PER_T_DRY_YR = 2_000.0
PYROLYSIS_OPEX_PER_T_DRY = 60.0
PYROLYSIS_LIFETIME_YEARS = 25

# ── Gasification + FT-overlap pathway ──────────────────────────────────
# Biomass gasification (fluidised-bed, O₂-blown or air-blown with cleanup):
# cold gas efficiency 70-75% LHV. Syngas is CO + H₂ rich.
# For LP-integration with the existing MeOH synth path (which wants
# CO₂ + 3H₂, not CO + 2H₂), we assume onboard water-gas shift:
#     CO + H₂O → CO₂ + H₂
# This consumes the CO and lifts H₂ yield while producing biogenic CO₂.
# Approximate post-WGS yields per t_dry biomass (CSIRO 2017, NREL PDU):
GASIFICATION_CGE_LHV = 0.72                       # cold gas efficiency
GASIFICATION_H2_T_PER_T_DRY = 0.08                # post-WGS
GASIFICATION_CO2_T_PER_T_DRY = 1.30               # biogenic, to co2 bus
# Aux electricity for gasification plant (O₂ ASU, blowers, cleanup):
# ~0.4 MWh / t_dry; bundled into opex at PPA price.
GASIFICATION_AUX_ELEC_MWH_PER_T_DRY = 0.40

GASIFICATION_CAPEX_PER_T_DRY_YR = 1_500.0
GASIFICATION_OPEX_PER_T_DRY = 50.0
GASIFICATION_LIFETIME_YEARS = 25


# ═══════════════════════════════════════════════════════════════════════
# WASTE-STREAM CREDITS
# ═══════════════════════════════════════════════════════════════════════
# Brine: treated as free (zero marginal cost). Counterfactual is disposal
# to Spencer Gulf via Northern Water's outfall — so biofuel pond intake
# avoids discharge cost. A future refinement could add a small positive
# credit (AUD/kL) if NW tariff structure is disclosed.
BRINE_CREDIT_AUD_PER_KL = 0.0

# Waste heat: see waste_streams.DRI_WASTE_HEAT_MWH_PER_YEAR.
# Marginal cost on the free waste-heat generator is zero (heat would
# otherwise be rejected to atmosphere).


# ═══════════════════════════════════════════════════════════════════════
# PRODUCT LHV (mirrors efuels_physics — duplicated here to keep the
# biofuels submodule self-contained for sensitivity sweeps).
# ═══════════════════════════════════════════════════════════════════════
# Imported from efuels_physics in callers; re-exported for convenience.
