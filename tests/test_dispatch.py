"""Acceptance tests for T07 (autosolar/dispatch.py). Written by the orchestrator. No network.

The hand worked day below was computed on paper from the rule in docs/specs/T07_dispatch.md
(eta = sqrt(0.81) = 0.9)."""
import dataclasses
import math
import time

import numpy as np
import pandas as pd
import pytest

from autosolar.dispatch import HOURLY_COLUMNS, Battery, DieselFleet, DispatchResult, dispatch

IDX24 = pd.date_range("2020-01-01", periods=24, freq="1h", tz="UTC")
BAT = Battery(energy_kwh=100.0, power_kw=50.0, round_trip_eff_frac=0.81, soc_min_frac=0.2, soc_initial_frac=0.5)
DSL = DieselFleet(unit_kw=100.0, n_units=2, min_load_frac=0.3, fuel_intercept_l_per_h_per_kw_rated=0.08,
                  fuel_slope_l_per_kwh=0.25)
NO_BAT = Battery(energy_kwh=0.0, power_kw=0.0, round_trip_eff_frac=1.0, soc_min_frac=0.0, soc_initial_frac=0.0)


def series(values, idx=IDX24):
    v = list(values) + [0.0] * (len(idx) - len(values))
    return pd.Series(v, index=idx, dtype=float)


def hand_day():
    pv = series([80, 80, 0, 0, 0, 0, 0, 0, 50])
    load = series([30, 30, 40, 120, 10, 250, 25, 33, 50])
    return dispatch(pv, load, BAT, DSL)


def test_columns_and_types():
    r = hand_day()
    assert isinstance(r, DispatchResult)
    assert HOURLY_COLUMNS == ("load_kw", "pv_kw", "pv_to_load_kw", "pv_to_battery_kw", "pv_curtailed_kw",
                              "battery_discharge_kw", "diesel_kw", "diesel_to_load_kw", "diesel_to_battery_kw",
                              "diesel_excess_kw", "diesel_units_on", "unserved_kw", "soc_kwh", "fuel_l")
    assert tuple(r.hourly.columns) == HOURLY_COLUMNS
    assert r.hourly.index.equals(IDX24)
    for c in HOURLY_COLUMNS:
        want = np.int64 if c == "diesel_units_on" else np.float64
        assert r.hourly[c].dtype == want, c
    assert isinstance(r.diesel_run_hours, int) and isinstance(r.diesel_starts, int)
    assert isinstance(r.fuel_l, float) and isinstance(r.load_kwh, float)


@pytest.mark.parametrize("col, expected", [
    ("pv_to_load_kw", [30, 30, 0, 0, 0, 0, 0, 0, 50]),
    ("pv_to_battery_kw", [50, 5.0 / 0.9, 0, 0, 0, 0, 0, 0, 0]),
    ("pv_curtailed_kw", [0, 50 - 5.0 / 0.9, 0, 0, 0, 0, 0, 0, 0]),
    ("battery_discharge_kw", [0, 0, 40, 32, 0, 16.2, 0, 3, 0]),
    ("diesel_kw", [0, 0, 0, 88, 30, 200, 30, 30, 0]),
    ("diesel_to_load_kw", [0, 0, 0, 88, 10, 200, 25, 30, 0]),
    ("diesel_to_battery_kw", [0, 0, 0, 0, 20, 0, 5, 0, 0]),
    ("diesel_excess_kw", [0] * 9),
    ("diesel_units_on", [0, 0, 0, 1, 1, 2, 1, 1, 0]),
    ("unserved_kw", [0, 0, 0, 0, 0, 33.8, 0, 0, 0]),
    ("soc_kwh", [95, 100, 100 - 40 / 0.9, 20, 38, 20, 24.5, 24.5 - 3 / 0.9, 24.5 - 3 / 0.9]),
    ("fuel_l", [0, 0, 0, 30, 15.5, 66, 15.5, 15.5, 0]),
])
def test_hand_worked_day(col, expected):
    r = hand_day()
    got = r.hourly[col].to_numpy()
    assert np.allclose(got[:9], expected, atol=1e-6), (col, got[:9])
    assert np.allclose(got[9:], got[8] if col == "soc_kwh" else 0.0, atol=1e-6)


