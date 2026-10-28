"""Acceptance tests for T14 (diesel unit size check). Written by the orchestrator. No network.

Unit tests use the small series of test_firmness; the study runs use the synthetic weather of test_study."""
import dataclasses
import json
import math

import pytest

import test_firmness as tf
import test_study as ts
from autosolar.dispatch import Battery, DieselFleet
from autosolar.econ import CostInputs
from autosolar.firmness import (ALT_KEYS, CHECK_NAMES, DUR_KEYS, FIRM_CHECK_LABEL, FIRM_SPECS, FIRM_TITLES,
                                OPTIONAL_CHECK_NAMES, diesel_size_case, load_checks, reserve_case)
from autosolar.site import caveats
from autosolar.study import firm_items, fmt_number, load_inputs, run_study
from autosolar.sweep import cost_table, dispatch_grid, least_cost, on_grid_edge

CHECKS = tf.CHECKS
KEYS = [k for k, _, _, _ in FIRM_SPECS]
ROWS = [
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
]
TITLES = {
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
}
RESERVE_KEYS = ("reserve_main_design_lcoe_usd_per_kwh", "reserve_pv_kwp", "reserve_battery_kwh",
                "reserve_lcoe_usd_per_kwh")
RESULT_KEYS = {"unit_kw", "diesel_only_lcoe_usd_per_kwh", "pv_kwp", "battery_kwh", "lcoe_usd_per_kwh", "saving_pct",
               "on_grid_edge"} | set(RESERVE_KEYS)
PV_GRID = [0.0, 500.0, 1000.0]
B_GRID = [0.0, 1000.0, 2000.0]


def case(**kw):
    args = dict(battery_hours=4.0, battery_template=tf.BAT_T, diesel=tf.FLEET, unit_kw=450.0, must_run_units=1,
                costs=tf.costs(), co2_kg_per_l=2.68, unserved_max_frac=0.001)
    args.update(kw)
    load = args.pop("load_kw", tf.LOAD)
    pv_grid = args.pop("pv_grid", PV_GRID)
    b_grid = args.pop("battery_grid", B_GRID)
    return diesel_size_case(tf.PER_KWP, load, pv_grid, b_grid, **args)


def direct(fleet, pv_grid=PV_GRID, b_grid=B_GRID):
    return cost_table(dispatch_grid(tf.PER_KWP, tf.LOAD, pv_grid, b_grid, battery_hours=4.0,
                                    battery_template=tf.BAT_T, diesel=fleet), tf.costs(), 2.68)


def direct_reserve(fleet, pick, units=1):
    return reserve_case(tf.PER_KWP, tf.LOAD, PV_GRID, B_GRID, battery_hours=4.0, battery_template=tf.BAT_T,
                        diesel=fleet, must_run_units=units, costs=tf.costs(), co2_kg_per_l=2.68,
                        unserved_max_frac=0.001, main_pv_kwp=float(pick["pv_kwp"]),
                        main_battery_kwh=float(pick["battery_kwh"]))


# ---------- constants ----------

def test_constants():
    assert OPTIONAL_CHECK_NAMES == ("diesel_unit_kw_alt", "battery_duration_h_alt")
    assert "diesel_unit_kw_alt" not in CHECK_NAMES
    assert ALT_KEYS == tuple(r[0] for r in ROWS)
    i = KEYS.index("reference_fuel_saved_l_yr")
    assert [tuple(r) for r in FIRM_SPECS[i + 1:i + 12]] == ROWS
    assert KEYS[i + 12] == "battery_peak_discharge_kw" and KEYS[-2:] == ["sourcing_cost_usd", "total_cost_usd"]
    assert FIRM_CHECK_LABEL["alt_diesel_unit_kw"] == "diesel_unit_kw_alt"
    for key, title in TITLES.items():
        assert FIRM_TITLES[key] == title


def test_firmness_does_not_import_study():
    src = (tf.ROOT / "autosolar" / "firmness.py").read_text(encoding="utf-8")
    assert "autosolar.study" not in src and "from autosolar import study" not in src


# ---------- load_checks ----------

