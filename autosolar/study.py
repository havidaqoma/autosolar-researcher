"""One question in, one checked study out. Lengths in chars, money in USD."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import numbers
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from autosolar.demand import HIRON_2021_SOURCE, build_demand_cases
from autosolar.dispatch import Battery, DieselFleet
from autosolar.econ import CostInputs
from autosolar.firmness import (
    CHECK_NAMES,
    FIRM_CHECK_LABEL,
    FIRM_SPECS,
    FIRM_TITLES,
    OUT_OF_SCOPE,
    land_check,
    load_checks,
    near_tie_band,
    reference_design,
    reserve_case,
    study_cost,
)
from autosolar.pv import PVDesign, simulate_pv
from autosolar.request import Site, StudyRequest, check_request, geocode, parse_question
from autosolar.sourcing import g6_check, read_sourcing
from autosolar.sweep import (
    break_even_fuel_price_usd_per_l,
    cost_table,
    dispatch_grid,
    least_cost,
    on_grid_edge,
    sensitivity_table,
)
from autosolar.weather import CASE_NAMES

REPORT_SCHEMA = "autosolar.report/1"
LABELS = ("measured", "computed", "assumed", "press", "paper", "paper (abstract)", "docs")
KARIMUNJAWA_DEG = (-5.85, 110.43)
DEMAND_RADIUS_KM = 30.0
INPUT_NAMES = (
    "pv_capex_usd_per_kwp",
    "pv_om_usd_per_kwp_yr",
    "pv_life_yr",
    "battery_capex_usd_per_kwh",
    "battery_power_capex_usd_per_kw",
    "battery_om_usd_per_kwh_yr",
    "battery_life_yr",
    "diesel_om_usd_per_kwh",
    "fuel_price_usd_per_l",
    "discount_rate_frac",
    "project_life_yr",
    "currency_year",
    "battery_round_trip_eff_frac",
    "battery_soc_min_frac",
    "battery_soc_initial_frac",
    "battery_duration_h",
    "diesel_unit_kw",
    "diesel_n_units",
    "diesel_min_load_frac",
    "fuel_intercept_l_per_h_per_kw_rated",
    "fuel_slope_l_per_kwh",
    "co2_kg_per_l",
    "unserved_max_frac",
    "rf_target_frac",
    "swing_frac",
    "pv_kwp_step",
    "pv_kwp_max",
    "battery_kwh_step",
    "battery_kwh_max",
)
INT_INPUT_NAMES = ("pv_life_yr", "battery_life_yr", "project_life_yr", "currency_year", "diesel_n_units")
FACT_SPECS = (
    ("site_lat_deg", "deg", "docs", 4),
    ("site_lon_deg", "deg", "docs", 4),
    ("weather_spread_pct", "%", "computed", 1),
    ("demand_kwh_yr", "kWh/yr", "computed", 0),
    ("demand_peak_kw", "kW", "paper", 0),
    ("best_pv_kwp", "kWp", "computed", 0),
    ("best_battery_kwh", "kWh", "computed", 0),
    ("best_battery_kw", "kW", "computed", 0),
    ("best_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("best_npc_usd", "USD", "computed", 0),
    ("best_capex_usd", "USD", "computed", 0),
    ("best_renewable_pct", "%", "computed", 1),
    ("best_curtailed_pct", "%", "computed", 1),
    ("best_fuel_l_yr", "L/yr", "computed", 0),
    ("best_co2_t_yr", "t/yr", "computed", 0),
    ("diesel_only_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("diesel_only_fuel_l_yr", "L/yr", "computed", 0),
    ("diesel_only_co2_t_yr", "t/yr", "computed", 0),
    ("fuel_saved_l_yr", "L/yr", "computed", 0),
    ("co2_saved_t_yr", "t/yr", "computed", 0),
    ("lcoe_change_pct", "%", "computed", 1),
    ("break_even_fuel_usd_per_l", "USD/L", "computed", 2),
    ("api_cost_usd", "USD", "computed", 5),
)
FACT_TITLES = {
    "site_lat_deg": "Site latitude",
    "site_lon_deg": "Site longitude",
    "weather_spread_pct": "Spread of annual sunshine across the weather sources",
    "demand_kwh_yr": "Annual electricity demand",
    "demand_peak_kw": "Peak demand",
    "best_pv_kwp": "Least cost design: PV size",
    "best_battery_kwh": "Least cost design: battery energy",
    "best_battery_kw": "Least cost design: battery power",
    "best_lcoe_usd_per_kwh": "Least cost design: cost of electricity (LCOE)",
    "best_npc_usd": "Least cost design: net present cost",
    "best_capex_usd": "Least cost design: up front capital cost",
    "best_renewable_pct": "Least cost design: renewable share",
    "best_curtailed_pct": "Least cost design: PV energy curtailed",
    "best_fuel_l_yr": "Least cost design: diesel fuel",
    "best_co2_t_yr": "Least cost design: CO2",
    "diesel_only_lcoe_usd_per_kwh": "Diesel only: cost of electricity (LCOE)",
    "diesel_only_fuel_l_yr": "Diesel only: diesel fuel",
    "diesel_only_co2_t_yr": "Diesel only: CO2",
    "fuel_saved_l_yr": "Diesel fuel saved",
    "co2_saved_t_yr": "CO2 saved",
    "lcoe_change_pct": "Change in cost of electricity against diesel only",
    "break_even_fuel_usd_per_l": "Diesel price at which PV starts to pay",
    "api_cost_usd": "Model API cost of this study",
}

_EARTH_RADIUS_KM = 6371.0088
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_])")
_GATE_TOL = 1e-6
_TWIN_TOL_FRAC = 0.001


class UnsupportedSite(ValueError):
    """Site outside the demand source area."""


class GateFailed(RuntimeError):
    """A deterministic physics or economics gate failed."""


class ReportNumberMismatch(RuntimeError):
    """Markdown holds a number missing from the JSON report."""


@dataclass(frozen=True)
class StudyOutput:
    """Finished study. run_hash holds 16 hex chars."""

    run_hash: str
    run_dir: Path
    report: dict
    markdown: str
    reused: bool


def haversine_km(lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float) -> float:
    """Great circle distance in km between two points in deg."""
    lat1_rad = math.radians(float(lat1_deg))
    lon1_rad = math.radians(float(lon1_deg))
    lat2_rad = math.radians(float(lat2_deg))
    lon2_rad = math.radians(float(lon2_deg))
    dlat_rad = lat2_rad - lat1_rad
    dlon_rad = lon2_rad - lon1_rad
    sides = math.sin(dlat_rad / 2.0) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(
        dlon_rad / 2.0
    ) ** 2
    return 2.0 * _EARTH_RADIUS_KM * math.asin(math.sqrt(sides))


def fmt_number(value: object, decimals: object) -> str:
    """Format a finite number with a comma separator. decimals in 0..8."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("value must be a real number: " + repr(value))
    out = float(value)
    if not math.isfinite(out):
        raise ValueError("value must be finite: " + repr(value))
    if type(decimals) is not int or not 0 <= decimals <= 8:
        raise ValueError("decimals must be an int in 0..8: " + repr(decimals))
    text = f"{out:,.{decimals}f}"
    if text.startswith("-") and float(text.replace(",", "")) == 0.0:
        text = text[1:]
    return text


