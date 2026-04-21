"""Benchmark: full_year vs representative_weeks + IPM.

Runs the dri-eaf model under both modes and prints wall-clock + objective.
"""
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "projects" / "dri-eaf"))

from run import default_config, main  # noqa: E402


def bench(mode: str, weeks: int = 4):
    cfg = default_config()
    cfg = replace(
        cfg,
        scenario=replace(cfg.scenario, snapshot_mode=mode, representative_weeks=weeks),
    )
    t0 = time.time()
    n, m = main(cfg)
    dt = time.time() - t0
    print(f"\n=== mode={mode}{f' N={weeks}' if mode == 'representative_weeks' else ''} ===")
    print(f"  wall_clock_s = {dt:.1f}")
    print(f"  objective    = {m['objective']:.3e}")
    print(f"  lcos_t       = {m['lcos_per_t_steel']:.2f}")
    print(f"  lcoh_kg      = {m['lcoh_per_kg']:.3f}")
    print(f"  ely_mw       = {m['ely_mw']:.1f}")
    print(f"  annual_h2_kg = {m['annual_h2_kg']:.3e}")
    return dt


if __name__ == "__main__":
    bench("representative_weeks", 4)
