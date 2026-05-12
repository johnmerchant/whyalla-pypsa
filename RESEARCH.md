# Whyalla-PyPSA: shared evidence dossier

> Citations and parameter justification shared by every project under
> `projects/`. Project-specific commentary (steelmaking, e-fuels) lives in
> the per-project `RESEARCH.md`. Numerical constants are imported from
> `whyalla_pypsa.assumptions`; this document is the citation chain behind
> those numbers.

## 1. Site context

**Whyalla Steelworks** is in administration since **February 2025**: KordaMentha
appointed by SA Government, GFG Alliance / OneSteel forced out, A$2.4 B
joint federal-state bailout announced. The bailout absorbed the **A$593 M
Hydrogen Jobs Plan (HJP)** envelope, dissolving the Office of Hydrogen
Power SA (OHPSA) in May 2025 and **deferring indefinitely** the GE Vernova
200 MW H₂-ready turbine contract and the 250 MW electrolyser order. Net
A$285.2 M was spent against the HJP envelope; **A$85.7 M of pre-EPC design
work was impaired** at cancellation. The HJP never reached EPC tender — its
$/kW figures are unvalidated political envelope numbers, not market-cleared
prices. See §6 for postmortem detail.

Land options secured by HJP (now repurposed for the bailout vehicle):
**238 ha Whyalla Industrial Estate** (electrolyser-preferred), **8.7 ha
Cultana Industrial Estate** (H₂ power station site), with Barngarla
Determination Aboriginal Corporation engagement complete. **Port Bonython**
(Point Lowly peninsula, 16 km NE) has ~2,000 ha developable, capesize
wharf, 81 ML diesel storage (Mitsubishi/Petro Diamond), and the **A$100 M
federal-state Port Bonython Hydrogen Hub** (A$70 M Cwlth + A$30 M SA,
finalised Oct 2023) for common-user infrastructure — **intact post-HJP**.

**Grid.** **Davenport 275 kV** is the regional hub. **Project EnergyConnect**
(NSW–SA, 800 MW, Stage 1 energised April 2025, Stage 2 last quarter 2026)
unlocks 5.3 GW new RE into SA/NSW but is **not sized to host a GW-scale
industrial load** standalone. Heywood interconnector V-SA steps 650→750 MW
on PEC Stage 2 commissioning (Draft 2026 ISP). **Cultana Pumped Hydro**
(225 MW / 1,770 MWh, EnergyAustralia, seawater) is **effectively cancelled**
after Defence land-lease failure.

**Water.** Morgan-Whyalla pipeline is fully committed; BHP Point Lowly
desal abandoned. **SA Northern Water Supply Project** (Mullaquana confirmed
Dec 2025, 260 ML/day ≈ 95 GL/y, 400 km pipeline, ~A$5 B CAPEX, FID
FY2026/27, first water 2029) is the only credible scale supply path.
Adelaide Desalination opex implies delivered water **A$1.00–2.50/kL**.

**Renewable resource.** Bungala Solar (220 MW AC) achieves **~25% AC CF**
— top-decile in NEM. Port Augusta Renewable Energy Park (DP Energy/Iberdrola,
317 MW Stage 1 + 500 MW solar/400 MW SCs Stage 2): hybrid solar **25–27%
CF**, wind **35–40% CF**. Lincoln Gap Wind Farm (~300 MW): **35–45% CF**
across Eyre Peninsula. **Thermal winds peak afternoon/evening, complementing
solar** — the single most valuable native feature of the site for
electrolyser load-factor firming.

## 2. Electrolyser techno-economics

Synthesising **CSIRO GenCost 2024-25 / 2025-26 draft** (Dec 2025), **IEA
Global Hydrogen Review 2024**, **IRENA Green Hydrogen Cost Reduction**,
**Electric Hydrogen 2024 whitepaper**, **NREL H2A May 2024**, **Krishnan
et al. 2023**, **Reksten et al. 2022**:

| Technology | 2026 | 2030 | 2035 | Efficiency (MWh/t H₂) | Stack life (hrs) | Confidence |
|---|---|---|---|---|---|---|
| Alkaline (AEL) | 1,200–1,800 | 700–1,100 | 500–800 | 52 → 48 | 60,000–90,000 | High |
| PEM | 1,500–2,400 | 900–1,400 | 600–950 | 50 → 46 | 50,000–80,000 | High |
| SOEC | 4,000–6,500 | 1,500–2,500 | 900–1,500 | 40 → 35 (with steam) | 20,000–40,000 | Low |

Recommended bracket for 2030 FID base case: **AUD 1,500/kW central, 1,000/kW
optimistic, 2,000/kW conservative**. NREL May 2024: PEM **~US$2,000/kW at
1 MW**, falling to **~US$500–700/kW at >100 MW**. Stack replacement every
7–10 years at **30–40% of initial CAPEX**; degradation ~1%/year.

