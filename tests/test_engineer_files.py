"""Acceptance tests for T22: confirm these first, public field figures and the hourly engineer files.

Written by the orchestrator before the code (docs/specs/T22_confirm_first.md). No network.
"""
import copy
import json
import math
import pathlib
import re
import shutil
import sys

import numpy as np
import pandas as pd
import pytest

import test_sweep as tw
from autosolar.dispatch import Battery, DispatchResult, dispatch
from autosolar.engineer_files import (ENGINEER_FILES_SCHEMA, HOMER_LINES, HOURLY_CSV_COLUMNS, NOTE, REL_TOL,
                                      engineer_doc, homer_load_lines, hourly_frame, main_design_dispatch,
                                      reproduction_errors)
from autosolar.site import (FIELD_ASK_DEFAULT, FIELD_ASKS, FIELD_COMPARES, FIELD_NOTE_KEYS, SENSITIVITY_LABELS,
                            check_field_note, confirm_section, esc, render_study_html)

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import engineer_files as tool  # noqa: E402  (tools/engineer_files.py)

PV1, LOAD, TEMPLATE, DSL = tw.PV1, tw.LOAD, tw.TEMPLATE, tw.DSL
IDX = tw.IDX
TZ = "Asia/Jakarta"
WEATHER = pd.DataFrame({"ghi_w_m2": 900.0 * PV1.to_numpy(), "temp_air_degc": 27.0 + 0.0 * PV1.to_numpy(),
                        "wind_speed_m_s": 4.0 + 0.0 * PV1.to_numpy()}, index=IDX)
DATA = ROOT / "docs" / "site" / "data" / "b4a44fc6d4c32339"
REPORT = json.loads((DATA / "report.json").read_text(encoding="ascii"))
TABLE = pd.read_csv(DATA / "design_table.csv")
NOTES = json.loads((ROOT / "config" / "field_notes.json").read_text(encoding="ascii"))
KARI = [n for n in NOTES["notes"] if n["site"] == "Karimunjawa"]


def _result(pv_kwp=50.0, bat_kwh=100.0):
    return main_design_dispatch(PV1, LOAD, main_pv_kwp=pv_kwp, main_battery_kwh=bat_kwh, battery_hours=4.0,
                                battery_template=TEMPLATE, diesel=DSL)


# ---------- constants ----------

def test_constants():
    assert ENGINEER_FILES_SCHEMA == "autosolar.engineer_files/1"
    assert REL_TOL == 1e-9 and HOMER_LINES == 8760
    assert HOURLY_CSV_COLUMNS == ("time_utc", "time_local", "ghi_w_m2", "temp_air_degc", "wind_speed_m_s", "load_kw",
                                  "pv_ac_kw_per_kwp", "pv_kw", "pv_to_load_kw", "pv_to_battery_kw", "pv_curtailed_kw",
                                  "battery_discharge_kw", "soc_kwh", "diesel_kw", "diesel_units_on", "unserved_kw",
                                  "fuel_l")
    assert NOTE == "Rebuilt from the study's inputs and cached weather. The study itself is unchanged."


# ---------- main_design_dispatch ----------

def test_main_design_dispatch_matches_direct_dispatch():
    res = _result()
    bat = Battery(energy_kwh=100.0, power_kw=25.0, round_trip_eff_frac=0.9, soc_min_frac=0.1, soc_initial_frac=0.5)
    direct = dispatch(PV1 * 50.0, LOAD, bat, DSL)
    assert isinstance(res, DispatchResult)
    assert res.fuel_l == direct.fuel_l and res.diesel_starts == direct.diesel_starts
    pd.testing.assert_frame_equal(res.hourly, direct.hourly)


def test_main_design_dispatch_zero_battery():
    res = _result(50.0, 0.0)
    bat = Battery(energy_kwh=0.0, power_kw=0.0, round_trip_eff_frac=0.9, soc_min_frac=0.1, soc_initial_frac=0.5)
    direct = dispatch(PV1 * 50.0, LOAD, bat, DSL)
    pd.testing.assert_frame_equal(res.hourly, direct.hourly)
    assert float(res.hourly["soc_kwh"].abs().sum()) == 0.0


