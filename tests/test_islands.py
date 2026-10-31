"""Acceptance tests for T24 (autosolar/islands.py). Written before the code. No network."""
import copy
import re

import pytest

from autosolar import islands as I
from autosolar.resources import screen_verdicts, solar_band, wind_class
from autosolar.site import esc

HASH = "b4a44fc6d4c32339"
SHA = "a" * 64


def _island(name="Alpha", study=None, lat=-5.9, lon=110.4):
    return {"name": name, "region": "Somewhere, Java", "lat_deg": lat, "lon_deg": lon, "point": "island centre",
            "diesel": {"url": "https://example.org/news/1", "quote": "the island runs on a diesel plant (PLTD)",
                       "outlet": "Example News", "year": 2025, "label": "press"},
            "study": study}


def _doc(*islands):
    return {"schema": I.ISLAND_LIST_SCHEMA, "note": "n", "islands": list(islands)}


def _parsed(**kw):
    return I.parse_island_list(_doc(_island(**kw)))[0]


WIND = {"mean_speed_m_s": 4.44, "power_density_w_m2": 90.8, "hours": 78888}
GSA = {"pvout_kwh_per_kwp_yr": 1478.25, "opta_deg": 7.0}
WATER = {"river": 1, "stream": 2, "canal": 0, "drain": 1, "ditch": 0, "other": 0, "named_rivers": [], "osm_base": ""}
PLACE = {"name": "Mlonggo", "place": "town", "km": 78.2}
FOUND = {"found": True, "status": I.QUOTE_FOUND}


def _row(island=None, **kw):
    args = {"wind": WIND, "gsa": GSA, "water": WATER, "place": PLACE, "place_fetched": True,
            "diesel_result": FOUND}
    args.update(kw)
    return I.island_row(island if island is not None else _parsed(), **args)


# ---------- constants ----------

def test_constants():
    assert I.ISLAND_LIST_SCHEMA == "autosolar.island_list/1"
    assert I.ISLAND_SCREEN_SCHEMA == "autosolar.island_screen/1"
    assert I.LAND_SCHEMA == "autosolar.land_rings/1"
    assert I.MAP_BBOX_DEG == (94.0, 142.0, -11.5, 6.5)
    assert (I.MAP_WIDTH_PX, I.MAP_HEIGHT_PX) == (960, 360)
    assert I.QUOTE_MIN_CHARS == 20
    assert I.NOT_COSTED == "no: no hourly load, so no cost; the tool refuses rather than guess"
    assert I.NOT_FETCHED == "not fetched"
    assert I.NO_TOWN == "none within 150 km"
    assert "post hoc" in I.NOTE and "741" in I.NOTE and "not a grid connection" in I.NOTE
    assert set(I.SOURCES) == {"nasa_power_hourly", "global_solar_atlas", "overpass", "nominatim", "natural_earth"}


# ---------- parse_island_list ----------

def test_parse_valid_returns_new_dicts():
    src = _doc(_island("Alpha"), _island("Beta", study=HASH, lat=-6, lon=115))
    keep = copy.deepcopy(src)
    out = I.parse_island_list(src)
    assert [x["name"] for x in out] == ["Alpha", "Beta"]
    assert isinstance(out[1]["lat_deg"], float) and out[1]["lat_deg"] == -6.0
    assert out[1]["study"] == HASH and out[0]["study"] is None
    assert set(out[0]) == {"name", "region", "lat_deg", "lon_deg", "point", "diesel", "study"}
    assert set(out[0]["diesel"]) == {"url", "quote", "outlet", "year", "label"}
    out[0]["diesel"]["quote"] = "changed"
    assert src == keep


