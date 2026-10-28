"""Acceptance tests for T15 (more checks: battery power, island prices, load not served, diesel engine hours).
Written by the orchestrator. No network.

Unit tests use the small series of test_firmness; the study runs use the synthetic weather of test_study."""
import dataclasses
import json

import pandas as pd
import pytest

import test_firmness as tf
import test_study as ts
from autosolar.dispatch import Battery, DieselFleet
from autosolar.econ import CostInputs
from autosolar.firmness import (ALT_KEYS, CHECK_NAMES, DUR_KEYS, FIRM_CHECK_LABEL, FIRM_SPECS, FIRM_TITLES, MORE_KEYS,
                                OPTIONAL_CHECK_NAMES, OUT_OF_SCOPE, battery_power_use, capex_break_even,
                                duration_case, engine_hours, load_checks, run_stats)
from autosolar.site import caveats
from autosolar.study import firm_items, fmt_number, load_inputs, run_study
from autosolar.sweep import cost_table, dispatch_grid, least_cost, on_grid_edge

CHECKS = tf.CHECKS
KEYS = [k for k, _, _, _ in FIRM_SPECS]
ROWS = [
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
]
TITLES = {
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
}
OVERHAUL = "Diesel overhaul and engine replacement costs, which grow with engine hours"
PV_GRID = [0.0, 500.0, 1000.0]
B_GRID = [0.0, 1000.0, 2000.0]
DUR_RESULT = {"hours", "pv_kwp", "battery_kwh", "battery_kw", "lcoe_usd_per_kwh", "change_pct", "on_grid_edge"}
BE_RESULT = {"factor", "rise_pct", "pv_capex_usd_per_kwp", "battery_capex_usd_per_kwh"}


def grid_points(load=None, hours=4.0, pv_grid=PV_GRID, b_grid=B_GRID):
    return dispatch_grid(tf.PER_KWP, tf.LOAD if load is None else load, pv_grid, b_grid, battery_hours=hours,
                         battery_template=tf.BAT_T, diesel=tf.FLEET)


@pytest.fixture(scope="module")
def pts():
    return grid_points()


def scaled(c, k):
    return dataclasses.replace(c, pv_capex_usd_per_kwp=k * c.pv_capex_usd_per_kwp,
                               battery_capex_usd_per_kwh=k * c.battery_capex_usd_per_kwh,
                               battery_power_capex_usd_per_kw=k * c.battery_power_capex_usd_per_kw)


def is_d0(p):
    return p.design.pv_kwp == 0.0 and p.design.battery_kwh == 0.0


def point(points, pv, b):
    return [p for p in points if p.design.pv_kwp == pv and p.design.battery_kwh == b][0]


def best_other_and_d0(points, c, limit=0.001):
    t = cost_table(points, c, 2.68)
    d0 = (t["pv_kwp"] == 0.0) & (t["battery_kwh"] == 0.0)
    other = t[~d0 & (t["unserved_frac"] <= limit)]
    return float(other["lcoe_usd_per_kwh"].min()), float(t[d0].iloc[0]["lcoe_usd_per_kwh"])


def infeasible(p):
    return dataclasses.replace(p, result=dataclasses.replace(p.result, unserved_frac=0.5))


# ---------- constants ----------

def test_constants():
    assert OPTIONAL_CHECK_NAMES == ("diesel_unit_kw_alt", "battery_duration_h_alt")
    assert "battery_duration_h_alt" not in CHECK_NAMES
    assert MORE_KEYS == tuple(r[0] for r in ROWS)
    assert DUR_KEYS == tuple(r[0] for r in ROWS if r[0].startswith("dur_alt_"))
    assert len(DUR_KEYS) == 7 and not set(DUR_KEYS) & set(ALT_KEYS)
    i = KEYS.index("alt_reserve_lcoe_usd_per_kwh")
    assert [tuple(r) for r in FIRM_SPECS[i + 1:i + 20]] == ROWS
    assert KEYS[i + 20:] == ["sourcing_cost_usd", "total_cost_usd"]
    assert len(FIRM_SPECS) == 60 and len(set(KEYS)) == 60
    assert FIRM_CHECK_LABEL["dur_alt_hours"] == "battery_duration_h_alt"
    for key, title in TITLES.items():
        assert FIRM_TITLES[key] == title, key
    assert len(OUT_OF_SCOPE) == 9 and OUT_OF_SCOPE[-1] == OVERHAUL


# ---------- load_checks ----------

def _write(tmp_path, fn, name="c.json"):
    raw = json.loads(CHECKS.read_text(encoding="utf-8"))
    fn(raw)
    p = tmp_path / name
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def test_default_checks_file_has_duration():
    values, raw = load_checks(CHECKS)
    assert type(values["battery_duration_h_alt"]) is float and values["battery_duration_h_alt"] == 8.0
    entry = raw["values"]["battery_duration_h_alt"]
    assert entry["label"] == "assumed" and entry["unit"] == "h"
    assert set(values) == set(CHECK_NAMES) | set(OPTIONAL_CHECK_NAMES)


def test_load_checks_without_duration(tmp_path):
    values, raw = load_checks(_write(tmp_path, lambda r: r["values"].pop("battery_duration_h_alt")))
    assert set(values) == set(CHECK_NAMES) | {"diesel_unit_kw_alt"}
    assert "battery_duration_h_alt" not in raw["values"]


