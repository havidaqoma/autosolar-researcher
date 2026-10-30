"""Acceptance tests for T23: which renewable fits this site? (docs/specs/T23_resource_screen.md).

Written by the orchestrator before the code. No network: every fetcher is a fake.
"""
import copy
import hashlib
import json
import math
import pathlib
import re
import sys

import numpy as np
import pandas as pd
import pytest

from autosolar.resources import (EARTH_RADIUS_KM, HYDRO_CHECK, LOOK, NOT_ON_SCREEN, NOTE, PLACE_RADIUS_KM,
                                 R_DRY_AIR_J_PER_KG_K, RESOURCE_SCHEMA, SOLAR_EXCELLENT_KWH_PER_KWP_DAY,
                                 SOLAR_LOOK_KWH_PER_KWP_DAY, SOURCES, WATER_RADIUS_KM, WATERWAY_KINDS, WIND_CLASSES,
                                 WIND_LOOK_CLASS, WIND_YEARS, ResourceFetchers, air_density_kg_m3,
                                 cached_resource_fetchers, gsa_lta, haversine_km, nearest_place,
                                 no_network_resource_fetchers, place_query, pv_yield_checks, pvgis_yield, screen_doc,
                                 screen_verdicts, solar_band, water_query, waterway_counts, wind_class,
                                 wind_from_power)
from autosolar.site import esc, render_study_html, resources_section

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import resource_screen as tool  # noqa: E402  (tools/resource_screen.py)

DATA = ROOT / "docs" / "site" / "data" / "b4a44fc6d4c32339"
REPORT = json.loads((DATA / "report.json").read_text(encoding="ascii"))
TABLE = pd.read_csv(DATA / "design_table.csv")
LAT, LON = REPORT["site"]["lat_deg"], REPORT["site"]["lon_deg"]


def _keys(year=2021):
    idx = pd.date_range("%d-01-01" % year, periods=8760, freq="1h", tz="UTC")
    return [t.strftime("%Y%m%d%H") for t in idx]


def _power(speed=None, temp=27.0, pres=101.0, keys=None):
    keys = keys or _keys()
    if speed is None:
        speed = {k: 3.0 + int(k[4:6]) * 0.25 for k in keys}
    elif not isinstance(speed, dict):
        speed = {k: float(speed) for k in keys}
    return {"type": "Feature", "header": {"fill_value": -999.0, "start": keys[0][:8], "end": keys[-1][:8]},
            "properties": {"parameter": {"WS50M": dict(speed), "T2M": {k: temp for k in keys},
                                         "PS": {k: pres for k in keys}}}}


GSA_PAYLOAD = {"annual": {"data": {"PVOUT_csi": 1477.524169921875, "GHI": 1827.9375, "OPTA": 11, "TEMP": 27.3}}}
PVGIS_PAYLOAD = {"inputs": {}, "outputs": {"totals": {"fixed": {"E_y": 1580.88, "E_d": 4.33}}}}
WATER_PAYLOAD = {"osm3s": {"timestamp_osm_base": "2026-10-30T08:46:02Z"}, "elements": [
    {"type": "way", "id": 1, "tags": {"waterway": "stream"}},
    {"type": "way", "id": 2, "tags": {"waterway": "drain"}},
    {"type": "way", "id": 3, "tags": {"waterway": "stream", "name": "Kali A"}},
    {"type": "way", "id": 4, "tags": {"waterway": "river", "name": "Sungai Sedimen"}},
    {"type": "way", "id": 5, "tags": {"waterway": "river", "name": "Sungai Sedimen"}},
    {"type": "way", "id": 6, "tags": {"waterway": "river", "name": "Alpha"}},
    {"type": "way", "id": 7, "tags": {"waterway": "weir"}},
    {"type": "way", "id": 8, "tags": {"natural": "water"}},
]}
PLACE_PAYLOAD = {"elements": [
    {"type": "node", "id": 1, "lat": -6.5886, "lon": 110.6684, "tags": {"place": "city", "name": "Jepara"}},
    {"type": "node", "id": 2, "lat": -6.4, "lon": 110.75, "tags": {"place": "town", "name": "Mlonggo"}},
    {"type": "node", "id": 3, "lat": -5.9, "lon": 110.44, "tags": {"place": "village", "name": "Near village"}},
    {"type": "node", "id": 4, "tags": {"place": "town", "name": "No coords"}},
]}