def test_main_design_dispatch_does_not_change_inputs():
    pv, load = PV1.copy(), LOAD.copy()
    _result()
    pd.testing.assert_series_equal(pv, PV1)
    pd.testing.assert_series_equal(load, LOAD)


@pytest.mark.parametrize("kw", [
    {"main_pv_kwp": -1.0}, {"main_pv_kwp": float("nan")}, {"main_pv_kwp": True}, {"main_battery_kwh": -5.0},
    {"main_battery_kwh": float("inf")}, {"main_battery_kwh": False}, {"battery_hours": 0.0},
    {"battery_hours": -4.0}, {"battery_hours": True}, {"battery_template": "battery"},
])
def test_main_design_dispatch_rejects(kw):
    args = dict(main_pv_kwp=50.0, main_battery_kwh=100.0, battery_hours=4.0, battery_template=TEMPLATE, diesel=DSL)
    args.update(kw)
    with pytest.raises(ValueError):
        main_design_dispatch(PV1, LOAD, **args)


# ---------- hourly_frame ----------

@pytest.fixture(scope="module")
def frame_and_result():
    res = _result()
    return hourly_frame(WEATHER, PV1, LOAD, res, TZ), res


def test_hourly_frame_columns_and_index(frame_and_result):
    frame, _res = frame_and_result
    assert tuple(frame.columns) == HOURLY_CSV_COLUMNS
    assert isinstance(frame.index, pd.RangeIndex) and len(frame) == 8760
    assert frame["time_utc"].iloc[0] == "2021-01-01 00:00" and frame["time_local"].iloc[0] == "2021-01-01 07:00"
    assert frame["time_utc"].iloc[-1] == "2021-12-31 23:00" and frame["time_local"].iloc[-1] == "2022-01-01 06:00"


def test_hourly_frame_values(frame_and_result):
    frame, res = frame_and_result
    for col in ("ghi_w_m2", "temp_air_degc", "wind_speed_m_s"):
        assert np.array_equal(frame[col].to_numpy(), WEATHER[col].to_numpy())
    assert np.array_equal(frame["load_kw"].to_numpy(), LOAD.to_numpy())
    assert np.array_equal(frame["pv_ac_kw_per_kwp"].to_numpy(), PV1.to_numpy())
    for col in ("pv_kw", "pv_to_load_kw", "pv_to_battery_kw", "pv_curtailed_kw", "battery_discharge_kw", "soc_kwh",
                "diesel_kw", "diesel_units_on", "unserved_kw", "fuel_l"):
        assert np.array_equal(frame[col].to_numpy(), res.hourly[col].to_numpy())


def test_hourly_frame_rejects():
    res = _result()
    with pytest.raises(ValueError):
        hourly_frame(WEATHER.drop(columns=["wind_speed_m_s"]), PV1, LOAD, res, TZ)
    with pytest.raises(ValueError):
        hourly_frame(WEATHER, PV1.iloc[1:], LOAD, res, TZ)
    shifted = LOAD.copy()
    shifted.index = shifted.index + pd.Timedelta(hours=1)
    with pytest.raises(ValueError):
        hourly_frame(WEATHER, PV1, shifted, res, TZ)
    with pytest.raises(ValueError):
        hourly_frame(WEATHER, PV1, LOAD, res, "Not/AZone")


# ---------- homer_load_lines ----------

def test_homer_load_lines_start_at_local_midnight():
    lines = homer_load_lines(LOAD, TZ)
    assert len(lines) == HOMER_LINES
    local = IDX.tz_convert(TZ)
    k = [i for i, t in enumerate(local) if t.month == 1 and t.day == 1 and t.hour == 0][0]
    assert k == 8753
    vals = LOAD.to_numpy()
    assert lines[0] == format(vals[k], ".6f") and lines[6] == format(vals[k + 6], ".6f")
    assert lines[7] == format(vals[0], ".6f") and lines[-1] == format(vals[k - 1], ".6f")
    assert math.isclose(sum(float(x) for x in lines), float(vals.sum()), rel_tol=1e-9)
    assert all(re.fullmatch(r"-?\d+\.\d{6}", x) for x in lines)


def test_homer_load_lines_aligned_index_not_rotated():
    idx = pd.date_range("2021-01-01", periods=8760, freq="1h", tz=TZ)
    load = pd.Series(np.arange(8760, dtype=float), index=idx)
    lines = homer_load_lines(load, TZ)
    assert lines[0] == "0.000000" and lines[-1] == "8759.000000"


