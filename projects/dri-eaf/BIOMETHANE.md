# SA Biomethane Availability — PyPSA Modelling Spec

Handoff document for setting up biomethane supply in a PyPSA model of the SA gas network, 2026–2045.

---

## 1. Scope & boundary

- **Geography**: SA gas network (AGN distribution + APA/Epic transmission-connected industrial). Bus mapping: at minimum a single `gas_SA` bus; preferred two-bus split `gas_dist_SA` (AGN distribution, Adelaide metro + outer) and `gas_tx_SA` (transmission-connected industrial loads e.g. Whyalla, Pelican Point, Torrens Island).
- **Time horizon**: 2026–2045, annual investment periods. Hourly resolution within each period optional — biomethane operates as baseload supply, no diurnal/seasonal profile other than maintenance outages.
- **Carriers to define**: `natural_gas`, `biomethane`, `RGGO` (decoupled environmental attribute, optional), `biogenic_CO2_avoid` (for ACCU shadow pricing if modelled).
- **Out of scope for this spec**: hydrogen blends, synthetic methane, LNG imports. Add separately if required.

---

## 2. Project pipeline (high-confidence anchor)

| Project | Bus | Commission | Stage 1 (PJ/yr) | Stage 2 (PJ/yr) | Source |
|---|---|---|---|---|---|
| Delorean SA1 Salisbury | `gas_dist_SA` | 2026 | 0.21 | 0.40 (Stage 2 conditional, ~2028 FID assumed) | [1], [2], [3] |

**Status as of April 2026**: SA1 Stage 1 in commissioning, Origin take-or-pay agreement effective April 2026 [1]. ARENA grant 62% disbursed [3]. No other named SA biomethane project in public funding pipeline.

---

## 3. Annual availability time series (PJ/yr injected to SA network)

Three scenarios. Use as `p_nom_max` constraint or `e_sum_max` annual energy constraint per generator.

| Year | Status Quo | Policy Enabled | Resource Ceiling |
|---|---|---|---|
| 2026 | 0.10 | 0.10 | 0.10 |
| 2027 | 0.21 | 0.21 | 0.21 |
| 2028 | 0.21 | 0.25 | 0.30 |
| 2029 | 0.30 | 0.40 | 0.50 |
| 2030 | 0.35 | 0.60 | 0.90 |
| 2031 | 0.40 | 0.80 | 1.30 |
| 2032 | 0.45 | 1.00 | 1.80 |
| 2033 | 0.50 | 1.30 | 2.40 |
| 2034 | 0.55 | 1.60 | 3.00 |
| 2035 | 0.60 | 2.00 | 3.80 |
| 2036 | 0.70 | 2.30 | 4.50 |
| 2037 | 0.80 | 2.60 | 5.20 |
| 2038 | 0.90 | 3.00 | 6.00 |
| 2039 | 1.00 | 3.30 | 6.80 |
| 2040 | 1.10 | 3.60 | 7.50 |
| 2042 | 1.30 | 4.20 | 8.50 |
| 2045 | 1.60 | 5.00 | 9.50 |

**Conversion to PyPSA energy units**: 1 PJ/yr = 277,778 MWh/yr (i.e. multiply PJ by 277.778 to get GWh).

```python
# Example annual energy budget per scenario (MWh/yr)
biomethane_mwh = {
    "status_quo":      {2026: 27_778, 2030: 97_222, 2035: 166_667, 2040: 305_556, 2045: 444_444},
    "policy_enabled":  {2026: 27_778, 2030: 166_667, 2035: 555_556, 2040: 1_000_000, 2045: 1_388_889},
    "resource_ceiling":{2026: 27_778, 2030: 250_000, 2035: 1_055_556, 2040: 2_083_333, 2045: 2_638_889},
}
```

**Trigger gates for non-status-quo scenarios** (encode as binary scenario switches):
- Federal Renewable Fuel Scheme certificate market liquidity from 2028 [4]
- SA-specific demand-side mechanism (mandate, anchor offtake, or carbon price)
- ≥2 follow-on SA proponents reaching FID by 2032