# ---------- constants ----------

def test_constants():
    assert RESOURCE_SCHEMA == "autosolar.resource_screen/1"
    assert WIND_YEARS == (2016, 2024) and WATER_RADIUS_KM == 10.0 and PLACE_RADIUS_KM == 150.0
    assert EARTH_RADIUS_KM == 6371.0088 and R_DRY_AIR_J_PER_KG_K == 287.05
    assert WIND_CLASSES == ((200.0, 1, "Poor"), (300.0, 2, "Marginal"), (400.0, 3, "Fair"), (500.0, 4, "Good"),
                            (600.0, 5, "Excellent"), (800.0, 6, "Outstanding"), (2000.0, 7, "Superb"))
    assert WIND_LOOK_CLASS == 3 and SOLAR_LOOK_KWH_PER_KWP_DAY == 3.5 and SOLAR_EXCELLENT_KWH_PER_KWP_DAY == 4.5
    assert WATERWAY_KINDS == ("river", "stream", "canal", "drain", "ditch")
    assert LOOK == "worth a closer look" and NOT_ON_SCREEN == "not on this screen"
    assert HYDRO_CHECK == "check flow and head on site"
    assert NOTE.startswith("Written after the studies ran (post hoc).")
    assert set(SOURCES) == {"nasa_power_hourly", "pvgis_pvcalc", "global_solar_atlas", "overpass",
                            "world_bank_pv_potential", "nrel_wind_classes"}
    assert all(u.startswith("https://") for u in SOURCES.values())


# ---------- small functions ----------

def test_haversine_km():
    assert haversine_km(0.0, 0.0, 0.0, 0.0) == 0.0
    assert math.isclose(haversine_km(0.0, 0.0, 0.0, 1.0), EARTH_RADIUS_KM * math.pi / 180, rel_tol=1e-12)
    assert math.isclose(haversine_km(LAT, LON, -6.5886, 110.6684), 83.02, abs_tol=0.01)
    for bad in [(91.0, 0.0, 0.0, 0.0), (0.0, 181.0, 0.0, 0.0), (0.0, 0.0, float("nan"), 0.0), (True, 0.0, 0.0, 0.0)]:
        with pytest.raises(ValueError):
            haversine_km(*bad)


def test_air_density():
    rho = air_density_kg_m3([27.0, 0.0], [101.0, 101.325])
    assert rho.dtype == np.float64 and rho.shape == (2,)
    assert math.isclose(rho[0], 101.0 * 1000 / (287.05 * 300.15), rel_tol=1e-12)
    assert math.isclose(rho[1], 1.2922, abs_tol=1e-4)
    for t, p in [([27.0], [101.0, 100.0]), ([], []), ([float("nan")], [101.0]), ([75.0], [101.0]),
                 ([27.0], [20.0]), ([27.0], [130.0]), ([-95.0], [101.0])]:
        with pytest.raises(ValueError):
            air_density_kg_m3(t, p)


def test_wind_from_power_values():
    out = wind_from_power(_power())
    assert set(out) == {"hours", "dropped_hours", "first", "last", "mean_speed_m_s", "mean_density_kg_m3",
                        "power_density_w_m2", "monthly_mean_speed_m_s"}
    keys = _keys()
    v = np.array([3.0 + int(k[4:6]) * 0.25 for k in keys])
    rho = 101.0 * 1000 / (287.05 * 300.15)
    assert out["hours"] == 8760 and out["dropped_hours"] == 0
    assert out["first"] == "2021010100" and out["last"] == "2021123123"
    assert math.isclose(out["mean_speed_m_s"], v.mean(), rel_tol=1e-12)
    assert math.isclose(out["mean_density_kg_m3"], rho, rel_tol=1e-12)
    assert math.isclose(out["power_density_w_m2"], float(np.mean(0.5 * rho * v ** 3)), rel_tol=1e-12)
    assert len(out["monthly_mean_speed_m_s"]) == 12
    assert math.isclose(out["monthly_mean_speed_m_s"][0], 3.25) and math.isclose(out["monthly_mean_speed_m_s"][11],
                                                                                    6.0)
    json.dumps(out)


