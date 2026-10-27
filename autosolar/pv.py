"""Hourly PV output from a weather table. Power in kW, energy in kWh."""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pvlib.inverter
import pvlib.irradiance
import pvlib.pvsystem
import pvlib.solarposition
import pvlib.temperature


def _as_float(name_str: str, value: object) -> float:
    """Value as a finite float. Raises ValueError on bad input."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(name_str + " must be a number: " + repr(value))
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " must be finite: " + repr(value))
    return out


def _check_range(
    name_str: str,
    value: object,
    lo: float,
    hi: float,
    lo_closed: bool,
    hi_closed: bool,
) -> float:
    """Range check for one design value. Raises ValueError on bad input."""
    out = _as_float(name_str, value)
    ok_lo = out >= lo if lo_closed else out > lo
    ok_hi = out <= hi if hi_closed else out < hi
    if not (ok_lo and ok_hi):
        raise ValueError(name_str + " out of range: " + repr(value))
    return out


@dataclass(frozen=True)
class PVDesign:
    """Fixed PV array description. Angles in deg, losses in pct, share as frac."""

    tilt_deg: float = 10.0
    azimuth_deg: float | None = None
    dc_ac_ratio: float = 1.2
    gamma_pdc_per_degc: float = -0.004
    system_loss_pct: float = 14.0
    eta_inv_nom_frac: float = 0.96
    albedo_frac: float = 0.2
    transposition: str = "haydavies"
    faiman_u0_w_m2_k: float = 25.0
    faiman_u1_w_s_m3_k: float = 6.84

    def __post_init__(self) -> None:
        """Check ranges. Raises ValueError on bad input."""
        _check_range("tilt_deg", self.tilt_deg, 0.0, 90.0, True, True)
        if self.azimuth_deg is not None:
            _check_range("azimuth_deg", self.azimuth_deg, 0.0, 360.0, True, False)
        _check_range("dc_ac_ratio", self.dc_ac_ratio, 0.0, 3.0, False, True)
        _check_range(
            "gamma_pdc_per_degc", self.gamma_pdc_per_degc, -0.01, 0.0, True, True
        )
        _check_range("system_loss_pct", self.system_loss_pct, 0.0, 50.0, True, True)
        _check_range(
            "eta_inv_nom_frac", self.eta_inv_nom_frac, 0.5, 1.0, False, True
        )
        _check_range("albedo_frac", self.albedo_frac, 0.0, 1.0, True, True)
        if self.transposition not in ("haydavies", "isotropic"):
            raise ValueError(
                "transposition must be haydavies or isotropic: "
                + repr(self.transposition)
            )
        _check_range("faiman_u0_w_m2_k", self.faiman_u0_w_m2_k, 0.0, math.inf, False, True)
        _check_range("faiman_u1_w_s_m3_k", self.faiman_u1_w_s_m3_k, 0.0, math.inf, False, True)


@dataclass(frozen=True)
class PVResult:
    """PV run output. Energy in kWh, yield in kWh per kWp, PR as frac."""

    hourly: pd.DataFrame
    n_hours: int
    is_full_year: bool
    azimuth_deg: float
    pdc0_kw: float
    pac0_kw: float
    energy_ac_kwh: float
    specific_yield_kwh_kwp: float
    insolation_ghi_kwh_m2: float
    insolation_poa_kwh_m2: float
    performance_ratio_frac: float | None


def _checked_values(
    name_str: str, series: pd.Series, lo_w: float, hi_w: float
) -> np.ndarray:
    """Column values as a float array. Raises ValueError on bad input."""
    if not pd.api.types.is_numeric_dtype(series.dtype):
        raise ValueError(name_str + " must hold numbers")
    out = series.to_numpy(dtype=float)
    if bool(np.isnan(out).any()):
        raise ValueError(name_str + " must not hold NaN")
    if bool(((out < lo_w) | (out > hi_w)).any()):
        raise ValueError(
            name_str + " out of range " + str(lo_w) + " to " + str(hi_w)
        )
    return out


def _check_weather(weather: object) -> tuple[np.ndarray, np.ndarray, np.ndarray, bool]:
    """Validate the hourly weather table. Returns ghi, temp, wind, dni dhi flag."""
    if not isinstance(weather, pd.DataFrame):
        raise ValueError("weather must be a pandas DataFrame")
    idx = weather.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("weather index must be a DatetimeIndex")
    if idx.tz is None:
        raise ValueError("weather index must be time zone aware")
    n_hours = len(weather)
    if n_hours < 24:
        raise ValueError("weather needs at least 24 rows: " + str(n_hours))
    diffs = idx.to_series().diff().dropna()
    if bool((diffs != pd.Timedelta(hours=1)).any()):
        raise ValueError("weather index must step exactly one hour")
    for col_str, lo, hi in (
        ("ghi_w_m2", 0.0, 1500.0),
        ("temp_air_degc", -30.0, 60.0),
        ("wind_speed_m_s", 0.0, 60.0),
    ):
        if col_str not in weather.columns:
            raise ValueError("weather missing column: " + col_str)
    ghi_w_m2 = _checked_values("ghi_w_m2", weather["ghi_w_m2"], 0.0, 1500.0)
    temp_air_degc = _checked_values(
        "temp_air_degc", weather["temp_air_degc"], -30.0, 60.0
    )
    wind_speed_m_s = _checked_values(
        "wind_speed_m_s", weather["wind_speed_m_s"], 0.0, 60.0
    )
    has_dni = "dni_w_m2" in weather.columns
    has_dhi = "dhi_w_m2" in weather.columns
    if has_dni != has_dhi:
        raise ValueError("weather must hold both dni_w_m2 and dhi_w_m2 or neither")
    if has_dni and has_dhi:
        _checked_values("dni_w_m2", weather["dni_w_m2"], 0.0, 1500.0)
        _checked_values("dhi_w_m2", weather["dhi_w_m2"], 0.0, 1000.0)
    return ghi_w_m2, temp_air_degc, wind_speed_m_s, bool(has_dni and has_dhi)


def _check_lat_lon(name_str: str, value: object, lo: float, hi: float) -> float:
    """Site angle check in deg. Raises ValueError on bad input."""
    out = _as_float(name_str, value)
    if not (lo <= out <= hi):
        raise ValueError(name_str + " out of range: " + repr(value))
    return out


def _check_pdc0(pdc0_kw: object) -> float:
    """Size check in kW. Raises ValueError on bad input."""
    out = _as_float("pdc0_kw", pdc0_kw)
    if not out > 0.0:
        raise ValueError("pdc0_kw must be greater than 0: " + repr(pdc0_kw))
    return out


def _as_f64(values: object) -> np.ndarray:
    """Values by position as float64."""
    return np.asarray(values, dtype=np.float64)


def simulate_pv(
    weather: pd.DataFrame,
    lat_deg: float,
    lon_deg: float,
    design: PVDesign = PVDesign(),
    pdc0_kw: float = 1.0,
) -> PVResult:
    """Hourly AC output for a fixed array. Irradiance in W per m2."""
    ghi_vals, temp_vals, wind_vals, has_split = _check_weather(weather)
    lat = _check_lat_lon("lat_deg", lat_deg, -90.0, 90.0)
    lon = _check_lat_lon("lon_deg", lon_deg, -180.0, 180.0)
    size_kw = _check_pdc0(pdc0_kw)
    if not isinstance(design, PVDesign):
        raise ValueError("design must be a PVDesign")
    if design.azimuth_deg is not None:
        azimuth_deg = float(design.azimuth_deg)
    elif lat < 0.0:
        azimuth_deg = 0.0
    else:
        azimuth_deg = 180.0

    mid = weather.index.tz_convert("UTC") + pd.Timedelta(minutes=30)
    ghi_w_m2 = pd.Series(ghi_vals, index=mid)
    temp_air_degc = pd.Series(temp_vals, index=mid)
    wind_speed_m_s = pd.Series(wind_vals, index=mid)

    sp = pvlib.solarposition.get_solarposition(mid, lat, lon)
    if has_split:
        dni_w_m2 = pd.Series(weather["dni_w_m2"].to_numpy(dtype=float), index=mid)
        dhi_w_m2 = pd.Series(weather["dhi_w_m2"].to_numpy(dtype=float), index=mid)
    else:
        erbs = pvlib.irradiance.erbs(ghi_w_m2, sp["zenith"], mid)
        dni_w_m2 = erbs["dni"]
        dhi_w_m2 = erbs["dhi"]

    dni_extra_w_m2 = pvlib.irradiance.get_extra_radiation(mid)
    poa_raw_w_m2 = pvlib.irradiance.get_total_irradiance(
        design.tilt_deg,
        azimuth_deg,
        sp["zenith"],
        sp["azimuth"],
        dni_w_m2,
        ghi_w_m2,
        dhi_w_m2,
        dni_extra=dni_extra_w_m2,
        albedo=design.albedo_frac,
        model=design.transposition,
    )["poa_global"]
    if bool(pd.Series(poa_raw_w_m2).isna().any()):
        raise ValueError("poa_global holds NaN")
    poa_global_w_m2 = poa_raw_w_m2.clip(lower=0.0)

    temp_cell_degc = pvlib.temperature.faiman(
        poa_global_w_m2,
        temp_air_degc,
        wind_speed_m_s,
        u0=design.faiman_u0_w_m2_k,
        u1=design.faiman_u1_w_s_m3_k,
    )
    dc_kw = pvlib.pvsystem.pvwatts_dc(
        poa_global_w_m2, temp_cell_degc, size_kw, design.gamma_pdc_per_degc
    ) * (1.0 - design.system_loss_pct / 100.0)
    pac0_kw = size_kw / design.dc_ac_ratio
    ac_kw = pvlib.inverter.pvwatts(
        dc_kw, pac0_kw / design.eta_inv_nom_frac, design.eta_inv_nom_frac
    )
    ac_kwh = ac_kw * 1.0

    hourly = pd.DataFrame(
        {
            "zenith_deg": _as_f64(sp["zenith"]),
            "dni_w_m2": _as_f64(dni_w_m2),
            "dhi_w_m2": _as_f64(dhi_w_m2),
            "poa_global_w_m2": _as_f64(poa_global_w_m2),
            "temp_cell_degc": _as_f64(temp_cell_degc),
            "dc_kw": _as_f64(dc_kw),
            "ac_kw": _as_f64(ac_kw),
            "ac_kwh": _as_f64(ac_kwh),
        },
        index=weather.index,
    )

    n_hours = len(weather)
    energy_ac_kwh = float(hourly["ac_kwh"].to_numpy().sum())
    specific_yield_kwh_kwp = energy_ac_kwh / size_kw
    insolation_ghi_kwh_m2 = float(np.sum(ghi_vals) / 1000.0)
    insolation_poa_kwh_m2 = float(hourly["poa_global_w_m2"].to_numpy().sum() / 1000.0)
    if insolation_poa_kwh_m2 == 0.0:
        performance_ratio_frac: float | None = None
    else:
        performance_ratio_frac = (
            specific_yield_kwh_kwp / insolation_poa_kwh_m2
        )

    return PVResult(
        hourly=hourly,
        n_hours=n_hours,
        is_full_year=n_hours in (8760, 8784),
        azimuth_deg=azimuth_deg,
        pdc0_kw=size_kw,
        pac0_kw=pac0_kw,
        energy_ac_kwh=energy_ac_kwh,
        specific_yield_kwh_kwp=specific_yield_kwh_kwp,
        insolation_ghi_kwh_m2=insolation_ghi_kwh_m2,
        insolation_poa_kwh_m2=insolation_poa_kwh_m2,
        performance_ratio_frac=performance_ratio_frac,
    )
