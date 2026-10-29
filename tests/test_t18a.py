"""Acceptance tests for T18a (sensitivity inputs, grid helpers, alt checks that widen the grid, tornado labels).

Written by the orchestrator. No network. Uses the small fixtures of test_sweep and the synthetic study of
test_study."""
import dataclasses
import re

import pytest

import test_study as ts
import test_sweep as tw
import autosolar.firmness as firm
import autosolar.study as study
from autosolar.firmness import diesel_size_case, duration_case, reserve_case
from autosolar.site import SENSITIVITY_LABELS, render_study_html, tornado_svg
from autosolar.sweep import (SENSITIVITY_INPUTS, cost_table, dispatch_grid, least_cost, on_grid_edge,
                             sensitivity_table, size_grid, widen_grid)

PV1, LOAD, TEMPLATE, DSL, COSTS = tw.PV1, tw.LOAD, tw.TEMPLATE, tw.DSL, tw.COSTS
NEW = ("diesel_om_usd_per_kwh", "fuel_intercept_l_per_h_per_kw_rated", "fuel_slope_l_per_kwh", "battery_duration_h")
CHEAP_PV = dataclasses.replace(COSTS, pv_capex_usd_per_kwp=150.0, fuel_price_usd_per_l=2.0)


# ---------- grid helpers ----------

def test_size_grid():
    assert size_grid(250.0, 1000.0) == [0.0, 250.0, 500.0, 750.0, 1000.0]
    assert size_grid(500, 0) == [0.0]
    assert all(isinstance(v, float) for v in size_grid(2, 4))


def test_widen_grid():
    assert max(widen_grid(size_grid(250.0, 9000.0), 250.0)) == 13500.0
    assert widen_grid([0.0, 500.0, 1000.0], 300.0) == [0.0, 300.0, 600.0, 900.0, 1200.0, 1500.0]
    assert widen_grid([0.0, 50.0, 100.0], 50.0) == [0.0, 50.0, 100.0, 150.0]


@pytest.mark.parametrize("call", [
    lambda: size_grid(0.0, 10.0), lambda: size_grid(-1.0, 10.0), lambda: size_grid(float("nan"), 10.0),
    lambda: size_grid(True, 10.0), lambda: size_grid(1.0, -1.0), lambda: size_grid(1.0, float("inf")),
    lambda: size_grid("1", 10.0), lambda: widen_grid([], 10.0), lambda: widen_grid([0.0, 10.0], 0.0),
])
def test_grid_helpers_reject(call):
    with pytest.raises(ValueError):
        call()


def test_study_grid_names_agree():
    for step, top in ((250.0, 4000.0), (500.0, 1500.0), (2000.0, 6000.0), (300.0, 1000.0)):
        assert study._size_grid(step, top) == size_grid(step, top)
        g = size_grid(step, top)
        assert study._widen_grid(g, step) == widen_grid(g, step)


# ---------- sensitivity table ----------

def test_sensitivity_inputs():
    assert SENSITIVITY_INPUTS == ("pv_capex_usd_per_kwp", "battery_capex_usd_per_kwh", "fuel_price_usd_per_l",
                                  "discount_rate_frac", "demand") + NEW


@pytest.fixture(scope="module")
def sens():
    return sensitivity_table(PV1, LOAD, tw.PV_GRID, tw.BAT_GRID, costs=COSTS, co2_kg_per_l=2.68,
                             unserved_max_frac=0.0, **tw.KW)


def test_sensitivity_has_18_rows(sens):
    assert len(sens) == 18
    assert sens.input.tolist() == [n for n in SENSITIVITY_INPUTS for _ in (0, 1)]
    assert sens.factor.tolist() == pytest.approx([0.8, 1.2] * 9)


