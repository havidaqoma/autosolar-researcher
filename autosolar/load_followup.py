"""Post hoc study at the load the paper chart implies. Loads in kW, energy in kWh, money in USD."""

from __future__ import annotations

import math
import numbers
from typing import Any

from autosolar.sweep import cost_table, dispatch_grid, least_cost

LOAD_FOLLOWUP_SCHEMA = "autosolar.load_followup/1"
REL_TOL = 1e-9

NOTE = "Added after the load check result (post hoc). The study's own answer and inputs are unchanged."


def _is_real(value: object) -> bool:
    """True for a real number that is not a bool."""
    if isinstance(value, bool):
        return False
    return isinstance(value, numbers.Real)


def _finite_above_zero(value: object) -> float:
    """Finite real above 0 as float. Raises ValueError otherwise."""
    if not _is_real(value):
        raise ValueError("value must be a finite real above 0: " + repr(value))
    out = float(value)  # type: ignore[arg-type]
    if not math.isfinite(out) or not out > 0.0:
        raise ValueError("value must be a finite real above 0: " + repr(value))
    return out


def followup_cases(figure_check: dict, swing_frac: float) -> list[dict]:
    """Four load scales in frac from a figure check and a swing in frac."""
    if not isinstance(figure_check, dict):
        raise ValueError("figure_check comparison must be a dict with verdict inside or outside band")
    comparison = figure_check.get("comparison")
    if not isinstance(comparison, dict):
        raise ValueError("figure_check comparison must be a dict with verdict inside or outside band")
    verdict = comparison.get("verdict")
    if verdict not in ("inside band", "outside band"):
        raise ValueError("figure_check comparison verdict must be inside band or outside band")
    for key in ("ratio", "mean_ratio"):
        val = comparison.get(key)
        if not _is_real(val):
            raise ValueError("figure_check comparison " + key + " must be a finite real above 0")
        num = float(val)  # type: ignore[arg-type]
        if not math.isfinite(num) or not num > 0.0:
            raise ValueError("figure_check comparison " + key + " must be a finite real above 0")
    basis = comparison.get("basis_series")
    if not isinstance(basis, str) or len(basis) == 0:
        raise ValueError("figure_check comparison basis_series must be a non-empty string")
    series = comparison.get("series")
    if not isinstance(series, list) or len(series) == 0:
        raise ValueError("figure_check comparison series must be a non-empty list")
    if not _is_real(swing_frac):
        raise ValueError("swing_frac must be a finite real above 0 and below 1: " + repr(swing_frac))
    swing_f = float(swing_frac)  # type: ignore[arg-type]
    if not math.isfinite(swing_f) or not 0.0 < swing_f < 1.0:
        raise ValueError("swing_frac must be a finite real above 0 and below 1: " + repr(swing_frac))
    ratio_f = float(comparison["ratio"])  # type: ignore[arg-type]
    mean_f = float(comparison["mean_ratio"])  # type: ignore[arg-type]
    return [
        {"key": "chart_basis", "scale_frac": float(1.0 / ratio_f), "post_hoc": True},
        {"key": "chart_mean", "scale_frac": float(1.0 / mean_f), "post_hoc": True},
        {"key": "swing_low", "scale_frac": float(1.0 - swing_f), "post_hoc": False},
        {"key": "swing_high", "scale_frac": float(1.0 + swing_f), "post_hoc": False},
    ]


