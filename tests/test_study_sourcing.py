"""Acceptance tests for T10c (autosolar/study.py reads a sourcing file; report polish). Written by the orchestrator.
No network: the search answers, source pages, DOI handle answer and judge are fakes; weather is synthetic."""
import dataclasses
import hashlib
import json
import re

import pytest

import test_study as ts
from autosolar.sourcing import Target, source_inputs, write_sourcing
from autosolar.study import FACT_SPECS, FACT_TITLES, REPORT_SCHEMA, fmt_number, render_markdown, run_study

JUDGE = "Muse Glimmer (test fake)"
PV_URL = "https://www.frontiersin.org/articles/10.3389/fsuep.2024.1308441/full"
PV_DOI = "10.3389/fsuep.2024.1308441"
FUEL_URL = "https://openknowledge.worldbank.org/fuel.html"
WACC_URL = "https://www.iea.org/commentaries/cost-of-capital"
PV_QUOTE = "The unsubsidised initial CAPEX in 2022 value is set at 1,119 USD/kW for utility PV."
FUEL_QUOTE = "Diesel 6,800 11,420 9,110 67.9 retail prices"
WACC_QUOTE = ("The median weighted average cost of capital (WACC, nominal, post-tax and in local currency) for solar "
              "PV in Indonesia was 9.4% in 2024.")
PAGES = {PV_URL: "<p>" + PV_QUOTE + " Single cost values simplify.</p>",
         FUEL_URL: "<p>Table 3. " + FUEL_QUOTE + " per litre</p>",
         WACC_URL: "<p>" + WACC_QUOTE + "</p>"}
T_PV = Target("pv_capex_usd_per_kwp", "USD/kWp", 300.0, 4000.0, "installed cost of utility PV in Indonesia", "pv")
T_FUEL = Target("fuel_price_usd_per_l", "USD/L", 0.3, 2.5, "industrial diesel price in Indonesia", "fuel")
T_WACC = Target("discount_rate_frac", "frac", 0.02, 0.25, "real discount rate for PV in Indonesia", "rate")
T_BATT = Target("battery_capex_usd_per_kwh", "USD/kWh", 50.0, 1500.0, "battery pack cost", "battery")
MISSING_URL = "https://example.org/missing.pdf"
ANSWERS = [
    {"value": 1119.0, "unit": "USD/kW", "currency_year": 2022, "url": PV_URL, "doi": PV_DOI,
     "title": "A comparative assessment of policy induced diffusion pathways", "quote": PV_QUOTE},
    {"value": 11420, "unit": "Rp/liter", "currency_year": 2023, "url": FUEL_URL, "doi": None,
     "title": "Indonesia\u2019s Fuel Subsidies Reforms", "quote": FUEL_QUOTE},
    {"value": 9.4, "unit": "%", "currency_year": None, "url": WACC_URL, "doi": None, "title": "High cost of capital",
     "quote": WACC_QUOTE},
    {"value": 5000, "unit": "USD/kWh", "currency_year": 2024, "url": MISSING_URL, "doi": None,
     "title": "Missing report", "quote": "Battery packs cost 5000 USD/kWh in this report."},
]
TITLES = {
    "site_lat_deg": "Site latitude",
    "site_lon_deg": "Site longitude",
    "weather_spread_pct": "Spread of annual sunshine across the weather sources",
    "demand_kwh_yr": "Annual electricity demand",
    "demand_peak_kw": "Peak demand",
    "best_pv_kwp": "Least cost design: PV size",
    "best_battery_kwh": "Least cost design: battery energy",
    "best_battery_kw": "Least cost design: battery power",
    "best_lcoe_usd_per_kwh": "Least cost design: cost of electricity (LCOE)",
    "best_npc_usd": "Least cost design: net present cost",
    "best_capex_usd": "Least cost design: up front capital cost",
    "best_renewable_pct": "Least cost design: renewable share",
    "best_curtailed_pct": "Least cost design: PV energy curtailed",
    "best_fuel_l_yr": "Least cost design: diesel fuel",
    "best_co2_t_yr": "Least cost design: CO2",
    "diesel_only_lcoe_usd_per_kwh": "Diesel only: cost of electricity (LCOE)",
    "diesel_only_fuel_l_yr": "Diesel only: diesel fuel",
    "diesel_only_co2_t_yr": "Diesel only: CO2",
    "fuel_saved_l_yr": "Diesel fuel saved",
    "co2_saved_t_yr": "CO2 saved",
    "lcoe_change_pct": "Change in cost of electricity against diesel only",
    "break_even_fuel_usd_per_l": "Diesel price at which PV starts to pay",
    "api_cost_usd": "Model API cost of this study",
}


