"""Acceptance tests for T11b (autosolar/firmness.py and its use in autosolar/study.py). Written by the orchestrator.

No network. Unit tests use small hand made tables; the study run uses the synthetic weather of test_study."""
import dataclasses
import hashlib
import json
import pathlib
import re

import numpy as np
import pandas as pd
import pytest

import test_study as ts
import autosolar.firmness as firm
from autosolar.dispatch import Battery, DieselFleet
from autosolar.firmness import (CHECK_NAMES, CHECKS_SCHEMA, FIRM_CHECK_LABEL, FIRM_SPECS, FIRM_TITLES, OUT_OF_SCOPE,
                                land_check, load_checks, near_tie_band, reference_design, reserve_case, study_cost)
from autosolar.econ import CostInputs
from autosolar.study import LABELS, REPORT_SCHEMA, firm_items, fmt_number, load_inputs, render_markdown, run_study
from autosolar.sweep import cost_table, dispatch_grid, least_cost, on_grid_edge

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHECKS = ROOT / "config" / "study_checks.json"
KEYS = [k for k, _, _, _ in FIRM_SPECS]


def table(rows):
    return pd.DataFrame(rows, columns=["pv_kwp", "battery_kwh", "lcoe_usd_per_kwh", "unserved_frac"])


T1 = table([
    (0.0, 0.0, 0.350, 0.0),
    (1000.0, 0.0, 0.300, 0.0),
    (2000.0, 0.0, 0.2524, 0.0),
    (2000.0, 1000.0, 0.2510, 0.0),
    (3000.0, 1000.0, 0.2500, 0.0),
    (3000.0, 2000.0, 0.2499, 0.01),
    (4000.0, 2000.0, 0.2520, 0.0),
    (4000.0, 3000.0, 0.2600, 0.0),
])


# ---------- constants ----------

def test_constants():
    assert CHECKS_SCHEMA == "autosolar.checks/1"
    assert CHECK_NAMES == ("site_land_ha", "pv_mwdc_per_ha", "reference_pv_kwp", "diesel_must_run_units",
                           "near_tie_frac")
    assert firm.LABELS == LABELS
    assert len(OUT_OF_SCOPE) == 8 and OUT_OF_SCOPE[0].startswith("Grid stability: frequency and voltage control")
    assert OUT_OF_SCOPE[7] == "Diesel price risk beyond the sensitivity table"
    assert len(FIRM_SPECS) == 30
    assert FIRM_SPECS[0] == ("near_tie_pct", "%", "check", 1)
    assert FIRM_SPECS[12] == ("reserve_lcoe_usd_per_kwh", "USD/kWh", "computed", 3)
    assert FIRM_SPECS[20] == ("land_fits", "", "computed", 0)
    assert FIRM_SPECS[29] == ("total_cost_usd", "USD", "computed", 5)
    assert KEYS[:2] == ["near_tie_pct", "near_tie_count"] and KEYS[24] == "reference_pv_kwp"
    assert FIRM_CHECK_LABEL == {"near_tie_pct": "near_tie_frac", "reserve_units": "diesel_must_run_units",
                                "land_site_ha": "site_land_ha", "land_pv_mwdc_per_ha": "pv_mwdc_per_ha",
                                "reference_pv_kwp": "reference_pv_kwp"}
    assert {k for k, _, lab, _ in FIRM_SPECS if lab == "check"} == set(FIRM_CHECK_LABEL)
    assert all(lab in LABELS for _, _, lab, _ in FIRM_SPECS if lab != "check")
    assert set(FIRM_TITLES) == set(KEYS)
    for t in list(FIRM_TITLES.values()) + list(OUT_OF_SCOPE):
        assert not re.search(r"\d", t), t
        t.encode("ascii")
    assert FIRM_TITLES["land_fits"] == "Land: main design fits"


def test_firmness_does_not_import_study():
    src = (ROOT / "autosolar" / "firmness.py").read_text(encoding="utf-8")
    assert "autosolar.study" not in src and "from autosolar import study" not in src


# ---------- load_checks ----------