Models in this repo carry **two paths** (`whyalla_pypsa.assumptions`):
- `central` — IEA-NZE-adjacent decline, alkaline/PEM convergence
- `conservative` — FOAK-stranded; first plants don't trigger the next cohort

The central path is anchored at **AUD 1,800/kW in 2028**, the upper bound
of the alkaline 2026 range. Defensibly above the cancelled HJP's
**AUD 880/kW** headline (250 MW, never priced by EPC tender, $85.7 M of
design impaired pre-cancellation) — see §6.

**Lifetime**: 20 years (industry-standard project life with one mid-life
stack replacement; matches CSIRO GenCost convention).

## 3. WACC framework

| Cohort | WACC (real, pre-tax) | Anchor |
|---|---|---|
| FOAK hydrogen / e-fuel / DRI process plant | **13%** | CEFC FOAK band 11–13%, upper bound |
| NOAK (≥100 MW operating reference at category) | **9%** | CEFC NOAK / mature CCGT-comparable |
| Renewables PPA-backed (wind/solar/battery) | **7%** | AU utility-scale 2025 signings (BRC-A) |

The 100 MW threshold is informed by HYBRIT/Stegra reference scale: alkaline
electrolyser cohorts cross from FOAK to NOAK pricing once one full-scale
deployment is operating (~700 MW Stegra Boden, in commissioning 2026).

Project life: **25 years** (shared across electrolyser amortisation, H₂
storage, process plant). Stack replacement is captured in opex, not in
the 20-year electrolyser equipment life used for capex annuitisation.

## 4. H₂ storage

**Whyalla has no salt or LRC option.** Site sits on the **Gawler Craton**
(Proterozoic crystalline basement); nearest sedimentary geology with cavern
potential is the **Polda Basin** ~250–300 km south on lower Eyre Peninsula,
too far for cost-effective pipeline transport. HYBRIT's 100 m³ rock cavern
(proven Feb 2025) is the only operating green-steel H₂ storage globally
and uses Swedish granitic geology not replicable at Whyalla. **Cavern
pricing is not modelled.**

Compressed-vessel literature (ARENA, IEA): **AUD 800–1,500/kg capacity**
at industrial scale. Cancelled HJP referenced **3,600 t at Cultana** scoped
down to 100 t pre-cancellation; figures never validated by EPC. Models
use **AUD 20,000/MWh = ~AUD 667/kg** (lower end of vessel literature)
held flat real because storage is a mature tank-tech line, not a learning
curve. A **AUD 30,000/MWh sensitivity** is an obvious robustness check
that has not been run.

## 5. Australian policy stack

**Hydrogen Headstart Program** — AUD 4 B total (AUD 2 B FY23-24 + AUD 2 B
FY24-25). Round 1 awarded 2025 to **Copenhagen Infrastructure Partners
(AUD 814 M / 1.5 GW)** under contracts-for-difference. Round 1 shortlist:
bp H2Kwinana (105 MW, SAF-relevant), HIF Asia Pacific Tasmania eFuel
(144 MW), KEPCO Port of Newcastle (750 MW), Stanwell CQ (720 MW), Origin
H2U, CIP. Round 2 EOI opened **October 2025**, AUD 1.3 B over FY24-25 to
FY33-34. **E-fuels derivatives (incl. e-methanol for shipping) qualify**.

**Hydrogen Production Tax Incentive** (Future Made in Australia Act,
Senate-passed 10 Feb 2025) — **AUD 2/kg refundable tax offset** for
renewable H₂ produced 2027-28 to 2039-40, up to 10 years per project.
Eligibility: 100% renewable-powered electrolysis. **Not stackable with
Headstart CfD in overlapping periods.**

**Safeguard Mechanism** baseline 2026: **AUD 35–40/t CO₂e**. ACCU forward
curve **AUD 60–80/t by 2030** (Reputex / Jarden). Trade-exposed steelworks
get a TEBA discount; Whyalla qualifies.

**IMO MEPC 83 Net-Zero Framework** effective March 2027, penalties from
2028: **US$100/t CO₂eq Tier 1 RU**, **US$380/t Tier 2 RU**. Creates an
implied e-methanol bunker premium of **~AUD 2,200/t methanol** over fossil
bunker if the vessel is selling Surplus Units.

**EU demand pull.** **FuelEU Maritime** (Jan 2025 effective): 2% GHG-intensity
reduction → 6% (2030) → 14.5% (2035) → 80% (2050), 2008 baseline 93.3
gCO₂e/MJ. **ReFuelEU Aviation**: SAF blending 2% (2025) → 6% (2030, with
0.7% RFNBO sub-mandate) → 20% (2035) → 70% (2050). Implied premiums
**EUR 800–1,500/t for RFNBO methanol** through 2030 in EU markets.

