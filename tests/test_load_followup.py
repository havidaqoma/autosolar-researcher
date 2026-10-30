"""Acceptance tests for T20 (the study at the load the paper's chart implies, as a post hoc follow-up).

Written by the orchestrator before the code. No network. Uses the small fixtures of test_sweep and the committed
data of the pre-registered study page (docs/site/data/b4a44fc6d4c32339)."""
import copy
import json
import math
import pathlib
import sys

import pandas as pd
import pytest

import test_sweep as tw
from autosolar.load_followup import (LOAD_FOLLOWUP_SCHEMA, NOTE, REL_TOL, check_reproduction, followup_cases,
                                     followup_doc, load_followup)
from autosolar.site import render_study_html
from autosolar.sweep import cost_table, dispatch_grid, least_cost
from autosolar.weather import WeatherFetchers, build_weather_cases, cached_fetchers

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import load_followup as tool  # noqa: E402  (tools/load_followup.py)

PV1, LOAD, TEMPLATE, DSL, COSTS = tw.PV1, tw.LOAD, tw.TEMPLATE, tw.DSL, tw.COSTS
PV_GRID = [0.0, 50.0, 100.0]
BAT_GRID = [0.0, 100.0, 300.0]
KW = dict(battery_hours=4.0, battery_template=TEMPLATE, diesel=DSL, costs=COSTS, co2_kg_per_l=2.68)
DATA = ROOT / "docs" / "site" / "data" / "b4a44fc6d4c32339"
REPORT = json.loads((DATA / "report.json").read_text(encoding="ascii"))
FIG = json.loads((DATA / "figure_check.json").read_text(encoding="ascii"))
TABLE = pd.read_csv(DATA / "design_table.csv")
ROW_KEYS = {"scale_frac", "demand_kwh_yr", "diesel_only_lcoe_usd_per_kwh", "diesel_only_unserved_frac", "best_pv_kwp",
            "best_battery_kwh", "best_lcoe_usd_per_kwh", "best_renewable_pct", "saving_pct", "main_lcoe_usd_per_kwh",
            "main_unserved_frac", "main_saving_pct"}
DOC_KEYS = {"schema", "run_id", "study_run_hash", "figure_check_run_id", "basis_series", "verdict", "designs", "base",
            "cases", "reproduced", "reproduction_errors", "wall_s", "note"}


def _manual(scale, main=(50.0, 100.0), unserved_max_frac=0.0):
    pts = dispatch_grid(PV1, LOAD * scale, PV_GRID, BAT_GRID, battery_hours=4.0, battery_template=TEMPLATE,
                        diesel=DSL)
    tab = cost_table(pts, COSTS, 2.68)
    d0 = tab[(tab["pv_kwp"] == 0.0) & (tab["battery_kwh"] == 0.0)].iloc[0]
    mrow = tab[(tab["pv_kwp"] == main[0]) & (tab["battery_kwh"] == main[1])].iloc[0]
    best = least_cost(tab, unserved_max_frac)
    return tab, d0, mrow, best


def _row(**kw):
    row = {k: 0.0 for k in ROW_KEYS}
    row.update(kw)
    return row


# ---------- followup_cases ----------

def test_followup_cases_real_figure_check():
    cases = followup_cases(FIG, 0.2)
    assert [c["key"] for c in cases] == ["chart_basis", "chart_mean", "swing_low", "swing_high"]
    assert all(set(c) == {"key", "scale_frac", "post_hoc"} for c in cases)
    comp = FIG["comparison"]
    assert cases[0]["scale_frac"] == pytest.approx(1.0 / comp["ratio"], rel=1e-15)
    assert cases[1]["scale_frac"] == pytest.approx(1.0 / comp["mean_ratio"], rel=1e-15)
    assert cases[2]["scale_frac"] == pytest.approx(0.8, rel=1e-15)
    assert cases[3]["scale_frac"] == pytest.approx(1.2, rel=1e-15)
    assert [c["post_hoc"] for c in cases] == [True, True, False, False]
    assert 0.766 < cases[0]["scale_frac"] < 0.768 and 0.845 < cases[1]["scale_frac"] < 0.847
    assert all(isinstance(c["scale_frac"], float) for c in cases)


def _bad_fig(change):
    fig = copy.deepcopy(FIG)
    change(fig)
    return fig