def test_hand_worked_totals():
    r = hand_day()
    assert r.load_kwh == pytest.approx(588.0)
    assert r.unserved_kwh == pytest.approx(33.8)
    assert r.load_served_kwh == pytest.approx(554.2)
    assert r.unserved_frac == pytest.approx(33.8 / 588.0)
    assert r.pv_available_kwh == pytest.approx(210.0)
    assert r.pv_used_kwh == pytest.approx(160.0 + 5.0 / 0.9)
    assert r.pv_curtailed_kwh == pytest.approx(50 - 5.0 / 0.9)
    assert r.battery_charge_kwh == pytest.approx(75.0 + 5.0 / 0.9)
    assert r.battery_discharge_kwh == pytest.approx(91.2)
    assert r.diesel_kwh == pytest.approx(378.0)
    assert r.diesel_excess_kwh == pytest.approx(0.0)
    assert r.fuel_l == pytest.approx(142.5)
    assert r.diesel_run_hours == 5 and r.diesel_starts == 1
    assert r.soc_start_kwh == pytest.approx(50.0)
    assert r.soc_end_kwh == pytest.approx(24.5 - 3 / 0.9)
    assert r.renewable_fraction_frac == pytest.approx(1 - 378.0 / 554.2)


def test_diesel_only_min_load_and_starts():
    pv = series([])
    load = series([150, 20, 0, 0, 0, 40])
    r = dispatch(pv, load, NO_BAT, DSL)
    h = r.hourly
    assert h["diesel_kw"].tolist()[:6] == pytest.approx([150, 30, 0, 0, 0, 40])
    assert h["diesel_units_on"].tolist()[:6] == [2, 1, 0, 0, 0, 1]
    assert h["diesel_excess_kw"].tolist()[:6] == pytest.approx([0, 10, 0, 0, 0, 0])
    assert h["fuel_l"].tolist()[:6] == pytest.approx([53.5, 15.5, 0, 0, 0, 18.0])
    assert r.diesel_starts == 2 and r.diesel_run_hours == 3
    assert r.diesel_excess_kwh == pytest.approx(10.0)
    assert r.renewable_fraction_frac == pytest.approx(0.0)
    assert h["soc_kwh"].abs().max() == 0.0


def test_full_battery_min_load_and_charge_limit():
    bat = Battery(energy_kwh=100.0, power_kw=10.0, round_trip_eff_frac=0.81, soc_min_frac=0.2, soc_initial_frac=1.0)
    r = dispatch(series([]), series([15, 5, 20]), bat, DSL)
    h = r.hourly
    # hour 0: battery could give 10 but the diesel must run at 30, so it carries the whole 15 and wastes 15
    assert h["battery_discharge_kw"].tolist()[:3] == pytest.approx([0, 5, 0])
    assert h["diesel_kw"].tolist()[:3] == pytest.approx([30, 0, 30])
    assert h["diesel_to_battery_kw"].tolist()[:3] == pytest.approx([0, 0, 5 / 0.9 / 0.9])
    assert h["diesel_excess_kw"].tolist()[:3] == pytest.approx([15, 0, 10 - 5 / 0.9 / 0.9])
    assert h["soc_kwh"].tolist()[:3] == pytest.approx([100, 100 - 5 / 0.9, 100])
    assert r.diesel_starts == 2


