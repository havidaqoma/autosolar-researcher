"""Acceptance tests for T21 (try another diesel price on the study page, no script).

Written by the orchestrator before the code. No network. Uses the committed data of two gallery studies
(docs/site/data/<run>/) and small hand-made tables."""
import json
import math
import pathlib
import re

import pandas as pd
import pytest

from autosolar.site import (FUEL_PRICE_CSS, FUEL_PRICE_STEPS_USD_PER_L, MAX_PRICE_STEPS, fuel_price_section,
                            fuel_price_steps, price_grid, render_index_html, render_study_html, study_price_inputs)

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNS = ("b4a44fc6d4c32339", "107477f112e5d92c")
STEP_KEYS = {"price_usd_per_l", "diesel_only_lcoe_usd_per_kwh", "best_pv_kwp", "best_battery_kwh",
             "best_lcoe_usd_per_kwh", "best_renewable_pct", "saving_pct", "diesel_only_wins", "on_grid_edge",
             "is_study_price"}


def _load(run):
    data = ROOT / "docs" / "site" / "data" / run
    report = json.loads((data / "report.json").read_text(encoding="ascii"))
    table = pd.read_csv(data / "design_table.csv")
    return report, table


def _steps(report, table, prices):
    inp = study_price_inputs(report)
    return fuel_price_steps(table, study_price_usd_per_l=inp["fuel_price_usd_per_l"],
                            demand_kwh_yr=inp["demand_kwh_yr"], unserved_max_frac=inp["unserved_max_frac"],
                            prices_usd_per_l=prices)


# ---------- constants and grid ----------

def test_steps_constant():
    assert FUEL_PRICE_STEPS_USD_PER_L == (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6)
    assert MAX_PRICE_STEPS == 24


def test_price_grid():
    assert price_grid(0.848485) == [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.848485, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5,
                                    1.6]
    assert price_grid(1.0) == list(FUEL_PRICE_STEPS_USD_PER_L)
    assert price_grid(1.26) == sorted(list(FUEL_PRICE_STEPS_USD_PER_L) + [1.26])
    assert price_grid(2.5)[-1] == 2.5 and len(price_grid(2.5)) == 16
    assert all(isinstance(v, float) for v in price_grid(0.848485))


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), True, "1.0", None])
def test_price_grid_rejects(bad):
    with pytest.raises(ValueError):
        price_grid(bad)


def test_study_price_inputs():
    report, _ = _load("b4a44fc6d4c32339")
    assert study_price_inputs(report) == {"fuel_price_usd_per_l": 0.848485, "unserved_max_frac": 0.001,
                                          "demand_kwh_yr": 9568110.0}
    bad = json.loads(json.dumps(report))
    bad["inputs_table"] = [r for r in bad["inputs_table"] if r["name"] != "fuel_price_usd_per_l"]
    with pytest.raises(ValueError):
        study_price_inputs(bad)
    bad = json.loads(json.dumps(report))
    del bad["facts"]["demand_kwh_yr"]
    with pytest.raises(ValueError):
        study_price_inputs(bad)


# ---------- the maths against the engine, on two real studies ----------

@pytest.mark.parametrize("run", RUNS)
def test_steps_give_back_the_engine_numbers(run):
    report, table = _load(run)
    p0 = study_price_inputs(report)["fuel_price_usd_per_l"]
    facts = report["facts"]
    sens = {round(r["factor"], 6): r for r in report["sensitivity_table"] if r["input"] == "fuel_price_usd_per_l"}
    assert set(sens) == {0.8, 1.2}
    steps = _steps(report, table, [p0, 0.8 * p0, 1.2 * p0])
    base, low, high = steps
    assert base["is_study_price"] is True and low["is_study_price"] is False
    assert base["best_pv_kwp"] == facts["best_pv_kwp"]["value"]
    assert base["best_battery_kwh"] == facts["best_battery_kwh"]["value"]
    assert base["best_lcoe_usd_per_kwh"] == pytest.approx(facts["best_lcoe_usd_per_kwh"]["value"], rel=1e-9)
    assert base["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(
        facts["diesel_only_lcoe_usd_per_kwh"]["value"], rel=1e-9)
    assert base["best_renewable_pct"] == pytest.approx(facts["best_renewable_pct"]["value"], rel=1e-9)
    assert base["saving_pct"] == pytest.approx(-facts["lcoe_change_pct"]["value"], rel=1e-9)
    for step, factor in ((low, 0.8), (high, 1.2)):
        row = sens[factor]
        assert step["best_pv_kwp"] == row["least_cost_pv_kwp"]
        assert step["best_battery_kwh"] == row["least_cost_battery_kwh"]
        assert step["best_lcoe_usd_per_kwh"] == pytest.approx(row["least_cost_lcoe_usd_per_kwh"], rel=1e-9)


