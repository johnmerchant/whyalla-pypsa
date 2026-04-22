# whyalla-pypsa

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

> **Disclaimer:** This is independent citizen/enthusiast research, not professional engineering or financial advice. It is not affiliated with or endorsed by any institution, organisation, or employer. Much of the code and analysis was generated with the assistance of generative AI tools. Use at your own discretion.

Facility-level techno-economic analysis at Whyalla, SA.

## Layout

```
whyalla-pypsa/
├── src/whyalla_pypsa/     shared facility-network core
├── tests/                 core tests
├── projects/
│   ├── dri-eaf/           H2-DRI + EAF steel (LCOH / LCOS)
│   └── efuels/            electrolyser + synthesis + ASF (LCOM / LCOF)
└── scripts/test-all.sh    run all three test trees
```

The shared core (`whyalla_pypsa`) provides `FacilityConfig`,
`build_facility_network()`, `attach_grid_price()`, `annuitise()`,
`levelised_cost()` and `run_sweep()`. Each project adds its own process chain
(electrolyser, DRI, EAF, synthesis, CO2 supply, etc.) on top.

Grid price is an RLDC merit-order proxy driven by AEMO Draft 2026 ISP inputs;
capex is annuitised post-solve via a component-specific WACC overlay.

## Install

```
# core
uv sync

# per-project deps (core is pulled in as -e ../..)
uv pip install -r projects/dri-eaf/requirements.txt
uv pip install -r projects/efuels/requirements.txt
```

## Run

```
# single scenario
cd projects/dri-eaf && uv run python run.py
cd projects/efuels && uv run python run.py

# parametric sweeps
uv run python sweep_example.py
```

## Test

```
uv run scripts/test-all.sh
```

Each project uses a flat module layout (e.g. `process_chain.py` at its root),
so tests run per-project rather than through a single pytest session — the
script invokes three pytests in sequence.

## Data

AEMO Draft 2026 ISP CSVs are expected at `~/Downloads/Draft 2026 ISP/` by
default. Override via `FacilityConfig.data_path`.