def _expected(name, factor):
    if name == "diesel_om_usd_per_kwh":
        pts = dispatch_grid(PV1, LOAD, tw.PV_GRID, tw.BAT_GRID, **tw.KW)
        return cost_table(pts, dataclasses.replace(COSTS, diesel_om_usd_per_kwh=COSTS.diesel_om_usd_per_kwh * factor),
                          2.68)
    if name in ("fuel_intercept_l_per_h_per_kw_rated", "fuel_slope_l_per_kwh"):
        fleet = dataclasses.replace(DSL, **{name: getattr(DSL, name) * factor})
        pts = dispatch_grid(PV1, LOAD, tw.PV_GRID, tw.BAT_GRID, battery_hours=4.0, battery_template=TEMPLATE,
                            diesel=fleet)
        return cost_table(pts, COSTS, 2.68)
    assert name == "battery_duration_h"
    pts = dispatch_grid(PV1, LOAD, tw.PV_GRID, tw.BAT_GRID, battery_hours=4.0 * factor, battery_template=TEMPLATE,
                        diesel=DSL)
    return cost_table(pts, COSTS, 2.68)


def test_new_rows_match_direct_runs(sens):
    base_table = cost_table(dispatch_grid(PV1, LOAD, tw.PV_GRID, tw.BAT_GRID, **tw.KW), COSTS, 2.68)
    i_base = int(least_cost(base_table, 0.0).name)
    base = least_cost(base_table, 0.0)
    for name in NEW:
        for factor in (0.8, 1.2):
            row = sens[(sens.input == name) & (abs(sens.factor - factor) < 1e-12)].iloc[0]
            t = _expected(name, factor)
            best = least_cost(t, 0.0)
            assert row.base_design_lcoe_usd_per_kwh == pytest.approx(t.lcoe_usd_per_kwh.iloc[i_base], rel=1e-12)
            assert (row.least_cost_pv_kwp, row.least_cost_battery_kwh) == (best.pv_kwp, best.battery_kwh)
            assert row.least_cost_lcoe_usd_per_kwh == pytest.approx(best.lcoe_usd_per_kwh, rel=1e-12)
            assert bool(row.same_design) == ((best.pv_kwp, best.battery_kwh) == (base.pv_kwp, base.battery_kwh))
            assert row.note == ""


def test_new_rows_move_the_cost_the_right_way(sens):
    def pair(name):
        lo = sens[(sens.input == name) & (sens.factor < 1)].iloc[0].base_design_lcoe_usd_per_kwh
        hi = sens[(sens.input == name) & (sens.factor > 1)].iloc[0].base_design_lcoe_usd_per_kwh
        return lo, hi
    for name in ("diesel_om_usd_per_kwh", "fuel_intercept_l_per_h_per_kw_rated", "fuel_slope_l_per_kwh"):
        lo, hi = pair(name)
        assert lo < hi, name


def test_sensitivity_keeps_inputs_unchanged(sens):
    assert DSL.fuel_slope_l_per_kwh == 0.25 and DSL.fuel_intercept_l_per_h_per_kw_rated == 0.08
    assert COSTS.diesel_om_usd_per_kwh == 0.03


# ---------- alt checks widen the grid ----------

def _manual_search(fleet, hours, pv_grid, bat_grid, widen_max, costs=CHEAP_PV):
    pv_grid, bat_grid = list(pv_grid), list(bat_grid)
    pts = dispatch_grid(PV1, LOAD, pv_grid, bat_grid, battery_hours=hours, battery_template=TEMPLATE, diesel=fleet)
    tab = cost_table(pts, costs, 2.68)
    best = least_cost(tab, 0.0)
    widened = 0
    while on_grid_edge(tab, best) and widened < widen_max:
        if float(best.pv_kwp) == max(pv_grid):
            pv_grid = widen_grid(pv_grid, 50.0)
        if float(best.battery_kwh) == max(bat_grid):
            bat_grid = widen_grid(bat_grid, 100.0)
        pts = dispatch_grid(PV1, LOAD, pv_grid, bat_grid, battery_hours=hours, battery_template=TEMPLATE,
                            diesel=fleet)
        tab = cost_table(pts, costs, 2.68)
        best = least_cost(tab, 0.0)
        widened += 1
    return tab, best, pv_grid, bat_grid, widened