@pytest.mark.parametrize("run", RUNS)
def test_break_even_matches_the_study(run):
    report, table = _load(run)
    be = report["facts"]["break_even_fuel_usd_per_l"]["value"]
    at, below = _steps(report, table, [be, 0.9 * be])
    assert at["best_lcoe_usd_per_kwh"] == pytest.approx(at["diesel_only_lcoe_usd_per_kwh"], abs=1e-12)
    assert below["diesel_only_wins"] is True and below["saving_pct"] == pytest.approx(0.0, abs=1e-12)


def test_real_steps_shape():
    report, table = _load("b4a44fc6d4c32339")
    steps = _steps(report, table, price_grid(0.848485))
    assert len(steps) == 16
    for s in steps:
        assert set(s) == STEP_KEYS
        assert isinstance(s["diesel_only_wins"], bool) and isinstance(s["on_grid_edge"], bool)
        assert isinstance(s["is_study_price"], bool)
        for k in STEP_KEYS - {"diesel_only_wins", "on_grid_edge", "is_study_price"}:
            assert isinstance(s[k], float) and math.isfinite(s[k])
    assert [s["is_study_price"] for s in steps].count(True) == 1
    assert steps[0]["diesel_only_wins"] is True and steps[0]["on_grid_edge"] is False
    assert steps[-1]["diesel_only_wins"] is False and steps[-1]["on_grid_edge"] is True
    d0 = [s["diesel_only_lcoe_usd_per_kwh"] for s in steps]
    assert d0 == sorted(d0)


# ---------- the rules, on a small hand-made table ----------

SMALL = pd.DataFrame({
    "pv_kwp": [0.0, 0.0, 100.0, 50.0],
    "battery_kwh": [0.0, 100.0, 0.0, 100.0],
    "lcoe_usd_per_kwh": [0.30, 0.31, 0.28, 0.10],
    "fuel_l_per_yr": [1000.0, 990.0, 300.0, 500.0],
    "unserved_frac": [0.0, 0.0, 0.0, 0.5],
    "renewable_fraction_frac": [0.0, 0.01, 0.4, 0.5],
})
SMALL_KW = dict(study_price_usd_per_l=1.0, demand_kwh_yr=10000.0, unserved_max_frac=0.001)


