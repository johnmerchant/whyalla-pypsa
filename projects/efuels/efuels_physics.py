"""Shared physical constants and formulae for the Whyalla e-methanol /
e-fuels model.

Scope: upstream electrolyser → H₂ → methanol synthesis (CO₂ + 3 H₂ →
CH₃OH + H₂O) → optional refinery (methanol-to-gasoline / methanol-to-jet /
methanol-to-olefins / Fischer-Tropsch).  The DRI-EAF steelmaking load
modelled in the sibling `whyalla` repo is *abstracted away* — this model
treats Whyalla as a greenfield e-fuels facility anchored to the SA
Northern REZ.

All energy flows are in MWh (LHV) unless stated otherwise.  Mass flows in
tonnes.
"""

# ── Hydrogen ───────────────────────────────────────────────────────────────
# LHV of H₂: 120 MJ/kg = 33.33 MWh/t
H2_LHV_MWH_PER_T = 33.333
# PEM system LHV efficiency (current commercial upper-end; IEA GHR 2024).
# Note: overall power-to-MeOH LHV is ~0.45 (OVERALL_POWER_TO_MEOH_LHV)
# after synthesis losses and parasitic loads — see Kassø benchmark in RESEARCH.md.
ELECTROLYSER_EFFICIENCY = 0.70
ELECTROLYSER_LIFE_YR = 20
H2_STORAGE_LIFE_YR = 25

# ── Methanol ───────────────────────────────────────────────────────────────
# LHV of methanol (CH₃OH): 19.9 MJ/kg = 5.528 MWh/t
MEOH_LHV_MWH_PER_T = 19.9 / 3.6

# Stoichiometry: CO₂ + 3 H₂ → CH₃OH + H₂O
#   1 t MeOH = 44/32 = 1.375 t CO₂ + 6/32 = 0.1875 t H₂
T_CO2_PER_T_MEOH = 44.0 / 32.0          # 1.375
T_H2_PER_T_MEOH = 6.0 / 32.0            # 0.1875

# Practical synthesis efficiency (LHV basis, H₂ → MeOH).  Typical Topsoe /
# Lurgi / Carbon Recycling International plants report 80–87% at optimum
# load; use 0.83 as a central commercial-demonstrated value.
MEOH_SYNTHESIS_LHV_EFFICIENCY = 0.83

# Aux electricity for compression + utilities: ~0.3 MWh/t MeOH (CRI George
# Olah plant disclosure, Irsching pilot data).  Excludes CO₂ capture energy,
# which is accounted on the CO₂ supply side.
MEOH_AUX_ELEC_MWH_PER_T = 0.3

MEOH_SYNTHESIS_LIFE_YR = 25
MEOH_STORAGE_LIFE_YR = 30

# ── Fuel product LHVs ─────────────────────────────────────────────────────
# Diesel: 42.8 MJ/kg = 11.89 MWh/t (IPCC AR5 / IEA energy statistics)
DIESEL_LHV_MWH_PER_T = 42.8 / 3.6       # 11.889 MWh/t
# Naphtha: 44.0 MJ/kg = 12.22 MWh/t
NAPHTHA_LHV_MWH_PER_T = 44.0 / 3.6      # 12.222 MWh/t
# Kerosene / jet: 43.0 MJ/kg = 11.94 MWh/t
KERO_LHV_MWH_PER_T = 43.0 / 3.6         # 11.944 MWh/t
# Wax (heavy paraffin): 41.8 MJ/kg = 11.61 MWh/t
WAX_LHV_MWH_PER_T = 41.8 / 3.6          # 11.611 MWh/t

# ── CO₂ supply ─────────────────────────────────────────────────────────────
# Central placeholders.  Update per scenario once CO₂ supply chain analysis
# (Section 4 of README) is complete.
#
# DAC (direct air capture): ~1.5 MWh elec + ~5 GJ heat/t CO₂ at scale;
# $200–400/t at 2030, $100–150/t at 2040 (IEA DAC roadmap, Climeworks/
# Carbon Engineering disclosures).
#
# Biogenic point source (ethanol fermentation, biogas upgrading, pulp mill):
# $30–80/t CO₂ captured, very low energy intensity.  Whyalla proximity:
# none currently operational at scale.
#
# Industrial point source (Santos Moomba CCS, SA cement/smelter flues):
# $50–120/t.  Geographically feasible via rail/pipeline from Moomba.
CO2_DAC_ELEC_MWH_PER_T = 1.5
CO2_DAC_CAPEX_PER_TPY = 1_400          # $/(t CO₂/yr) — Climeworks-scale 2030
DEFAULT_CO2_PRICE_PER_T = 150.0        # central placeholder, scenario input

# ── Refinery efficiencies ─────────────────────────────────────────────────
# Each downstream pathway converts MeOH (LHV) → finished fuel (LHV).
#
# MTO+MOGD (Methanol-to-Olefins + Mobil Olefins-to-Gasoline-and-Distillate):
#   82% distillate / 15% gasoline product split; LHV efficiency ~72%
#   (Ruokonen et al. MDPI 2021; DICP/Sinopec DMTO reference).  DEFAULT path.
# MTG (Methanol-to-Gasoline, ExxonMobil/Topsoe TIGAS): 0.44 t gasoline/t MeOH,
#   LHV efficiency ~88% (MeOH → gasoline LHV).  Gasoline-dominant; poor diesel
#   match.  Retained as sensitivity / legacy.
# MTJ (Methanol-to-Jet / SAF): MTO + oligomerisation + hydrotreating;
#   LHV efficiency ~75–85%.  Retained as sensitivity.
# FT (Fischer-Tropsch via RWGS + FT): bypasses methanol; LHV efficiency ~55%
#   (RWGS + cobalt FT + hydrocracking).  Alternative to MTO+MOGD.
MTO_MOGD_LHV_EFFICIENCY = 0.72     # default diesel refinery path
MTO_MOGD_DISTILLATE_SHARE = 0.82   # fraction of fuel output that is diesel
MTO_MOGD_GASOLINE_SHARE = 0.15     # remainder is gasoline
MTG_LHV_EFFICIENCY = 0.88          # legacy gasoline path
MTJ_LHV_EFFICIENCY = 0.80          # legacy SAF path
E_FT_LHV_EFFICIENCY = 0.55         # RWGS + FT direct route

