"""Second read of the load from the paper chart. Loads in kW and kWh."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from autosolar.chart_reader import CHART_READER_VALIDATION, ChartReadError, ChartSpec, read_chart

FIGURE_PLAN_SCHEMA = "autosolar.figure_plan/1"
FIGURE_CHECK_SCHEMA = "autosolar.figure_check/1"
MIN_HOURS = 12

_PLAN_KEYS = ("schema", "paper", "figure", "image", "image_sha256", "series", "x_kind", "y_kind", "y_unit",
              "x_values", "stacking", "compare")
_SERIES_KEYS = ("name", "prompt")
_COMPARE_KEYS = ("table", "basis_series", "basis_note", "table_year", "figure_year", "growth_frac_per_yr",
                 "band_frac")
_HEX_CHARS = set("0123456789abcdef")


def _is_bool(value: Any) -> bool:
    """Check for bool type. Input in any unit, output in flag."""
    return type(value) is bool


def _is_finite_real(value: Any) -> bool:
    """Check for finite int or float. Input in any unit, output in flag."""
    if _is_bool(value):
        return False
    if type(value) not in (int, float):
        return False
    return math.isfinite(float(value))


def _need_str_nonempty(value: Any, field: str) -> str:
    """Require a non empty string. Input in str, output in str."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(field + " must be a non empty string")
    return value


def _check_growth_frac_per_yr(value: Any) -> float:
    """Check the yearly growth fraction. Input in fraction, output in fraction."""
    if not _is_finite_real(value):
        raise ValueError("growth_frac_per_yr must be a finite real from 0 to 0.5")
    num = float(value)
    if num < 0.0 or num > 0.5:
        raise ValueError("growth_frac_per_yr must be a finite real from 0 to 0.5")
    return num


def _check_band_frac(value: Any) -> float:
    """Check the band fraction. Input in fraction, output in fraction."""
    if not _is_finite_real(value):
        raise ValueError("band_frac must be a finite real above 0 and below 1")
    num = float(value)
    if not 0.0 < num < 1.0:
        raise ValueError("band_frac must be a finite real above 0 and below 1")
    return num


def _check_year_pair(table_year: Any, figure_year: Any) -> tuple[int, int]:
    """Check the year pair. Inputs in years, outputs in years."""
    if _is_bool(table_year) or type(table_year) is not int:
        raise ValueError("table_year must be an int")
    if _is_bool(figure_year) or type(figure_year) is not int:
        raise ValueError("figure_year must be an int")
    if int(table_year) < int(figure_year):
        raise ValueError("table_year must be at or after figure_year")
    return int(table_year), int(figure_year)


def _check_table_kw(table_kw: Any) -> list[float]:
    """Check the hourly table load. Input in kW, output in kW."""
    if not isinstance(table_kw, (list, tuple)):
        raise ValueError("table_kw must hold 24 finite values in kW of at least 0")
    if len(table_kw) != 24:
        raise ValueError("table_kw must hold 24 finite values in kW of at least 0")
    out: list[float] = []
    for value in table_kw:
        if not _is_finite_real(value):
            raise ValueError("table_kw must hold 24 finite values in kW of at least 0")
        num = float(value)
        if num < 0.0:
            raise ValueError("table_kw must hold 24 finite values in kW of at least 0")
        out.append(num)
    return out