def test_small_table_values():
    before = SMALL.copy()
    at_study, cheap = fuel_price_steps(SMALL, **SMALL_KW, prices_usd_per_l=[1.0, 0.5])
    assert SMALL.equals(before)
    assert at_study == {"price_usd_per_l": 1.0, "diesel_only_lcoe_usd_per_kwh": pytest.approx(0.30),
                        "best_pv_kwp": 100.0, "best_battery_kwh": 0.0,
                        "best_lcoe_usd_per_kwh": pytest.approx(0.28), "best_renewable_pct": pytest.approx(40.0),
                        "saving_pct": pytest.approx(100.0 * (1.0 - 0.28 / 0.30)), "diesel_only_wins": False,
                        "on_grid_edge": True, "is_study_price": True}
    assert cheap["diesel_only_wins"] is True and cheap["on_grid_edge"] is False
    assert cheap["best_pv_kwp"] == 0.0 and cheap["best_battery_kwh"] == 0.0
    assert cheap["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(0.30 - 0.5 * 0.1)
    assert cheap["best_lcoe_usd_per_kwh"] == pytest.approx(0.25) and cheap["saving_pct"] == pytest.approx(0.0)


def test_small_table_skips_infeasible_rows():
    for step in fuel_price_steps(SMALL, **SMALL_KW, prices_usd_per_l=[0.2, 1.0, 3.0]):
        assert not (step["best_pv_kwp"] == 50.0 and step["best_battery_kwh"] == 100.0)


def test_slope_uses_served_energy():
    table = SMALL.copy()
    table.loc[3, "unserved_frac"] = 0.0005
    step = fuel_price_steps(table, **SMALL_KW, prices_usd_per_l=[2.0])[0]
    assert step["best_pv_kwp"] == 50.0
    assert step["best_lcoe_usd_per_kwh"] == pytest.approx(0.10 + 1.0 * 500.0 / (10000.0 * (1.0 - 0.0005)))


def test_tie_goes_to_earliest_row():
    table = pd.DataFrame({"pv_kwp": [0.0, 100.0, 200.0], "battery_kwh": [0.0, 0.0, 0.0],
                          "lcoe_usd_per_kwh": [0.30, 0.25, 0.25], "fuel_l_per_yr": [1000.0, 0.0, 0.0],
                          "unserved_frac": [0.0, 0.0, 0.0], "renewable_fraction_frac": [0.0, 1.0, 1.0]})
    step = fuel_price_steps(table, **SMALL_KW, prices_usd_per_l=[1.0])[0]
    assert step["best_pv_kwp"] == 100.0 and step["best_lcoe_usd_per_kwh"] == pytest.approx(0.25)


@pytest.mark.parametrize("change", [
    dict(prices_usd_per_l=[]), dict(prices_usd_per_l=[0.0]), dict(prices_usd_per_l=[-0.5]),
    dict(prices_usd_per_l=[True]), dict(prices_usd_per_l=[float("nan")]), dict(prices_usd_per_l=1.0),
    dict(prices_usd_per_l=[0.1] * 25), dict(study_price_usd_per_l=0.0), dict(study_price_usd_per_l=True),
    dict(demand_kwh_yr=0.0), dict(demand_kwh_yr=float("inf")), dict(unserved_max_frac=1.5),
    dict(unserved_max_frac=-0.1), dict(unserved_max_frac=True),
])
def test_small_table_rejects_bad_args(change):
    args = dict(SMALL_KW, prices_usd_per_l=[1.0])
    args.update(change)
    with pytest.raises(ValueError):
        fuel_price_steps(SMALL, **args)


@pytest.mark.parametrize("table", [
    SMALL.drop(columns=["fuel_l_per_yr"]),
    SMALL.drop(columns=["renewable_fraction_frac"]),
    SMALL.iloc[1:].reset_index(drop=True),
    SMALL.iloc[0:0],
    SMALL.assign(unserved_frac=0.5),
])
def test_small_table_rejects_bad_tables(table):
    with pytest.raises(ValueError):
        fuel_price_steps(table, **SMALL_KW, prices_usd_per_l=[1.0])


# ---------- the page ----------

@pytest.fixture(scope="module")
def page():
    report, table = _load("b4a44fc6d4c32339")
    return render_study_html(report, table)


def _sec(page):
    start = page.index('<section id="fuel-price">')
    return page[start:page.index("</section>", start)]


def test_section_on_real_page(page):
    page.encode("ascii")
    assert "<script" not in page and page.count("<style>") == 1
    assert page.count('<section id="fuel-price">') == 1
    sec = _sec(page)
    assert "<h2>Try another diesel price</h2>" in sec
    assert ("Pick a diesel price in USD per litre. The page re-costs all 925 designs of this study at that price; "
            "every other input stays as in the study, which used 0.85 USD/L.") in sec
    assert sec.count('<input type="radio" name="fp"') == 16
    assert sec.count(" checked") == 1
    checked = re.search(r'<input type="radio" name="fp" id="fp(\d+)" checked>', sec)
    assert checked is not None and checked.group(1) == "7"
    assert '<label for="fp7">0.85 (study)</label>' in sec and '<label for="fp0">0.20</label>' in sec
    assert '<label for="fp15">1.60</label>' in sec
    assert sec.count('<p class="fp-out" id="fpo') == 16
    assert sec.index('<div class="fp-labels">') > sec.index('id="fp15"')
    assert sec.index('<div class="fp-outs">') > sec.index('<div class="fp-labels">')


def test_section_lines(page):
    sec = _sec(page)
    assert ('<p class="fp-out" id="fpo7">At 0.85 USD/L: diesel only costs 0.354 USD/kWh. The least cost design is '
            '7,250 kWp of PV and 19,000 kWh of battery at 0.251 USD/kWh, 29.1% less, with ') in sec
    assert ("<p class=\"fp-out\" id=\"fpo0\">At 0.20 USD/L: diesel only, at 0.106 USD/kWh, is the least cost choice; "
            "no design with PV or battery beats it (computed).</p>") in sec
    last = sec[sec.index('id="fpo15"'):]
    last = last[:last.index("</p>")]
    assert "9,000 kWp of PV" in last
    assert last.endswith("(computed). It sits on the edge of the design grid, so a larger design may cost less.")
    assert ("How: a design&#x27;s fuel use does not depend on the price, so its cost moves in a straight line with "
            "it. At 20% below and above the study price these are the same numbers as the fuel price rows of What "
            "moves the cost. Below 0.27 USD/L, diesel only is cheapest (break-even from the study).") in sec


def test_section_place_and_css(page):
    assert page.index('<section id="answer">') < page.index('<section id="fuel-price">') < page.index(
        '<section id="firm">')
    head = page[:page.index("</head>")]
    for i in (0, 7, 15, MAX_PRICE_STEPS - 1):
        assert ("#fp%d:checked~.fp-outs #fpo%d{display:block}" % (i, i)) in head
        assert ("#fp%d:checked~.fp-labels label[for=fp%d]{background:#1f5f99;color:#fff}" % (i, i)) in head
    assert ".fp-out{display:none;margin:8px 0}" in FUEL_PRICE_CSS and FUEL_PRICE_CSS in head
    assert FUEL_PRICE_CSS not in render_index_html([])


def test_section_without_firmness():
    report, table = _load("b4a44fc6d4c32339")
    report["firmness"] = None
    page = render_study_html(report, table)
    assert page.index('<section id="answer">') < page.index('<section id="fuel-price">') < page.index(
        '<section id="designs">')


def test_section_function_matches_page(page):
    report, table = _load("b4a44fc6d4c32339")
    assert fuel_price_section(report, table) in page


def test_curated_page_has_its_own_price():
    report, table = _load("107477f112e5d92c")
    sec = _sec(render_study_html(report, table))
    assert sec.count('<input type="radio" name="fp"') == 16
    assert "which used 1.26 USD/L." in sec and '1.26 (study)</label>' in sec
    assert "Below 0.24 USD/L, diesel only is cheapest (break-even from the study)." in sec
