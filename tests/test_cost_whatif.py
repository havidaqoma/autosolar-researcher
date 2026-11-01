"""Acceptance tests for T25: costs the study leaves out, as what-ifs, and a year by year cash flow (post hoc).

Written by hand before the code (docs/specs/T25_cost_whatif.md). No network.
"""
import dataclasses
import json
import math
import pathlib
import shutil
import sys

import pytest

import test_sweep as tw
from autosolar.cost_whatif import (CASE_KEYS, CASES, COST_WHATIF_SCHEMA, NOTE, ROW_KEYS, apply_case, cash_flow,
                                   render_md, run_cases, summary, yearly_flows)
from autosolar.dispatch import Battery, dispatch
from autosolar.econ import AnnualFlows, CostInputs, Design, evaluate, lcoe_path_a

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import cost_whatif as tool  # noqa: E402  (tools/cost_whatif.py)

PV1, LOAD, TEMPLATE, DSL, COSTS = tw.PV1, tw.LOAD, tw.TEMPLATE, tw.DSL, tw.COSTS
D = Design(pv_kwp=100.0, battery_kwh=300.0, battery_kw=75.0)
D0 = Design(pv_kwp=0.0, battery_kwh=0.0, battery_kw=0.0)
EXAMPLE = "b4a44fc6d4c32339"
HAND = CostInputs(pv_capex_usd_per_kwp=1000.0, pv_om_usd_per_kwp_yr=10.0, pv_life_yr=25,
                  battery_capex_usd_per_kwh=300.0, battery_power_capex_usd_per_kw=100.0,
                  battery_om_usd_per_kwh_yr=5.0, battery_life_yr=12, diesel_om_usd_per_kwh=0.03,
                  fuel_price_usd_per_l=1.0, discount_rate_frac=0.08, project_life_yr=20, currency_year=2025)
HAND_D = Design(pv_kwp=100.0, battery_kwh=200.0, battery_kw=50.0)
HAND_F = AnnualFlows(load_served_kwh=1.0e6, fuel_l=1.0e5, diesel_kwh=3.0e5)

EXPECTED_CASES = [
    ("study", "As in the study", 0.0, 0, 0.0, 1.0, 0.0, 0.0),
    ("pv_degradation", "PV output falls 0.5% a year", 0.005, 0, 0.0, 1.0, 0.0, 0.0),
    ("battery_life", "Battery lasts 2 years less", 0.0, 2, 0.0, 1.0, 0.0, 0.0),
    ("grid_forming", "Grid-forming inverters: battery power price +150 USD/kW", 0.0, 0, 150.0, 1.0, 0.0, 0.0),
    ("island_capital", "Island premium: PV and battery prices +30%", 0.0, 0, 0.0, 1.3, 0.0, 0.0),
    ("solar_side", "The four above at once", 0.005, 2, 150.0, 1.3, 0.0, 0.0),
    ("diesel_overhaul", "Diesel overhauls: diesel O&M +0.02 USD/kWh", 0.0, 0, 0.0, 1.0, 0.02, 0.0),
    ("fuel_escalation", "Fuel price rises 2% a year (real)", 0.0, 0, 0.0, 1.0, 0.0, 0.02),
    ("diesel_side", "The two diesel items at once", 0.0, 0, 0.0, 1.0, 0.02, 0.02),
    ("all_six", "All six at once", 0.005, 2, 150.0, 1.3, 0.02, 0.02),
]
CASE_OUT_KEYS = ("key", "label", "main_lcoe_usd_per_kwh", "diesel_only_lcoe_usd_per_kwh", "main_npc_usd",
                 "diesel_only_npc_usd", "main_vs_diesel_pct")


def _bat(design):
    if design.battery_kwh == 0:
        return Battery(energy_kwh=0.0, power_kw=0.0, round_trip_eff_frac=TEMPLATE.round_trip_eff_frac,
                       soc_min_frac=TEMPLATE.soc_min_frac, soc_initial_frac=TEMPLATE.soc_initial_frac)
    return Battery(energy_kwh=design.battery_kwh, power_kw=design.battery_kw,
                   round_trip_eff_frac=TEMPLATE.round_trip_eff_frac, soc_min_frac=TEMPLATE.soc_min_frac,
                   soc_initial_frac=TEMPLATE.soc_initial_frac)


