"""Hourly dispatch of PV, battery and diesel. Power in kW, energy in kWh."""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass

import numpy as np
import pandas as pd

HOURLY_COLUMNS = (
    "load_kw",
    "pv_kw",
    "pv_to_load_kw",
    "pv_to_battery_kw",
    "pv_curtailed_kw",
    "battery_discharge_kw",
    "diesel_kw",
    "diesel_to_load_kw",
    "diesel_to_battery_kw",
    "diesel_excess_kw",
    "diesel_units_on",
    "unserved_kw",
    "soc_kwh",
    "fuel_l",
)


def _as_float(name_str: str, value: object) -> float:
    """Value as a finite float. Raises ValueError naming the field."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(name_str + " must be a number: " + repr(value))
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " must be finite: " + repr(value))
    return out


def _check_battery(battery: object) -> tuple[float, float, float, float, float]:
    """Check Battery fields. Returns energy, power, rte, soc min, soc init."""
    if not isinstance(battery, Battery):
        raise ValueError("battery must be a Battery: " + repr(battery))
    energy_kwh = _as_float("energy_kwh", battery.energy_kwh)
    if energy_kwh < 0.0:
        raise ValueError("energy_kwh must be >= 0: " + repr(battery.energy_kwh))
    power_kw = _as_float("power_kw", battery.power_kw)
    if power_kw < 0.0:
        raise ValueError("power_kw must be >= 0: " + repr(battery.power_kw))
    if energy_kwh == 0.0 and power_kw != 0.0:
        raise ValueError("power_kw must be 0 when energy_kwh is 0")
    rte_frac = _as_float("round_trip_eff_frac", battery.round_trip_eff_frac)
    if not 0.0 < rte_frac <= 1.0:
        raise ValueError("round_trip_eff_frac must be in (0, 1]: " + repr(battery.round_trip_eff_frac))
    soc_min_frac = _as_float("soc_min_frac", battery.soc_min_frac)
    if not 0.0 <= soc_min_frac < 1.0:
        raise ValueError("soc_min_frac must be in [0, 1): " + repr(battery.soc_min_frac))
    soc_initial_frac = _as_float("soc_initial_frac", battery.soc_initial_frac)
    if not soc_min_frac <= soc_initial_frac <= 1.0:
        raise ValueError("soc_initial_frac must be in [soc_min_frac, 1]: " + repr(battery.soc_initial_frac))
    return energy_kwh, power_kw, rte_frac, soc_min_frac, soc_initial_frac


def _check_n_units(value: object) -> int:
    """Check n_units as int >= 1. Raises ValueError naming the field."""
    if isinstance(value, bool):
        raise ValueError("n_units must be an int >= 1: " + repr(value))
    if not isinstance(value, (int, np.integer)):
        raise ValueError("n_units must be an int >= 1: " + repr(value))
    out = int(value)
    if out < 1:
        raise ValueError("n_units must be an int >= 1: " + repr(value))
    return out


def _check_diesel(diesel: object) -> tuple[float, int, float, float, float]:
    """Check DieselFleet fields. Returns unit kw, n, min load, intercept, slope."""
    if not isinstance(diesel, DieselFleet):
        raise ValueError("diesel must be a DieselFleet: " + repr(diesel))
    unit_kw = _as_float("unit_kw", diesel.unit_kw)
    if not unit_kw > 0.0:
        raise ValueError("unit_kw must be > 0: " + repr(diesel.unit_kw))
    n_units = _check_n_units(diesel.n_units)
    min_load_frac = _as_float("min_load_frac", diesel.min_load_frac)
    if not 0.0 <= min_load_frac < 1.0:
        raise ValueError("min_load_frac must be in [0, 1): " + repr(diesel.min_load_frac))
    intercept_l = _as_float(
        "fuel_intercept_l_per_h_per_kw_rated", diesel.fuel_intercept_l_per_h_per_kw_rated
    )
    if intercept_l < 0.0:
        raise ValueError("fuel_intercept_l_per_h_per_kw_rated must be >= 0")
    slope_l = _as_float("fuel_slope_l_per_kwh", diesel.fuel_slope_l_per_kwh)
    if not slope_l > 0.0:
        raise ValueError("fuel_slope_l_per_kwh must be > 0")
    return unit_kw, n_units, min_load_frac, intercept_l, slope_l


@dataclass(frozen=True)
class Battery:
    """Usable battery. Energy in kWh, power in kW, shares as frac."""

    energy_kwh: float
    power_kw: float
    round_trip_eff_frac: float
    soc_min_frac: float
    soc_initial_frac: float

    def __post_init__(self) -> None:
        """Check ranges. Raises ValueError naming the field."""
        _check_battery(self)


@dataclass(frozen=True)
class DieselFleet:
    """Diesel fleet. Rating in kW, fuel in l per h and l per kWh."""

    unit_kw: float
    n_units: int
    min_load_frac: float
    fuel_intercept_l_per_h_per_kw_rated: float
    fuel_slope_l_per_kwh: float

    def __post_init__(self) -> None:
        """Check ranges. Raises ValueError naming the field."""
        _check_diesel(self)


@dataclass(frozen=True)
class DispatchResult:
    """Dispatch output. Energy in kWh, fuel in l, shares as frac."""

    hourly: pd.DataFrame
    load_kwh: float
    load_served_kwh: float
    unserved_kwh: float
    unserved_frac: float
    pv_available_kwh: float
    pv_used_kwh: float
    pv_curtailed_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    diesel_kwh: float
    diesel_excess_kwh: float
    fuel_l: float
    diesel_run_hours: int
    diesel_starts: int
    soc_start_kwh: float
    soc_end_kwh: float
    renewable_fraction_frac: float


def _series_values(name_str: str, series: pd.Series) -> np.ndarray:
    """Series values as float array. Raises ValueError on bad input."""
    if pd.api.types.is_bool_dtype(series.dtype):
        raise ValueError(name_str + " must hold numbers")
    if pd.api.types.is_complex_dtype(series.dtype):
        raise ValueError(name_str + " must hold numbers")
    if not pd.api.types.is_numeric_dtype(series.dtype):
        raise ValueError(name_str + " must hold numbers")
    try:
        out = series.to_numpy(dtype=float)
    except (ValueError, TypeError) as exc:
        raise ValueError(name_str + " must hold numbers") from exc
    if not bool(np.isfinite(out).all()):
        raise ValueError(name_str + " must be finite")
    if bool((out < 0.0).any()):
        raise ValueError(name_str + " must be >= 0")
    return out


def _check_inputs(pv_kw: pd.Series, load_kw: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Check series and index. Returns pv and load float arrays."""
    if not isinstance(pv_kw, pd.Series):
        raise ValueError("pv_kw must be a pandas Series")
    if not isinstance(load_kw, pd.Series):
        raise ValueError("load_kw must be a pandas Series")
    if not pv_kw.index.equals(load_kw.index):
        raise ValueError("pv_kw and load_kw indexes must be equal")
    idx = pv_kw.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("index must be a DatetimeIndex")
    if idx.tz is None:
        raise ValueError("index must be time zone aware")
    n_hours = len(idx)
    if n_hours < 24:
        raise ValueError("index needs at least 24 rows: " + str(n_hours))
    diffs = idx.to_series().diff().dropna()
    if bool((diffs != pd.Timedelta(hours=1)).any()):
        raise ValueError("index must step exactly one hour")
    pv_vals = _series_values("pv_kw", pv_kw)
    load_vals = _series_values("load_kw", load_kw)
    if not float(load_vals.sum()) > 0.0:
        raise ValueError("load_kw must sum to more than 0")
    return pv_vals, load_vals


