# DRI-EAF: project-specific evidence dossier

> **Status**: this dossier covers green-iron / DRI-EAF parameters and
> citations specific to `projects/dri-eaf`. **Shared parameters** (Whyalla
> site context, electrolyser TEA, WACC framework, H₂ storage, Australian
> policy stack, HJP postmortem) live in `../../RESEARCH.md`. Numerical
> constants (electrolyser capex paths, lifetimes, WACC bands, H₂ storage
> capex) are imported from `whyalla_pypsa.assumptions`.

## 1. Process chain

The model represents a **single MIDREX Flex shaft furnace** at Whyalla,
commissioning 2030 with the Cooper Basin pipeline gas (first gas March
2030, 20 PJ/yr). Pre-2030: BF-BOS continues; EAF on scrap precedes DRI.
H₂/NG blend is operational, not capex — one shaft, fired on whatever
mixture the LP picks.

| Component | Role | Lifetime | Source |
|---|---|---|---|
| Electrolyser (alkaline) | H₂ for shaft reductant | 20 yr | shared (RESEARCH.md §2) |
| H₂ vessel storage | 12-h dispatch buffer | 25 yr | shared |
| MIDREX Flex shaft | DRI from H₂/NG blend | 25 yr | this doc §2 |
| Electric resistance heater | Process gas heating (no-gas branch) | 20 yr | this doc §3 |
| H₂ burner | Process gas heating (dual-fuel branch) | 20 yr | this doc §3 |
| Thermal buffer (TES) | Dunkelflaute ride-through (no-gas only) | 25 yr | this doc §4 |
| Scrap-EAF | Steelmaking on metallic-iron + scrap | 25 yr | shared CAPEX bands |

## 2. MIDREX Flex shaft furnace

MIDREX Flex is the **dual-fuel** variant — ~70% H₂ / 30% NG operationally,
with the NG reformer providing self-heat that covers the shaft's thermal
demand intra-timestep. **Single shaft installed once at FY2030**;
H₂ fraction is a dispatch decision, not a capex decision. See memory:
`project_whyalla_midrex_flex`.

CAPEX anchored at MIDREX Inc's 2024 quotes for 1.6 Mt/yr DRI capacity,
~AUD 800–1,000 M EPC range. Energiron-ZR is the only operational dual-fuel
alternative; no Australian DRI plant has reached FID.

**No-gas (100% H₂) variant**: removes reformer, replaces with electric
resistance heater + thermal buffer. Modelled as a separate scenario branch
(`No gas (100% H2)` in `generate_trajectory.py`). **Skipped pre-2030** —
no shaft commissioned yet.

**Gas supply**: pipeline from Cooper Basin / Moomba, fossil NG only. No
biomethane available at scale; rule it out for Scope 1 abatement. See
memory: `project_whyalla_gas_supply`.

## 3. Heater / burner blocks

Both are mature equipment classes with **flat real CAPEX**:

| Item | AUD/kW_th | Lifetime | Anchor |
|---|---|---|---|
| Electric resistance heater (Kanthal Prothal, Tutco SureHeat) | 400 | 20 yr | Vendor brochure |
| H₂ burner (combustion-air retrofit on existing reformer feed) | 30 | 20 yr | MIDREX Flex differential |

The huge cost asymmetry reflects that the H₂ burner is a small modification
to an existing combustion train, while the electric heater replaces the
entire reformer thermal duty (~150–250 MW_th for 1.6 Mt/yr DRI).

## 4. Thermal buffer (FOAK)

**No sanctioned green-steel project uses 100s-MWh TES on a shaft heater.**
HYBRIT, Stegra/Boden, SALCOS, tkH2Steel, ArcelorMittal Hamburg, POSCO
HyREX all buffer with: (1) H₂ caverns (HYBRIT Feb 2025), (2) oversized
electrolysers (Stegra 740 MW alkaline), (3) firm grid imports (Nordic
hydro, German backbone), or (4) dual-fuel ride-through (every Energiron-ZR
plant; MIDREX Flex). Existing MIDREX H₂ / Energiron ZR flowsheets have
**recuperative** heat exchangers (top-gas, ~350-400 °C) and resistive
electric process-gas heaters — **no thermal mass for grid-scale storage**.

