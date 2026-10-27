"""Weather cases from free sources. Irradiance in W per m2, totals in kWh per m2."""

from __future__ import annotations

import calendar
import json
import math
import numbers
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import pvlib.iotools
import requests

YEAR_FROM = 2016
YEAR_TO = 2024
RANGE_REQUIRED_PCT = 10.0
CASE_NAMES = ("CAMS", "NASA POWER", "PVGIS-ERA5 TMY", "GSA scaled")
BASIS = "CAMS"

_GHI_MAX_W_M2 = 1500.0
_TEMP_LO_DEGC = -30.0
_TEMP_HI_DEGC = 60.0
_WIND_MAX_M_S = 60.0


def _as_float(name_str: str, value: object) -> float:
    """Value as a finite float. Raises ValueError on bad input."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(name_str + " must be a number: " + repr(value))
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " must be finite: " + repr(value))
    return out


def _check_hourly_index(dframe: pd.DataFrame) -> pd.DatetimeIndex:
    """Shared hourly index check. Raises ValueError on bad input."""
    if not isinstance(dframe, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    idx = dframe.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("df index must be a DatetimeIndex")
    if idx.tz is None:
        raise ValueError("df index must be time zone aware")
    if len(dframe) < 24:
        raise ValueError("df needs at least 24 rows: " + str(len(dframe)))
    diffs = idx.to_series().diff().dropna()
    if bool((diffs != pd.Timedelta(hours=1)).any()):
        raise ValueError("df index must step exactly one hour")
    return idx


def _column_floats(name_str: str, dframe: pd.DataFrame, col_str: str) -> np.ndarray:
    """One column as a float array with no NaN. Raises ValueError on bad input."""
    if col_str not in dframe.columns:
        raise ValueError("df missing column: " + col_str)
    series = dframe[col_str]
    if pd.api.types.is_bool_dtype(series.dtype):
        raise ValueError(name_str + " must hold numbers")
    if not pd.api.types.is_numeric_dtype(series.dtype):
        raise ValueError(name_str + " must hold numbers")
    try:
        out = series.to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(name_str + " must hold numbers") from exc
    if bool(np.isnan(out).any()):
        raise ValueError(name_str + " must not hold NaN")
    return out


def _check_range(name_str: str, vals: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Array range check. Raises ValueError on bad input."""
    if bool(((vals < lo) | (vals > hi)).any()):
        raise ValueError(name_str + " out of range " + str(lo) + " to " + str(hi))
    return vals


def ghi_from_pvlib(dframe: pd.DataFrame) -> pd.Series:
    """GHI in W per m2 from a pvlib hourly frame."""
    idx = _check_hourly_index(dframe)
    vals = _check_range("ghi", _column_floats("ghi", dframe, "ghi"), 0.0, _GHI_MAX_W_M2)
    return pd.Series(vals.astype(np.float64), index=idx, name="ghi_w_m2", dtype=np.float64)


def meteo_from_pvlib(dframe: pd.DataFrame) -> pd.DataFrame:
    """Air temperature in degC and wind in m per s from a pvlib hourly frame."""
    idx = _check_hourly_index(dframe)
    temp = _check_range(
        "temp_air",
        _column_floats("temp_air", dframe, "temp_air"),
        _TEMP_LO_DEGC,
        _TEMP_HI_DEGC,
    )
    wind = _check_range(
        "wind_speed",
        _column_floats("wind_speed", dframe, "wind_speed"),
        0.0,
        _WIND_MAX_M_S,
    )
    return pd.DataFrame(
        {"temp_air_degc": temp.astype(np.float64), "wind_speed_m_s": wind.astype(np.float64)},
        index=idx,
    ).astype(np.float64)


def weather_table(ghi: pd.Series, meteo: pd.DataFrame) -> pd.DataFrame:
    """Join GHI and meteo into one hourly table. Irradiance in W per m2."""
    if not isinstance(ghi, pd.Series):
        raise ValueError("ghi must be a pandas Series")
    if not isinstance(meteo, pd.DataFrame):
        raise ValueError("meteo must be a pandas DataFrame")
    if not ghi.index.equals(meteo.index):
        raise ValueError("ghi and meteo indexes must match")
    for col_str in ("temp_air_degc", "wind_speed_m_s"):
        if col_str not in meteo.columns:
            raise ValueError("meteo missing column: " + col_str)
    try:
        ghi_vals = ghi.to_numpy(dtype=float)
        temp_vals = meteo["temp_air_degc"].to_numpy(dtype=float)
        wind_vals = meteo["wind_speed_m_s"].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("weather values must be numbers") from exc
    return pd.DataFrame(
        {"ghi_w_m2": ghi_vals, "temp_air_degc": temp_vals, "wind_speed_m_s": wind_vals},
        index=ghi.index,
    ).astype(np.float64)


