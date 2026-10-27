"""Acceptance tests for T08 (autosolar/econ.py). Written by the orchestrator. No network.

Expected values are written out by hand as plain arithmetic, not computed with the code under test."""
import dataclasses
import math

import pytest

import autosolar.econ as econ
from autosolar.econ import (LCOE_TWIN_TOL_FRAC, AnnualFlows, CostInputs, Design, EconResult, LcoeTwinMismatch,
                            component_schedule, crf, evaluate, lcoe_path_a, lcoe_path_b)

C1 = CostInputs(pv_capex_usd_per_kwp=1000.0, pv_om_usd_per_kwp_yr=10.0, pv_life_yr=25,
                battery_capex_usd_per_kwh=300.0, battery_power_capex_usd_per_kw=200.0,
                battery_om_usd_per_kwh_yr=5.0, battery_life_yr=12, diesel_om_usd_per_kwh=0.02,
                fuel_price_usd_per_l=0.8, discount_rate_frac=0.1, project_life_yr=2, currency_year=2025)
D1 = Design(pv_kwp=100.0, battery_kwh=0.0, battery_kw=0.0)
F1 = AnnualFlows(load_served_kwh=100000.0, fuel_l=10000.0, diesel_kwh=30000.0)


def test_constant():
    assert LCOE_TWIN_TOL_FRAC == 0.001
    assert issubclass(LcoeTwinMismatch, RuntimeError)


@pytest.mark.parametrize("rate, years, expected", [
    (0.1, 2, 0.1 * 1.21 / 0.21),
    (0.0, 10, 0.1),
    (0.08, 20, 0.08 * 1.08 ** 20 / (1.08 ** 20 - 1)),
    (0.05, 1, 1.05),
])
def test_crf(rate, years, expected):
    assert crf(rate, years) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("rate, years", [(-0.01, 10), (0.6, 10), (0.1, 0), (0.1, 61), (0.1, 2.0), (0.1, True),
                                         (math.nan, 10), (True, 10)])
def test_crf_rejects(rate, years):
    with pytest.raises(ValueError):
        crf(rate, years)


@pytest.mark.parametrize("capex, life, n, events, salvage", [
    (1000.0, 10, 20, [(10, 1000.0)], 0.0),
    (1000.0, 7, 20, [(7, 1000.0), (14, 1000.0)], 1000.0 / 7),
    (1000.0, 12, 20, [(12, 1000.0)], 1000.0 * 4 / 12),
    (1000.0, 25, 20, [], 1000.0 * 5 / 25),
    (1000.0, 20, 20, [], 0.0),
    (1000.0, 1, 3, [(1, 1000.0), (2, 1000.0)], 0.0),
])
def test_component_schedule(capex, life, n, events, salvage):
    got_events, got_salvage = component_schedule(capex, life, n)
    assert [(int(y), pytest.approx(c)) for y, c in got_events] == events
    assert got_salvage == pytest.approx(salvage)


def test_component_schedule_zero_capex():
    events, salvage = component_schedule(0.0, 7, 20)
    assert all(c == 0.0 for _, c in events) and salvage == 0.0


def test_two_year_hand_case():
    expected = (100000 + 9600 / 1.1 + (9600 - 92000) / 1.21) / (100000 / 1.1 + 100000 / 1.21)
    assert lcoe_path_a(D1, F1, C1) == pytest.approx(expected, rel=1e-9)
    assert lcoe_path_b(D1, F1, C1) == pytest.approx(expected, rel=1e-9)
    r = evaluate(D1, F1, C1, 2.68)
    assert isinstance(r, EconResult)
    assert r.lcoe_usd_per_kwh == pytest.approx(expected, rel=1e-9)
    assert r.capex_initial_usd == pytest.approx(100000.0)
    assert r.annual_cost_usd == pytest.approx(9600.0)
    assert r.fuel_cost_usd_per_yr == pytest.approx(8000.0)
    assert r.co2_t_per_yr == pytest.approx(26.8)
    assert r.npc_usd == pytest.approx(100000 - 92000 / 1.21 + 9600 / (0.1 * 1.21 / 0.21), rel=1e-9)
    assert r.twin_gap_frac < 1e-9 and r.currency_year == 2025