def test_load_checks_without_both_optional(tmp_path):
    def fn(r):
        r["values"].pop("battery_duration_h_alt")
        r["values"].pop("diesel_unit_kw_alt")
    values, _ = load_checks(_write(tmp_path, fn))
    assert set(values) == set(CHECK_NAMES)


def test_load_checks_duration_values(tmp_path):
    values, _ = load_checks(_write(tmp_path, lambda r: r["values"]["battery_duration_h_alt"].update(value=8)))
    assert type(values["battery_duration_h_alt"]) is float and values["battery_duration_h_alt"] == 8.0
    values, _ = load_checks(_write(tmp_path, lambda r: r["values"]["battery_duration_h_alt"].update(value=2.5),
                                   "c2.json"))
    assert values["battery_duration_h_alt"] == 2.5 and values["diesel_unit_kw_alt"] == 2700.0


@pytest.mark.parametrize("fn", [
    lambda r: r["values"]["battery_duration_h_alt"].update(value=0.0),
    lambda r: r["values"]["battery_duration_h_alt"].update(value=-8.0),
    lambda r: r["values"]["battery_duration_h_alt"].update(value="8"),
    lambda r: r["values"]["battery_duration_h_alt"].update(value=True),
    lambda r: r["values"]["battery_duration_h_alt"].update(value=None),
    lambda r: r["values"]["battery_duration_h_alt"].update(value=[8.0]),
    lambda r: r["values"]["battery_duration_h_alt"].update(value=float("inf")),
    lambda r: r["values"]["battery_duration_h_alt"].update(value=float("nan")),
    lambda r: r["values"]["battery_duration_h_alt"].update(label="guess"),
    lambda r: r["values"]["battery_duration_h_alt"].update(unit=""),
    lambda r: r["values"]["battery_duration_h_alt"].update(unit=None),
    lambda r: r["values"]["battery_duration_h_alt"].update(note=None),
    lambda r: r["values"]["battery_duration_h_alt"].update(source="x"),
    lambda r: r["values"]["battery_duration_h_alt"].pop("note"),
    lambda r: r["values"].update(battery_duration_h_alt=8.0),
    lambda r: r["values"].update(battery_duration_h_alt2={"value": 8.0, "unit": "h", "label": "assumed", "note": ""}),
])
def test_load_checks_rejects_bad_duration(tmp_path, fn):
    with pytest.raises(ValueError):
        load_checks(_write(tmp_path, fn, "bad.json"))


# ---------- battery_power_use ----------

def frame(dis, pv, dg):
    return pd.DataFrame({"battery_discharge_kw": dis, "pv_to_battery_kw": pv, "diesel_to_battery_kw": dg,
                         "load_kw": [500.0] * len(dis)})


def test_battery_power_use_discharge_sets_the_peak():
    r = battery_power_use(frame([0.0, 50.0, 120.0, 30.0], [100.0, 0.0, 10.0, 0.0], [0.0, 0.0, 80.0, 0.0]), 200.0)
    assert set(r) == {"peak_discharge_kw", "peak_charge_kw", "peak_use_pct"}
    assert r["peak_discharge_kw"] == 120.0
    assert r["peak_charge_kw"] == 100.0
    assert r["peak_use_pct"] == pytest.approx(60.0, rel=1e-12)
    assert all(type(v) is float for v in r.values())


def test_battery_power_use_charge_sets_the_peak():
    r = battery_power_use(frame([10.0, 20.0, 5.0], [250.0, 0.0, 60.0], [0.0, 40.0, 70.0]), 500)
    assert r["peak_charge_kw"] == 250.0 and r["peak_discharge_kw"] == 20.0
    assert r["peak_use_pct"] == pytest.approx(50.0, rel=1e-12)


def test_battery_power_use_charge_is_pv_plus_diesel_in_the_same_hour():
    r = battery_power_use(frame([5.0, 0.0, 0.0], [60.0, 10.0, 0.0], [0.0, 70.0, 65.0]), 160.0)
    assert r["peak_charge_kw"] == 80.0
    assert r["peak_use_pct"] == pytest.approx(50.0, rel=1e-12)


def test_battery_power_use_zero_rating():
    r = battery_power_use(frame([0.0, 0.0], [0.0, 0.0], [0.0, 0.0]), 0.0)
    assert r["peak_use_pct"] is None and r["peak_discharge_kw"] == 0.0 and r["peak_charge_kw"] == 0.0


@pytest.mark.parametrize("bad", [-1.0, True, "200", None, float("nan"), float("inf")])
def test_battery_power_use_rejects_rating(bad):
    with pytest.raises(ValueError):
        battery_power_use(frame([1.0], [1.0], [1.0]), bad)


@pytest.mark.parametrize("hourly", [
    frame([], [], []),
    frame([1.0], [1.0], [1.0]).drop(columns=["diesel_to_battery_kw"]),
    frame([1.0], [1.0], [1.0]).drop(columns=["battery_discharge_kw"]),
    {"battery_discharge_kw": [1.0], "pv_to_battery_kw": [1.0], "diesel_to_battery_kw": [1.0]},
    None,
])
def test_battery_power_use_rejects_hourly(hourly):
    with pytest.raises(ValueError):
        battery_power_use(hourly, 100.0)