def test_load_checks_default_file():
    values, raw = load_checks(CHECKS)
    assert raw["schema"] == CHECKS_SCHEMA and set(values) == set(CHECK_NAMES)
    assert values["site_land_ha"] == 9.0 and values["pv_mwdc_per_ha"] == 0.87
    assert values["reference_pv_kwp"] == pytest.approx(3889 * 0.32)
    assert type(values["diesel_must_run_units"]) is int and values["diesel_must_run_units"] == 1
    assert values["near_tie_frac"] == 0.01
    assert raw["values"]["site_land_ha"]["label"] == "press"
    assert raw["values"]["pv_mwdc_per_ha"]["label"] == "paper"


def test_load_checks_int_becomes_float(tmp_path):
    raw = json.loads(CHECKS.read_text(encoding="utf-8"))
    raw["values"]["site_land_ha"]["value"] = 9
    p = tmp_path / "c.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    values, _ = load_checks(p)
    assert type(values["site_land_ha"]) is float and values["site_land_ha"] == 9.0


def _bad(tmp_path, fn):
    raw = json.loads(CHECKS.read_text(encoding="utf-8"))
    fn(raw)
    p = tmp_path / "bad_checks.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


@pytest.mark.parametrize("fn", [
    lambda r: r.update(schema="autosolar.checks/2"),
    lambda r: r.update(values=[]),
    lambda r: r["values"].pop("near_tie_frac"),
    lambda r: r["values"].update(extra={"value": 1.0, "unit": "x", "label": "assumed", "note": ""}),
    lambda r: r["values"]["site_land_ha"].update(label="guess"),
    lambda r: r["values"]["site_land_ha"].update(unit=""),
    lambda r: r["values"]["site_land_ha"].update(note=None),
    lambda r: r["values"]["site_land_ha"].update(source="x"),
    lambda r: r["values"]["site_land_ha"].update(value="9"),
    lambda r: r["values"]["site_land_ha"].update(value=True),
    lambda r: r["values"]["site_land_ha"].update(value=0.0),
    lambda r: r["values"]["pv_mwdc_per_ha"].update(value=-0.87),
    lambda r: r["values"]["reference_pv_kwp"].update(value=float("inf")),
    lambda r: r["values"]["diesel_must_run_units"].update(value=1.0),
    lambda r: r["values"]["diesel_must_run_units"].update(value=True),
    lambda r: r["values"]["diesel_must_run_units"].update(value=0),
    lambda r: r["values"]["near_tie_frac"].update(value=0.25),
    lambda r: r["values"]["near_tie_frac"].update(value=0.0),
])
def test_load_checks_rejects(tmp_path, fn):
    with pytest.raises(ValueError):
        load_checks(_bad(tmp_path, fn))


def test_load_checks_rejects_non_dict(tmp_path):
    p = tmp_path / "list.json"
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_checks(p)


# ---------- near_tie_band ----------

def test_near_tie_band_hand_table():
    b = near_tie_band(T1, 0.001, 0.01)
    # feasible least LCOE 0.2500 (the 0.2499 row is not feasible); limit 0.2525
    assert b == {"count": 4, "pv_kwp_min": 2000.0, "pv_kwp_max": 4000.0, "battery_kwh_min": 0.0,
                 "battery_kwh_max": 2000.0, "lcoe_max_usd_per_kwh": 0.2524}
    for k in ("pv_kwp_min", "pv_kwp_max", "battery_kwh_min", "battery_kwh_max", "lcoe_max_usd_per_kwh"):
        assert type(b[k]) is float
    assert type(b["count"]) is int


def test_near_tie_band_tighter_and_looser():
    b = near_tie_band(T1, 0.001, 0.005)
    assert b["count"] == 2 and b["pv_kwp_min"] == 2000.0 and b["battery_kwh_min"] == 1000.0
    assert b["pv_kwp_max"] == 3000.0 and b["lcoe_max_usd_per_kwh"] == 0.251
    b = near_tie_band(T1, 0.02, 0.0001)
    assert b["count"] == 1 and b["pv_kwp_min"] == 3000.0 and b["battery_kwh_max"] == 2000.0


def test_near_tie_band_no_feasible():
    with pytest.raises(ValueError):
        near_tie_band(T1.assign(unserved_frac=0.5), 0.001, 0.01)


# ---------- land_check ----------

