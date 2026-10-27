"""Grid search over PV and battery sizes. Power in kW, energy in kWh, money in USD."""

from __future__ import annotations

import dataclasses
import math
import numbers
from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from autosolar.dispatch import Battery, DieselFleet, DispatchResult, dispatch
from autosolar.econ import AnnualFlows, CostInputs, Design, evaluate

TABLE_COLUMNS = (
    "pv_kwp",
    "battery_kwh",
    "battery_kw",
    "lcoe_usd_per_kwh",
    "lcoe_path_a_usd_per_kwh",
    "npc_usd",
    "capex_initial_usd",
    "fuel_l_per_yr",
    "diesel_kwh_per_yr",
    "co2_t_per_yr",
    "renewable_fraction_frac",
    "unserved_frac",
    "pv_curtailed_frac",
    "diesel_starts",
    "diesel_run_hours",
)

SENSITIVITY_INPUTS = (
    "pv_capex_usd_per_kwp",
    "battery_capex_usd_per_kwh",
    "fuel_price_usd_per_l",
    "discount_rate_frac",
    "demand",
)

SENSITIVITY_COLUMNS = (
    "input",
    "factor",
    "base_design_lcoe_usd_per_kwh",
    "least_cost_pv_kwp",
    "least_cost_battery_kwh",
    "least_cost_lcoe_usd_per_kwh",
    "same_design",
    "note",
)

_INT_COLS = ("diesel_starts", "diesel_run_hours")


@dataclass(frozen=True)
class GridPoint:
    """One design with its dispatch. Sizes in kWp, kWh and kW."""

    design: Design
    result: DispatchResult


def _is_num(value: object) -> bool:
    """True for real numbers excluding bool."""
    if isinstance(value, bool):
        return False
    return isinstance(value, numbers.Real)


def _check_grid(name_str: str, grid: object, min_len: int) -> list[float]:
    """Check size grid. Returns values as floats."""
    if not isinstance(grid, (list, tuple)):
        raise ValueError(name_str + " must be a list or tuple")
    if len(grid) < min_len:
        raise ValueError(name_str + " needs at least " + str(min_len) + " values")
    vals: list[float] = []
    for v in grid:
        if not _is_num(v):
            raise ValueError(name_str + " must hold numbers, not bool: " + repr(v))
        f = float(v)  # type: ignore[arg-type]
        if not math.isfinite(f):
            raise ValueError(name_str + " must hold finite numbers: " + repr(v))
        vals.append(f)
    if vals[0] != 0.0:
        raise ValueError(name_str + " first value must be exactly 0")
    for i in range(1, len(vals)):
        if not vals[i] > vals[i - 1]:
            raise ValueError(name_str + " must be strictly increasing")
    return vals


def _check_battery_hours(value: object) -> float:
    """Check battery hours in h. Returns float."""
    if not _is_num(value):
        raise ValueError("battery_hours must be a number: " + repr(value))
    out = float(value)  # type: ignore[arg-type]
    if not math.isfinite(out):
        raise ValueError("battery_hours must be finite: " + repr(value))
    if not out > 0.0:
        raise ValueError("battery_hours must be > 0: " + repr(value))
    return out


def _check_frac01(name_str: str, value: object) -> float:
    """Check fraction in [0, 1]. Returns float."""
    if not _is_num(value):
        raise ValueError(name_str + " must be a number: " + repr(value))
    out = float(value)  # type: ignore[arg-type]
    if not math.isfinite(out):
        raise ValueError(name_str + " must be finite: " + repr(value))
    if not 0.0 <= out <= 1.0:
        raise ValueError(name_str + " must be in [0, 1]: " + repr(value))
    return out


def _check_swing_frac(value: object) -> float:
    """Check swing fraction in (0, 1). Returns float."""
    if not _is_num(value):
        raise ValueError("swing_frac must be a number: " + repr(value))
    out = float(value)  # type: ignore[arg-type]
    if not math.isfinite(out):
        raise ValueError("swing_frac must be finite: " + repr(value))
    if not 0.0 < out < 1.0:
        raise ValueError("swing_frac must be in (0, 1): " + repr(value))
    return out


