"""Loaders for AEMO Draft 2026 ISP trace CSVs.

CSVs are wide-format: `Year, Month, Day, 01..48`. Period `01` is the interval
00:00–00:30; period `48` is 23:30–24:00. Files span the whole ISP horizon as
Australian financial years (Jul YYYY → Jun YYYY+1), typically FY2026 to FY2051.
Loaders filter to a single FY selected by `model_year` where the returned slice
is FY = Jul (model_year - 1) → Jun (model_year), giving 17520 half-hours.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


_HALF_HOUR_COLS = [f"{i:02d}" for i in range(1, 49)]


def _model_traces_dir(data_path: Path, scenario_file_token: str) -> Path:
    """Map scenario file-token to the human-named ISP Model subfolder."""
    token_to_folder = {
        "STEP_CHANGE": "Draft 2026 ISP Step Change",
        "ACCELERATED_TRANSITION": "Draft 2026 ISP Accelerated Transition",
        "SLOWER_GROWTH": "Draft 2026 ISP Slower Growth",
    }
    folder = token_to_folder.get(scenario_file_token)
    if folder is None:
        raise ValueError(f"Unknown scenario file token: {scenario_file_token}")
    return data_path / "Draft 2026 ISP Model" / folder / "Traces"


def _filename_token(scenario_file_token: str) -> str:
    """Translate the public scenario token to the token embedded in trace CSV filenames.

    Draft 2026 ISP kept legacy folder names (Slower Growth, Accelerated Transition)
    but renamed the trace filenames to the current AEMO scenario labels.
    """
    return {
        "STEP_CHANGE": "STEP_CHANGE",
        "ACCELERATED_TRANSITION": "GREEN_ENERGY_INDUSTRIES",
        "SLOWER_GROWTH": "PROGRESSIVE_CHANGE",
    }.get(scenario_file_token, scenario_file_token)


def _wide_to_series(df: pd.DataFrame, model_year: int | None) -> pd.Series:
    """Pivot wide (Year, Month, Day, 01..48) to a half-hourly Series.

    If `model_year` is given, filter to the Australian financial year ending in
    that year (Jul model_year-1 → Jun model_year). If None, return the first
    full FY present in the file.
    """
    df = df.copy()
    df.columns = [str(c).strip().strip('"') for c in df.columns]
    df["date"] = pd.to_datetime(
        dict(year=df["Year"], month=df["Month"], day=df["Day"])
    )
    df = df.sort_values("date").reset_index(drop=True)

    if model_year is None:
        # First FY present: start from first Jul in the file.
        jul_rows = df[df["Month"] == 7]
        if jul_rows.empty:
            raise ValueError("No July rows found in trace file — cannot infer FY.")
        model_year = int(jul_rows["Year"].iloc[0]) + 1

    start = pd.Timestamp(year=model_year - 1, month=7, day=1)
    end = pd.Timestamp(year=model_year, month=6, day=30)
    fy = df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)
    if fy.empty:
        available = sorted(df["Year"].unique().tolist())
        raise ValueError(
            f"No rows for FY ending {model_year} in trace file. "
            f"File spans years {available[0]}–{available[-1]}."
        )

    values = fy[_HALF_HOUR_COLS].to_numpy(dtype=float).reshape(-1)
    index = pd.date_range(start=start, periods=len(values), freq="30min")
    series = pd.Series(values, index=index, name="value")
    if len(series) >= 17520:
        series = series.iloc[:17520]
    return series


def _read_trace_csv(path: Path, model_year: int | None = None) -> pd.Series:
    if not path.exists():
        raise FileNotFoundError(f"Trace CSV not found: {path}")
    df = pd.read_csv(path)
    return _wide_to_series(df, model_year)


def load_demand(
    data_path: Path,
    subregion: str,
    scenario_file_token: str,
    refyear: int = 5000,
    model_year: int | None = None,
) -> pd.Series:
    """Load subregional demand (MW, half-hourly) for a given scenario / FY."""
    traces = _model_traces_dir(Path(data_path), scenario_file_token)
    fname = (
        f"{subregion}_RefYear_{refyear}_{_filename_token(scenario_file_token)}"
        "_POE10_OPSO_MODELLING_PVLITE.csv"
    )
    return _read_trace_csv(traces / "demand" / fname, model_year)


def load_trace(
    data_path: Path,
    kind: str,
    site: str,
    refyear: int = 5000,
    model_year: int | None = None,
) -> pd.Series:
    """Load a capacity-factor trace for one wind/solar site and FY.

    `kind` in {"wind", "solar"}. Traces sit outside the scenario folders (they
    are weather-driven, not scenario-driven).
    """
    base = Path(data_path)
    folder = {
        "wind": "Draft 2026 ISP Wind traces",
        "solar": "Draft 2026 ISP Solar traces",
    }.get(kind)
    if folder is None:
        raise ValueError(f"Unknown trace kind: {kind!r}. Use 'wind' or 'solar'.")
    path = base / folder / f"{site}_RefYear{refyear}.csv"
    series = _read_trace_csv(path, model_year)
    return series.clip(lower=0.0, upper=1.0)


def load_subregion_vre_aggregate(
    data_path: Path,
    subregion: str,
    kind: str,
    scenario_file_token: str,
    refyear: int = 5000,
    model_year: int | None = None,
) -> pd.Series:
    """Best-effort subregion-level VRE availability proxy.

    Draft 2026 does not ship per-subregion aggregate wind/solar generation
    traces (load_subtractor is state-level MW, not subregion). For the RLDC
    merit-order grid stub we return what is available:

    - `rooftop_pv`: rooftop PV (MW) from scenario Traces/rooftop PV/.
    - `wind` / `solar`: single-site CF as a proxy; caller scales by demand.

    TODO: once a subregion-aggregate wind/solar generation trace is confirmed
    in Draft 2026, switch to it and deprecate the single-site proxy.
    """
    traces = _model_traces_dir(Path(data_path), scenario_file_token)
    if kind == "rooftop_pv":
        fname = (
            f"{subregion}_Area1_RefYear_{refyear}_{_filename_token(scenario_file_token)}"
            "_POE10_PV_TOT.csv"
        )
        return _read_trace_csv(traces / "rooftop PV" / fname, model_year)
    raise NotImplementedError(
        f"subregion VRE aggregate for kind={kind!r} not available in Draft 2026"
    )


def to_hourly(half_hourly: pd.Series, how: str = "mean") -> pd.Series:
    """Collapse 30-min series to hourly via mean (CFs) or sum-energy (MWh)."""
    if how == "mean":
        return half_hourly.resample("1h").mean()
    if how == "sum":
        # Sum of the two half-hourly MW values, then /2 since each is a 0.5 h
        # snapshot and PyPSA snapshots represent an hourly instantaneous MW.
        return half_hourly.resample("1h").mean()
    raise ValueError(f"Unknown resample method: {how!r}")