def test_land_check_fits():
    r = land_check(T1, 0.001, 3000.0, 9.0, 0.87)
    assert r["need_ha"] == pytest.approx(3000.0 / 870.0)
    assert r["max_pv_kwp"] == pytest.approx(7830.0)
    assert r["fits"] is True
    assert (r["pv_kwp"], r["battery_kwh"], r["lcoe_usd_per_kwh"]) == (3000.0, 1000.0, 0.25)


def test_land_check_does_not_fit():
    r = land_check(T1, 0.001, 3000.0, 2.5, 1.0)
    assert r["max_pv_kwp"] == pytest.approx(2500.0) and r["fits"] is False
    assert r["need_ha"] == pytest.approx(3.0)
    assert (r["pv_kwp"], r["battery_kwh"], r["lcoe_usd_per_kwh"]) == (2000.0, 1000.0, 0.251)


def test_land_check_exact_edge_fits():
    r = land_check(T1, 0.001, 3000.0, 3.0, 1.0)
    assert r["fits"] is True and r["pv_kwp"] == 3000.0


def test_land_check_nothing_within():
    t = T1[T1["pv_kwp"] >= 1000.0]
    r = land_check(t, 0.001, 3000.0, 0.5, 1.0)
    assert r["fits"] is False and r["pv_kwp"] is None and r["battery_kwh"] is None and r["lcoe_usd_per_kwh"] is None
    r = land_check(T1.assign(unserved_frac=0.5), 0.001, 3000.0, 9.0, 1.0)
    assert r["fits"] is True and r["pv_kwp"] is None


# ---------- reserve_case and reference_design on a small series ----------

IDX = pd.date_range("2021-01-01", periods=24 * 365, freq="1h", tz="UTC")
_H = IDX.hour.to_numpy()
PER_KWP = pd.Series(np.clip(np.sin((_H - 6) / 12.0 * np.pi), 0.0, None) * 0.8, index=IDX)
LOAD = pd.Series(300.0 + 150.0 * (_H >= 18), index=IDX, dtype=float)
BAT_T = Battery(energy_kwh=1.0, power_kw=1.0, round_trip_eff_frac=0.9, soc_min_frac=0.1, soc_initial_frac=0.5)
FLEET = DieselFleet(unit_kw=300.0, n_units=2, min_load_frac=0.3, fuel_intercept_l_per_h_per_kw_rated=0.08,
                    fuel_slope_l_per_kwh=0.25)


def costs():
    values, _ = load_inputs(ts.DEFAULT_INPUTS)
    return CostInputs(**{f.name: values[f.name] for f in dataclasses.fields(CostInputs)})


def test_reserve_case_matches_direct_grid():
    c = costs()
    pv_grid, b_grid = [0.0, 500.0, 1000.0], [0.0, 1000.0, 2000.0]
    r = reserve_case(PER_KWP, LOAD, pv_grid, b_grid, battery_hours=4.0, battery_template=BAT_T, diesel=FLEET,
                     must_run_units=1, costs=c, co2_kg_per_l=2.68, unserved_max_frac=0.001, main_pv_kwp=1000.0,
                     main_battery_kwh=1000.0)
    assert FLEET.must_run_units == 0
    fleet1 = dataclasses.replace(FLEET, must_run_units=1)
    t = cost_table(dispatch_grid(PER_KWP, LOAD, pv_grid, b_grid, battery_hours=4.0, battery_template=BAT_T,
                                 diesel=fleet1), c, 2.68)
    pick = least_cost(t, 0.001)
    main = t[(t["pv_kwp"] == 1000.0) & (t["battery_kwh"] == 1000.0)].iloc[0]
    assert r["units"] == 1 and type(r["units"]) is int
    assert r["pv_kwp"] == float(pick["pv_kwp"]) and r["battery_kwh"] == float(pick["battery_kwh"])
    assert r["lcoe_usd_per_kwh"] == pytest.approx(float(pick["lcoe_usd_per_kwh"]), rel=1e-12)
    assert r["renewable_pct"] == pytest.approx(100.0 * float(pick["renewable_fraction_frac"]), rel=1e-12)
    assert r["fuel_l_yr"] == pytest.approx(float(pick["fuel_l_per_yr"]), rel=1e-12)
    assert r["main_design_lcoe_usd_per_kwh"] == pytest.approx(float(main["lcoe_usd_per_kwh"]), rel=1e-12)
    assert r["on_grid_edge"] is on_grid_edge(t, pick)
    t0 = cost_table(dispatch_grid(PER_KWP, LOAD, pv_grid, b_grid, battery_hours=4.0, battery_template=BAT_T,
                                  diesel=FLEET), c, 2.68)
    main0 = t0[(t0["pv_kwp"] == 1000.0) & (t0["battery_kwh"] == 1000.0)].iloc[0]
    assert r["main_design_lcoe_usd_per_kwh"] > float(main0["lcoe_usd_per_kwh"])
    assert r["pv_kwp"] > 0.0 and 1.0 < r["renewable_pct"] < 100.0