def dispatch_grid(
    pv_ac_kw_per_kwp: pd.Series,
    load_kw: pd.Series,
    pv_kwp_grid: Sequence[float],
    battery_kwh_grid: Sequence[float],
    *,
    battery_hours: float,
    battery_template: Battery,
    diesel: DieselFleet,
) -> list[GridPoint]:
    """Dispatch every PV kWp and battery kWh pair. Power in kW, energy in kWh."""
    _check_grid("pv_kwp_grid", pv_kwp_grid, 2)
    _check_grid("battery_kwh_grid", battery_kwh_grid, 1)
    hours_f = _check_battery_hours(battery_hours)
    if not isinstance(battery_template, Battery):
        raise ValueError("battery_template must be a Battery")
    if not isinstance(diesel, DieselFleet):
        raise ValueError("diesel must be a DieselFleet")
    out: list[GridPoint] = []
    for pv in pv_kwp_grid:  # type: ignore[union-attr]
        pv_f = float(pv)  # type: ignore[arg-type]
        pv_kw = pv_ac_kw_per_kwp * pv_f
        for b in battery_kwh_grid:  # type: ignore[union-attr]
            b_f = float(b)  # type: ignore[arg-type]
            if b_f == 0.0:
                bat = Battery(
                    energy_kwh=0.0,
                    power_kw=0.0,
                    round_trip_eff_frac=battery_template.round_trip_eff_frac,
                    soc_min_frac=battery_template.soc_min_frac,
                    soc_initial_frac=battery_template.soc_initial_frac,
                )
            else:
                bat = Battery(
                    energy_kwh=b_f,
                    power_kw=b_f / hours_f,
                    round_trip_eff_frac=battery_template.round_trip_eff_frac,
                    soc_min_frac=battery_template.soc_min_frac,
                    soc_initial_frac=battery_template.soc_initial_frac,
                )
            result = dispatch(pv_kw, load_kw, bat, diesel)
            design = Design(pv_kwp=pv_f, battery_kwh=b_f, battery_kw=b_f / hours_f)
            out.append(GridPoint(design=design, result=result))
    return out


def cost_table(
    points: Sequence[GridPoint], costs: CostInputs, co2_kg_per_l: float
) -> pd.DataFrame:
    """Cost each dispatched point. Money in USD, energy in kWh, fuel in l."""
    if points is None or len(points) == 0:  # type: ignore[arg-type]
        raise ValueError("points must not be empty")
    rows: list[dict[str, float]] = []
    for p in points:
        r = p.result
        flows = AnnualFlows(
            load_served_kwh=r.load_served_kwh, fuel_l=r.fuel_l, diesel_kwh=r.diesel_kwh
        )
        e = evaluate(p.design, flows, costs, co2_kg_per_l)
        if r.pv_available_kwh == 0.0:
            curtailed_frac = 0.0
        else:
            curtailed_frac = r.pv_curtailed_kwh / r.pv_available_kwh
        rows.append(
            {
                "pv_kwp": float(p.design.pv_kwp),
                "battery_kwh": float(p.design.battery_kwh),
                "battery_kw": float(p.design.battery_kw),
                "lcoe_usd_per_kwh": float(e.lcoe_usd_per_kwh),
                "lcoe_path_a_usd_per_kwh": float(e.lcoe_path_a_usd_per_kwh),
                "npc_usd": float(e.npc_usd),
                "capex_initial_usd": float(e.capex_initial_usd),
                "fuel_l_per_yr": float(r.fuel_l),
                "diesel_kwh_per_yr": float(r.diesel_kwh),
                "co2_t_per_yr": float(e.co2_t_per_yr),
                "renewable_fraction_frac": float(r.renewable_fraction_frac),
                "unserved_frac": float(r.unserved_frac),
                "pv_curtailed_frac": float(curtailed_frac),
                "diesel_starts": int(r.diesel_starts),
                "diesel_run_hours": int(r.diesel_run_hours),
            }
        )
    table = pd.DataFrame(rows, columns=list(TABLE_COLUMNS))
    for col in TABLE_COLUMNS:
        if col in _INT_COLS:
            table[col] = table[col].astype("int64")
        else:
            table[col] = table[col].astype("float64")
    return table


def least_cost(table: pd.DataFrame, unserved_max_frac: float) -> pd.Series:
    """Cheapest feasible row by LCOE in USD per kWh. Ties go to earliest row."""
    limit_f = _check_frac01("unserved_max_frac", unserved_max_frac)
    feas = table[table["unserved_frac"] <= limit_f]
    if len(feas) == 0:
        raise ValueError("no feasible row within unserved_max_frac")
    label = feas["lcoe_usd_per_kwh"].idxmin()
    return table.loc[label]


def on_grid_edge(table: pd.DataFrame, row: pd.Series) -> bool:
    """True when row sits on the high PV kWp or battery kWh edge."""
    return bool(
        float(row["pv_kwp"]) == float(table["pv_kwp"].max())
        or float(row["battery_kwh"]) == float(table["battery_kwh"].max())
    )


def high_renewable(
    table: pd.DataFrame, rf_target_frac: float, unserved_max_frac: float
) -> pd.Series | None:
    """Cheapest feasible row above renewable share. None when there is none."""
    target_f = _check_frac01("rf_target_frac", rf_target_frac)
    limit_f = _check_frac01("unserved_max_frac", unserved_max_frac)
    feas = table[
        (table["unserved_frac"] <= limit_f)
        & (table["renewable_fraction_frac"] >= target_f)
    ]
    if len(feas) == 0:
        return None
    label = feas["lcoe_usd_per_kwh"].idxmin()
    return table.loc[label]