def test_default_checks_file_has_alt():
    values, raw = load_checks(CHECKS)
    assert type(values["diesel_unit_kw_alt"]) is float and values["diesel_unit_kw_alt"] == 2700.0
    entry = raw["values"]["diesel_unit_kw_alt"]
    assert entry["label"] == "paper" and entry["unit"] == "kW"
    assert "2 x 2.7 MW" in entry["note"] and "2 x 1.8 MW" in entry["note"]


def _write(tmp_path, fn, name="c.json"):
    raw = json.loads(CHECKS.read_text(encoding="utf-8"))
    fn(raw)
    p = tmp_path / name
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def test_load_checks_without_alt(tmp_path):
    values, raw = load_checks(_write(tmp_path, lambda r: r["values"].pop("diesel_unit_kw_alt")))
    assert set(values) == set(CHECK_NAMES) | {"battery_duration_h_alt"} and "diesel_unit_kw_alt" not in raw["values"]


def test_load_checks_alt_int_becomes_float(tmp_path):
    values, _ = load_checks(_write(tmp_path, lambda r: r["values"]["diesel_unit_kw_alt"].update(value=2700)))
    assert type(values["diesel_unit_kw_alt"]) is float and values["diesel_unit_kw_alt"] == 2700.0


@pytest.mark.parametrize("fn", [
    lambda r: r["values"]["diesel_unit_kw_alt"].update(value=0.0),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(value=-2700.0),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(value="2700"),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(value=True),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(value=None),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(value=float("inf")),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(value=float("nan")),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(label="guess"),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(unit=""),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(note=None),
    lambda r: r["values"]["diesel_unit_kw_alt"].update(source="x"),
    lambda r: r["values"].update(diesel_unit_kw_alt=2700.0),
    lambda r: r["values"].update(diesel_unit_kw_alt2={"value": 2700.0, "unit": "kW", "label": "paper", "note": ""}),
    lambda r: r["values"].pop("near_tie_frac"),
])
def test_load_checks_rejects_bad_alt(tmp_path, fn):
    with pytest.raises(ValueError):
        load_checks(_write(tmp_path, fn, "bad.json"))


# ---------- diesel_size_case on a small series ----------

