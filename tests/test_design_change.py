"""Acceptance tests for T26: which inputs would change the design.

Written by hand before the code (docs/specs/T26_design_change.md). No network.
"""
import copy
import json
import math
import pathlib
import re

import pandas as pd
import pytest

import autosolar.site as site
from autosolar.site import (DESIGN_CHANGE_MIN_FRAC, DESIGN_CHANGE_TOL, SENSITIVITY_LABELS, design_change_rows,
                            design_change_section, esc, fmt, render_study_html)

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "docs" / "site" / "data" / "b4a44fc6d4c32339"
REPORT = json.loads((DATA / "report.json").read_text(encoding="ascii"))
TABLE = pd.read_csv(DATA / "design_table.csv")
KEYS = {"input", "factor", "extra_frac", "pv_kwp", "battery_kwh", "same_design"}
HEAD = '<section id="design-change"><h2>Which inputs would change the design?</h2>'
T1 = ("Confirm these first ranks inputs by how far they move the cost. Before building, a second question matters "
      "more: if an input is wrong, would another design be cheaper? For each input moved down and up, the study "
      "also found the least cost design at that value. The table shows how much more the main design costs than "
      "that design, for the worse of the two moves (computed).")
T4 = ("This is the cost of a wrong input at one point each way, not an expected value: the study puts no odds on "
      "the inputs. Some inputs, such as the future diesel price, cannot be measured before building; for those, "
      "read the table as a check that the choice still holds.")
HEADERS = ["Input", "Moved", "Least cost design at that value", "Main design costs more by"]


def _row(name, factor, base, least, pv=100.0, bat=200.0, same=False):
    return {"input": name, "factor": factor, "base_design_lcoe_usd_per_kwh": base,
            "least_cost_lcoe_usd_per_kwh": least, "least_cost_pv_kwp": pv, "least_cost_battery_kwh": bat,
            "same_design": same, "note": ""}


def _rep(rows):
    return {"sensitivity_table": rows}


def _reference(report):
    """Independent restatement of the spec for a table whose rows are all usable."""
    best, order = {}, []
    for r in report["sensitivity_table"]:
        extra = max(r["base_design_lcoe_usd_per_kwh"] / r["least_cost_lcoe_usd_per_kwh"] - 1.0, 0.0)
        name = r["input"]
        if name not in best:
            order.append(name)
            best[name] = (extra, r)
        elif extra > best[name][0]:
            best[name] = (extra, r)
    ranked = sorted(range(len(order)), key=lambda i: (-best[order[i]][0], i))
    out = []
    for i in ranked:
        extra, r = best[order[i]]
        out.append({"input": r["input"], "factor": float(r["factor"]), "extra_frac": extra,
                    "pv_kwp": float(r["least_cost_pv_kwp"]), "battery_kwh": float(r["least_cost_battery_kwh"]),
                    "same_design": r["same_design"]})
    return out


def _cells_for(item):
    f = item["factor"]
    moved = ("down " + fmt(100 * (1 - f), 0) + "%") if f < 1 else ("up " + fmt(100 * (f - 1), 0) + "%")
    design = ("Same as the main design" if item["same_design"]
              else fmt(item["pv_kwp"], 0) + " kWp and " + fmt(item["battery_kwh"], 0) + " kWh")
    return [esc(SENSITIVITY_LABELS.get(item["input"], item["input"])), esc(moved), esc(design),
            esc(fmt(100 * item["extra_frac"], 1) + "%")]


def _body_rows(sec):
    body = sec[sec.index("<tbody>"):sec.index("</tbody>")]
    return [re.findall(r"<td>(.*?)</td>", tr) for tr in re.findall(r"<tr>(.*?)</tr>", body)]


def _t3_one(label, m="1"):
    return ("Confirm before sizing the plant: " + label + ". If this input is off by the amount above, the main "
            "design costs " + m + "% or more above the best design for that case. The other inputs move the price "
            "more than the plan (computed; the " + m + "% line is assumed).")


def _cut(page, sid):
    tag = '<section id="%s">' % sid
    if tag not in page:
        return page
    start = page.index(tag)
    return page[:start] + page[page.index("</section>", start) + len("</section>"):]


# ---------- constants ----------

def test_constants():
    assert DESIGN_CHANGE_MIN_FRAC == 0.01 and DESIGN_CHANGE_TOL == 1e-9


# ---------- design_change_rows ----------

def test_rows_example_matches_reference():
    rows = design_change_rows(REPORT)
    want = _reference(REPORT)
    assert len(rows) == 9 == len({r["input"] for r in REPORT["sensitivity_table"]})
    assert [r["input"] for r in rows] == [w["input"] for w in want]
    for got, exp in zip(rows, want):
        assert set(got) == KEYS
        assert got["factor"] == exp["factor"] and got["same_design"] is exp["same_design"]
        assert got["pv_kwp"] == exp["pv_kwp"] and got["battery_kwh"] == exp["battery_kwh"]
        assert got["extra_frac"] == pytest.approx(exp["extra_frac"], rel=1e-12, abs=1e-15)
        assert isinstance(got["factor"], float) and isinstance(got["extra_frac"], float)
        assert isinstance(got["pv_kwp"], float) and isinstance(got["battery_kwh"], float)