def test_battery_power_use_on_a_dispatch(pts):
    p = point(pts, 1000.0, 2000.0)
    h = p.result.hourly
    r = battery_power_use(h, p.design.battery_kw)
    chg = float((h["pv_to_battery_kw"] + h["diesel_to_battery_kw"]).max())
    assert r["peak_charge_kw"] == pytest.approx(chg, rel=1e-12) and chg > 0.0
    assert r["peak_discharge_kw"] == pytest.approx(float(h["battery_discharge_kw"].max()), rel=1e-12)


# ---------- duration_case ----------

def dcase(**kw):
    args = dict(battery_hours=8.0, battery_template=tf.BAT_T, diesel=tf.FLEET, costs=tf.costs(), co2_kg_per_l=2.68,
                unserved_max_frac=0.001, main_lcoe_usd_per_kwh=0.3)
    args.update(kw)
    load = args.pop("load_kw", tf.LOAD)
    pv_grid = args.pop("pv_grid", PV_GRID)
    b_grid = args.pop("battery_grid", B_GRID)
    return duration_case(tf.PER_KWP, load, pv_grid, b_grid, **args)


@pytest.mark.parametrize("hours", [8.0, 2.0])
def test_duration_case_matches_direct(hours):
    r = dcase(battery_hours=hours)
    t = cost_table(grid_points(hours=hours), tf.costs(), 2.68)
    pick = least_cost(t, 0.001)
    assert set(r) == DUR_RESULT
    assert type(r["hours"]) is float and r["hours"] == hours
    for k in ("pv_kwp", "battery_kwh", "battery_kw"):
        assert type(r[k]) is float and r[k] == float(pick[k]), k
    assert r["lcoe_usd_per_kwh"] == pytest.approx(float(pick["lcoe_usd_per_kwh"]), rel=1e-12)
    assert r["change_pct"] == pytest.approx(100.0 * (float(pick["lcoe_usd_per_kwh"]) / 0.3 - 1.0), rel=1e-12)
    assert r["on_grid_edge"] is bool(on_grid_edge(t, pick))


def test_duration_case_hours_change_the_battery():
    r8, r2 = dcase(battery_hours=8.0), dcase(battery_hours=2.0)
    assert r8["battery_kwh"] > 0.0 and r2["battery_kwh"] > 0.0
    assert r8["battery_kw"] == pytest.approx(r8["battery_kwh"] / 8.0, rel=1e-12)
    assert r2["battery_kw"] == pytest.approx(r2["battery_kwh"] / 2.0, rel=1e-12)
    assert r8["lcoe_usd_per_kwh"] != pytest.approx(r2["lcoe_usd_per_kwh"], rel=1e-6)


def test_duration_case_change_uses_main_lcoe():
    a, b = dcase(main_lcoe_usd_per_kwh=0.3), dcase(main_lcoe_usd_per_kwh=0.25)
    assert a["lcoe_usd_per_kwh"] == b["lcoe_usd_per_kwh"]
    assert b["change_pct"] == pytest.approx(100.0 * (b["lcoe_usd_per_kwh"] / 0.25 - 1.0), rel=1e-12)
    assert a["change_pct"] != pytest.approx(b["change_pct"], rel=1e-6)


def test_duration_case_int_hours():
    r = dcase(battery_hours=8)
    assert type(r["hours"]) is float and r == dcase(battery_hours=8.0)


def test_duration_case_no_feasible_design():
    r = dcase(load_kw=tf.LOAD * 10.0, pv_grid=[0.0, 500.0], battery_grid=[0.0, 1000.0])
    assert set(r) == DUR_RESULT
    for k in ("pv_kwp", "battery_kwh", "battery_kw", "lcoe_usd_per_kwh", "change_pct"):
        assert r[k] is None, k
    assert r["on_grid_edge"] is False and r["hours"] == 8.0


@pytest.mark.parametrize("bad", [0, 0.0, -8.0, True, False, "8", None, float("nan"), float("inf")])
def test_duration_case_rejects_hours(bad):
    with pytest.raises(ValueError):
        dcase(battery_hours=bad)


@pytest.mark.parametrize("bad", [0.0, -0.3, True, "0.3", None, float("nan"), float("inf")])
def test_duration_case_rejects_main_lcoe(bad):
    with pytest.raises(ValueError):
        dcase(main_lcoe_usd_per_kwh=bad)


# ---------- capex_break_even ----------

def test_capex_break_even_ties_diesel_only(pts):
    c = tf.costs()
    r = capex_break_even(pts, c, 2.68, 0.001)
    assert set(r) == BE_RESULT and all(type(v) is float for v in r.values())
    k = r["factor"]
    assert k > 0.0
    assert r["rise_pct"] == pytest.approx(100.0 * (k - 1.0), rel=1e-12)
    assert r["pv_capex_usd_per_kwp"] == pytest.approx(k * c.pv_capex_usd_per_kwp, rel=1e-12)
    assert r["battery_capex_usd_per_kwh"] == pytest.approx(k * c.battery_capex_usd_per_kwh, rel=1e-12)
    lo, d0 = best_other_and_d0(pts, scaled(c, k))
    assert lo == pytest.approx(d0, rel=1e-9)
    lo, d0 = best_other_and_d0(pts, scaled(c, k * 1.01))
    assert lo > d0
    lo, d0 = best_other_and_d0(pts, scaled(c, k * 0.99))
    assert lo < d0