---

## 4. Cost assumptions (A$/GJ delivered, including RGGOs)

Three-step supply curve per ACIL Allen 2024 / ENA 2025 methodology [5], [6]:

| Cost step | Feedstock type | A$/GJ (2026) | A$/MWh (2026) | SA share of national 50 PJ first tranche |
|---|---|---|---|---|
| Tier 1 | Landfill gas | 8–12 | 29–43 | ~0.5 PJ [6] |
| Tier 2 | AD of C&I food/wastewater | 14–20 | 50–72 | 2–4 PJ |
| Tier 3 | AD of crop residues | 22–30 | 79–108 | 1–4 PJ |

**SA1 implied delivered price**: A$15–20/GJ (A$54–72/MWh), Origin take-or-pay including RGGOs [1].

**CPI escalation**: 2.77% (per ACIL Allen 2024 IASR assumption [5]) — apply to marginal_cost time series.

```python
# Generator marginal_cost in A$/MWh by scenario, including RGGO premium
mc_AUD_per_MWh = {
    "tier1_landfill": 36,    # midpoint
    "tier2_AD_waste": 61,    # midpoint, SA1 sits here
    "tier3_AD_crop":  93,    # midpoint
}
# Escalate by (1.0277)^(year-2026) for time-varying cost
```

---

## 5. Emissions parameters (PyPSA `co2_emissions` on carriers)

| Carrier | t CO₂/MWh | Notes |
|---|---|---|
| `natural_gas` (combustion only) | 0.1853 | NGER pipeline-distributed factor 51.4 kg CO₂-e/GJ [7] |
| `natural_gas` (lifecycle, AU) | 0.216–0.234 | Adds ~10 kg/GJ upstream fugitive CH₄ |
| `biomethane` (combustion only) | 0 | Biogenic carbon, NGER scope 1 |
| `biomethane` (production lifecycle) | 0.018–0.054 | 5–15 kg CO₂-e/GJ; AD parasitic load + upgrading slip |
| `biomethane` (system boundary, waste-derived) | -0.90 to -1.08 | Avoided landfill credit, only when modelling ACCU revenue [8] |

**Recommended modelling defaults for SA1-class projects**: combustion-only for Scope 1 substitution claims (RGGO retirement); production-lifecycle for fair commodity comparison; system boundary only if ACCU revenue is being explicitly stacked.

---

## 6. PyPSA component definitions (skeleton)

```python
import pypsa
n = pypsa.Network()

# Carriers
n.add("Carrier", "natural_gas", co2_emissions=0.1853)
n.add("Carrier", "biomethane", co2_emissions=0.0)  # combustion-only frame
n.add("Carrier", "RGGO", co2_emissions=0.0)

# Buses
n.add("Bus", "gas_dist_SA", carrier="natural_gas")
n.add("Bus", "gas_tx_SA", carrier="natural_gas")

# Biomethane generator (SA1 Stage 1 anchor case)
n.add("Generator",
      "biomethane_SA1_S1",
      bus="gas_dist_SA",
      carrier="biomethane",
      p_nom=24.0,                    # MW: 0.21 PJ/yr / 8760h × 1000 = 24 MW continuous
      p_nom_extendable=False,
      marginal_cost=61.0,            # A$/MWh delivered (tier 2)
      committable=False,
      efficiency=1.0)

# Aggregate "future SA biomethane" (scenario-dependent capacity)
n.add("Generator",
      "biomethane_SA_future",
      bus="gas_dist_SA",
      carrier="biomethane",
      p_nom_extendable=True,
      p_nom_min=0,
      p_nom_max=<scenario_value>,    # MW from time series above
      marginal_cost=<tier-weighted>,
      capital_cost=0)                # capex captured in marginal_cost via PPA pricing
```