def test_wind_from_power_drops_fill_hours():
    keys = _keys(2020)[:24] + _keys()
    payload = _power(keys=keys)
    payload["properties"]["parameter"]["PS"][keys[3]] = -999.0
    payload["properties"]["parameter"]["WS50M"][keys[5]] = -999.0
    out = wind_from_power(payload)
    assert out["hours"] == 8782 and out["dropped_hours"] == 2


def test_wind_from_power_fill_value_default_and_header():
    payload = _power()
    del payload["header"]
    k = _keys()[0]
    payload["properties"]["parameter"]["T2M"][k] = -999.0
    with pytest.raises(ValueError):  # 8759 hours left
        wind_from_power(payload)
    payload = _power(keys=_keys(2020)[:5] + _keys())
    payload["header"]["fill_value"] = -99.0
    payload["properties"]["parameter"]["WS50M"][_keys()[0]] = -99.0
    assert wind_from_power(payload)["dropped_hours"] == 1


def test_wind_from_power_rejects():
    payload = _power()
    payload["properties"]["parameter"]["WS50M"][_keys()[7]] = -1.0
    with pytest.raises(ValueError):
        wind_from_power(payload)
    payload = _power()
    del payload["properties"]["parameter"]["T2M"][_keys()[7]]
    with pytest.raises(ValueError):
        wind_from_power(payload)
    payload = _power()
    del payload["properties"]["parameter"]["PS"]
    with pytest.raises(ValueError):
        wind_from_power(payload)
    keys = [k for k in _keys() if k[4:6] != "02"] + _keys(2022)[-24 * 40:]
    with pytest.raises(ValueError):  # no February hour kept
        wind_from_power(_power(keys=keys))


@pytest.mark.parametrize("value,expected", [
    (0.0, (1, "Poor")), (90.77, (1, "Poor")), (199.9, (1, "Poor")), (200.0, (2, "Marginal")), (350.0, (3, "Fair")),
    (450.0, (4, "Good")), (599.0, (5, "Excellent")), (799.0, (6, "Outstanding")), (1999.0, (7, "Superb")),
    (2000.0, (8, "Above Superb")),
])
def test_wind_class(value, expected):
    assert wind_class(value) == expected


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf"), True, "100"])
def test_wind_class_rejects(bad):
    with pytest.raises(ValueError):
        wind_class(bad)


@pytest.mark.parametrize("value,band", [(4.51, "excellent"), (4.5, "favorable middle range"),
                                        (4.05, "favorable middle range"), (3.5, "favorable middle range"),
                                        (3.49, "lower end"), (0.1, "lower end")])
def test_solar_band(value, band):
    assert solar_band(value) == band


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), False])
def test_solar_band_rejects(bad):
    with pytest.raises(ValueError):
        solar_band(bad)


def test_gsa_and_pvgis_parsers():
    assert gsa_lta(GSA_PAYLOAD) == {"pvout_kwh_per_kwp_yr": 1477.524169921875, "opta_deg": 11.0}
    assert pvgis_yield(PVGIS_PAYLOAD) == 1580.88
    for bad in [{"annual": {"data": {"PVOUT_csi": 0, "OPTA": 11}}}, {"annual": {"data": {"PVOUT_csi": 1400.0}}},
                {"annual": {"data": {"PVOUT_csi": 1400.0, "OPTA": 95}}}, {}]:
        with pytest.raises(ValueError):
            gsa_lta(bad)
    for bad in [{"outputs": {"totals": {"fixed": {"E_y": -1.0}}}}, {"outputs": {}},
                {"outputs": {"totals": {"fixed": {"E_y": float("nan")}}}}]:
        with pytest.raises(ValueError):
            pvgis_yield(bad)


def test_queries():
    assert water_query(LAT, LON, 10.0) == \
        '[out:json][timeout:90];way["waterway"](around:10000,-5.879626,110.432907);out tags;'
    assert place_query(LAT, LON, 150.0) == \
        '[out:json][timeout:90];node["place"~"^(city|town)$"](around:150000,-5.879626,110.432907);out;'
    for bad in [0.0, -1.0, 501.0, float("nan"), True]:
        with pytest.raises(ValueError):
            water_query(LAT, LON, bad)
        with pytest.raises(ValueError):
            place_query(LAT, LON, bad)
    with pytest.raises(ValueError):
        water_query(95.0, LON, 10.0)


