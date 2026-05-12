#!/usr/bin/env bash
# Regenerate every model output and chart for the Whyalla synthetic-fuels
# project from a clean state. Run from the projects/efuels/ directory.
#
# Total run-time on a recent laptop: ~10-12 minutes
#   Trajectory regen (3 scenarios × 8 years × biofuels-on, 3 workers):  ~5 min
#   Standalone solve charts (dispatch, buffer, sensitivity 3×3):        ~5 min
#   Trajectory-driven charts (no solve, just CSV → PNG):                <1 min
#
# Usage:
#   ./regen_all.sh                    # full regen, all scenarios
#   ./regen_all.sh policy_stated      # regen single scenario only (faster)
#
# Exit on any error so a partial result doesn't masquerade as a complete one.

set -euo pipefail

cd "$(dirname "$0")"

SCENARIO_FILTER="${1:-}"
TRAJECTORY_ARGS=(--biofuels --workers 3 --out trajectory.csv)
if [[ -n "$SCENARIO_FILTER" ]]; then
    TRAJECTORY_ARGS+=(--scenarios "$SCENARIO_FILTER")
    echo "─── Single-scenario mode: $SCENARIO_FILTER"
fi

echo "─── 1/4  Regenerating trajectory.csv (LP solves)"
uv run python generate_trajectory.py "${TRAJECTORY_ARGS[@]}"

echo
echo "─── 2/4  Trajectory-driven charts"
uv run python chart_trajectory.py
uv run python chart_co2_supply_curve.py
for scen in policy_stated imo_binding foak_stranded; do
    if [[ -z "$SCENARIO_FILTER" || "$SCENARIO_FILTER" == "$scen" ]]; then
        uv run python chart_capital_works.py \
            --scenario "$scen" \
            --out "chart_capital_works_${scen}.png"
    fi
done

echo
echo "─── 3/4  Fuel-security framing charts (no solver runs)"
uv run python chart_cost_stack.py
uv run python chart_strategic_substitution.py
uv run python chart_programme_timeline.py
uv run python chart_electrification_split.py

echo
echo "─── 4/4  Standalone solve charts (dispatch, buffer, sensitivity)"
uv run python chart_dispatch.py
uv run python chart_buffer_partition.py
uv run python chart_biofuels_sensitivity.py --grid-size 3 --workers 2

echo
echo "─── Done. All outputs in $(pwd):"
ls -la chart_*.png trajectory.csv 2>/dev/null