def test_diesel_size_case_matches_direct_grid():
    r = case()
    assert set(r) == RESULT_KEYS
    fleet = dataclasses.replace(tf.FLEET, unit_kw=450.0)
    t = direct(fleet)
    pick = least_cost(t, 0.001)
    d0 = t[(t["pv_kwp"] == 0.0) & (t["battery_kwh"] == 0.0)].iloc[0]
    assert type(r["unit_kw"]) is float and r["unit_kw"] == 450.0
    assert r["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(float(d0["lcoe_usd_per_kwh"]), rel=1e-12)
    assert r["pv_kwp"] == float(pick["pv_kwp"]) and r["battery_kwh"] == float(pick["battery_kwh"])
    assert r["lcoe_usd_per_kwh"] == pytest.approx(float(pick["lcoe_usd_per_kwh"]), rel=1e-12)
    want = 100.0 * (1.0 - float(pick["lcoe_usd_per_kwh"]) / float(d0["lcoe_usd_per_kwh"]))
    assert r["saving_pct"] == pytest.approx(want, rel=1e-12)
    assert r["on_grid_edge"] is bool(on_grid_edge(t, pick))
    assert tf.FLEET.unit_kw == 300.0


def test_diesel_size_case_reserve_matches_direct():
    r = case()
    fleet = dataclasses.replace(tf.FLEET, unit_kw=450.0)
    pick = least_cost(direct(fleet), 0.001)
    rc = direct_reserve(fleet, pick)
    assert r["reserve_main_design_lcoe_usd_per_kwh"] == pytest.approx(rc["main_design_lcoe_usd_per_kwh"], rel=1e-12)
    for k in ("pv_kwp", "battery_kwh", "lcoe_usd_per_kwh"):
        assert rc[k] is not None
        assert r["reserve_" + k] == pytest.approx(rc[k], rel=1e-12), k
    rc_main = direct_reserve(tf.FLEET, least_cost(direct(tf.FLEET), 0.001))
    assert abs(r["reserve_main_design_lcoe_usd_per_kwh"] - rc_main["main_design_lcoe_usd_per_kwh"]) > 1e-4


def test_diesel_size_case_reserve_units_used():
    r1 = case(must_run_units=1)
    r2 = case(must_run_units=2)
    fleet = dataclasses.replace(tf.FLEET, unit_kw=450.0)
    pick = least_cost(direct(fleet), 0.001)
    rc2 = direct_reserve(fleet, pick, units=2)
    assert r2["reserve_main_design_lcoe_usd_per_kwh"] == pytest.approx(rc2["main_design_lcoe_usd_per_kwh"], rel=1e-12)
    assert r1["reserve_main_design_lcoe_usd_per_kwh"] != pytest.approx(r2["reserve_main_design_lcoe_usd_per_kwh"],
                                                                     rel=1e-6)
    assert r1["lcoe_usd_per_kwh"] == r2["lcoe_usd_per_kwh"]


def test_diesel_size_case_unit_size_matters():
    r450 = case(unit_kw=450.0)
    r300 = case(unit_kw=300.0)
    t0 = direct(tf.FLEET)
    d0 = t0[(t0["pv_kwp"] == 0.0) & (t0["battery_kwh"] == 0.0)].iloc[0]
    assert r300["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(float(d0["lcoe_usd_per_kwh"]), rel=1e-12)
    assert abs(r450["diesel_only_lcoe_usd_per_kwh"] - r300["diesel_only_lcoe_usd_per_kwh"]) > 1e-4
    assert r450["unit_kw"] == 450.0 and r300["unit_kw"] == 300.0


def test_diesel_size_case_keeps_other_fleet_fields():
    base = dataclasses.replace(tf.FLEET, must_run_units=1, min_load_frac=0.4)
    r = case(diesel=base, unit_kw=450.0)
    t = direct(dataclasses.replace(base, unit_kw=450.0))
    pick = least_cost(t, 0.001)
    assert r["lcoe_usd_per_kwh"] == pytest.approx(float(pick["lcoe_usd_per_kwh"]), rel=1e-12)
    d0 = t[(t["pv_kwp"] == 0.0) & (t["battery_kwh"] == 0.0)].iloc[0]
    assert r["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(float(d0["lcoe_usd_per_kwh"]), rel=1e-12)
    r_plain = case(unit_kw=450.0)
    assert r["lcoe_usd_per_kwh"] != pytest.approx(r_plain["lcoe_usd_per_kwh"], rel=1e-6)


@pytest.mark.parametrize("bad", [0, 0.0, -450.0, True, False, "450", None, float("nan"), float("inf")])
def test_diesel_size_case_rejects_unit(bad):
    with pytest.raises(ValueError):
        case(unit_kw=bad)


@pytest.mark.parametrize("grids", [([500.0, 1000.0], [0.0, 1000.0]), ([0.0, 500.0], [1000.0, 2000.0])])
def test_diesel_size_case_needs_diesel_only_row(grids):
    with pytest.raises(ValueError):
        case(pv_grid=grids[0], battery_grid=grids[1])


def test_diesel_size_case_no_feasible_design():
    r = case(load_kw=tf.LOAD * 10.0, pv_grid=[0.0, 500.0], battery_grid=[0.0, 1000.0])
    assert set(r) == RESULT_KEYS
    for k in ("pv_kwp", "battery_kwh", "lcoe_usd_per_kwh", "saving_pct") + RESERVE_KEYS:
        assert r[k] is None, k
    assert r["on_grid_edge"] is False
    assert isinstance(r["diesel_only_lcoe_usd_per_kwh"], float) and math.isfinite(r["diesel_only_lcoe_usd_per_kwh"])
    assert r["unit_kw"] == 450.0


# ---------- firm_items ----------

def test_firm_items_skips_alt_rows_without_check():
    craw = json.loads(CHECKS.read_text(encoding="utf-8"))
    vals = {k: 1234.5678 for k in KEYS}
    vals["land_fits"] = True
    vals["alt_on_grid_edge"] = True
    items = firm_items(vals, craw)
    assert [it["key"] for it in items] == KEYS
    by = {it["key"]: it for it in items}
    assert by["alt_on_grid_edge"]["value"] is True and by["alt_on_grid_edge"]["text"] == "yes"
    assert by["alt_diesel_unit_kw"]["label"] == "paper" and by["alt_diesel_unit_kw"]["text"] == "1,235"
    assert by["alt_saving_pct"]["text"] == "1,234.6" and by["alt_saving_pct"]["label"] == "computed"
    assert by["alt_reserve_lcoe_usd_per_kwh"]["text"] == "1,234.568"
    vals["alt_on_grid_edge"] = 0
    by = {it["key"]: it for it in firm_items(vals, craw)}
    assert by["alt_on_grid_edge"]["value"] is False and by["alt_on_grid_edge"]["text"] == "no"
    craw["values"].pop("diesel_unit_kw_alt")
    items = firm_items(vals, craw)
    assert [it["key"] for it in items] == [k for k in KEYS if k not in ALT_KEYS]


# ---------- the study runs ----------

@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("alt")
    inputs = ts.small_inputs(tmp)
    raw = json.loads(CHECKS.read_text(encoding="utf-8"))
    raw["values"].pop("diesel_unit_kw_alt")
    raw["values"].pop("battery_duration_h_alt")
    no_alt = tmp / "checks_no_alt.json"
    no_alt.write_text(json.dumps(raw), encoding="utf-8")
    with_alt = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                         inputs_path=inputs, runs_dir=tmp / "runs", run_id="alt", checks_path=CHECKS)
    without = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                        inputs_path=inputs, runs_dir=tmp / "runs", run_id="noalt", checks_path=no_alt)
    return {"alt": with_alt, "noalt": without, "inputs": inputs, "no_alt_path": no_alt}


def _items(out):
    return {it["key"]: it for it in out.report["firmness"]["items"]}


def test_alt_values_match_direct(runs):
    out = runs["alt"]
    it = _items(out)
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
    grid = out.report["grid"]
    units = int(it["reserve_units"]["value"])
    r = diesel_size_case(basis_kw, load, grid["pv_kwp"], grid["battery_kwh"],
                         battery_hours=float(values["battery_duration_h"]), battery_template=bat, diesel=fleet,
                         unit_kw=2700.0, must_run_units=units, costs=c, co2_kg_per_l=float(values["co2_kg_per_l"]),
                         unserved_max_frac=float(values["unserved_max_frac"]))
    assert it["alt_diesel_unit_kw"]["value"] == 2700.0 and it["alt_diesel_unit_kw"]["label"] == "paper"
    assert it["alt_diesel_unit_kw"]["text"] == "2,700" and it["alt_diesel_unit_kw"]["unit"] == "kW"
    for key, _, _, _ in ROWS[1:]:
        if key == "alt_on_grid_edge":
            continue
        rk = key[len("alt_"):]
        if r[rk] is None:
            assert it[key]["value"] is None, key
        else:
            assert it[key]["value"] == pytest.approx(r[rk], rel=1e-9), key
        assert it[key]["label"] == "computed"
    assert r["lcoe_usd_per_kwh"] is not None and r["reserve_main_design_lcoe_usd_per_kwh"] is not None
    assert it["alt_on_grid_edge"]["value"] is r["on_grid_edge"]
    assert it["alt_on_grid_edge"]["text"] == ("yes" if r["on_grid_edge"] else "no")
    main_diesel = out.report["facts"]["diesel_only_lcoe_usd_per_kwh"]["value"]
    assert abs(it["alt_diesel_only_lcoe_usd_per_kwh"]["value"] - main_diesel) > 1e-4


def test_alt_texts(runs):
    for key, unit, label, dec in ROWS:
        item = _items(runs["alt"])[key]
        assert item["title"] == TITLES[key] and item["unit"] == unit
        if key != "alt_on_grid_edge" and item["value"] is not None:
            assert item["text"] == fmt_number(float(item["value"]), dec), key


def test_main_answer_unchanged(runs):
    a, b = runs["alt"].report, runs["noalt"].report
    assert a["facts"] == b["facts"] and a["gates"] == b["gates"] and a["range_table"] == b["range_table"]
    assert runs["alt"].run_hash != runs["noalt"].run_hash


def test_without_alt_is_the_old_shape(runs):
    out = runs["noalt"]
    keys = [it["key"] for it in out.report["firmness"]["items"]]
    assert keys == [k for k in KEYS if k not in ALT_KEYS and k not in DUR_KEYS] and len(keys) == 42
    md = out.markdown
    block = md[md.index("## How firm is the answer\n"):md.index("## Weather sources\n")]
    assert len([x for x in block.split("\n")[1:] if x]) == 42
    assert "Diesel unit size" not in md
    assert "Battery duration check" not in md
    assert len(caveats(out.report)) == 7


def test_with_alt_markdown_and_sources(runs):
    md = runs["alt"].markdown
    block = md[md.index("## How firm is the answer\n"):md.index("## Weather sources\n")]
    assert "- Diesel unit size check: other unit rating in the sources: 2,700 kW (paper)\n" in block
    lines = [x for x in block.split("\n")[1:] if x]
    i = [x.split(":")[0] for x in lines].index("- Published design size")
    assert lines[i + 3].startswith("- Published design size: diesel fuel saved")
    assert lines[i + 4].startswith("- Diesel unit size check: other unit rating")
    assert lines[i + 14].startswith("- Diesel unit size check: reserve case LCOE")
    assert lines[i + 15].startswith("- Battery power: highest discharge")
    assert lines[i + 34].startswith("- Cost of the web search")
    note = json.loads(CHECKS.read_text(encoding="utf-8"))["values"]["diesel_unit_kw_alt"]["note"]
    assert runs["alt"].report["sources"] == runs["noalt"].report["sources"] + [
        "Check input diesel_unit_kw_alt: " + note]
    md.encode("ascii")


def test_alt_source_line_only_for_press_or_paper(tmp_path, runs):
    p = _write(tmp_path, lambda r: r["values"]["diesel_unit_kw_alt"].update(label="assumed"), "assumed.json")
    out = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                    inputs_path=runs["inputs"], runs_dir=tmp_path / "runs", run_id="assumed", checks_path=p)
    assert out.report["sources"] == runs["noalt"].report["sources"]
    assert _items(out)["alt_diesel_unit_kw"]["label"] == "assumed"