ALT = dict(battery_hours=4.0, battery_template=TEMPLATE, diesel=DSL, unit_kw=150.0, must_run_units=1,
           costs=CHEAP_PV, co2_kg_per_l=2.68, unserved_max_frac=0.0)


@pytest.fixture(scope="module")
def alt_wide():
    return diesel_size_case(PV1, LOAD, [0.0, 50.0, 100.0], [0.0, 100.0, 200.0], pv_step_kwp=50.0,
                            battery_step_kwh=100.0, widen_max=2, **ALT)


def test_diesel_size_case_widens(alt_wide):
    fleet = dataclasses.replace(DSL, unit_kw=150.0)
    tab, best, pv_grid, bat_grid, widened = _manual_search(fleet, 4.0, [0.0, 50.0, 100.0], [0.0, 100.0, 200.0], 2)
    assert widened >= 1, "fixture must reach the grid edge"
    assert alt_wide["widened"] == widened
    assert (alt_wide["pv_kwp"], alt_wide["battery_kwh"]) == (float(best.pv_kwp), float(best.battery_kwh))
    assert alt_wide["lcoe_usd_per_kwh"] == pytest.approx(float(best.lcoe_usd_per_kwh), rel=1e-12)
    assert alt_wide["on_grid_edge"] == bool(on_grid_edge(tab, best))
    d0 = tab[(tab.pv_kwp == 0.0) & (tab.battery_kwh == 0.0)].iloc[0]
    assert alt_wide["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(float(d0.lcoe_usd_per_kwh), rel=1e-12)
    res = reserve_case(PV1, LOAD, pv_grid, bat_grid, battery_hours=4.0, battery_template=TEMPLATE, diesel=fleet,
                       must_run_units=1, costs=CHEAP_PV, co2_kg_per_l=2.68, unserved_max_frac=0.0,
                       main_pv_kwp=float(best.pv_kwp), main_battery_kwh=float(best.battery_kwh))
    assert alt_wide["reserve_pv_kwp"] == res["pv_kwp"] and alt_wide["reserve_battery_kwh"] == res["battery_kwh"]
    assert alt_wide["reserve_lcoe_usd_per_kwh"] == pytest.approx(res["lcoe_usd_per_kwh"], rel=1e-12)
    assert alt_wide["reserve_main_design_lcoe_usd_per_kwh"] == pytest.approx(
        res["main_design_lcoe_usd_per_kwh"], rel=1e-12)


def test_diesel_size_case_default_does_not_widen():
    out = diesel_size_case(PV1, LOAD, [0.0, 50.0, 100.0], [0.0, 100.0, 200.0], **ALT)
    fleet = dataclasses.replace(DSL, unit_kw=150.0)
    tab, best, _, _, widened = _manual_search(fleet, 4.0, [0.0, 50.0, 100.0], [0.0, 100.0, 200.0], 0)
    assert widened == 0 and out["widened"] == 0
    assert (out["pv_kwp"], out["battery_kwh"]) == (float(best.pv_kwp), float(best.battery_kwh))
    assert out["on_grid_edge"] is True


def test_diesel_size_case_one_widening_only():
    out = diesel_size_case(PV1, LOAD, [0.0, 50.0, 100.0], [0.0, 100.0, 200.0], pv_step_kwp=50.0,
                           battery_step_kwh=100.0, widen_max=1, **ALT)
    fleet = dataclasses.replace(DSL, unit_kw=150.0)
    _, best, _, _, widened = _manual_search(fleet, 4.0, [0.0, 50.0, 100.0], [0.0, 100.0, 200.0], 1)
    assert out["widened"] == widened == 1
    assert (out["pv_kwp"], out["battery_kwh"]) == (float(best.pv_kwp), float(best.battery_kwh))


def test_duration_case_widens():
    kw = dict(battery_hours=2.0, battery_template=TEMPLATE, diesel=DSL, costs=CHEAP_PV, co2_kg_per_l=2.68,
              unserved_max_frac=0.0, main_lcoe_usd_per_kwh=0.3)
    out = duration_case(PV1, LOAD, [0.0, 50.0, 100.0], [0.0, 100.0, 200.0], pv_step_kwp=50.0,
                        battery_step_kwh=100.0, widen_max=2, **kw)
    tab, best, _, _, widened = _manual_search(DSL, 2.0, [0.0, 50.0, 100.0], [0.0, 100.0, 200.0], 2)
    assert widened >= 1 and out["widened"] == widened
    assert (out["pv_kwp"], out["battery_kwh"]) == (float(best.pv_kwp), float(best.battery_kwh))
    assert out["battery_kw"] == float(best.battery_kw)
    assert out["lcoe_usd_per_kwh"] == pytest.approx(float(best.lcoe_usd_per_kwh), rel=1e-12)
    assert out["change_pct"] == pytest.approx(100.0 * (float(best.lcoe_usd_per_kwh) / 0.3 - 1.0), rel=1e-12)
    assert out["on_grid_edge"] == bool(on_grid_edge(tab, best))
    plain = duration_case(PV1, LOAD, [0.0, 50.0, 100.0], [0.0, 100.0, 200.0], **kw)
    assert plain["widened"] == 0 and plain["on_grid_edge"] is True


@pytest.mark.parametrize("bad", [
    dict(widen_max=-1, pv_step_kwp=50.0, battery_step_kwh=100.0),
    dict(widen_max=True, pv_step_kwp=50.0, battery_step_kwh=100.0),
    dict(widen_max=1.0, pv_step_kwp=50.0, battery_step_kwh=100.0),
    dict(widen_max=1),
    dict(widen_max=1, pv_step_kwp=50.0),
    dict(widen_max=1, pv_step_kwp=0.0, battery_step_kwh=100.0),
    dict(widen_max=1, pv_step_kwp=50.0, battery_step_kwh=float("nan")),
])
def test_widen_arguments_rejected(bad):
    with pytest.raises(ValueError):
        diesel_size_case(PV1, LOAD, [0.0, 50.0], [0.0, 100.0], **bad, **ALT)
    kw = dict(battery_hours=2.0, battery_template=TEMPLATE, diesel=DSL, costs=CHEAP_PV, co2_kg_per_l=2.68,
              unserved_max_frac=0.0, main_lcoe_usd_per_kwh=0.3)
    with pytest.raises(ValueError):
        duration_case(PV1, LOAD, [0.0, 50.0], [0.0, 100.0], **bad, **kw)


def test_infeasible_alt_has_zero_widened():
    import pandas as pd
    flat = pd.Series(250.0, index=tw.IDX)  # 2 x 100 kW cannot serve 250 kW
    out = diesel_size_case(PV1, flat, [0.0, 50.0], [0.0, 100.0], battery_hours=4.0, battery_template=TEMPLATE,
                           diesel=DSL, unit_kw=100.0, must_run_units=1, costs=CHEAP_PV, co2_kg_per_l=2.68,
                           unserved_max_frac=0.0, pv_step_kwp=50.0, battery_step_kwh=100.0, widen_max=2)
    assert out["pv_kwp"] is None and out["widened"] == 0 and out["on_grid_edge"] is False


# ---------- study ----------

def test_report_schema_bumped():
    assert study.REPORT_SCHEMA == "autosolar.report/2"


def test_study_passes_widen_arguments(tmp_path, monkeypatch):
    seen = {}
    real_size, real_dur = study.diesel_size_case, study.duration_case

    def spy_size(*a, **k):
        seen["size"] = k
        return real_size(*a, **k)

    def spy_dur(*a, **k):
        seen["dur"] = k
        return real_dur(*a, **k)

    monkeypatch.setattr(study, "diesel_size_case", spy_size)
    monkeypatch.setattr(study, "duration_case", spy_dur)
    out = study.run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                          inputs_path=ts.small_inputs(tmp_path), runs_dir=tmp_path / "runs", run_id="t18a",
                          checks_path=ts.ROOT / "config" / "study_checks.json")
    for key in ("size", "dur"):
        k = seen[key]
        assert k["widen_max"] == 2 and k["pv_step_kwp"] == 500.0 and k["battery_step_kwh"] == 2000.0, key
    sens = out.report["sensitivity_table"]
    assert len(sens) == 18 and [x["input"] for x in sens][::2] == list(SENSITIVITY_INPUTS)


