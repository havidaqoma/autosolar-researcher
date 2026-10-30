"""Hourly engineer files rebuilt from the study inputs and cached weather.

No network, no file writes. Power in kW, energy in kWh, fuel in l.
"""

from __future__ import annotations

import math
import numbers

import numpy as np
import pandas as pd

from autosolar.dispatch import Battery, DispatchResult, dispatch

ENGINEER_FILES_SCHEMA = "autosolar.engineer_files/1"
REL_TOL = 1e-9
HOMER_LINES = 8760
HOURLY_CSV_COLUMNS = (
    "time_utc",
    "time_local",
    "ghi_w_m2",
    "temp_air_degc",
    "wind_speed_m_s",
    "load_kw",
    "pv_ac_kw_per_kwp",
    "pv_kw",
    "pv_to_load_kw",
    "pv_to_battery_kw",
    "pv_curtailed_kw",
    "battery_discharge_kw",
    "soc_kwh",
    "diesel_kw",
    "diesel_units_on",
    "unserved_kw",
    "fuel_l",
)
NOTE = "Rebuilt from the study's inputs and cached weather. The study itself is unchanged."

_WEATHER_COLUMNS = ("ghi_w_m2", "temp_air_degc", "wind_speed_m_s")
_RESULT_COLUMNS = (
    "pv_kw",
    "pv_to_load_kw",
    "pv_to_battery_kw",
    "pv_curtailed_kw",
    "battery_discharge_kw",
    "soc_kwh",
    "diesel_kw",
    "diesel_units_on",
    "unserved_kw",
    "fuel_l",
)