def test_twenty_year_case_with_battery_replacement():
    c = dataclasses.replace(C1, pv_capex_usd_per_kwp=900.0, pv_om_usd_per_kwp_yr=12.0, fuel_price_usd_per_l=0.9,
                            diesel_om_usd_per_kwh=0.025, discount_rate_frac=0.08, project_life_yr=20)
    d = Design(pv_kwp=500.0, battery_kwh=1000.0, battery_kw=250.0)
    f = AnnualFlows(load_served_kwh=2000000.0, fuel_l=200000.0, diesel_kwh=600000.0)
    annuity = (1 - 1.08 ** -20) / 0.08
    npc = 800000 + 350000 / 1.08 ** 12 - (90000 + 350000 * 4 / 12) / 1.08 ** 20 + 206000 * annuity
    expected = npc / (2000000 * annuity)
    assert lcoe_path_a(d, f, c) == pytest.approx(expected, rel=1e-9)
    assert lcoe_path_b(d, f, c) == pytest.approx(expected, rel=1e-9)
    r = evaluate(d, f, c, 2.68)
    assert r.npc_usd == pytest.approx(npc, rel=1e-9)
    assert r.capex_initial_usd == pytest.approx(800000.0)
    assert r.annual_cost_usd == pytest.approx(206000.0)


def test_zero_discount_rate():
    c = dataclasses.replace(C1, discount_rate_frac=0.0, project_life_yr=10, pv_om_usd_per_kwp_yr=20.0,
                            fuel_price_usd_per_l=1.0, diesel_om_usd_per_kwh=0.0)
    d = Design(pv_kwp=10.0, battery_kwh=0.0, battery_kw=0.0)
    f = AnnualFlows(load_served_kwh=20000.0, fuel_l=1000.0, diesel_kwh=5000.0)
    assert lcoe_path_a(d, f, c) == pytest.approx(0.08, rel=1e-12)
    assert lcoe_path_b(d, f, c) == pytest.approx(0.08, rel=1e-12)


@pytest.mark.parametrize("rate", [0.0, 0.05, 0.12])
def test_diesel_only_cost_is_fuel_plus_om_over_energy(rate):
    c = dataclasses.replace(C1, discount_rate_frac=rate, project_life_yr=20, fuel_price_usd_per_l=0.85)
    d = Design(pv_kwp=0.0, battery_kwh=0.0, battery_kw=0.0)
    f = AnnualFlows(load_served_kwh=3000000.0, fuel_l=1000000.0, diesel_kwh=3000000.0)
    r = evaluate(d, f, c, 2.68)
    assert r.lcoe_usd_per_kwh == pytest.approx(910000 / 3000000, rel=1e-12)
    assert r.capex_initial_usd == 0.0
    assert r.co2_t_per_yr == pytest.approx(2680.0)


def test_twin_gate_trips_when_one_path_drifts(monkeypatch):
    original = econ.lcoe_path_a
    monkeypatch.setattr(econ, "lcoe_path_a", lambda d, f, c: original(d, f, c) * 1.002)
    with pytest.raises(LcoeTwinMismatch):
        evaluate(D1, F1, C1, 2.68)


def test_twin_gate_passes_small_drift(monkeypatch):
    original = econ.lcoe_path_b
    monkeypatch.setattr(econ, "lcoe_path_b", lambda d, f, c: original(d, f, c) * 1.0005)
    r = evaluate(D1, F1, C1, 2.68)
    assert r.twin_gap_frac == pytest.approx(0.0005 / 1.0005, rel=1e-6)


@pytest.mark.parametrize("which, kw", [
    ("cost", {"pv_capex_usd_per_kwp": -1.0}), ("cost", {"fuel_price_usd_per_l": math.nan}),
    ("cost", {"discount_rate_frac": 0.6}), ("cost", {"discount_rate_frac": -0.1}), ("cost", {"pv_life_yr": 0}),
    ("cost", {"battery_life_yr": True}), ("cost", {"project_life_yr": 2.5}), ("cost", {"project_life_yr": 61}),
    ("cost", {"currency_year": 1990}), ("cost", {"battery_om_usd_per_kwh_yr": math.inf}),
    ("cost", {"diesel_om_usd_per_kwh": True}),
    ("design", {"pv_kwp": -1.0}), ("design", {"battery_kw": math.nan}),
    ("flows", {"load_served_kwh": 0.0}), ("flows", {"fuel_l": -5.0}), ("flows", {"diesel_kwh": math.inf}),
])
def test_rejects_bad_inputs(which, kw):
    with pytest.raises(ValueError):
        c = dataclasses.replace(C1, **kw) if which == "cost" else C1
        d = dataclasses.replace(D1, **kw) if which == "design" else D1
        f = dataclasses.replace(F1, **kw) if which == "flows" else F1
        evaluate(d, f, c, 2.68)


def test_rejects_bad_co2_factor():
    with pytest.raises(ValueError):
        evaluate(D1, F1, C1, -2.68)
    with pytest.raises(ValueError):
        evaluate(D1, F1, C1, math.nan)
