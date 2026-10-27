"""Demand cases from the paper profile. Load in kW, energy in kWh."""

from __future__ import annotations

import math
import numbers
from dataclasses import dataclass

import numpy as np
import pandas as pd

HIRON_2021_LOAD_KW: tuple[float, ...] = (
    1126.0, 1105.0, 1052.0, 1031.0, 1044.0, 1104.0, 1152.0, 1004.0,
    995.0, 976.0, 942.0, 936.0, 949.0, 985.0, 974.0, 934.0,
    926.0, 1003.0, 1367.0, 1422.0, 1377.0, 1351.0, 1264.0, 1195.0,
)
HIRON_2021_SOURCE = (
    "Hiron et al. 2021, Energies 14, 8311, Table 6 (p19), doi:10.3390/en14248311"
)
HIRON_2021_DAILY_KWH_STATED = 26479.0
HIRON_2021_PEAK_KW_STATED = 1422.0
HIRON_2021_GROWTH_FRAC_PER_YR = 0.0348
HIRON_2021_BASE_YEAR = 2022
LOCAL_TZ = "Asia/Jakarta"


def _checked_profile(profile_kw: object) -> list[float]:
    """Profile as 24 finite floats in kW. Raises ValueError on bad input."""
    if isinstance(profile_kw, (str, bytes)):
        raise ValueError("profile_kw length check failed: must hold 24 values")
    try:
        size = len(profile_kw)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ValueError("profile_kw length check failed: must be a sequence") from exc
    if size != 24:
        raise ValueError(
            "profile_kw length check failed: need 24 values, got " + str(size)
        )
    out: list[float] = []
    for pos, raw in enumerate(profile_kw):  # type: ignore[arg-type]
        if isinstance(raw, bool) or not isinstance(raw, numbers.Real):
            raise ValueError(
                "profile_kw number check failed at hour "
                + str(pos)
                + ": "
                + repr(raw)
            )
        val = float(raw)
        if not math.isfinite(val):
            raise ValueError(
                "profile_kw finite check failed at hour " + str(pos)
            )
        if not val >= 0.0:
            raise ValueError(
                "profile_kw range check failed at hour "
                + str(pos)
                + ": must be >= 0"
            )
        out.append(val)
    return out


def _checked_expected(name_str: str, value: object) -> float:
    """Expected energy in kWh or peak in kW. Raises ValueError on bad input."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(name_str + " check failed: must be a number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " check failed: must be finite")
    if not out > 0.0:
        raise ValueError(name_str + " check failed: must be above 0")
    return out


def _checked_tol(tol_frac: object) -> float:
    """Tolerance as frac. Raises ValueError on bad input."""
    if isinstance(tol_frac, bool) or not isinstance(tol_frac, numbers.Real):
        raise ValueError("tol_frac check failed: must be a number")
    out = float(tol_frac)
    if not math.isfinite(out):
        raise ValueError("tol_frac check failed: must be finite")
    if not 0.0 <= out <= 0.5:
        raise ValueError("tol_frac check failed: must be in [0, 0.5]")
    return out


def _checked_index(index: object) -> pd.DatetimeIndex:
    """Hourly aware index check. Raises ValueError on bad input."""
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("index check failed: must be a DatetimeIndex")
    if index.tz is None:
        raise ValueError("index check failed: must be time zone aware")
    if len(index) < 24:
        raise ValueError(
            "index check failed: need at least 24 entries, got " + str(len(index))
        )
    diffs = index.to_series().diff().dropna()
    if bool((diffs != pd.Timedelta(hours=1)).any()):
        raise ValueError("index check failed: steps must be exactly one hour")
    return index


def _checked_local_tz(index: pd.DatetimeIndex, local_tz: object) -> pd.DatetimeIndex:
    """Index converted to local_tz. Raises ValueError on bad input."""
    if not isinstance(local_tz, str):
        raise ValueError("local_tz check failed: must be a string")
    try:
        local = index.tz_convert(local_tz)
    except Exception as exc:
        raise ValueError("local_tz check failed: " + repr(local_tz)) from exc
    if bool((local.minute != 0).any()):
        raise ValueError(
            "local minute check failed: every stamp must fall on a whole hour in "
            + local_tz
        )
    return local


def check_daily_profile(
    profile_kw: object,
    daily_kwh_expected: float,
    peak_kw_expected: float,
    tol_frac: float = 0.02,
) -> None:
    """Check a 24 hour profile in kW against daily kWh and peak kW."""
    vals = _checked_profile(profile_kw)
    daily = _checked_expected("daily_kwh_expected", daily_kwh_expected)
    peak = _checked_expected("peak_kw_expected", peak_kw_expected)
    tol = _checked_tol(tol_frac)
    total_kwh = float(sum(vals))
    if abs(total_kwh - daily) / daily > tol:
        raise ValueError(
            "daily sum check failed: sum "
            + str(total_kwh)
            + " differs from expected "
            + str(daily)
            + " by more than tol_frac "
            + str(tol)
        )
    top_kw = float(max(vals))
    if abs(top_kw - peak) / peak > tol:
        raise ValueError(
            "peak check failed: max "
            + str(top_kw)
            + " differs from expected "
            + str(peak)
            + " by more than tol_frac "
            + str(tol)
        )


def daily_profile_to_hourly(
    profile_kw: object,
    index: pd.DatetimeIndex,
    local_tz: str = LOCAL_TZ,
) -> pd.Series:
    """Repeat a daily kW profile over an hourly index. Returns load in kW."""
    vals = _checked_profile(profile_kw)
    checked = _checked_index(index)
    local = _checked_local_tz(checked, local_tz)
    hours = local.hour.to_numpy()
    data = np.array([vals[int(hour)] for hour in hours], dtype=np.float64)
    return pd.Series(data, index=checked, name="load_kw", dtype=np.float64)


def _checked_season_months(value: object) -> list[int]:
    """Season months as ints in 1 to 12. Raises ValueError on bad input."""
    if not isinstance(value, (tuple, list)):
        raise ValueError("season_months check failed: must be a tuple or list")
    if len(value) == 0:
        raise ValueError("season_months check failed: must not be empty")
    out: list[int] = []
    seen: set[int] = set()
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, numbers.Integral):
            raise ValueError(
                "season_months check failed: entries must be ints: " + repr(raw)
            )
        month = int(raw)
        if not 1 <= month <= 12:
            raise ValueError(
                "season_months check failed: entries must be in 1..12: " + repr(raw)
            )
        if month in seen:
            raise ValueError(
                "season_months check failed: duplicate month " + str(month)
            )
        seen.add(month)
        out.append(month)
    return out


def _checked_frac(name_str: str, value: object, hi: float) -> float:
    """Frac in [0, hi]. Raises ValueError on bad input."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(name_str + " check failed: must be a number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " check failed: must be finite")
    if not 0.0 <= out <= hi:
        raise ValueError(
            name_str + " check failed: must be in [0, " + str(hi) + "]"
        )
    return out