def test_homer_load_lines_rejects():
    with pytest.raises(ValueError):
        homer_load_lines(LOAD.iloc[1:], TZ)
    bad = LOAD.copy()
    bad.iloc[5] = float("nan")
    with pytest.raises(ValueError):
        homer_load_lines(bad, TZ)
    naive = LOAD.copy()
    naive.index = naive.index.tz_localize(None)
    with pytest.raises(ValueError):
        homer_load_lines(naive, TZ)
    with pytest.raises(ValueError, match="midnight"):
        homer_load_lines(LOAD, "Asia/Kolkata")


# ---------- reproduction_errors ----------

def _fake_report(frame, res, basis="CAMS"):
    return {
        "run_hash": "abc123",
        "facts": {
            "demand_kwh_yr": {"value": float(frame["load_kw"].sum()), "label": "computed"},
            "demand_peak_kw": {"value": float(frame["load_kw"].max()), "label": "paper"},
            "best_fuel_l_yr": {"value": float(frame["fuel_l"].sum()), "label": "computed"},
        },
        "weather_table": [{"case": "NASA POWER", "yield_kwh_kwp_yr": 1.0},
                          {"case": basis, "yield_kwh_kwp_yr": float(frame["pv_ac_kw_per_kwp"].sum())}],
        "firmness": {"items": [
            {"key": "best_unserved_kwh_yr", "value": float(frame["unserved_kw"].sum())},
            {"key": "best_diesel_run_hours", "value": float(res.diesel_run_hours)},
            {"key": "best_diesel_starts", "value": float(res.diesel_starts)},
        ]},
    }


def test_reproduction_errors_pass(frame_and_result):
    frame, res = frame_and_result
    assert reproduction_errors(_fake_report(frame, res), frame, res, "CAMS") == []


@pytest.mark.parametrize("path,field", [
    (("facts", "demand_kwh_yr"), "demand_kwh_yr"),
    (("facts", "demand_peak_kw"), "demand_peak_kw"),
    (("facts", "best_fuel_l_yr"), "best_fuel_l_yr"),
])
def test_reproduction_errors_name_the_fact(frame_and_result, path, field):
    frame, res = frame_and_result
    rep = _fake_report(frame, res)
    rep[path[0]][path[1]]["value"] *= 1.01
    errs = reproduction_errors(rep, frame, res, "CAMS")
    assert len(errs) == 1 and errs[0].startswith(field + ": got ") and " want " in errs[0]


@pytest.mark.parametrize("pos,field", [(0, "best_unserved_kwh_yr"), (1, "best_diesel_run_hours"),
                                       (2, "best_diesel_starts")])
def test_reproduction_errors_name_the_firmness_item(frame_and_result, pos, field):
    frame, res = frame_and_result
    rep = _fake_report(frame, res)
    rep["firmness"]["items"][pos]["value"] += 1.0
    errs = reproduction_errors(rep, frame, res, "CAMS")
    assert len(errs) == 1 and errs[0].startswith(field + ": got ")


def test_reproduction_errors_yield_and_missing_weather_row(frame_and_result):
    frame, res = frame_and_result
    rep = _fake_report(frame, res)
    rep["weather_table"][1]["yield_kwh_kwp_yr"] *= 0.99
    errs = reproduction_errors(rep, frame, res, "CAMS")
    assert len(errs) == 1 and errs[0].startswith("yield_kwh_kwp_yr: got ")
    errs = reproduction_errors(_fake_report(frame, res), frame, res, "GSA scaled")
    assert len(errs) == 1 and errs[0].startswith("weather_table")


def test_reproduction_errors_tolerance(frame_and_result):
    frame, res = frame_and_result
    rep = _fake_report(frame, res)
    rep["facts"]["demand_kwh_yr"]["value"] *= 1.0 + 0.5e-9
    assert reproduction_errors(rep, frame, res, "CAMS") == []
    rep["facts"]["demand_kwh_yr"]["value"] *= 1.0 + 5e-9
    assert len(reproduction_errors(rep, frame, res, "CAMS")) == 1