class SearchResult:
    def __init__(self, answer):
        self.text = json.dumps(answer)
        self.cost_usd = 0.03


class SearchClient:
    def __init__(self):
        self.answers = list(ANSWERS)

    def respond(self, *args, **kwargs):
        return SearchResult(self.answers.pop(0))


class Page:
    def __init__(self, status, content, url):
        self.status_code, self.content, self.url, self.headers = status, content, url, {}


def page_get(url, **kwargs):
    if url == "https://doi.org/api/handles/" + PV_DOI:
        return Page(200, b'{"responseCode": 1}', url)
    if url in PAGES:
        return Page(200, PAGES[url].encode("utf-8"), url)
    return Page(404, b"", url)


def judge(prompt):
    if "real discount rate" in prompt:
        return '{"supports": false, "reason": "The quote gives a nominal rate."}'
    return '{"supports": true, "reason": "The quote states the value."}'


def make_sourcing(tmp):
    base_path = ts.small_inputs(tmp)
    base_raw = json.loads(base_path.read_text(encoding="utf-8"))
    raw, rows = source_inputs(base_raw, [T_PV, T_FUEL, T_WACC, T_BATT], client=SearchClient(), run_id="src",
                              http_get=page_get, judge_fn=judge, judge_name=JUDGE, fx_idr_per_usd=16500.0)
    meta = {"run_id": "src", "judge": JUDGE}
    spath = tmp / "sourcing.json"
    write_sourcing(spath, raw, rows, meta)
    ipath = tmp / "inputs_sourced.json"
    ipath.write_text(json.dumps(raw), encoding="utf-8")
    return base_path, ipath, spath, raw, rows, meta


@pytest.fixture(scope="module")
def sourced(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("sourced")
    base_path, ipath, spath, raw, rows, meta = make_sourcing(tmp)
    out = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                    inputs_path=ipath, runs_dir=tmp / "runs", run_id="t", sourcing_path=spath)
    plain = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                      inputs_path=ipath, runs_dir=tmp / "runs_plain", run_id="t")
    return {"out": out, "plain": plain, "raw": raw, "rows": rows, "meta": meta, "tmp": tmp,
            "base_path": base_path, "ipath": ipath, "spath": spath}


