"""Acceptance tests for T11a (must run diesel units in autosolar/dispatch.py). Written by the orchestrator.

No network. The hand worked day was computed on paper from the rule in docs/specs/T11a_must_run_diesel.md
(eta = sqrt(0.81) = 0.9, d_must = 1 * 100 * 0.3 = 30 kW)."""
import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from autosolar.dispatch import HOURLY_COLUMNS, Battery, DieselFleet, dispatch
from autosolar.sweep import dispatch_grid

IDX24 = pd.date_range("2020-01-01", periods=24, freq="1h", tz="UTC")
BAT = Battery(energy_kwh=100.0, power_kw=50.0, round_trip_eff_frac=0.81, soc_min_frac=0.2, soc_initial_frac=0.5)
KW = dict(unit_kw=100.0, n_units=2, min_load_frac=0.3, fuel_intercept_l_per_h_per_kw_rated=0.08,
          fuel_slope_l_per_kwh=0.25)
DSL0 = DieselFleet(**KW)
DSL1 = DieselFleet(**KW, must_run_units=1)
DSL2 = DieselFleet(**KW, must_run_units=2)


def series(values, idx=IDX24):
    v = list(values) + [0.0] * (len(idx) - len(values))
    return pd.Series(v, index=idx, dtype=float)


def hand_day(diesel=DSL1):
    pv = series([80, 80, 0, 0, 0, 0, 0, 0, 50])
    load = series([30, 30, 40, 120, 10, 250, 25, 33, 50])
    return dispatch(pv, load, BAT, diesel)


def random_case(seed, n=600):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-01", periods=n, freq="1h", tz="UTC")
    pv = pd.Series(rng.uniform(0.0, 260.0, n) * (rng.uniform(0, 1, n) > 0.4), index=idx)
    load = pd.Series(rng.uniform(0.0, 230.0, n), index=idx)
    return pv, load


# ---------- 1. the field ----------

def test_field_is_last_with_default_zero():
    names = [f.name for f in dataclasses.fields(DieselFleet)]
    assert names[-1] == "must_run_units"
    assert names[:-1] == ["unit_kw", "n_units", "min_load_frac", "fuel_intercept_l_per_h_per_kw_rated",
                          "fuel_slope_l_per_kwh"]
    assert DSL0.must_run_units == 0
    assert DSL1.must_run_units == 1


@pytest.mark.parametrize("bad", [True, False, 1.0, 0.0, -1, 3, "1", None])
def test_bad_must_run_units_raise(bad):
    with pytest.raises(ValueError, match="must_run_units"):
        DieselFleet(**KW, must_run_units=bad)


def test_numpy_int_is_fine():
    d = DieselFleet(**KW, must_run_units=np.int64(2))
    assert int(d.must_run_units) == 2


def test_min_load_limit_only_when_units_must_run():
    hi = dict(KW, min_load_frac=0.6)
    DieselFleet(**hi)
    DieselFleet(**hi, must_run_units=0)
    with pytest.raises(ValueError, match="min_load_frac"):
        DieselFleet(**hi, must_run_units=1)
    DieselFleet(**dict(KW, min_load_frac=0.5), must_run_units=1)


# ---------- 2. m = 0 is the old rule ----------

@pytest.mark.parametrize("seed", [1, 2, 3])
def test_zero_must_run_gives_identical_floats(seed):
    pv, load = random_case(seed)
    a = dispatch(pv, load, BAT, DSL0)
    b = dispatch(pv, load, BAT, DieselFleet(**KW, must_run_units=0))
    pd.testing.assert_frame_equal(a.hourly, b.hourly, check_exact=True)
    for f in dataclasses.fields(a):
        if f.name != "hourly":
            assert getattr(a, f.name) == getattr(b, f.name), f.name


def test_zero_must_run_t07_hand_day_unchanged():
    r = hand_day(DSL0)
    assert np.allclose(r.hourly["diesel_kw"].to_numpy()[:9], [0, 0, 0, 88, 30, 200, 30, 30, 0], atol=1e-6)
    assert np.allclose(r.hourly["diesel_units_on"].to_numpy()[:9], [0, 0, 0, 1, 1, 2, 1, 1, 0])
    assert r.fuel_l == pytest.approx(30 + 15.5 + 66 + 15.5 + 15.5)


# ---------- 3. hand worked day, must_run_units = 1 ----------

SOC = [95, 100, 800 / 9, 300 / 9, 154 / 3, 20, 24.5, 127 / 6, 289 / 6, 451 / 6] + [100.0] * 14
D2B_10 = (100 - 451 / 6) / 0.9