def test_rows_example_headline_numbers():
    top = design_change_rows(REPORT)[0]
    assert top["input"] == "demand" and top["factor"] == 0.8
    assert top["pv_kwp"] == 6000.0 and top["battery_kwh"] == 15000.0 and top["same_design"] is False
    assert fmt(100 * top["extra_frac"], 1) == "8.8"
    extras = [r["extra_frac"] for r in design_change_rows(REPORT)]
    assert extras == sorted(extras, reverse=True) and min(extras) >= 0.0
    assert extras[1] < DESIGN_CHANGE_MIN_FRAC


def test_rows_keep_worse_side_and_stable_ties():
    rows = design_change_rows(_rep([
        _row("a", 0.8, 0.102, 0.100), _row("a", 1.2, 0.105, 0.100, pv=7.0),
        _row("b", 0.8, 0.103, 0.100, pv=1.0), _row("b", 1.2, 0.103, 0.100, pv=2.0),
        _row("c", 0.8, 0.105, 0.100, pv=9.0),
    ]))
    assert [r["input"] for r in rows] == ["a", "c", "b"]
    assert rows[0]["factor"] == 1.2 and rows[0]["pv_kwp"] == 7.0
    assert rows[2]["factor"] == 0.8 and rows[2]["pv_kwp"] == 1.0


@pytest.mark.parametrize("change", [
    {"input": ""}, {"input": 5}, {"factor": 1.0}, {"factor": True}, {"factor": float("nan")}, {"factor": "0.8"},
    {"factor": float("inf")}, {"base_design_lcoe_usd_per_kwh": 0.0}, {"base_design_lcoe_usd_per_kwh": -0.1},
    {"base_design_lcoe_usd_per_kwh": float("inf")}, {"least_cost_lcoe_usd_per_kwh": float("nan")},
    {"least_cost_lcoe_usd_per_kwh": None}, {"least_cost_lcoe_usd_per_kwh": True},
    {"least_cost_lcoe_usd_per_kwh": 0.0}, {"least_cost_pv_kwp": -1.0}, {"least_cost_pv_kwp": float("nan")},
    {"least_cost_battery_kwh": float("inf")}, {"least_cost_battery_kwh": False}, {"same_design": "no"},
    {"same_design": None}, {"same_design": 0},
])
def test_rows_skip_unusable_rows(change):
    bad = _row("bad", 0.8, 0.13, 0.10)
    bad.update(change)
    rows = design_change_rows(_rep([bad, _row("ok", 0.8, 0.11, 0.10)]))
    assert [r["input"] for r in rows] == ["ok"]


@pytest.mark.parametrize("missing", ["input", "factor", "base_design_lcoe_usd_per_kwh",
                                     "least_cost_lcoe_usd_per_kwh", "least_cost_pv_kwp",
                                     "least_cost_battery_kwh", "same_design"])
def test_rows_skip_rows_with_a_missing_key(missing):
    bad = _row("bad", 0.8, 0.13, 0.10)
    del bad[missing]
    rows = design_change_rows(_rep(["not a dict", bad, _row("ok", 1.2, 0.11, 0.10)]))
    assert [r["input"] for r in rows] == ["ok"]


def test_rows_no_feasible_design_row_is_skipped():
    nf = {"input": "demand", "factor": 1.2, "base_design_lcoe_usd_per_kwh": 0.3, "least_cost_pv_kwp": math.nan,
          "least_cost_battery_kwh": math.nan, "least_cost_lcoe_usd_per_kwh": math.nan, "same_design": False,
          "note": "no feasible design"}
    rows = design_change_rows(_rep([_row("demand", 0.8, 0.11, 0.10), nf]))
    assert len(rows) == 1 and rows[0]["factor"] == 0.8


def test_rows_negative_extra_raises_and_tolerance():
    with pytest.raises(ValueError, match="least cost"):
        design_change_rows(_rep([_row("x", 0.8, 0.0999, 0.1)]))
    rows = design_change_rows(_rep([_row("x", 0.8, 0.1 * (1 - 1e-12), 0.1)]))
    assert rows[0]["extra_frac"] == 0.0


def test_rows_bad_report():
    with pytest.raises(ValueError):
        design_change_rows([])
    with pytest.raises(ValueError):
        design_change_rows({"sensitivity_table": {}})
    with pytest.raises(ValueError):
        design_change_rows({"sensitivity_table": None})
    assert design_change_rows({}) == []
    assert design_change_rows(_rep([])) == []


def test_rows_do_not_change_the_report():
    rep = copy.deepcopy(REPORT)
    design_change_rows(rep)
    design_change_section(rep)
    assert rep == REPORT


# ---------- design_change_section ----------