def test_pv_charge_power_limit():
    bat = Battery(energy_kwh=1000.0, power_kw=10.0, round_trip_eff_frac=0.81, soc_min_frac=0.2, soc_initial_frac=0.5)
    r = dispatch(series([100]), series([0, 1]), bat, DSL)
    assert r.hourly["pv_to_battery_kw"].iloc[0] == pytest.approx(10.0)
    assert r.hourly["pv_curtailed_kw"].iloc[0] == pytest.approx(90.0)
    assert r.hourly["soc_kwh"].iloc[0] == pytest.approx(509.0)


def check_balances(r, bat, dsl):
    h = r.hourly
    eta = math.sqrt(bat.round_trip_eff_frac)
    tol = 1e-6
    assert np.allclose(h.pv_kw, h.pv_to_load_kw + h.pv_to_battery_kw + h.pv_curtailed_kw, atol=tol)
    assert np.allclose(h.load_kw, h.pv_to_load_kw + h.battery_discharge_kw + h.diesel_to_load_kw + h.unserved_kw,
                       atol=tol)
    assert np.allclose(h.diesel_kw, h.diesel_to_load_kw + h.diesel_to_battery_kw + h.diesel_excess_kw, atol=tol)
    prev = np.concatenate([[bat.soc_initial_frac * bat.energy_kwh], h.soc_kwh.to_numpy()[:-1]])
    charge = (h.pv_to_battery_kw + h.diesel_to_battery_kw).to_numpy()
    dis = h.battery_discharge_kw.to_numpy()
    assert np.allclose(h.soc_kwh.to_numpy(), prev + eta * charge - dis / eta, atol=tol)
    assert (h.soc_kwh >= bat.soc_min_frac * bat.energy_kwh - tol).all()
    assert (h.soc_kwh <= bat.energy_kwh + tol).all()
    assert not ((charge > tol) & (dis > tol)).any()
    assert (charge <= bat.power_kw + tol).all() and (dis <= bat.power_kw + tol).all()
    for c in HOURLY_COLUMNS:
        assert (h[c] >= -tol).all(), c
    on = h.diesel_units_on.to_numpy()
    d = h.diesel_kw.to_numpy()
    assert ((on == 0) == (d == 0)).all()
    assert (d[on > 0] >= dsl.min_load_frac * on[on > 0] * dsl.unit_kw - tol).all()
    assert (d <= on * dsl.unit_kw + tol).all() and (on <= dsl.n_units).all()
    short = h.unserved_kw.to_numpy() > tol
    assert (on[short] == dsl.n_units).all() and np.allclose(d[short], dsl.n_units * dsl.unit_kw)
    expect_fuel = on * dsl.unit_kw * dsl.fuel_intercept_l_per_h_per_kw_rated + dsl.fuel_slope_l_per_kwh * d
    assert np.allclose(h.fuel_l.to_numpy(), expect_fuel, atol=tol)
    assert r.fuel_l == pytest.approx(expect_fuel.sum())
    assert r.load_served_kwh == pytest.approx(r.load_kwh - r.unserved_kwh)
    assert r.pv_used_kwh == pytest.approx(float((h.pv_to_load_kw + h.pv_to_battery_kw).sum()))


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_balances_random_week(seed):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-03-01", periods=168, freq="1h", tz="Asia/Jakarta")
    hour = idx.hour.to_numpy()
    pv = np.clip(np.sin((hour - 6) / 12 * np.pi), 0, None) * rng.uniform(0, 400, 168)
    load = rng.uniform(20, 260, 168)
    bat = Battery(energy_kwh=float(rng.uniform(50, 600)), power_kw=float(rng.uniform(20, 200)),
                  round_trip_eff_frac=float(rng.uniform(0.7, 0.95)), soc_min_frac=0.1, soc_initial_frac=0.6)
    dsl = DieselFleet(unit_kw=100.0, n_units=2, min_load_frac=float(rng.uniform(0.2, 0.5)),
                      fuel_intercept_l_per_h_per_kw_rated=0.08, fuel_slope_l_per_kwh=0.25)
    r = dispatch(pd.Series(pv, index=idx), pd.Series(load, index=idx), bat, dsl)
    check_balances(r, bat, dsl)