def test_waterway_counts():
    out = waterway_counts(WATER_PAYLOAD)
    assert out == {"river": 3, "stream": 2, "canal": 0, "drain": 1, "ditch": 0, "other": 2,
                   "named_rivers": ["Alpha", "Sungai Sedimen"], "osm_base": "2026-10-30T08:46:02Z"}
    assert waterway_counts({"elements": []})["osm_base"] == ""
    with pytest.raises(ValueError):
        waterway_counts({"remark": "runtime error"})


def test_nearest_place():
    out = nearest_place(PLACE_PAYLOAD, LAT, LON)
    assert out["name"] == "Mlonggo" and out["place"] == "town"
    assert math.isclose(out["km"], haversine_km(LAT, LON, -6.4, 110.75), rel_tol=1e-12)
    assert nearest_place({"elements": PLACE_PAYLOAD["elements"][2:]}, LAT, LON) is None
    assert nearest_place({"elements": []}, LAT, LON) is None
    tie = {"elements": [{"lat": -6.0, "lon": 110.43, "tags": {"place": "town", "name": "Zeta"}},
                        {"lat": -6.0, "lon": 110.43, "tags": {"place": "city", "name": "Beta"}}]}
    assert nearest_place(tie, LAT, LON)["name"] == "Beta"
    unnamed = {"elements": [{"lat": -6.0, "lon": 110.43, "tags": {"place": "town"}}]}
    assert nearest_place(unnamed, LAT, LON)["name"] == ""
    with pytest.raises(ValueError):
        nearest_place({}, LAT, LON)


def test_pv_yield_checks():
    rows = pv_yield_checks(REPORT, pvgis_e_y_kwh_per_kwp=1580.88, gsa_pvout_kwh_per_kwp_yr=1477.524169921875)
    assert [r["service"] for r in rows] == ["PVGIS PVcalc (JRC), ERA5", "Global Solar Atlas PVOUT (Solargis)"]
    assert [r["case"] for r in rows] == ["PVGIS-ERA5 TMY", "GSA scaled"]
    assert set(rows[0]) == {"service", "case", "theirs_kwh_per_kwp_yr", "ours_kwh_per_kwp_yr", "gap_pct"}
    assert math.isclose(rows[0]["ours_kwh_per_kwp_yr"], 1603.4139192835241)
    assert round(rows[0]["gap_pct"], 1) == 1.4 and round(rows[1]["gap_pct"], 1) == -3.3
    rep = copy.deepcopy(REPORT)
    rep["weather_table"] = [w for w in rep["weather_table"] if w["case"] != "GSA scaled"]
    with pytest.raises(ValueError):
        pv_yield_checks(rep, pvgis_e_y_kwh_per_kwp=1580.88, gsa_pvout_kwh_per_kwp_yr=1477.5)
    with pytest.raises(ValueError):
        pv_yield_checks(REPORT, pvgis_e_y_kwh_per_kwp=0.0, gsa_pvout_kwh_per_kwp_yr=1477.5)


def test_screen_verdicts():
    assert screen_verdicts(pvout_kwh_per_kwp_day=4.05, wind_class_number=1, rivers=1) == {
        "solar": LOOK, "wind": NOT_ON_SCREEN, "hydro": HYDRO_CHECK}
    assert screen_verdicts(pvout_kwh_per_kwp_day=3.49, wind_class_number=3, rivers=0) == {
        "solar": NOT_ON_SCREEN, "wind": LOOK, "hydro": NOT_ON_SCREEN}
    assert screen_verdicts(pvout_kwh_per_kwp_day=3.5, wind_class_number=2, rivers=0)["solar"] == LOOK
    for kw in [{"wind_class_number": 0}, {"wind_class_number": 9}, {"wind_class_number": True}, {"rivers": -1},
               {"rivers": 1.0}, {"pvout_kwh_per_kwp_day": float("nan")}]:
        args = dict(pvout_kwh_per_kwp_day=4.0, wind_class_number=1, rivers=0)
        args.update(kw)
        with pytest.raises(ValueError):
            screen_verdicts(**args)


# ---------- screen_doc ----------