def annual_totals_cams_monthly(dframe: pd.DataFrame) -> dict[int, float]:
    """Yearly GHI totals in kWh per m2 from a CAMS monthly frame in Wh per m2."""
    if not isinstance(dframe, pd.DataFrame):
        raise ValueError("df must be a pandas DataFrame")
    if not isinstance(dframe.index, pd.DatetimeIndex):
        raise ValueError("df index must be a DatetimeIndex")
    vals = _column_floats("ghi", dframe, "ghi")
    if bool((vals < 0.0).any()):
        raise ValueError("ghi must not hold negative values")
    years = dframe.index.year
    totals: dict[int, float] = {}
    for year in sorted(set(int(y) for y in years)):
        rows = int((years == year).sum())
        if rows != 12:
            raise ValueError("year " + str(year) + " holds " + str(rows) + " rows, need 12")
        totals[year] = float(vals[years == year].sum() / 1000.0)
    return totals


def annual_totals_nasa_monthly(payload: dict) -> dict[int, float]:
    """Yearly GHI totals in kWh per m2 from a NASA POWER monthly payload."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    try:
        param = payload["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]
    except (KeyError, TypeError) as exc:
        raise ValueError("payload missing NASA monthly values") from exc
    if not isinstance(param, dict):
        raise ValueError("payload monthly values must be a dict")
    totals: dict[int, float] = {}
    for key, value in param.items():
        if not (isinstance(key, str) and len(key) == 6 and key.endswith("13")):
            continue
        try:
            year = int(key[:4])
        except ValueError as exc:
            raise ValueError("bad NASA annual key: " + repr(key)) from exc
        daily = _as_float("NASA annual value " + key, value)
        if not daily >= 0.0:
            raise ValueError("NASA annual value below 0: " + repr(value))
        days = 366 if calendar.isleap(year) else 365
        totals[year] = daily * days
    if not totals:
        raise ValueError("payload holds no NASA annual values")
    return dict(sorted(totals.items()))


def gsa_annual_ghi_kwh_m2(payload: dict) -> float:
    """Long term annual GHI in kWh per m2 from a Global Solar Atlas payload."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    try:
        raw = payload["annual"]["data"]["GHI"]
    except (KeyError, TypeError) as exc:
        raise ValueError("payload missing GSA annual GHI") from exc
    out = _as_float("GSA annual GHI", raw)
    if not out > 0.0:
        raise ValueError("GSA annual GHI must be above 0: " + repr(raw))
    return out


def year_closest_to_mean(totals: dict[int, float]) -> int:
    """Year whose total is closest to the mean. Ties go to the earliest year."""
    if not isinstance(totals, dict) or not totals:
        raise ValueError("totals must not be empty")
    vals = {y: _as_float("total " + str(y), v) for y, v in totals.items()}
    mean = sum(vals.values()) / len(vals)
    return min(sorted(vals), key=lambda y: abs(vals[y] - mean))


def spread_pct(totals: dict[str, float]) -> float:
    """Spread of totals in pct: (max minus min) over min times 100."""
    if not isinstance(totals, dict) or len(totals) < 2:
        raise ValueError("totals needs at least 2 values")
    vals = [_as_float("total " + str(k), v) for k, v in totals.items()]
    for val in vals:
        if not val > 0.0:
            raise ValueError("totals must hold values above 0")
    return (max(vals) - min(vals)) / min(vals) * 100.0