def dispatch(
    pv_kw: pd.Series,
    load_kw: pd.Series,
    battery: Battery,
    diesel: DieselFleet,
) -> DispatchResult:
    """Hour by hour energy flow. Power in kW, energy in kWh, fuel in l."""
    energy_kwh, power_kw, rte_frac, soc_min_frac, soc_initial_frac = _check_battery(battery)
    unit_kw, n_units, min_load_frac, intercept_l, slope_l = _check_diesel(diesel)
    pv_vals, load_vals = _check_inputs(pv_kw, load_kw)

    eta_frac = math.sqrt(rte_frac)
    e_min_kwh = soc_min_frac * energy_kwh
    e_max_kwh = energy_kwh
    s_kwh = soc_initial_frac * energy_kwh

    n_hours = len(pv_vals)
    pv_in = pv_vals.tolist()
    load_in = load_vals.tolist()

    load_col: list[float] = []
    pv_col: list[float] = []
    pv_to_load_col: list[float] = []
    pv_to_battery_col: list[float] = []
    pv_curtailed_col: list[float] = []
    discharge_col: list[float] = []
    diesel_col: list[float] = []
    diesel_to_load_col: list[float] = []
    diesel_to_battery_col: list[float] = []
    diesel_excess_col: list[float] = []
    units_col: list[int] = []
    unserved_col: list[float] = []
    soc_col: list[float] = []
    fuel_col: list[float] = []

    for i in range(n_hours):
        pv_val_kw = float(pv_in[i])
        load_val_kw = float(load_in[i])
        pv_to_load_kw = pv_val_kw if pv_val_kw < load_val_kw else load_val_kw
        surplus_kw = pv_val_kw - pv_to_load_kw
        deficit_kw = load_val_kw - pv_to_load_kw
        pv_to_battery_kw = 0.0
        pv_curtailed_kw = 0.0
        battery_discharge_kw = 0.0
        diesel_kw = 0.0
        diesel_to_load_kw = 0.0
        diesel_to_battery_kw = 0.0
        diesel_excess_kw = 0.0
        units_on = 0
        unserved_kw = 0.0
        if surplus_kw > 0.0:
            room_kwh = (e_max_kwh - s_kwh) / eta_frac
            if room_kwh < 0.0:
                room_kwh = 0.0
            pv_to_battery_kw = surplus_kw
            if power_kw < pv_to_battery_kw:
                pv_to_battery_kw = power_kw
            if room_kwh < pv_to_battery_kw:
                pv_to_battery_kw = room_kwh
            s_kwh += pv_to_battery_kw * eta_frac
            pv_curtailed_kw = surplus_kw - pv_to_battery_kw
        elif deficit_kw > 0.0:
            headroom_kwh = (s_kwh - e_min_kwh) * eta_frac
            if headroom_kwh < 0.0:
                headroom_kwh = 0.0
            max_dis_kw = headroom_kwh
            if power_kw < max_dis_kw:
                max_dis_kw = power_kw
            if deficit_kw <= max_dis_kw + 1e-9:
                battery_discharge_kw = deficit_kw
            else:
                rem_kw = deficit_kw - max_dis_kw
                units_on = int(math.ceil(rem_kw / unit_kw - 1e-9))
                if units_on < 1:
                    units_on = 1
                if units_on > n_units:
                    units_on = n_units
                cap_kw = float(units_on) * unit_kw
                d_min_kw = min_load_frac * cap_kw
                if rem_kw > cap_kw:
                    diesel_kw = cap_kw
                    diesel_to_load_kw = cap_kw
                    battery_discharge_kw = max_dis_kw
                    unserved_kw = rem_kw - cap_kw
                elif rem_kw < d_min_kw:
                    diesel_kw = d_min_kw
                    diesel_to_load_kw = deficit_kw if deficit_kw < d_min_kw else d_min_kw
                    battery_discharge_kw = deficit_kw - diesel_to_load_kw
                    if battery_discharge_kw == 0.0:
                        left_kw = d_min_kw - diesel_to_load_kw
                        room_kwh = (e_max_kwh - s_kwh) / eta_frac
                        if room_kwh < 0.0:
                            room_kwh = 0.0
                        diesel_to_battery_kw = left_kw
                        if power_kw < diesel_to_battery_kw:
                            diesel_to_battery_kw = power_kw
                        if room_kwh < diesel_to_battery_kw:
                            diesel_to_battery_kw = room_kwh
                        diesel_excess_kw = left_kw - diesel_to_battery_kw
                else:
                    diesel_kw = rem_kw
                    diesel_to_load_kw = rem_kw
                    battery_discharge_kw = max_dis_kw
            s_kwh -= battery_discharge_kw / eta_frac
            s_kwh += diesel_to_battery_kw * eta_frac
        if units_on > 0:
            fuel_l = float(units_on) * unit_kw * intercept_l + slope_l * diesel_kw
        else:
            fuel_l = 0.0
        load_col.append(load_val_kw)
        pv_col.append(pv_val_kw)
        pv_to_load_col.append(pv_to_load_kw)
        pv_to_battery_col.append(pv_to_battery_kw)
        pv_curtailed_col.append(pv_curtailed_kw)
        discharge_col.append(battery_discharge_kw)
        diesel_col.append(diesel_kw)
        diesel_to_load_col.append(diesel_to_load_kw)
        diesel_to_battery_col.append(diesel_to_battery_kw)
        diesel_excess_col.append(diesel_excess_kw)
        units_col.append(units_on)
        unserved_col.append(unserved_kw)
        soc_col.append(s_kwh)
        fuel_col.append(fuel_l)

    idx = pv_kw.index
    hourly = pd.DataFrame(
        {
            "load_kw": np.asarray(load_col, dtype=np.float64),
            "pv_kw": np.asarray(pv_col, dtype=np.float64),
            "pv_to_load_kw": np.asarray(pv_to_load_col, dtype=np.float64),
            "pv_to_battery_kw": np.asarray(pv_to_battery_col, dtype=np.float64),
            "pv_curtailed_kw": np.asarray(pv_curtailed_col, dtype=np.float64),
            "battery_discharge_kw": np.asarray(discharge_col, dtype=np.float64),
            "diesel_kw": np.asarray(diesel_col, dtype=np.float64),
            "diesel_to_load_kw": np.asarray(diesel_to_load_col, dtype=np.float64),
            "diesel_to_battery_kw": np.asarray(diesel_to_battery_col, dtype=np.float64),
            "diesel_excess_kw": np.asarray(diesel_excess_col, dtype=np.float64),
            "diesel_units_on": np.asarray(units_col, dtype=np.int64),
            "unserved_kw": np.asarray(unserved_col, dtype=np.float64),
            "soc_kwh": np.asarray(soc_col, dtype=np.float64),
            "fuel_l": np.asarray(fuel_col, dtype=np.float64),
        },
        index=idx,
    )
    hourly = hourly[list(HOURLY_COLUMNS)]

    load_kwh = float(np.sum(load_col))
    unserved_kwh = float(np.sum(unserved_col))
    load_served_kwh = load_kwh - unserved_kwh
    pv_available_kwh = float(np.sum(pv_col))
    pv_used_kwh = float(np.sum(pv_to_load_col) + np.sum(pv_to_battery_col))
    pv_curtailed_kwh = float(np.sum(pv_curtailed_col))
    battery_charge_kwh = float(np.sum(pv_to_battery_col) + np.sum(diesel_to_battery_col))
    battery_discharge_kwh = float(np.sum(discharge_col))
    diesel_kwh = float(np.sum(diesel_col))
    diesel_excess_kwh = float(np.sum(diesel_excess_col))
    fuel_total_l = float(np.sum(fuel_col))
    diesel_run_hours = int(sum(1 for u in units_col if u > 0))
    diesel_starts = 0
    for i, u in enumerate(units_col):
        if u > 0 and (i == 0 or units_col[i - 1] == 0):
            diesel_starts += 1
    soc_start_kwh = float(soc_initial_frac * energy_kwh)
    soc_end_kwh = float(soc_col[-1])
    if load_served_kwh <= 0.0:
        renewable_fraction_frac = 0.0
    else:
        renewable_fraction_frac = 1.0 - (diesel_kwh - diesel_excess_kwh) / load_served_kwh
        if renewable_fraction_frac < 0.0:
            renewable_fraction_frac = 0.0
    unserved_frac = unserved_kwh / load_kwh

    return DispatchResult(
        hourly=hourly,
        load_kwh=load_kwh,
        load_served_kwh=load_served_kwh,
        unserved_kwh=unserved_kwh,
        unserved_frac=unserved_frac,
        pv_available_kwh=pv_available_kwh,
        pv_used_kwh=pv_used_kwh,
        pv_curtailed_kwh=pv_curtailed_kwh,
        battery_charge_kwh=battery_charge_kwh,
        battery_discharge_kwh=battery_discharge_kwh,
        diesel_kwh=diesel_kwh,
        diesel_excess_kwh=diesel_excess_kwh,
        fuel_l=fuel_total_l,
        diesel_run_hours=diesel_run_hours,
        diesel_starts=diesel_starts,
        soc_start_kwh=soc_start_kwh,
        soc_end_kwh=soc_end_kwh,
        renewable_fraction_frac=renewable_fraction_frac,
    )
