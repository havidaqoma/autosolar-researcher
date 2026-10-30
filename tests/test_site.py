"""Acceptance tests for T13 (autosolar/site.py). Written by the orchestrator.

No network. The study is the synthetic run of test_study with the check inputs (as in test_firmness)."""
import json
import re

import pandas as pd
import pytest

import test_study as ts
from autosolar.site import (CARD_TITLES, SITE_CSS, esc, headline, heatmap_svg, render_index_html,
                            render_study_html, tornado_svg, weather_svg)
from autosolar.study import run_study

CHECKS = ts.ROOT / "config" / "study_checks.json"
FORBIDDEN = ("<script", "<iframe", "<link", "<img", "@import", "src=")


@pytest.fixture(scope="module")
def study(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("site")
    out = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                    inputs_path=ts.small_inputs(tmp), runs_dir=tmp / "runs", run_id="site", checks_path=CHECKS)
    table = pd.read_csv(out.run_dir / "design_table.csv")
    return {"report": out.report, "table": table}


PAPER = {"label": "invented paper", "summary": {"flags": 2, "passes": 1, "not_checkable": 12,
                                                 "flagged_ids": ["P5", "P6"]},
         "results": [{"check_id": "P%d" % i, "status": ("flag" if i in (5, 6) else "pass" if i == 2
                                                         else "not checkable"),
                      "detail": ("pv: 1,990 kW at 11:00 vs rating 990 kW" if i == 5 else "detail %d" % i),
                      "pages": [7, 19] if i == 5 else []} for i in range(1, 16)]}
REVIEW = {"model": "muse-wonder-1.0", "points": [
    {"point": "Is the battery cost < 300 USD/kWh realistic for a remote island?", "addressed_in": "Sensitivity"},
    {"point": "Grid forming inverters are not costed.", "addressed_in": None}]}


def ascii_ok(page):
    page.encode("ascii")
    for bad in FORBIDDEN:
        assert bad not in page.lower(), bad


# ---------- helpers ----------

def test_esc():
    assert esc("a < b & \"c\"") == "a &lt; b &amp; &quot;c&quot;"
    assert esc("Caf\u00e9 \u2013 x") == "Caf&#233; &#8211; x"
    assert esc(12.5) == "12.5"


def test_css_and_titles():
    assert isinstance(SITE_CSS, str) and len(SITE_CSS) > 50
    SITE_CSS.encode("ascii")
    assert "@import" not in SITE_CSS and "url(" not in SITE_CSS
    assert [k for k, _ in CARD_TITLES] == ["best_pv_kwp", "best_battery_kwh", "best_lcoe_usd_per_kwh",
                                           "diesel_only_lcoe_usd_per_kwh", "best_renewable_pct", "fuel_saved_l_yr",
                                           "co2_saved_t_yr", "break_even_fuel_usd_per_l"]
    assert CARD_TITLES[2] == ("best_lcoe_usd_per_kwh", "Cost of electricity")
    assert CARD_TITLES[7][1] == "Diesel price where PV starts to pay"


def _facts(best, dsl, change):
    return {"site": {"name": "Pulau Contoh"}, "facts": {
        "best_lcoe_usd_per_kwh": {"value": best, "text": "%.3f" % best},
        "diesel_only_lcoe_usd_per_kwh": {"value": dsl, "text": "%.3f" % dsl},
        "lcoe_change_pct": {"value": change, "text": "%.1f" % change}}}


def test_headline_yes_and_no():
    assert headline(_facts(0.251, 0.354, -29.1)) == (
        "Yes. Solar plus battery cuts the cost of electricity on Pulau Contoh from 0.354 to 0.251 USD/kWh (-29.1%).")
    assert headline(_facts(0.354, 0.354, 0.0)) == (
        "No. On Pulau Contoh the least cost design costs 0.354 USD/kWh against 0.354 USD/kWh for diesel only.")


# ---------- charts ----------

def tiny_table():
    rows = []
    for pv in (0.0, 500.0, 1000.0):
        for b in (0.0, 2000.0):
            rows.append({"pv_kwp": pv, "battery_kwh": b, "lcoe_usd_per_kwh": 0.40 - pv / 10000.0 - b / 100000.0,
                         "unserved_frac": 0.01 if (pv, b) == (1000.0, 2000.0) else 0.0})
    return pd.DataFrame(rows)


