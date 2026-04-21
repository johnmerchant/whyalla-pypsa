# Migration: ISPyPSA → whyalla-pypsa

## What changed

This project has been refactored to use a shared custom PyPSA facility-network core (`whyalla-pypsa`) instead of the national grid capacity-expansion tool ISPyPSA. The focus is now purely facility-level techno-economics for e-fuels (hydrogen, methanol, ASF products) at Whyalla.

## Dropped

- **ISPyPSA dependency** — no longer required
- **NEM capacity expansion** — facility is price-taker on a merit-order grid proxy
- **Old price-taker scripts and components** — `efuels_components.py`, `efuels_pricetaker.py`
- **ISPyPSA-tied file I/O** — old data loaders, pickle caches

## Retained

- AEMO Draft 2026 ISP input data (wind/solar traces, demand, rooftop PV) in `~/Downloads/Draft 2026 ISP/`
- Wide CSV format (Year/Month/Day/01-48 columns) with proper Australian FY filtering via `model_year` parameter in `whyalla_pypsa.data.aemo_draft_2026`
- LCOM / LCOF modelling intent (methanol, diesel, naphtha, kerosene, wax)
- Schulz-Flory carbon-chain distribution (alpha parameter) and blended CO2 supply curve (steelworks, DAC, merit-order tranches)

## Added

The shared `whyalla-pypsa` core provides:

- `FacilityConfig`, cost-assumption dataclasses, `ScenarioConfig`
- `build_facility_network()` — wind, solar, battery, H2 storage, bidirectional grid link
- `attach_grid_price()` with RLDC merit-order proxy (CSA subregion default)
- `annuitise()`, `levelised_cost()` with component-specific WACC overlay (applied post-solve)
- `run_sweep()` for parametric sweeps

## Reproducing prior results

1. **Install dependencies** (from `projects/efuels/`):
   ```
   pip install -r requirements.txt   # installs shared core via -e ../.. plus deps
   ```

2. **Ensure AEMO data exists:**
   - Check `~/Downloads/Draft 2026 ISP/` contains `data/` and CSV files
   - Or symlink it into `./data/` if stored elsewhere

3. **Run a single scenario:**
   ```
   python run.py
   ```

4. **Run a parametric sweep:**
   ```
   python sweep_example.py
   ```

5. **Validate results against prior spreadsheets:**
   ```
   python validate.py
   ```

6. **Run tests:**
   ```
   python -m pytest -v
   ```

## Key differences vs. prior workflow

- **Grid price is a merit-order proxy**, not a solved NEM dispatch — it uses RLDC (regional load duration curve) with demand offset to estimate the marginal cost seen at Whyalla
- **No capacity expansion** — wind, solar, battery, and H2 storage are sized for the facility only; grid capacity is fixed and not optimized
- **Component-specific WACC overlay** is applied *after* optimization — capex is converted to annuity via CRF, then combined with opex in `extract_lcom_lcof()` — not solved within PyPSA
- **Simpler, faster solves** — local facility network (wind + solar + battery + H2 storage + electrolyser + synthesis + refinery + grid link) vs. entire NEM