def number_tokens(text: str) -> list[str]:
    """Number tokens in text order. No match inside words or hex."""
    return _NUMBER_RE.findall(text)


def _collect_tokens(obj: object, found: set[str]) -> None:
    """Add number tokens of every string inside obj to found."""
    if isinstance(obj, str):
        found.update(number_tokens(obj))
    elif isinstance(obj, dict):
        for item in obj.values():
            _collect_tokens(item, found)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_tokens(item, found)


def scan_report_numbers(md_text: str, report: dict) -> list[str]:
    """Sorted unique markdown tokens missing from report strings."""
    reported: set[str] = set()
    _collect_tokens(report, reported)
    return sorted(set(number_tokens(md_text)) - reported)


def _entry_value(name_str: str, entry: object) -> float | int:
    """Checked numeric value from one inputs entry."""
    if not isinstance(entry, dict) or set(entry) != {"value", "unit", "label", "note"}:
        raise ValueError("entry for " + name_str + " must hold value, unit, label, note")
    unit = entry["unit"]
    if not isinstance(unit, str) or len(unit) == 0:
        raise ValueError("unit for " + name_str + " must be a non-empty string")
    if entry["label"] not in LABELS:
        raise ValueError("label for " + name_str + " must be one of " + str(LABELS))
    if not isinstance(entry["note"], str):
        raise ValueError("note for " + name_str + " must be a string")
    val = entry["value"]
    if name_str in INT_INPUT_NAMES:
        if type(val) is not int:
            raise ValueError("value for " + name_str + " must be an int")
        return val
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise ValueError("value for " + name_str + " must be a finite int or float")
    if not math.isfinite(float(val)):
        raise ValueError("value for " + name_str + " must be finite")
    return val