def test_reproduction_errors_skip_missing_firmness(frame_and_result):
    frame, res = frame_and_result
    rep = _fake_report(frame, res)
    rep["firmness"] = None
    assert reproduction_errors(rep, frame, res, "CAMS") == []
    rep = _fake_report(frame, res)
    rep["firmness"]["items"] = rep["firmness"]["items"][:1]
    assert reproduction_errors(rep, frame, res, "CAMS") == []


# ---------- engineer_doc ----------

def test_engineer_doc_fields(frame_and_result):
    frame, res = frame_and_result
    rep = _fake_report(frame, res)
    files = {"hourly.csv": "a" * 64, "homer_load_kw.txt": "b" * 64}
    lines = homer_load_lines(LOAD, TZ)
    errs = ["demand_kwh_yr: got 1 want 2"]
    doc = engineer_doc(rep, run_id="files-x", basis_case="CAMS", local_tz=TZ, frame=frame, result=res,
                       homer_lines=lines, errors=errs, files=files, wall_s=1.5)
    assert set(doc) == {"schema", "run_id", "study_run_hash", "basis_case", "local_tz", "rows", "columns",
                        "homer_lines", "sums", "files", "reproduced", "reproduction_errors", "wall_s", "note"}
    assert doc["schema"] == ENGINEER_FILES_SCHEMA and doc["study_run_hash"] == "abc123" and doc["note"] == NOTE
    assert doc["rows"] == 8760 and doc["homer_lines"] == 8760 and doc["columns"] == list(HOURLY_CSV_COLUMNS)
    assert set(doc["sums"]) == {"load_kwh", "peak_kw", "pv_kwh_per_kwp", "fuel_l", "unserved_kwh",
                                "diesel_run_hours", "diesel_starts"}
    assert doc["sums"]["load_kwh"] == float(frame["load_kw"].sum())
    assert doc["sums"]["peak_kw"] == float(frame["load_kw"].max())
    assert isinstance(doc["sums"]["diesel_starts"], int) and doc["sums"]["diesel_starts"] == res.diesel_starts
    assert isinstance(doc["sums"]["diesel_run_hours"], int)
    assert doc["reproduced"] is False and doc["reproduction_errors"] == errs and doc["wall_s"] == 1.5
    files["hourly.csv"] = "changed"
    errs.append("x")
    assert doc["files"]["hourly.csv"] == "a" * 64 and len(doc["reproduction_errors"]) == 1
    json.dumps(doc)


def test_engineer_doc_reproduced(frame_and_result):
    frame, res = frame_and_result
    doc = engineer_doc(_fake_report(frame, res), run_id="r", basis_case="CAMS", local_tz=TZ, frame=frame, result=res,
                       homer_lines=homer_load_lines(LOAD, TZ), errors=[], files={}, wall_s=0.0)
    assert doc["reproduced"] is True and doc["reproduction_errors"] == []


# ---------- field notes ----------

def test_field_constants():
    assert FIELD_NOTE_KEYS == ("site", "key", "item", "value", "decimals", "unit", "label", "date", "source", "url",
                               "quote", "compare", "note")
    assert FIELD_COMPARES == ("energy_kwh_per_day", "fuel_l_per_kwh", "peak_kw", "fuel_l_per_day")  # T22c
    assert FIELD_ASK_DEFAULT == "Field records for this input"
    assert set(FIELD_ASKS) == set(SENSITIVITY_LABELS)
    assert FIELD_ASKS["demand"] == "Metered hourly load for a full year, or at least monthly kWh sent out"


def test_config_notes_are_valid():
    assert NOTES["schema"] == "autosolar.field_notes/1"
    assert len(KARI) == 5
    for note in NOTES["notes"]:
        assert check_field_note(note) is note
        note["quote"].encode("ascii")


@pytest.mark.parametrize("change", [
    {"value": float("nan")}, {"value": True}, {"value": "8000"}, {"decimals": 7}, {"decimals": -1},
    {"decimals": True}, {"label": "assumed"}, {"url": "ftp://x"}, {"compare": "other"}, {"item": ""},
    {"quote": ""}, {"site": 3}, {"note": None}, {"extra": "x"},
])
def test_check_field_note_rejects(change):
    note = copy.deepcopy(KARI[0])
    note.update(change)
    with pytest.raises(ValueError):
        check_field_note(note)