def test_full_year_runs_fast():
    idx = pd.date_range("2020-01-01", periods=8784, freq="1h", tz="UTC")
    hour = idx.hour.to_numpy()
    pv = 1500 * np.clip(np.sin((hour + 7 - 6) / 12 * np.pi), 0, None)
    load = 1000 + 400 * ((hour + 7) % 24 >= 18)
    bat = Battery(energy_kwh=4000.0, power_kw=1000.0, round_trip_eff_frac=0.88, soc_min_frac=0.1, soc_initial_frac=0.5)
    dsl = DieselFleet(unit_kw=1000.0, n_units=3, min_load_frac=0.3, fuel_intercept_l_per_h_per_kw_rated=0.08,
                      fuel_slope_l_per_kwh=0.25)
    t = time.perf_counter()
    r = dispatch(pd.Series(pv, index=idx, dtype=float), pd.Series(load, index=idx, dtype=float), bat, dsl)
    assert time.perf_counter() - t < 10.0
    check_balances(r, bat, dsl)
    assert 0.0 < r.renewable_fraction_frac < 1.0 and r.unserved_kwh == 0.0


@pytest.mark.parametrize("part, kw", [
    ("battery", {"energy_kwh": -1.0}), ("battery", {"energy_kwh": math.inf}),
    ("battery", {"energy_kwh": 0.0}),  # power 50 with no energy
    ("battery", {"power_kw": -1.0}), ("battery", {"round_trip_eff_frac": 0.0}),
    ("battery", {"round_trip_eff_frac": 1.1}), ("battery", {"soc_min_frac": 1.0}),
    ("battery", {"soc_min_frac": -0.1}), ("battery", {"soc_initial_frac": 0.1}),
    ("battery", {"soc_initial_frac": 1.2}), ("battery", {"power_kw": True}),
    ("diesel", {"unit_kw": 0.0}), ("diesel", {"n_units": 0}), ("diesel", {"n_units": True}),
    ("diesel", {"n_units": 1.5}), ("diesel", {"min_load_frac": 1.0}), ("diesel", {"min_load_frac": -0.1}),
    ("diesel", {"fuel_slope_l_per_kwh": 0.0}), ("diesel", {"fuel_intercept_l_per_h_per_kw_rated": -0.1}),
    ("diesel", {"fuel_slope_l_per_kwh": math.nan}),
])
def test_rejects_bad_parameters(part, kw):
    # the check may happen when the object is built or when dispatch is called; both are inside the block
    with pytest.raises(ValueError):
        bat = dataclasses.replace(BAT, **kw) if part == "battery" else BAT
        dsl = dataclasses.replace(DSL, **kw) if part == "diesel" else DSL
        dispatch(series([10]), series([20]), bat, dsl)


@pytest.mark.parametrize("kind", ["index_mismatch", "naive", "short", "step", "nan", "negative", "zero_load",
                                  "numpy", "inf"])
def test_rejects_bad_series(kind):
    pv, load = series([10]), series([20])
    if kind == "index_mismatch":
        load = series([20], IDX24 + pd.Timedelta(hours=1))
    elif kind == "naive":
        idx = IDX24.tz_localize(None)
        pv, load = series([10], idx), series([20], idx)
    elif kind == "short":
        pv, load = pv.iloc[:23], load.iloc[:23]
    elif kind == "step":
        idx = pd.date_range("2020-01-01", periods=24, freq="2h", tz="UTC")
        pv, load = series([10], idx), series([20], idx)
    elif kind == "nan":
        pv.iloc[3] = np.nan
    elif kind == "negative":
        load.iloc[3] = -1.0
    elif kind == "zero_load":
        load = series([])
    elif kind == "numpy":
        pv = pv.to_numpy()
    elif kind == "inf":
        load.iloc[2] = np.inf
    with pytest.raises(ValueError):
        dispatch(pv, load, BAT, DSL)