def load_followup(
    pv_ac_kw_per_kwp: Any,
    load_kw: Any,
    pv_kwp_grid: Any,
    battery_kwh_grid: Any,
    *,
    battery_hours: float,
    battery_template: Any,
    diesel: Any,
    costs: Any,
    co2_kg_per_l: float,
    unserved_max_frac: float,
    main_pv_kwp: float,
    main_battery_kwh: float,
    scales: Any,
) -> list[dict]:
    """Least cost row per load scale in frac. Power in kW, energy in kWh, money in USD."""
    if not isinstance(scales, (list, tuple)) or len(scales) == 0:
        raise ValueError("scales must be a non-empty list or tuple")
    scale_fs: list[float] = []
    for item in scales:
        if not _is_real(item):
            raise ValueError("scales must hold finite reals above 0: " + repr(item))
        num = float(item)  # type: ignore[arg-type]
        if not math.isfinite(num) or not num > 0.0:
            raise ValueError("scales must hold finite reals above 0: " + repr(item))
        scale_fs.append(num)
    if not isinstance(pv_kwp_grid, (list, tuple)) or not any(
        float(v) == 0.0 for v in pv_kwp_grid  # type: ignore[arg-type]
    ):
        raise ValueError("pv_kwp_grid must hold 0.0")
    if not isinstance(battery_kwh_grid, (list, tuple)) or not any(
        float(v) == 0.0 for v in battery_kwh_grid  # type: ignore[arg-type]
    ):
        raise ValueError("battery_kwh_grid must hold 0.0")
    try:
        main_pv_f = float(main_pv_kwp)  # type: ignore[arg-type]
        main_bat_f = float(main_battery_kwh)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError("main sizes must be in the grids")
    if not any(float(v) == main_pv_f for v in pv_kwp_grid):  # type: ignore[arg-type]
        raise ValueError("main_pv_kwp must be in the PV grid")
    if not any(float(v) == main_bat_f for v in battery_kwh_grid):  # type: ignore[arg-type]
        raise ValueError("main_battery_kwh must be in the battery grid")
    out: list[dict] = []
    for scale_f in scale_fs:
        scaled_kw = load_kw * scale_f
        points = dispatch_grid(
            pv_ac_kw_per_kwp,
            scaled_kw,
            pv_kwp_grid,
            battery_kwh_grid,
            battery_hours=battery_hours,
            battery_template=battery_template,
            diesel=diesel,
        )
        table = cost_table(points, costs, co2_kg_per_l)
        d0 = table[(table["pv_kwp"] == 0.0) & (table["battery_kwh"] == 0.0)].iloc[0]
        mrow = table[
            (table["pv_kwp"] == main_pv_f) & (table["battery_kwh"] == main_bat_f)
        ].iloc[0]
        d0_lcoe = float(d0["lcoe_usd_per_kwh"])
        try:
            best = least_cost(table, unserved_max_frac)
        except ValueError:
            best = None
        if best is None:
            out.append(
                {
                    "scale_frac": float(scale_f),
                    "demand_kwh_yr": float(scaled_kw.sum()),
                    "diesel_only_lcoe_usd_per_kwh": float(d0["lcoe_usd_per_kwh"]),
                    "diesel_only_unserved_frac": float(d0["unserved_frac"]),
                    "best_pv_kwp": None,
                    "best_battery_kwh": None,
                    "best_lcoe_usd_per_kwh": None,
                    "best_renewable_pct": None,
                    "saving_pct": None,
                    "main_lcoe_usd_per_kwh": float(mrow["lcoe_usd_per_kwh"]),
                    "main_unserved_frac": float(mrow["unserved_frac"]),
                    "main_saving_pct": float(
                        100.0 * (1.0 - float(mrow["lcoe_usd_per_kwh"]) / d0_lcoe)
                    ),
                }
            )
            continue
        best_lcoe = float(best["lcoe_usd_per_kwh"])
        out.append(
            {
                "scale_frac": float(scale_f),
                "demand_kwh_yr": float(scaled_kw.sum()),
                "diesel_only_lcoe_usd_per_kwh": float(d0["lcoe_usd_per_kwh"]),
                "diesel_only_unserved_frac": float(d0["unserved_frac"]),
                "best_pv_kwp": float(best["pv_kwp"]),
                "best_battery_kwh": float(best["battery_kwh"]),
                "best_lcoe_usd_per_kwh": best_lcoe,
                "best_renewable_pct": float(100.0 * float(best["renewable_fraction_frac"])),
                "saving_pct": float(100.0 * (1.0 - best_lcoe / d0_lcoe)),
                "main_lcoe_usd_per_kwh": float(mrow["lcoe_usd_per_kwh"]),
                "main_unserved_frac": float(mrow["unserved_frac"]),
                "main_saving_pct": float(
                    100.0 * (1.0 - float(mrow["lcoe_usd_per_kwh"]) / d0_lcoe)
                ),
            }
        )
    return out


def _close(a: object, b: object) -> bool:
    """True when floats match within REL_TOL. Inputs in any unit."""
    a_f = float(a)  # type: ignore[arg-type]
    b_f = float(b)  # type: ignore[arg-type]
    return abs(a_f - b_f) <= REL_TOL * max(1.0, abs(b_f))