@pytest.mark.parametrize("mutate", [
    lambda d: d.update(schema="other/1"),
    lambda d: d.update(islands=[]),
    lambda d: d.update(islands="x"),
    lambda d: d["islands"].append(_island("Alpha")),
    lambda d: d["islands"][0].update(name=""),
    lambda d: d["islands"][0].update(lat_deg=91.0),
    lambda d: d["islands"][0].update(lat_deg=True),
    lambda d: d["islands"][0].update(lon_deg=float("nan")),
    lambda d: d["islands"][0].update(lon_deg=-181.0),
    lambda d: d["islands"][0].update(study="B4A44FC6D4C32339"),
    lambda d: d["islands"][0].update(study="b4a44fc6"),
    lambda d: d["islands"][0].pop("point"),
    lambda d: d["islands"][0]["diesel"].update(url="ftp://example.org"),
    lambda d: d["islands"][0]["diesel"].update(quote="  too short  "),
    lambda d: d["islands"][0]["diesel"].update(outlet=""),
    lambda d: d["islands"][0]["diesel"].update(year=True),
    lambda d: d["islands"][0]["diesel"].update(year=1989),
    lambda d: d["islands"][0]["diesel"].update(year=2025.0),
    lambda d: d["islands"][0]["diesel"].update(label="assumed"),
    lambda d: d["islands"][0].pop("diesel"),
])
def test_parse_rejects(mutate):
    d = _doc(_island("Alpha"))
    mutate(d)
    with pytest.raises(ValueError):
        I.parse_island_list(d)


def test_parse_rejects_non_dict():
    with pytest.raises(ValueError):
        I.parse_island_list(["x"])


# ---------- diesel_check ----------

def test_diesel_check_found_and_missing():
    d = _parsed()["diesel"]
    hit = I.diesel_check(d, ["Some text. The island runs on a diesel plant (PLTD) since 1992."])
    assert hit == {"found": True, "status": I.QUOTE_FOUND}
    assert type(hit["found"]) is bool
    miss = I.diesel_check(d, ["A page about something else entirely, with no plant named."])
    assert miss == {"found": False, "status": I.QUOTE_MISSING}


def test_diesel_check_not_fetched():
    d = _parsed()["diesel"]
    assert I.diesel_check(d, None, error="HTTP 404") == {"found": False, "status": "not fetched: HTTP 404"}
    with pytest.raises(ValueError):
        I.diesel_check(d, None)
    with pytest.raises(ValueError):
        I.diesel_check(d, None, error="")
    with pytest.raises(ValueError):
        I.diesel_check(d, "not a list")
    with pytest.raises(ValueError):
        I.diesel_check(d, [1, 2])


# ---------- island_row ----------

def test_row_full():
    row = _row(_parsed(study=HASH))
    day = 1478.25 / 365.0
    assert row["solar"] == {"pvout_kwh_per_kwp_yr": 1478.25, "pvout_kwh_per_kwp_day": day, "band": solar_band(day)}
    num, name = wind_class(90.8)
    assert row["wind"] == {"mean_speed_m_s": 4.44, "power_density_w_m2": 90.8, "class_number": num,
                           "class_name": name}
    assert row["hydro"] == {"river": 1, "stream": 2}
    assert row["nearest_town"] == {"name": "Mlonggo", "place": "town", "km": 78.2}
    assert row["nearest_town_status"] == "fetched"
    assert row["verdicts"] == screen_verdicts(pvout_kwh_per_kwp_day=day, wind_class_number=num, rivers=1)
    assert row["costed"] == "yes: study " + HASH
    assert row["missing"] == []
    assert row["diesel"]["found"] is True and row["diesel"]["status"] == I.QUOTE_FOUND
    assert row["diesel"]["outlet"] == "Example News" and row["diesel"]["year"] == 2025
    for key in ("name", "region", "lat_deg", "lon_deg", "point"):
        assert key in row


def test_row_not_costed_without_study():
    assert _row()["costed"] == I.NOT_COSTED


def test_row_missing_parts():
    row = _row(wind=None, gsa=None, water=None, place=None, place_fetched=False)
    assert row["solar"] is None and row["wind"] is None and row["hydro"] is None
    assert row["nearest_town"] is None and row["nearest_town_status"] == I.NOT_FETCHED
    assert row["verdicts"] is None
    assert row["missing"] == ["hydro", "nearest_town", "solar", "wind"]