def test_check_field_note_rejects_missing_key():
    note = copy.deepcopy(KARI[0])
    del note["date"]
    with pytest.raises(ValueError):
        check_field_note(note)
    with pytest.raises(ValueError):
        check_field_note(["not", "a", "dict"])


# ---------- confirm_section ----------

def _rows(sec, after="<h2>Confirm these first</h2>"):
    body = sec[sec.index(after):]
    first = body[body.index("<tbody>"):body.index("</tbody>")]
    return re.findall(r"<tr>(.*?)</tr>", first)


def _cells(row):
    return re.findall(r"<td>(.*?)</td>", row)


def test_confirm_section_frame():
    sec = confirm_section(REPORT)
    sec.encode("ascii")
    assert sec.startswith('<section id="confirm"><h2>Confirm these first</h2>') and sec.endswith("</section>")
    assert ("<p>This page is a first screen, made in minutes from public data. It is not a design study. Before "
            "anyone builds on it, confirm the inputs below with field data, from the top, and check the result in "
            "your own tool.</p>") in sec
    assert "<h3>" not in sec and "<script" not in sec


def test_confirm_section_engineering_question():
    sec = confirm_section(REPORT)
    text = ("An engineering question comes first: can the island grid run on batteries and inverters alone? The main "
            "design runs with no diesel for 7,302 hours a year (computed). If one diesel unit must run in every hour, "
            "the main design costs 0.414 USD/kWh, more than diesel only at 0.354 USD/kWh (computed). Under that "
            "rule the least cost design is 1,500 kWp and 1,000 kWh at 0.336 USD/kWh, below diesel only (computed; "
            "see How firm is the answer).")  # second sentence: T22c, updated after the code
    assert '<p class="ask">' + esc(text) + "</p>" in sec


def test_confirm_section_question_variants():
    rep = copy.deepcopy(REPORT)
    for item in rep["firmness"]["items"]:
        if item["key"] == "reserve_units":
            item["value"] = 2.0
        if item["key"] == "reserve_main_design_lcoe_usd_per_kwh":
            item["value"] = 0.30
    sec = confirm_section(rep)
    assert "If 2 diesel units must run in every hour, the main design costs 0.300 USD/kWh, not more than diesel " \
           "only at 0.354 USD/kWh (computed)." in sec
    rep["firmness"] = None
    assert 'class="ask"' not in confirm_section(rep)
    rep = copy.deepcopy(REPORT)
    rep["firmness"]["items"] = [i for i in rep["firmness"]["items"] if i["key"] != "best_no_diesel_hours"]
    assert 'class="ask"' not in confirm_section(rep)


def _expected_order(report):
    groups = {}
    order = []
    for row in report["sensitivity_table"]:
        name = row["input"]
        if name not in groups:
            groups[name] = {}
            order.append(name)
        if row["factor"] < 1:
            groups[name]["low"] = row
        elif row["factor"] > 1:
            groups[name]["high"] = row
    keep = [n for n in order if "low" in groups[n] and "high" in groups[n]]
    spread = {n: abs(groups[n]["high"]["base_design_lcoe_usd_per_kwh"] - groups[n]["low"]["base_design_lcoe_usd_per_kwh"])
              for n in keep}
    return sorted(keep, key=lambda n: -spread[n]), groups


def test_confirm_section_ranking_table():
    sec = confirm_section(REPORT)
    heads = re.findall(r"<th>(.*?)</th>", sec)
    assert heads == ["Rank", "Input", "Value in this study", "Main design cost, input down / up (USD/kWh)",
                     "Field data to ask for"]
    order, groups = _expected_order(REPORT)
    assert order[:4] == ["discount_rate_frac", "pv_capex_usd_per_kwp", "battery_capex_usd_per_kwh", "demand"]
    rows = [_cells(r) for r in _rows(sec)]
    assert [r[0] for r in rows] == [str(i) for i in range(1, len(order) + 1)]
    assert [r[1] for r in rows] == [esc(SENSITIVITY_LABELS[n]) for n in order]
    assert [r[4] for r in rows] == [esc(FIELD_ASKS[n]) for n in order]
    assert rows[0][2] == "0.08 frac (assumed)" and rows[0][3] == "0.233 / 0.269"
    demand = rows[order.index("demand")]
    assert demand[2] == "9,568,110 kWh/yr (computed)" and demand[3] == "0.278 / 0.253"
    assert ("<p>Each input is moved 20% down and up, the swing in the inputs table. The order is by how far the cost "
            "of the main design moves (computed).</p>") in sec


