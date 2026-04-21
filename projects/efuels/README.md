# Whyalla e-Methanol & e-Fuels: A Breakeven Analysis

A PyPSA + ISPyPSA-based technoeconomic model of a greenfield e-methanol
and e-fuels refinery at Whyalla, anchored to the SA Northern REZ. Treats
Whyalla as a chemical / liquid-fuels export precinct, leveraging the existing
deepwater port and the same SA Northern REZ that hosts the adjacent
steelworks.

> **Status: implemented.**  Physics, components, results extraction, the
> CO₂ supply merit-order curve, the scenario matrix, and 6 chart scripts
> are all complete and tested.  Run `python -m pytest` to verify.

## Thesis

The central question: **under what combination of electrolyser cost
decline, CO₂ supply cost, cost of capital, and product-price policy
(ReFuelEU Aviation, FuelEU Maritime, domestic SAF mandate, IMO 2050) does
a greenfield e-methanol / synthetic-diesel facility at Whyalla clear
commercial hurdle rates?**

### Central-case plant sizing — GW-scale diesel-led

The model is anchored to a **1 Mt/yr synthetic diesel** output
(≈ 3 Mt/yr MeOH feedstock, ≈ 5–6 GW electrolyser at 50–55% capacity
factor), derived from the MTO+MOGD pathway.  This anchor was chosen to
match a realistic Queensland/SA deepwater port export precinct scale and
to provide a direct comparison with VLSFO / diesel import-parity pricing.

| Parameter | Value | Notes |
| --- | ---: | --- |
| `DEFAULT_MEOH_TONNES_PER_YEAR` | 3 000 000 t/yr | Model default |
| `DEFAULT_DIESEL_TONNES_PER_YEAR` | 1 000 000 t/yr | MTO+MOGD from 3 Mt MeOH |
| Electrolyser (model build-out) | 4 700–5 200 MW | LP-optimised at 50 AUD/MWh grid |
| Import-parity diesel (2030) | 1 550 AUD/t | Revenue benchmark |
| LCOF range (chart1 sweep) | 3 300–6 500 AUD/t | 2–4× import parity |

The LCOF gap to import parity closes with IMO policy premiums (+400/t
Tier-1, +800/t Tier-2) and electrolyser CAPEX decline below 800 AUD/kW.

### Five interacting forces

The answer is not a single breakeven point — it is a surface shaped by:

1. **Electrolyser CAPEX decline** — BNEF central: 2 200 → 500 AUD/kW
   (2026–2040); BNEF slow: 2 400 → 900; IEA NZE: 2 000 → 400.
2. **CO₂ supply cost and availability** — five tranches from steelworks
   DRI off-gas (80/t) through DAC (600→300/t declining); see §4 and
   `co2_supply.py`.
3. **Product price path** — import parity, IMO Tier-1 (+400/t from
   2030), IMO Tier-2 (+800/t from 2033); see `trajectory_ispypsa.py`.
4. **Cost of capital** — FOAK→NOAK step (13%→9% linear, 2030–2035)
   dominates timing of first commercial tranche.
5. **Buffer partition** — MeOH synthesis prefers steady state; the
   optimiser pushes flexibility into the cheap MeOH tank farm, leaving
   H₂ storage as the short-cycle fast buffer.

---

## 1. The flexibility premium revisited

`chart_buffer_partition.py` quantifies the buffer partition at three
MeOH synthesis `min_pu` values (0.3 / 0.5 / 0.7).  Key result: at
`min_pu=0.5`, ~60–70% of buffering moves to MeOH storage (cheap,
ambient-pressure) rather than compressed H₂ (expensive, 20 000 AUD/MWh),
reducing overall system cost vs the DRI-EAF configuration.

---

## 2. The breakeven surface

`chart_breakeven_heatmap.py` produces a 2D heatmap of LCOF − import
parity diesel across the (electrolyser CAPEX × blended CO₂ price) grid,
with IMO Tier-1 and Tier-2 breakeven contours overlaid.

Key results at WACC=11%, year 2030:

- **No-policy breakeven** requires CAPEX < ~600 AUD/kW AND CO₂ < 100 AUD/t
  — achievable only in the IEA NZE scenario by 2038.