def test_heatmap():
    svg = heatmap_svg(tiny_table(), 1000.0, 0.0, 0.001)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    cells = re.findall(r'<rect class="cell[^"]*"', svg)
    assert len(cells) == 6
    assert svg.count('class="cell best"') == 1 and svg.count('class="cell infeasible"') == 1
    assert "<title>PV 1,000 kWp, battery 0 kWh: 0.300 USD/kWh</title>" in svg
    assert "<title>PV 0 kWp, battery 2,000 kWh: 0.380 USD/kWh</title>" in svg
    assert "PV kWp" in svg and "Battery kWh" in svg
    ascii_ok(svg)
    fills = re.findall(r'<rect class="cell"[^>]*fill="([^"]+)"', svg)
    assert len(fills) == 4 and len(set(fills)) >= 3


def test_heatmap_dark_is_cheapest():
    t = tiny_table()
    svg = heatmap_svg(t, 1000.0, 0.0, 0.001)
    best_fill = re.search(r'<rect class="cell best"[^>]*fill="([^"]+)"', svg).group(1)
    worst = re.search(r'<rect class="cell"[^>]*fill="([^"]+)"[^>]*>\s*<title>PV 0 kWp, battery 0 kWh', svg)
    assert worst is not None and worst.group(1) != best_fill


SENS = [
    {"input": "pv_capex_usd_per_kwp", "factor": 0.8, "base_design_lcoe_usd_per_kwh": 0.245},
    {"input": "battery_capex_usd_per_kwh", "factor": 1.2, "base_design_lcoe_usd_per_kwh": 0.262},
    {"input": "lonely_input", "factor": 1.2, "base_design_lcoe_usd_per_kwh": 0.300},
    {"input": "fuel_price_usd_per_l", "factor": 0.8, "base_design_lcoe_usd_per_kwh": 0.231},
    {"input": "fuel_price_usd_per_l", "factor": 1.2, "base_design_lcoe_usd_per_kwh": 0.271},
    {"input": "battery_capex_usd_per_kwh", "factor": 0.8, "base_design_lcoe_usd_per_kwh": 0.240},
    {"input": "pv_capex_usd_per_kwp", "factor": 1.2, "base_design_lcoe_usd_per_kwh": 0.257},
]


def test_tornado():
    svg = tornado_svg(SENS, 0.251)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    bars = re.findall(r'<g class="bar">(.*?)</g>', svg, flags=re.S)
    assert len(bars) == 3
    assert "Diesel price" in bars[0] and "0.231 to 0.271" in bars[0]  # plain labels since T18a
    assert "Battery price" in bars[1] and "0.240 to 0.262" in bars[1]
    assert "PV price" in bars[2] and "0.245 to 0.257" in bars[2]
    assert "lonely_input" not in svg
    assert "<line" in svg
    ascii_ok(svg)


def test_weather():
    rows = [{"case": "CAMS", "ghi_kwh_m2_yr": 1731.0}, {"case": "PVGIS-ERA5 TMY", "ghi_kwh_m2_yr": 2049.2}]
    svg = weather_svg(rows)
    bars = re.findall(r'<g class="bar">(.*?)</g>', svg, flags=re.S)
    assert len(bars) == 2 and "CAMS" in bars[0] and "1,731 kWh/m2/yr" in bars[0]
    assert "2,049 kWh/m2/yr" in bars[1]
    widths = [float(re.search(r'<rect[^>]*width="([0-9.]+)"', b).group(1)) for b in bars]
    assert widths[0] < widths[1]
    assert widths[0] / widths[1] == pytest.approx(1731.0 / 2049.2, rel=0.02)


# ---------- the study page ----------

