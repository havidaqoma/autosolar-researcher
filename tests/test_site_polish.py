"""Acceptance tests for T13b (autosolar/site.py polish). Written by the orchestrator. No network."""
import json
import re

import pytest

import test_site as tsite
from autosolar.site import SITE_CSS, caveats, heatmap_svg, render_study_html

study = tsite.study


def _items(report):
    return {i["key"]: i for i in report["firmness"]["items"]}


def test_caveats_text(study):
    r = study["report"]
    it = _items(r)
    c = caveats(r)
    assert len(c) == 8
    assert c[0] == ("Near tie: " + it["near_tie_count"]["text"] + " designs are within " + it["near_tie_pct"]["text"]
                    + "% of the least cost, from " + it["near_tie_pv_kwp_min"]["text"] + " to "
                    + it["near_tie_pv_kwp_max"]["text"] + " kWp of PV.")
    assert c[1] == ("Reserve case: if " + it["reserve_units"]["text"] + " diesel unit(s) must run in every hour, the "
                    "least cost design is " + it["reserve_pv_kwp"]["text"] + " kWp with "
                    + it["reserve_battery_kwh"]["text"] + " kWh at " + it["reserve_lcoe_usd_per_kwh"]["text"]
                    + " USD/kWh, and the main design would cost "
                    + it["reserve_main_design_lcoe_usd_per_kwh"]["text"] + " USD/kWh.")
    assert c[2] == ("Diesel unit size: with units of " + it["alt_diesel_unit_kw"]["text"] + " kW instead, diesel only "
                    "costs " + it["alt_diesel_only_lcoe_usd_per_kwh"]["text"] + " USD/kWh and the least cost design is "
                    + it["alt_pv_kwp"]["text"] + " kWp with " + it["alt_battery_kwh"]["text"] + " kWh at "
                    + it["alt_lcoe_usd_per_kwh"]["text"] + " USD/kWh (" + it["alt_saving_pct"]["text"]
                    + "% below diesel only); if " + it["reserve_units"]["text"] + " diesel unit(s) must run in every hour, "
                    "that design would cost " + it["alt_reserve_main_design_lcoe_usd_per_kwh"]["text"]
                    + " USD/kWh and the least cost design is " + it["alt_reserve_pv_kwp"]["text"] + " kWp with "
                    + it["alt_reserve_battery_kwh"]["text"] + " kWh at " + it["alt_reserve_lcoe_usd_per_kwh"]["text"]
                    + " USD/kWh.")
    assert c[3].startswith("Island prices: ")
    assert c[4].startswith("Diesel engine hours: ")
    assert c[5] == ("Land: the main design needs " + it["land_need_ha"]["text"] + " ha of the "
                    + it["land_site_ha"]["text"] + " ha set aside (fits: " + it["land_fits"]["text"] + ").")
    assert c[6] == ("Published design size: " + it["reference_pv_kwp"]["text"] + " kWp of PV with no battery gives "
                    + it["reference_lcoe_usd_per_kwh"]["text"] + " USD/kWh.")
    assert c[7] == ("Cost: this study used " + it["total_cost_usd"]["text"] + " USD of model API calls, of which "
                    + it["sourcing_cost_usd"]["text"] + " USD was the web search that sourced its inputs.")


def test_caveats_empty_without_firmness(study):
    r = json.loads(json.dumps(study["report"]))
    r["firmness"] = None
    assert caveats(r) == []
    r.pop("firmness")
    assert caveats(r) == []
    page = render_study_html(r, study["table"])
    assert 'class="caveats"' not in page


def test_caveats_on_page(study):
    page = render_study_html(study["report"], study["table"])
    ans = page[page.index('<section id="answer"'):page.index('<section id="firm"')]
    head = ans.index('class="headline"')
    ul = ans.index('<ul class="caveats">')
    cards = ans.index('<div class="cards">')
    assert head < ul < cards
    lis = re.findall(r"<li>(.*?)</li>", ans[ul:cards], flags=re.S)
    assert lis == [tsite.esc(x) for x in caveats(study["report"])]
    assert ans[cards:].count('<div class="card">') == 8


def test_scroll_wrappers(study):
    page = render_study_html(study["report"], study["table"], paper_check=tsite.PAPER, review=tsite.REVIEW)
    n_svg = page.count("<svg")
    n_table = page.count("<table")
    wrapped_svg = len(re.findall(r'<div class="scroll">\s*<svg', page))
    wrapped_table = len(re.findall(r'<div class="scroll">\s*<table', page))
    assert n_svg == 3 and wrapped_svg == n_svg
    assert n_table >= 5 and wrapped_table == n_table
    css = SITE_CSS.replace(" ", "")
    assert ".scroll{" in css and "overflow-x:auto" in css
    assert ".cards{" in css and ("grid-template-columns" in css or "display:flex" in css)


def test_heatmap_legend_and_label():
    t = tsite.tiny_table()
    svg = heatmap_svg(t, 1000.0, 0.0, 0.001)
    legend = re.search(r'<g class="legend">(.*?)</g>', svg, flags=re.S)
    assert legend is not None
    body = legend.group(1)
    assert "lowest 0.300 USD/kWh" in body and "highest 0.400 USD/kWh" in body
    assert "grey: unserved energy above the limit" in body
    assert body.count("<rect") >= 2
    best_fill = re.search(r'<rect class="cell best"[^>]*fill="([^"]+)"', svg).group(1)
    assert best_fill in body
    lab = re.search(r'<text([^>]*)>Battery kWh</text>', svg)
    assert lab is not None
    attrs = lab.group(1)
    xm = re.search(r'\bx="(-?[0-9.]+)"', attrs)
    assert "rotate(-90" in attrs or (xm is not None and float(xm.group(1)) >= 0)


def test_heatmap_legend_without_infeasible():
    t = tsite.tiny_table()
    t["unserved_frac"] = 0.0
    svg = heatmap_svg(t, 1000.0, 2000.0, 0.001)
    legend = re.search(r'<g class="legend">(.*?)</g>', svg, flags=re.S).group(1)
    assert "lowest 0.280 USD/kWh" in legend and "grey" not in legend