@pytest.mark.parametrize("col, expected", [
    ("pv_to_load_kw", [0, 0, 0, 0, 0, 0, 0, 0, 20] + [0] * 15),
    ("pv_to_battery_kw", [50, 5 / 0.9, 0, 0, 0, 0, 0, 0, 30] + [0] * 15),
    ("pv_curtailed_kw", [30, 80 - 5 / 0.9, 0, 0, 0, 0, 0, 0, 0] + [0] * 15),
    ("battery_discharge_kw", [0, 0, 10, 50, 0, 28.2, 0, 3, 0] + [0] * 15),
    ("diesel_kw", [30, 30, 30, 70, 30, 200, 30, 30, 30] + [30] * 15),
    ("diesel_to_load_kw", [30, 30, 30, 70, 10, 200, 25, 30, 30] + [0] * 15),
    ("diesel_to_battery_kw", [0, 0, 0, 0, 20, 0, 5, 0, 0, 30, D2B_10] + [0] * 13),
    ("diesel_excess_kw", [0] * 9 + [0, 30 - D2B_10] + [30] * 13),
    ("diesel_units_on", [1, 1, 1, 1, 1, 2, 1, 1, 1] + [1] * 15),
    ("unserved_kw", [0, 0, 0, 0, 0, 21.8, 0, 0, 0] + [0] * 15),
    ("soc_kwh", SOC),
    ("fuel_l", [15.5, 15.5, 15.5, 25.5, 15.5, 66, 15.5, 15.5, 15.5] + [15.5] * 15),
])
def test_hand_worked_day_must_run(col, expected):
    r = hand_day()
    got = r.hourly[col].to_numpy()
    assert np.allclose(got, expected, atol=1e-6), (col, got)


def test_hand_worked_totals_must_run():
    r = hand_day()
    assert tuple(r.hourly.columns) == HOURLY_COLUMNS
    assert r.hourly["diesel_units_on"].dtype == np.int64
    assert r.load_kwh == pytest.approx(588.0)
    assert r.unserved_kwh == pytest.approx(21.8)
    assert r.load_served_kwh == pytest.approx(566.2)
    assert r.pv_available_kwh == pytest.approx(210.0)
    assert r.pv_used_kwh == pytest.approx(20 + 80 + 5 / 0.9)
    assert r.pv_curtailed_kwh == pytest.approx(110 - 5 / 0.9)
    assert r.battery_charge_kwh == pytest.approx(80 + 5 / 0.9 + 55 + D2B_10)
    assert r.battery_discharge_kwh == pytest.approx(91.2)
    assert r.diesel_kwh == pytest.approx(930.0)
    assert r.diesel_excess_kwh == pytest.approx(13 * 30 + 30 - D2B_10)
    assert r.fuel_l == pytest.approx(22 * 15.5 + 25.5 + 66)
    assert r.diesel_run_hours == 24
    assert r.diesel_starts == 1
    assert r.soc_start_kwh == pytest.approx(50.0)
    assert r.soc_end_kwh == pytest.approx(100.0)
    rf = 1.0 - (930.0 - (13 * 30 + 30 - D2B_10)) / 566.2
    assert r.renewable_fraction_frac == pytest.approx(rf)


def test_two_must_run_units_lift_the_floor():
    r = hand_day(DSL2)
    h = r.hourly
    assert (h["diesel_units_on"].to_numpy() == 2).all()
    assert np.allclose(h["diesel_kw"].to_numpy()[[0, 1, 4, 9]], 60.0)
    assert h["diesel_to_load_kw"].iloc[0] == pytest.approx(30.0)
    assert h["pv_to_load_kw"].iloc[0] == pytest.approx(0.0)
    assert h["diesel_kw"].iloc[5] == pytest.approx(200.0)
    assert r.diesel_starts == 1 and r.diesel_run_hours == 24


# ---------- 4. properties on random data ----------