def test_capex_break_even_scales_with_the_price(pts):
    c = tf.costs()
    r1 = capex_break_even(pts, c, 2.68, 0.001)
    r10 = capex_break_even(pts, scaled(c, 10.0), 2.68, 0.001)
    assert r10["factor"] == pytest.approx(r1["factor"] / 10.0, rel=1e-9)
    assert r10["rise_pct"] == pytest.approx(100.0 * (r1["factor"] / 10.0 - 1.0), rel=1e-9)
    assert r10["rise_pct"] < 0.0
    assert r10["pv_capex_usd_per_kwp"] == pytest.approx(r1["pv_capex_usd_per_kwp"], rel=1e-9)
    assert r10["battery_capex_usd_per_kwh"] == pytest.approx(r1["battery_capex_usd_per_kwh"], rel=1e-9)


def test_capex_break_even_battery_price_counts(pts):
    c = tf.costs()
    only_b = [p for p in pts if is_d0(p) or p.design.battery_kwh > 0.0]
    r = capex_break_even(only_b, c, 2.68, 0.001)
    assert r["factor"] is not None
    lo, d0 = best_other_and_d0(only_b, scaled(c, r["factor"]))
    assert lo == pytest.approx(d0, rel=1e-9)
    no_power = dataclasses.replace(c, battery_power_capex_usd_per_kw=0.0)
    r2 = capex_break_even(only_b, no_power, 2.68, 0.001)
    assert r2["factor"] != pytest.approx(r["factor"], rel=1e-6)
    lo, d0 = best_other_and_d0(only_b, scaled(no_power, r2["factor"]))
    assert lo == pytest.approx(d0, rel=1e-9)


def test_capex_break_even_order_free(pts):
    c = tf.costs()
    r = capex_break_even(pts, c, 2.68, 0.001)
    assert capex_break_even(list(reversed(pts)), c, 2.68, 0.001) == pytest.approx(r, rel=1e-12)


def test_capex_break_even_skips_designs_over_the_unserved_limit(pts):
    c = tf.costs()
    r = capex_break_even(pts, c, 2.68, 0.001)
    t = cost_table(pts, scaled(c, r["factor"]), 2.68)
    d0 = (t["pv_kwp"] == 0.0) & (t["battery_kwh"] == 0.0)
    tie = t[~d0].sort_values("lcoe_usd_per_kwh").iloc[0]
    masked = [infeasible(p) if (p.design.pv_kwp == float(tie["pv_kwp"])
                                and p.design.battery_kwh == float(tie["battery_kwh"])) else p for p in pts]
    r2 = capex_break_even(masked, c, 2.68, 0.001)
    assert r2["factor"] < r["factor"] - 1e-9
    lo, d0v = best_other_and_d0(masked, scaled(c, r2["factor"]))
    assert lo == pytest.approx(d0v, rel=1e-9)
    assert capex_break_even(masked, c, 2.68, 0.6)["factor"] == pytest.approx(r["factor"], rel=1e-12)


def test_capex_break_even_none_when_no_design_qualifies(pts):
    masked = [p if is_d0(p) else infeasible(p) for p in pts]
    r = capex_break_even(masked, tf.costs(), 2.68, 0.001)
    assert r == {"factor": None, "rise_pct": None, "pv_capex_usd_per_kwp": None, "battery_capex_usd_per_kwh": None}


def test_capex_break_even_none_when_diesel_only_wins_at_any_price(pts):
    c = dataclasses.replace(tf.costs(), fuel_price_usd_per_l=1e-6, diesel_om_usd_per_kwh=1e-6)
    lo, d0 = best_other_and_d0(pts, scaled(c, 1e-9))
    assert lo > d0
    r = capex_break_even(pts, c, 2.68, 0.001)
    assert r == {"factor": None, "rise_pct": None, "pv_capex_usd_per_kwp": None, "battery_capex_usd_per_kwh": None}


def test_capex_break_even_needs_points_and_diesel_only(pts):
    with pytest.raises(ValueError):
        capex_break_even([], tf.costs(), 2.68, 0.001)
    with pytest.raises(ValueError):
        capex_break_even([p for p in pts if not is_d0(p)], tf.costs(), 2.68, 0.001)


@pytest.mark.parametrize("bad", [-0.1, True, None, "0.001", float("nan")])
def test_capex_break_even_rejects_limit(pts, bad):
    with pytest.raises(ValueError):
        capex_break_even(pts, tf.costs(), 2.68, bad)


# ---------- run_stats ----------

def test_run_stats_feasible(pts):
    p = point(pts, 1000.0, 2000.0)
    r = run_stats(p.result, 2000.0)
    assert set(r) == {"unserved_kwh", "unserved_hours", "battery_cycles"}
    assert type(r["unserved_kwh"]) is float and r["unserved_kwh"] == float(p.result.unserved_kwh)
    assert type(r["unserved_hours"]) is int
    assert r["unserved_hours"] == int((p.result.hourly["unserved_kw"] > 0.0).sum())
    assert type(r["battery_cycles"]) is float and p.result.battery_discharge_kwh > 0.0
    assert r["battery_cycles"] == pytest.approx(float(p.result.battery_discharge_kwh) / 2000.0, rel=1e-12)
    assert run_stats(p.result, 1000)["battery_cycles"] == pytest.approx(2.0 * r["battery_cycles"], rel=1e-12)