def _doc(place=None, water=None, wind_payload=None):
    wind = wind_from_power(wind_payload or _power(speed=4.4))
    water = water if water is not None else waterway_counts(WATER_PAYLOAD)
    place = place if place is not None else nearest_place(PLACE_PAYLOAD, LAT, LON)
    return screen_doc(REPORT, run_id="resources-x", wind=wind, gsa=gsa_lta(GSA_PAYLOAD), pvgis_e_y_kwh_per_kwp=1580.88,
                      water=water, place=place, files={"a.json": "0" * 64}, wall_s=2.5)


def test_screen_doc_fields():
    doc = _doc()
    assert set(doc) == {"schema", "run_id", "study_run_hash", "site", "weather_coords_deg", "solar", "wind", "hydro",
                        "grid", "pv_checks", "verdicts", "files", "wall_s", "sources", "note"}
    assert doc["schema"] == RESOURCE_SCHEMA and doc["study_run_hash"] == REPORT["run_hash"] and doc["note"] == NOTE
    assert doc["site"] == {"name": "Karimunjawa", "lat_deg": LAT, "lon_deg": LON}
    assert doc["weather_coords_deg"] == [-5.88, 110.43]
    assert doc["solar"]["band"] == "favorable middle range" and doc["solar"]["opta_deg"] == 11.0
    assert math.isclose(doc["solar"]["pvout_kwh_per_kwp_day"], 1477.524169921875 / 365, rel_tol=1e-12)
    assert doc["wind"]["years"] == [2016, 2024] and doc["wind"]["class_number"] == 1
    assert doc["wind"]["class_name"] == "Poor" and doc["wind"]["hours"] == 8760
    assert doc["hydro"]["river"] == 3 and doc["hydro"]["radius_km"] == 10.0
    assert doc["grid"]["nearest"]["name"] == "Mlonggo" and doc["grid"]["radius_km"] == 150.0
    assert doc["verdicts"] == {"solar": LOOK, "wind": NOT_ON_SCREEN, "hydro": HYDRO_CHECK}
    assert len(doc["pv_checks"]) == 2 and doc["sources"] == SOURCES and doc["files"] == {"a.json": "0" * 64}
    assert doc["wall_s"] == 2.5
    json.dumps(doc)


def test_screen_doc_copies_inputs():
    wind = wind_from_power(_power(speed=4.4))
    water = waterway_counts(WATER_PAYLOAD)
    files = {"a.json": "0" * 64}
    doc = screen_doc(REPORT, run_id="r", wind=wind, gsa=gsa_lta(GSA_PAYLOAD), pvgis_e_y_kwh_per_kwp=1580.88,
                     water=water, place=None, files=files, wall_s=0.0)
    assert "class_number" not in wind and "radius_km" not in water
    files["b.json"] = "1"
    assert set(doc["files"]) == {"a.json"} and doc["grid"]["nearest"] is None
    doc["sources"]["overpass"] = "changed"
    assert SOURCES["overpass"] == "https://overpass-api.de/api/interpreter"


# ---------- fetchers ----------

class Calls:
    def __init__(self):
        self.log = []

    def fetchers(self):
        def nasa(lat, lon, y0, y1):
            self.log.append(("nasa", lat, lon, y0, y1))
            return _power(speed=4.4)

        def pvgis(lat, lon, tilt, loss):
            self.log.append(("pvgis", lat, lon, tilt, loss))
            return PVGIS_PAYLOAD

        def overpass(query):
            self.log.append(("overpass", query))
            return WATER_PAYLOAD if "waterway" in query else PLACE_PAYLOAD

        return ResourceFetchers(nasa_wind_hourly=nasa, pvgis_pvcalc=pvgis, overpass=overpass)


def test_no_network_fetchers():
    f = no_network_resource_fetchers()
    for call in (lambda: f.nasa_wind_hourly(0.0, 0.0, 2016, 2024), lambda: f.pvgis_pvcalc(0.0, 0.0, 10.0, 14.0),
                 lambda: f.overpass("q")):
        with pytest.raises(RuntimeError, match="no network"):
            call()