def _checked_year(name_str: str, value: object) -> int:
    """Year as int. Raises ValueError on bad input."""
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise ValueError(name_str + " check failed: must be an int")
    return int(value)


@dataclass(frozen=True)
class DemandCase:
    """One hourly demand case. Load in kW, totals in kWh."""

    name: str
    load_kw: pd.Series
    label: str
    source: str
    annual_kwh: float
    peak_kw: float
    notes: tuple[str, ...]


def _make_case(
    name: str,
    series: pd.Series,
    label: str,
    notes: tuple[str, ...],
) -> DemandCase:
    """DemandCase from an hourly load in kW."""
    load = pd.Series(
        series.to_numpy(dtype=float).astype(np.float64),
        index=series.index,
        name="load_kw",
        dtype=np.float64,
    )
    return DemandCase(
        name=name,
        load_kw=load,
        label=label,
        source=HIRON_2021_SOURCE,
        annual_kwh=float(load.sum()),
        peak_kw=float(load.max()),
        notes=notes,
    )


def build_demand_cases(
    index: pd.DatetimeIndex,
    *,
    profile_kw: object = HIRON_2021_LOAD_KW,
    season_months: object = (6, 7, 8, 12),
    season_uplift_frac: float = 0.15,
    growth_frac_per_yr: float = HIRON_2021_GROWTH_FRAC_PER_YR,
    base_year: int = HIRON_2021_BASE_YEAR,
    target_year: int = 2027,
    local_tz: str = LOCAL_TZ,
) -> dict[str, DemandCase]:
    """Three hourly demand cases in kW on the given index."""
    months = _checked_season_months(season_months)
    uplift = _checked_frac("season_uplift_frac", season_uplift_frac, 1.0)
    growth = _checked_frac("growth_frac_per_yr", growth_frac_per_yr, 0.2)
    base = _checked_year("base_year", base_year)
    target = _checked_year("target_year", target_year)
    if base > target:
        raise ValueError("base_year check failed: must be <= target_year")
    paper_series = daily_profile_to_hourly(profile_kw, index, local_tz)
    if not isinstance(local_tz, str):
        raise ValueError("local_tz check failed: must be a string")
    local = paper_series.index.tz_convert(local_tz)
    in_season = np.isin(local.month.to_numpy(), np.array(months))
    paper_vals = paper_series.to_numpy(dtype=float)
    season_vals = paper_vals * np.where(in_season, 1.0 + uplift, 1.0)
    season_series = pd.Series(
        season_vals.astype(np.float64),
        index=paper_series.index,
        name="load_kw",
        dtype=np.float64,
    )
    factor = float((1.0 + growth) ** (target - base))
    growth_vals = paper_vals * factor
    growth_series = pd.Series(
        growth_vals.astype(np.float64),
        index=paper_series.index,
        name="load_kw",
        dtype=np.float64,
    )
    paper = _make_case(
        "paper",
        paper_series,
        "paper",
        ("profile repeated every day; local hour in " + str(local_tz),),
    )
    season = _make_case(
        "tourist season",
        season_series,
        "assumed scenario",
        (
            "season months "
            + str(months)
            + ", uplift "
            + f"{uplift * 100:.1f}"
            + "% (assumed)",
        ),
    )
    grown = _make_case(
        "growth",
        growth_series,
        "assumed scenario",
        (
            f"growth {growth * 100:.2f}% per year from {base} to {target}",
        ),
    )
    return {"paper": paper, "tourist season": season, "growth": grown}