def test_run_stats_counts_hours_with_load_not_served():
    res = point(grid_points(load=tf.LOAD * 1.5, pv_grid=[0.0, 500.0], b_grid=[0.0, 1000.0]), 0.0, 0.0).result
    r = run_stats(res, 0.0)
    want = int((res.hourly["unserved_kw"] > 0.0).sum())
    assert 0 < want < len(res.hourly)
    assert r["unserved_hours"] == want
    assert r["unserved_kwh"] == pytest.approx(float(res.unserved_kwh), rel=1e-12) and r["unserved_kwh"] > want
    assert r["battery_cycles"] is None


@pytest.mark.parametrize("bad", [-1.0, True, "2000", None, float("nan"), float("inf")])
def test_run_stats_rejects_battery(pts, bad):
    with pytest.raises(ValueError):
        run_stats(pts[0].result, bad)


def test_run_stats_rejects_result():
    with pytest.raises(ValueError):
        run_stats({"unserved_kwh": 0.0}, 1000.0)


# ---------- engine_hours ----------

def test_engine_hours_sums_running_units(pts):
    d0 = [p for p in pts if is_d0(p)][0].result
    des = point(pts, 1000.0, 2000.0).result
    r = engine_hours(d0, des)
    u0 = float(d0.hourly["diesel_units_on"].sum())
    u1 = float(des.hourly["diesel_units_on"].sum())
    assert u0 > d0.diesel_run_hours
    assert set(r) == {"diesel_only_unit_hours", "design_unit_hours", "cut_pct"}
    assert all(type(v) is float for v in r.values())
    assert r["diesel_only_unit_hours"] == u0 and r["design_unit_hours"] == u1
    assert r["cut_pct"] == pytest.approx(100.0 * (1.0 - u1 / u0), rel=1e-12)
    back = engine_hours(des, d0)
    assert back["cut_pct"] == pytest.approx(100.0 * (1.0 - u0 / u1), rel=1e-12) and back["cut_pct"] < 0.0


def test_engine_hours_zero_diesel_only(pts):
    d0 = [p for p in pts if is_d0(p)][0].result
    h = d0.hourly.copy()
    h["diesel_units_on"] = 0
    off = dataclasses.replace(d0, hourly=h)
    r = engine_hours(off, d0)
    assert r["cut_pct"] is None and r["diesel_only_unit_hours"] == 0.0


def test_engine_hours_rejects_non_results(pts):
    with pytest.raises(ValueError):
        engine_hours({"hourly": None}, pts[0].result)
    with pytest.raises(ValueError):
        engine_hours(pts[0].result, None)


# ---------- firm_items ----------

def test_firm_items_duration_rows():
    craw = json.loads(CHECKS.read_text(encoding="utf-8"))
    vals = {k: 1234.5678 for k in KEYS}
    vals["land_fits"] = True
    vals["alt_on_grid_edge"] = True
    vals["dur_alt_on_grid_edge"] = 0
    vals["best_battery_cycles_yr"] = None
    items = firm_items(vals, craw)
    assert [it["key"] for it in items] == KEYS
    by = {it["key"]: it for it in items}
    assert by["dur_alt_on_grid_edge"]["value"] is False and by["dur_alt_on_grid_edge"]["text"] == "no"
    assert by["dur_alt_hours"]["label"] == "assumed" and by["dur_alt_hours"]["text"] == "1,234.6"
    assert by["battery_peak_use_pct"]["text"] == "1,234.6" and by["battery_peak_use_pct"]["label"] == "computed"
    assert by["engine_hours_best"]["text"] == "1,235" and by["engine_hours_best"]["unit"] == "unit h/yr"
    assert by["best_battery_cycles_yr"]["value"] is None and by["best_battery_cycles_yr"]["text"] == "none"
    vals["dur_alt_on_grid_edge"] = 1
    assert {it["key"]: it for it in firm_items(vals, craw)}["dur_alt_on_grid_edge"]["text"] == "yes"
    craw["values"]["battery_duration_h_alt"]["label"] = "paper"
    assert {it["key"]: it for it in firm_items(vals, craw)}["dur_alt_hours"]["label"] == "paper"
    craw["values"].pop("battery_duration_h_alt")
    assert [it["key"] for it in firm_items(vals, craw)] == [k for k in KEYS if k not in DUR_KEYS]
    craw["values"].pop("diesel_unit_kw_alt")
    keys = [it["key"] for it in firm_items(vals, craw)]
    assert keys == [k for k in KEYS if k not in DUR_KEYS and k not in ALT_KEYS] and len(keys) == 42


# ---------- the study runs ----------

@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("more")
    inputs = ts.small_inputs(tmp)
    raw = json.loads(CHECKS.read_text(encoding="utf-8"))
    raw["values"]["battery_duration_h_alt"]["label"] = "paper"
    paper = tmp / "checks_dur_paper.json"
    paper.write_text(json.dumps(raw), encoding="utf-8")
    raw["values"].pop("battery_duration_h_alt")
    nodur = tmp / "checks_no_dur.json"
    nodur.write_text(json.dumps(raw), encoding="utf-8")

    def go(run_id, path):
        return run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                         inputs_path=inputs, runs_dir=tmp / "runs", run_id=run_id, checks_path=path)
    return {"dur": go("dur", CHECKS), "paper": go("paper", paper), "nodur": go("nodur", nodur), "inputs": inputs}


