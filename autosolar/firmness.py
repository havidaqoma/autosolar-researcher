"""How firm the least cost answer is. Sizes in kWp and kWh, money in USD, shares in pct."""

from __future__ import annotations

import dataclasses
import json
import math
import numbers
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from autosolar.dispatch import Battery, DieselFleet, DispatchResult
from autosolar.econ import CostInputs
from autosolar.sweep import GridPoint, cost_table, dispatch_grid, least_cost, on_grid_edge

CHECKS_SCHEMA = "autosolar.checks/1"
CHECK_NAMES = ("site_land_ha", "pv_mwdc_per_ha", "reference_pv_kwp", "diesel_must_run_units", "near_tie_frac")
OPTIONAL_CHECK_NAMES = ("diesel_unit_kw_alt", "battery_duration_h_alt")
LABELS = ("measured", "computed", "assumed", "press", "paper", "paper (abstract)", "docs")
OUT_OF_SCOPE = (
    "Grid stability: frequency and voltage control, grid forming inverters and protection for hours with no diesel running",
    "Land ownership, permits and the environmental review",
    "Site layout, shading, soil and access for construction",
    "Shipping to the island, local labour and construction time",
    "Financing terms, tariffs, subsidies and who pays",
    "Demand growth beyond the growth case, and new loads such as electric boats",
    "Battery ageing beyond the replacement rule, and salt air corrosion",
    "Diesel price risk beyond the sensitivity table",
    "Diesel overhaul and engine replacement costs, which grow with engine hours",
)
FIRM_SPECS = (
    ("near_tie_pct", "%", "check", 1),
    ("near_tie_count", "designs", "computed", 0),
    ("near_tie_pv_kwp_min", "kWp", "computed", 0),
    ("near_tie_pv_kwp_max", "kWp", "computed", 0),
    ("near_tie_battery_kwh_min", "kWh", "computed", 0),
    ("near_tie_battery_kwh_max", "kWh", "computed", 0),
    ("best_diesel_run_hours", "h/yr", "computed", 0),
    ("best_diesel_starts", "starts/yr", "computed", 0),
    ("best_no_diesel_hours", "h/yr", "computed", 0),
    ("reserve_units", "units", "check", 0),
    ("reserve_pv_kwp", "kWp", "computed", 0),
    ("reserve_battery_kwh", "kWh", "computed", 0),
    ("reserve_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("reserve_renewable_pct", "%", "computed", 1),
    ("reserve_fuel_l_yr", "L/yr", "computed", 0),
    ("reserve_main_design_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("land_site_ha", "ha", "check", 1),
    ("land_pv_mwdc_per_ha", "MWdc/ha", "check", 2),
    ("land_need_ha", "ha", "computed", 1),
    ("land_max_pv_kwp", "kWp", "computed", 0),
    ("land_fits", "", "computed", 0),
    ("land_pv_kwp", "kWp", "computed", 0),
    ("land_battery_kwh", "kWh", "computed", 0),
    ("land_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("reference_pv_kwp", "kWp", "check", 0),
    ("reference_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("reference_renewable_pct", "%", "computed", 1),
    ("reference_fuel_saved_l_yr", "L/yr", "computed", 0),
    ("alt_diesel_unit_kw", "kW", "check", 0),
    ("alt_diesel_only_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("alt_pv_kwp", "kWp", "computed", 0),
    ("alt_battery_kwh", "kWh", "computed", 0),
    ("alt_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("alt_saving_pct", "%", "computed", 1),
    ("alt_on_grid_edge", "", "computed", 0),
    ("alt_reserve_main_design_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("alt_reserve_pv_kwp", "kWp", "computed", 0),
    ("alt_reserve_battery_kwh", "kWh", "computed", 0),
    ("alt_reserve_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("battery_peak_discharge_kw", "kW", "computed", 0),
    ("battery_peak_charge_kw", "kW", "computed", 0),
    ("battery_peak_use_pct", "%", "computed", 1),
    ("dur_alt_hours", "h", "check", 1),
    ("dur_alt_pv_kwp", "kWp", "computed", 0),
    ("dur_alt_battery_kwh", "kWh", "computed", 0),
    ("dur_alt_battery_kw", "kW", "computed", 0),
    ("dur_alt_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("dur_alt_change_pct", "%", "computed", 1),
    ("dur_alt_on_grid_edge", "", "computed", 0),
    ("capex_break_even_rise_pct", "%", "computed", 1),
    ("capex_break_even_pv_usd_per_kwp", "USD/kWp", "computed", 0),
    ("capex_break_even_battery_usd_per_kwh", "USD/kWh", "computed", 0),
    ("best_unserved_kwh_yr", "kWh/yr", "computed", 0),
    ("best_unserved_hours", "h/yr", "computed", 0),
    ("best_battery_cycles_yr", "cycles/yr", "computed", 0),
    ("engine_hours_diesel_only", "unit h/yr", "computed", 0),
    ("engine_hours_best", "unit h/yr", "computed", 0),
    ("engine_hours_cut_pct", "%", "computed", 1),
    ("sourcing_cost_usd", "USD", "computed", 5),
    ("total_cost_usd", "USD", "computed", 5),
)
ALT_KEYS = (
    "alt_diesel_unit_kw",
    "alt_diesel_only_lcoe_usd_per_kwh",
    "alt_pv_kwp",
    "alt_battery_kwh",
    "alt_lcoe_usd_per_kwh",
    "alt_saving_pct",
    "alt_on_grid_edge",
    "alt_reserve_main_design_lcoe_usd_per_kwh",
    "alt_reserve_pv_kwp",
    "alt_reserve_battery_kwh",
    "alt_reserve_lcoe_usd_per_kwh",
)
DUR_KEYS = (
    "dur_alt_hours",
    "dur_alt_pv_kwp",
    "dur_alt_battery_kwh",
    "dur_alt_battery_kw",
    "dur_alt_lcoe_usd_per_kwh",
    "dur_alt_change_pct",
    "dur_alt_on_grid_edge",
)
MORE_KEYS = (
    "battery_peak_discharge_kw",
    "battery_peak_charge_kw",
    "battery_peak_use_pct",
    "dur_alt_hours",
    "dur_alt_pv_kwp",
    "dur_alt_battery_kwh",
    "dur_alt_battery_kw",
    "dur_alt_lcoe_usd_per_kwh",
    "dur_alt_change_pct",
    "dur_alt_on_grid_edge",
    "capex_break_even_rise_pct",
    "capex_break_even_pv_usd_per_kwp",
    "capex_break_even_battery_usd_per_kwh",
    "best_unserved_kwh_yr",
    "best_unserved_hours",
    "best_battery_cycles_yr",
    "engine_hours_diesel_only",
    "engine_hours_best",
    "engine_hours_cut_pct",
)
FIRM_CHECK_LABEL = {
    "near_tie_pct": "near_tie_frac",
    "reserve_units": "diesel_must_run_units",
    "land_site_ha": "site_land_ha",
    "land_pv_mwdc_per_ha": "pv_mwdc_per_ha",
    "reference_pv_kwp": "reference_pv_kwp",
    "alt_diesel_unit_kw": "diesel_unit_kw_alt",
    "dur_alt_hours": "battery_duration_h_alt",
}
FIRM_TITLES = {
    "near_tie_pct": "Near tie: share above the least LCOE that still counts as a tie",
    "near_tie_count": "Near tie: designs within that share",
    "near_tie_pv_kwp_min": "Near tie: smallest PV size",
    "near_tie_pv_kwp_max": "Near tie: largest PV size",
    "near_tie_battery_kwh_min": "Near tie: smallest battery",
    "near_tie_battery_kwh_max": "Near tie: largest battery",
    "best_diesel_run_hours": "Least cost design: hours the diesel runs",
    "best_diesel_starts": "Least cost design: diesel starts",
    "best_no_diesel_hours": "Least cost design: hours the battery and PV hold the grid with no diesel",
    "reserve_units": "Reserve case: diesel units that run in every hour",
    "reserve_pv_kwp": "Reserve case: least cost PV size",
    "reserve_battery_kwh": "Reserve case: least cost battery",
    "reserve_lcoe_usd_per_kwh": "Reserve case: least cost LCOE",
    "reserve_renewable_pct": "Reserve case: renewable share",
    "reserve_fuel_l_yr": "Reserve case: diesel fuel",
    "reserve_main_design_lcoe_usd_per_kwh": "Reserve case: LCOE of the main design",
    "land_site_ha": "Land: area set aside for the PV plant",
    "land_pv_mwdc_per_ha": "Land: PV per hectare",
    "land_need_ha": "Land: area the main design needs",
    "land_max_pv_kwp": "Land: largest PV that fits",
    "land_fits": "Land: main design fits",
    "land_pv_kwp": "Land: least cost PV size that fits",
    "land_battery_kwh": "Land: battery with that PV",
    "land_lcoe_usd_per_kwh": "Land: LCOE of that design",
    "reference_pv_kwp": "Published design size: PV only",
    "reference_lcoe_usd_per_kwh": "Published design size: LCOE",
    "reference_renewable_pct": "Published design size: renewable share",
    "reference_fuel_saved_l_yr": "Published design size: diesel fuel saved",
    "alt_diesel_unit_kw": "Diesel unit size check: other unit rating in the sources",
    "alt_diesel_only_lcoe_usd_per_kwh": "Diesel unit size check: diesel only LCOE",
    "alt_pv_kwp": "Diesel unit size check: least cost PV size",
    "alt_battery_kwh": "Diesel unit size check: least cost battery",
    "alt_lcoe_usd_per_kwh": "Diesel unit size check: least cost LCOE",
    "alt_saving_pct": "Diesel unit size check: saving against diesel only",
    "alt_on_grid_edge": "Diesel unit size check: least cost design on the grid edge",
    "alt_reserve_main_design_lcoe_usd_per_kwh": "Diesel unit size check: that design with the reserve units always on",
    "alt_reserve_pv_kwp": "Diesel unit size check: reserve case PV size",
    "alt_reserve_battery_kwh": "Diesel unit size check: reserve case battery",
    "alt_reserve_lcoe_usd_per_kwh": "Diesel unit size check: reserve case LCOE",
    "battery_peak_discharge_kw": "Battery power: highest discharge in any hour, main design",
    "battery_peak_charge_kw": "Battery power: highest charge in any hour, main design",
    "battery_peak_use_pct": "Battery power: highest hour as a share of the power rating",
    "dur_alt_hours": "Battery duration check: other duration (battery kWh per kW)",
    "dur_alt_pv_kwp": "Battery duration check: least cost PV size",
    "dur_alt_battery_kwh": "Battery duration check: least cost battery",
    "dur_alt_battery_kw": "Battery duration check: battery power rating",
    "dur_alt_lcoe_usd_per_kwh": "Battery duration check: least cost LCOE",
    "dur_alt_change_pct": "Battery duration check: change against the main least cost LCOE",
    "dur_alt_on_grid_edge": "Battery duration check: least cost design on the grid edge",
    "capex_break_even_rise_pct": "Island prices: rise in PV and battery capital prices before diesel only is cheaper",
    "capex_break_even_pv_usd_per_kwp": "Island prices: PV capital price at that point",
    "capex_break_even_battery_usd_per_kwh": "Island prices: battery energy capital price at that point",
    "best_unserved_kwh_yr": "Least cost design: load not served",
    "best_unserved_hours": "Least cost design: hours with some load not served",
    "best_battery_cycles_yr": "Least cost design: battery discharge in full battery cycles",
    "engine_hours_diesel_only": "Diesel engine hours: diesel only (hours times units running)",
    "engine_hours_best": "Diesel engine hours: least cost design",
    "engine_hours_cut_pct": "Diesel engine hours: cut by the least cost design",
    "sourcing_cost_usd": "Cost of the web search that sourced the inputs",
    "total_cost_usd": "Total model API cost behind this study",
}


def load_checks(path: object) -> tuple[dict, dict]:
    """Read checks file. Returns values by name and the raw parsed file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("checks top level must be a dict")
    if raw.get("schema") != CHECKS_SCHEMA:
        raise ValueError("checks schema must be " + CHECKS_SCHEMA)
    entries = raw.get("values")
    allowed = set(CHECK_NAMES) | set(OPTIONAL_CHECK_NAMES)
    if (
        not isinstance(entries, dict)
        or not set(CHECK_NAMES) <= set(entries)
        or not set(entries) <= allowed
    ):
        raise ValueError("checks values keys must hold every name in " + str(CHECK_NAMES))
    values: dict[str, float | int] = {}
    for name in CHECK_NAMES:
        entry = entries[name]
        if not isinstance(entry, dict) or set(entry) != {"value", "unit", "label", "note"}:
            raise ValueError("entry for " + name + " must hold value, unit, label, note")
        unit = entry["unit"]
        if not isinstance(unit, str) or len(unit) == 0:
            raise ValueError("unit for " + name + " must be a non-empty string")
        if entry["label"] not in LABELS:
            raise ValueError("label for " + name + " must be one of " + str(LABELS))
        if not isinstance(entry["note"], str):
            raise ValueError("note for " + name + " must be a string")
        val = entry["value"]
        if name == "diesel_must_run_units":
            if type(val) is not int or val < 1:
                raise ValueError("value for diesel_must_run_units must be an int of at least 1")
            values[name] = val
        else:
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise ValueError("value for " + name + " must be a finite int or float")
            num = float(val)
            if not math.isfinite(num):
                raise ValueError("value for " + name + " must be finite")
            if not num > 0.0:
                raise ValueError("value for " + name + " must be above 0")
            if name == "near_tie_frac" and num > 0.2:
                raise ValueError("value for near_tie_frac must be at most 0.2")
            values[name] = num
    for name in OPTIONAL_CHECK_NAMES:
        if name not in entries:
            continue
        entry = entries[name]
        if not isinstance(entry, dict) or set(entry) != {"value", "unit", "label", "note"}:
            raise ValueError("entry for " + name + " must hold value, unit, label, note")
        unit = entry["unit"]
        if not isinstance(unit, str) or len(unit) == 0:
            raise ValueError("unit for " + name + " must be a non-empty string")
        if entry["label"] not in LABELS:
            raise ValueError("label for " + name + " must be one of " + str(LABELS))
        if not isinstance(entry["note"], str):
            raise ValueError("note for " + name + " must be a string")
        val = entry["value"]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError("value for " + name + " must be a finite int or float")
        num = float(val)
        if not math.isfinite(num):
            raise ValueError("value for " + name + " must be finite")
        if not num > 0.0:
            raise ValueError("value for " + name + " must be above 0")
        values[name] = num
    return values, raw


def near_tie_band(table: pd.DataFrame, unserved_max_frac: float, tie_frac: float) -> dict:
    """Designs within tie_frac of the least feasible LCOE. Sizes in kWp and kWh, money in USD per kWh."""
    feas = table[table["unserved_frac"] <= float(unserved_max_frac)]
    if len(feas) == 0:
        raise ValueError("no feasible row within unserved_max_frac")
    low = float(feas["lcoe_usd_per_kwh"].min())
    band = feas[feas["lcoe_usd_per_kwh"] <= low * (1.0 + float(tie_frac))]
    return {
        "count": int(len(band)),
        "pv_kwp_min": float(band["pv_kwp"].min()),
        "pv_kwp_max": float(band["pv_kwp"].max()),
        "battery_kwh_min": float(band["battery_kwh"].min()),
        "battery_kwh_max": float(band["battery_kwh"].max()),
        "lcoe_max_usd_per_kwh": float(band["lcoe_usd_per_kwh"].max()),
    }


def land_check(
    table: pd.DataFrame,
    unserved_max_frac: float,
    main_pv_kwp: float,
    land_ha: float,
    pv_mwdc_per_ha: float,
) -> dict:
    """Land need in ha and largest fitting PV in kWp for the main PV size in kWp."""
    need_ha = float(main_pv_kwp) / (1000.0 * float(pv_mwdc_per_ha))
    max_pv_kwp = float(land_ha) * float(pv_mwdc_per_ha) * 1000.0
    fits = bool(float(main_pv_kwp) <= max_pv_kwp * (1.0 + 1e-9))
    within = table[table["pv_kwp"] <= max_pv_kwp * (1.0 + 1e-9)]
    try:
        pick = least_cost(within, unserved_max_frac)
    except ValueError:
        return {
            "need_ha": need_ha,
            "max_pv_kwp": max_pv_kwp,
            "fits": fits,
            "pv_kwp": None,
            "battery_kwh": None,
            "lcoe_usd_per_kwh": None,
        }
    return {
        "need_ha": need_ha,
        "max_pv_kwp": max_pv_kwp,
        "fits": fits,
        "pv_kwp": float(pick["pv_kwp"]),
        "battery_kwh": float(pick["battery_kwh"]),
        "lcoe_usd_per_kwh": float(pick["lcoe_usd_per_kwh"]),
    }


def reserve_case(
    pv_kw_per_kwp: pd.Series,
    load_kw: pd.Series,
    pv_grid: Sequence[float],
    battery_grid: Sequence[float],
    *,
    battery_hours: float,
    battery_template: Battery,
    diesel: DieselFleet,
    must_run_units: int,
    costs: CostInputs,
    co2_kg_per_l: float,
    unserved_max_frac: float,
    main_pv_kwp: float,
    main_battery_kwh: float,
) -> dict:
    """Least cost design with must_run_units diesel units on. Sizes in kWp and kWh, fuel in l."""
    fleet = dataclasses.replace(diesel, must_run_units=must_run_units)
    points = dispatch_grid(
        pv_kw_per_kwp,
        load_kw,
        pv_grid,
        battery_grid,
        battery_hours=battery_hours,
        battery_template=battery_template,
        diesel=fleet,
    )
    table = cost_table(points, costs, co2_kg_per_l)
    main = table[(table["pv_kwp"] == float(main_pv_kwp)) & (table["battery_kwh"] == float(main_battery_kwh))]
    if len(main) == 0:
        raise ValueError("main design pv_kwp and battery_kwh not in the reserve table")
    main_lcoe = float(main.iloc[0]["lcoe_usd_per_kwh"])
    try:
        pick = least_cost(table, unserved_max_frac)
    except ValueError:
        return {
            "units": int(must_run_units),
            "pv_kwp": None,
            "battery_kwh": None,
            "lcoe_usd_per_kwh": None,
            "renewable_pct": None,
            "fuel_l_yr": None,
            "main_design_lcoe_usd_per_kwh": main_lcoe,
            "on_grid_edge": False,
        }
    return {
        "units": int(must_run_units),
        "pv_kwp": float(pick["pv_kwp"]),
        "battery_kwh": float(pick["battery_kwh"]),
        "lcoe_usd_per_kwh": float(pick["lcoe_usd_per_kwh"]),
        "renewable_pct": 100.0 * float(pick["renewable_fraction_frac"]),
        "fuel_l_yr": float(pick["fuel_l_per_yr"]),
        "main_design_lcoe_usd_per_kwh": main_lcoe,
        "on_grid_edge": bool(on_grid_edge(table, pick)),
    }


def diesel_size_case(
    pv_kw_per_kwp: pd.Series,
    load_kw: pd.Series,
    pv_grid: Sequence[float],
    battery_grid: Sequence[float],
    *,
    battery_hours: float,
    battery_template: Battery,
    diesel: DieselFleet,
    unit_kw: float,
    must_run_units: int,
    costs: CostInputs,
    co2_kg_per_l: float,
    unserved_max_frac: float,
) -> dict:
    """Rerun the design search with unit_kw rated diesel units. Sizes in kW, kWp and kWh, money in USD per kWh."""
    if isinstance(unit_kw, bool) or not isinstance(unit_kw, numbers.Real):
        raise ValueError("unit_kw must be a real number above 0: " + repr(unit_kw))
    size_kw = float(unit_kw)
    if not math.isfinite(size_kw) or not size_kw > 0.0:
        raise ValueError("unit_kw must be a real number above 0: " + repr(unit_kw))
    fleet = dataclasses.replace(diesel, unit_kw=size_kw)
    points = dispatch_grid(
        pv_kw_per_kwp,
        load_kw,
        pv_grid,
        battery_grid,
        battery_hours=battery_hours,
        battery_template=battery_template,
        diesel=fleet,
    )
    table = cost_table(points, costs, co2_kg_per_l)
    base = table[(table["pv_kwp"] == 0.0) & (table["battery_kwh"] == 0.0)]
    if len(base) == 0:
        raise ValueError("alt grid holds no diesel only row at pv_kwp 0 and battery_kwh 0")
    diesel_only_lcoe = float(base.iloc[0]["lcoe_usd_per_kwh"])
    try:
        pick = least_cost(table, unserved_max_frac)
    except ValueError:
        return {
            "unit_kw": size_kw,
            "diesel_only_lcoe_usd_per_kwh": diesel_only_lcoe,
            "pv_kwp": None,
            "battery_kwh": None,
            "lcoe_usd_per_kwh": None,
            "saving_pct": None,
            "on_grid_edge": False,
            "reserve_main_design_lcoe_usd_per_kwh": None,
            "reserve_pv_kwp": None,
            "reserve_battery_kwh": None,
            "reserve_lcoe_usd_per_kwh": None,
        }
    reserve = reserve_case(
        pv_kw_per_kwp,
        load_kw,
        pv_grid,
        battery_grid,
        battery_hours=battery_hours,
        battery_template=battery_template,
        diesel=fleet,
        must_run_units=must_run_units,
        costs=costs,
        co2_kg_per_l=co2_kg_per_l,
        unserved_max_frac=unserved_max_frac,
        main_pv_kwp=float(pick["pv_kwp"]),
        main_battery_kwh=float(pick["battery_kwh"]),
    )
    lcoe = float(pick["lcoe_usd_per_kwh"])
    return {
        "unit_kw": size_kw,
        "diesel_only_lcoe_usd_per_kwh": diesel_only_lcoe,
        "pv_kwp": float(pick["pv_kwp"]),
        "battery_kwh": float(pick["battery_kwh"]),
        "lcoe_usd_per_kwh": lcoe,
        "saving_pct": 100.0 * (1.0 - lcoe / diesel_only_lcoe),
        "on_grid_edge": bool(on_grid_edge(table, pick)),
        "reserve_main_design_lcoe_usd_per_kwh": reserve["main_design_lcoe_usd_per_kwh"],
        "reserve_pv_kwp": reserve["pv_kwp"],
        "reserve_battery_kwh": reserve["battery_kwh"],
        "reserve_lcoe_usd_per_kwh": reserve["lcoe_usd_per_kwh"],
    }


def _real_above_zero(name_str: str, value: object) -> float:
    """Finite real number above 0. Raises ValueError naming the field."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(name_str + " must be a real number above 0: " + repr(value))
    out = float(value)  # type: ignore[arg-type]
    if not math.isfinite(out) or not out > 0.0:
        raise ValueError(name_str + " must be a real number above 0: " + repr(value))
    return out


def _real_at_least_zero(name_str: str, value: object) -> float:
    """Finite real number of at least 0. Raises ValueError naming the field."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(name_str + " must be a real number of at least 0: " + repr(value))
    out = float(value)  # type: ignore[arg-type]
    if not math.isfinite(out) or not out >= 0.0:
        raise ValueError(name_str + " must be a real number of at least 0: " + repr(value))
    return out


def battery_power_use(hourly: pd.DataFrame, battery_kw: object) -> dict:
    """Highest charge and discharge in kW and peak share of the rating in pct."""
    if not isinstance(hourly, pd.DataFrame):
        raise ValueError("hourly must be a pandas DataFrame")
    for col in ("battery_discharge_kw", "pv_to_battery_kw", "diesel_to_battery_kw"):
        if col not in hourly.columns:
            raise ValueError("hourly is missing column: " + col)
    if len(hourly) == 0:
        raise ValueError("hourly must hold at least one row")
    rating_kw = _real_at_least_zero("battery_kw", battery_kw)
    dis_kw = float(hourly["battery_discharge_kw"].max())
    chg_kw = float((hourly["pv_to_battery_kw"] + hourly["diesel_to_battery_kw"]).max())
    if rating_kw == 0.0:
        use_pct = None
    else:
        use_pct = 100.0 * max(dis_kw, chg_kw) / rating_kw
    return {"peak_discharge_kw": dis_kw, "peak_charge_kw": chg_kw, "peak_use_pct": use_pct}


def duration_case(
    pv_kw_per_kwp: pd.Series,
    load_kw: pd.Series,
    pv_grid: Sequence[float],
    battery_grid: Sequence[float],
    *,
    battery_hours: float,
    battery_template: Battery,
    diesel: DieselFleet,
    costs: CostInputs,
    co2_kg_per_l: float,
    unserved_max_frac: float,
    main_lcoe_usd_per_kwh: float,
) -> dict:
    """Least cost design for another battery duration. Sizes in kWp and kWh, money in USD per kWh."""
    hours_f = _real_above_zero("battery_hours", battery_hours)
    main_lcoe = _real_above_zero("main_lcoe_usd_per_kwh", main_lcoe_usd_per_kwh)
    points = dispatch_grid(
        pv_kw_per_kwp,
        load_kw,
        pv_grid,
        battery_grid,
        battery_hours=hours_f,
        battery_template=battery_template,
        diesel=diesel,
    )
    table = cost_table(points, costs, co2_kg_per_l)
    try:
        pick = least_cost(table, unserved_max_frac)
    except ValueError:
        return {
            "hours": hours_f,
            "pv_kwp": None,
            "battery_kwh": None,
            "battery_kw": None,
            "lcoe_usd_per_kwh": None,
            "change_pct": None,
            "on_grid_edge": False,
        }
    lcoe = float(pick["lcoe_usd_per_kwh"])
    return {
        "hours": hours_f,
        "pv_kwp": float(pick["pv_kwp"]),
        "battery_kwh": float(pick["battery_kwh"]),
        "battery_kw": float(pick["battery_kw"]),
        "lcoe_usd_per_kwh": lcoe,
        "change_pct": 100.0 * (lcoe / main_lcoe - 1.0),
        "on_grid_edge": bool(on_grid_edge(table, pick)),
    }


def capex_break_even(
    points: object,
    costs: CostInputs,
    co2_kg_per_l: float,
    unserved_max_frac: float,
) -> dict:
    """Capital price scale in frac at which PV stops beating diesel only."""
    if isinstance(unserved_max_frac, bool) or not isinstance(unserved_max_frac, numbers.Real):
        raise ValueError("unserved_max_frac must be a number in [0, 1]: " + repr(unserved_max_frac))
    limit = float(unserved_max_frac)  # type: ignore[arg-type]
    if not math.isfinite(limit) or not 0.0 <= limit <= 1.0:
        raise ValueError("unserved_max_frac must be a number in [0, 1]: " + repr(unserved_max_frac))
    if not isinstance(points, (list, tuple)) or len(points) == 0:
        raise ValueError("points must be a non-empty list of GridPoint")
    for item in points:
        if not isinstance(item, GridPoint):
            raise ValueError("points must hold GridPoint: " + repr(item))
    if not isinstance(costs, CostInputs):
        raise ValueError("costs must be a CostInputs")
    first_d0 = None
    for item in points:
        if float(item.design.pv_kwp) == 0.0 and float(item.design.battery_kwh) == 0.0:
            first_d0 = item
            break
    if first_d0 is None:
        raise ValueError("points hold no diesel only point at pv_kwp 0 and battery_kwh 0")
    table = cost_table(points, costs, co2_kg_per_l)
    bare = dataclasses.replace(
        costs,
        pv_capex_usd_per_kwp=0.0,
        battery_capex_usd_per_kwh=0.0,
        battery_power_capex_usd_per_kw=0.0,
    )
    table0 = cost_table(points, bare, co2_kg_per_l)
    d0_row = table[(table["pv_kwp"] == 0.0) & (table["battery_kwh"] == 0.0)].iloc[0]
    base_lcoe = float(d0_row["lcoe_usd_per_kwh"])
    factor = None
    for (_, row), (_, row0) in zip(table.iterrows(), table0.iterrows()):
        if float(row["pv_kwp"]) == 0.0 and float(row["battery_kwh"]) == 0.0:
            continue
        if not float(row["unserved_frac"]) <= limit:
            continue
        free = float(row0["lcoe_usd_per_kwh"])
        slope = float(row["lcoe_usd_per_kwh"]) - free
        if slope > 0.0:
            cand = (base_lcoe - free) / slope
            if factor is None or cand > factor:
                factor = cand
    if factor is None or not factor > 0.0:
        return {"factor": None, "rise_pct": None, "pv_capex_usd_per_kwp": None,
                "battery_capex_usd_per_kwh": None}
    scale = float(factor)
    return {
        "factor": scale,
        "rise_pct": 100.0 * (scale - 1.0),
        "pv_capex_usd_per_kwp": scale * float(costs.pv_capex_usd_per_kwp),
        "battery_capex_usd_per_kwh": scale * float(costs.battery_capex_usd_per_kwh),
    }


def run_stats(result: DispatchResult, battery_kwh: object) -> dict:
    """Unserved energy in kWh, unserved hours in h and full battery cycles."""
    if not isinstance(result, DispatchResult):
        raise ValueError("result must be a DispatchResult")
    energy_kwh = _real_at_least_zero("battery_kwh", battery_kwh)
    unserved_kwh = float(result.unserved_kwh)
    unserved_hours = int((result.hourly["unserved_kw"] > 0.0).sum())
    if energy_kwh == 0.0:
        cycles = None
    else:
        cycles = float(result.battery_discharge_kwh) / energy_kwh
    return {"unserved_kwh": unserved_kwh, "unserved_hours": unserved_hours, "battery_cycles": cycles}


def engine_hours(diesel_only: DispatchResult, design: DispatchResult) -> dict:
    """Running unit hours in unit h and the cut by the design in pct."""
    if not isinstance(diesel_only, DispatchResult):
        raise ValueError("diesel_only must be a DispatchResult")
    if not isinstance(design, DispatchResult):
        raise ValueError("design must be a DispatchResult")
    d0_hours = float(diesel_only.hourly["diesel_units_on"].sum())
    d1_hours = float(design.hourly["diesel_units_on"].sum())
    if d0_hours == 0.0:
        cut_pct = None
    else:
        cut_pct = 100.0 * (1.0 - d1_hours / d0_hours)
    return {"diesel_only_unit_hours": d0_hours, "design_unit_hours": d1_hours, "cut_pct": cut_pct}


def reference_design(
    pv_kw_per_kwp: pd.Series,
    load_kw: pd.Series,
    pv_kwp: float,
    *,
    battery_hours: float,
    battery_template: Battery,
    diesel: DieselFleet,
    costs: CostInputs,
    co2_kg_per_l: float,
) -> dict:
    """Published PV only design at pv_kwp. Size in kWp, fuel in l, share in pct."""
    if isinstance(pv_kwp, bool) or not isinstance(pv_kwp, numbers.Real):
        raise ValueError("pv_kwp must be a real number above 0: " + repr(pv_kwp))
    size = float(pv_kwp)
    if not math.isfinite(size) or not size > 0.0:
        raise ValueError("pv_kwp must be a real number above 0: " + repr(pv_kwp))
    points = dispatch_grid(
        pv_kw_per_kwp,
        load_kw,
        [0.0, size],
        [0.0],
        battery_hours=battery_hours,
        battery_template=battery_template,
        diesel=diesel,
    )
    table = cost_table(points, costs, co2_kg_per_l)
    base = table.iloc[0]
    des = table.iloc[1]
    return {
        "pv_kwp": size,
        "lcoe_usd_per_kwh": float(des["lcoe_usd_per_kwh"]),
        "renewable_pct": 100.0 * float(des["renewable_fraction_frac"]),
        "fuel_l_yr": float(des["fuel_l_per_yr"]),
        "fuel_saved_l_yr": float(base["fuel_l_per_yr"]) - float(des["fuel_l_per_yr"]),
        "unserved_frac": float(des["unserved_frac"]),
    }


def study_cost(api_cost_usd: float, sourcing_rows: object) -> dict:
    """Sourcing cost in USD and total model API cost in USD."""
    if sourcing_rows is None:
        sourcing = 0.0
    else:
        sourcing = float(sum(float(row.search_cost_usd) for row in sourcing_rows))  # type: ignore[union-attr]
    api = float(api_cost_usd)
    return {"sourcing_cost_usd": sourcing, "total_cost_usd": api + sourcing}