def _check_amount(name_str: str, value: object, *, allow_zero: bool) -> float:
    """Finite real, bool refused, range checked. Returns float."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(name_str + " must be a number: " + repr(value))
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " must be finite: " + repr(value))
    if allow_zero:
        if out < 0.0:
            raise ValueError(name_str + " must be >= 0: " + repr(value))
    elif out <= 0.0:
        raise ValueError(name_str + " must be above 0: " + repr(value))
    return out


def main_design_dispatch(
    pv_ac_kw_per_kwp: pd.Series,
    load_kw: pd.Series,
    *,
    main_pv_kwp: float,
    main_battery_kwh: float,
    battery_hours: float,
    battery_template: Battery,
    diesel: object,
) -> DispatchResult:
    """Dispatch the study main design. Power in kW, energy in kWh, fuel in l."""
    pv_f = _check_amount("main_pv_kwp", main_pv_kwp, allow_zero=True)
    bat_f = _check_amount("main_battery_kwh", main_battery_kwh, allow_zero=True)
    hours_f = _check_amount("battery_hours", battery_hours, allow_zero=False)
    if not isinstance(battery_template, Battery):
        raise ValueError("battery_template must be a Battery: " + repr(battery_template))
    if bat_f == 0.0:
        battery = Battery(
            energy_kwh=0.0,
            power_kw=0.0,
            round_trip_eff_frac=battery_template.round_trip_eff_frac,
            soc_min_frac=battery_template.soc_min_frac,
            soc_initial_frac=battery_template.soc_initial_frac,
        )
    else:
        battery = Battery(
            energy_kwh=bat_f,
            power_kw=bat_f / hours_f,
            round_trip_eff_frac=battery_template.round_trip_eff_frac,
            soc_min_frac=battery_template.soc_min_frac,
            soc_initial_frac=battery_template.soc_initial_frac,
        )
    return dispatch(pv_ac_kw_per_kwp * float(pv_f), load_kw, battery, diesel)


def _check_weather_frame(weather_frame: object) -> pd.DatetimeIndex:
    """Weather frame index. Raises ValueError on bad input."""
    if not isinstance(weather_frame, pd.DataFrame):
        raise ValueError("weather_frame must be a DataFrame")
    for col in _WEATHER_COLUMNS:
        if col not in weather_frame.columns:
            raise ValueError("weather_frame holds no " + col + " column")
    idx = weather_frame.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("weather_frame index must be a DatetimeIndex")
    if idx.tz is None:
        raise ValueError("weather_frame index must be time zone aware")
    return idx


def _check_same_index(name_str: str, series: object, idx: pd.DatetimeIndex) -> None:
    """Series index must equal the weather index. Raises ValueError."""
    if not isinstance(series, pd.Series):
        raise ValueError(name_str + " must be a pandas Series")
    if not series.index.equals(idx):
        raise ValueError(name_str + " index must equal the weather_frame index")


def hourly_frame(
    weather_frame: pd.DataFrame,
    pv_ac_kw_per_kwp: pd.Series,
    load_kw: pd.Series,
    result: DispatchResult,
    local_tz: str,
) -> pd.DataFrame:
    """One row per hour with weather, load, PV and dispatch flow. Returns frame."""
    idx = _check_weather_frame(weather_frame)
    _check_same_index("pv_ac_kw_per_kwp", pv_ac_kw_per_kwp, idx)
    _check_same_index("load_kw", load_kw, idx)
    if not isinstance(result, DispatchResult):
        raise ValueError("result must be a DispatchResult")
    if not isinstance(result.hourly, pd.DataFrame):
        raise ValueError("result.hourly must be a DataFrame")
    if not result.hourly.index.equals(idx):
        raise ValueError("result.hourly index must equal the weather_frame index")
    for col in _RESULT_COLUMNS:
        if col not in result.hourly.columns:
            raise ValueError("result.hourly holds no " + col + " column")
    try:
        utc = idx.tz_convert("UTC")
        local = idx.tz_convert(local_tz)
    except Exception as exc:
        raise ValueError("local_tz not accepted by tz_convert: " + repr(local_tz)) from exc
    data: dict[str, object] = {
        "time_utc": list(utc.strftime("%Y-%m-%d %H:%M")),
        "time_local": list(local.strftime("%Y-%m-%d %H:%M")),
        "ghi_w_m2": weather_frame["ghi_w_m2"].to_numpy(),
        "temp_air_degc": weather_frame["temp_air_degc"].to_numpy(),
        "wind_speed_m_s": weather_frame["wind_speed_m_s"].to_numpy(),
        "load_kw": load_kw.to_numpy(),
        "pv_ac_kw_per_kwp": pv_ac_kw_per_kwp.to_numpy(),
    }
    for col in _RESULT_COLUMNS:
        data[col] = result.hourly[col].to_numpy()
    return pd.DataFrame({key: data[key] for key in HOURLY_CSV_COLUMNS})


def _check_homer_load(load_kw: object) -> pd.DatetimeIndex:
    """HOMER load series and index. Raises ValueError on bad input."""
    if not isinstance(load_kw, pd.Series):
        raise ValueError("load_kw must be a pandas Series")
    idx = load_kw.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("load_kw index must be a DatetimeIndex")
    if idx.tz is None:
        raise ValueError("load_kw index must be time zone aware")
    if len(load_kw) != HOMER_LINES:
        raise ValueError("load_kw must hold exactly %d rows: %d" % (HOMER_LINES, len(load_kw)))
    if pd.api.types.is_bool_dtype(load_kw.dtype):
        raise ValueError("load_kw must hold numbers")
    if not pd.api.types.is_numeric_dtype(load_kw.dtype):
        raise ValueError("load_kw must hold numbers")
    try:
        vals = load_kw.to_numpy(dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError("load_kw must hold numbers") from exc
    if not bool(np.isfinite(vals).all()):
        raise ValueError("load_kw must be finite")
    diffs = idx.to_series().diff().dropna()
    if bool((diffs != pd.Timedelta(hours=1)).any()):
        raise ValueError("load_kw index must step exactly one hour")
    return idx


def homer_load_lines(load_kw: pd.Series, local_tz: str) -> list[str]:
    """Load in kW, one line, starting at local midnight on 1 January. Returns lines."""
    idx = _check_homer_load(load_kw)
    try:
        local = idx.tz_convert(local_tz)
    except Exception as exc:
        raise ValueError("local_tz not accepted by tz_convert: " + repr(local_tz)) from exc
    hits = [
        pos
        for pos, stamp in enumerate(local)
        if stamp.month == 1 and stamp.day == 1 and stamp.hour == 0 and stamp.minute == 0
    ]
    if not hits:
        raise ValueError("no stamp is at local midnight on 1 January for " + str(local_tz))
    pos0 = hits[0]
    vals = load_kw.to_numpy(dtype=float).tolist()
    ordered = vals[pos0:] + vals[:pos0]
    return [format(val, ".6f") for val in ordered]


def _matches(got: float, want: float) -> bool:
    """Two floats match within REL_TOL. Returns bool."""
    return abs(float(got) - float(want)) <= REL_TOL * max(1.0, abs(float(want)))


def reproduction_errors(
    report: dict,
    frame: pd.DataFrame,
    result: DispatchResult,
    basis_case: str,
) -> list[str]:
    """Messages where the files miss the study numbers. Empty when all match."""
    errs: list[str] = []
    facts = report["facts"]

    def check(name_str: str, got: float, want: float) -> None:
        """Append a message when got misses want. Returns None."""
        if not _matches(got, want):
            errs.append("%s: got %s want %s" % (name_str, float(got), float(want)))

    check("demand_kwh_yr", float(frame["load_kw"].sum()), float(facts["demand_kwh_yr"]["value"]))
    check("demand_peak_kw", float(frame["load_kw"].max()), float(facts["demand_peak_kw"]["value"]))
    hit = None
    for row in report["weather_table"]:
        if row.get("case") == basis_case:
            hit = row
            break
    if hit is None:
        errs.append("weather_table: no row with case " + str(basis_case))
    else:
        check(
            "yield_kwh_kwp_yr",
            float(frame["pv_ac_kw_per_kwp"].sum()),
            float(hit["yield_kwh_kwp_yr"]),
        )
    check("best_fuel_l_yr", float(frame["fuel_l"].sum()), float(facts["best_fuel_l_yr"]["value"]))
    firm = report.get("firmness")
    if isinstance(firm, dict):
        by_key = {item["key"]: item for item in firm.get("items", [])}
        if "best_unserved_kwh_yr" in by_key:
            check(
                "best_unserved_kwh_yr",
                float(frame["unserved_kw"].sum()),
                float(by_key["best_unserved_kwh_yr"]["value"]),
            )
        if "best_diesel_run_hours" in by_key:
            check(
                "best_diesel_run_hours",
                float(result.diesel_run_hours),
                float(by_key["best_diesel_run_hours"]["value"]),
            )
        if "best_diesel_starts" in by_key:
            check(
                "best_diesel_starts",
                float(result.diesel_starts),
                float(by_key["best_diesel_starts"]["value"]),
            )
    return errs


def engineer_doc(
    report: dict,
    *,
    run_id: str,
    basis_case: str,
    local_tz: str,
    frame: pd.DataFrame,
    result: DispatchResult,
    homer_lines: list[str],
    errors: list[str],
    files: dict,
    wall_s: float,
) -> dict:
    """JSON-able record for one engineer files run. Returns dict."""
    return {
        "schema": ENGINEER_FILES_SCHEMA,
        "run_id": run_id,
        "study_run_hash": report["run_hash"],
        "basis_case": basis_case,
        "local_tz": local_tz,
        "rows": len(frame),
        "columns": list(frame.columns),
        "homer_lines": len(homer_lines),
        "sums": {
            "load_kwh": float(frame["load_kw"].sum()),
            "peak_kw": float(frame["load_kw"].max()),
            "pv_kwh_per_kwp": float(frame["pv_ac_kw_per_kwp"].sum()),
            "fuel_l": float(frame["fuel_l"].sum()),
            "unserved_kwh": float(frame["unserved_kw"].sum()),
            "diesel_run_hours": int(result.diesel_run_hours),
            "diesel_starts": int(result.diesel_starts),
        },
        "files": dict(files),
        "reproduced": len(errors) == 0,
        "reproduction_errors": list(errors),
        "wall_s": float(wall_s),
        "note": NOTE,
    }