# ---------- site ----------

def test_sensitivity_labels():
    assert SENSITIVITY_LABELS == {
        "pv_capex_usd_per_kwp": "PV price",
        "battery_capex_usd_per_kwh": "Battery price",
        "fuel_price_usd_per_l": "Diesel price",
        "discount_rate_frac": "Discount rate",
        "demand": "Demand",
        "diesel_om_usd_per_kwh": "Diesel O&M",
        "fuel_intercept_l_per_h_per_kw_rated": "Diesel idle fuel",
        "fuel_slope_l_per_kwh": "Diesel fuel per kWh",
        "battery_duration_h": "Battery hours",
    }


def test_tornado_plain_labels_and_layout():
    rows = []
    for k, name in enumerate(SENSITIVITY_INPUTS + ("lonely_pair",)):
        rows.append({"input": name, "factor": 0.8, "base_design_lcoe_usd_per_kwh": 0.25 - 0.001 * (k + 1)})
        rows.append({"input": name, "factor": 1.2, "base_design_lcoe_usd_per_kwh": 0.25 + 0.001 * (k + 1)})
    svg = tornado_svg(rows, 0.25)
    assert 'width="720"' in svg.split(">", 1)[0]
    bars = re.findall(r'<g class="bar">(.*?)</g>', svg, flags=re.S)
    assert len(bars) == 10
    assert "lonely_pair: 0.240 to 0.260 USD/kWh" in bars[0]
    assert "Battery hours: 0.241 to 0.259 USD/kWh" in bars[1]
    assert "Diesel O&amp;M: 0.244 to 0.256 USD/kWh" in svg
    assert "PV price: 0.249 to 0.251 USD/kWh" in bars[-1]
    for name in SENSITIVITY_INPUTS:
        assert name not in svg
    xs = [float(x) for x in re.findall(r'<rect x="([0-9.]+)"', svg)]
    assert xs and min(xs) >= 340.0 and max(float(w) + x for x, w in zip(
        xs, re.findall(r'<rect x="[0-9.]+" y="[0-9.]+" width="([0-9.]+)"', svg))) <= 700.0 + 1e-6
    texts = re.findall(r'<text x="([0-9.]+)"[^>]*>([^<]*)</text>', svg)
    for x, t in texts:
        if " to " in t:
            assert float(x) < 20.0 and len(t) <= 52, t


def test_page_explains_the_bars():
    report, table = ts_report()
    page = render_study_html(report, table)
    sec = page.split('<section id="sensitivity">', 1)[1].split("</section>", 1)[0]
    assert "Each bar moves one input down and up by the swing in the inputs table" in sec


def ts_report():
    """A finished report from the synthetic study, cached on the function."""
    if not hasattr(ts_report, "cache"):
        import json
        import pathlib
        import tempfile
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="t18a_"))
        out = study.run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(),
                              weather_fn=ts.WeatherFn(), inputs_path=ts.small_inputs(tmp), runs_dir=tmp / "runs",
                              run_id="t18a-page")
        import pandas as pd
        report = json.loads(json.dumps(out.report))
        ts_report.cache = (report, pd.read_csv(out.run_dir / "design_table.csv"))
    return ts_report.cache