- **IMO Tier-1 (+400/t)** breakeven shifts to CAPEX < 1 200 AUD/kW at
  CO₂ = 195 AUD/t; achievable from ~2034 under BNEF central.
- **IMO Tier-2 (+800/t)** breakeven at CAPEX < 1 800 AUD/kW; achievable
  from ~2031 under BNEF central at steelworks CO₂ (80/t).

The static breakeven surface is predominantly red in 2030, turning green
first in the top-left corner (low CAPEX, cheap CO₂, strong policy).

## 3. Cost of capital

The model adopts the FOAK→NOAK step from the DRI-EAF sibling repo:
**13%→9% WACC linear 2030–2035** (`foak_to_noak` path).  The `noak_only`
path (9% flat) is available for de-risked comparison.  CRF values used
in all LCOM/LCOF calculations:

---

## 4. CO₂ supply — five-tranche merit-order curve

`co2_supply.py` implements the merit-order CO₂ supply curve with five
tranches.  The blended price is ~190 AUD/t in 2030 (base weights: 50%
steelworks, 25% Nyrstar, 25% DAC) declining to ~120 AUD/t by 2040.

| Source | AUD/t CO₂ (2030) | AUD/t CO₂ (2040) | Volume | Window |
| --- | ---: | ---: | ---: | --- |
| **Whyalla Steelworks DRI off-gas** | 80 | 80 | 2.0 Mt/yr | 2028–2035 |
| **Nyrstar Port Pirie smelter** | 100 | 100 | 0.4 Mt/yr | always |
| **Santos Moomba CCS** | 100 | 100 | 1.7 Mt/yr | from 2032 |
| **Adbri Birkenhead cement** | 100 | 100 | 1.0 Mt/yr | always |
| **Direct Air Capture** | 500 | 300 | unbounded | always |

Three CO₂ supply paths for scenario runs:
- **`industrial_blend`**: all five tranches (default)
- **`dac_backfill_early`**: DAC + Santos + Adbri (skips steelworks + Nyrstar)

`chart_co2_supply_curve.py` plots the stacked dispatch by source over
2030–2040 with the blended-price overlay.

---

## 5. Transition trajectories — three named scenarios

`trajectory_ispypsa.py` implements a myopic year-by-year solver across
three compound scenarios (crash-resume, argparse CLI).

| Scenario | CAPEX path | CO₂ path | Fuel price | WACC |
| --- | --- | --- | --- | --- |
| **`policy_stated`** | BNEF central | industrial blend | import parity | 13→9% |
| **`imo_binding`** | BNEF central | industrial blend | IMO Tier-2 | 13→9% |
| **`foak_stranded`** | BNEF slow | DAC backfill early | import parity | 13% flat |

Run:

```bash
python trajectory_ispypsa.py --years 2030,2035,2040 --scenarios policy_stated,imo_binding,foak_stranded
```

Output: `trajectory.csv` (year × scenario rows) + `trajectory_state.json`
(crash-resume state).  `chart_trajectory.py` plots a 2×3 panel grid
from this CSV.

---

## 6. The cumulative case

*TODO(§6): equivalent to the DRI-EAF repo's Chart 6.  Cumulative fossil
methanol / VLSFO / Jet A displaced, and the carbon-liability equivalent
under each policy path.*

---

## 7. MeOH synthesis + refinery co-dispatch

*TODO(§7): the key co-dispatch trade-off is different from the DRI-EAF
case.  There are three buffers in series:*

1. *Upstream: **H₂ storage** (compressed, expensive per kWh)*
2. *Middle: **CO₂ storage** (liquid, cheap per tonne, short cycle)*
3. *Downstream: **MeOH storage** (ambient-pressure tank farm, very
   cheap per MWh)*

*Optimal partition: do most of the arbitrage at the MeOH buffer,
because MeOH synthesis itself prefers steady-state operation
(catalyst thermal cycling penalty, though this is debated).  That
inverts the DRI-EAF result where H₂ storage is the primary buffer.*

### 7b. Refinery (placeholder)