def test_cached_fetchers_write_then_read(tmp_path):
    calls = Calls()
    f = cached_resource_fetchers(calls.fetchers(), tmp_path / "cache")
    q = water_query(LAT, LON, 10.0)
    a = f.nasa_wind_hourly(-5.88, 110.43, 2016, 2024)
    b = f.pvgis_pvcalc(-5.88, 110.43, 10.0, 14.0)
    c = f.overpass(q)
    assert len(calls.log) == 3
    names = sorted(p.name for p in (tmp_path / "cache").iterdir())
    h = hashlib.sha256(q.encode("utf-8")).hexdigest()[:16]
    assert names == sorted(["nasa_wind_-5.8800_110.4300_2016_2024.json", "pvgis_pvcalc_-5.8800_110.4300_t10_l14.json",
                            "overpass_%s.json" % h])
    for p in (tmp_path / "cache").iterdir():
        p.read_bytes().decode("ascii")
    g = cached_resource_fetchers(no_network_resource_fetchers(), tmp_path / "cache")
    assert g.nasa_wind_hourly(-5.88, 110.43, 2016, 2024) == a
    assert g.pvgis_pvcalc(-5.88, 110.43, 10.0, 14.0) == b and g.overpass(q) == c
    with pytest.raises(RuntimeError):
        g.overpass(place_query(LAT, LON, 150.0))
    with pytest.raises(ValueError):
        cached_resource_fetchers("not fetchers", tmp_path)


# ---------- tool ----------

def _setup_runs(tmp_path):
    run = tmp_path / "studies" / "b4a44fc6d4c32339"
    run.mkdir(parents=True)
    (run / "report.json").write_text((DATA / "report.json").read_text(encoding="ascii"), encoding="ascii")
    wc = tmp_path / "weather_cache"
    wc.mkdir()
    (wc / "gsa_-5.8800_110.4300.json").write_text(json.dumps(GSA_PAYLOAD), encoding="ascii")
    return ["--run", "b4a44fc6d4c32339", "--runs", str(tmp_path / "studies"), "--out", str(tmp_path / "out"),
            "--cache", str(tmp_path / "rcache"), "--weather-cache", str(wc)]


def test_tool_end_to_end_with_fakes(tmp_path, capsys):
    args = _setup_runs(tmp_path)
    calls = Calls()
    assert tool.main(args, fetchers=calls.fetchers()) == 0
    assert ("nasa", -5.88, 110.43, 2016, 2024) in calls.log
    assert ("pvgis", -5.88, 110.43, 10.0, 14.0) in calls.log
    assert ("overpass", water_query(LAT, LON, 10.0)) in calls.log
    assert ("overpass", place_query(LAT, LON, 150.0)) in calls.log
    outs = list((tmp_path / "out").iterdir())
    assert len(outs) == 1 and re.fullmatch(r"resources-\d{8}T\d{6}-[0-9a-f]{6}", outs[0].name)
    doc = json.loads((outs[0] / "resource_screen.json").read_text(encoding="ascii"))
    assert doc["run_id"] == outs[0].name and doc["study_run_hash"] == REPORT["run_hash"]
    assert doc["schema"] == RESOURCE_SCHEMA and doc["verdicts"]["solar"] == LOOK
    assert doc["grid"]["nearest"]["name"] == "Mlonggo"
    assert len(doc["files"]) == 5 and "gsa_-5.8800_110.4300.json" in doc["files"]
    for name, sha in doc["files"].items():
        path = (tmp_path / "rcache" / name) if name != "gsa_-5.8800_110.4300.json" else (
            tmp_path / "weather_cache" / name)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == sha
    text = capsys.readouterr().out
    assert outs[0].name in text


def test_tool_cache_only_rerun_and_missing(tmp_path, capsys):
    args = _setup_runs(tmp_path)
    with pytest.raises(RuntimeError, match="no network"):
        tool.main(args + ["--cache-only"])
    assert tool.main(args, fetchers=Calls().fetchers()) == 0
    assert tool.main(args + ["--cache-only"]) == 0
    assert len(list((tmp_path / "out").iterdir())) == 2
    code = tool.main(["--run", "nope", "--runs", str(tmp_path / "studies"), "--out", str(tmp_path / "out2")])
    assert code == 2 and "not found" in capsys.readouterr().out
    assert not (tmp_path / "out2").exists() or not any((tmp_path / "out2").iterdir())


# ---------- the page ----------

def test_resources_section_none():
    assert resources_section(REPORT, None) == ""


def test_resources_section_rejects():
    doc = _doc()
    with pytest.raises(ValueError):
        resources_section(REPORT, dict(doc, study_run_hash="other"))
    with pytest.raises(ValueError):
        resources_section(REPORT, dict(doc, schema="other/1"))


