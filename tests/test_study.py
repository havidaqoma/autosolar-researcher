"""Acceptance tests for T09b (autosolar/study.py). Written by the orchestrator. No network.

The weather is synthetic (a clear sky shaped day, scaled per source); the question, model text and geocoder
answer are the measured ones from T09a."""
import dataclasses
import hashlib
import json
import math
import pathlib

import numpy as np
import pandas as pd
import pytest

import autosolar.study as study
from autosolar.demand import HIRON_2021_SOURCE, build_demand_cases
from autosolar.dispatch import Battery, DieselFleet
from autosolar.econ import CostInputs
from autosolar.pv import PVDesign, simulate_pv
from autosolar.request import UnsupportedQuestion
from autosolar.study import (DEMAND_RADIUS_KM, FACT_SPECS, INPUT_NAMES, INT_INPUT_NAMES, KARIMUNJAWA_DEG, LABELS,
                             REPORT_SCHEMA, GateFailed, ReportNumberMismatch, StudyOutput, UnsupportedSite,
                             fmt_number, haversine_km, load_inputs, number_tokens, render_markdown, run_study,
                             scan_report_numbers)
from autosolar.sweep import (break_even_fuel_price_usd_per_l, cost_table, dispatch_grid, least_cost)
from autosolar.weather import CASE_NAMES, WeatherCases

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = ROOT / "config" / "default_inputs.json"
GEO = ROOT / "tests" / "fixtures" / "geocode"
QUESTION = "Is solar plus battery worth it for Karimunjawa? The island runs on diesel."
KARIMUNJAWA_TEXT = ('{"site_name": "Karimunjawa", "country": "Indonesia", "question_type": '
                    '"pv_battery_for_diesel_grid", "language": "en"}')
SCALES = {"CAMS": 1.0, "NASA POWER": 1.08, "PVGIS-ERA5 TMY": 1.15, "GSA scaled": 1.04}
HEADINGS = ["## Answer", "## Weather sources", "## Range of the answer", "## Sensitivity", "## Checks",
            "## Inputs", "## Sources"]


class FakeResult:
    def __init__(self, text):
        self.text = text
        self.cost_usd = 0.00016
        self.model = "muse-spark-1.3-contributor"


class FakeClient:
    def __init__(self, text=KARIMUNJAWA_TEXT):
        self.text = text
        self.calls = 0

    def respond(self, *args, **kwargs):
        self.calls += 1
        return FakeResult(self.text)


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeGet:
    def __init__(self, fixture="karimunjawa.json"):
        self.payload = json.loads((GEO / fixture).read_text(encoding="utf-8"))
        self.calls = 0

    def __call__(self, url, **kwargs):
        self.calls += 1
        return FakeResponse(self.payload)


def synthetic_weather(lat_deg, lon_deg, scales=SCALES, peak_w_m2=640.0):
    cases, years, totals = {}, {}, {}
    for name, s in scales.items():
        if name == "PVGIS-ERA5 TMY":
            idx = pd.date_range("2019-01-01", periods=8760, freq="1h", tz="UTC")
            years[name] = None
        else:
            idx = pd.date_range("2020-01-01", periods=8784, freq="1h", tz="UTC")
            years[name] = 2020
        local_h = (idx.hour.to_numpy() + 7) % 24 + 0.5
        ghi = s * peak_w_m2 * np.clip(np.sin((local_h - 6.0) / 12.0 * np.pi), 0.0, None)
        cases[name] = pd.DataFrame({"ghi_w_m2": ghi, "temp_air_degc": 28.0, "wind_speed_m_s": 3.0}, index=idx)
        totals[name] = float(ghi.sum() / 1000.0)
    vals = list(totals.values())
    spread = 100.0 * (max(vals) - min(vals)) / min(vals)
    return WeatherCases(basis="CAMS", cases=cases, years=years, annual_ghi_kwh_m2=totals, spread_pct_all=spread,
                        spread_pct_no_era5=spread, range_required=spread > 10.0,
                        cams_annual_totals_kwh_m2={2020: totals["CAMS"]},
                        nasa_annual_totals_kwh_m2={2020: totals["NASA POWER"]},
                        gsa_annual_ghi_kwh_m2=totals["GSA scaled"], notes=["synthetic weather for tests"])