def _items(out):
    return {it["key"]: it for it in out.report["firmness"]["items"]}


def _direct(runs):
    values, _ = load_inputs(runs["inputs"])
    w = ts.synthetic_weather(-5.88, 110.43)
    from autosolar.demand import build_demand_cases
    from autosolar.pv import PVDesign, simulate_pv
    basis_kw = simulate_pv(w.cases["CAMS"], -5.88, 110.43, PVDesign(), 1.0).hourly["ac_kw"]
    load = build_demand_cases(w.cases["CAMS"].index)["paper"].load_kw
    c = CostInputs(**{f.name: values[f.name] for f in dataclasses.fields(CostInputs)})
    bat = Battery(energy_kwh=1.0, power_kw=1.0, round_trip_eff_frac=float(values["battery_round_trip_eff_frac"]),
                  soc_min_frac=float(values["battery_soc_min_frac"]),
                  soc_initial_frac=float(values["battery_soc_initial_frac"]))
    fleet = DieselFleet(unit_kw=float(values["diesel_unit_kw"]), n_units=int(values["diesel_n_units"]),
                        min_load_frac=float(values["diesel_min_load_frac"]),
                        fuel_intercept_l_per_h_per_kw_rated=float(values["fuel_intercept_l_per_h_per_kw_rated"]),
                        fuel_slope_l_per_kwh=float(values["fuel_slope_l_per_kwh"]))
    grid = runs["dur"].report["grid"]
    points = dispatch_grid(basis_kw, load, grid["pv_kwp"], grid["battery_kwh"],
                           battery_hours=float(values["battery_duration_h"]), battery_template=bat, diesel=fleet)
    co2 = float(values["co2_kg_per_l"])
    umax = float(values["unserved_max_frac"])
    t = cost_table(points, c, co2)
    pick = least_cost(t, umax)
    return dict(values=values, basis_kw=basis_kw, load=load, costs=c, bat=bat, fleet=fleet, grid=grid,
                points=points, co2=co2, umax=umax, pick=pick, best=points[int(pick.name)].result)


def test_more_values_match_direct(runs):
    d = _direct(runs)
    it = _items(runs["dur"])
    facts = runs["dur"].report["facts"]
    pick, best = d["pick"], d["best"]
    assert float(pick["pv_kwp"]) == facts["best_pv_kwp"]["value"]
    assert float(pick["battery_kwh"]) == facts["best_battery_kwh"]["value"]
    h = best.hourly
    dis = float(h["battery_discharge_kw"].max())
    chg = float((h["pv_to_battery_kw"] + h["diesel_to_battery_kw"]).max())
    assert float(pick["battery_kw"]) > 0.0
    want = {
        "battery_peak_discharge_kw": dis,
        "battery_peak_charge_kw": chg,
        "battery_peak_use_pct": 100.0 * max(dis, chg) / float(pick["battery_kw"]),
        "best_unserved_kwh_yr": float(best.unserved_kwh),
        "best_unserved_hours": float((h["unserved_kw"] > 0.0).sum()),
        "best_battery_cycles_yr": float(best.battery_discharge_kwh) / float(pick["battery_kwh"]),
    }
    d0 = [p.result for p in d["points"] if is_d0(p)][0]
    u0 = float(d0.hourly["diesel_units_on"].sum())
    u1 = float(h["diesel_units_on"].sum())
    want.update(engine_hours_diesel_only=u0, engine_hours_best=u1, engine_hours_cut_pct=100.0 * (1.0 - u1 / u0))
    be = capex_break_even(d["points"], d["costs"], d["co2"], d["umax"])
    want.update(capex_break_even_rise_pct=be["rise_pct"], capex_break_even_pv_usd_per_kwp=be["pv_capex_usd_per_kwp"],
                capex_break_even_battery_usd_per_kwh=be["battery_capex_usd_per_kwh"])
    assert be["factor"] is not None
    lo, d0v = best_other_and_d0(d["points"], scaled(d["costs"], be["factor"]), d["umax"])
    assert lo == pytest.approx(d0v, rel=1e-9)
    for key, val in want.items():
        assert it[key]["value"] == pytest.approx(val, rel=1e-9, abs=1e-12), key
        assert it[key]["label"] == "computed", key


def test_duration_values_match_direct(runs):
    d = _direct(runs)
    it = _items(runs["dur"])
    main = runs["dur"].report["facts"]["best_lcoe_usd_per_kwh"]["value"]
    r = duration_case(d["basis_kw"], d["load"], d["grid"]["pv_kwp"], d["grid"]["battery_kwh"], battery_hours=8.0,
                      battery_template=d["bat"], diesel=d["fleet"], costs=d["costs"], co2_kg_per_l=d["co2"],
                      unserved_max_frac=d["umax"], main_lcoe_usd_per_kwh=main)
    assert r["lcoe_usd_per_kwh"] is not None
    assert it["dur_alt_hours"]["value"] == 8.0 and it["dur_alt_hours"]["label"] == "assumed"
    assert it["dur_alt_hours"]["text"] == "8.0" and it["dur_alt_hours"]["unit"] == "h"
    for name in ("pv_kwp", "battery_kwh", "battery_kw", "lcoe_usd_per_kwh", "change_pct"):
        assert it["dur_alt_" + name]["value"] == pytest.approx(r[name], rel=1e-9), name
        assert it["dur_alt_" + name]["label"] == "computed"
    assert it["dur_alt_on_grid_edge"]["value"] is r["on_grid_edge"]
    assert it["dur_alt_on_grid_edge"]["text"] == ("yes" if r["on_grid_edge"] else "no")
    assert it["dur_alt_battery_kw"]["value"] == pytest.approx(it["dur_alt_battery_kwh"]["value"] / 8.0, rel=1e-12)