# ---------- caveats ----------

def _head(it):
    return ("Diesel unit size: with units of " + it["alt_diesel_unit_kw"]["text"] + " kW instead, diesel only costs "
            + it["alt_diesel_only_lcoe_usd_per_kwh"]["text"] + " USD/kWh")


def _mid(it):
    return (" and the least cost design is " + it["alt_pv_kwp"]["text"] + " kWp with " + it["alt_battery_kwh"]["text"]
            + " kWh at " + it["alt_lcoe_usd_per_kwh"]["text"] + " USD/kWh (" + it["alt_saving_pct"]["text"]
            + "% below diesel only); if " + it["reserve_units"]["text"] + " diesel unit(s) must run in every hour, "
            "that design would cost " + it["alt_reserve_main_design_lcoe_usd_per_kwh"]["text"] + " USD/kWh")


def test_caveats_with_alt(runs):
    r = runs["alt"].report
    it = _items(runs["alt"])
    c = caveats(r)
    assert len(c) == 8
    assert c[2] == (_head(it) + _mid(it) + " and the least cost design is " + it["alt_reserve_pv_kwp"]["text"]
                    + " kWp with " + it["alt_reserve_battery_kwh"]["text"] + " kWh at "
                    + it["alt_reserve_lcoe_usd_per_kwh"]["text"] + " USD/kWh.")
    assert c[:2] + c[3:] == caveats(runs["noalt"].report)


def _blank(report, keys):
    r = json.loads(json.dumps(report))
    for item in r["firmness"]["items"]:
        if item["key"] in keys:
            item["value"] = None
            item["text"] = "none"
    return r, {i["key"]: i for i in r["firmness"]["items"]}


def test_caveats_alt_with_no_feasible_design(runs):
    r, it = _blank(runs["alt"].report, ("alt_pv_kwp", "alt_battery_kwh", "alt_lcoe_usd_per_kwh", "alt_saving_pct",
                                         "alt_reserve_main_design_lcoe_usd_per_kwh", "alt_reserve_pv_kwp",
                                         "alt_reserve_battery_kwh", "alt_reserve_lcoe_usd_per_kwh"))
    c = caveats(r)
    assert len(c) == 8
    assert c[2] == _head(it) + " and no design in the grid meets the unserved limit."


def test_caveats_alt_with_no_feasible_reserve(runs):
    r, it = _blank(runs["alt"].report, ("alt_reserve_pv_kwp", "alt_reserve_battery_kwh", "alt_reserve_lcoe_usd_per_kwh"))
    c = caveats(r)
    assert len(c) == 8
    assert c[2] == _head(it) + _mid(it) + " and no design in the grid meets the unserved limit."