def scale_ghi_to_annual(weather: pd.DataFrame, target_kwh_m2: float) -> pd.DataFrame:
    """Copy of weather with GHI scaled to target kWh per m2 per year."""
    target = _as_float("target_kwh_m2", target_kwh_m2)
    if not target > 0.0:
        raise ValueError("target_kwh_m2 must be above 0: " + repr(target_kwh_m2))
    if not isinstance(weather, pd.DataFrame):
        raise ValueError("weather must be a pandas DataFrame")
    if "ghi_w_m2" not in weather.columns:
        raise ValueError("weather missing column: ghi_w_m2")
    try:
        base = weather["ghi_w_m2"].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("ghi_w_m2 must hold numbers") from exc
    if bool(np.isnan(base).any()):
        raise ValueError("ghi_w_m2 must not hold NaN")
    total = float(base.sum() / 1000.0)
    if not total > 0.0:
        raise ValueError("weather GHI sum must be above 0")
    scaled = base * (target / total)
    if bool((scaled > _GHI_MAX_W_M2).any()):
        raise ValueError("scaled GHI above 1500 W per m2")
    out = weather.copy()
    out["ghi_w_m2"] = scaled.astype(np.float64)
    return out


@dataclass(frozen=True)
class WeatherFetchers:
    """Source callables. Tests pass fakes, so unit tests touch no network."""

    cams_monthly: Callable[[float, float, int, int, str], pd.DataFrame]
    cams_hourly: Callable[[float, float, int, str], pd.DataFrame]
    nasa_monthly: Callable[[float, float, int, int], dict]
    nasa_hourly: Callable[[float, float, int], pd.DataFrame]
    pvgis_tmy: Callable[[float, float], pd.DataFrame]
    gsa: Callable[[float, float], dict]


def default_fetchers() -> WeatherFetchers:
    """Live fetchers. Creation makes no network call."""
    def _cams_monthly(lat_deg: float, lon_deg: float, year_from: int, year_to: int,
                      email: str) -> pd.DataFrame:
        """CAMS monthly frame in Wh per m2 per month."""
        return pvlib.iotools.get_cams(
            lat_deg, lon_deg, f"{year_from}-01-01", f"{year_to}-12-31", email=email,
            identifier="cams_radiation", time_step="1M", time_ref="UT",
            integrated=True, timeout=180)[0]

    def _cams_hourly(lat_deg: float, lon_deg: float, year: int, email: str) -> pd.DataFrame:
        """CAMS hourly frame in W per m2."""
        return pvlib.iotools.get_cams(
            lat_deg, lon_deg, f"{year}-01-01", f"{year}-12-31", email=email,
            identifier="cams_radiation", time_step="1h", time_ref="UT",
            integrated=False, timeout=180)[0]

    def _nasa_monthly(lat_deg: float, lon_deg: float, year_from: int, year_to: int) -> dict:
        """NASA POWER monthly payload in kWh per m2 per day."""
        resp = requests.get(
            "https://power.larc.nasa.gov/api/temporal/monthly/point",
            params={"parameters": "ALLSKY_SFC_SW_DWN", "community": "RE",
                    "longitude": lon_deg, "latitude": lat_deg,
                    "start": year_from, "end": year_to, "format": "JSON"},
            timeout=60)
        resp.raise_for_status()
        return resp.json()

    def _nasa_hourly(lat_deg: float, lon_deg: float, year: int) -> pd.DataFrame:
        """NASA POWER hourly frame, irradiance in Wh per m2 per hour."""
        return pvlib.iotools.get_nasa_power(
            lat_deg, lon_deg, pd.Timestamp(f"{year}-01-01", tz="UTC"),
            pd.Timestamp(f"{year}-12-31 23:00", tz="UTC"),
            parameters=["ghi", "temp_air", "wind_speed"])[0]

    def _pvgis_tmy(lat_deg: float, lon_deg: float) -> pd.DataFrame:
        """PVGIS TMY hourly frame stamped 1990 by pvlib."""
        return pvlib.iotools.get_pvgis_tmy(
            lat_deg, lon_deg, outputformat="json", usehorizon=True,
            map_variables=True, timeout=60)[0]

    def _gsa(lat_deg: float, lon_deg: float) -> dict:
        """Global Solar Atlas long term annual payload in kWh per m2 per year."""
        resp = requests.get(
            "https://api.globalsolaratlas.info/data/lta",
            params={"loc": f"{lat_deg},{lon_deg}"}, timeout=60)
        resp.raise_for_status()
        return resp.json()

    return WeatherFetchers(cams_monthly=_cams_monthly, cams_hourly=_cams_hourly,
                           nasa_monthly=_nasa_monthly, nasa_hourly=_nasa_hourly,
                           pvgis_tmy=_pvgis_tmy, gsa=_gsa)