def break_even_fuel_price_usd_per_l(
    points: Sequence[GridPoint],
    costs: CostInputs,
    co2_kg_per_l: float,
    unserved_max_frac: float,
) -> float:
    """Fuel price in USD per l below which diesel only wins. Inf when never."""
    limit_f = _check_frac01("unserved_max_frac", unserved_max_frac)
    if points is None or len(points) == 0:  # type: ignore[arg-type]
        raise ValueError("points must not be empty")
    diesel_pts = [
        p
        for p in points
        if float(p.design.pv_kwp) == 0.0 and float(p.design.battery_kwh) == 0.0
    ]
    if len(diesel_pts) == 0:
        raise ValueError("diesel only point is missing")
    d0 = diesel_pts[0]
    if not float(d0.result.unserved_frac) <= limit_f:
        raise ValueError("diesel only point is not feasible")
    costs0 = dataclasses.replace(costs, fuel_price_usd_per_l=0.0)

    def _line(p: GridPoint) -> tuple[float, float]:
        """Intercept a in USD per kWh and slope s in l per kWh."""
        r = p.result
        flows = AnnualFlows(
            load_served_kwh=r.load_served_kwh, fuel_l=r.fuel_l, diesel_kwh=r.diesel_kwh
        )
        a = float(evaluate(p.design, flows, costs0, co2_kg_per_l).lcoe_usd_per_kwh)
        s = float(r.fuel_l) / float(r.load_served_kwh)
        return (a, s)

    a0, s0 = _line(d0)
    prices: list[float] = []
    for p in points:
        if p is d0:
            continue
        if float(p.design.pv_kwp) == 0.0 and float(p.design.battery_kwh) == 0.0:
            continue
        if not float(p.result.unserved_frac) <= limit_f:
            continue
        ai, si = _line(p)
        if si < s0:
            prices.append((ai - a0) / (s0 - si))
    if len(prices) == 0:
        return math.inf
    return max(0.0, min(prices))


def sensitivity_table(
    pv_ac_kw_per_kwp: pd.Series,
    load_kw: pd.Series,
    pv_kwp_grid: Sequence[float],
    battery_kwh_grid: Sequence[float],
    *,
    battery_hours: float,
    battery_template: Battery,
    diesel: DieselFleet,
    costs: CostInputs,
    co2_kg_per_l: float,
    unserved_max_frac: float,
    swing_frac: float = 0.2,
) -> pd.DataFrame:
    """Least cost sensitivity to cost and demand moves. Money in USD."""
    limit_f = _check_frac01("unserved_max_frac", unserved_max_frac)
    swing_f = _check_swing_frac(swing_frac)
    base_points = dispatch_grid(
        pv_ac_kw_per_kwp,
        load_kw,
        pv_kwp_grid,
        battery_kwh_grid,
        battery_hours=battery_hours,
        battery_template=battery_template,
        diesel=diesel,
    )
    base_table = cost_table(base_points, costs, co2_kg_per_l)
    base = least_cost(base_table, limit_f)
    i_base = int(base.name)  # type: ignore[arg-type]
    factors = (1.0 - swing_f, 1.0 + swing_f)
    rows: list[dict[str, object]] = []
    for name in SENSITIVITY_INPUTS:
        for factor in factors:
            factor_f = float(factor)
            if name == "demand":
                pts = dispatch_grid(
                    pv_ac_kw_per_kwp,
                    load_kw * factor_f,
                    pv_kwp_grid,
                    battery_kwh_grid,
                    battery_hours=battery_hours,
                    battery_template=battery_template,
                    diesel=diesel,
                )
                tab = cost_table(pts, costs, co2_kg_per_l)
            else:
                case_costs = dataclasses.replace(
                    costs, **{name: float(getattr(costs, name)) * factor_f}
                )
                tab = cost_table(base_points, case_costs, co2_kg_per_l)
            base_lcoe = float(tab["lcoe_usd_per_kwh"].iloc[i_base])
            try:
                best = least_cost(tab, limit_f)
            except ValueError:
                rows.append(
                    {
                        "input": name,
                        "factor": factor_f,
                        "base_design_lcoe_usd_per_kwh": base_lcoe,
                        "least_cost_pv_kwp": math.nan,
                        "least_cost_battery_kwh": math.nan,
                        "least_cost_lcoe_usd_per_kwh": math.nan,
                        "same_design": False,
                        "note": "no feasible design",
                    }
                )
                continue
            same = bool(
                float(best["pv_kwp"]) == float(base["pv_kwp"])
                and float(best["battery_kwh"]) == float(base["battery_kwh"])
            )
            rows.append(
                {
                    "input": name,
                    "factor": factor_f,
                    "base_design_lcoe_usd_per_kwh": base_lcoe,
                    "least_cost_pv_kwp": float(best["pv_kwp"]),
                    "least_cost_battery_kwh": float(best["battery_kwh"]),
                    "least_cost_lcoe_usd_per_kwh": float(best["lcoe_usd_per_kwh"]),
                    "same_design": same,
                    "note": "",
                }
            )
    out = pd.DataFrame(rows, columns=list(SENSITIVITY_COLUMNS))
    return out