def _flows(result):
    return AnnualFlows(load_served_kwh=result.load_served_kwh, fuel_l=result.fuel_l, diesel_kwh=result.diesel_kwh)


# ---------- constants ----------

def test_constants():
    assert COST_WHATIF_SCHEMA == "autosolar.cost_whatif/1"
    assert CASE_KEYS == ("key", "label", "pv_degradation_frac_per_yr", "battery_life_minus_yr",
                         "battery_power_plus_usd_per_kw", "capital_mult", "diesel_om_plus_usd_per_kwh",
                         "fuel_escalation_frac_per_yr")
    assert ROW_KEYS == ("year", "capital_usd", "om_usd", "fuel_usd", "salvage_usd", "total_usd", "discounted_usd",
                        "served_kwh", "discounted_kwh")
    assert isinstance(CASES, tuple) and len(CASES) == 10
    for case, exp in zip(CASES, EXPECTED_CASES):
        assert tuple(case) == CASE_KEYS
        assert tuple(case[k] for k in CASE_KEYS) == exp
        assert isinstance(case["battery_life_minus_yr"], int) and not isinstance(case["battery_life_minus_yr"], bool)
    assert NOTE == ("Re-costs the study's least cost design with the study's own dispatch and cost functions on its "
                    "own hourly file. The design is not re-sized, so each row is a ceiling on that design's cost. "
                    "The six single changes and their sizes were fixed before the first run; the three combined "
                    "rows were added after it. Every change is assumed; every result is computed. Post hoc: none "
                    "of this is in the study.")


# ---------- apply_case ----------

def test_apply_case_study_is_unchanged():
    assert apply_case(COSTS, CASES[0]) == COSTS


def test_apply_case_solar_side():
    out = apply_case(COSTS, CASES[5])
    assert out.pv_capex_usd_per_kwp == pytest.approx(800.0 * 1.3, rel=1e-15)
    assert out.battery_capex_usd_per_kwh == pytest.approx(300.0 * 1.3, rel=1e-15)
    assert out.battery_power_capex_usd_per_kw == pytest.approx((150.0 + 150.0) * 1.3, rel=1e-15)
    assert out.battery_life_yr == 10 and isinstance(out.battery_life_yr, int)
    assert out.diesel_om_usd_per_kwh == COSTS.diesel_om_usd_per_kwh
    assert out.fuel_price_usd_per_l == COSTS.fuel_price_usd_per_l
    assert (out.pv_om_usd_per_kwp_yr, out.pv_life_yr, out.battery_om_usd_per_kwh_yr, out.discount_rate_frac,
            out.project_life_yr, out.currency_year) == (10.0, 25, 5.0, 0.08, 20, 2025)
    assert COSTS.battery_life_yr == 12 and COSTS.pv_capex_usd_per_kwp == 800.0     # input not changed


def test_apply_case_diesel_items():
    out = apply_case(COSTS, CASES[8])
    assert out.diesel_om_usd_per_kwh == pytest.approx(0.05, rel=1e-15)
    assert out.fuel_price_usd_per_l == 1.0       # escalation is applied in cash_flow, not here
    assert dataclasses.replace(out, diesel_om_usd_per_kwh=0.03) == COSTS