class WeatherFn:
    def __init__(self, **kw):
        self.kw = kw
        self.calls = []

    def __call__(self, lat_deg, lon_deg):
        self.calls.append((lat_deg, lon_deg))
        return synthetic_weather(lat_deg, lon_deg, **self.kw)


def small_inputs(tmp_path, **changes):
    raw = json.loads(DEFAULT_INPUTS.read_text(encoding="utf-8"))
    grid = {"pv_kwp_step": 500.0, "pv_kwp_max": 1500.0, "battery_kwh_step": 2000.0, "battery_kwh_max": 6000.0}
    grid.update(changes)
    for k, v in grid.items():
        raw["values"][k]["value"] = v
    path = tmp_path / ("inputs_" + hashlib.sha256(json.dumps(grid, sort_keys=True).encode()).hexdigest()[:8]
                       + ".json")
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("study")
    client, get, wfn = FakeClient(), FakeGet(), WeatherFn()
    out = run_study(QUESTION, client=client, http_get=get, weather_fn=wfn, inputs_path=small_inputs(tmp),
                    runs_dir=tmp / "runs", run_id="test-run")
    return {"out": out, "client": client, "get": get, "wfn": wfn, "tmp": tmp}


# ---------- constants and helpers ----------

def test_constants():
    assert REPORT_SCHEMA == "autosolar.report/2"  # T18a
    assert LABELS == ("measured", "computed", "assumed", "press", "paper", "paper (abstract)", "docs")
    assert KARIMUNJAWA_DEG == (-5.85, 110.43) and DEMAND_RADIUS_KM == 30.0
    raw = json.loads(DEFAULT_INPUTS.read_text(encoding="utf-8"))
    assert tuple(raw["values"]) == INPUT_NAMES
    assert INT_INPUT_NAMES == ("pv_life_yr", "battery_life_yr", "project_life_yr", "currency_year", "diesel_n_units")
    assert len(FACT_SPECS) == 23 and FACT_SPECS[8] == ("best_lcoe_usd_per_kwh", "USD/kWh", "computed", 3)
    assert all(lab in LABELS for _, _, lab, _ in FACT_SPECS)


def test_load_inputs_default():
    values, raw = load_inputs(DEFAULT_INPUTS)
    assert raw["schema"] == "autosolar.inputs/1"
    assert tuple(values) == INPUT_NAMES or set(values) == set(INPUT_NAMES)
    assert values["fuel_price_usd_per_l"] == 0.85 and values["diesel_unit_kw"] == 1800.0
    for k in INT_INPUT_NAMES:
        assert type(values[k]) is int
    CostInputs(**{k: values[k] for k in (f.name for f in dataclasses.fields(CostInputs))})


def _mutate(tmp_path, fn):
    raw = json.loads(DEFAULT_INPUTS.read_text(encoding="utf-8"))
    fn(raw)
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


@pytest.mark.parametrize("fn", [
    lambda r: r.update(schema="autosolar.inputs/2"),
    lambda r: r["values"].pop("swing_frac"),
    lambda r: r["values"].update(extra={"value": 1.0, "unit": "x", "label": "assumed", "note": ""}),
    lambda r: r["values"]["pv_capex_usd_per_kwp"].update(label="guess"),
    lambda r: r["values"]["pv_capex_usd_per_kwp"].update(unit=""),
    lambda r: r["values"]["pv_capex_usd_per_kwp"].update(note=None),
    lambda r: r["values"]["pv_capex_usd_per_kwp"].update(source="x"),
    lambda r: r["values"]["pv_capex_usd_per_kwp"].update(value="1000"),
    lambda r: r["values"]["pv_capex_usd_per_kwp"].update(value=True),
    lambda r: r["values"]["pv_capex_usd_per_kwp"].update(value=float("nan")),
    lambda r: r["values"]["pv_life_yr"].update(value=25.0),
    lambda r: r["values"]["diesel_n_units"].update(value=True),
    lambda r: r["values"]["pv_kwp_step"].update(value=0.0),
    lambda r: r["values"]["pv_kwp_max"].update(value=4100.0),
    lambda r: r["values"]["battery_kwh_max"].update(value=500.0),
    lambda r: r.update(values=[]),
])
def test_load_inputs_rejects(tmp_path, fn):
    with pytest.raises(ValueError):
        load_inputs(_mutate(tmp_path, fn))