## 6. HJP postmortem — calibration anchor

The cancelled SA Whyalla Hydrogen Jobs Plan is the most important recent
data point for **how political FOAK envelopes don't survive engineering**:

| Item | Pre-cancellation | Post-mortem signal |
|---|---|---|
| Envelope | AUD 593 M committed | AUD 285.2 M actually spent |
| Design work | Pre-EPC ECI in progress | **AUD 85.7 M impaired** at cancellation |
| Electrolyser | 250 MW @ AUD 220 M ≈ **AUD 880/kW** | Never tested by EPC tender |
| H₂ power station | 200 MW @ AUD 342 M ≈ AUD 1,710/kW | 4× GE Vernova LM6000VELOX deferred |
| H₂ storage | 3,600 t at Cultana descoped to 100 t | Figures never validated |
| Trigger | GFG/OneSteel administration Feb 2025 | OHPSA dissolved May 2025 |

**Why this matters for the model:** the HJP's $880/kW electrolyser figure
is **not a clean benchmark**. It is the announced envelope for a 250 MW
project killed at ECI stage, with $85.7 M of design work already showing
overrun pressure pre-cancellation. The model's central path of AUD 1,800/kW
in 2028 is the **conservative-end IEA/CSIRO range** for alkaline at
100+ MW scale — defensibly above HJP's headline because:

1. Model sizes 600–800 MW (closer to FOAK GW-scale where vendor pricing
   and BOP integration risk are higher per kW).
2. HJP $220 M was an internal/political envelope, not EPC-priced.
3. Model figure is **all-in installed** (grid connect, water, compression,
   cooling); HJP $880/kW likely covered electrolyser + immediate BOS only.
4. The HJP impairment shows the envelope was already insufficient by the
   time detailed engineering hit the desk.

**Implication for FOAK premia in derivative components** (e.g., DRI
thermal storage in `projects/dri-eaf`): the HJP collapse validates
modelling **vendor margin + EPC wrap + bonded performance + financing
penalty** stacked over commodity pricing for any FOAK item.

## 7. Comparable projects — cancellation context

- **Ørsted FlagshipONE (Sweden)** cancelled August 2024: DKK 1.5 B
  (US$221 M) impairment + DKK 300 M cancellation provision. Cited reason
  (Mads Nipper): "inability to sign long-term offtake at sustainable
  pricing and significantly higher project costs."
- **HIF Matagorda (Texas)**: US$6 B target, 1.8 GW electrolyser, FID not
  taken as of April 2026; supplier switched Siemens → Electric Hydrogen
  Sept 2025.
- **H2U Eyre Peninsula Gateway** (75 MW electrolyser, 120 t/day NH₃,
  Worley FEED, RWE MoU): listed "Archived" on CSIRO HyResource post Feb 2025.

The pattern is consistent: **standalone facility economics under speculative
offtake do not clear the FOAK hurdle**. The Whyalla case differs by virtue
of (a) multi-pathway portfolio optionality, (b) free real estate (DRI off-gas
during transition; Northern Water co-siting), (c) Australian taxpayer
willingness already demonstrated by JobKeeper / AUKUS / 2024 nuclear policy.

## 8. Project-specific dossiers

- `projects/dri-eaf/RESEARCH.md` — green-iron / DRI-EAF: MIDREX shaft
  furnace, scrap pricing, EAF, thermal buffer FOAK premium, MIDREX
  licensor re-qualification, gas pipeline timing.
- `projects/efuels/RESEARCH.md` — synthetic fuels: methanol synthesis,
  MTO+MOGD / FT, Kassø reference, CO₂ tranche dispatch, biofuels coupling.

## 9. Data gaps shared across projects

1. **Northern Water tariff to secondary customers** — A$5 B CAPEX is
   public; allocated tariff beyond BHP foundation offtake is not.
2. **Whyalla seawater quality** — Upper Spencer Gulf ~40 g/L vs 35 g/L
   ocean affects desal energy intensity.
3. **Port Bonython liquid CO₂ import infrastructure** — no published
   estimate for cryogenic tank farm + jetty upgrade.
4. **Hydrogen Headstart Round 2 eligibility for derivatives where H₂ is
   intermediate, not final product** — guidelines under revision as of
   April 2026.
5. **Australian DAC cost curves at scale** — Southern Green Gas /
   AspiraDAC prototypes; aspirational <AUD 100/t unsubstantiated.
6. **HJP detailed cost stack** — never publicly released; would settle
   the AUD 20k/MWh storage figure.