def check_reproduction(report: dict, base_row: dict, low_row: dict, high_row: dict) -> list[str]:
    """Check follow-up rows give back the study numbers. Returns message strs."""
    errors: list[str] = []
    facts = report["facts"]
    if float(base_row["best_pv_kwp"]) != float(facts["best_pv_kwp"]["value"]):
        errors.append(
            "best_pv_kwp differs: %s vs %s" % (repr(base_row["best_pv_kwp"]), repr(facts["best_pv_kwp"]["value"]))
        )
    if float(base_row["best_battery_kwh"]) != float(facts["best_battery_kwh"]["value"]):
        errors.append(
            "best_battery_kwh differs: %s vs %s"
            % (repr(base_row["best_battery_kwh"]), repr(facts["best_battery_kwh"]["value"]))
        )
    if not _close(base_row["best_lcoe_usd_per_kwh"], facts["best_lcoe_usd_per_kwh"]["value"]):
        errors.append(
            "best_lcoe_usd_per_kwh differs: %s vs %s"
            % (repr(base_row["best_lcoe_usd_per_kwh"]), repr(facts["best_lcoe_usd_per_kwh"]["value"]))
        )
    if not _close(
        base_row["diesel_only_lcoe_usd_per_kwh"], facts["diesel_only_lcoe_usd_per_kwh"]["value"]
    ):
        errors.append(
            "diesel_only_lcoe_usd_per_kwh differs: %s vs %s"
            % (
                repr(base_row["diesel_only_lcoe_usd_per_kwh"]),
                repr(facts["diesel_only_lcoe_usd_per_kwh"]["value"]),
            )
        )
    for row in (low_row, high_row):
        scale_f = float(row["scale_frac"])
        match = None
        for cand in report.get("sensitivity_table", []):
            if cand.get("input") == "demand" and abs(float(cand.get("factor")) - scale_f) <= 1e-12:
                match = cand
                break
        if match is None:
            errors.append("demand row missing for factor %s" % repr(scale_f))
            continue
        if float(row["best_pv_kwp"]) != float(match["least_cost_pv_kwp"]):
            errors.append(
                "least_cost_pv_kwp differs at demand factor %s: %s vs %s"
                % (repr(scale_f), repr(row["best_pv_kwp"]), repr(match["least_cost_pv_kwp"]))
            )
        if float(row["best_battery_kwh"]) != float(match["least_cost_battery_kwh"]):
            errors.append(
                "least_cost_battery_kwh differs at demand factor %s: %s vs %s"
                % (repr(scale_f), repr(row["best_battery_kwh"]), repr(match["least_cost_battery_kwh"]))
            )
        if not _close(row["best_lcoe_usd_per_kwh"], match["least_cost_lcoe_usd_per_kwh"]):
            errors.append(
                "least_cost_lcoe_usd_per_kwh differs at demand factor %s: %s vs %s"
                % (repr(scale_f), repr(row["best_lcoe_usd_per_kwh"]), repr(match["least_cost_lcoe_usd_per_kwh"]))
            )
        if not _close(row["main_lcoe_usd_per_kwh"], match["base_design_lcoe_usd_per_kwh"]):
            errors.append(
                "base_design_lcoe_usd_per_kwh differs at demand factor %s: %s vs %s"
                % (
                    repr(scale_f),
                    repr(row["main_lcoe_usd_per_kwh"]),
                    repr(match["base_design_lcoe_usd_per_kwh"]),
                )
            )
    return errors


def followup_doc(
    report: dict,
    figure_check: dict,
    *,
    figure_check_id: str,
    run_id: str,
    base_row: dict,
    cases: list[dict],
    case_rows: list[dict],
    errors: list[str],
    wall_s: float,
) -> dict:
    """Follow-up record for the site page. Sizes in kWp and kWh, money in USD."""
    if len(cases) != len(case_rows):
        raise ValueError("cases and case_rows must hold the same count")
    comparison = figure_check["comparison"]
    merged: list[dict] = []
    for case, row in zip(cases, case_rows):
        item: dict = {}
        for key in case:
            item[key] = case[key]
        for key in row:
            item[key] = row[key]
        merged.append(item)
    grid = report["grid"]
    return {
        "schema": LOAD_FOLLOWUP_SCHEMA,
        "run_id": run_id,
        "study_run_hash": report["run_hash"],
        "figure_check_run_id": figure_check_id,
        "basis_series": comparison["basis_series"],
        "verdict": comparison["verdict"],
        "designs": int(len(grid["pv_kwp"]) * len(grid["battery_kwh"])),
        "base": dict(base_row),
        "cases": merged,
        "reproduced": len(errors) == 0,
        "reproduction_errors": list(errors),
        "wall_s": float(wall_s),
        "note": NOTE,
    }