def cached_fetchers(base: WeatherFetchers, cache_dir: Path) -> WeatherFetchers:
    """Fetchers with a file cache in cache_dir. Frames in CSV, payloads in JSON."""
    if not isinstance(base, WeatherFetchers):
        raise ValueError("base must be a WeatherFetchers")
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    def _tag(lat_deg: float, lon_deg: float) -> tuple[str, str]:
        """Lat and lon as file name parts."""
        return (f"{lat_deg:.4f}", f"{lon_deg:.4f}")

    def _read_frame(path: Path) -> pd.DataFrame:
        """Frame from a cache CSV with a UTC index."""
        out = pd.read_csv(path, index_col=0)
        out.index = pd.to_datetime(out.index, utc=True)
        return out

    def _read_payload(path: Path) -> dict:
        """Payload from a cache JSON file."""
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def _write_payload(obj: dict, path: Path) -> None:
        """Payload to a cache JSON file in UTF-8."""
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(obj, handle)

    def _cams_monthly(lat_deg: float, lon_deg: float, year_from: int, year_to: int,
                      email: str) -> pd.DataFrame:
        """Cached CAMS monthly frame in Wh per m2 per month."""
        cache.mkdir(parents=True, exist_ok=True)
        la, lo = _tag(lat_deg, lon_deg)
        path = cache / f"cams_monthly_{la}_{lo}_{year_from}_{year_to}.csv"
        if path.is_file():
            return _read_frame(path)
        out = base.cams_monthly(lat_deg, lon_deg, year_from, year_to, email)
        out.to_csv(path)
        return out

    def _cams_hourly(lat_deg: float, lon_deg: float, year: int, email: str) -> pd.DataFrame:
        """Cached CAMS hourly frame in W per m2."""
        cache.mkdir(parents=True, exist_ok=True)
        la, lo = _tag(lat_deg, lon_deg)
        path = cache / f"cams_hourly_{la}_{lo}_{year}.csv"
        if path.is_file():
            return _read_frame(path)
        out = base.cams_hourly(lat_deg, lon_deg, year, email)
        out.to_csv(path)
        return out

    def _nasa_monthly(lat_deg: float, lon_deg: float, year_from: int, year_to: int) -> dict:
        """Cached NASA POWER monthly payload."""
        cache.mkdir(parents=True, exist_ok=True)
        la, lo = _tag(lat_deg, lon_deg)
        path = cache / f"nasa_monthly_{la}_{lo}_{year_from}_{year_to}.json"
        if path.is_file():
            return _read_payload(path)
        out = base.nasa_monthly(lat_deg, lon_deg, year_from, year_to)
        _write_payload(out, path)
        return out

    def _nasa_hourly(lat_deg: float, lon_deg: float, year: int) -> pd.DataFrame:
        """Cached NASA POWER hourly frame."""
        cache.mkdir(parents=True, exist_ok=True)
        la, lo = _tag(lat_deg, lon_deg)
        path = cache / f"nasa_hourly_{la}_{lo}_{year}.csv"
        if path.is_file():
            return _read_frame(path)
        out = base.nasa_hourly(lat_deg, lon_deg, year)
        out.to_csv(path)
        return out

    def _pvgis_tmy(lat_deg: float, lon_deg: float) -> pd.DataFrame:
        """Cached PVGIS TMY hourly frame."""
        cache.mkdir(parents=True, exist_ok=True)
        la, lo = _tag(lat_deg, lon_deg)
        path = cache / f"pvgis_tmy_{la}_{lo}.csv"
        if path.is_file():
            return _read_frame(path)
        out = base.pvgis_tmy(lat_deg, lon_deg)
        out.to_csv(path)
        return out

    def _gsa(lat_deg: float, lon_deg: float) -> dict:
        """Cached Global Solar Atlas payload."""
        cache.mkdir(parents=True, exist_ok=True)
        la, lo = _tag(lat_deg, lon_deg)
        path = cache / f"gsa_{la}_{lo}.json"
        if path.is_file():
            return _read_payload(path)
        out = base.gsa(lat_deg, lon_deg)
        _write_payload(out, path)
        return out

    return WeatherFetchers(cams_monthly=_cams_monthly, cams_hourly=_cams_hourly,
                           nasa_monthly=_nasa_monthly, nasa_hourly=_nasa_hourly,
                           pvgis_tmy=_pvgis_tmy, gsa=_gsa)


