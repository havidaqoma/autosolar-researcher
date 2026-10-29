"""Acceptance tests for T08b (autosolar/sweep.py). Written by the orchestrator. No network."""
import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from autosolar.dispatch import Battery, DieselFleet, dispatch
from autosolar.econ import AnnualFlows, CostInputs, Design, evaluate
from autosolar.sweep import (SENSITIVITY_COLUMNS, SENSITIVITY_INPUTS, TABLE_COLUMNS, GridPoint,
                             break_even_fuel_price_usd_per_l, cost_table, dispatch_grid, high_renewable, least_cost,
                             on_grid_edge, sensitivity_table)

IDX = pd.date_range("2021-01-01", periods=8760, freq="1h", tz="UTC")
LOCAL_HOUR = IDX.tz_convert("Asia/Jakarta").hour.to_numpy()
PV1 = pd.Series(0.8 * np.clip(np.sin((LOCAL_HOUR + 0.5 - 6) / 12 * np.pi), 0, None), index=IDX)
LOAD = pd.Series(80.0 + 15.0 * ((LOCAL_HOUR >= 18) & (LOCAL_HOUR <= 22)), index=IDX)
TEMPLATE = Battery(energy_kwh=1.0, power_kw=1.0, round_trip_eff_frac=0.9, soc_min_frac=0.1, soc_initial_frac=0.5)
DSL = DieselFleet(unit_kw=100.0, n_units=2, min_load_frac=0.3, fuel_intercept_l_per_h_per_kw_rated=0.08,
                  fuel_slope_l_per_kwh=0.25)
COSTS = CostInputs(pv_capex_usd_per_kwp=800.0, pv_om_usd_per_kwp_yr=10.0, pv_life_yr=25,
                   battery_capex_usd_per_kwh=300.0, battery_power_capex_usd_per_kw=150.0,
                   battery_om_usd_per_kwh_yr=5.0, battery_life_yr=12, diesel_om_usd_per_kwh=0.03,
                   fuel_price_usd_per_l=1.0, discount_rate_frac=0.08, project_life_yr=20, currency_year=2025)
PV_GRID = [0, 50, 100]
BAT_GRID = (0.0, 100.0, 300.0)
KW = dict(battery_hours=4.0, battery_template=TEMPLATE, diesel=DSL)


@pytest.fixture(scope="module")
def points():
    return dispatch_grid(PV1, LOAD, PV_GRID, BAT_GRID, **KW)


@pytest.fixture(scope="module")
def table(points):
    return cost_table(points, COSTS, 2.68)


def test_grid_order_and_designs(points):
    assert len(points) == 9 and all(isinstance(p, GridPoint) for p in points)
    pairs = [(p.design.pv_kwp, p.design.battery_kwh, p.design.battery_kw) for p in points]
    assert pairs == [(0.0, 0.0, 0.0), (0.0, 100.0, 25.0), (0.0, 300.0, 75.0), (50.0, 0.0, 0.0),
                     (50.0, 100.0, 25.0), (50.0, 300.0, 75.0), (100.0, 0.0, 0.0), (100.0, 100.0, 25.0),
                     (100.0, 300.0, 75.0)]
    assert all(isinstance(p.design, Design) for p in points)


def test_grid_point_matches_direct_dispatch(points):
    bat = dataclasses.replace(TEMPLATE, energy_kwh=300.0, power_kw=75.0)
    direct = dispatch(PV1 * 100.0, LOAD, bat, DSL)
    got = points[8].result
    assert got.fuel_l == pytest.approx(direct.fuel_l)
    assert got.diesel_kwh == pytest.approx(direct.diesel_kwh)
    assert got.pv_curtailed_kwh == pytest.approx(direct.pv_curtailed_kwh)
    assert points[0].result.pv_available_kwh == 0.0 and points[0].result.battery_charge_kwh == 0.0