def load_inputs(path: object) -> tuple[dict, dict]:
    """Read inputs file. Returns values by name and the raw parsed file."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("inputs top level must be a dict")
    if raw.get("schema") != "autosolar.inputs/1":
        raise ValueError("inputs schema must be autosolar.inputs/1")
    entries = raw.get("values")
    if not isinstance(entries, dict) or set(entries) != set(INPUT_NAMES):
        raise ValueError("inputs values keys must be exactly INPUT_NAMES")
    values: dict[str, float | int] = {}
    for name in INPUT_NAMES:
        values[name] = _entry_value(name, entries[name])
    if not values["pv_kwp_step"] > 0:
        raise ValueError("pv_kwp_step must be above 0")
    if not values["battery_kwh_step"] > 0:
        raise ValueError("battery_kwh_step must be above 0")
    for max_key, step_key in (("pv_kwp_max", "pv_kwp_step"), ("battery_kwh_max", "battery_kwh_step")):
        top = float(values[max_key])
        step = float(values[step_key])
        if top < step:
            raise ValueError(max_key + " must not be smaller than " + step_key)
        quotient = top / step
        if abs(quotient - round(quotient)) > 1e-9:
            raise ValueError(max_key + " must be a whole multiple of " + step_key)
    return values, raw


def _clean(text: object) -> str:
    """ASCII text for markdown. Drops non-ASCII, swaps pipe for slash."""
    out = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    return out.replace("|", "/")


def _row_line(cells: list[str]) -> str:
    """One markdown table row from cell strings."""
    return "| " + " | ".join(_clean(cell) for cell in cells) + " |"


def firm_items(values: dict, checks_raw: dict) -> list[dict]:
    """One markdown item per FIRM_SPECS row. Values in firmness units, text formatted."""
    items: list[dict] = []
    check_entries = checks_raw["values"]
    for key, unit, label, decimals in FIRM_SPECS:
        if label == "check":
            shown = check_entries[FIRM_CHECK_LABEL[key]]["label"]
        else:
            shown = label
        val = values[key]
        if key == "land_fits":
            items.append({
                "key": key,
                "title": FIRM_TITLES[key],
                "value": bool(val),
                "unit": unit,
                "label": shown,
                "text": "yes" if val else "no",
            })
        elif val is None:
            items.append({
                "key": key,
                "title": FIRM_TITLES[key],
                "value": None,
                "unit": unit,
                "label": shown,
                "text": "none",
            })
        else:
            num = float(val)
            items.append({
                "key": key,
                "title": FIRM_TITLES[key],
                "value": num,
                "unit": unit,
                "label": shown,
                "text": fmt_number(num, decimals),
            })
    return items


def render_markdown(report: dict) -> str:
    """Markdown study report. Ends with one newline."""
    facts = report["facts"]
    firm = report.get("firmness")
    lines = ["# AutoSolar pre-feasibility study: " + _clean(report["site"]["name"]), ""]
    lines += ["Question: " + _clean(report["question"]), ""]
    lines += [
        "Run "
        + _clean(report["run_hash"])
        + ". Labels: measured (service data saved with the run), "
        + "computed (this run), paper, docs, assumed.",
        "",
    ]
    lines += ["## Answer", ""]
    for key, unit, label, _dec in FACT_SPECS:
        fact = facts[key]
        lines.append(
            "- "
            + _clean(FACT_TITLES[key])
            + ": "
            + _clean(fact["text"])
            + " "
            + _clean(fact["unit"])
            + " ("
            + _clean(fact["label"])
            + ")"
        )
    if firm is not None:
        lines += ["", "## How firm is the answer", ""]
        for item in firm["items"]:
            if item["unit"] == "":
                lines.append(
                    "- "
                    + _clean(item["title"])
                    + ": "
                    + _clean(item["text"])
                    + " ("
                    + _clean(item["label"])
                    + ")"
                )
            else:
                lines.append(
                    "- "
                    + _clean(item["title"])
                    + ": "
                    + _clean(item["text"])
                    + " "
                    + _clean(item["unit"])
                    + " ("
                    + _clean(item["label"])
                    + ")"
                )
    lines += ["", "## Weather sources", ""]
    lines.append(
        "| Case | Year | GHI kWh/m2/yr (measured) | Yield kWh/kWp/yr (computed) | PR (computed) | G3 passed |"
    )
    lines.append("|---|---|---|---|---|---|")
    for row in report["weather_table"]:
        lines.append(_row_line(row["cells"]))
    lines += ["", "## Range of the answer", ""]
    lines.append(
        "| Weather | Demand | PV kWp | Battery kWh | LCOE USD/kWh | LCOE of the main design USD/kWh | Note |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for row in report["range_table"]:
        lines.append(_row_line(row["cells"]))
    lines += ["", "## Sensitivity", ""]
    lines.append(
        "| Input | Factor | LCOE of the main design USD/kWh | Least cost PV kWp | Least cost battery kWh | "
        "Least cost LCOE USD/kWh | Same design | Note |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in report["sensitivity_table"]:
        lines.append(_row_line(row["cells"]))
    lines += ["", "## Checks", ""]
    lines.append("| Gate | Scope | Passed | Detail |")
    lines.append("|---|---|---|---|")
    for row in report["gates"]:
        lines.append(_row_line(row["cells"]))
    lines += ["", "## Inputs", ""]
    lines.append("| Name | Value | Unit | Label | Note |")
    lines.append("|---|---|---|---|---|")
    for row in report["inputs_table"]:
        lines.append(_row_line(row["cells"]))
    sourcing = report.get("sourcing")
    if sourcing is not None:
        s_rows = sourcing["rows"]
        s_meta = sourcing["meta"] if isinstance(sourcing.get("meta"), dict) else {}
        count_c = sum(1 for x in s_rows if x["status"] == "checked")
        count_n = len(s_rows)
        judge = s_meta.get("judge")
        judge = judge if isinstance(judge, str) else "not named"
        lines += ["", "## Sourced inputs", ""]
        lines.append(
            str(count_c)
            + " of "
            + str(count_n)
            + " inputs were sourced by web search and checked: the quote was found in the fetched source, the "
            + "value appears in the quote, the DOI resolves when one is given, and the support judge ("
            + _clean(judge)
            + ") agreed. The others keep their assumed value; the last column says why."
        )
        lines.append("")
        lines.append(
            "| Input | Status | Value used | Unit | Label | As written | Source | URL | Page | Quote match | Why kept "
            "assumed |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for row in s_rows:
            lines.append(_row_line(row["cells"]))
    if firm is not None:
        lines += ["", "## Not covered by this study", ""]
        for line in firm["out_of_scope"]:
            lines.append("- " + _clean(line))
    lines += ["", "## Sources", ""]
    for source in report["sources"]:
        lines.append("- " + _clean(source))
    return "\n".join(lines) + "\n"


def _read_cached_request(req_file: Path) -> tuple[StudyRequest, Site]:
    """Study request and site rebuilt from a cached JSON file."""
    data = json.loads(req_file.read_text(encoding="utf-8"))
    req = StudyRequest(**data["request"])
    site = Site(**data["site"])
    check_request(req)
    return req, site


def _write_cached_request(req_file: Path, req: StudyRequest, site: Site) -> None:
    """Save request and site JSON for reuse. Creates folders as needed."""
    req_file.parent.mkdir(parents=True, exist_ok=True)
    blob = json.dumps(
        {"request": dataclasses.asdict(req), "site": dataclasses.asdict(site)},
        ensure_ascii=True,
        allow_nan=False,
    )
    req_file.write_text(blob, encoding="utf-8")


def _run_hash(
    lat_w: float, lon_w: float, raw: dict, sourcing_rows: object = None, checks: object = None
) -> str:
    """16 hex chars marking one inputs and weather point choice."""
    payload: dict = {"schema": REPORT_SCHEMA, "weather_coords_deg": [lat_w, lon_w], "inputs": raw}
    if sourcing_rows is not None:
        payload["sourcing"] = [dataclasses.asdict(r) for r in sourcing_rows]  # type: ignore[union-attr]
    if checks is not None:
        payload["checks"] = checks
    blob = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(blob).hexdigest()[:16]


def _g3_passed(pv_result: object) -> bool:
    """True when specific yield in kWh per kWp and PR frac pass G3."""
    spec_yield = float(pv_result.specific_yield_kwh_kwp)
    perf = pv_result.performance_ratio_frac
    if not 1100.0 <= spec_yield <= 1800.0:
        return False
    if perf is None:
        return False
    return bool(0.65 <= float(perf) <= 0.90)


def _design_objects(values: dict) -> tuple[CostInputs, Battery, DieselFleet, float]:
    """Cost, battery template and diesel objects from input values."""
    field_names = {item.name for item in dataclasses.fields(CostInputs)}
    costs = CostInputs(**{name: values[name] for name in field_names})
    battery = Battery(
        energy_kwh=1.0,
        power_kw=1.0,
        round_trip_eff_frac=float(values["battery_round_trip_eff_frac"]),
        soc_min_frac=float(values["battery_soc_min_frac"]),
        soc_initial_frac=float(values["battery_soc_initial_frac"]),
    )
    diesel = DieselFleet(
        unit_kw=float(values["diesel_unit_kw"]),
        n_units=int(values["diesel_n_units"]),
        min_load_frac=float(values["diesel_min_load_frac"]),
        fuel_intercept_l_per_h_per_kw_rated=float(values["fuel_intercept_l_per_h_per_kw_rated"]),
        fuel_slope_l_per_kwh=float(values["fuel_slope_l_per_kwh"]),
    )
    return costs, battery, diesel, float(values["battery_duration_h"])


def _size_grid(step: float, top: float) -> list[float]:
    """Grid from 0 to top in kWp, kWh or kW steps."""
    count = round(float(top) / float(step))
    return [float(idx * float(step)) for idx in range(count + 1)]


def _widen_grid(grid: list[float], step: float) -> list[float]:
    """Grid stretched by 1.5 times, snapped up to a whole step in kWp or kWh."""
    top = max(grid)
    grown = math.ceil(top * 1.5 / step - 1e-9) * step
    return _size_grid(step, grown)


def _opt(value: object, decimals: int) -> str:
    """Formatted number or none for markdown cells and facts text."""
    if value is None:
        return "none"
    if isinstance(value, float) and math.isnan(value):
        return "none"
    return fmt_number(float(value), decimals)


def _range_row(
    weather_name: str,
    demand_name: str,
    pv_kw_per_kwp: object,
    load_kw: object,
    pv_grid: list[float],
    battery_grid: list[float],
    battery_hours: float,
    battery: Battery,
    diesel: DieselFleet,
    costs: CostInputs,
    co2_kg_per_l: float,
    unserved_max_frac: float,
    best_pv_kwp: float,
    best_battery_kwh: float,
) -> dict:
    """One range table row in kWp, kWh and USD per kWh."""
    points = dispatch_grid(
        pv_kw_per_kwp,
        load_kw,
        pv_grid,
        battery_grid,
        battery_hours=battery_hours,
        battery_template=battery,
        diesel=diesel,
    )
    table = cost_table(points, costs, co2_kg_per_l)
    base = table[(table["pv_kwp"] == best_pv_kwp) & (table["battery_kwh"] == best_battery_kwh)]
    base_lcoe = float(base.iloc[0]["lcoe_usd_per_kwh"])
    note = ""
    try:
        own = least_cost(table, unserved_max_frac)
    except ValueError:
        own_pv: float | None = None
        own_batt: float | None = None
        own_lcoe: float | None = None
        note = "no feasible design"
    else:
        own_pv = float(own["pv_kwp"])
        own_batt = float(own["battery_kwh"])
        own_lcoe = float(own["lcoe_usd_per_kwh"])
        if note == "" and (own_pv == max(pv_grid) or own_batt == max(battery_grid)):
            note = "on grid edge"
    return {
        "weather": weather_name,
        "demand": demand_name,
        "pv_kwp": own_pv,
        "battery_kwh": own_batt,
        "lcoe_usd_per_kwh": own_lcoe,
        "base_design_lcoe_usd_per_kwh": base_lcoe,
        "note": note,
        "cells": [
            weather_name,
            demand_name,
            _opt(own_pv, 0),
            _opt(own_batt, 0),
            _opt(own_lcoe, 3),
            _opt(base_lcoe, 3),
            note,
        ],
    }


def _gate(gate: str, scope: str, passed: bool, detail: str) -> dict:
    """One gate row with its markdown cells."""
    return {
        "gate": gate,
        "scope": scope,
        "passed": bool(passed),
        "detail": str(detail),
        "cells": [gate, scope, "yes" if passed else "no", str(detail)],
    }


def _check_g1(hourly: object) -> tuple[bool, str]:
    """PV, load and diesel hourly balances in kW within 1e-6 kW."""
    pv_gap = float((hourly["pv_kw"] - hourly["pv_to_load_kw"] - hourly["pv_to_battery_kw"]
                    - hourly["pv_curtailed_kw"]).abs().max())
    load_gap = float((hourly["load_kw"] - hourly["pv_to_load_kw"] - hourly["battery_discharge_kw"]
                      - hourly["diesel_to_load_kw"] - hourly["unserved_kw"]).abs().max())
    diesel_gap = float((hourly["diesel_kw"] - hourly["diesel_to_load_kw"]
                        - hourly["diesel_to_battery_kw"] - hourly["diesel_excess_kw"]).abs().max())
    worst = max(pv_gap, load_gap, diesel_gap)
    return worst <= _GATE_TOL, "max hourly gap kW: pv %g, load %g, diesel %g" % (pv_gap, load_gap, diesel_gap)


def _check_g2(hourly: object, result: object, battery_kwh: float, values: dict) -> tuple[bool, str]:
    """Battery SOC band in kWh and charge energy balance in kWh."""
    energy_kwh = float(battery_kwh)
    floor_kwh = float(values["battery_soc_min_frac"]) * energy_kwh - _GATE_TOL
    ceil_kwh = energy_kwh + _GATE_TOL
    in_band = bool(((hourly["soc_kwh"] >= floor_kwh) & (hourly["soc_kwh"] <= ceil_kwh)).all())
    rte_frac = float(values["battery_round_trip_eff_frac"])
    stored_kwh = (result.battery_charge_kwh * rte_frac
                  + (result.soc_start_kwh - result.soc_end_kwh) * math.sqrt(rte_frac))
    balanced = bool(result.battery_discharge_kwh <= stored_kwh + _GATE_TOL)
    detail = "soc band kWh [%s, %s], discharge kWh %s against stored kWh %s" % (
        fmt_number(floor_kwh, 0),
        fmt_number(ceil_kwh, 0),
        fmt_number(float(result.battery_discharge_kwh), 0),
        fmt_number(float(stored_kwh), 0),
    )
    return bool(in_band and balanced), detail


def _check_g4(hourly: object, diesel: DieselFleet) -> tuple[bool, str]:
    """Diesel minimum load in kW on every hour with units on."""
    running = hourly[hourly["diesel_units_on"] > 0]
    if len(running) == 0:
        return True, "diesel never runs"
    need_kw = running["diesel_units_on"] * float(diesel.unit_kw) * float(diesel.min_load_frac)
    ok = bool((running["diesel_kw"] >= need_kw - _GATE_TOL).all())
    worst_kw = float((running["diesel_kw"] - need_kw).min())
    return ok, "worst margin kW above min load: " + fmt_number(worst_kw, 1)


def _check_g8(table: object) -> tuple[bool, str]:
    """Twin LCOE gap frac over the main table within 0.001."""
    worst = 0.0
    for path_a, path_b in zip(table["lcoe_path_a_usd_per_kwh"], table["lcoe_usd_per_kwh"]):
        path_a_f = float(path_a)
        path_b_f = float(path_b)
        if path_b_f == 0.0:
            gap = 0.0 if path_a_f == 0.0 else math.inf
        else:
            gap = abs(path_a_f - path_b_f) / path_b_f
        worst = max(worst, gap)
    return worst <= _TWIN_TOL_FRAC, "max twin gap frac: %.1e" % (worst,)


def run_study(
    question: object,
    *,
    client: object,
    http_get: object,
    weather_fn: object,
    inputs_path: object,
    runs_dir: object,
    run_id: object,
    sourcing_path: object = None,
    checks_path: object = None,
) -> StudyOutput:
    """One checked study in a run folder. Returns run hash, dir, report and markdown."""
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 2000:
        raise ValueError("question must hold 1 to 2000 characters after strip")
    asked = question.strip()
    values, raw = load_inputs(inputs_path)
    checks_values: dict | None = None
    checks_raw: dict | None = None
    if checks_path is not None:
        checks_values, checks_raw = load_checks(checks_path)
    s_rows: list | None = None
    s_meta: dict | None = None
    if sourcing_path is not None:
        s_raw, s_rows, s_meta = read_sourcing(sourcing_path)
        if s_raw != raw:
            raise ValueError("inputs file does not match the sourcing file")
    runs_path = Path(runs_dir)
    req_name = hashlib.sha256(asked.encode("utf-8")).hexdigest()[:16] + ".json"
    req_file = runs_path / "requests" / req_name
    if req_file.is_file():
        req, site = _read_cached_request(req_file)
    else:
        req = parse_question(question, client, run_id)
        check_request(req)
        site = geocode(req.site_name, http_get)
        _write_cached_request(req_file, req, site)
    if haversine_km(site.lat_deg, site.lon_deg, *KARIMUNJAWA_DEG) > DEMAND_RADIUS_KM:
        raise UnsupportedSite("site outside the Karimunjawa demand source area")
    lat_w = round(float(site.lat_deg), 2)
    lon_w = round(float(site.lon_deg), 2)
    run_hash = _run_hash(lat_w, lon_w, raw, s_rows, checks_raw)
    run_dir = runs_path / run_hash
    done_json = run_dir / "report.json"
    done_md = run_dir / "report.md"
    if done_json.is_file():
        report = json.loads(done_json.read_text(encoding="ascii"))
        markdown = done_md.read_text(encoding="ascii")
        return StudyOutput(run_hash, run_dir, report, markdown, True)
    weather = weather_fn(lat_w, lon_w)
    pv_by_case: dict[str, object] = {}
    g3_ok: dict[str, bool] = {}
    for name in CASE_NAMES:
        if name not in weather.cases:
            continue
        pv = simulate_pv(weather.cases[name], lat_w, lon_w, PVDesign(), 1.0)
        pv_by_case[name] = pv
        g3_ok[name] = _g3_passed(pv)
    basis = str(weather.basis)
    if basis not in pv_by_case or not g3_ok[basis]:
        raise GateFailed("G3 PV physics failed on the basis case " + basis)
    costs, battery, diesel, battery_hours = _design_objects(values)
    co2_kg_per_l = float(values["co2_kg_per_l"])
    unserved_max_frac = float(values["unserved_max_frac"])
    basis_cases = build_demand_cases(weather.cases[basis].index)
    basis_kw = pv_by_case[basis].hourly["ac_kw"]
    paper_load = basis_cases["paper"].load_kw
    pv_step = float(values["pv_kwp_step"])
    pv_top = float(values["pv_kwp_max"])
    batt_step = float(values["battery_kwh_step"])
    batt_top = float(values["battery_kwh_max"])
    pv_grid = _size_grid(pv_step, pv_top)
    battery_grid = _size_grid(batt_step, batt_top)
    points = dispatch_grid(
        basis_kw, paper_load, pv_grid, battery_grid,
        battery_hours=battery_hours, battery_template=battery, diesel=diesel,
    )
    table = cost_table(points, costs, co2_kg_per_l)
    best = least_cost(table, unserved_max_frac)
    widened = 0
    while on_grid_edge(table, best) and widened < 2:
        if float(best["pv_kwp"]) == float(max(pv_grid)):
            pv_grid = _widen_grid(pv_grid, pv_step)
        if float(best["battery_kwh"]) == float(max(battery_grid)):
            battery_grid = _widen_grid(battery_grid, batt_step)
        points = dispatch_grid(
            basis_kw, paper_load, pv_grid, battery_grid,
            battery_hours=battery_hours, battery_template=battery, diesel=diesel,
        )
        table = cost_table(points, costs, co2_kg_per_l)
        best = least_cost(table, unserved_max_frac)
        widened += 1
    best_pv_kwp = float(best["pv_kwp"])
    best_battery_kwh = float(best["battery_kwh"])
    break_even = break_even_fuel_price_usd_per_l(points, costs, co2_kg_per_l, unserved_max_frac)
    sens = sensitivity_table(
        basis_kw, paper_load, pv_grid, battery_grid,
        battery_hours=battery_hours, battery_template=battery, diesel=diesel,
        costs=costs, co2_kg_per_l=co2_kg_per_l, unserved_max_frac=unserved_max_frac,
        swing_frac=float(values["swing_frac"]),
    )
    range_rows = [
        _range_row(
            basis, "paper", basis_kw, paper_load, pv_grid, battery_grid,
            battery_hours, battery, diesel, costs, co2_kg_per_l, unserved_max_frac,
            best_pv_kwp, best_battery_kwh,
        )
    ]
    for name in CASE_NAMES:
        if name == basis or name not in pv_by_case or not g3_ok[name]:
            continue
        case_load = build_demand_cases(weather.cases[name].index)["paper"].load_kw
        range_rows.append(
            _range_row(
                name, "paper", pv_by_case[name].hourly["ac_kw"], case_load, pv_grid, battery_grid,
                battery_hours, battery, diesel, costs, co2_kg_per_l, unserved_max_frac,
                best_pv_kwp, best_battery_kwh,
            )
        )
    for demand_name in ("tourist season", "growth"):
        range_rows.append(
            _range_row(
                basis, demand_name, basis_kw, basis_cases[demand_name].load_kw, pv_grid,
                battery_grid, battery_hours, battery, diesel, costs, co2_kg_per_l,
                unserved_max_frac, best_pv_kwp, best_battery_kwh,
            )
        )
    best_result = points[int(best.name)].result
    best_hourly = best_result.hourly
    gates = []
    for name in CASE_NAMES:
        if name in pv_by_case:
            pv = pv_by_case[name]
            yld = float(pv.specific_yield_kwh_kwp)
            prf = pv.performance_ratio_frac
            detail = "yield kWh/kWp " + fmt_number(yld, 0) + ", PR " + (
                "none" if prf is None else fmt_number(float(prf), 2))
            gates.append(_gate("G3 PV physics", name, bool(g3_ok[name]), detail))
        else:
            gates.append(_gate("G3 PV physics", name, False, "no data for case"))
    g1_ok, g1_detail = _check_g1(best_hourly)
    gates.append(_gate("G1 energy balance", "main design", g1_ok, g1_detail))
    g2_ok, g2_detail = _check_g2(best_hourly, best_result, best_battery_kwh, values)
    gates.append(_gate("G2 battery", "main design", g2_ok, g2_detail))
    g4_ok, g4_detail = _check_g4(best_hourly, diesel)
    gates.append(_gate("G4 diesel", "main design", g4_ok, g4_detail))
    weather_names = {row["weather"] for row in range_rows}
    g5_ok = bool(not weather.range_required or len(weather_names) >= 2)
    gates.append(_gate(
        "G5 weather spread", "weather", g5_ok,
        "range required: %s, weather rows in range: %d" % (weather.range_required, len(weather_names)),
    ))
    if s_rows is not None:
        g6_ok, g6_detail = g6_check(s_rows, raw)
        gates.append(_gate("G6 sourced inputs", "inputs", g6_ok, g6_detail))
        if not g6_ok:
            raise GateFailed("gate failed: G6 sourced inputs: " + g6_detail)
    g7_ok = not on_grid_edge(table, best)
    gates.append(_gate("G7 grid edge", "main design", g7_ok, "grid widened %d times" % (widened,)))
    g8_ok, g8_detail = _check_g8(table)
    gates.append(_gate("G8 LCOE twins", "main design", g8_ok, g8_detail))
    for gate_row, hard in zip(gates[4:7], (g1_ok, g2_ok, g4_ok)):
        if not hard:
            raise GateFailed("gate failed: " + gate_row["gate"] + ": " + gate_row["detail"])
    if not g8_ok:
        raise GateFailed("gate failed: G8 LCOE twins: " + g8_detail)
    diesel_only = table[(table["pv_kwp"] == 0.0) & (table["battery_kwh"] == 0.0)].iloc[0]
    diesel_lcoe = float(diesel_only["lcoe_usd_per_kwh"])
    diesel_fuel = float(diesel_only["fuel_l_per_yr"])
    diesel_co2 = float(diesel_only["co2_t_per_yr"])
    best_lcoe = float(best["lcoe_usd_per_kwh"])
    best_fuel = float(best["fuel_l_per_yr"])
    best_co2 = float(best["co2_t_per_yr"])
    paper_case = basis_cases["paper"]
    fact_values: dict[str, float | None] = {
        "site_lat_deg": float(site.lat_deg),
        "site_lon_deg": float(site.lon_deg),
        "weather_spread_pct": float(weather.spread_pct_all),
        "demand_kwh_yr": float(paper_case.annual_kwh),
        "demand_peak_kw": float(paper_case.peak_kw),
        "best_pv_kwp": best_pv_kwp,
        "best_battery_kwh": best_battery_kwh,
        "best_battery_kw": float(best["battery_kw"]),
        "best_lcoe_usd_per_kwh": best_lcoe,
        "best_npc_usd": float(best["npc_usd"]),
        "best_capex_usd": float(best["capex_initial_usd"]),
        "best_renewable_pct": 100.0 * float(best["renewable_fraction_frac"]),
        "best_curtailed_pct": 100.0 * float(best["pv_curtailed_frac"]),
        "best_fuel_l_yr": best_fuel,
        "best_co2_t_yr": best_co2,
        "diesel_only_lcoe_usd_per_kwh": diesel_lcoe,
        "diesel_only_fuel_l_yr": diesel_fuel,
        "diesel_only_co2_t_yr": diesel_co2,
        "fuel_saved_l_yr": diesel_fuel - best_fuel,
        "co2_saved_t_yr": diesel_co2 - best_co2,
        "lcoe_change_pct": 100.0 * (best_lcoe / diesel_lcoe - 1.0),
        "break_even_fuel_usd_per_l": None if math.isinf(break_even) else float(break_even),
        "api_cost_usd": float(req.cost_usd),
    }
    facts = {}
    for key, unit, label, decimals in FACT_SPECS:
        val = fact_values[key]
        if val is None:
            facts[key] = {"value": None, "unit": unit, "label": label, "text": "not reached in grid"}
        else:
            num = float(val)
            facts[key] = {"value": num, "unit": unit, "label": label, "text": fmt_number(num, decimals)}
    firmness: dict | None = None
    if checks_raw is not None and checks_values is not None:
        tie_frac = float(checks_values["near_tie_frac"])
        site_ha = float(checks_values["site_land_ha"])
        density_mwdc_per_ha = float(checks_values["pv_mwdc_per_ha"])
        ref_pv_kwp = float(checks_values["reference_pv_kwp"])
        must_run_units = int(checks_values["diesel_must_run_units"])
        band = near_tie_band(table, unserved_max_frac, tie_frac)
        land = land_check(table, unserved_max_frac, best_pv_kwp, site_ha, density_mwdc_per_ha)
        reserve = reserve_case(
            basis_kw,
            paper_load,
            pv_grid,
            battery_grid,
            battery_hours=battery_hours,
            battery_template=battery,
            diesel=diesel,
            must_run_units=must_run_units,
            costs=costs,
            co2_kg_per_l=co2_kg_per_l,
            unserved_max_frac=unserved_max_frac,
            main_pv_kwp=best_pv_kwp,
            main_battery_kwh=best_battery_kwh,
        )
        ref_design = reference_design(
            basis_kw,
            paper_load,
            ref_pv_kwp,
            battery_hours=battery_hours,
            battery_template=battery,
            diesel=diesel,
            costs=costs,
            co2_kg_per_l=co2_kg_per_l,
        )
        firm_cost = study_cost(float(req.cost_usd), s_rows)
        diesel_run_hours = int(best["diesel_run_hours"])
        diesel_starts = int(best["diesel_starts"])
        firm_values: dict[str, object] = {
            "near_tie_pct": 100.0 * tie_frac,
            "near_tie_count": band["count"],
            "near_tie_pv_kwp_min": band["pv_kwp_min"],
            "near_tie_pv_kwp_max": band["pv_kwp_max"],
            "near_tie_battery_kwh_min": band["battery_kwh_min"],
            "near_tie_battery_kwh_max": band["battery_kwh_max"],
            "best_diesel_run_hours": diesel_run_hours,
            "best_diesel_starts": diesel_starts,
            "best_no_diesel_hours": len(best_result.hourly) - diesel_run_hours,
            "reserve_units": must_run_units,
            "reserve_pv_kwp": reserve["pv_kwp"],
            "reserve_battery_kwh": reserve["battery_kwh"],
            "reserve_lcoe_usd_per_kwh": reserve["lcoe_usd_per_kwh"],
            "reserve_renewable_pct": reserve["renewable_pct"],
            "reserve_fuel_l_yr": reserve["fuel_l_yr"],
            "reserve_main_design_lcoe_usd_per_kwh": reserve["main_design_lcoe_usd_per_kwh"],
            "land_site_ha": site_ha,
            "land_pv_mwdc_per_ha": density_mwdc_per_ha,
            "land_need_ha": land["need_ha"],
            "land_max_pv_kwp": land["max_pv_kwp"],
            "land_fits": land["fits"],
            "land_pv_kwp": land["pv_kwp"],
            "land_battery_kwh": land["battery_kwh"],
            "land_lcoe_usd_per_kwh": land["lcoe_usd_per_kwh"],
            "reference_pv_kwp": ref_pv_kwp,
            "reference_lcoe_usd_per_kwh": ref_design["lcoe_usd_per_kwh"],
            "reference_renewable_pct": ref_design["renewable_pct"],
            "reference_fuel_saved_l_yr": ref_design["fuel_saved_l_yr"],
            "sourcing_cost_usd": firm_cost["sourcing_cost_usd"],
            "total_cost_usd": firm_cost["total_cost_usd"],
        }
        firmness = {
            "items": firm_items(firm_values, checks_raw),
            "out_of_scope": list(OUT_OF_SCOPE),
            "checks": checks_raw,
        }
    weather_rows = []
    for name in CASE_NAMES:
        if name not in pv_by_case:
            continue
        pv = pv_by_case[name]
        year = weather.years.get(name)
        ghi = float(weather.annual_ghi_kwh_m2[name])
        spec_yield = float(pv.specific_yield_kwh_kwp)
        perf = pv.performance_ratio_frac
        perf_f = None if perf is None else float(perf)
        weather_rows.append({
            "case": name,
            "year": year,
            "ghi_kwh_m2_yr": ghi,
            "yield_kwh_kwp_yr": spec_yield,
            "performance_ratio_frac": perf_f,
            "g3_passed": bool(g3_ok[name]),
            "cells": [
                name,
                "none" if year is None else str(year),
                fmt_number(ghi, 0),
                fmt_number(spec_yield, 0),
                "none" if perf_f is None else fmt_number(perf_f, 2),
                "yes" if g3_ok[name] else "no",
            ],
        })
    sens_rows = []
    for _, srow in sens.iterrows():
        least_pv = float(srow["least_cost_pv_kwp"])
        least_batt = float(srow["least_cost_battery_kwh"])
        least_lcoe = float(srow["least_cost_lcoe_usd_per_kwh"])
        base_lcoe = float(srow["base_design_lcoe_usd_per_kwh"])
        if math.isnan(least_pv):
            least_pv = None
        if math.isnan(least_batt):
            least_batt = None
        if math.isnan(least_lcoe):
            least_lcoe = None
        same = bool(srow["same_design"])
        note = "" if srow["note"] is None else str(srow["note"])
        if isinstance(note, float) and math.isnan(note):
            note = ""
        if least_pv is not None and note == "" and (
            least_pv == max(pv_grid) or least_batt == max(battery_grid)
        ):
            note = "on grid edge"
        sens_rows.append({
            "input": str(srow["input"]),
            "factor": float(srow["factor"]),
            "base_design_lcoe_usd_per_kwh": base_lcoe,
            "least_cost_pv_kwp": least_pv,
            "least_cost_battery_kwh": least_batt,
            "least_cost_lcoe_usd_per_kwh": least_lcoe,
            "same_design": same,
            "note": note,
            "cells": [
                str(srow["input"]),
                fmt_number(float(srow["factor"]), 2),
                _opt(base_lcoe, 3),
                _opt(least_pv, 0),
                _opt(least_batt, 0),
                _opt(least_lcoe, 3),
                "yes" if same else "no",
                note,
            ],
        })
    inputs_rows = []
    for name in INPUT_NAMES:
        entry = raw["values"][name]
        inputs_rows.append({
            "name": name,
            "value": values[name],
            "unit": entry["unit"],
            "label": entry["label"],
            "note": entry["note"],
            "cells": [name, str(values[name]), entry["unit"], entry["label"], entry["note"]],
        })
    sources = [
        HIRON_2021_SOURCE,
        "OpenStreetMap Nominatim (data OpenStreetMap contributors, ODbL)",
        "Weather sources: " + ", ".join(CASE_NAMES),
    ]
    sources += [str(note) for note in weather.notes]
    sourcing_report: dict | None = None
    if s_rows is not None:
        assert s_meta is not None
        for r in s_rows:
            if r.status == "checked":
                line = "Sourced input " + r.input + ": " + (r.title or "untitled") + ", " + r.url
                if isinstance(r.doi, str) and r.doi != "":
                    line = line + ", doi:" + r.doi
                sources.append(line)
        sourcing_rows_report = []
        for r in s_rows:
            row_dict = dataclasses.asdict(r)
            if r.value_as_written is None:
                written = "none"
            else:
                written = format(r.value_as_written, "g") + " " + r.unit_as_written
            row_dict["cells"] = [
                r.input,
                r.status,
                str(r.value_used),
                r.unit,
                r.label,
                written,
                r.title or "none",
                r.url or "none",
                "none" if r.page is None else str(r.page),
                r.quote_kind,
                "; ".join(r.reasons) or "none",
            ]
            sourcing_rows_report.append(row_dict)
        sourcing_report = {"meta": s_meta, "rows": sourcing_rows_report}
    if checks_raw is not None:
        for name in CHECK_NAMES:
            entry = checks_raw["values"][name]
            if entry["label"] in ("press", "paper"):
                sources.append("Check input " + name + ": " + entry["note"])
    report = {
        "schema": REPORT_SCHEMA,
        "run_hash": run_hash,
        "question": asked,
        "request": dataclasses.asdict(req),
        "site": dataclasses.asdict(site),
        "weather_coords_deg": [lat_w, lon_w],
        "facts": facts,
        "weather_table": weather_rows,
        "range_table": range_rows,
        "sensitivity_table": sens_rows,
        "gates": gates,
        "inputs_table": inputs_rows,
        "sources": sources,
        "sourcing": sourcing_report,
        "grid": {"pv_kwp": pv_grid, "battery_kwh": battery_grid, "widened": int(widened)},
        "firmness": firmness,
    }
    markdown = render_markdown(report)
    bad = scan_report_numbers(markdown, report)
    if bad:
        raise ReportNumberMismatch("numbers in markdown missing from report: " + ", ".join(bad))
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "request.json").write_text(
        json.dumps(dataclasses.asdict(req), ensure_ascii=True, allow_nan=False, indent=2),
        encoding="ascii",
    )
    (run_dir / "site.json").write_text(
        json.dumps(dataclasses.asdict(site), ensure_ascii=True, allow_nan=False, indent=2),
        encoding="ascii",
    )
    (run_dir / "inputs.json").write_text(
        json.dumps(raw, ensure_ascii=True, allow_nan=False, indent=2), encoding="ascii"
    )
    table.to_csv(run_dir / "design_table.csv", index=False)
    sens.to_csv(run_dir / "sensitivity.csv", index=False)
    (run_dir / "report.md").write_text(markdown, encoding="ascii")
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=True, allow_nan=False, indent=2), encoding="ascii"
    )
    return StudyOutput(run_hash, run_dir, report, markdown, False)