def test_confirm_section_ranking_edge_cases():
    rep = copy.deepcopy(REPORT)
    rep["sensitivity_table"] = [r for r in rep["sensitivity_table"] if r["input"] != "pv_capex_usd_per_kwp"
                                or r["factor"] < 1]
    rep["sensitivity_table"].append({"input": "new_input", "factor": 0.8, "base_design_lcoe_usd_per_kwh": 0.1})
    rep["sensitivity_table"].append({"input": "new_input", "factor": 1.2, "base_design_lcoe_usd_per_kwh": 0.9})
    rows = [_cells(r) for r in _rows(confirm_section(rep))]
    names = [r[1] for r in rows]
    assert "PV price" not in names and names[0] == "new_input"
    assert rows[0][2] == "" and rows[0][4] == FIELD_ASK_DEFAULT
    rep["sensitivity_table"] = []
    sec = confirm_section(rep)
    assert "<table>" not in sec and "Each input is moved" not in sec


def test_confirm_section_equal_spread_keeps_first_order():
    rep = copy.deepcopy(REPORT)
    rep["sensitivity_table"] = [
        {"input": "fuel_price_usd_per_l", "factor": 0.8, "base_design_lcoe_usd_per_kwh": 0.2},
        {"input": "fuel_price_usd_per_l", "factor": 1.2, "base_design_lcoe_usd_per_kwh": 0.3},
        {"input": "pv_capex_usd_per_kwp", "factor": 0.8, "base_design_lcoe_usd_per_kwh": 0.3},
        {"input": "pv_capex_usd_per_kwp", "factor": 1.2, "base_design_lcoe_usd_per_kwh": 0.2},
    ]
    rows = [_cells(r) for r in _rows(confirm_section(rep))]
    assert [r[1] for r in rows] == ["Diesel price", "PV price"]


def test_confirm_section_field_notes():
    sec = confirm_section(REPORT, field_notes=KARI)
    assert "<h3>Public field figures for this site</h3>" in sec
    assert ("<p>From the press and public documents, not from the operator&#x27;s records. They can be old or "
            "rounded. They show where to look; they do not replace the study&#x27;s inputs.</p>") in sec
    part = sec[sec.index("<h3>Public field figures for this site</h3>"):]
    heads = re.findall(r"<th>(.*?)</th>", part)
    assert heads[:6] == ["Item", "Public figure", "Date", "Source and quote", "This study", "Study / public"]
    rows = [_cells(r) for r in _rows(part, after="<h3>Public field figures for this site</h3>")]
    assert len(rows) == 5
    energy, fuel, peak, perday, units = rows
    # T22c (updated after the code): item name, note, per-day compare and fuel wording
    assert energy[0] == "Electricity produced a day"
    assert energy[1] == esc("8,000 kWh (press); " + KARI[0]["note"])
    assert "about 9,500 kWh, and the study 2.76 times that (computed)" in KARI[0]["note"]
    assert energy[4] == "26,214 kWh a day (computed)" and energy[5] == "3.28x"
    assert energy[3] == esc(KARI[0]["source"] + ': "' + KARI[0]["quote"] + '" ' + KARI[0]["url"])
    assert fuel[1] == "0.50 L/kWh (press); 4,000 L for 8,000 kWh a day, in the same sentence"
    assert fuel[4] == "0.382 L/kWh, diesel only, idle fuel included (computed)" and fuel[5] == "0.76x"
    assert peak[1] == "612 kW (press)" and peak[4] == "1,422 kW (paper)" and peak[5] == "2.32x"
    assert perday[4] == "10,010 L a day, diesel only (computed)" and perday[5] == "2.50x"
    assert perday[2] == "4 April 2017"
    assert units[1] == "2.5 MW each, 2 units (press); the study runs 2 x 1.8 MW and checks 2 x 2.7 MW, both from " \
                       "the paper"


def test_confirm_section_field_notes_empty_and_bad():
    assert "<h3>" not in confirm_section(REPORT, field_notes=[])
    bad = copy.deepcopy(KARI)
    bad[0]["compare"] = "nope"
    with pytest.raises(ValueError):
        confirm_section(REPORT, field_notes=bad)