def test_section_example_exact():
    sec = design_change_section(REPORT)
    sec.encode("ascii")
    assert sec.startswith(HEAD) and sec.endswith("</section>")
    assert sec.count("<section") == 1 and sec.count("<table") == 1 and "<script" not in sec
    assert re.findall(r"<th>(.*?)</th>", sec) == HEADERS
    assert _body_rows(sec) == [_cells_for(it) for it in _reference(REPORT)]
    assert _body_rows(sec)[0] == ["Demand", "down 20%", "6,000 kWp and 15,000 kWh", "8.8%"]
    p1 = "<p>" + esc(T1) + "</p>"
    p3 = "<p>" + esc(_t3_one("Demand")) + "</p>"
    p4 = "<p>" + esc(T4) + "</p>"
    assert sec.index(HEAD) < sec.index(p1) < sec.index("<table") < sec.index(p3) < sec.index(p4)
    assert sec == HEAD + p1 + sec[sec.index("<div"):sec.index(p3)] + p3 + p4 + "</section>"


def test_section_same_design_cell():
    sec = design_change_section(_rep([_row("battery_capex_usd_per_kwh", 0.8, 0.2, 0.2, same=True),
                                      _row("battery_capex_usd_per_kwh", 1.2, 0.3, 0.3, same=True)]))
    assert _body_rows(sec) == [["Battery price", "down 20%", "Same as the main design", "0.0%"]]
    assert "No input moved this way" in sec


def test_section_plural_text():
    sec = design_change_section(_rep([
        _row("pv_capex_usd_per_kwp", 0.8, 0.105, 0.100, pv=1500.0, bat=2500.0),
        _row("demand", 1.2, 0.120, 0.100, pv=8500.0, bat=23000.0),
        _row("fuel_price_usd_per_l", 0.8, 0.1001, 0.100),
    ]))
    t3 = ("Confirm before sizing the plant: Demand, PV price. If these inputs are off by the amounts above, the main "
          "design costs 1% or more above the best design for that case. The other inputs move the price more than "
          "the plan (computed; the 1% line is assumed).")
    assert "<p>" + esc(t3) + "</p>" in sec
    assert [r[0] for r in _body_rows(sec)] == ["Demand", "PV price", "Diesel price"]
    assert _body_rows(sec)[0] == ["Demand", "up 20%", "8,500 kWp and 23,000 kWh", "20.0%"]


def test_section_none_above_the_line():
    sec = design_change_section(_rep([_row("fuel_price_usd_per_l", 0.8, 0.1005, 0.100)]))
    t3 = ("No input moved this way makes the main design cost 1% or more above the best design for that case: the "
          "inputs move the price more than the plan (computed; the 1% line is assumed).")
    assert "<p>" + esc(t3) + "</p>" in sec and "Confirm before sizing" not in sec
    assert "<p>" + esc(T4) + "</p>" in sec


def test_section_line_is_inclusive_and_read_at_call_time(monkeypatch):
    monkeypatch.setattr(site, "DESIGN_CHANGE_MIN_FRAC", 0.5)
    sec = site.design_change_section(_rep([_row("demand", 0.5, 1.5, 1.0), _row("pv_capex_usd_per_kwp", 0.8, 1.4, 1.0)]))
    assert "<p>" + esc(_t3_one("Demand", "50")) + "</p>" in sec


def test_section_up_move_unknown_input_and_escaping():
    sec = design_change_section(_rep([_row("new<input>", 1.3, 0.13, 0.10, pv=12345.6, bat=0.0)]))
    sec.encode("ascii")
    assert _body_rows(sec) == [[esc("new<input>"), "up 30%", "12,346 kWp and 0 kWh", "30.0%"]]
    assert "new<input>" not in sec


def test_section_empty_when_no_usable_row():
    assert design_change_section(_rep([])) == ""
    assert design_change_section({}) == ""
    assert design_change_section(_rep([_row("x", 1.0, 0.2, 0.1), _row("y", 0.8, 0.2, 0.1, same=None)])) == ""


# ---------- the page ----------

def test_page_places_section_after_confirm():
    page = render_study_html(REPORT, TABLE)
    page.encode("ascii")
    assert "<script" not in page and page.count('<section id="design-change">') == 1
    assert design_change_section(REPORT) in page
    assert page.index('<section id="confirm">') < page.index('<section id="design-change">') < page.index(
        '<section id="firm">')
    end_confirm = page.index("</section>", page.index('<section id="confirm">')) + len("</section>")
    assert page[end_confirm:].startswith('<section id="design-change">')


def test_page_with_resource_screen_order():
    screen = json.loads((DATA / "resource_screen.json").read_text(encoding="ascii"))
    page = render_study_html(REPORT, TABLE, resource_screen=screen)
    assert (page.index('<section id="confirm">') < page.index('<section id="design-change">')
            < page.index('<section id="resources">') < page.index('<section id="firm">'))


def test_page_otherwise_unchanged():
    rep = copy.deepcopy(REPORT)
    for row in rep["sensitivity_table"]:
        row["same_design"] = None
    without = render_study_html(rep, TABLE)
    assert '<section id="design-change">' not in without
    assert _cut(render_study_html(REPORT, TABLE), "design-change") == without