def test_study_page_structure(study):
    page = render_study_html(study["report"], study["table"])
    ascii_ok(page)
    assert page.startswith("<!DOCTYPE html>") and '<meta charset="utf-8">' in page
    assert page.count("<style>") == 1 and "<title>AutoSolar study: Karimunjawa</title>" in page
    ids = re.findall(r'<section id="([a-z]+)"', page)
    assert ids == ["answer", "confirm", "firm", "designs", "sensitivity", "weather", "range", "checks", "inputs",
                   "scope", "sources"]
    assert page.count("<svg") == 3
    assert study["report"]["run_hash"] in page
    assert esc(headline(study["report"])) in page
    assert page == render_study_html(study["report"], study["table"])


def test_study_page_numbers(study):
    r = study["report"]
    page = render_study_html(r, study["table"])
    for key, title in CARD_TITLES:
        f = r["facts"][key]
        assert esc(title) in page
        assert esc(f["text"] + " " + f["unit"] + " (" + f["label"] + ")") in page, key
    for item in r["firmness"]["items"]:
        assert esc(item["title"]) in page and esc(item["text"]) in page
    for row in r["range_table"] + r["gates"] + r["inputs_table"]:
        for cell in row["cells"]:
            assert esc(cell) in page
    for line in r["firmness"]["out_of_scope"]:
        assert "<li>" + esc(line) + "</li>" in page
    cells = re.findall(r'<rect class="cell[^"]*"', page)
    assert len(cells) == len(study["table"])


def test_study_page_sources_links(study):
    r = json.loads(json.dumps(study["report"]))
    r["sources"] = r["sources"] + ["Sourced input x: A title, https://example.org/a?b=1&c=2, doi:10.1/x",
                                   "Plain text with no link"]
    page = render_study_html(r, study["table"])
    assert '<a href="https://example.org/a?b=1&amp;c=2">' in page
    assert "<li>Plain text with no link</li>" in page


def test_study_page_with_paper_and_review(study):
    page = render_study_html(study["report"], study["table"], paper_check=PAPER, review=REVIEW)
    ascii_ok(page)
    ids = re.findall(r'<section id="([a-z]+)"', page)
    assert ids == ["answer", "confirm", "firm", "designs", "sensitivity", "weather", "range", "paper", "review",
                   "checks", "inputs", "scope", "sources"]
    assert "Flags 2, passes 1, not checkable 12" in page
    assert page.count('<tr class="flag">') == 2
    assert "pv: 1,990 kW at 11:00 vs rating 990 kW" in page and "7, 19" in page
    assert "it is not a finding about the authors." in page
    assert "Is the battery cost &lt; 300 USD/kWh realistic for a remote island?" in page
    assert "muse-wonder-1.0" in page
    review_block = page[page.index('<section id="review"'):page.index('<section id="checks"')]
    assert review_block.count("<li>") == 2 and "Sensitivity" in review_block and "open" in review_block


def test_study_page_escapes_report_text(study):
    r = json.loads(json.dumps(study["report"]))
    r["question"] = "Is <b>solar</b> worth it? \u2013 yes"
    page = render_study_html(r, study["table"])
    assert "Is &lt;b&gt;solar&lt;/b&gt; worth it? &#8211; yes" in page
    assert "<b>solar</b>" not in page


def test_study_page_without_firmness(study):
    r = json.loads(json.dumps(study["report"]))
    r["firmness"] = None
    page = render_study_html(r, study["table"])
    ids = re.findall(r'<section id="([a-z]+)"', page)
    assert "firm" not in ids and "scope" not in ids and ids[0] == "answer"


# ---------- index ----------

def test_index():
    cards = [{"href": "abc.html", "site": "Karimunjawa", "question": "Is <solar> worth it?",
              "headline": "Yes. Cheaper.", "run_hash": "abc"},
             {"href": "def.html", "site": "Pulau Contoh", "question": "q2", "headline": "No.", "run_hash": "def"}]
    page = render_index_html(cards)
    ascii_ok(page)
    assert "<title>AutoSolar Researcher: study gallery</title>" in page
    links = re.findall(r'<a class="study" href="([^"]+)"', page)
    assert links == ["abc.html", "def.html"]
    assert "<h2>Karimunjawa</h2>" in page and "Is &lt;solar&gt; worth it?" in page
    assert "No studies yet." not in page
    empty = render_index_html([])
    assert "No studies yet." in empty and '<a class="study"' not in empty