def test_cost_table_columns_and_values(points, table):
    assert TABLE_COLUMNS == ("pv_kwp", "battery_kwh", "battery_kw", "lcoe_usd_per_kwh", "lcoe_path_a_usd_per_kwh",
                             "npc_usd", "capex_initial_usd", "fuel_l_per_yr", "diesel_kwh_per_yr", "co2_t_per_yr",
                             "renewable_fraction_frac", "unserved_frac", "pv_curtailed_frac", "diesel_starts",
                             "diesel_run_hours")
    assert tuple(table.columns) == TABLE_COLUMNS
    assert isinstance(table.index, pd.RangeIndex) and len(table) == 9
    for c in TABLE_COLUMNS:
        want = np.int64 if c in ("diesel_starts", "diesel_run_hours") else np.float64
        assert table[c].dtype == want, c
    for i in (0, 4, 8):
        p = points[i]
        r = p.result
        e = evaluate(p.design, AnnualFlows(r.load_served_kwh, r.fuel_l, r.diesel_kwh), COSTS, 2.68)
        row = table.iloc[i]
        assert row.lcoe_usd_per_kwh == pytest.approx(e.lcoe_usd_per_kwh)
        assert row.lcoe_path_a_usd_per_kwh == pytest.approx(e.lcoe_path_a_usd_per_kwh)
        assert row.npc_usd == pytest.approx(e.npc_usd)
        assert row.capex_initial_usd == pytest.approx(e.capex_initial_usd)
        assert row.co2_t_per_yr == pytest.approx(e.co2_t_per_yr)
        assert row.fuel_l_per_yr == pytest.approx(r.fuel_l)
        assert row.diesel_kwh_per_yr == pytest.approx(r.diesel_kwh)
        assert row.renewable_fraction_frac == pytest.approx(r.renewable_fraction_frac)
        assert row.unserved_frac == pytest.approx(r.unserved_frac)
        assert row.diesel_starts == r.diesel_starts and row.diesel_run_hours == r.diesel_run_hours
    assert table.pv_curtailed_frac.iloc[0] == 0.0
    r8 = points[8].result
    assert table.pv_curtailed_frac.iloc[8] == pytest.approx(r8.pv_curtailed_kwh / r8.pv_available_kwh)
    # with these inputs PV is cheaper than fuel, so adding PV lowers the cost
    assert table.lcoe_usd_per_kwh.iloc[6] < table.lcoe_usd_per_kwh.iloc[0]


def hand_table(rows):
    t = pd.DataFrame([dict(zip(("pv_kwp", "battery_kwh", "lcoe_usd_per_kwh", "renewable_fraction_frac",
                                "unserved_frac"), r)) for r in rows])
    for c in TABLE_COLUMNS:
        if c not in t:
            t[c] = 0
    return t[list(TABLE_COLUMNS)]


HAND = hand_table([(0, 0, 0.40, 0.0, 0.0), (0, 100, 0.42, 0.0, 0.0), (100, 0, 0.30, 0.30, 0.0),
                   (100, 100, 0.25, 0.45, 0.02), (200, 0, 0.30, 0.40, 0.0), (200, 100, 0.33, 0.70, 0.0)])


def test_least_cost_and_edge():
    row = least_cost(HAND, 0.0)
    assert (row.pv_kwp, row.battery_kwh) == (100, 0)  # 0.25 is cheaper but not feasible; tie 0.30 goes to row 2
    assert not on_grid_edge(HAND, row)
    row2 = least_cost(HAND, 0.05)
    assert (row2.pv_kwp, row2.battery_kwh) == (100, 100)
    assert on_grid_edge(HAND, row2)  # battery at the grid maximum
    assert on_grid_edge(HAND, HAND.iloc[4])  # pv at the grid maximum
    with pytest.raises(ValueError):
        least_cost(HAND.assign(unserved_frac=0.5), 0.0)
    with pytest.raises(ValueError):
        least_cost(HAND, 1.5)


def test_high_renewable():
    row = high_renewable(HAND, 0.6, 0.0)
    assert (row.pv_kwp, row.battery_kwh) == (200, 100)
    row = high_renewable(HAND, 0.35, 0.0)
    assert (row.pv_kwp, row.battery_kwh) == (200, 0)
    assert high_renewable(HAND, 0.9, 0.0) is None
    with pytest.raises(ValueError):
        high_renewable(HAND, -0.1, 0.0)


def test_break_even_fuel_price(points):
    p = break_even_fuel_price_usd_per_l(points, COSTS, 2.68, 0.0)
    assert 0.0 < p < COSTS.fuel_price_usd_per_l
    below = least_cost(cost_table(points, dataclasses.replace(COSTS, fuel_price_usd_per_l=p * 0.99), 2.68), 0.0)
    above = least_cost(cost_table(points, dataclasses.replace(COSTS, fuel_price_usd_per_l=p * 1.01), 2.68), 0.0)
    assert (below.pv_kwp, below.battery_kwh) == (0.0, 0.0)
    assert (above.pv_kwp, above.battery_kwh) != (0.0, 0.0)


def test_break_even_no_pv_is_infinite():
    dark = dispatch_grid(PV1 * 0.0, LOAD, [0, 100], [0.0], **KW)  # battery grid of one value is allowed
    assert break_even_fuel_price_usd_per_l(dark, COSTS, 2.68, 0.0) == math.inf


def test_break_even_free_pv_is_zero(points):
    free = dataclasses.replace(COSTS, pv_capex_usd_per_kwp=0.0, pv_om_usd_per_kwp_yr=0.0)
    assert break_even_fuel_price_usd_per_l(points, free, 2.68, 0.0) == 0.0


@pytest.mark.parametrize("pv_grid, bat_grid", [([50, 100], [0, 100]), ([0, 100, 50], [0, 100]), ([0], [0, 100]),
                                               ([0, 100], [0, 100, 100]), ([0, math.nan], [0, 100]),
                                               ([0, True], [0, 100]), ([0, -50], [0, 100]), ([0, 100], [10, 100])])