**Note on annual energy constraint**: PyPSA doesn't natively constrain annual generator output. Three options:
1. Set `p_nom` such that `p_nom × 8760 = annual_PJ_in_MWh` and run as baseload (simplest).
2. Use a `Store` with daily/weekly throughput limits if modelling intra-year flexibility.
3. Add custom Pyomo constraint `sum(p_t) <= annual_budget` per investment period.

For this forecast, option 1 is appropriate — biomethane is fundamentally limited by feedstock flow rate, not storage.

---

## 7. Scenario triggers (binary switches in config)

```yaml
scenarios:
  status_quo:
    sa_mandate: false
    rfs_price_AUD_per_GJ: 5
    follow_on_projects: 1   # Stage 2 only
  policy_enabled:
    sa_mandate: true
    rfs_price_AUD_per_GJ: 12
    follow_on_projects: 4
  resource_ceiling:
    sa_mandate: true
    rfs_price_AUD_per_GJ: 20
    follow_on_projects: 8
    eu_repower_eu_analogue: true   # National policy step-change assumed
```

---

## 8. Demand-side anchors (for sanity-checking biomethane share)

| Year | SA distribution gas demand (PJ/yr) | Source |
|---|---|---|
| 2025 (actual) | ~24 | AGN SA serves >480,000 connections [9] |
| 2030 (Step Change) | 18–20 | AEMO 2025 GSOO [10] |
| 2035 (Step Change) | 13–16 | AEMO 2025 GSOO [10] |
| 2040 (Step Change) | 10–13 | AEMO 2025 GSOO [10] |
| 2044 (Step Change) | 8–11 | AEMO 2025 GSOO [10] |