@dataclass(frozen=True)
class WeatherCases:
    """Four hourly weather cases with annual totals in kWh per m2."""

    basis: str
    cases: dict[str, pd.DataFrame]
    years: dict[str, int | None]
    annual_ghi_kwh_m2: dict[str, float]
    spread_pct_all: float
    spread_pct_no_era5: float
    range_required: bool
    cams_annual_totals_kwh_m2: dict[int, float]
    nasa_annual_totals_kwh_m2: dict[int, float]
    gsa_annual_ghi_kwh_m2: float
    notes: list[str]


def build_weather_cases(lat_deg: float, lon_deg: float, cams_email: str,
                        fetchers: WeatherFetchers) -> WeatherCases:
    """Four hourly weather cases for the site. Raises ValueError on bad input."""
    lat = _as_float("lat_deg", lat_deg)
    if not -90.0 <= lat <= 90.0:
        raise ValueError("lat_deg out of range: " + repr(lat_deg))
    lon = _as_float("lon_deg", lon_deg)
    if not -180.0 <= lon <= 180.0:
        raise ValueError("lon_deg out of range: " + repr(lon_deg))
    if not isinstance(cams_email, str) or "@" not in cams_email:
        raise ValueError("cams_email must hold @: " + repr(cams_email))
    if not isinstance(fetchers, WeatherFetchers):
        raise ValueError("fetchers must be a WeatherFetchers")
    cams_tot = annual_totals_cams_monthly(
        fetchers.cams_monthly(lat_deg, lon_deg, YEAR_FROM, YEAR_TO, cams_email))
    if list(cams_tot) != list(range(YEAR_FROM, YEAR_TO + 1)):
        raise ValueError("CAMS years must cover YEAR_FROM to YEAR_TO")
    cams_year = year_closest_to_mean(cams_tot)
    nasa_tot = annual_totals_nasa_monthly(
        fetchers.nasa_monthly(lat_deg, lon_deg, YEAR_FROM, YEAR_TO))
    if list(nasa_tot) != list(range(YEAR_FROM, YEAR_TO + 1)):
        raise ValueError("NASA POWER years must cover YEAR_FROM to YEAR_TO")
    nasa_year = year_closest_to_mean(nasa_tot)
    nasa_cams_frame = fetchers.nasa_hourly(lat_deg, lon_deg, cams_year)
    if nasa_year == cams_year:
        nasa_frame = nasa_cams_frame
    else:
        nasa_frame = fetchers.nasa_hourly(lat_deg, lon_deg, nasa_year)
    cams_case = weather_table(
        ghi_from_pvlib(fetchers.cams_hourly(lat_deg, lon_deg, cams_year, cams_email)),
        meteo_from_pvlib(nasa_cams_frame))
    nasa_case = weather_table(ghi_from_pvlib(nasa_frame), meteo_from_pvlib(nasa_frame))
    tmy_frame = fetchers.pvgis_tmy(lat_deg, lon_deg)
    tmy_case = weather_table(ghi_from_pvlib(tmy_frame), meteo_from_pvlib(tmy_frame))
    gsa_val = gsa_annual_ghi_kwh_m2(fetchers.gsa(lat_deg, lon_deg))
    gsa_case = scale_ghi_to_annual(cams_case, gsa_val)
    cases = {"CAMS": cams_case, "NASA POWER": nasa_case,
             "PVGIS-ERA5 TMY": tmy_case, "GSA scaled": gsa_case}
    annual = {k: float(v["ghi_w_m2"].sum() / 1000.0) for k, v in cases.items()}
    spread_all = spread_pct(annual)
    spread_no = spread_pct({k: v for k, v in annual.items() if k != "PVGIS-ERA5 TMY"})
    notes = [
        f"CAMS case: temperature and wind from NASA POWER {cams_year}",
        f"GSA scaled case: CAMS {cams_year} hourly shape scaled to the GSA "
        "long term annual GHI",
        "PVGIS-ERA5 TMY case: months from different years, stamped 1990 by pvlib",
    ]
    return WeatherCases(
        basis=BASIS, cases=cases,
        years={"CAMS": cams_year, "NASA POWER": nasa_year,
               "PVGIS-ERA5 TMY": None, "GSA scaled": cams_year},
        annual_ghi_kwh_m2=annual, spread_pct_all=spread_all,
        spread_pct_no_era5=spread_no,
        range_required=bool(spread_all > RANGE_REQUIRED_PCT),
        cams_annual_totals_kwh_m2=cams_tot, nasa_annual_totals_kwh_m2=nasa_tot,
        gsa_annual_ghi_kwh_m2=gsa_val, notes=notes)