def test_more_texts(runs):
    it = _items(runs["dur"])
    for key, unit, label, dec in ROWS:
        item = it[key]
        assert item["title"] == TITLES[key] and item["unit"] == unit, key
        if key != "dur_alt_on_grid_edge" and item["value"] is not None:
            assert item["text"] == fmt_number(float(item["value"]), dec), key


def test_main_answer_unchanged(runs):
    a, b = runs["dur"].report, runs["nodur"].report
    assert a["facts"] == b["facts"] and a["gates"] == b["gates"] and a["range_table"] == b["range_table"]
    assert runs["dur"].run_hash != runs["nodur"].run_hash


def test_without_duration(runs):
    out = runs["nodur"]
    keys = [it["key"] for it in out.report["firmness"]["items"]]
    assert keys == [k for k in KEYS if k not in DUR_KEYS]
    assert "Battery duration check" not in out.markdown
    a, b = _items(runs["dur"]), _items(out)
    for key in MORE_KEYS:
        if key not in DUR_KEYS:
            assert b[key] == a[key], key


def test_markdown_order(runs):
    md = runs["dur"].markdown
    block = md[md.index("## How firm is the answer\n"):md.index("## Weather sources\n")]
    lines = [x for x in block.split("\n")[1:] if x]
    assert len(lines) == 60
    j = [x.split(":")[0] + ":" + x.split(":")[1] for x in lines].index("- Diesel unit size check: reserve case LCOE")
    assert lines[j + 1].startswith("- Battery power: highest discharge in any hour, main design: ")
    assert lines[j + 4] == "- Battery duration check: other duration (battery kWh per kW): 8.0 h (assumed)"
    assert lines[j + 11].startswith("- Island prices: rise in PV and battery capital prices before diesel only is ")
    assert lines[j + 19].startswith("- Diesel engine hours: cut by the least cost design: ")
    assert lines[j + 20].startswith("- Cost of the web search")
    nb = md[md.index("## Not covered by this study\n"):md.index("## Sources\n")]
    assert "- " + OVERHAUL + "\n" in nb
    md.encode("ascii")


def test_sources(runs):
    note = json.loads(CHECKS.read_text(encoding="utf-8"))["values"]["battery_duration_h_alt"]["note"]
    src, paper = runs["dur"].report["sources"], runs["paper"].report["sources"]
    assert src == runs["nodur"].report["sources"]
    assert paper == src + ["Check input battery_duration_h_alt: " + note]
    assert paper[-2].startswith("Check input diesel_unit_kw_alt: ")
    assert _items(runs["paper"])["dur_alt_hours"]["label"] == "paper"



def test_study_passes_its_inputs_to_break_even(tmp_path, monkeypatch):
    import inspect

    import autosolar.firmness as fm
    import autosolar.study as st
    real = fm.capex_break_even
    seen = []

    def spy(*args, **kwargs):
        bound = inspect.signature(real).bind(*args, **kwargs)
        seen.append(dict(bound.arguments))
        return real(*args, **kwargs)
    monkeypatch.setattr(fm, "capex_break_even", spy)
    monkeypatch.setattr(st, "capex_break_even", spy, raising=False)
    inputs = ts.small_inputs(tmp_path)
    values, _ = load_inputs(inputs)
    out = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                    inputs_path=inputs, runs_dir=tmp_path / "runs", run_id="spy", checks_path=CHECKS)
    grid = out.report["grid"]
    assert len(seen) == 1
    got = seen[0]
    assert len(got["points"]) == len(grid["pv_kwp"]) * len(grid["battery_kwh"])
    assert got["co2_kg_per_l"] == float(values["co2_kg_per_l"])
    assert got["unserved_max_frac"] == float(values["unserved_max_frac"])
    assert 0.0 < got["unserved_max_frac"] < 1.0
    assert got["costs"].pv_capex_usd_per_kwp == float(values["pv_capex_usd_per_kwp"])


# ---------- caveats ----------

def _copy(report, drop=(), **set_items):
    r = json.loads(json.dumps(report))
    r["firmness"]["items"] = [i for i in r["firmness"]["items"] if i["key"] not in drop]
    for i in r["firmness"]["items"]:
        if i["key"] in set_items:
            i["value"], i["text"] = set_items[i["key"]]
    return r