@pytest.mark.parametrize("fig", [
    {},
    _bad_fig(lambda f: f.update(comparison=None)),
    _bad_fig(lambda f: f["comparison"].update(verdict="not checkable")),
    _bad_fig(lambda f: f["comparison"].update(ratio=0.0)),
    _bad_fig(lambda f: f["comparison"].update(ratio=float("nan"))),
    _bad_fig(lambda f: f["comparison"].update(ratio=True)),
    _bad_fig(lambda f: f["comparison"].update(ratio=None)),
    _bad_fig(lambda f: f["comparison"].update(mean_ratio=-1.0)),
    _bad_fig(lambda f: f["comparison"].update(mean_ratio=float("inf"))),
    _bad_fig(lambda f: f["comparison"].update(basis_series="")),
    _bad_fig(lambda f: f["comparison"].update(series=[])),
    "not a dict",
])
def test_followup_cases_rejects_bad_figure_check(fig):
    with pytest.raises(ValueError):
        followup_cases(fig, 0.2)


@pytest.mark.parametrize("swing", [0.0, 1.0, -0.2, True, float("nan"), float("inf"), "0.2", None])
def test_followup_cases_rejects_bad_swing(swing):
    with pytest.raises(ValueError):
        followup_cases(FIG, swing)


def test_followup_cases_does_not_change_input():
    before = json.dumps(FIG, sort_keys=True)
    followup_cases(FIG, 0.2)
    assert json.dumps(FIG, sort_keys=True) == before


# ---------- load_followup ----------

@pytest.fixture(scope="module")
def rows():
    return load_followup(PV1, LOAD, PV_GRID, BAT_GRID, **KW, unserved_max_frac=0.0, main_pv_kwp=50.0,
                         main_battery_kwh=100.0, scales=[1.0, 0.75, 1.1])


