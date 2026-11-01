"""Re-cost one published study under assumed what-if changes (T25).

Reads docs/site/data/<run>/report.json and files/hourly.csv, runs
autosolar.cost_whatif.run_cases, checks the study case reproduces the
published facts, and writes JSON plus Markdown into docs/posthoc/.
"""

import argparse
import json
import math
import pathlib
import sys

import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.cost_whatif import (CASES, COST_WHATIF_SCHEMA, NOTE, apply_case,  # noqa: E402
                                   cash_flow, render_md, run_cases, summary)
from autosolar.dispatch import Battery, DieselFleet  # noqa: E402
from autosolar.econ import CostInputs, Design  # noqa: E402

COST_FIELD_ORDER = ("pv_capex_usd_per_kwp", "pv_om_usd_per_kwp_yr", "pv_life_yr",
                    "battery_capex_usd_per_kwh", "battery_power_capex_usd_per_kw",
                    "battery_om_usd_per_kwh_yr", "battery_life_yr", "diesel_om_usd_per_kwh",
                    "fuel_price_usd_per_l", "discount_rate_frac", "project_life_yr",
                    "currency_year")
INT_FIELDS = ("pv_life_yr", "battery_life_yr", "project_life_yr", "currency_year")


def _raw_value(raw: dict, name_str: str) -> object:
    """inputs_table value by name. Raises ValueError."""
    if name_str not in raw:
        raise ValueError("inputs_table misses " + name_str)
    return raw[name_str]


def _as_float(raw: dict, name_str: str) -> float:
    """inputs_table value as float. Raises ValueError."""
    value = _raw_value(raw, name_str)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name_str + " must be a number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " must be finite")
    return out


def _as_int(raw: dict, name_str: str) -> int:
    """inputs_table value as int. Raises ValueError."""
    value = _raw_value(raw, name_str)
    if isinstance(value, bool):
        raise ValueError(name_str + " must be an int")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ValueError(name_str + " must be an int")


def _fact(facts: dict, name_str: str) -> float:
    """facts value by name. Raises ValueError."""
    try:
        value = facts[name_str]["value"]
    except (KeyError, TypeError) as exc:
        raise ValueError("facts miss " + name_str) from exc
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name_str + " must be a number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " must be finite")
    return out


def main(argv=None) -> int:
    """Run the what-if tool. Returns 0 on success, 1 when not reproduced."""
    parser = argparse.ArgumentParser(description="Re-cost a study under what-if changes.")
    parser.add_argument("--run", required=True, help="study hash under site data")
    parser.add_argument("--site", default="docs/site", help="site dir, relative to repo root")
    parser.add_argument("--out", default="docs/posthoc", help="output dir, relative to repo root")
    args = parser.parse_args(argv)
    site = pathlib.Path(args.site)
    if not site.is_absolute():
        site = ROOT / site
    out = pathlib.Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    run = args.run
    report = json.loads((site / "data" / run / "report.json").read_text(encoding="utf-8"))
    frame = pd.read_csv(site / "data" / run / "files" / "hourly.csv")
    raw = {}
    for row in report["inputs_table"]:
        raw[row["name"]] = row["value"]
    facts = report["facts"]
    kwargs = {}
    for name_str in COST_FIELD_ORDER:
        if name_str in INT_FIELDS:
            kwargs[name_str] = _as_int(raw, name_str)
        else:
            kwargs[name_str] = _as_float(raw, name_str)
    costs = CostInputs(**kwargs)
    template = Battery(energy_kwh=1.0, power_kw=1.0,
                       round_trip_eff_frac=_as_float(raw, "battery_round_trip_eff_frac"),
                       soc_min_frac=_as_float(raw, "battery_soc_min_frac"),
                       soc_initial_frac=_as_float(raw, "battery_soc_initial_frac"))
    diesel = DieselFleet(unit_kw=_as_float(raw, "diesel_unit_kw"),
                         n_units=_as_int(raw, "diesel_n_units"),
                         min_load_frac=_as_float(raw, "diesel_min_load_frac"),
                         fuel_intercept_l_per_h_per_kw_rated=_as_float(
                             raw, "fuel_intercept_l_per_h_per_kw_rated"),
                         fuel_slope_l_per_kwh=_as_float(raw, "fuel_slope_l_per_kwh"))
    design = Design(pv_kwp=_fact(facts, "best_pv_kwp"),
                    battery_kwh=_fact(facts, "best_battery_kwh"),
                    battery_kw=_fact(facts, "best_battery_kw"))
    index = pd.DatetimeIndex(pd.to_datetime(frame["time_utc"], format="%Y-%m-%d %H:%M"))
    index = index.tz_localize("UTC")
    pv_ac_kw_per_kwp = pd.Series(np.asarray(frame["pv_ac_kw_per_kwp"], dtype=float), index=index)
    load_kw = pd.Series(np.asarray(frame["load_kw"], dtype=float), index=index)
    cases = run_cases(pv_ac_kw_per_kwp, load_kw, design=design, battery_template=template,
                      diesel=diesel, costs=costs)
    study = dict(CASES[0])
    plain = apply_case(costs, study)
    diesel_only = Design(pv_kwp=0.0, battery_kwh=0.0, battery_kw=0.0)
    from autosolar.cost_whatif import yearly_flows
    main_rows = cash_flow(design, yearly_flows(pv_ac_kw_per_kwp, load_kw, design=design,
                                               battery_template=template, diesel=diesel,
                                               project_life_yr=costs.project_life_yr,
                                               pv_degradation_frac_per_yr=0.0), plain, 0.0)
    diesel_rows = cash_flow(diesel_only, yearly_flows(pv_ac_kw_per_kwp, load_kw,
                                                      design=diesel_only,
                                                      battery_template=template, diesel=diesel,
                                                      project_life_yr=costs.project_life_yr,
                                                      pv_degradation_frac_per_yr=0.0), plain, 0.0)
    good = (math.isclose(cases[0]["main_lcoe_usd_per_kwh"],
                         _fact(facts, "best_lcoe_usd_per_kwh"), rel_tol=1e-9)
            and math.isclose(cases[0]["diesel_only_lcoe_usd_per_kwh"],
                             _fact(facts, "diesel_only_lcoe_usd_per_kwh"), rel_tol=1e-9)
            and math.isclose(summary(main_rows)["npc_usd"], _fact(facts, "best_npc_usd"),
                             rel_tol=1e-9))
    if not good:
        print("REPRODUCTION FAILED: study case does not match facts for run " + run)
        return 1
    inputs = {name_str: getattr(costs, name_str) for name_str in COST_FIELD_ORDER}
    inputs["pv_kwp"] = float(design.pv_kwp)
    inputs["battery_kwh"] = float(design.battery_kwh)
    inputs["battery_kw"] = float(design.battery_kw)
    doc = {"schema": COST_WHATIF_SCHEMA, "run_hash": run, "note": NOTE,
           "inputs": inputs, "cases": cases, "cash_flow_main": main_rows,
           "cash_flow_diesel_only": diesel_rows}
    out.mkdir(parents=True, exist_ok=True)
    with open(out / (run + "_cost_whatif.json"), "w", encoding="ascii", newline="\n") as handle:
        handle.write(json.dumps(doc, indent=1) + "\n")
    with open(out / (run + "_cost_whatif.md"), "w", encoding="ascii", newline="\n") as handle:
        handle.write(render_md(doc))
    for case in cases:
        print("%s %.4f %.4f" % (case["key"], case["main_lcoe_usd_per_kwh"],
                                 case["diesel_only_lcoe_usd_per_kwh"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
