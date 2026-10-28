"""How firm the least cost answer is. Sizes in kWp and kWh, money in USD, shares in pct."""

from __future__ import annotations

import dataclasses
import json
import math
import numbers
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from autosolar.dispatch import Battery, DieselFleet
from autosolar.econ import CostInputs
from autosolar.sweep import cost_table, dispatch_grid, least_cost, on_grid_edge

CHECKS_SCHEMA = "autosolar.checks/1"
CHECK_NAMES = ("site_land_ha", "pv_mwdc_per_ha", "reference_pv_kwp", "diesel_must_run_units", "near_tie_frac")
OPTIONAL_CHECK_NAMES = ("diesel_unit_kw_alt",)
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
FIRM_CHECK_LABEL = {
    "near_tie_pct": "near_tie_frac",
    "reserve_units": "diesel_must_run_units",
    "land_site_ha": "site_land_ha",
    "land_pv_mwdc_per_ha": "pv_mwdc_per_ha",
    "reference_pv_kwp": "reference_pv_kwp",
    "alt_diesel_unit_kw": "diesel_unit_kw_alt",
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
    if "diesel_unit_kw_alt" in entries:
        entry = entries["diesel_unit_kw_alt"]
        if not isinstance(entry, dict) or set(entry) != {"value", "unit", "label", "note"}:
            raise ValueError("entry for diesel_unit_kw_alt must hold value, unit, label, note")
        unit = entry["unit"]
        if not isinstance(unit, str) or len(unit) == 0:
            raise ValueError("unit for diesel_unit_kw_alt must be a non-empty string")
        if entry["label"] not in LABELS:
            raise ValueError("label for diesel_unit_kw_alt must be one of " + str(LABELS))
        if not isinstance(entry["note"], str):
            raise ValueError("note for diesel_unit_kw_alt must be a string")
        val = entry["value"]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise ValueError("value for diesel_unit_kw_alt must be a finite int or float")
        num = float(val)
        if not math.isfinite(num):
            raise ValueError("value for diesel_unit_kw_alt must be finite")
        if not num > 0.0:
            raise ValueError("value for diesel_unit_kw_alt must be above 0")
        values["diesel_unit_kw_alt"] = num
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