The refinery block in `efuels_components.attach_efuels()` accepts a
`refinery_mode` of `None`, `"MTG"`, `"MTJ"`, or `"FT"`, with
placeholder LHV efficiencies (see `efuels_physics.py`).  The link is
sized to zero by default — calibrate per-pathway CAPEX, O&M, and
product price once Section 7 analysis is settled, then enable the mode
in `trajectory_ispypsa.run_trajectory(refinery_mode=...)`.

Pathway sketches for the placeholder:

- **MTG (ExxonMobil / Topsoe TIGAS)** — MeOH → DME → gasoline-range
  hydrocarbons.  44% mass yield, 88% LHV efficiency.  Bankable product
  = MOGAS at refinery gate.
- **MTJ (methanol-to-jet)** — MeOH → olefins → oligomerisation →
  hydrotreating.  ~75–80% LHV efficiency.  Product = drop-in SAF
  (ReFuelEU Aviation Annex I-eligible).
- **FT (Fischer-Tropsch)** — parallel pathway from H₂ + CO (reverse
  water-gas shift to synthesise CO from CO₂ + H₂, then FT synthesis).
  ~60–70% LHV efficiency overall.  Included for completeness; less
  mature than MTJ for SAF.

---

## 8. Synthesis

*TODO(§8): once §§1–7 are populated, write the four or five
paragraph-long key findings in the sibling repo's style.*

---

## Scenarios modelled

*TODO: matrix table once §5 is wired in.*

## Model structure

**Network topology.**  ISPyPSA-derived NEM-wide operational network is
used as the electricity-side substrate.  Whyalla e-fuels components are
grafted on via `attach_efuels()` at the SA Northern sub-region bus
(auto-discovered via `resolve_sa_north_bus()`).  Buses added:

- `H2_Whyalla` (carrier: H2) — electrolyser output, H₂ storage
- `CO2_Whyalla` (carrier: CO2) — aggregated CO₂ supply + short-cycle tank
- `MeOH_Whyalla` (carrier: MeOH) — synthesis output, MeOH tank farm, and
  either direct export offtake or refinery feed
- `Fuel_Whyalla` (carrier: Fuel) — refinery product (zero-sized until
  `refinery_mode` is set)

**Electrolyser + H₂ storage.**  Identical physics to the sibling repo:
PEM at 70% LHV, 20-yr life, CAPEX input parameter; compressed H₂ at
$20k/MWh, 25-yr life.

**Methanol synthesis.**  Single Link, `bus0=H2_Whyalla`,
`bus1=MeOH_Whyalla`, `bus2=CO2_Whyalla`, `bus3=SA_N` (aux electricity).
LHV efficiency 0.83; stoichiometric CO₂ (1.375 t/t MeOH) and aux
electricity (0.3 MWh/t MeOH) flow from their respective buses.

**CO₂ supply.**  Currently a single aggregated `Generator` on
`CO2_Whyalla` at `co2_price_per_t`.  §4 of this README will decompose
this into DAC / biogenic / industrial components with separate marginal
costs and capacity constraints.

**Offtake.**  Both the MeOH and the refinery offtakes are modelled as
negative-marginal-cost sink Generators capped at the plant nameplate,
so the optimiser sizes production endogenously up to the offtake limit.
Swap to fixed-`p_set` Loads once a binding offtake contract anchors the
scenario.

**Time resolution.**  Inherited from ISPyPSA config — 30-minute
operational, weekly rolling horizon with 2-day overlap (same as sibling
repo).  See `ispypsa_config_whyalla.yaml`.

## Caveats and limitations

- **Greenfield assumption.**  The model ignores any shared infrastructure
  savings from co-locating with the existing Whyalla steelworks
  (shared substation, port berth, hydrogen offtake with DRI shaft).  A
  full integrated Whyalla model would couple this repo with the sibling
  DRI-EAF repo at the `SA_N` bus and jointly optimise.
- **CO₂ supply is a scalar marginal cost, not a supply curve.**  Until
  §4 is populated, all CO₂ flows at a single price.
- **Refinery yields are placeholders.**  MTG / MTJ / FT efficiencies are
  literature averages; real-project yields depend heavily on product
  slate and hydrotreating severity.
- **Single weather year, frozen price profile, myopic annual solve.**
  Same caveats as the sibling repo.

## Dependencies