def _files_doc(**change):
    doc = {"schema": ENGINEER_FILES_SCHEMA, "study_run_hash": REPORT["run_hash"], "reproduced": True,
           "rows": 8760, "homer_lines": 8760}
    doc.update(change)
    return doc


def test_confirm_section_engineer_files():
    sec = confirm_section(REPORT, engineer_files=_files_doc())
    assert "<h3>Check us in your own tool</h3>" in sec
    assert ("<p>The hourly series behind this page, rebuilt from the study&#x27;s inputs and cached weather. Before "
            "writing them, the tool gave back this study&#x27;s yearly demand, peak load, PV yield, and the main "
            "design&#x27;s fuel, load not served, diesel hours and starts, to within one part in a billion "
            "(computed).</p>") in sec
    assert ('<ul><li><a href="data/b4a44fc6d4c32339/files/hourly.csv">hourly.csv</a>: 8,760 rows, one per hour: '
            "weather, load, PV per kWp and the main design&#x27;s energy flow, in UTC and local time.</li>") in sec
    assert ('<li><a href="data/b4a44fc6d4c32339/files/homer_load_kw.txt">homer_load_kw.txt</a>: the load in kW, one '
            "value per line, 8,760 lines, starting at local midnight on 1 January (the single column layout in "
            "HOMER&#x27;s import formats).</li></ul>") in sec


@pytest.mark.parametrize("change", [{"reproduced": False}, {"study_run_hash": "other"}])
def test_confirm_section_refuses_bad_files(change):
    with pytest.raises(ValueError):
        confirm_section(REPORT, engineer_files=_files_doc(**change))


def test_confirm_section_order_of_blocks():
    sec = confirm_section(REPORT, field_notes=KARI, engineer_files=_files_doc())
    assert sec.index('class="ask"') < sec.index("<th>Rank</th>") < sec.index("Public field figures") < sec.index(
        "Check us in your own tool")
    assert sec.count("<section") == 1 and sec.count("</section>") == 1


# ---------- the page ----------

def _load_json(name):
    return json.loads((DATA / name).read_text(encoding="ascii"))


def _page(**kw):
    return render_study_html(REPORT, TABLE, paper_check=_load_json("paper_check.json"),
                             figure_check=_load_json("figure_check.json"),
                             load_followup=_load_json("load_followup.json"), **kw)


def _cut(page, sid):
    tag = '<section id="%s">' % sid
    if tag not in page:
        return page
    start = page.index(tag)
    return page[:start] + page[page.index("</section>", start) + len("</section>"):]


def test_page_has_one_confirm_section_in_place():
    page = _page()
    page.encode("ascii")
    assert "<script" not in page and page.count('<section id="confirm">') == 1
    assert page.index('<section id="fuel-price">') < page.index('<section id="confirm">') < page.index(
        '<section id="firm">')
    assert confirm_section(REPORT) in page


def test_page_with_notes_and_files():
    page = _page(field_notes=KARI, engineer_files=_files_doc())
    assert confirm_section(REPORT, field_notes=KARI, engineer_files=_files_doc()) in page
    with pytest.raises(ValueError):
        _page(engineer_files=_files_doc(reproduced=False))


def test_page_otherwise_unchanged_from_committed_page():
    committed = (ROOT / "docs" / "site" / "b4a44fc6d4c32339.html").read_text(encoding="ascii")
    # Changed after consult round 1 (Sat 31 Oct): config/gallery.json now sets a Muse Wonder review for this study,
    # and tools/make_site.py renders the committed page with that review, so this page is rendered with it too.
    new = _page(field_notes=KARI, engineer_files=_files_doc(), review=_load_json("review.json"))
    # Changed with T26 (Sun 1 Nov, docs/specs/T26_design_change.md): the new design-change section is cut too, so
    # this test keeps checking that nothing else on the page changes.
    for sid in ("confirm", "resources", "design-change"):
        committed = _cut(committed, sid)
        new = _cut(new, sid)
    assert new == committed


# ---------- tool ----------

def test_tool_reuses_cache_only_helpers():
    import load_followup as lf
    assert tool.CACHE_ONLY_EMAIL == lf.CACHE_ONLY_EMAIL
    assert tool.no_network_fetchers is lf.no_network_fetchers