def _rows_after(sec, marker):
    body = sec[sec.index(marker):]
    return [re.findall(r"<td>(.*?)</td>", r) for r in
            re.findall(r"<tr>(.*?)</tr>", body[body.index("<tbody>"):body.index("</tbody>")])]


def test_resources_section_text():
    doc = _doc()
    sec = resources_section(REPORT, doc)
    sec.encode("ascii")
    assert sec.startswith('<section id="resources"><h2>Which renewable fits this site?</h2>')
    assert sec.endswith("</section>") and "<script" not in sec
    assert ("<p>A first screen of other local resources, from free public data. The costs on this page cover solar, "
            "battery and diesel only; wind, hydro and a grid link are not costed here.</p>") in sec
    heads = re.findall(r"<th>(.*?)</th>", sec)
    assert heads[:4] == ["Resource", "Public data", "Screen reading", "Next check"]
    sun, wind, hydro, grid = _rows_after(sec, "<h2>")
    assert sun == ["Sun", "PV output 4.05 kWh/kWp a day, 1,478 a year (Global Solar Atlas, measured)",
                   "World Bank band: favorable middle range (docs); worth a closer look", "Costed on this page"]
    w = doc["wind"]
    assert wind == ["Wind", esc("Mean 4.40 m/s and %s W/m2 at 50 m, hourly 2016 to 2024 (NASA POWER, coarse MERRA-2 "
                                "grid; computed)" % format(w["power_density_w_m2"], ",.0f")),
                    "Class 1, Poor, on the NREL scale (docs); not on this screen",
                    "Global Wind Atlas or a mast on site; a coarse grid can miss local wind"]
    assert hydro == ["Hydro", "3 river and 2 stream lines mapped within 10 km (OpenStreetMap, measured)",
                     "check flow and head on site", "Flow and head from a field survey"]
    km = format(doc["grid"]["nearest"]["km"], ",.0f")
    assert grid == ["Grid link", "Nearest town or city on the map: Mlonggo (town), %s km in a straight line "
                    "(computed)" % km, "Not screened", "Cost of a grid link or sea cable"]
    assert ("<p>Screen rule (assumed): solar is worth a closer look at 3.5 kWh/kWp a day or more, the lower bound of "
            "the World Bank&#x27;s favorable range; wind at class 3 or more; hydro needs at least one mapped river "
            "within 10 km, and then flow and head decide.</p>") in sec
    assert "<h3>Is our PV model close to outside models?</h3>" in sec
    part = sec[sec.index("<h3>"):]
    assert re.findall(r"<th>(.*?)</th>", part) == ["Outside model", "Their PV output (kWh/kWp a year)",
                                                    "Our model on their weather (kWh/kWp a year)", "Gap"]
    rows = _rows_after(part, "<h3>")
    assert rows == [["PVGIS PVcalc (JRC), ERA5", "1,581", "1,603", "+1.4%"],
                    ["Global Solar Atlas PVOUT (Solargis)", "1,478", "1,428", "-3.3%"]]
    assert ("<p>Same site and panel tilt; the loss chains differ, so a gap of a few percent is expected. Computed "
            "after the studies ran (post hoc).</p>") in sec


def test_resources_section_no_place_and_no_river():
    water = waterway_counts({"elements": []})
    doc = _doc(water=water)
    doc["grid"]["nearest"] = None
    sec = resources_section(REPORT, doc)
    assert "No town or city on the map within 150 km" in sec
    assert "0 river and 0 stream lines mapped within 10 km" in sec


def test_page_places_resources_after_confirm():
    def load(name):
        return json.loads((DATA / name).read_text(encoding="ascii"))
    base = dict(paper_check=load("paper_check.json"), figure_check=load("figure_check.json"),
                load_followup=load("load_followup.json"))
    page = render_study_html(REPORT, TABLE, resource_screen=_doc(), **base)
    page.encode("ascii")
    assert "<script" not in page and page.count('<section id="resources">') == 1
    assert page.index('<section id="confirm">') < page.index('<section id="resources">') < page.index(
        '<section id="firm">')
    assert resources_section(REPORT, _doc()) in page
    plain = render_study_html(REPORT, TABLE, **base)
    assert '<section id="resources">' not in plain
    start = page.index('<section id="resources">')
    end = page.index("</section>", start) + len("</section>")
    assert page[:start] + page[end:] == plain