def load_plan(path: Any) -> dict:
    """Read a figure plan file. Values in kWh, years and fractions. Returns dict."""
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("plan must be a JSON object")
    if set(raw) != set(_PLAN_KEYS):
        for key in _PLAN_KEYS:
            if key not in raw:
                raise ValueError("plan is missing field: " + key)
        for key in raw:
            if key not in _PLAN_KEYS:
                raise ValueError("plan has extra field: " + str(key))
        raise ValueError("plan must hold exactly the plan fields")
    if raw["schema"] != FIGURE_PLAN_SCHEMA:
        raise ValueError("schema must equal " + FIGURE_PLAN_SCHEMA)
    _need_str_nonempty(raw["paper"], "paper")
    _need_str_nonempty(raw["figure"], "figure")
    _need_str_nonempty(raw["image"], "image")
    sha = raw["image_sha256"]
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in _HEX_CHARS for c in sha):
        raise ValueError("image_sha256 must be 64 lowercase hex characters")
    series = raw["series"]
    if not isinstance(series, list) or len(series) == 0:
        raise ValueError("series must be a non empty list")
    names: list[str] = []
    for item in series:
        if not isinstance(item, dict) or set(item) != set(_SERIES_KEYS):
            raise ValueError("series items must hold exactly name and prompt")
        for field in _SERIES_KEYS:
            _need_str_nonempty(item[field], "series " + field)
        names.append(str(item["name"]))
    if len(set(names)) != len(names):
        raise ValueError("series names must be unique")
    if raw["x_kind"] not in ("clock", "number"):
        raise ValueError('x_kind must be "clock" or "number"')
    if raw["y_kind"] not in ("clock", "number"):
        raise ValueError('y_kind must be "clock" or "number"')
    if raw["y_unit"] != "kWh":
        raise ValueError('y_unit must be "kWh"')
    x_values = raw["x_values"]
    if not isinstance(x_values, list) or len(x_values) != 24:
        raise ValueError("x_values must be the 24 hours 0 to 23 in order")
    for pos, value in enumerate(x_values):
        if not _is_finite_real(value) or float(value) != float(pos):
            raise ValueError("x_values must be the 24 hours 0 to 23 in order")
    if raw["stacking"] not in ("overlap", "none"):
        raise ValueError('stacking must be "overlap" or "none"')
    compare = raw["compare"]
    if not isinstance(compare, dict) or set(compare) != set(_COMPARE_KEYS):
        raise ValueError("compare must hold exactly the compare fields")
    _need_str_nonempty(compare["table"], "compare table")
    if not isinstance(compare["basis_series"], str) or compare["basis_series"] not in names:
        raise ValueError("compare basis_series must be one of the series names")
    if not isinstance(compare["basis_note"], str):
        raise ValueError("compare basis_note must be a string")
    _check_year_pair(compare["table_year"], compare["figure_year"])
    _check_growth_frac_per_yr(compare["growth_frac_per_yr"])
    _check_band_frac(compare["band_frac"])
    plan = dict(raw)
    plan["series"] = [dict(item) for item in series]
    plan["x_values"] = [float(v) for v in x_values]
    plan["compare"] = dict(compare)
    return plan


def _check_values_status(values: Any, status: Any) -> list[str]:
    """Check the read values and statuses. Values in kWh, output in names."""
    if not isinstance(values, dict) or len(values) == 0:
        raise ValueError("values must be a non empty dict of 24 values in kWh")
    if not isinstance(status, dict) or set(status) != set(values):
        raise ValueError("status must be a dict with the same keys as values")
    names = list(values)
    for name in names:
        vals = values[name]
        stats = status[name]
        if not isinstance(vals, (list, tuple)) or len(vals) != 24:
            raise ValueError("values for " + str(name) + " must hold 24 values in kWh")
        if not isinstance(stats, (list, tuple)) or len(stats) != 24:
            raise ValueError("status for " + str(name) + " must hold 24 strings")
        for item in stats:
            if not isinstance(item, str):
                raise ValueError("status for " + str(name) + " must hold 24 strings")
        for item in vals:
            if item is None:
                continue
            if not _is_finite_real(item):
                raise ValueError("values for " + str(name) + " must be finite reals or None in kWh")
    return names