@pytest.mark.parametrize("m", [1, 2])
@pytest.mark.parametrize("seed", [11, 12, 13, 14])
def test_properties_every_hour(m, seed):
    pv, load = random_case(seed)
    d = DieselFleet(**KW, must_run_units=m)
    r = dispatch(pv, load, BAT, d)
    h = r.hourly
    d_must = m * 100.0 * 0.3
    tol = 1e-6
    assert (h["diesel_units_on"] >= m).all()
    assert (h["diesel_units_on"] <= 2).all()
    assert (h["diesel_kw"] >= d_must - tol).all()
    assert (h["diesel_kw"] <= 200.0 + tol).all()
    lhs = h["pv_to_load_kw"] + h["battery_discharge_kw"] + h["diesel_to_load_kw"] + h["unserved_kw"]
    assert np.allclose(lhs, h["load_kw"], atol=tol)
    assert np.allclose(h["pv_to_load_kw"] + h["pv_to_battery_kw"] + h["pv_curtailed_kw"], h["pv_kw"], atol=tol)
    assert np.allclose(h["diesel_to_load_kw"] + h["diesel_to_battery_kw"] + h["diesel_excess_kw"], h["diesel_kw"],
                       atol=tol)
    for c in HOURLY_COLUMNS:
        assert (h[c] >= -tol).all(), c
    charge = h["pv_to_battery_kw"] + h["diesel_to_battery_kw"]
    assert not ((charge > tol) & (h["battery_discharge_kw"] > tol)).any()
    assert (charge <= 50.0 + tol).all()
    assert (h["battery_discharge_kw"] <= 50.0 + tol).all()
    assert (h["soc_kwh"] >= 20.0 - tol).all() and (h["soc_kwh"] <= 100.0 + tol).all()
    fuel = h["diesel_units_on"] * 100.0 * 0.08 + 0.25 * h["diesel_kw"]
    assert np.allclose(fuel, h["fuel_l"], atol=tol)
    soc = h["soc_kwh"].to_numpy()
    prev = np.concatenate([[50.0], soc[:-1]])
    step = charge.to_numpy() * 0.9 - h["battery_discharge_kw"].to_numpy() / 0.9
    assert np.allclose(soc, prev + step, atol=1e-6)
    assert (h["unserved_kw"] <= tol).all() or (h.loc[h["unserved_kw"] > tol, "diesel_kw"] >= 200.0 - tol).all()
    assert r.diesel_run_hours == len(h) and r.diesel_starts == 1


@pytest.mark.parametrize("seed", [21, 22])
def test_extra_units_only_when_battery_cannot_cover(seed):
    pv, load = random_case(seed)
    r = dispatch(pv, load, BAT, DSL1)
    h = r.hourly
    above = h["diesel_kw"] > 30.0 + 1e-6
    head = np.maximum(0.0, (np.concatenate([[50.0], h["soc_kwh"].to_numpy()[:-1]]) - 20.0) * 0.9)
    max_dis = np.minimum(head, 50.0)
    assert np.allclose(h.loc[above, "battery_discharge_kw"].to_numpy(), max_dis[above.to_numpy()], atol=1e-6)


def test_spare_diesel_only_when_load_below_floor():
    pv, load = random_case(31)
    h = dispatch(pv, load, BAT, DSL1).hourly
    spare = (h["diesel_to_battery_kw"] + h["diesel_excess_kw"]) > 1e-9
    assert (h.loc[spare, "load_kw"] < 30.0 + 1e-9).all()
    assert np.allclose(h.loc[spare, "diesel_to_load_kw"], h.loc[spare, "load_kw"], atol=1e-9)
    assert np.allclose(h.loc[spare, "pv_to_load_kw"], 0.0, atol=1e-9)


def test_must_run_costs_renewable_share_on_a_sunny_case():
    idx = pd.date_range("2021-06-01", periods=24 * 20, freq="1h", tz="UTC")
    hour = idx.hour.to_numpy()
    sun = np.clip(np.sin((hour - 6) / 12.0 * math.pi), 0.0, None) * 300.0
    pv = pd.Series(sun, index=idx)
    load = pd.Series(80.0 + 40.0 * (hour >= 18), index=idx, dtype=float)
    r0 = dispatch(pv, load, BAT, DSL0)
    r1 = dispatch(pv, load, BAT, DSL1)
    assert r1.renewable_fraction_frac < r0.renewable_fraction_frac
    assert r1.pv_curtailed_kwh > r0.pv_curtailed_kwh
    assert r1.fuel_l > r0.fuel_l
    assert r1.diesel_starts == 1 and r0.diesel_starts >= 1


# ---------- 5. the sweep passes the fleet through ----------

def test_dispatch_grid_uses_the_must_run_fleet():
    pv, load = random_case(41, n=200)
    per_kwp = pv / 200.0
    points = dispatch_grid(per_kwp, load, [0.0, 150.0], [0.0, 100.0], battery_hours=2.0,
                           battery_template=BAT, diesel=DSL1)
    assert len(points) == 4
    for p in points:
        assert (p.result.hourly["diesel_units_on"] >= 1).all()
    direct = dispatch(per_kwp * 150.0, load,
                      Battery(energy_kwh=100.0, power_kw=50.0, round_trip_eff_frac=0.81, soc_min_frac=0.2,
                              soc_initial_frac=0.5), DSL1)
    pd.testing.assert_frame_equal(points[3].result.hourly, direct.hourly, check_exact=True)