# ── Default plant sizing (diesel-led GW-scale anchor, per RESEARCH.md) ────
# Central case: 1 Mt/y synthetic diesel via MTO+MOGD, ~3 Mt/y MeOH
# intermediate, ~5–6 GW electrolyser, ~3.5 Mt/y CO₂ demand.
#
# MTO+MOGD stoichiometry: 3.0 t MeOH per t diesel (Ruokonen 2021 central).
# This implies a methanol plant of 3 Mt/y as the upstream anchor.
DEFAULT_DIESEL_TONNES_PER_YEAR = 1_000_000      # 1 Mt/y diesel output target
T_MEOH_PER_T_DIESEL = 3.0                        # MTO+MOGD central; see RESEARCH.md §scaling
DEFAULT_MEOH_TONNES_PER_YEAR = int(
    DEFAULT_DIESEL_TONNES_PER_YEAR * T_MEOH_PER_T_DIESEL
)  # 3_000_000 t/y
DEFAULT_MEOH_ANNUAL_MWH = DEFAULT_MEOH_TONNES_PER_YEAR * MEOH_LHV_MWH_PER_T

# Cross-check constant: overall power-to-MeOH LHV efficiency.
# Kassø plant (52 MW PEM, 360–380 GWh/y, 32–42 kt/y MeOH) implies 41–49%;
# use 0.45 as central Whyalla estimate for validation / reporting.
# ELECTROLYSER_EFFICIENCY × MEOH_SYNTHESIS_LHV_EFFICIENCY ≈ 0.70 × 0.83 = 0.58
# (textbook) vs Kassø-implied 0.41–0.49 — derating factor ~0.80 covers
# parasitic losses, startup cycling, and curtailment below nameplate.
OVERALL_POWER_TO_MEOH_LHV = 0.45    # cross-check/documentation constant only


def crf(discount_rate: float, lifetime_yr: int) -> float:
    """Capital Recovery Factor: r(1+r)^n / ((1+r)^n - 1)."""
    r, n = discount_rate, lifetime_yr
    return (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def annual_capex_per_mw(capex_per_kw: float, discount_rate: float,
                        lifetime_yr: int = ELECTROLYSER_LIFE_YR) -> float:
    """Annualised CAPEX in $/MW/yr."""
    return capex_per_kw * 1_000 * crf(discount_rate, lifetime_yr)


def meoh_annual_mwh(meoh_tonnes_per_year: float = DEFAULT_MEOH_TONNES_PER_YEAR) -> float:
    """Annual methanol production energy in MWh (LHV)."""
    return meoh_tonnes_per_year * MEOH_LHV_MWH_PER_T


def meoh_mw(meoh_tonnes_per_year: float = DEFAULT_MEOH_TONNES_PER_YEAR) -> float:
    """Average methanol production power in MW (LHV)."""
    return meoh_annual_mwh(meoh_tonnes_per_year) / 8760


def h2_mwh_per_t_meoh() -> float:
    """H₂ energy (LHV MWh) required per tonne of methanol at the modelled
    synthesis efficiency."""
    return (T_H2_PER_T_MEOH * H2_LHV_MWH_PER_T) / MEOH_SYNTHESIS_LHV_EFFICIENCY


def h2_mwh_per_mwh_meoh() -> float:
    """H₂ MWh per MWh methanol (both LHV).  Used as Link efficiency on the
    MeOH synthesis link."""
    return h2_mwh_per_t_meoh() / MEOH_LHV_MWH_PER_T


def asf_mass_fractions(alpha: float = 0.9, n_max: int = 40) -> dict[str, float]:
    """Schulz-Flory mass fractions bucketed into disjoint product cuts.

    w_n = n * (1 - alpha)^2 * alpha^(n-1)  [Anderson–Schulz–Flory distribution]

    Disjoint carbon-number buckets (avoids double-counting across overlapping
    refinery cut points):
        naphtha  n =  5..8   (light naphtha / gasoline precursor)
        kero     n =  9..14  (jet / SAF cut)
        diesel   n = 15..20  (diesel / distillate cut)
        wax      n = 21..n_max  (heavy paraffins, hydrocracker feed)

    n = 1..4 (methane + LPG) are excluded — they leave the liquid product
    stream and are treated as fuel-gas credit (not modelled here).

    Returns dict with keys naphtha, kero, diesel, wax; values sum to 1.0
    over the liquid-product fraction captured in n=5..n_max.
    """
    raw: dict[str, float] = {"naphtha": 0.0, "kero": 0.0, "diesel": 0.0, "wax": 0.0}
    for n in range(5, n_max + 1):
        w_n = n * (1 - alpha) ** 2 * alpha ** (n - 1)
        if 5 <= n <= 8:
            raw["naphtha"] += w_n
        elif 9 <= n <= 14:
            raw["kero"] += w_n
        elif 15 <= n <= 20:
            raw["diesel"] += w_n
        else:  # 21..n_max
            raw["wax"] += w_n

    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}