@pytest.mark.parametrize("value, dec, text", [(1234.567, 1, "1,234.6"), (-0.04, 1, "0.0"), (0.30149, 3, "0.301"),
                                              (5, 0, "5"), (-12.5, 1, "-12.5"), (1234567.0, 0, "1,234,567"),
                                              (-0.4, 0, "0")])
def test_fmt_number(value, dec, text):
    assert fmt_number(value, dec) == text


@pytest.mark.parametrize("value, dec", [(True, 1), (math.nan, 1), (math.inf, 0), ("1", 0), (1.0, 9), (1.0, -1),
                                        (1.0, 1.0)])
def test_fmt_number_rejects(value, dec):
    with pytest.raises(ValueError):
        fmt_number(value, dec)


def test_number_tokens():
    text = "PV 1,250.5 kWp in m2 at G3 and S0_parse 3f9a, -5.8796 and 12. Also 7,00 and 0.301|"
    assert number_tokens(text) == ["1,250.5", "5.8796", "12", "7", "00", "0.301"]
    assert number_tokens("year 2020, 26,214 kWh") == ["2020", "26,214"]
    assert number_tokens("no digits here") == []


def test_haversine():
    assert haversine_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(2 * math.pi * 6371.0088 / 360, rel=1e-9)
    assert haversine_km(-5.8796265, 110.4329073, -5.85, 110.43) == pytest.approx(
        haversine_km(-5.85, 110.43, -5.8796265, 110.4329073))
    assert 3.0 < haversine_km(-5.8796265, 110.4329073, *KARIMUNJAWA_DEG) < 3.6


def test_scan_report_numbers():
    report = {"a": ["x 1,250 y", {"b": "0.301 USD"}], "n": 5, "k": {"999": "none"}}
    assert scan_report_numbers("1,250 and 0.301", report) == []
    assert scan_report_numbers("1,250 and 0.301 and 5 and 999 and 5", report) == ["5", "999"]


# ---------- the full run ----------

def test_output_and_files(run):
    out = run["out"]
    assert isinstance(out, StudyOutput) and out.reused is False
    assert len(out.run_hash) == 16 and out.run_dir.name == out.run_hash
    for name in ("request.json", "site.json", "inputs.json", "design_table.csv", "sensitivity.csv", "report.md",
                 "report.json"):
        assert (out.run_dir / name).is_file(), name
    assert json.loads((out.run_dir / "report.json").read_text(encoding="ascii")) == out.report
    assert (out.run_dir / "report.md").read_text(encoding="ascii") == out.markdown
    assert out.markdown.endswith("\n") and not out.markdown.endswith("\n\n")
    out.markdown.encode("ascii")
    assert run["client"].calls == 1 and run["get"].calls == 1
    assert run["wfn"].calls == [(-5.88, 110.43)]
    req_file = run["tmp"] / "runs" / "requests" / (hashlib.sha256(QUESTION.encode("utf-8")).hexdigest()[:16]
                                                    + ".json")
    cached = json.loads(req_file.read_text(encoding="utf-8"))
    assert cached["request"]["site_name"] == "Karimunjawa" and cached["site"]["osm_id"] == 450714446