def test_apply_case_rejects():
    good = dict(CASES[0])
    bads = [
        dict(good, pv_degradation_frac_per_yr=1.0), dict(good, pv_degradation_frac_per_yr=-0.01),
        dict(good, pv_degradation_frac_per_yr=float("nan")), dict(good, pv_degradation_frac_per_yr=True),
        dict(good, battery_life_minus_yr=1.5), dict(good, battery_life_minus_yr=True),
        dict(good, battery_life_minus_yr=-1), dict(good, battery_life_minus_yr=12),
        dict(good, battery_power_plus_usd_per_kw=-1.0), dict(good, battery_power_plus_usd_per_kw=float("inf")),
        dict(good, capital_mult=0.0), dict(good, capital_mult=-1.0), dict(good, capital_mult=False),
        dict(good, diesel_om_plus_usd_per_kwh=-0.01), dict(good, fuel_escalation_frac_per_yr=-1.0),
        dict(good, fuel_escalation_frac_per_yr=float("nan")),
    ]
    for bad in bads:
        with pytest.raises(ValueError):
            apply_case(COSTS, bad)
    missing = dict(good)
    del missing["capital_mult"]
    with pytest.raises(ValueError):
        apply_case(COSTS, missing)
    with pytest.raises(ValueError):
        apply_case("costs", good)
    with pytest.raises(ValueError):
        apply_case(COSTS, "case")
    assert apply_case(COSTS, dict(good, battery_life_minus_yr=11)).battery_life_yr == 1


# ---------- cash_flow and summary (hand case) ----------

def test_cash_flow_hand_case():
    rows = cash_flow(HAND_D, [HAND_F] * 20, HAND)
    assert len(rows) == 21 and [r["year"] for r in rows] == list(range(21))
    for r in rows:
        assert tuple(r) == ROW_KEYS
        assert isinstance(r["year"], int)
        assert all(isinstance(r[k], float) for k in ROW_KEYS[1:])
    cap0 = 100 * 1000.0 + 200 * 300.0 + 50 * 100.0
    assert rows[0] == {"year": 0, "capital_usd": cap0, "om_usd": 0.0, "fuel_usd": 0.0, "salvage_usd": 0.0,
                       "total_usd": cap0, "discounted_usd": cap0, "served_kwh": 0.0, "discounted_kwh": 0.0}
    for r in rows[1:]:
        y = r["year"]
        assert r["capital_usd"] == (65000.0 if y == 12 else 0.0)
        assert r["om_usd"] == pytest.approx(100 * 10.0 + 200 * 5.0 + 3.0e5 * 0.03, rel=1e-12)
        assert r["fuel_usd"] == pytest.approx(1.0e5, rel=1e-12)
        salvage = -(100000.0 * 5 / 25 + 65000.0 * 4 / 12) if y == 20 else 0.0
        assert r["salvage_usd"] == pytest.approx(salvage, rel=1e-12)
        total = r["capital_usd"] + r["om_usd"] + r["fuel_usd"] + r["salvage_usd"]
        assert r["total_usd"] == pytest.approx(total, rel=1e-12)
        assert r["discounted_usd"] == pytest.approx(total / 1.08 ** y, rel=1e-12)
        assert r["served_kwh"] == 1.0e6
        assert r["discounted_kwh"] == pytest.approx(1.0e6 / 1.08 ** y, rel=1e-12)
    s = summary(rows)
    assert set(s) == {"npc_usd", "lcoe_usd_per_kwh"}
    assert s["lcoe_usd_per_kwh"] == pytest.approx(lcoe_path_a(HAND_D, HAND_F, HAND), rel=1e-12)
    assert s["npc_usd"] == pytest.approx(evaluate(HAND_D, HAND_F, HAND, 2.68).npc_usd, rel=1e-12)
    assert s["npc_usd"] == pytest.approx(sum(r["discounted_usd"] for r in rows), rel=1e-15)


def test_cash_flow_fuel_escalation_and_yearly_flows():
    flows = [AnnualFlows(load_served_kwh=1.0e6, fuel_l=1.0e5 - 1000.0 * i, diesel_kwh=3.0e5) for i in range(20)]
    rows = cash_flow(HAND_D, flows, HAND, fuel_escalation_frac_per_yr=0.02)
    assert rows[1]["fuel_usd"] == pytest.approx(1.0e5, rel=1e-12)
    for y in range(1, 21):
        assert rows[y]["fuel_usd"] == pytest.approx((1.0e5 - 1000.0 * (y - 1)) * 1.02 ** (y - 1), rel=1e-12)
    plain = cash_flow(HAND_D, flows, HAND)
    assert summary(rows)["lcoe_usd_per_kwh"] > summary(plain)["lcoe_usd_per_kwh"]