def _island(it):
    rise = it["capex_break_even_rise_pct"]
    prices = (" (PV to " + it["capex_break_even_pv_usd_per_kwp"]["text"] + " USD/kWp, battery to "
              + it["capex_break_even_battery_usd_per_kwh"]["text"] + " USD/kWh)")
    if rise["value"] is None:
        return "Island prices: no design in the grid beats diesel only at any PV and battery capital price above zero."
    if rise["value"] >= 0.0:
        return ("Island prices: PV and battery capital prices can rise " + rise["text"] + "%" + prices
                + " before diesel only is cheaper.")
    return ("Island prices: diesel only is cheaper now; PV and battery capital prices must fall " + rise["text"][1:]
            + "%" + prices + " before a design with PV beats it.")


def _engine(it):
    cut = it["engine_hours_cut_pct"]
    if cut["value"] is not None and cut["value"] > 0.0:
        return ("Diesel engine hours: the least cost design cuts engine hours by " + cut["text"] + "% ("
                + it["engine_hours_best"]["text"] + " against " + it["engine_hours_diesel_only"]["text"]
                + " unit hours a year), so overhaul and engine replacement costs, left out here, would favour it.")
    return ("Diesel engine hours: the least cost design runs " + it["engine_hours_best"]["text"]
            + " unit hours a year against " + it["engine_hours_diesel_only"]["text"]
            + " for diesel only; overhaul and engine replacement costs are left out.")


def test_caveats_order_and_text(runs):
    r = runs["dur"].report
    it = _items(runs["dur"])
    c = caveats(r)
    assert len(c) == 8
    assert c[3] == _island(it) and c[4] == _engine(it)
    old = caveats(_copy(r, drop=MORE_KEYS))
    assert len(old) == 6 and c[:3] + c[5:] == old
    assert c[2].startswith("Diesel unit size: ")


def test_caveats_without_alt(runs):
    r = _copy(runs["dur"].report, drop=ALT_KEYS)
    c = caveats(r)
    assert len(c) == 7
    assert c[1].startswith("Reserve case: ") and c[2].startswith("Island prices: ")
    assert c[3].startswith("Diesel engine hours: ") and c[4].startswith("Land: ")


@pytest.mark.parametrize("vals,want", [
    ({"capex_break_even_rise_pct": (189.4, "189.4"), "capex_break_even_pv_usd_per_kwp": (3239.0, "3,239"),
      "capex_break_even_battery_usd_per_kwh": (868.0, "868")},
     "Island prices: PV and battery capital prices can rise 189.4% (PV to 3,239 USD/kWp, battery to 868 USD/kWh) "
     "before diesel only is cheaper."),
    ({"capex_break_even_rise_pct": (0.0, "0.0"), "capex_break_even_pv_usd_per_kwp": (1119.0, "1,119"),
      "capex_break_even_battery_usd_per_kwh": (300.0, "300")},
     "Island prices: PV and battery capital prices can rise 0.0% (PV to 1,119 USD/kWp, battery to 300 USD/kWh) "
     "before diesel only is cheaper."),
    ({"capex_break_even_rise_pct": (-12.5, "-12.5"), "capex_break_even_pv_usd_per_kwp": (979.0, "979"),
      "capex_break_even_battery_usd_per_kwh": (263.0, "263")},
     "Island prices: diesel only is cheaper now; PV and battery capital prices must fall 12.5% (PV to 979 USD/kWp, "
     "battery to 263 USD/kWh) before a design with PV beats it."),
    ({"capex_break_even_rise_pct": (None, "none"), "capex_break_even_pv_usd_per_kwp": (None, "none"),
      "capex_break_even_battery_usd_per_kwh": (None, "none")},
     "Island prices: no design in the grid beats diesel only at any PV and battery capital price above zero."),
])
def test_caveats_island_branches(runs, vals, want):
    assert caveats(_copy(runs["dur"].report, **vals))[3] == want


@pytest.mark.parametrize("vals,want", [
    ({"engine_hours_cut_pct": (83.4, "83.4"), "engine_hours_best": (1458.0, "1,458"),
      "engine_hours_diesel_only": (8760.0, "8,760")},
     "Diesel engine hours: the least cost design cuts engine hours by 83.4% (1,458 against 8,760 unit hours a year), "
     "so overhaul and engine replacement costs, left out here, would favour it."),
    ({"engine_hours_cut_pct": (0.0, "0.0"), "engine_hours_best": (8760.0, "8,760"),
      "engine_hours_diesel_only": (8760.0, "8,760")},
     "Diesel engine hours: the least cost design runs 8,760 unit hours a year against 8,760 for diesel only; "
     "overhaul and engine replacement costs are left out."),
    ({"engine_hours_cut_pct": (-5.0, "-5.0"), "engine_hours_best": (9198.0, "9,198"),
      "engine_hours_diesel_only": (8760.0, "8,760")},
     "Diesel engine hours: the least cost design runs 9,198 unit hours a year against 8,760 for diesel only; "
     "overhaul and engine replacement costs are left out."),
    ({"engine_hours_cut_pct": (None, "none"), "engine_hours_best": (0.0, "0"),
      "engine_hours_diesel_only": (0.0, "0")},
     "Diesel engine hours: the least cost design runs 0 unit hours a year against 0 for diesel only; "
     "overhaul and engine replacement costs are left out."),
])
def test_caveats_engine_branches(runs, vals, want):
    assert caveats(_copy(runs["dur"].report, **vals))[4] == want


def test_caveats_ascii(runs):
    for line in caveats(runs["dur"].report):
        line.encode("ascii")