def compare_load(values: dict, status: dict, table_kw: Any, *, basis_series: str, table_year: int,
                 figure_year: int, growth_frac_per_yr: float, band_frac: float) -> dict:
    """Compare the table load with the read curves. Loads in kW and kWh. Returns dict."""
    names = _check_values_status(values, status)
    table_list_kv = table_kw if isinstance(table_kw, (list, tuple)) else None
    if table_list_kv is None:
        raise ValueError("table_kw must hold 24 finite values in kW of at least 0")
    table_checked_kw = _check_table_kw(list(table_list_kv))
    if basis_series not in values:
        raise ValueError("basis_series must be one of the series names")
    table_year_i, figure_year_i = _check_year_pair(table_year, figure_year)
    growth_num = _check_growth_frac_per_yr(growth_frac_per_yr)
    band_num = _check_band_frac(band_frac)
    years = table_year_i - figure_year_i
    scale = (1.0 + growth_num) ** years
    table_at_figure_year_kw = [v / scale for v in table_checked_kw]
    hours: list[int] = []
    for pos in range(24):
        keep = True
        for name in names:
            if status[name][pos] != "validated" or values[name][pos] is None:
                keep = False
                break
        if keep:
            hours.append(pos)
    base: dict[str, Any] = {"hours": hours, "years": years, "scale": float(scale),
                            "table_at_figure_year_kw": list(table_at_figure_year_kw),
                            "basis_series": basis_series, "band_frac": float(band_num)}
    if len(hours) < MIN_HOURS:
        return {**base, "verdict": "not checkable",
                "reason": "fewer than 12 hours read and validated in every curve", "table_kwh": None,
                "series": [], "ratio": None, "diff_pct": None, "mean_ratio": None}
    basis_kwh = float(sum(float(values[basis_series][h]) for h in hours))
    if basis_kwh <= 0.0:
        return {**base, "verdict": "not checkable", "reason": "basis curve has no energy", "table_kwh": None,
                "series": [], "ratio": None, "diff_pct": None, "mean_ratio": None}
    table_kwh = float(sum(table_at_figure_year_kw[h] for h in hours))
    rows: list[dict] = []
    for name in names:
        kwh = float(sum(float(values[name][h]) for h in hours))
        peak_kwh = float(max(float(values[name][h]) for h in hours))
        ratio = table_kwh / kwh if kwh > 0.0 else None
        rows.append({"name": name, "kwh": kwh, "peak_kwh": peak_kwh, "ratio": ratio})
    ratio = table_kwh / basis_kwh
    diff_pct = 100.0 * (ratio - 1.0)
    mean_kwh = float(sum(r["kwh"] for r in rows) / len(rows))
    mean_ratio = table_kwh / mean_kwh if mean_kwh > 0.0 else None
    verdict = "inside band" if abs(ratio - 1.0) <= band_num + 1e-12 else "outside band"
    return {**base, "verdict": verdict, "reason": "", "table_kwh": table_kwh, "series": rows, "ratio": ratio,
            "diff_pct": diff_pct, "mean_ratio": mean_ratio}


def run_figure_check(plan: dict, image_png: bytes, table_kw: Any, segment: Any, read_labels: Any) -> dict:
    """Run one figure check on chart bytes. Loads in kW and kWh. Returns dict."""
    digest = hashlib.sha256(bytes(image_png)).hexdigest()
    if digest != plan["image_sha256"]:
        raise ValueError("image sha256 does not match the plan image_sha256")
    checked_kw = _check_table_kw(list(table_kw) if isinstance(table_kw, (list, tuple)) else table_kw)
    spec = ChartSpec(series={item["name"]: item["prompt"] for item in plan["series"]},
                     x_kind=plan["x_kind"], y_kind=plan["y_kind"], y_unit=plan["y_unit"],
                     stacking=plan["stacking"], x_values=tuple(float(v) for v in plan["x_values"]))
    try:
        reading = read_chart(bytes(image_png), spec, segment, read_labels)
    except ChartReadError as err:
        return {"schema": FIGURE_CHECK_SCHEMA, "plan": plan, "image_sha256": digest,
                "table_kw": [float(v) for v in checked_kw], "verdict": "not checkable",
                "reason": "chart not read: " + str(err), "reading": None, "comparison": None,
                "validation": dict(CHART_READER_VALIDATION)}
    compare_in = plan["compare"]
    comparison = compare_load(reading.values, reading.point_status, checked_kw,
                              basis_series=compare_in["basis_series"], table_year=compare_in["table_year"],
                              figure_year=compare_in["figure_year"],
                              growth_frac_per_yr=compare_in["growth_frac_per_yr"], band_frac=compare_in["band_frac"])
    reading_dict = {"values": {k: list(v) for k, v in reading.values.items()},
                    "point_status": {k: list(v) for k, v in reading.point_status.items()},
                    "y_unit": reading.y_unit, "sam_calls": reading.sam_calls,
                    "label_calls": reading.label_calls,
                    "x_axis": {"slope": float(reading.x_axis.slope),
                               "intercept": float(reading.x_axis.intercept),
                               "used": [int(i) for i in reading.x_axis.used],
                               "dropped": [int(i) for i in reading.x_axis.dropped],
                               "max_resid": float(reading.x_axis.max_resid)},
                    "y_axis": {"slope": float(reading.y_axis.slope),
                               "intercept": float(reading.y_axis.intercept),
                               "used": [int(i) for i in reading.y_axis.used],
                               "dropped": [int(i) for i in reading.y_axis.dropped],
                               "max_resid": float(reading.y_axis.max_resid)}}
    return {"schema": FIGURE_CHECK_SCHEMA, "plan": plan, "image_sha256": digest,
            "table_kw": [float(v) for v in checked_kw], "verdict": comparison["verdict"],
            "reason": comparison["reason"], "reading": reading_dict, "comparison": comparison,
            "validation": dict(CHART_READER_VALIDATION)}