The most credible Australian engineering reference is **HILT CRC project
RP2.017** (2024–) — repurposing hot-blast Cowper stoves as TES for H₂-DRI.
Research-stage, no deployment yet. Rondo / Antora / Kraftblock market at
steel but have zero contracted DRI-heater deployments.

**FOAK pricing trajectory** (`whyalla_pypsa` does not centralise this —
it's specific to the no-gas branch):

| Year | AUD/MWh installed | Cohort |
|---|---|---|
| 2028 | 150,000 | FOAK ceiling — vendor margin + EPC wrap + bonded performance + financing penalty over commodity ~$50k/MWh |
| 2030 | 150,000 | FOAK persists |
| 2033 | 110,000 | First learning-curve drop |
| 2037 | 75,000 | NOAK approach |
| 2040 | 55,000 | Asymptotic to Rondo/Antora commodity reference |

**FOAK→NOAK threshold**: 100 MWh cumulative site capacity (mirrors
electrolyser threshold but for storage rather than power).

**MIDREX licensor re-qualification fee**: AUD 15 M one-time, paid on
first thermal buffer deployment to re-qualify the shaft furnace warranty.
Mid-point of $5–20 M industry range for licensor re-qualification on
non-standard integrations.

**Earliest commission year**: 2033. FOAK schedule slip means the unit
isn't commissioning-day-ready with the shaft furnace in 2030.

LP behaviour at FOAK pricing: **dual-fuel branches build essentially zero
buffer** (gas reformer self-heat covers shaft thermal demand intra-timestep);
**no-gas branch builds ~400 MWh** to ride out dunkelflaute on the
all-electric heater. See memory: `project_whyalla_thermal_buffer_status`.

## 5. EAF + scrap

EAF commissions 2028 (scrap-only operation precedes DRI). 30% scrap cap
on metallic feed (industry maximum for tap-to-tap quality consistency).

**Two-tier supply curve.** Tier capacities are peak-hour caps that
double as annual budgets at 100 % utilisation, so the LP can use less but
never more.

| Tier | Annual cap (t/yr) | AUD/t | Source |
|---|---|---|---|
| 1 — domestic HMS 80:20 | 1,000,000 | 500 | AU recovers ~6 Mt/yr (BIR World Steel Recycling); ~1 Mt realistically allocable to a single mill without disrupting other consumers. 2026 spot AU HMS 80:20 $420-550/t |
| 2 — premium HMS / shred / imports | 800,000 | 700 | Premium grades + seaborne imports from China/India landed ~$700-850/t at AU port |

Bridge year 2028 (EAF scrap-only at 1.6 Mt steel) draws from both tiers:
~1.0 Mt tier 1 + ~0.6 Mt tier 2 → effective scrap cost ~$575/t blended.
Post-DRI dual-fuel years (≤480 kt/yr scrap at the 30 % cap) sit entirely
in tier 1 at $500/t.

150 MW grid baseline (existing EAF-era electrical connection) seeded as
zero-capex tranche; trajectory additions above 150 MW are the only entries
in the capital-works schedule. See memory: `project_whyalla_scrap_and_phase_model`.

## 6. Phase model

| Year | Phase | Operations |
|---|---|---|
| 2026–2027 | BF-BOS | Existing blast furnace continues |
| 2028 | EAF commissions | Scrap-only operation (no DRI) |
| 2029 | BF retires | Transition year |
| 2030+ | DRI-EAF | MIDREX Flex shaft on H₂/NG blend, EAF unchanged |
| 2033+ | Optional TES | If no-gas branch and economics clear FOAK premium |

See memories: `project_whyalla_pipeline_timing`, `project_whyalla_scrap_and_phase_model`.

## 7. Heywood interconnector

V-SA flow steps **650 → 750 MW** on PEC Stage 2 commissioning **2027-11-30**
(Draft 2026 ISP). Affects grid import availability for the no-gas branch
which leans hardest on imports during dunkelflaute. See memory:
`project_whyalla_heywood_upgrade`.

## 8. Open questions

1. **Thermal buffer NOAK date.** Rondo/Antora/Kraftblock have not
   announced contracted DRI deployments; the 2037 NOAK transition is a
   modelling assumption, not a committed industry milestone.
2. **MIDREX licensor fee scope.** The AUD 15 M figure is mid-point of an
   industry range; vendor negotiation could move it ±50%.
3. **HILT CRC RP2.017 outcome.** Cowper-stove retrofit research is
   ongoing; positive/negative results would reset the FOAK premium curve.
4. **Energiron-ZR vs MIDREX Flex price differential.** Tenova-HYL is a
   real alternative; not modelled.
5. **Heywood Stage 3 timing.** Currently no announced date; would
   relax import constraint further if it landed pre-2035.

## 9. References

[^1]: CSIRO (2025). *GenCost 2024–25 Final Report.* Graham, P., Hayward, J. & Foster, J. [PDF](https://www.csiro.au/-/media/Energy/GenCost/GenCost-2024-25-Final_20250728.pdf) · [release](https://www.csiro.au/en/news/all/news/2025/july/2024-25-gencost-final-report). Baseline WACC raised from 6% to 7% real per Infrastructure Australia recommendation; nth-of-a-kind only. GenCost's rebuttal to Frontier Economics' nuclear modelling states "a premium of over 100% is more appropriate for the first plant."

[^2]: IRENA (2020). *Green Hydrogen Cost Reduction: Scaling Up Electrolysers to Meet the 1.5°C Climate Goal.* [Publication page](https://www.irena.org/publications/2020/Dec/Green-hydrogen-cost-reduction) · [PDF](https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2020/Dec/IRENA_Green_hydrogen_cost_2020.pdf). Uses 6% WACC as "best" case (comparable to mature renewables) and 10% as "relatively high risk" sensitivity.

[^3]: IRENA (2022). *Global Hydrogen Trade to Meet the 1.5°C Climate Goal — Part I: Trade Outlook.* [Publication page](https://www.irena.org/publications/2022/Jul/Global-Hydrogen-Trade-Outlook). Holds electrolyser CAPEX globally uniform but varies WACC by region "to express the risk of investment."

[^4]: IEA (2024). *Global Hydrogen Review 2024.* [Report page](https://www.iea.org/reports/global-hydrogen-review-2024) · [PDF](https://iea.blob.core.windows.net/assets/89c1e382-dc59-46ca-aa47-9f7d41531ab5/GlobalHydrogenReview2024.pdf). Source for electrolyser CAPEX learning-curve trajectory.

[^5]: IEA. *Cost of Capital Observatory.* [Report page](https://www.iea.org/reports/cost-of-capital-observatory) · [Launch announcement](https://www.iea.org/news/iea-and-partners-launch-cost-of-capital-observatory-to-improve-transparency-over-higher-borrowing-costs-for-energy-projects-in-developing-world). Clean-energy cost of capital in EMDEs sits 2–3× advanced-economy levels; a 2pp WACC reduction in EMDEs alone would cut cumulative net-zero investment needs by USD 16 trillion to 2050.

[^6]: BloombergNEF (2023). *2023 Hydrogen Levelized Cost Update: Green Beats Gray.* [Insight page](https://about.bnef.com/insights/clean-energy/2023-hydrogen-levelized-cost-update-green-beats-gray/). Differentiates cost of capital by market to reflect regional financing differences; green LCOH range $2.38–$12/kg in 2023.

[^7]: Hydrogen Council / McKinsey (Dec 2023). *Hydrogen Insights 2023 December Update.* [Publication page](https://hydrogencouncil.com/en/hydrogen-insights-2023-december-update/) · [PDF](https://hydrogencouncil.com/wp-content/uploads/2023/12/Hydrogen-Insights-Dec-2023-Update.pdf). Documents a 3–5pp rise in cost of capital for renewable hydrogen between mid-2022 and mid-2023; LCOH up 30–65% to USD 4.5–6.5/kg. Primary source for the FOAK premium used in the 13% scenario.

[^8]: Lee, M. & Saygin, D. (2023). *Financing cost impacts on cost competitiveness of green hydrogen in emerging and developing economies.* OECD Environment Working Papers No. 227, OECD Publishing. [Publication page](https://www.oecd.org/en/publications/financing-cost-impacts-on-cost-competitiveness-of-green-hydrogen-in-emerging-and-developing-economies_15b16fc3-en.html) · [PDF](https://www.oecd.org/content/dam/oecd/en/publications/reports/2023/11/financing-cost-impacts-on-cost-competitiveness-of-green-hydrogen-in-emerging-and-developing-economies_c660be85/15b16fc3-en.pdf). SPV-level WACC for green-hydrogen projects spans 6.4–24%, with 10% representative for a "best-in-class" location. Primary source for the 9% NOAK project-finance benchmark.

[^9]: RMI (2024). *Five Lessons for Industrial Project Finance from H2 Green Steel.* [Article](https://rmi.org/five-lessons-for-industrial-project-finance-from-h2-green-steel/). Anatomy of the Stegra capital stack and ECA-enhanced senior debt.

[^10]: Megaproject performance literature — Merrow (RAND / IPA) and Mignacca & Locatelli have documented that FOAK industrial megaprojects routinely suffer material capex overruns and schedule slips relative to NOAK infrastructure. Project-finance equity IRRs of 15–20% are characteristic of FOAK-risk industrial projects vs 8–12% for proven NOAK infrastructure. Treat the specific percentage ranges as indicative rather than precisely attributable without the original monographs.

[^11]: Alpha Spread. *BlueScope Steel Ltd (BSL) Discount Rate — WACC & Cost of Equity.* [Discount-rate page](https://www.alphaspread.com/security/asx/bsl/discount-rate). WACC ~8.4% nominal (β=1.01, cost of equity 8.35%, cost of debt 9.01%).

[^12]: BlueScope Steel. *Annual Reports FY24 and FY25.* [Investor centre](https://www.bluescope.com/investors). Underlying-EBIT ROIC is the primary performance measure; BCP goodwill impairment of AUD 438.9m in FY25 demonstrates willingness to write down capital rather than persist with sub-hurdle investments. NeoSmelt ESF JV (with BHP, Rio Tinto, Mitsui, Woodside) is the revealed hedge away from a standalone H₂-DRI bet.

[^13]: H2 Green Steel / Stegra (22 Jan 2024). *H2 Green Steel raises more than €4 billion in debt financing for the world's first large-scale green steel plant.* [Press release](https://stegra.com/en/news-and-stories/h2-green-steel-raises-more-than-4-billion-in-debt-financing-for-the-worlds-first-large-scale-green-steel-plant). ~€6.5bn total: ~€4.2bn debt (~€3.5bn senior + ~€600m junior; ~€2.4bn credit-enhanced by Riksgälden and Euler Hermes), ~€2.1bn equity, EU Innovation Fund €250m grant plus additional public support.

[^14]: Stegra refinancing (Oct 2025 – Apr 2026). Oct 2025 Hy24 investment followed by a ~€1.4bn April 2026 round led by Wallenberg Investments after Citigroup sought exit; construction ~60% complete as of late 2025. Coverage: Canary Media, *["Europe's flagship green-steel project gets a financial lifeline"](https://www.canarymedia.com/articles/green-steel/europes-flagship-green-steel-project-gets-a-financial-lifeline-stegra-hy24)*.

[^15]: HYBRIT (SSAB / LKAB / Vattenfall). Gällivare demonstration plant: SEK >20bn capex, SEK 3.1bn Swedish Energy Agency + €108m EU Innovation Fund (~20% subsidy intensity). Corporate balance-sheet financing; implied cost of capital closer to sovereign than commercial given state ownership.

[^16]: European Commission (Oct 2022). *State aid: Commission approves €1 billion German measure to support Salzgitter decarbonise its steel production by using hydrogen.* [Press release IP/22/5968](https://ec.europa.eu/commission/presscorner/detail/en/ip_22_5968). SALCOS stage 1 carries ~40% subsidy intensity (~€1bn public funding on ~€2.5bn investment). Comparable ~45% subsidy intensity at ArcelorMittal Gijón (~€450m grant on ~€1bn investment); ThyssenKrupp tkH2Steel approved for ~€2bn in EU-cleared aid on a larger project.

[^17]: ArcelorMittal (Nov 2024). *Update on European decarbonisation plans.* [Press release](https://corporate.arcelormittal.com/media/press-releases/arcelormittal-provides-update-on-its-european-decarbonization-plans). Gijón FID postponed; Dunkirk DRI-EAF FID could not be taken. Earlier in 2024, ArcelorMittal Europe CEO Geert Van Poelvoorde publicly stated that green hydrogen was too expensive to make the DRI-EAF economics work even with billions in committed subsidies.

[^18]: ARENA. *Hydrogen Headstart* — [Round 1](https://arena.gov.au/funding/hydrogen-headstart/) · [Round 2](https://arena.gov.au/funding/hydrogen-headstart-round2/). DCCEEW programme overview: [Hydrogen Headstart program](https://www.dcceew.gov.au/energy/hydrogen/hydrogen-headstart-program). Designed to "bridge the commercial gap for first mover projects."

[^19]: AEMO. *Draft 2026 Integrated System Plan.* [Consultation page](https://www.aemo.com.au/energy-systems/major-publications/integrated-system-plan-isp/2026-integrated-system-plan-isp) · [PDF](https://www.aemo.com.au/-/media/files/major-publications/isp/draft-2026/draft-2026-integrated-system-plan.pdf). Uses CSIRO GenCost assumptions; source of SA1 fleet projections for the `slower_growth`, `step_change`, and `accelerated_transition` scenarios in this model.

[^20]: Midrex (2024). *2023 World Direct Reduction Statistics* and MIDREX® process flowsheet data. [Midrex technology page](https://www.midrex.com/technology/midrex-process/). Shaft furnace reductant intensity ~10.0–11.0 GJ/t DRI (central 10.5 GJ/t used here); 92–94% metallisation with high-grade (>67% Fe) magnetite pellet feed. DRI-to-liquid-steel yield of 1.05 t DRI / t steel reflects typical DRI-EAF practice with ~5% scrap addition to neutralise residual FeO and balance heat. EAF electricity demand of 0.60 MWh/t steel is the World Steel Association benchmark for a hot-charged DRI-EAF route with high-grade, highly-metallised feed (see also *WSA — Steel's Contribution to a Low Carbon Future*, Sep 2020), vs ~0.65 MWh/t on mid-grade hematite-derived DRI. Middleback Ranges concentrate grade (GFG / OneSteel technical disclosures, 2023–2024) supports the high-grade end of this range.

[^21]: DCCEEW (Mar 2023). *Safeguard Mechanism Reforms.* [Programme page](https://www.dcceew.gov.au/climate-change/emissions-reporting/national-greenhouse-energy-reporting-scheme/safeguard-mechanism). Amendments introduce declining baselines (−4.9% p.a. to 2030), Safeguard Mechanism Credits (SMCs) with a price cap indexed to CPI+2%, and enhanced linkage to the Australian Carbon Credit Unit (ACCU) market. ACCU spot prices sat around AUD 30–40/t through 2024–2025; the $40/t 2026 start in the Policy-stated path reflects this level.

[^22]: European Union (2023). *Regulation (EU) 2023/956 of the European Parliament and of the Council of 10 May 2023 establishing a carbon border adjustment mechanism.* [EUR-Lex](https://eur-lex.europa.eu/eli/reg/2023/956/oj). Transitional reporting phase Oct 2023 – Dec 2025; definitive regime (financial obligation) from 1 January 2026 covering steel, cement, aluminium, fertilisers, electricity, and hydrogen. CBAM certificate price tracks weekly EU ETS average; the $200/t 2040 endpoint aligns with EU ETS forward-curve and Fit-for-55 / Net-Zero Industry Act abatement-cost trajectories.

[^23]: DCCEEW (2024). *National Greenhouse Accounts Factors 2024.* [Publication page](https://www.dcceew.gov.au/climate-change/publications/national-greenhouse-accounts-factors-2024). Scope 1 emission factor for combustion of natural gas distributed in a pipeline: 51.33 kg CO₂-e/GJ on a gross calorific value (HHV) basis. The model uses the IPCC 2006 default of 56.1 kg CO₂/GJ on a net calorific value (LHV) basis, consistent with international practice and most hydrogen-economy literature. The ~9% difference (LHV vs HHV) slightly overstates gas-DRI emissions (0.589 vs ~0.539 t CO₂-e/t DRI), making the model conservative on the carbon cost of the gas counterfactual.

[^24]: IEA (2024). *Electrolysers — Tracking Report.* [Tracking page](https://www.iea.org/energy-system/low-emission-fuels/electrolysers). Current installed PEM electrolyser system CAPEX: USD 2,000–2,450/kWe; alkaline: USD 2,000/kWe (Chinese alkaline as low as $750–1,300/kWe). Alkaline and PEM have comparable system efficiency; advanced designs (Hysata capillary-fed PEM) report 80% LHV system efficiency. The model's 70% LHV is at the upper end of current commercial PEM system-level range (~55–65% LHV including BoP and compression) and within the 2028–2030 projected range. CAPEX trajectory endpoint of $700/kW by 2040 aligns with IEA NZE and BNEF learning-curve projections from a 16–21% learning rate.

[^25]: IRENA (2020). *Green Hydrogen Cost Reduction: Scaling Up Electrolysers to Meet the 1.5°C Climate Goal.* [PDF](https://www.irena.org/-/media/Files/IRENA/Agency/Publication/2020/Dec/IRENA_Green_hydrogen_cost_2020.pdf). PEM stack lifetime: 60,000–80,000 hours current, 100,000+ hours projected. O&M costs: 2–5% of CAPEX per year for PEM systems (the model's $2/MWh variable O&M represents only the variable component — water, cooling, routine maintenance — with stack replacement costs implicitly absorbed into the 20-year CRF amortisation). Asset economic life of 20–30 years is standard for electrolyser investment appraisal; CSIRO GenCost 2024-25 uses 25 years.

[^26]: Hydrogen Council / McKinsey (2020). *Path to Hydrogen Competitiveness: A Cost Perspective.* [PDF](https://hydrogencouncil.com/wp-content/uploads/2020/01/Path-to-Hydrogen-Competitiveness_Full-Study-1.pdf). Compressed gas H₂ storage (above-ground, ~350 bar): $15–25/kWh at current scale; projected to $8–12/kWh with scale-up and manufacturing learning. Salt cavern storage is significantly cheaper ($1–2/kWh) but unavailable at Whyalla due to geology. The model's $20/kWh ($20,000/MWh) is a conservative mid-range estimate for above-ground storage held flat real (mature tank-line, not on a learning curve).

[^27]: Cooper Basin / Moomba pipeline gas allocation (2026). 200 PJ over 10 years (20 PJ/yr), first gas 1 March 2030, delivered ex-Moomba at indexed pricing. The $10.5/GJ modelled price reflects indexed real-terms pricing (base 2030, CPI-linked with floor/ceiling). Pre-contract spot ($12/GJ) and post-contract spot ($14/GJ) bracket recent AEMO Gas Statement of Opportunities and ACCC Gas Inquiry quarterly reports for the East Coast market. Pipeline gas is fossil NG only — no biomethane available at scale.

[^28]: AEMC Reliability Panel (2024). *NEM Reliability Standard and Settings Review.* Market price cap (MPC): $16,600/MWh for 2024-25, indexed annually to CPI per National Electricity Rules clause 3.9.4. The MPC was previously $15,100/MWh (2022-24) and $15,000/MWh (2021-22). As a VOLL backstop the model is insensitive to the exact value; it dispatches only when all other supply is exhausted (extreme scarcity events, typically <10 hours/yr).

[^29]: AEMO (2025). *NEM Registration and Exemption List* and *Generator Information Page.* SA thermal generators: Pelican Point CCGT (479 MW, ~50% HHV); Osborne CCGT (180 MW, ~48% HHV); Hallett, Quarantine and other OCGTs (~30% HHV). The model aggregates to 1200 MW CCGT at 50% and 1400 MW OCGT at 30%, representing the SA thermal fleet at ISP baseline. BESS: Hornsdale Power Reserve (193.5 MW / 386 MWh) + Torrens Island BESS (250 MW / 500 MWh, commissioned Nov 2023) ≈ 443 MW combined; model simplifies to 400 MW / 2h (800 MWh). Li-ion round-trip efficiency of 84.6% (√0.846 ≈ 0.92 each way) is standard for grid-scale BESS.

[^30]: ElectraNet (2025). *Northern Transmission Project (NTx).* [Project page](https://electranet.com.au/projects/northern-transmission-project-ntx/). Actionable project in AEMO 2024 ISP to increase transfer capacity from the Mid North and Greater Adelaide to the Upper Spencer Gulf (Whyalla/Cultana). Current SA_N–SA_C backbone is thermally rated at ~650 MW; NTx delivers ~1500 MW transfer capacity. Status: pending (RIT-T underway as of Dec 2025). Heywood interconnector (V-SA): steps 650 → 750 MW on PEC Stage 2 commissioning (2027-11-30, Draft 2026 ISP). Project EnergyConnect (SA–NSW): 800 MW nominal at full build; Stage 1 (Robertstown–Buronga–Red Cliffs) operational April 2025 at 150 MW transfer capacity. Stage 2 (Buronga–Wagga Wagga) expected late 2027 for full 800 MW.

[^31]: Midrex Technologies. *MIDREX Flex®* and *MIDREX H₂™* technology documentation. [Technology page](https://www.midrex.com/technology/midrex-process/). MIDREX Flex is the dual-fuel variant — operationally ~70% H₂ / 30% NG with the NG reformer providing self-heat that covers the shaft's thermal demand intra-timestep. Standard MIDREX process designed for up to ~30% H₂ blend without modification; full H₂ operation requires MIDREX H₂ configuration with modified gas heating, top-gas recycling, and electrical preheating. H₂ consumption for 100% H₂-DRI: 51–58 kg H₂/t DRI at 92–94% metallisation (≈6.1–7.0 GJ H₂ LHV/t DRI). MIDREX Inc 2024 EPC quotes for 1.6 Mt/yr DRI capacity sit in the AUD 800–1,000 M range. Energiron-ZR is the only operational dual-fuel alternative; no Australian DRI plant has reached FID.

[^32]: US DOE (2023). *Hydrogen Storage* fact sheet. [Page](https://www.energy.gov/eere/fuelcells/hydrogen-storage). H₂ lower heating value (LHV): 120 MJ/kg = 33.33 kWh/kg = 33.33 MWh/t. H₂ higher heating value (HHV): 142 MJ/kg. Standard thermophysical property; consistent across NIST, IEA, and IRENA reference data.

[^33]: World Steel Association (2020). *Steel's Contribution to a Low Carbon Future* and *Fact Sheet: Electric Arc Furnace Steelmaking.* [WSA publications](https://worldsteel.org/publications/). EAF electricity consumption for hot-charged DRI-EAF with high-grade feed: 0.55–0.65 MWh/t liquid steel (model uses 0.60). EAF tap-to-tap cycle: typical peak electrical draw 2–3× average during melt/refine phase (model uses 2.5× peak factor). The 24-hour DRI pile buffer and 8-hour slab/billet campaign buffer are operational design parameters for continuous EAF-caster coupling and are consistent with standard DRI-EAF practice.

[^34]: AEMO (2025). *Draft 2026 Integrated System Plan* and *2025 Electricity Statement of Opportunities.* [ISP page](https://www.aemo.com.au/energy-systems/major-publications/integrated-system-plan-isp/2026-integrated-system-plan-isp). SA demand split: SA_North (Upper Spencer Gulf, including existing Whyalla steelworks) peak ~600 MW; SA_Central (Adelaide metro and surrounds) peak ~1800 MW. SA_North receives ~68% of SA1 wind capacity (REZ distribution).

[^35]: Clean Energy Regulator / OpenNEM (2025). *National Electricity Market emissions intensity.* [OpenNEM dashboard](https://opennem.org.au/). NEM-wide average emissions intensity: ~0.55–0.65 t CO₂/MWh in 2024-25 (declining from ~0.8 t/MWh a decade ago as coal retires and renewables grow). SA-specific intensity is much lower (~0.15–0.25 t/MWh) due to high wind/solar penetration; the model's 0.6 t/MWh for VIC/NSW import carriers proxies the broader NEM mix that SA imports during low-RE periods (predominantly Victorian brown coal and NSW black coal at the margin).

[^36]: HILT CRC (Heavy Industry Low-carbon Transition Cooperative Research Centre). *Project RP2.017 — Repurposing hot-blast Cowper stoves as thermal energy storage for H₂-DRI.* Research-stage as of 2024–2025. The most credible Australian engineering reference for shaft-furnace TES; no deployment yet. Outcomes will materially update the FOAK premium curve used here.

[^37]: HYBRIT / SSAB (Feb 2025). *HYBRIT pilot — H₂ buffer storage.* SSAB's HYBRIT pilot uses lined rock cavern H₂ storage to buffer intermittent renewable supply; this is the storage architecture sanctioned green-iron projects choose, not multi-100-MWh thermal buffer on the shaft heater itself.