def test_row_no_town_is_not_missing():
    row = _row(place=None, place_fetched=True)
    assert row["nearest_town_status"] == I.NO_TOWN
    assert row["missing"] == []
    assert row["verdicts"] is not None


def test_row_one_missing_part_drops_verdicts():
    row = _row(wind=None)
    assert row["missing"] == ["wind"] and row["verdicts"] is None and row["solar"] is not None


@pytest.mark.parametrize("kw", [
    {"place": PLACE, "place_fetched": False},
    {"place_fetched": 1},
    {"wind": "x"},
    {"wind": {"mean_speed_m_s": 4.0}},
    {"gsa": {"pvout_kwh_per_kwp_yr": 0.0}},
    {"gsa": {"pvout_kwh_per_kwp_yr": True}},
    {"water": {"river": -1, "stream": 0}},
    {"water": {"river": 1.5, "stream": 0}},
    {"place": {"name": "T", "place": "town", "km": -1.0}},
    {"diesel_result": {"found": "yes", "status": "x"}},
    {"diesel_result": {"found": True}},
])
def test_row_rejects(kw):
    with pytest.raises(ValueError):
        _row(**kw)


# ---------- island_screen_doc ----------

def _rows():
    a = _row(_parsed(study=HASH))
    b = _row(I.parse_island_list(_doc(_island("Beta", lat=-7, lon=114)))[0], wind=None,
             diesel_result={"found": False, "status": I.QUOTE_MISSING})
    b["errors"] = {"wind": "RuntimeError: down"}
    return [a, b]


def test_screen_doc_counts():
    rows = _rows()
    doc = I.island_screen_doc(rows, run_id="islands-1", list_sha256=SHA, files={"f.json": SHA}, wall_s=3)
    assert doc["schema"] == I.ISLAND_SCREEN_SCHEMA and doc["run_id"] == "islands-1"
    assert doc["list_sha256"] == SHA and doc["note"] == I.NOTE
    assert doc["counts"] == {"islands": 2, "diesel_quote_found": 1, "fully_screened": 1, "costed": 1}
    assert doc["rows"] == rows and doc["rows"] is not rows
    assert doc["rows"][1]["errors"] == {"wind": "RuntimeError: down"}
    assert doc["files"] == {"f.json": SHA} and isinstance(doc["wall_s"], float)
    assert doc["sources"] == I.SOURCES


@pytest.mark.parametrize("kw", [
    {"rows": []},
    {"run_id": "resources-1"},
    {"list_sha256": "A" * 64},
    {"list_sha256": "a" * 63},
    {"files": {"f": 1}},
    {"wall_s": -0.1},
    {"wall_s": float("inf")},
])
def test_screen_doc_rejects(kw):
    args = {"rows": _rows(), "run_id": "islands-1", "list_sha256": SHA, "files": {}, "wall_s": 1.0}
    args.update(kw)
    with pytest.raises(ValueError):
        I.island_screen_doc(**args)


# ---------- map_xy and parse_land ----------

def test_map_xy():
    assert I.map_xy(6.5, 94.0) == (0.0, 0.0)
    assert I.map_xy(-11.5, 142.0) == (960.0, 360.0)
    assert I.map_xy(-2.5, 118.0) == (480.0, 180.0)
    x, y = I.map_xy(-5.879626, 110.432907)
    assert (x, y) == (round((110.432907 - 94.0) / 48.0 * 960, 2), round((6.5 + 5.879626) / 18.0 * 360, 2))
    for lat, lon in ((7.0, 100.0), (-12.0, 100.0), (0.0, 93.9), (0.0, 142.1)):
        with pytest.raises(ValueError):
            I.map_xy(lat, lon)
    with pytest.raises(ValueError):
        I.map_xy(True, 100.0)