def test_dispatch_grid_rejects_bad_grids(pv_grid, bat_grid):
    with pytest.raises(ValueError):
        dispatch_grid(PV1, LOAD, pv_grid, bat_grid, **KW)


def test_dispatch_grid_rejects_bad_hours():
    with pytest.raises(ValueError):
        dispatch_grid(PV1, LOAD, [0, 100], [0, 100], battery_hours=0.0, battery_template=TEMPLATE, diesel=DSL)


def test_cost_table_rejects_empty():
    with pytest.raises(ValueError):
        cost_table([], COSTS, 2.68)


@pytest.fixture(scope="module")
def sens():
    return sensitivity_table(PV1, LOAD, PV_GRID, BAT_GRID, costs=COSTS, co2_kg_per_l=2.68, unserved_max_frac=0.0, **KW)


def test_sensitivity_shape(sens):
    assert SENSITIVITY_INPUTS == ("pv_capex_usd_per_kwp", "battery_capex_usd_per_kwh", "fuel_price_usd_per_l",
                                  "discount_rate_frac", "demand", "diesel_om_usd_per_kwh",
                                  "fuel_intercept_l_per_h_per_kw_rated", "fuel_slope_l_per_kwh",
                                  "battery_duration_h")  # T18a added the last four
    assert SENSITIVITY_COLUMNS == ("input", "factor", "base_design_lcoe_usd_per_kwh", "least_cost_pv_kwp",
                                   "least_cost_battery_kwh", "least_cost_lcoe_usd_per_kwh", "same_design", "note")
    assert tuple(sens.columns) == SENSITIVITY_COLUMNS and len(sens) == 18
    assert isinstance(sens.index, pd.RangeIndex)
    assert sens.input.tolist() == [n for n in SENSITIVITY_INPUTS for _ in (0, 1)]
    assert sens.factor.tolist() == pytest.approx([0.8, 1.2] * 9)
    assert (sens.note == "").all()


def test_sensitivity_values(points, table, sens):
    base = least_cost(table, 0.0)
    i_base = int(base.name)
    for k, (name, factor) in enumerate(zip(sens.input, sens.factor)):
        row = sens.iloc[k]
        if name in ("fuel_intercept_l_per_h_per_kw_rated", "fuel_slope_l_per_kwh", "battery_duration_h"):
            continue  # T18a rows, checked in test_t18a.py
        if name == "demand":
            pts = dispatch_grid(PV1, LOAD * factor, PV_GRID, BAT_GRID, **KW)
            t = cost_table(pts, COSTS, 2.68)
        else:
            c = dataclasses.replace(COSTS, **{name: getattr(COSTS, name) * factor})
            t = cost_table(points, c, 2.68)
        best = least_cost(t, 0.0)
        assert row.base_design_lcoe_usd_per_kwh == pytest.approx(t.lcoe_usd_per_kwh.iloc[i_base])
        assert (row.least_cost_pv_kwp, row.least_cost_battery_kwh) == (best.pv_kwp, best.battery_kwh)
        assert row.least_cost_lcoe_usd_per_kwh == pytest.approx(best.lcoe_usd_per_kwh)
        assert bool(row.same_design) == ((best.pv_kwp, best.battery_kwh) == (base.pv_kwp, base.battery_kwh))
    fuel_up = sens[(sens.input == "fuel_price_usd_per_l") & (sens.factor > 1)].iloc[0]
    fuel_down = sens[(sens.input == "fuel_price_usd_per_l") & (sens.factor < 1)].iloc[0]
    assert fuel_up.base_design_lcoe_usd_per_kwh > fuel_down.base_design_lcoe_usd_per_kwh


def test_sensitivity_no_feasible_case():
    flat = pd.Series(90.0, index=IDX)
    one_unit = dataclasses.replace(DSL, n_units=1)  # 100 kW serves 90 kW but not 108 kW
    s = sensitivity_table(PV1, flat, [0, 50], [0, 10], battery_hours=4.0, battery_template=TEMPLATE, diesel=one_unit,
                          costs=COSTS, co2_kg_per_l=2.68, unserved_max_frac=0.0)
    up = s[(s.input == "demand") & (s.factor > 1)].iloc[0]
    assert up.note == "no feasible design" and not bool(up.same_design)
    assert math.isnan(up.least_cost_pv_kwp) and math.isnan(up.least_cost_lcoe_usd_per_kwh)
    others = s.drop(up.name)
    assert (others.note == "").all()


def test_sensitivity_rejects_bad_swing():
    with pytest.raises(ValueError):
        sensitivity_table(PV1, LOAD, PV_GRID, BAT_GRID, costs=COSTS, co2_kg_per_l=2.68, unserved_max_frac=0.0,
                          swing_frac=1.0, **KW)