**Implied biomethane share of distribution network**:
- Status Quo 2030: ~2%; 2040: ~10%
- Policy Enabled 2030: ~3%; 2040: ~30%
- Resource Ceiling 2040: ~70% (approaches AGIG's voluntary 100%-by-2050 ambition [11])

---

## 9. Key sensitivities to sweep

Ranked by 2030 forecast variance:
1. **`rfs_price_AUD_per_GJ`** — sweep 0–25 in increments of 5
2. **`sa_mandate`** boolean — counterfactual for each price
3. **`landfill_capture_rate_SA`** — affects ACCU revenue stack; 29% (current) → 60% (regulated) → 90% (fully captured) [8]
4. **`feedstock_diversion_mandate_year`** — when does SA mandate FOGO/EfW for C&I waste? Erodes gate fee revenue
5. **`network_connection_cost_AUD_per_proj`** — AGN SA access arrangement July 2026–June 2031 [12] sets pass-through

---

## 10. Validation tests

- 2026 output ≈ 0.10 PJ in all scenarios (SA1 Stage 1 ramp).
- 2030 status quo output ≤ 0.5 PJ.
- All scenarios respect ENA national ceiling of 50 PJ first tranche [6] when scaled across all states.
- Marginal cost ≥ A$10/GJ in all years (ENA lower bound).
- Biomethane share never exceeds AGN distribution demand (no negative natural gas).
- ACCU credit not double-counted with RGGO retirement on the same molecule.

---

## 11. Open data needs (flagged for John's follow-up)

- AGN SA access arrangement 2026-31 final determination — biomethane connection cost socialisation [12].
- AEMO 2026 ISP final IASR — updated biomethane supply curves [13].
- SA Government renewable gas position post-March 2026 election (no current mandate).
- Federal Renewable Fuel Scheme certificate scheme rules (active from 2028).

---

## Citations

[1] Delorean Corporation ASX Announcement, "Major Biomethane Gas Supply Deal with Origin Energy", 8 September 2025 — https://announcements.asx.com.au/asxpdf/20250908/pdf/06ny1bmtcz74ck.pdf

[2] AGIG, "New Agreement Paves the Way for AGIG's First Biomethane Connection", April 2025 — https://www.agig.com.au/new-agreement-paves-the-way-for-agigs-first-biomethane-connection

[3] Delorean SA1 Salisbury Bioenergy Plant project page — https://deloreancorporation.com.au/projects/sa1-salisbury-bioenergy-plant/ ; ARENA project page — https://arena.gov.au/projects/delorean-sa1-biomethane-upgrading-project/

[4] Austrade, "Abundant feedstocks and growing industry demand to fuel biomethane investment in Australia", March 2026 — https://international.austrade.gov.au/en/news-and-analysis/news/abundant-feedstocks-and-growing-industry-demand-to-fuel-biomethane-investment-in-australia

[5] ACIL Allen for AEMO, *Gas, liquid fuel, coal and renewable gas projections — Final report* (2024 IASR fuel price forecast input) — https://www.aemo.com.au/-/media/files/major-publications/isp/2025/acil-allen-2024-fuel-price-forecast-report.pdf

[6] Energy Networks Australia, *Biomethane Opportunities to Decarbonise Australian Industry*, July 2025 — https://www.energynetworks.com.au/resources/reports/biomethane-opportunities-to-decarbonise-australian-industry/

[7] National Greenhouse and Energy Reporting (NGER) factor of 51.4 kg CO₂-e/GJ for natural gas distributed in a pipeline. Cited in Blunomy/AGIG 2024 study — https://theblunomy.com/static/0b57f58eddebfefd73ceaeea41b846ab/blunomy_agig_biomethane_potential_and_co-benefits.pdf

[8] Delorean / ARENA, *SA1 Bioenergy Facility Public LCA Summary*, September 2025 — https://arena.gov.au/assets/2025/11/Delorean-SA1-Biomethane-Upgrading-Proof-of-Concept-LCA-Public-Summary.pdf (-66 kt CO₂-e/yr net system benefit, 29% SA average landfill capture rate assumed)

[9] AGN South Australia network description and customer base — https://www.agig.com.au/australian-gas-networks ; AGIG corporate overview — https://www.agig.com.au/biomethane

[10] AEMO, *2025 Gas Statement of Opportunities*, March 2025 — https://www.aemo.com.au/-/media/files/gas/national_planning_and_forecasting/gsoo/2025/2025-gas-statement-of-opportunities.pdf ; methodology — https://www.aemo.com.au/-/media/files/gas/national_planning_and_forecasting/gsoo/2025/gsoo-methodology-demand-forecasting.pdf

[11] AGIG corporate target of 100% carbon-neutral gas by 2050 with 10% renewable gas blend by 2030 — https://www.agig.com.au/australia-network-is-hydrogen-ready

[12] AGN SA Access Arrangement July 2026–June 2031, AGIG/AER consultation — https://gasmatters.agig.com.au/australian-gas-networks-south-australia-access-arrangement-2026-27-2030-31/widgets/442451/documents

[13] AGIG submission to AEMO 2025 ISP Stage 2 (citing Blunomy 63 PJ AGIG-catchment estimate, Deloitte 349 PJ national bioenergy estimate) — https://www.aemo.com.au/-/media/files/major-publications/isp/2025/stage-2-submissions/agigpdf.pdf

[14] Blunomy/AGIG, *Biomethane Potential in AGIG's Network Catchment and Associated Co-benefits*, July 2024 — https://theblunomy.com/static/0b57f58eddebfefd73ceaeea41b846ab/blunomy_agig_biomethane_potential_and_co-benefits.pdf

[15] Energy Networks Australia, "Are we up the GSOO without renewable gas?" (commentary on AEMO 30 PJ/y by 2031 figure) — https://www.energynetworks.com.au/news/are-we-up-the-gsoo-without-renewable-gas/

---

## Quick numerical reference card

```
1 PJ/yr     = 277,778 MWh/yr = 31.7 MW continuous
A$1/GJ      = A$3.60/MWh
1 GJ NG     = 51.4 kg CO₂-e (NGER scope 1, pipeline)
SA1 nameplate = 0.21 PJ/yr = 24 MW = ~58.3 GWh/yr
SA AGN demand 2025 ≈ 24 PJ/yr ≈ 6,667 GWh/yr ≈ 761 MW continuous
```