def test_reserve_case_two_units_and_missing_main():
    c = costs()
    r2 = reserve_case(PER_KWP, LOAD, [0.0, 1000.0], [0.0, 1000.0], battery_hours=4.0, battery_template=BAT_T,
                      diesel=FLEET, must_run_units=2, costs=c, co2_kg_per_l=2.68, unserved_max_frac=0.001,
                      main_pv_kwp=0.0, main_battery_kwh=0.0)
    assert r2["units"] == 2
    with pytest.raises(ValueError):
        reserve_case(PER_KWP, LOAD, [0.0, 1000.0], [0.0, 1000.0], battery_hours=4.0, battery_template=BAT_T,
                     diesel=FLEET, must_run_units=1, costs=c, co2_kg_per_l=2.68, unserved_max_frac=0.001,
                     main_pv_kwp=750.0, main_battery_kwh=0.0)


def test_reserve_case_no_feasible_design():
    c = costs()
    big = LOAD * 10.0
    r = reserve_case(PER_KWP, big, [0.0, 500.0], [0.0, 1000.0], battery_hours=4.0, battery_template=BAT_T,
                     diesel=FLEET, must_run_units=1, costs=c, co2_kg_per_l=2.68, unserved_max_frac=0.001,
                     main_pv_kwp=500.0, main_battery_kwh=1000.0)
    for k in ("pv_kwp", "battery_kwh", "lcoe_usd_per_kwh", "renewable_pct", "fuel_l_yr"):
        assert r[k] is None, k
    assert r["on_grid_edge"] is False and r["main_design_lcoe_usd_per_kwh"] is not None


def test_reference_design_matches_direct():
    c = costs()
    r = reference_design(PER_KWP, LOAD, 1244.48, battery_hours=4.0, battery_template=BAT_T, diesel=FLEET, costs=c,
                         co2_kg_per_l=2.68)
    t = cost_table(dispatch_grid(PER_KWP, LOAD, [0.0, 1244.48], [0.0], battery_hours=4.0, battery_template=BAT_T,
                                 diesel=FLEET), c, 2.68)
    assert r["pv_kwp"] == 1244.48
    assert r["lcoe_usd_per_kwh"] == pytest.approx(float(t.iloc[1]["lcoe_usd_per_kwh"]), rel=1e-12)
    assert r["renewable_pct"] == pytest.approx(100.0 * float(t.iloc[1]["renewable_fraction_frac"]), rel=1e-12)
    assert r["fuel_l_yr"] == pytest.approx(float(t.iloc[1]["fuel_l_per_yr"]), rel=1e-12)
    assert r["fuel_saved_l_yr"] == pytest.approx(float(t.iloc[0]["fuel_l_per_yr"] - t.iloc[1]["fuel_l_per_yr"]),
                                                 rel=1e-12)
    assert r["unserved_frac"] == pytest.approx(float(t.iloc[1]["unserved_frac"]), abs=1e-15)
    assert r["fuel_saved_l_yr"] > 0.0


@pytest.mark.parametrize("bad", [0.0, -5.0, True, "1000", None])
def test_reference_design_rejects(bad):
    with pytest.raises(ValueError):
        reference_design(PER_KWP, LOAD, bad, battery_hours=4.0, battery_template=BAT_T, diesel=FLEET, costs=costs(),
                         co2_kg_per_l=2.68)


# ---------- study_cost ----------