def test_run_hash_rule(run):
    out = run["out"]
    raw = json.loads((out.run_dir / "inputs.json").read_text(encoding="utf-8"))
    blob = json.dumps({"schema": REPORT_SCHEMA, "weather_coords_deg": [-5.88, 110.43], "inputs": raw},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    assert out.run_hash == hashlib.sha256(blob).hexdigest()[:16]


def test_report_top_level(run):
    r = run["out"].report
    for key in ("schema", "run_hash", "question", "request", "site", "weather_coords_deg", "facts", "weather_table",
                "range_table", "sensitivity_table", "gates", "inputs_table", "sources", "grid"):
        assert key in r, key
    assert r["schema"] == REPORT_SCHEMA and r["question"] == QUESTION
    assert r["weather_coords_deg"] == [-5.88, 110.43]
    assert r["site"]["name"] == "Karimunjawa" and r["request"]["language"] == "en"
    assert HIRON_2021_SOURCE in r["sources"] and "synthetic weather for tests" in r["sources"]
    assert any("Nominatim" in s for s in r["sources"])
    assert isinstance(r["grid"]["widened"], int) and 0 <= r["grid"]["widened"] <= 2


def test_facts_format(run):
    facts = run["out"].report["facts"]
    assert list(facts) == [k for k, _, _, _ in FACT_SPECS]
    for key, unit, label, dec in FACT_SPECS:
        f = facts[key]
        assert f["unit"] == unit and f["label"] == label, key
        if f["value"] is None:
            assert key == "break_even_fuel_usd_per_l" and f["text"] == "not reached in grid"
        else:
            assert f["text"] == fmt_number(f["value"], dec), key


def recompute(run):
    """Independent recomputation of the main case with the tested T04 to T08b functions."""
    r = run["out"].report
    values, _ = load_inputs(small_inputs(run["tmp"]))
    w = synthetic_weather(-5.88, 110.43)
    pv = simulate_pv(w.cases["CAMS"], -5.88, 110.43, PVDesign(), 1.0)
    load = build_demand_cases(w.cases["CAMS"].index)["paper"].load_kw
    costs = CostInputs(**{f.name: values[f.name] for f in dataclasses.fields(CostInputs)})
    tmpl = Battery(1.0, 1.0, values["battery_round_trip_eff_frac"], values["battery_soc_min_frac"],
                   values["battery_soc_initial_frac"])
    dsl = DieselFleet(values["diesel_unit_kw"], values["diesel_n_units"], values["diesel_min_load_frac"],
                      values["fuel_intercept_l_per_h_per_kw_rated"], values["fuel_slope_l_per_kwh"])
    pts = dispatch_grid(pv.hourly["ac_kw"], load, r["grid"]["pv_kwp"], r["grid"]["battery_kwh"],
                        battery_hours=values["battery_duration_h"], battery_template=tmpl, diesel=dsl)
    table = cost_table(pts, costs, values["co2_kg_per_l"])
    best = least_cost(table, values["unserved_max_frac"])
    be = break_even_fuel_price_usd_per_l(pts, costs, values["co2_kg_per_l"], values["unserved_max_frac"])
    return values, pv, load, table, best, be


def test_facts_values_match_recomputation(run):
    facts = run["out"].report["facts"]
    values, pv, load, table, best, be = recompute(run)
    d0 = table[(table.pv_kwp == 0) & (table.battery_kwh == 0)].iloc[0]
    v = {k: f["value"] for k, f in facts.items()}
    assert v["site_lat_deg"] == pytest.approx(-5.8796265) and v["site_lon_deg"] == pytest.approx(110.4329073)
    assert v["demand_kwh_yr"] == pytest.approx(float(load.sum()))
    assert v["demand_peak_kw"] == pytest.approx(1422.0)
    assert v["best_pv_kwp"] == best.pv_kwp and v["best_battery_kwh"] == best.battery_kwh
    assert v["best_battery_kw"] == pytest.approx(best.battery_kw)
    assert v["best_lcoe_usd_per_kwh"] == pytest.approx(best.lcoe_usd_per_kwh, rel=1e-9)
    assert v["best_npc_usd"] == pytest.approx(best.npc_usd, rel=1e-9)
    assert v["best_capex_usd"] == pytest.approx(best.capex_initial_usd)
    assert v["best_renewable_pct"] == pytest.approx(100 * best.renewable_fraction_frac)
    assert v["best_curtailed_pct"] == pytest.approx(100 * best.pv_curtailed_frac)
    assert v["best_fuel_l_yr"] == pytest.approx(best.fuel_l_per_yr)
    assert v["best_co2_t_yr"] == pytest.approx(best.co2_t_per_yr)
    assert v["diesel_only_lcoe_usd_per_kwh"] == pytest.approx(d0.lcoe_usd_per_kwh, rel=1e-9)
    assert v["diesel_only_fuel_l_yr"] == pytest.approx(d0.fuel_l_per_yr)
    assert v["diesel_only_co2_t_yr"] == pytest.approx(d0.co2_t_per_yr)
    assert v["fuel_saved_l_yr"] == pytest.approx(d0.fuel_l_per_yr - best.fuel_l_per_yr)
    assert v["co2_saved_t_yr"] == pytest.approx(d0.co2_t_per_yr - best.co2_t_per_yr)
    assert v["lcoe_change_pct"] == pytest.approx(100 * (best.lcoe_usd_per_kwh / d0.lcoe_usd_per_kwh - 1))
    if math.isinf(be):
        assert v["break_even_fuel_usd_per_l"] is None
    else:
        assert v["break_even_fuel_usd_per_l"] == pytest.approx(be, rel=1e-9)
    assert v["api_cost_usd"] == pytest.approx(0.00016)
    assert v["weather_spread_pct"] == pytest.approx(synthetic_weather(-5.88, 110.43).spread_pct_all, rel=1e-12)
    assert v["weather_spread_pct"] == pytest.approx(100 * (1.15 * 365 / 366 - 1), rel=1e-9)


def test_design_table_csv(run):
    _, _, _, table, _, _ = recompute(run)
    saved = pd.read_csv(run["out"].run_dir / "design_table.csv")
    assert list(saved.columns) == list(table.columns) and len(saved) == len(table)
    assert np.allclose(saved.lcoe_usd_per_kwh, table.lcoe_usd_per_kwh, rtol=1e-9)
    grid = run["out"].report["grid"]
    assert len(saved) == len(grid["pv_kwp"]) * len(grid["battery_kwh"])
    assert grid["pv_kwp"][0] == 0.0 and grid["battery_kwh"][0] == 0.0


def test_weather_table(run):
    rows = run["out"].report["weather_table"]
    assert [x["case"] for x in rows] == list(CASE_NAMES)
    w = synthetic_weather(-5.88, 110.43)
    for x in rows:
        pv = simulate_pv(w.cases[x["case"]], -5.88, 110.43, PVDesign(), 1.0)
        assert x["yield_kwh_kwp_yr"] == pytest.approx(pv.specific_yield_kwh_kwp)
        assert x["performance_ratio_frac"] == pytest.approx(pv.performance_ratio_frac)
        assert x["ghi_kwh_m2_yr"] == pytest.approx(w.annual_ghi_kwh_m2[x["case"]])
        assert x["g3_passed"] is True
        assert x["cells"] == [x["case"], "none" if x["year"] is None else str(x["year"]),
                              fmt_number(x["ghi_kwh_m2_yr"], 0), fmt_number(x["yield_kwh_kwp_yr"], 0),
                              fmt_number(x["performance_ratio_frac"], 2), "yes"]


def test_range_table(run):
    r = run["out"].report
    rows = r["range_table"]
    assert [(x["weather"], x["demand"]) for x in rows] == [
        ("CAMS", "paper"), ("NASA POWER", "paper"), ("PVGIS-ERA5 TMY", "paper"), ("GSA scaled", "paper"),
        ("CAMS", "tourist season"), ("CAMS", "growth")]
    main = rows[0]
    assert main["lcoe_usd_per_kwh"] == pytest.approx(r["facts"]["best_lcoe_usd_per_kwh"]["value"])
    assert main["base_design_lcoe_usd_per_kwh"] == pytest.approx(main["lcoe_usd_per_kwh"])
    for x in rows:
        if x["lcoe_usd_per_kwh"] is not None:
            assert x["lcoe_usd_per_kwh"] <= x["base_design_lcoe_usd_per_kwh"] + 1e-12
    # more sun lowers the cost of the same design
    assert rows[2]["base_design_lcoe_usd_per_kwh"] < main["base_design_lcoe_usd_per_kwh"] or \
        r["facts"]["best_pv_kwp"]["value"] == 0.0


def test_range_row_recomputed_for_tmy_index(run):
    """The TMY case has its own 8760 hour index; the paper demand must be rebuilt on it."""
    r = run["out"].report
    values, _, _, _, _, _ = recompute(run)
    w = synthetic_weather(-5.88, 110.43)
    pv = simulate_pv(w.cases["PVGIS-ERA5 TMY"], -5.88, 110.43, PVDesign(), 1.0)
    load = build_demand_cases(w.cases["PVGIS-ERA5 TMY"].index)["paper"].load_kw
    costs = CostInputs(**{f.name: values[f.name] for f in dataclasses.fields(CostInputs)})
    tmpl = Battery(1.0, 1.0, values["battery_round_trip_eff_frac"], values["battery_soc_min_frac"],
                   values["battery_soc_initial_frac"])
    dsl = DieselFleet(values["diesel_unit_kw"], values["diesel_n_units"], values["diesel_min_load_frac"],
                      values["fuel_intercept_l_per_h_per_kw_rated"], values["fuel_slope_l_per_kwh"])
    pts = dispatch_grid(pv.hourly["ac_kw"], load, r["grid"]["pv_kwp"], r["grid"]["battery_kwh"],
                        battery_hours=values["battery_duration_h"], battery_template=tmpl, diesel=dsl)
    best = least_cost(cost_table(pts, costs, values["co2_kg_per_l"]), values["unserved_max_frac"])
    row = r["range_table"][2]
    assert (row["pv_kwp"], row["battery_kwh"]) == (best.pv_kwp, best.battery_kwh)
    assert row["lcoe_usd_per_kwh"] == pytest.approx(best.lcoe_usd_per_kwh, rel=1e-9)


def test_sensitivity_and_gates(run):
    r = run["out"].report
    sens = r["sensitivity_table"]
    assert len(sens) == 18 and [x["input"] for x in sens][::2] == [
        "pv_capex_usd_per_kwp", "battery_capex_usd_per_kwh", "fuel_price_usd_per_l", "discount_rate_frac", "demand",
        "diesel_om_usd_per_kwh", "fuel_intercept_l_per_h_per_kw_rated", "fuel_slope_l_per_kwh", "battery_duration_h"]
    assert all(isinstance(x["same_design"], bool) and len(x["cells"]) == 8 for x in sens)
    saved = pd.read_csv(run["out"].run_dir / "sensitivity.csv")
    assert len(saved) == 18
    gates = r["gates"]
    assert [g["gate"] for g in gates] == ["G3 PV physics"] * 4 + ["G1 energy balance", "G2 battery", "G4 diesel",
                                                                  "G5 weather spread", "G7 grid edge",
                                                                  "G8 LCOE twins"]
    assert [g["scope"] for g in gates[:4]] == list(CASE_NAMES)
    assert all(g["passed"] is True for g in gates if g["gate"] != "G7 grid edge")
    assert all(g["cells"][2] in ("yes", "no") and len(g["cells"]) == 4 for g in gates)
    assert {x["name"] for x in r["inputs_table"]} == set(INPUT_NAMES)
    row = [x for x in r["inputs_table"] if x["name"] == "fuel_price_usd_per_l"][0]
    assert row["cells"] == ["fuel_price_usd_per_l", "0.85", "USD/L", "assumed", "delivered to the island"]


def test_markdown(run):
    md = run["out"].markdown
    assert md.startswith("# AutoSolar pre-feasibility study: Karimunjawa\n")
    assert ("Question: " + QUESTION) in md and ("Run " + run["out"].run_hash + ".") in md
    pos = [md.index(h + "\n") for h in HEADINGS]
    assert pos == sorted(pos)
    f = run["out"].report["facts"]["best_lcoe_usd_per_kwh"]
    assert ("- Least cost design: cost of electricity (LCOE): " + f["text"] + " USD/kWh (computed)\n") in md
    assert "| Case | Year | GHI kWh/m2/yr (measured) | Yield kWh/kWp/yr (computed) | PR (computed) | G3 passed |\n" \
           "|---|---|---|---|---|---|\n" in md
    assert scan_report_numbers(md, run["out"].report) == []
    assert render_markdown(run["out"].report) == md


def test_markdown_ascii_and_pipes():
    report = json.loads(json.dumps(_tiny_report()))
    report["site"]["name"] = "Pulau Kemujan | Utara"
    report["question"] = "Caf\u00e9 question"
    md = render_markdown(report)
    md.encode("ascii")
    assert "Pulau Kemujan / Utara" in md and "Cafe question" in md


def _tiny_report():
    facts = {k: {"value": 1.0, "unit": u, "label": lab, "text": fmt_number(1.0, d)} for k, u, lab, d in FACT_SPECS}
    return {"schema": REPORT_SCHEMA, "run_hash": "abc", "question": "q", "request": {}, "site": {"name": "X"},
            "weather_coords_deg": [0, 0], "facts": facts, "weather_table": [], "range_table": [],
            "sensitivity_table": [], "gates": [], "inputs_table": [], "sources": ["s"], "grid": {}}


# ---------- reuse, refusal and planted faults ----------

def test_rerun_reuses_without_calls(run):
    client, get = FakeClient(), FakeGet()

    def no_weather(lat, lon):
        raise AssertionError("weather must not be fetched again")
    out2 = run_study("  " + QUESTION + " ", client=client, http_get=get, weather_fn=no_weather,
                     inputs_path=small_inputs(run["tmp"]), runs_dir=run["tmp"] / "runs", run_id="test-run-2")
    assert out2.reused is True and out2.run_hash == run["out"].run_hash
    assert out2.report == run["out"].report and out2.markdown == run["out"].markdown
    assert client.calls == 0 and get.calls == 0


def test_cached_request_new_inputs_new_run(run):
    client, get, wfn = FakeClient(), FakeGet(), WeatherFn()
    path = small_inputs(run["tmp"], pv_kwp_max=1000.0)
    out3 = run_study(QUESTION, client=client, http_get=get, weather_fn=wfn, inputs_path=path,
                     runs_dir=run["tmp"] / "runs", run_id="test-run-3")
    assert client.calls == 0 and get.calls == 0 and len(wfn.calls) == 1
    assert out3.reused is False and out3.run_hash != run["out"].run_hash


def test_other_country_refused_before_geocoder(tmp_path):
    text = ('{"site_name": "Lord Howe Island", "country": "Australia", "question_type": '
            '"pv_battery_for_diesel_grid", "language": "en"}')
    get, wfn = FakeGet("lord_howe_island.json"), WeatherFn()
    with pytest.raises(UnsupportedQuestion):
        run_study("Size a PV and battery system for Lord Howe Island in Australia.", client=FakeClient(text),
                  http_get=get, weather_fn=wfn, inputs_path=small_inputs(tmp_path), runs_dir=tmp_path / "runs",
                  run_id="r")
    assert get.calls == 0 and wfn.calls == []


def test_site_without_demand_source_refused(tmp_path):
    text = '{"site_name": "Sumba", "country": "Indonesia", "question_type": "pv_battery_for_diesel_grid", ' \
           '"language": "en"}'
    wfn = WeatherFn()
    with pytest.raises(UnsupportedSite):
        run_study("How much solar should Sumba add?", client=FakeClient(text),
                  http_get=FakeGet("sumba_no_country_filter.json"), weather_fn=wfn,
                  inputs_path=small_inputs(tmp_path), runs_dir=tmp_path / "runs", run_id="r")
    assert wfn.calls == []
    assert issubclass(UnsupportedSite, ValueError)


def test_basis_weather_failing_g3_stops(tmp_path):
    wfn = WeatherFn(scales=dict(SCALES, CAMS=1.6))
    with pytest.raises(GateFailed):
        run_study(QUESTION, client=FakeClient(), http_get=FakeGet(), weather_fn=wfn,
                  inputs_path=small_inputs(tmp_path), runs_dir=tmp_path / "runs", run_id="r")
    assert not list((tmp_path / "runs").glob("*/report.json"))


def test_non_basis_weather_failing_g3_is_flagged_and_left_out(tmp_path):
    wfn = WeatherFn(scales=dict(SCALES, **{"PVGIS-ERA5 TMY": 1.6}))
    out = run_study(QUESTION, client=FakeClient(), http_get=FakeGet(), weather_fn=wfn,
                    inputs_path=small_inputs(tmp_path), runs_dir=tmp_path / "runs", run_id="r")
    g3 = [g for g in out.report["gates"] if g["gate"] == "G3 PV physics"]
    assert [g["passed"] for g in g3] == [True, True, False, True]
    assert "PVGIS-ERA5 TMY" not in [x["weather"] for x in out.report["range_table"]]
    assert [x["g3_passed"] for x in out.report["weather_table"]] == [True, True, False, True]


def test_number_scan_trips_on_planted_number(tmp_path, monkeypatch):
    original = study.render_markdown
    monkeypatch.setattr(study, "render_markdown", lambda report: original(report) + "Planted 987.65 kWh\n")
    with pytest.raises(ReportNumberMismatch):
        run_study(QUESTION, client=FakeClient(), http_get=FakeGet(), weather_fn=WeatherFn(),
                  inputs_path=small_inputs(tmp_path), runs_dir=tmp_path / "runs", run_id="r")
    assert not list((tmp_path / "runs").glob("*/report.json"))


@pytest.mark.parametrize("q", ["", "  ", "x" * 2001, None])
def test_rejects_bad_question(tmp_path, q):
    client = FakeClient()
    with pytest.raises(ValueError):
        run_study(q, client=client, http_get=FakeGet(), weather_fn=WeatherFn(), inputs_path=small_inputs(tmp_path),
                  runs_dir=tmp_path / "runs", run_id="r")
    assert client.calls == 0