def test_cash_flow_battery_life_10_has_no_salvage():
    rows = cash_flow(HAND_D, [HAND_F] * 20, dataclasses.replace(HAND, battery_life_yr=10))
    assert [r["year"] for r in rows if r["capital_usd"] > 0] == [0, 10]
    assert rows[20]["salvage_usd"] == pytest.approx(-100000.0 * 5 / 25, rel=1e-12)


def test_cash_flow_and_summary_reject():
    with pytest.raises(ValueError):
        cash_flow(HAND_D, [HAND_F] * 19, HAND)
    with pytest.raises(ValueError):
        cash_flow(HAND_D, [HAND_F] * 19 + ["x"], HAND)
    with pytest.raises(ValueError):
        cash_flow(HAND_D, [HAND_F] * 20, HAND, fuel_escalation_frac_per_yr=-1.0)
    with pytest.raises(ValueError):
        cash_flow(HAND_D, [HAND_F] * 20, HAND, fuel_escalation_frac_per_yr=True)
    with pytest.raises(ValueError):
        cash_flow("design", [HAND_F] * 20, HAND)
    with pytest.raises(ValueError):
        cash_flow(HAND_D, [HAND_F] * 20, "costs")
    with pytest.raises(ValueError):
        summary([])
    with pytest.raises(ValueError):
        summary([{"discounted_usd": 1.0, "discounted_kwh": 0.0}])
    with pytest.raises(ValueError):
        summary("rows")


# ---------- yearly_flows ----------

def test_yearly_flows_no_degradation_repeats_one_dispatch():
    out = yearly_flows(PV1, LOAD, design=D, battery_template=TEMPLATE, diesel=DSL, project_life_yr=4,
                       pv_degradation_frac_per_yr=0.0)
    want = _flows(dispatch(PV1 * 100.0, LOAD, _bat(D), DSL))
    assert out == [want] * 4


def test_yearly_flows_with_degradation():
    out = yearly_flows(PV1, LOAD, design=D, battery_template=TEMPLATE, diesel=DSL, project_life_yr=3,
                       pv_degradation_frac_per_yr=0.1)
    assert len(out) == 3 and all(isinstance(f, AnnualFlows) for f in out)
    assert out[0] == _flows(dispatch(PV1 * 100.0, LOAD, _bat(D), DSL))
    assert out[2] == _flows(dispatch(PV1 * (100.0 * 0.9 ** 2), LOAD, _bat(D), DSL))
    assert out[2].fuel_l > out[1].fuel_l > out[0].fuel_l


def test_yearly_flows_zero_pv_and_zero_battery():
    out = yearly_flows(PV1, LOAD, design=D0, battery_template=TEMPLATE, diesel=DSL, project_life_yr=3,
                       pv_degradation_frac_per_yr=0.1)
    want = _flows(dispatch(PV1 * 0.0, LOAD, _bat(D0), DSL))
    assert out == [want] * 3


def test_yearly_flows_rejects():
    kw = dict(design=D, battery_template=TEMPLATE, diesel=DSL, project_life_yr=3, pv_degradation_frac_per_yr=0.0)
    for bad in (dict(pv_degradation_frac_per_yr=1.0), dict(pv_degradation_frac_per_yr=-0.1),
                dict(pv_degradation_frac_per_yr=True), dict(project_life_yr=0), dict(project_life_yr=True),
                dict(project_life_yr=2.0), dict(design="d"), dict(battery_template="b"), dict(diesel="x")):
        with pytest.raises(ValueError):
            yearly_flows(PV1, LOAD, **dict(kw, **bad))


# ---------- run_cases ----------

@pytest.fixture(scope="module")
def synthetic_cases():
    return run_cases(PV1, LOAD, design=D, battery_template=TEMPLATE, diesel=DSL, costs=COSTS)