class Row:
    def __init__(self, c):
        self.search_cost_usd = c


def test_study_cost():
    assert study_cost(0.00013, None) == {"sourcing_cost_usd": 0.0, "total_cost_usd": 0.00013}
    r = study_cost(0.00013, [Row(0.1), Row(0.0), Row(0.144685)])
    assert r["sourcing_cost_usd"] == pytest.approx(0.244685)
    assert r["total_cost_usd"] == pytest.approx(0.244815)


# ---------- the study run with checks ----------

@pytest.fixture(scope="module")
def firm_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("firm")
    inputs = ts.small_inputs(tmp)
    plain = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                      inputs_path=inputs, runs_dir=tmp / "runs", run_id="plain")
    checked = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                        inputs_path=inputs, runs_dir=tmp / "runs", run_id="checked", checks_path=CHECKS)
    return {"plain": plain, "checked": checked, "tmp": tmp, "inputs": inputs}


def test_plain_run_unchanged(firm_run):
    out = firm_run["plain"]
    assert out.report["firmness"] is None
    assert "## How firm is the answer" not in out.markdown and "## Not covered by this study" not in out.markdown
    raw = json.loads((out.run_dir / "inputs.json").read_text(encoding="utf-8"))
    blob = json.dumps({"schema": REPORT_SCHEMA, "weather_coords_deg": [-5.88, 110.43], "inputs": raw},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    assert out.run_hash == hashlib.sha256(blob).hexdigest()[:16]


def test_checked_run_hash(firm_run):
    out = firm_run["checked"]
    raw = json.loads((out.run_dir / "inputs.json").read_text(encoding="utf-8"))
    craw = json.loads(CHECKS.read_text(encoding="utf-8"))
    blob = json.dumps({"schema": REPORT_SCHEMA, "weather_coords_deg": [-5.88, 110.43], "inputs": raw,
                       "checks": craw}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    assert out.run_hash == hashlib.sha256(blob).hexdigest()[:16]
    assert out.run_hash != firm_run["plain"].run_hash
    assert out.reused is False


def test_checked_run_keeps_main_answer(firm_run):
    a, b = firm_run["plain"].report, firm_run["checked"].report
    assert a["facts"] == b["facts"] and a["gates"] == b["gates"] and a["range_table"] == b["range_table"]


def _items(out):
    return {it["key"]: it for it in out.report["firmness"]["items"]}


def test_items_shape(firm_run):
    f = firm_run["checked"].report["firmness"]
    assert set(f) == {"items", "out_of_scope", "checks"}
    assert [it["key"] for it in f["items"]] == KEYS
    assert f["out_of_scope"] == list(OUT_OF_SCOPE)
    assert f["checks"] == json.loads(CHECKS.read_text(encoding="utf-8"))
    craw = f["checks"]["values"]
    for (key, unit, label, dec), it in zip(FIRM_SPECS, f["items"]):
        assert set(it) == {"key", "title", "value", "unit", "label", "text"}
        assert it["title"] == FIRM_TITLES[key] and it["unit"] == unit
        want = craw[FIRM_CHECK_LABEL[key]]["label"] if label == "check" else label
        assert it["label"] == want, key
        if key == "land_fits":
            assert it["value"] in (True, False) and it["text"] == ("yes" if it["value"] else "no")
        elif it["value"] is None:
            assert it["text"] == "none"
        else:
            assert it["text"] == fmt_number(float(it["value"]), dec), key


def test_item_values(firm_run):
    out = firm_run["checked"]
    it = _items(out)
    t = pd.read_csv(out.run_dir / "design_table.csv")
    values, _ = load_inputs(firm_run["inputs"])
    unserved = float(values["unserved_max_frac"])
    best = least_cost(t, unserved)
    band = near_tie_band(t, unserved, 0.01)
    assert it["near_tie_pct"]["value"] == pytest.approx(1.0)
    assert it["near_tie_count"]["value"] == band["count"]
    assert it["near_tie_pv_kwp_min"]["value"] == band["pv_kwp_min"]
    assert it["near_tie_pv_kwp_max"]["value"] == band["pv_kwp_max"]
    assert it["near_tie_battery_kwh_min"]["value"] == band["battery_kwh_min"]
    assert it["near_tie_battery_kwh_max"]["value"] == band["battery_kwh_max"]
    assert it["best_diesel_run_hours"]["value"] == float(best["diesel_run_hours"])
    assert it["best_diesel_starts"]["value"] == float(best["diesel_starts"])
    assert it["best_no_diesel_hours"]["value"] == 8784 - float(best["diesel_run_hours"])
    land = land_check(t, unserved, float(best["pv_kwp"]), 9.0, 0.87)
    assert it["land_site_ha"]["value"] == 9.0 and it["land_site_ha"]["label"] == "press"
    assert it["land_pv_mwdc_per_ha"]["value"] == 0.87 and it["land_pv_mwdc_per_ha"]["label"] == "paper"
    assert it["land_need_ha"]["value"] == pytest.approx(land["need_ha"])
    assert it["land_max_pv_kwp"]["value"] == pytest.approx(7830.0)
    assert it["land_fits"]["value"] is land["fits"]
    assert it["land_pv_kwp"]["value"] == land["pv_kwp"]
    assert it["reserve_units"]["value"] == 1 and it["reserve_units"]["label"] == "assumed"
    assert it["reference_pv_kwp"]["value"] == pytest.approx(1244.48) and it["reference_pv_kwp"]["label"] == "paper"
    assert it["sourcing_cost_usd"]["value"] == 0.0
    api = out.report["facts"]["api_cost_usd"]["value"]
    assert it["total_cost_usd"]["value"] == pytest.approx(api)


def test_reserve_and_reference_values(firm_run):
    out = firm_run["checked"]
    it = _items(out)
    values, _ = load_inputs(firm_run["inputs"])
    w = ts.synthetic_weather(-5.88, 110.43)
    from autosolar.pv import PVDesign, simulate_pv
    from autosolar.demand import build_demand_cases
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
    grid = out.report["grid"]
    facts = out.report["facts"]
    r = reserve_case(basis_kw, load, grid["pv_kwp"], grid["battery_kwh"],
                     battery_hours=float(values["battery_duration_h"]), battery_template=bat, diesel=fleet,
                     must_run_units=1, costs=c, co2_kg_per_l=float(values["co2_kg_per_l"]),
                     unserved_max_frac=float(values["unserved_max_frac"]),
                     main_pv_kwp=facts["best_pv_kwp"]["value"], main_battery_kwh=facts["best_battery_kwh"]["value"])
    for key, rk in (("reserve_pv_kwp", "pv_kwp"), ("reserve_battery_kwh", "battery_kwh"),
                    ("reserve_lcoe_usd_per_kwh", "lcoe_usd_per_kwh"), ("reserve_renewable_pct", "renewable_pct"),
                    ("reserve_fuel_l_yr", "fuel_l_yr"),
                    ("reserve_main_design_lcoe_usd_per_kwh", "main_design_lcoe_usd_per_kwh")):
        if r[rk] is None:
            assert it[key]["value"] is None
        else:
            assert it[key]["value"] == pytest.approx(r[rk], rel=1e-9), key
    ref = reference_design(basis_kw, load, 1244.48, battery_hours=float(values["battery_duration_h"]),
                           battery_template=bat, diesel=fleet, costs=c, co2_kg_per_l=float(values["co2_kg_per_l"]))
    assert it["reference_lcoe_usd_per_kwh"]["value"] == pytest.approx(ref["lcoe_usd_per_kwh"], rel=1e-9)
    assert it["reference_renewable_pct"]["value"] == pytest.approx(ref["renewable_pct"], rel=1e-9)
    assert it["reference_fuel_saved_l_yr"]["value"] == pytest.approx(ref["fuel_saved_l_yr"], rel=1e-9)
    assert it["reserve_main_design_lcoe_usd_per_kwh"]["value"] >= facts["best_lcoe_usd_per_kwh"]["value"] - 1e-12


def test_sources_gain_check_lines(firm_run):
    src = firm_run["checked"].report["sources"]
    plain = firm_run["plain"].report["sources"]
    craw = json.loads(CHECKS.read_text(encoding="utf-8"))["values"]
    extra = ["Check input " + n + ": " + craw[n]["note"] for n in CHECK_NAMES if craw[n]["label"] in ("press", "paper")]
    assert len(extra) == 3
    assert src == plain + extra


def test_markdown_sections(firm_run):
    out = firm_run["checked"]
    md = out.markdown
    heads = ["## Answer", "## How firm is the answer", "## Weather sources", "## Range of the answer",
             "## Sensitivity", "## Checks", "## Inputs", "## Not covered by this study", "## Sources"]
    pos = [md.index(h + "\n") for h in heads]
    assert pos == sorted(pos)
    block = md[md.index("## How firm is the answer\n"):md.index("## Weather sources\n")]
    lines = [x for x in block.split("\n")[1:] if x]
    assert len(lines) == 30
    for line, item in zip(lines, out.report["firmness"]["items"]):
        if item["unit"] == "":
            assert line == "- " + item["title"] + ": " + item["text"] + " (" + item["label"] + ")"
        else:
            assert line == "- " + item["title"] + ": " + item["text"] + " " + item["unit"] + " (" + item["label"] + ")"
    assert block.startswith("## How firm is the answer\n\n- Near tie: share above the least LCOE")
    nb = md[md.index("## Not covered by this study\n"):md.index("## Sources\n")]
    assert nb == "## Not covered by this study\n\n" + "".join("- " + x + "\n" for x in OUT_OF_SCOPE) + "\n"
    assert render_markdown(out.report) == md
    md.encode("ascii")


def test_render_without_firmness_key_is_old_output(firm_run):
    rep = json.loads(json.dumps(firm_run["checked"].report))
    rep.pop("firmness")
    md_a = render_markdown(rep)
    rep["firmness"] = None
    assert render_markdown(rep) == md_a
    assert "## How firm is the answer" not in md_a


def test_bad_checks_raise_before_any_call(tmp_path):
    client, get, wfn = ts.FakeClient(), ts.FakeGet(), ts.WeatherFn()
    bad = _bad(tmp_path, lambda r: r["values"].pop("site_land_ha"))
    with pytest.raises(ValueError):
        run_study(ts.QUESTION, client=client, http_get=get, weather_fn=wfn, inputs_path=ts.small_inputs(tmp_path),
                  runs_dir=tmp_path / "runs", run_id="bad", checks_path=bad)
    assert client.calls == 0 and get.calls == 0 and wfn.calls == []


def test_checked_rerun_reuses(firm_run):
    def no_weather(lat, lon):
        raise AssertionError("weather must not be fetched again")
    out = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=no_weather,
                    inputs_path=firm_run["inputs"], runs_dir=firm_run["tmp"] / "runs", run_id="again",
                    checks_path=CHECKS)
    assert out.reused is True and out.run_hash == firm_run["checked"].run_hash
    assert out.markdown == firm_run["checked"].markdown


def test_firm_items_texts():
    craw = json.loads(CHECKS.read_text(encoding="utf-8"))
    vals = {k: 1234.5678 for k in KEYS}
    vals["land_fits"] = False
    vals["reserve_pv_kwp"] = None
    vals["land_lcoe_usd_per_kwh"] = None
    vals["near_tie_count"] = 3
    items = firm_items(vals, craw)
    assert [it["key"] for it in items] == KEYS
    by = {it["key"]: it for it in items}
    assert by["land_fits"]["text"] == "no" and by["land_fits"]["value"] is False
    assert by["reserve_pv_kwp"]["text"] == "none" and by["reserve_pv_kwp"]["value"] is None
    assert by["land_lcoe_usd_per_kwh"]["text"] == "none"
    assert by["near_tie_count"]["text"] == "3" and by["near_tie_count"]["value"] == 3
    assert by["near_tie_pct"]["text"] == "1,234.6" and by["near_tie_pct"]["label"] == "assumed"
    assert by["reserve_lcoe_usd_per_kwh"]["text"] == "1,234.568"
    assert by["total_cost_usd"]["text"] == "1,234.56780"
    assert by["land_site_ha"]["label"] == "press" and by["reference_pv_kwp"]["label"] == "paper"
    vals["land_fits"] = True
    assert {it["key"]: it for it in firm_items(vals, craw)}["land_fits"]["text"] == "yes"