def test_parse_land():
    doc = {"schema": I.LAND_SCHEMA, "rings": [[[100, -1], [101, -1], [101, 0], [100, 0]]]}
    out = I.parse_land(doc)
    assert out == [[(100.0, -1.0), (101.0, -1.0), (101.0, 0.0), (100.0, 0.0)]]
    assert I.parse_land({"schema": I.LAND_SCHEMA, "rings": []}) == []
    for bad in ({"schema": "x", "rings": []},
                {"schema": I.LAND_SCHEMA, "rings": [[[100, -1], [101, -1], [101, 0]]]},
                {"schema": I.LAND_SCHEMA, "rings": [[[100, -1], [101, -1], [101, 0], [100, "a"]]]},
                {"schema": I.LAND_SCHEMA, "rings": [[[100, -1, 3], [101, -1], [101, 0], [100, 0]]]},
                {"schema": I.LAND_SCHEMA}):
        with pytest.raises(ValueError):
            I.parse_land(bad)


# ---------- render_islands_html ----------

def _page(land=None, rows=None):
    doc = I.island_screen_doc(rows or _rows(), run_id="islands-1", list_sha256=SHA, files={}, wall_s=1.0)
    return I.render_islands_html(doc, land)


def test_page_basics():
    html = _page()
    html.encode("ascii")
    assert html.startswith("<!DOCTYPE html>")
    assert "<script" not in html.lower()
    assert "<title>AutoSolar Researcher: island screen</title>" in html
    assert 'href="index.html"' in html
    assert "Which diesel islands could use solar or wind? A first screen of 2 islands" in html
    assert ("2 islands are named in a news article as running a diesel plant; the tool found the quote in the "
            "fetched page for 1. Fully screened: 1. Costed: 1 (Alpha), the only island with an hourly load.") in html
    assert esc(I.NOTE) in html
    assert 'viewBox="0 0 960 360"' in html


def test_page_table_and_map():
    html = _page()
    heads = re.findall(r"<th[^>]*>(.*?)</th>", html)
    assert heads == ["Island", "Diesel plant named in", "Sun (kWh/kWp a day)", "Wind at 50 m",
                     "Rivers and streams within 10 km", "Nearest mapped town", "Costed here?"]
    assert html.count("<tr") == 3
    assert len(re.findall(r"<circle", html)) == 2
    assert len(re.findall(r'<circle[^>]*class="costed"', html)) == 1
    assert len(re.findall(r'<circle[^>]*class="island"', html)) == 1
    assert '<a href="' + HASH + '.html">yes: study ' + HASH + "</a>" in html
    assert I.NOT_COSTED in html
    assert "4.05, " in html                      # 1478.25 / 365 = 4.05
    assert "4.44 m/s, 91 W/m2, class 1 (Poor)" in html
    assert "1 rivers, 2 streams" in html
    assert "Mlonggo (town), 78 km" in html
    assert I.NOT_FETCHED in html                 # Beta has no wind
    assert I.QUOTE_MISSING in html
    assert '<a href="https://example.org/news/1">Example News 2025</a>' in html
    assert "<q>the island runs on a diesel plant (PLTD)</q>" in html
    assert "Natural Earth (public domain)" in html and "NASA POWER hourly at 50 m, 2016 to 2024" in html


def test_page_land_paths():
    land = I.parse_land({"schema": I.LAND_SCHEMA, "rings": [[[100, -1], [101, -1], [101, 0], [100, 0]],
                                                            [[90, 0], [91, 0], [91, 1], [90, 1]]]})
    html = _page(land)
    paths = re.findall(r'<path class="land" d="([^"]*)"', html)
    assert len(paths) == 2
    assert paths[0].startswith("M 120") and paths[0].rstrip().endswith("Z")
    assert paths[0].count("L ") == 3
    assert "-80" in paths[1]                     # outside the box: still drawn, no error
    assert '<path class="land"' not in _page()


def test_page_escapes_text():
    isl = _island("A&B <x>")
    isl["region"] = "R & S"
    row = _row(I.parse_island_list(_doc(isl))[0])
    html = _page(rows=[row])
    assert "A&amp;B &lt;x&gt;" in html and "R &amp; S" in html
    assert "A&B <x>" not in html