def test_run_cases_shape_and_study_row(synthetic_cases):
    out = synthetic_cases
    assert [r["key"] for r in out] == [c["key"] for c in CASES]
    assert [r["label"] for r in out] == [c["label"] for c in CASES]
    for r in out:
        assert tuple(r) == CASE_OUT_KEYS
        assert r["main_vs_diesel_pct"] == pytest.approx(
            (r["main_lcoe_usd_per_kwh"] / r["diesel_only_lcoe_usd_per_kwh"] - 1) * 100, rel=1e-12)
    study = out[0]
    main = evaluate(D, _flows(dispatch(PV1 * 100.0, LOAD, _bat(D), DSL)), COSTS, 2.68)
    dies = evaluate(D0, _flows(dispatch(PV1 * 0.0, LOAD, _bat(D0), DSL)), COSTS, 2.68)
    assert study["main_lcoe_usd_per_kwh"] == pytest.approx(main.lcoe_usd_per_kwh, rel=1e-12)
    assert study["main_npc_usd"] == pytest.approx(main.npc_usd, rel=1e-12)
    assert study["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(dies.lcoe_usd_per_kwh, rel=1e-12)
    assert study["diesel_only_npc_usd"] == pytest.approx(dies.npc_usd, rel=1e-12)


def test_run_cases_directions(synthetic_cases):
    by = {r["key"]: r for r in synthetic_cases}
    base = by["study"]
    for key in ("pv_degradation", "battery_life", "grid_forming", "island_capital"):
        assert by[key]["main_lcoe_usd_per_kwh"] > base["main_lcoe_usd_per_kwh"]
        assert by[key]["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(base["diesel_only_lcoe_usd_per_kwh"],
                                                                         rel=1e-12)
    assert by["solar_side"]["main_lcoe_usd_per_kwh"] > max(
        by[k]["main_lcoe_usd_per_kwh"] for k in ("pv_degradation", "battery_life", "grid_forming", "island_capital"))
    for key in ("diesel_overhaul", "fuel_escalation"):
        assert by[key]["diesel_only_lcoe_usd_per_kwh"] > base["diesel_only_lcoe_usd_per_kwh"]
    assert by["diesel_side"]["diesel_only_lcoe_usd_per_kwh"] > max(
        by[k]["diesel_only_lcoe_usd_per_kwh"] for k in ("diesel_overhaul", "fuel_escalation"))
    assert by["all_six"]["main_lcoe_usd_per_kwh"] > by["solar_side"]["main_lcoe_usd_per_kwh"]
    assert by["all_six"]["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(
        by["diesel_side"]["diesel_only_lcoe_usd_per_kwh"], rel=1e-12)


def test_run_cases_grid_forming_matches_a_direct_cost(synthetic_cases):
    by = {r["key"]: r for r in synthetic_cases}
    f = _flows(dispatch(PV1 * 100.0, LOAD, _bat(D), DSL))
    direct = evaluate(D, f, dataclasses.replace(COSTS, battery_power_capex_usd_per_kw=300.0), 2.68)
    assert by["grid_forming"]["main_lcoe_usd_per_kwh"] == pytest.approx(direct.lcoe_usd_per_kwh, rel=1e-12)


# ---------- render_md ----------

def _doc(cases, run_hash="abc"):
    main_flows = [_flows(dispatch(PV1 * 100.0, LOAD, _bat(D), DSL))] * 20
    dies_flows = [_flows(dispatch(PV1 * 0.0, LOAD, _bat(D0), DSL))] * 20
    return {"schema": COST_WHATIF_SCHEMA, "run_hash": run_hash, "cases": cases,
            "cash_flow_main": cash_flow(D, main_flows, COSTS), "cash_flow_diesel_only": cash_flow(D0, dies_flows, COSTS)}


def _usd(x):
    return format(int(round(x)), ",d")


def test_render_md_exact(synthetic_cases):
    doc = _doc(synthetic_cases)
    md = render_md(doc)
    assert md.endswith("\n") and not md.endswith("\n\n")
    assert all(ord(ch) < 128 for ch in md) and (" -" + "- ") not in md
    lines = md[:-1].split("\n")
    head = ["# Costs the study leaves out: what if? (study abc, post hoc)", "", NOTE, "",
            "| Change (assumed) | Solar plus battery (USD/kWh) | Diesel only (USD/kWh) | Solar plus battery against "
            "diesel only |", "|---|---|---|---|"]
    assert lines[:6] == head
    for i, c in enumerate(synthetic_cases):
        assert lines[6 + i] == "| %s | %.3f | %.3f | %+.1f%% |" % (
            c["label"], c["main_lcoe_usd_per_kwh"], c["diesel_only_lcoe_usd_per_kwh"], c["main_vs_diesel_pct"])
    k = 16
    for title, rows in (("main design", doc["cash_flow_main"]), ("diesel only", doc["cash_flow_diesel_only"])):
        assert lines[k:k + 5] == ["", "## Year by year cash flow, %s (USD, computed)" % title, "",
                                  "| Year | Capital | O&M | Fuel | Salvage | Total | Discounted |",
                                  "|---|---|---|---|---|---|---|"]
        k += 5
        for r in rows:
            assert lines[k] == "| %d | %s | %s | %s | %s | %s | %s |" % (
                r["year"], _usd(r["capital_usd"]), _usd(r["om_usd"]), _usd(r["fuel_usd"]), _usd(r["salvage_usd"]),
                _usd(r["total_usd"]), _usd(r["discounted_usd"]))
            k += 1
        assert lines[k] == "| NPC | | | | | | %s |" % _usd(summary(rows)["npc_usd"])
        k += 1
    assert k == len(lines)
    assert "| 0 | 0 | 0 | 0 | 0 | 0 | 0 |" in md                 # diesel only year 0, no "-0"
    assert "| 20 | " in md and "-0 " not in md and "| -0 |" not in md


def test_render_md_rejects(synthetic_cases):
    doc = _doc(synthetic_cases)
    for bad in (dict(doc, schema="x"), dict(doc, run_hash=5)):
        with pytest.raises(ValueError):
            render_md(bad)
    for key in ("cases", "cash_flow_main", "cash_flow_diesel_only", "run_hash"):
        missing = dict(doc)
        del missing[key]
        with pytest.raises(ValueError):
            render_md(missing)
    with pytest.raises(ValueError):
        render_md("doc")


# ---------- tools/cost_whatif.py on the example study ----------

@pytest.fixture(scope="module")
def example_out(tmp_path_factory):
    out = tmp_path_factory.mktemp("posthoc")
    rc = tool.main(["--run", EXAMPLE, "--out", str(out)])
    return rc, out


def test_tool_example_study_reproduces_and_writes(example_out):
    rc, out = example_out
    assert rc == 0
    raw = (out / (EXAMPLE + "_cost_whatif.json")).read_bytes()
    assert raw.endswith(b"\n") and b"\r" not in raw and all(b < 128 for b in raw)
    doc = json.loads(raw.decode("ascii"))
    assert list(doc) == ["schema", "run_hash", "note", "inputs", "cases", "cash_flow_main", "cash_flow_diesel_only"]
    assert doc["schema"] == COST_WHATIF_SCHEMA and doc["run_hash"] == EXAMPLE and doc["note"] == NOTE
    assert doc["inputs"]["pv_kwp"] == 7250.0 and doc["inputs"]["battery_kwh"] == 19000.0
    assert doc["inputs"]["battery_kw"] == 4750.0 and doc["inputs"]["battery_life_yr"] == 12
    assert doc["inputs"]["fuel_price_usd_per_l"] == 0.848485 and doc["inputs"]["discount_rate_frac"] == 0.08
    study = doc["cases"][0]
    # the published study (docs/site/data/b4a44fc6d4c32339/report.json facts)
    assert study["main_lcoe_usd_per_kwh"] == pytest.approx(0.2511304871971075, rel=1e-9)
    assert study["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(0.3539837723163195, rel=1e-9)
    rows = doc["cash_flow_main"]
    assert summary(rows)["npc_usd"] == pytest.approx(23591477.8247731, rel=1e-9)
    assert rows[0]["capital_usd"] == pytest.approx(14287750.0, rel=1e-12)
    assert rows[12]["capital_usd"] == pytest.approx(19000 * 300.0 + 4750 * 100.0, rel=1e-12)
    assert rows[20]["salvage_usd"] == pytest.approx(-(7250 * 1119.0 * 5 / 25 + 6175000.0 * 4 / 12), rel=1e-12)
    md = (out / (EXAMPLE + "_cost_whatif.md")).read_bytes()
    assert b"\r" not in md and md.decode("ascii") == render_md(doc)


def test_tool_example_study_values_from_the_scratch_run(example_out):
    # measured before the code with a scratch script (post hoc), which used the same six sizes; 3 places
    _, out = example_out
    doc = json.loads((out / (EXAMPLE + "_cost_whatif.json")).read_text(encoding="ascii"))
    got = {c["key"]: (round(c["main_lcoe_usd_per_kwh"], 3), round(c["diesel_only_lcoe_usd_per_kwh"], 3))
           for c in doc["cases"]}
    assert got["study"] == (0.251, 0.354)
    assert got["pv_degradation"] == (0.255, 0.354)
    assert got["battery_life"] == (0.260, 0.354)
    assert got["grid_forming"] == (0.261, 0.354)
    assert got["island_capital"] == (0.302, 0.354)
    assert got["solar_side"] == (0.332, 0.354)
    assert got["diesel_overhaul"] == (0.254, 0.374)
    assert got["fuel_escalation"] == (0.259, 0.405)


@pytest.mark.parametrize("fact", ["best_lcoe_usd_per_kwh", "diesel_only_lcoe_usd_per_kwh", "best_npc_usd"])
def test_tool_refuses_when_the_study_is_not_reproduced(tmp_path, capsys, fact):
    src = ROOT / "docs" / "site" / "data" / EXAMPLE
    site = tmp_path / "site"
    data = site / "data" / EXAMPLE
    (data / "files").mkdir(parents=True)
    shutil.copyfile(src / "files" / "hourly.csv", data / "files" / "hourly.csv")
    report = json.loads((src / "report.json").read_text(encoding="utf-8"))
    report["facts"][fact]["value"] = report["facts"][fact]["value"] * 1.000001
    (data / "report.json").write_text(json.dumps(report), encoding="utf-8")
    out = tmp_path / "out"
    rc = tool.main(["--run", EXAMPLE, "--site", str(site), "--out", str(out)])
    assert rc == 1
    assert not out.exists()
    assert any(line.startswith("REPRODUCTION FAILED") for line in capsys.readouterr().out.splitlines())


def test_committed_output_matches_a_fresh_run(example_out):
    # the orchestrator runs the tool after the code and commits docs/posthoc; until then this test skips
    _, out = example_out
    committed = ROOT / "docs" / "posthoc" / (EXAMPLE + "_cost_whatif.json")
    if not committed.exists():
        pytest.skip("docs/posthoc is written by the tool after the code")
    fresh = json.loads((out / (EXAMPLE + "_cost_whatif.json")).read_text(encoding="ascii"))
    old = json.loads(committed.read_text(encoding="ascii"))
    assert list(old) == list(fresh) and old["inputs"] == fresh["inputs"]
    assert len(old["cases"]) == len(fresh["cases"]) == 10
    for a, b in zip(old["cases"], fresh["cases"]):
        assert a["key"] == b["key"]
        for k in CASE_OUT_KEYS[2:]:
            assert math.isclose(a[k], b[k], rel_tol=1e-12)
    for part in ("cash_flow_main", "cash_flow_diesel_only"):
        for a, b in zip(old[part], fresh[part]):
            for k in ROW_KEYS[1:]:
                assert math.isclose(a[k], b[k], rel_tol=1e-12, abs_tol=1e-6)
    md_old = (ROOT / "docs" / "posthoc" / (EXAMPLE + "_cost_whatif.md")).read_text(encoding="ascii")
    md_new = (out / (EXAMPLE + "_cost_whatif.md")).read_text(encoding="ascii")
    assert md_old.replace("\r\n", "\n") == md_new
