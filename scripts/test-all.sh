#!/usr/bin/env bash
# Run all three test trees in isolation.
# Flat-layout project modules (process_chain.py etc.) would otherwise collide
# under a single pytest session, so each tree runs in its own invocation.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" && python -m pytest tests/ -v
cd "$ROOT/projects/dri-eaf" && python -m pytest -v
cd "$ROOT/projects/efuels" && python -m pytest test_attach_efuels.py tests/ -v