def test_load_followup_rows_match_engine(rows):
    assert len(rows) == 3
    for row, scale in zip(rows, (1.0, 0.75, 1.1)):
        assert set(row) == ROW_KEYS
        tab, d0, mrow, best = _manual(scale)
        assert row["scale_frac"] == scale
        assert row["demand_kwh_yr"] == pytest.approx(float((LOAD * scale).sum()), rel=1e-12)
        assert row["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(float(d0["lcoe_usd_per_kwh"]), rel=1e-12)
        assert row["diesel_only_unserved_frac"] == pytest.approx(float(d0["unserved_frac"]), abs=1e-15)
        assert row["best_pv_kwp"] == float(best["pv_kwp"]) and row["best_battery_kwh"] == float(best["battery_kwh"])
        assert row["best_lcoe_usd_per_kwh"] == pytest.approx(float(best["lcoe_usd_per_kwh"]), rel=1e-12)
        assert row["best_renewable_pct"] == pytest.approx(100.0 * float(best["renewable_fraction_frac"]), rel=1e-12)
        assert row["saving_pct"] == pytest.approx(
            100.0 * (1.0 - float(best["lcoe_usd_per_kwh"]) / float(d0["lcoe_usd_per_kwh"])), rel=1e-12)
        assert row["main_lcoe_usd_per_kwh"] == pytest.approx(float(mrow["lcoe_usd_per_kwh"]), rel=1e-12)
        assert row["main_unserved_frac"] == pytest.approx(float(mrow["unserved_frac"]), abs=1e-15)
        assert row["main_saving_pct"] == pytest.approx(
            100.0 * (1.0 - float(mrow["lcoe_usd_per_kwh"]) / float(d0["lcoe_usd_per_kwh"])), rel=1e-12)
        assert all(isinstance(v, float) for v in row.values())


def test_load_followup_scale_changes_the_answer(rows):
    assert rows[1]["demand_kwh_yr"] < rows[0]["demand_kwh_yr"] < rows[2]["demand_kwh_yr"]
    assert rows[1]["diesel_only_lcoe_usd_per_kwh"] != rows[0]["diesel_only_lcoe_usd_per_kwh"]


def test_load_followup_does_not_change_inputs():
    load = LOAD.copy()
    pv_grid = list(PV_GRID)
    bat_grid = list(BAT_GRID)
    load_followup(PV1, load, pv_grid, bat_grid, **KW, unserved_max_frac=0.0, main_pv_kwp=0.0,
                  main_battery_kwh=0.0, scales=(0.9,))
    assert load.equals(LOAD) and pv_grid == PV_GRID and bat_grid == BAT_GRID


def test_load_followup_no_feasible_design():
    out = load_followup(PV1, LOAD, PV_GRID, BAT_GRID, **KW, unserved_max_frac=0.0, main_pv_kwp=100.0,
                        main_battery_kwh=300.0, scales=[3.0])
    row = out[0]
    assert set(row) == ROW_KEYS
    assert row["best_pv_kwp"] is None and row["best_battery_kwh"] is None
    assert row["best_lcoe_usd_per_kwh"] is None and row["best_renewable_pct"] is None
    assert row["saving_pct"] is None
    assert row["diesel_only_unserved_frac"] > 0.0 and row["main_unserved_frac"] > 0.0
    assert isinstance(row["main_lcoe_usd_per_kwh"], float)


@pytest.mark.parametrize("kw", [
    dict(scales=[]), dict(scales=[0.0]), dict(scales=[-1.0]), dict(scales=[True]), dict(scales=[float("nan")]),
    dict(scales=[float("inf")]), dict(scales="1.0"), dict(scales=1.0), dict(scales=["1.0"]),
    dict(main_pv_kwp=75.0), dict(main_battery_kwh=200.0),
])
def test_load_followup_rejects(kw):
    args = dict(unserved_max_frac=0.0, main_pv_kwp=50.0, main_battery_kwh=100.0, scales=[1.0])
    args.update(kw)
    with pytest.raises(ValueError):
        load_followup(PV1, LOAD, PV_GRID, BAT_GRID, **KW, **args)


@pytest.mark.parametrize("grids", [([50.0, 100.0], BAT_GRID), (PV_GRID, [100.0, 300.0])])
def test_load_followup_needs_zero_in_grids(grids):
    with pytest.raises(ValueError):
        load_followup(PV1, LOAD, grids[0], grids[1], **KW, unserved_max_frac=0.0, main_pv_kwp=100.0,
                      main_battery_kwh=300.0, scales=[1.0])


# ---------- check_reproduction ----------

def _real_rows():
    facts = REPORT["facts"]
    base = _row(scale_frac=1.0, best_pv_kwp=facts["best_pv_kwp"]["value"],
                best_battery_kwh=facts["best_battery_kwh"]["value"],
                best_lcoe_usd_per_kwh=facts["best_lcoe_usd_per_kwh"]["value"],
                diesel_only_lcoe_usd_per_kwh=facts["diesel_only_lcoe_usd_per_kwh"]["value"])
    out = [base]
    for factor in (0.8, 1.2):
        sens = [r for r in REPORT["sensitivity_table"] if r["input"] == "demand" and abs(r["factor"] - factor) < 1e-9]
        assert len(sens) == 1
        s = sens[0]
        out.append(_row(scale_frac=s["factor"], best_pv_kwp=s["least_cost_pv_kwp"],
                        best_battery_kwh=s["least_cost_battery_kwh"],
                        best_lcoe_usd_per_kwh=s["least_cost_lcoe_usd_per_kwh"],
                        main_lcoe_usd_per_kwh=s["base_design_lcoe_usd_per_kwh"]))
    return out


def test_check_reproduction_passes_on_matching_rows():
    base, low, high = _real_rows()
    assert check_reproduction(REPORT, base, low, high) == []
    assert REL_TOL == 1e-9


def test_check_reproduction_tolerance():
    base, low, high = _real_rows()
    base["best_lcoe_usd_per_kwh"] *= 1.0 + 1e-12
    assert check_reproduction(REPORT, base, low, high) == []
    base["best_lcoe_usd_per_kwh"] *= 1.0 + 1e-6
    errs = check_reproduction(REPORT, base, low, high)
    assert len(errs) == 1 and "lcoe" in errs[0]


@pytest.mark.parametrize("which,key,delta,word", [
    (0, "best_pv_kwp", 250.0, "pv_kwp"),
    (0, "best_battery_kwh", 1000.0, "battery_kwh"),
    (0, "diesel_only_lcoe_usd_per_kwh", 0.01, "diesel_only"),
    (1, "best_pv_kwp", 250.0, "pv_kwp"),
    (1, "best_lcoe_usd_per_kwh", 0.001, "lcoe"),
    (2, "best_battery_kwh", -1000.0, "battery_kwh"),
    (2, "main_lcoe_usd_per_kwh", 0.001, "lcoe"),
])
def test_check_reproduction_names_the_field(which, key, delta, word):
    rows = _real_rows()
    rows[which][key] = rows[which][key] + delta
    errs = check_reproduction(REPORT, *rows)
    assert len(errs) == 1 and word in errs[0]


def test_check_reproduction_missing_demand_row():
    report = copy.deepcopy(REPORT)
    report["sensitivity_table"] = [r for r in report["sensitivity_table"] if r["input"] != "demand"]
    errs = check_reproduction(report, *_real_rows())
    assert len(errs) >= 1 and all("demand" in e for e in errs)


# ---------- followup_doc ----------

def _case_rows():
    cases = followup_cases(FIG, 0.2)
    vals = [
        (6000.0, 15000.0, 0.262, 0.371, 72.5),
        (6500.0, 17000.0, 0.256, 0.362, 74.0),
        (6000.0, 15000.0, 0.256, 0.360, 73.1),
        (8500.0, 23000.0, 0.248, 0.352, 80.2),
    ]
    rows = []
    for case, (pv, bat, best, d0, ren) in zip(cases, vals):
        rows.append(_row(scale_frac=case["scale_frac"], demand_kwh_yr=9568110.0 * case["scale_frac"],
                         diesel_only_lcoe_usd_per_kwh=d0, best_pv_kwp=pv, best_battery_kwh=bat,
                         best_lcoe_usd_per_kwh=best, best_renewable_pct=ren,
                         saving_pct=100.0 * (1.0 - best / d0), main_lcoe_usd_per_kwh=best + 0.01,
                         main_saving_pct=100.0 * (1.0 - (best + 0.01) / d0)))
    return cases, rows


def _doc(errors=()):
    cases, rows = _case_rows()
    base = _real_rows()[0]
    return followup_doc(REPORT, FIG, figure_check_id="figure-20261029T053942-12137f", run_id="followup-test",
                        base_row=base, cases=cases, case_rows=rows, errors=list(errors), wall_s=12.5)


def test_followup_doc_fields():
    doc = _doc()
    assert set(doc) == DOC_KEYS
    assert doc["schema"] == LOAD_FOLLOWUP_SCHEMA == "autosolar.load_followup/1"
    assert doc["run_id"] == "followup-test" and doc["figure_check_run_id"] == "figure-20261029T053942-12137f"
    assert doc["study_run_hash"] == "b4a44fc6d4c32339"
    assert doc["basis_series"] == "31 Dec 2018" and doc["verdict"] == "outside band"
    assert doc["designs"] == 925
    assert doc["reproduced"] is True and doc["reproduction_errors"] == []
    assert doc["wall_s"] == 12.5 and isinstance(doc["wall_s"], float)
    assert doc["note"] == NOTE
    assert NOTE == ("Added after the load check result (post hoc). The study's own answer and inputs are "
                    "unchanged.")
    assert [c["key"] for c in doc["cases"]] == ["chart_basis", "chart_mean", "swing_low", "swing_high"]
    first = doc["cases"][0]
    assert list(first)[:3] == ["key", "scale_frac", "post_hoc"]
    assert set(first) == {"key", "post_hoc"} | ROW_KEYS
    assert first["best_pv_kwp"] == 6000.0
    json.dumps(doc)


def test_followup_doc_not_reproduced():
    doc = _doc(errors=["best_lcoe_usd_per_kwh differs"])
    assert doc["reproduced"] is False and doc["reproduction_errors"] == ["best_lcoe_usd_per_kwh differs"]


def test_followup_doc_rejects_length_mismatch():
    cases, rows = _case_rows()
    with pytest.raises(ValueError):
        followup_doc(REPORT, FIG, figure_check_id="f", run_id="r", base_row=_real_rows()[0], cases=cases,
                     case_rows=rows[:3], errors=[], wall_s=1.0)


# ---------- site ----------

def _section(page):
    start = page.index('<section id="figure-check">')
    end = page.index("</section>", start)
    return page[start:end]


def test_page_without_followup_unchanged():
    assert render_study_html(REPORT, TABLE, figure_check=FIG, load_followup=None) == render_study_html(
        REPORT, TABLE, figure_check=FIG)
    assert "If the chart is right" not in render_study_html(REPORT, TABLE, figure_check=FIG)


def test_page_with_followup():
    page = render_study_html(REPORT, TABLE, figure_check=FIG, load_followup=_doc())
    page.encode("ascii")
    assert "<script" not in page
    sec = _section(page)
    assert "<h3>If the chart is right</h3>" in sec
    assert ("Added after the load check result (post hoc), so the answer above is unchanged. The engine re-ran all "
            "925 designs at each load below (computed). Before that, it gave back this study&#x27;s own answer and "
            "the two demand rows of What moves the cost, to within one part in a billion.") in sec
    assert ("If the load is what the 31 Dec 2018 curve implies (23.3% lower), the least cost design is 6,000 kWp of "
            "PV and 15,000 kWh of battery at 0.262 USD/kWh against 0.371 for diesel only: 29.4% less "
            "(computed).") in sec
    for head in ("Load case", "Load (kWh/yr)", "Diesel only (USD/kWh)", "Least cost design", "Its cost (USD/kWh)",
                 "Below diesel only", "Main design (USD/kWh)"):
        assert "<th>" + head + "</th>" in sec
    for name in ("Chart day: 31 Dec 2018 (post hoc)", "Chart, mean of all days (post hoc)",
                 "Demand -20% (sensitivity row)", "Demand +20% (sensitivity row)"):
        assert "<td>" + name + "</td>" in sec
    assert "<td>6,000 kWp + 15,000 kWh</td>" in sec and "<td>8,500 kWp + 23,000 kWh</td>" in sec
    assert "<td>0.371</td>" in sec and "<td>29.4%</td>" in sec
    assert ("Main design: the study&#x27;s answer, 7,250 kWp + 19,000 kWh, at each load. Other inputs stay as in "
            "the study.") in sec
    assert sec.index("If the chart is right") > sec.index("Reader error in the chart reader test")


def test_page_followup_no_saving_line():
    doc = _doc()
    case = doc["cases"][0]
    for key in ("best_pv_kwp", "best_battery_kwh", "best_lcoe_usd_per_kwh", "best_renewable_pct", "saving_pct"):
        case[key] = None
    sec = _section(render_study_html(REPORT, TABLE, figure_check=FIG, load_followup=doc))
    assert ("If the load is what the 31 Dec 2018 curve implies (23.3% lower), no design with PV or battery beats "
            "diesel only at 0.371 USD/kWh (computed).") in sec
    assert "<td>none feasible</td>" in sec


@pytest.mark.parametrize("change", ["not reproduced", "other study", "no figure check"])
def test_page_refuses_bad_followup(change):
    doc = _doc()
    fig = FIG
    if change == "not reproduced":
        doc["reproduced"] = False
    elif change == "other study":
        doc["study_run_hash"] = "0000000000000000"
    else:
        fig = None
    with pytest.raises(ValueError):
        render_study_html(REPORT, TABLE, figure_check=fig, load_followup=doc)


# ---------- tool ----------

def test_tool_cache_only_email():
    assert "@" in tool.CACHE_ONLY_EMAIL and "." not in tool.CACHE_ONLY_EMAIL


def test_tool_no_network_fetchers():
    f = tool.no_network_fetchers()
    assert isinstance(f, WeatherFetchers)
    calls = [
        lambda: f.cams_monthly(-5.88, 110.43, 2016, 2024, tool.CACHE_ONLY_EMAIL),
        lambda: f.cams_hourly(-5.88, 110.43, 2018, tool.CACHE_ONLY_EMAIL),
        lambda: f.nasa_monthly(-5.88, 110.43, 2016, 2024),
        lambda: f.nasa_hourly(-5.88, 110.43, 2020),
        lambda: f.pvgis_tmy(-5.88, 110.43),
        lambda: f.gsa(-5.88, 110.43),
    ]
    for call in calls:
        with pytest.raises(RuntimeError, match="no network"):
            call()


def test_tool_empty_cache_never_reaches_network(tmp_path):
    fetchers = cached_fetchers(tool.no_network_fetchers(), tmp_path / "cache")
    with pytest.raises(RuntimeError, match="no network"):
        build_weather_cases(-5.88, 110.43, tool.CACHE_ONLY_EMAIL, fetchers)


def test_tool_missing_run(tmp_path, capsys):
    code = tool.main(["--run", "nope", "--figure-check", "nofig", "--runs", str(tmp_path / "studies"),
                      "--figure-checks", str(tmp_path / "figs"), "--out", str(tmp_path / "out"),
                      "--weather-cache", str(tmp_path / "cache")])
    assert code == 2
    assert "not found" in capsys.readouterr().out
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_no_nan_in_real_inputs():
    assert all(math.isfinite(r["least_cost_lcoe_usd_per_kwh"]) for r in REPORT["sensitivity_table"]
               if r["input"] == "demand")