def test_tool_missing_run(tmp_path, capsys):
    code = tool.main(["--run", "nope", "--runs", str(tmp_path / "studies"), "--out", str(tmp_path / "out"),
                      "--weather-cache", str(tmp_path / "cache")])
    assert code == 2
    assert "not found" in capsys.readouterr().out
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())


def test_tool_empty_cache_never_reaches_network(tmp_path):
    run = tmp_path / "studies" / "b4a44fc6d4c32339"
    run.mkdir(parents=True)
    shutil.copy(DATA / "report.json", run / "report.json")
    shutil.copy(ROOT / "config" / "default_inputs.json", run / "inputs.json")
    with pytest.raises(RuntimeError, match="no network"):
        tool.main(["--run", "b4a44fc6d4c32339", "--runs", str(tmp_path / "studies"), "--out", str(tmp_path / "out"),
                   "--weather-cache", str(tmp_path / "cache")])


# ---------- added after the T22 code (planted fault e3 passed the tests above; labelled so) ----------

def test_homer_load_lines_rotation_with_a_load_that_never_repeats():
    load = pd.Series(np.arange(8760, dtype=float), index=IDX)
    lines = homer_load_lines(load, TZ)
    assert lines[0] == "8753.000000" and lines[6] == "8759.000000"
    assert lines[7] == "0.000000" and lines[-1] == "8752.000000"


# ---------- T22b (tests added after the T22 code) ----------

def test_tool_writes_lf_ascii_bytes(tmp_path):
    p = tmp_path / "x.txt"
    tool.write_ascii_lf(p, "a,b\n1,2\n")
    assert p.read_bytes() == b"a,b\n1,2\n"
    with pytest.raises(UnicodeEncodeError):
        tool.write_ascii_lf(tmp_path / "y.txt", "caf\u00e9\n")


def test_tool_has_no_write_text():
    src = (ROOT / "tools" / "engineer_files.py").read_text(encoding="ascii")
    assert "write_text(" not in src and src.count("write_ascii_lf(") >= 4


# ---------- T22c (added after the T22 code, labelled so) ----------

def _without(report, keys):
    rep = copy.deepcopy(report)
    rep["firmness"]["items"] = [i for i in rep["firmness"]["items"] if i["key"] not in keys]
    return rep


def test_confirm_question_least_cost_under_rule():
    first = ("If one diesel unit must run in every hour, the main design costs 0.414 USD/kWh, more than diesel only "
             "at 0.354 USD/kWh (computed).")
    tail = (" Under that rule the least cost design is 1,500 kWp and 1,000 kWh at 0.336 USD/kWh, below diesel only "
            "(computed; see How firm is the answer).")
    assert esc(first + tail) in confirm_section(REPORT)
    for key in ("reserve_pv_kwp", "reserve_battery_kwh", "reserve_lcoe_usd_per_kwh"):
        sec = confirm_section(_without(REPORT, {key}))
        assert esc(first) + "</p>" in sec and "Under that rule" not in sec
    rep = copy.deepcopy(REPORT)
    for item in rep["firmness"]["items"]:
        if item["key"] == "reserve_lcoe_usd_per_kwh":
            item["value"] = 0.40
    assert "at 0.400 USD/kWh, not below diesel only (computed; see How firm is the answer)." in confirm_section(rep)
    for bad in (float("nan"), None, "0.3", True):
        rep = copy.deepcopy(REPORT)
        for item in rep["firmness"]["items"]:
            if item["key"] == "reserve_pv_kwp":
                item["value"] = bad
        sec = confirm_section(rep)
        assert "Under that rule" not in sec and esc(first) in sec


def test_field_fuel_per_day():
    note = copy.deepcopy(KARI[3])
    assert note["compare"] == "fuel_l_per_day"
    sec = confirm_section(REPORT, field_notes=[note])
    part = sec[sec.index("<h3>Public field figures for this site</h3>"):]
    row = _cells(_rows(part, after="<h3>Public field figures for this site</h3>")[0])
    per_day = REPORT["facts"]["diesel_only_fuel_l_yr"]["value"] / 365.0
    assert row[4] == format(per_day, ",.0f") + " L a day, diesel only (computed)"
    assert row[5] == format(per_day / 4000.0, ",.2f") + "x"