```bash
pip install -r requirements.txt
```

Data acquisition (manual — see `ispypsa_config_whyalla.yaml` header):
AEMO IASR 2024 workbook and ISP 2024 trace data.

In this tree the workbook, trace data, and parsed-workbook cache are
**symlinked** from the sibling repo at `../../Downloads/whyalla/data/`.
See the symlinks in [data/](data/) — no re-download required if the
parent repo already has them.

## File inventory

### Core model

| File | Description |
| --- | --- |
| `efuels_physics.py` | Physical constants and stoichiometry (H₂, CO₂, MeOH, MTG/MTJ/FT efficiencies) |
| `efuels_components.py` | `attach_efuels()` — grafts e-fuels complex onto any PyPSA network at a SA_N bus |
| `efuels_results.py` | `extract_efuels_results()` — electrolyser / MeOH / storage / refinery metrics from a solved network |
| `ispypsa_adapter.py` | ISPyPSA pipeline adapter (build + solve NEM operational network for a given scenario × year) |
| `ispypsa_config_whyalla.yaml` | Base ISPyPSA configuration (symlink-compatible with sibling repo) |

### Verification

| File | Description |
| --- | --- |
| `smoke_ispypsa.py` | Single-year ISPyPSA solve smoke test |
| `test_attach_efuels.py` | Unit tests: electrolyser + MeOH synthesis build/no-build under favourable / hostile economics; refinery mode wiring |

### Trajectory (placeholder)

| File | Description |
| --- | --- |
| `trajectory_ispypsa.py` | Multi-year myopic solver — **placeholder**; scenario matrix not yet populated (see §5) |

## Running order

```bash
# 0. Set up environment
pip install -r requirements.txt

# 1. Verify ISPyPSA wiring
python smoke_ispypsa.py

# 2. Verify Whyalla attachment and solve on a stub network
pytest test_attach_efuels.py -v

# 3. Trajectory — once §5 scenarios are implemented
# python trajectory_ispypsa.py
```

## Next steps

1. **Settle the plant-sizing anchor** — pick A, B, or C from the Thesis
   table and derive the others from it.  Update
   `DEFAULT_MEOH_TONNES_PER_YEAR` and the sizing derivation block.
2. **Populate §4 CO₂ supply scenarios** — replace the single
   `co2_supply` Generator with a supply curve of {Moomba CCS, industrial
   flues, DAC, biogenic} tranches at distinct marginal costs.
3. **Populate §5 scenario matrix** — wire `SCENARIOS` dict in
   `trajectory_ispypsa.py` and run the first pass.
4. **Populate §7b refinery** — calibrate CAPEX, O&M, and product price
   for each of MTG / MTJ / FT; run with `refinery_mode` enabled; report
   whether the raw-MeOH export baseline dominates or the integrated
   refinery does.
5. **Integrated Whyalla model** — couple this repo and the sibling
   DRI-EAF repo at `SA_N` and jointly optimise; test whether the two
   loads cannibalise or complement each other's flexibility premium
   (mirrors §7 of the sibling repo, but with an e-fuels plant as the
   second flex load instead of an EAF).

## References

See the sibling repo README's reference list for shared sources
(IEA GHR 2024, IRENA Green H₂, BNEF LCOH, AEMO ISP 2026 draft, Hydrogen
Council / McKinsey, OECD WP 227, Stegra / HYBRIT capital stacks, etc.).
E-fuels-specific references to be added as §§1–8 are populated:

- IEA (2023). *The Role of E-fuels in Decarbonising Transport.*
- IRENA / Methanol Institute (2021). *Innovation Outlook: Renewable Methanol.*
- European Commission (2023). *ReFuelEU Aviation Regulation* (EU 2023/2405).
- European Commission (2023). *FuelEU Maritime Regulation* (EU 2023/1805).
- IMO MEPC 83 (Apr 2025). *Net-Zero Framework for International Shipping.*
- Carbon Recycling International (2023). *George Olah Renewable Methanol Plant — Operating Data.*
- ExxonMobil / Topsoe. *TIGAS Methanol-to-Gasoline Technology.*
- Australian Government (2024). *Low-Carbon Liquid Fuels Strategy Consultation.*