def _hash(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()[:16]


# ---------- sourcing file in the study ----------

def test_sourcing_fixture_as_expected(sourced):
    assert [r.status for r in sourced["rows"]] == ["checked", "checked", "assumed", "assumed"]


def test_g6_row(sourced):
    gates = sourced["out"].report["gates"]
    assert [g["gate"] for g in gates] == ["G3 PV physics"] * 4 + [
        "G1 energy balance", "G2 battery", "G4 diesel", "G5 weather spread", "G6 sourced inputs", "G7 grid edge",
        "G8 LCOE twins"]
    g6 = gates[8]
    assert (g6["scope"], g6["passed"], g6["detail"]) == ("inputs", True, "2 of 4 sourced inputs checked, 2 kept assumed")
    assert g6["cells"] == ["G6 sourced inputs", "inputs", "yes", "2 of 4 sourced inputs checked, 2 kept assumed"]


def test_plain_run_unchanged_shape(sourced):
    r = sourced["plain"].report
    assert "G6 sourced inputs" not in [g["gate"] for g in r["gates"]]
    assert r["sourcing"] is None
    assert "## Sourced inputs" not in sourced["plain"].markdown


def test_run_hash_rules(sourced):
    out, plain = sourced["out"], sourced["plain"]
    coords = out.report["weather_coords_deg"]
    base = {"schema": REPORT_SCHEMA, "weather_coords_deg": coords, "inputs": sourced["raw"]}
    assert plain.run_hash == _hash(base)
    with_rows = dict(base, sourcing=[dataclasses.asdict(r) for r in sourced["rows"]])
    assert out.run_hash == _hash(with_rows) and out.run_hash != plain.run_hash


def test_sourcing_rows_and_cells(sourced):
    s = sourced["out"].report["sourcing"]
    assert s["meta"] == sourced["meta"]
    assert [x["input"] for x in s["rows"]] == ["pv_capex_usd_per_kwp", "fuel_price_usd_per_l", "discount_rate_frac",
                                         "battery_capex_usd_per_kwh"]
    for x, r in zip(s["rows"], sourced["rows"]):
        assert {k: v for k, v in x.items() if k != "cells"} == dataclasses.asdict(r)
    assert s["rows"][0]["cells"] == [
        "pv_capex_usd_per_kwp", "checked", "1119.0", "USD/kWp", "paper", "1119 USD/kW",
        "A comparative assessment of policy induced diffusion pathways", PV_URL, "1", "exact", "none"]
    assert s["rows"][1]["cells"] == [
        "fuel_price_usd_per_l", "checked", "0.692121", "USD/L", "docs", "11420 Rp/liter",
        "Indonesia's Fuel Subsidies Reforms", FUEL_URL, "1", "exact", "none"]
    assert s["rows"][2]["cells"] == [
        "discount_rate_frac", "assumed", "0.08", "frac", "assumed", "9.4 %", "High cost of capital", WACC_URL, "1",
        "exact", "judge says not supported: The quote gives a nominal rate."]
    assert s["rows"][3]["cells"] == [
        "battery_capex_usd_per_kwh", "assumed", "300.0", "USD/kWh", "assumed", "5000 USD/kWh", "Missing report",
        MISSING_URL, "none", "not run", "value 5000 USD/kWh outside band [50, 1500]; fetch: HTTP 404"]


def test_sourced_values_used(sourced):
    rows = {x["name"]: x for x in sourced["out"].report["inputs_table"]}
    assert rows["fuel_price_usd_per_l"]["value"] == 0.692121 and rows["fuel_price_usd_per_l"]["label"] == "docs"
    assert rows["pv_capex_usd_per_kwp"]["label"] == "paper"
    assert rows["discount_rate_frac"]["value"] == 0.08 and rows["discount_rate_frac"]["label"] == "assumed"


def test_sources_lines(sourced):
    src = sourced["out"].report["sources"]
    assert ("Sourced input pv_capex_usd_per_kwp: A comparative assessment of policy induced diffusion pathways, "
            + PV_URL + ", doi:" + PV_DOI) in src
    assert "Sourced input fuel_price_usd_per_l: Indonesia's Fuel Subsidies Reforms, " + FUEL_URL in src
    assert not any(s.startswith("Sourced input discount_rate_frac") for s in src)
    plain_src = sourced["plain"].report["sources"]
    assert src[:len(plain_src)] == plain_src and len(src) == len(plain_src) + 2


def test_markdown_sourced_block(sourced):
    out = sourced["out"]
    md = out.markdown
    pos = [md.index(h + "\n") for h in ("## Inputs", "## Sourced inputs", "## Sources")]
    assert pos == sorted(pos)
    block = md[pos[1]:pos[2]]
    intro = ("2 of 4 inputs were sourced by web search and checked: the quote was found in the fetched source, the "
             "value appears in the quote, the DOI resolves when one is given, and the support judge (" + JUDGE
             + ") agreed. The others keep their assumed value; the last column says why.")
    header = ("| Input | Status | Value used | Unit | Label | As written | Source | URL | Page | Quote match | Why kept "
              "assumed |\n|---|---|---|---|---|---|---|---|---|---|---|\n")
    assert block.startswith("## Sourced inputs\n\n" + intro + "\n\n" + header)
    for x in out.report["sourcing"]["rows"]:
        assert ("| " + " | ".join(x["cells"]) + " |\n") in block
    assert block.endswith(" |\n\n")
    assert render_markdown(out.report) == md
    md.encode("ascii")


def test_judge_name_fallback(sourced):
    report = json.loads(json.dumps(sourced["out"].report))
    report["sourcing"]["meta"] = {}
    assert "support judge (not named) agreed" in render_markdown(report)
    report.pop("sourcing")
    assert "## Sourced inputs" not in render_markdown(report)


def test_mismatch_refused_before_any_call(sourced, tmp_path):
    client, get, wfn = ts.FakeClient(), ts.FakeGet(), ts.WeatherFn()
    with pytest.raises(ValueError, match="does not match the sourcing file"):
        run_study(ts.QUESTION, client=client, http_get=get, weather_fn=wfn, inputs_path=sourced["base_path"],
                  runs_dir=tmp_path / "runs", run_id="t", sourcing_path=sourced["spath"])
    assert client.calls == 0 and get.calls == 0 and wfn.calls == []


def test_tampered_sourcing_refused(sourced, tmp_path):
    doc = json.loads(sourced["spath"].read_text(encoding="utf-8"))
    doc["inputs"]["values"]["fuel_price_usd_per_l"]["value"] = 0.5
    bad = tmp_path / "sourcing_bad.json"
    bad.write_text(json.dumps(doc), encoding="utf-8")
    ipath = tmp_path / "inputs_bad.json"
    ipath.write_text(json.dumps(doc["inputs"]), encoding="utf-8")
    client, get, wfn = ts.FakeClient(), ts.FakeGet(), ts.WeatherFn()
    with pytest.raises(ValueError, match="fails G6"):
        run_study(ts.QUESTION, client=client, http_get=get, weather_fn=wfn, inputs_path=ipath,
                  runs_dir=tmp_path / "runs", run_id="t", sourcing_path=bad)
    assert client.calls == 0 and get.calls == 0 and wfn.calls == []


def test_rerun_with_sourcing_reuses(sourced):
    client, wfn = ts.FakeClient(), ts.WeatherFn()
    again = run_study(ts.QUESTION, client=client, http_get=ts.FakeGet(), weather_fn=wfn,
                      inputs_path=sourced["ipath"], runs_dir=sourced["tmp"] / "runs", run_id="t2",
                      sourcing_path=sourced["spath"])
    assert again.reused is True and again.run_hash == sourced["out"].run_hash and wfn.calls == []


# ---------- polish ----------

def test_fact_titles_constant():
    assert list(FACT_TITLES) == [k for k, _, _, _ in FACT_SPECS]
    assert FACT_TITLES == TITLES


def test_answer_lines_use_titles(sourced):
    out = sourced["plain"]
    for key, unit, label, _ in FACT_SPECS:
        f = out.report["facts"][key]
        assert ("- " + TITLES[key] + ": " + f["text"] + " " + unit + " (" + label + ")\n") in out.markdown
    assert "- best lcoe usd per kwh:" not in out.markdown


def test_gate_details_rounded(sourced):
    r = sourced["plain"].report
    weather = {x["case"]: x for x in r["weather_table"]}
    for g in r["gates"]:
        d = g["detail"]
        if g["gate"] == "G3 PV physics":
            w = weather[g["scope"]]
            assert d == ("yield kWh/kWp " + fmt_number(w["yield_kwh_kwp_yr"], 0) + ", PR "
                         + fmt_number(w["performance_ratio_frac"], 2))
        elif g["gate"] == "G2 battery":
            assert re.fullmatch(r"soc band kWh \[[0-9,]+, [0-9,]+\], discharge kWh [0-9,]+ against stored kWh "
                                r"[0-9,]+", d), d
        elif g["gate"] == "G4 diesel":
            assert d == "diesel never runs" or re.fullmatch(r"worst margin kW above min load: -?[0-9,]+\.[0-9]", d), d
        elif g["gate"] == "G8 LCOE twins":
            assert re.fullmatch(r"max twin gap frac: [0-9]\.[0-9]e[+-][0-9]{2}", d), d
        elif g["gate"] == "G1 energy balance":
            assert d.startswith("max hourly gap kW: pv ")
    assert re.search(r"\d\.\d{6,}", json.dumps([g["cells"] for g in r["gates"]])) is None


def test_grid_edge_notes(sourced):
    flagged = 0
    for report in (sourced["out"].report, sourced["plain"].report):
        pv_top = max(report["grid"]["pv_kwp"])
        batt_top = max(report["grid"]["battery_kwh"])
        for x in report["range_table"]:
            if x["pv_kwp"] is None:
                want = "no feasible design"
            else:
                want = "on grid edge" if (x["pv_kwp"] == pv_top or x["battery_kwh"] == batt_top) else ""
            assert x["note"] == want and x["cells"][-1] == want, x
            flagged += want == "on grid edge"
        for x in report["sensitivity_table"]:
            if x["least_cost_pv_kwp"] is None:
                want = "no feasible design"
            else:
                on_edge = x["least_cost_pv_kwp"] == pv_top or x["least_cost_battery_kwh"] == batt_top
                want = "on grid edge" if on_edge else ""
            assert x["note"] == want and x["cells"][-1] == want, x
            flagged += want == "on grid edge"
    assert flagged > 0
