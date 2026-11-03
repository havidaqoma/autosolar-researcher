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
    assert I.MAP_BBOX_DEG == (95.0, 123.0, -9.5, 4.5)  # T24d
    assert (I.MAP_WIDTH_PX, I.MAP_HEIGHT_PX) == (960, 480)  # T24d
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
    assert I.map_xy(4.5, 95.0) == (0.0, 0.0)  # T24d
    assert I.map_xy(-9.5, 123.0) == (960.0, 480.0)  # T24d
    assert I.map_xy(-2.5, 109.0) == (480.0, 240.0)  # T24d
    x, y = I.map_xy(-5.879626, 110.432907)
    assert (x, y) == (round((110.432907 - 95.0) / 28.0 * 960, 2), round((4.5 + 5.879626) / 14.0 * 480, 2))  # T24d
    for lat, lon in ((4.6, 100.0), (-9.6, 100.0), (0.0, 94.9), (0.0, 123.1)):  # T24d
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
    assert ("The list names 2 islands, each with a news article that says it has a diesel plant (PLTD); the tool "  # T24c
            "found the quote in the fetched page for 1. Fully screened: 1. Costed: 1 (Alpha), the only island with an "
            "hourly load.") in html
    assert esc(I.NOTE) in html
    assert 'viewBox="0 0 960 480"' in html  # T24d


def test_page_table_and_map():
    html = _page()
    heads = re.findall(r"<th[^>]*>(.*?)</th>", html)
    assert heads == ["Island", "Diesel plant named in", "Sun (kWh/kWp a day)", "Wind at 50 m",
                     "Rivers and streams within 10 km", "Nearest mapped town", "Costed here?",
                     "Screen says"]                  # T24b: eighth column
    assert html.count("<tr") == 3
    assert len(re.findall(r"<circle", html)) == 2
    assert len(re.findall(r'<circle[^>]*class="costed"', html)) == 1
    assert len(re.findall(r'<circle[^>]*class="island"', html)) == 1
    assert '<a href="' + HASH + '.html">yes: open the full study</a> (run ' + HASH + ")" in html  # T24c
    assert "<td>" + I.NOT_COSTED_CELL + "</td>" in html                   # T28: short cell
    assert I.NOT_COSTED not in html                                         # T28: the long sentence is said once
    assert "<p>" + esc(I.TABLE_NOTE) + "</p><table>" in html and html.count(esc(I.TABLE_NOTE)) == 1
    assert "4.05, " in html                      # 1478.25 / 365 = 4.05
    assert "4.44 m/s, 91 W/m2, class 1 (Poor)" in html
    assert "1 river, 2 streams" in html            # T24b: was "1 rivers"
    assert "Mlonggo (town), 78 km in a straight line<" in html   # T24c
    assert I.NOT_FETCHED in html                 # Beta has no wind
    assert I.QUOTE_MISSING in html
    assert '<a href="https://example.org/news/1">Example News 2025</a>' in html
    assert "<q>the island runs on a diesel plant (PLTD)</q>" in html
    assert "Natural Earth 1:10m (public domain)" in html and "NASA POWER hourly at 50 m, 2016 to 2024" in html  # T24d


def test_page_land_paths():
    land = I.parse_land({"schema": I.LAND_SCHEMA, "rings": [[[100, -1], [101, -1], [101, 0], [100, 0]],
                                                            [[90, 0], [91, 0], [91, 1], [90, 1]]]})
    html = _page(land)
    paths = re.findall(r'<path class="land" d="([^"]*)"', html)
    assert len(paths) == 2
    assert paths[0].startswith("M 171.43 188.57") and paths[0].rstrip().endswith("Z")  # T24d
    assert paths[0].count("L ") == 3
    assert "-171.43" in paths[1]                 # outside the box: still drawn, no error  # T24d
    assert '<path class="land"' not in _page()


def test_page_escapes_text():
    isl = _island("A&B <x>")
    isl["region"] = "R & S"
    row = _row(I.parse_island_list(_doc(isl))[0])
    html = _page(rows=[row])
    assert "A&amp;B &lt;x&gt;" in html and "R &amp; S" in html
    assert "A&B <x>" not in html


# ---------- written AFTER the T24 code: planted fault i8 (verdict read from streams) was not caught ----------

def test_hydro_verdict_counts_rivers_not_streams():
    """With 1 river and 2 streams both counts give the same verdict; 0 rivers and 3 streams does not."""
    row = _row(water={"river": 0, "stream": 3})
    assert row["verdicts"]["hydro"] == "not on this screen"
    row = _row(water={"river": 2, "stream": 0})
    assert row["verdicts"]["hydro"] == "check flow and head on site"


# ---------- T24b (written before the T24b code) ----------

from autosolar.resources import HYDRO_CHECK, LOOK, NOT_ON_SCREEN  # noqa: E402


def _isl_at(name, lat, lon):
    return I.parse_island_list(_doc(_island(name, lat=lat, lon=lon)))[0]


def test_t24b_constants():
    assert I.LABEL_MERGE_PX == 30.0  # T24d
    assert I.MAP_CSS == ("svg.map{background:#eaf2fa;border:1px solid #c9d6e3}"  # T24d
                         "path.land{fill:#efe9da;stroke:#b8ad94;stroke-width:0.6}"
                         "circle.island{fill:none;stroke:#1a4f9c;stroke-width:2.5}"
                         "circle.costed{fill:none;stroke:#d9822b;stroke-width:3.5}"
                         "svg.map text{fill:#222222;paint-order:stroke;stroke:#ffffff;stroke-width:3px}"
                         "p.mapnote{font-size:0.9em}")


def _verdict_rows():
    a = _row(_isl_at("A", -5.0, 110.0))                                            # solar, hydro
    b = _row(_isl_at("B", -5.0, 112.0), wind={"mean_speed_m_s": 7.0, "power_density_w_m2": 350.0},
             water={"river": 0, "stream": 4})                                      # solar, wind
    c = _row(_isl_at("C", -5.0, 114.0), gsa={"pvout_kwh_per_kwp_yr": 1000.0},
             water={"river": 0, "stream": 0})                                      # nothing
    d = _row(_isl_at("D", -5.0, 116.0), wind=None)                                 # not fully screened
    e = _row(_isl_at("E", -5.0, 118.0), water={"river": 3, "stream": 0})           # solar, hydro
    return [a, b, c, d, e]


def test_t24b_verdict_fixture_is_what_we_think():
    v = [r["verdicts"] for r in _verdict_rows()]
    assert v[0] == {"solar": LOOK, "wind": NOT_ON_SCREEN, "hydro": HYDRO_CHECK}
    assert v[1] == {"solar": LOOK, "wind": LOOK, "hydro": NOT_ON_SCREEN}
    assert v[2] == {"solar": NOT_ON_SCREEN, "wind": NOT_ON_SCREEN, "hydro": NOT_ON_SCREEN}
    assert v[3] is None


def test_t24b_answer_line():
    assert I.answer_line(_verdict_rows()) == (
        "On this screen, of the 4 islands with every part fetched: solar is worth a closer look on 3, wind at 50 m "
        "on 1, and 2 have a mapped river to check for flow and head on site.")
    assert I.answer_line([_verdict_rows()[3]]) == "No island has every part fetched, so the screen gives no verdict."
    assert I.answer_line([]) == "No island has every part fetched, so the screen gives no verdict."
    with pytest.raises(ValueError):
        I.answer_line("rows")


def test_t24b_verdict_text():
    rows = _verdict_rows()
    # T28: parts that are not on this screen are left out; nothing left says so
    assert I.verdict_text(rows[0]) == "solar: " + LOOK + "; hydro: " + HYDRO_CHECK
    assert I.verdict_text(rows[1]) == "solar: " + LOOK + "; wind: " + LOOK
    assert I.verdict_text(rows[2]) == I.NOTHING_PASSES
    assert I.verdict_text(rows[3]) == I.NOT_FETCHED


def test_t28_constants():
    assert I.NOT_COSTED == "no: no hourly load, so no cost; the tool refuses rather than guess"   # stored value
    assert I.NOT_COSTED_CELL == "no: no hourly load"
    assert I.NOTHING_PASSES == "nothing passes this screen"
    assert I.TABLE_NOTE == ("Costed here: the tool costs an island only when it has an hourly load; without one it "
                            "refuses rather than guess. Screen says: only what passes the screen rule above.")


def test_t28_page_says_not_on_screen_nowhere():
    html = I.render_islands_html(I.island_screen_doc(_verdict_rows(), run_id="islands-1", list_sha256=SHA,
                                                     files={}, wall_s=1.0))
    assert NOT_ON_SCREEN not in html
    assert "<td>" + I.NOTHING_PASSES + "</td>" in html                       # island C passes nothing


def _rows_at(points):
    return [_row(_isl_at(name, lat, lon)) for name, lat, lon in points]


def test_t24b_label_groups_madura_cluster():
    pts = [("Raas", -7.147953, 114.588171), ("Kangean", -6.919626, 115.273309), ("Sapudi", -7.118528, 114.33041),
           ("Masalembu", -5.561209, 114.422845)]
    groups = I.label_groups(_rows_at(pts))
    xy = {n: I.map_xy(lat, lon) for n, lat, lon in pts}
    assert [g["names"] for g in groups] == [["Raas", "Kangean", "Sapudi"], ["Masalembu"]]
    assert groups[0]["x"] == round(max(xy["Raas"][0], xy["Kangean"][0], xy["Sapudi"][0]) + 10.0, 2)  # T24d
    assert groups[0]["y"] == round(xy["Raas"][1] + 4.0, 2)
    assert groups[1] == {"names": ["Masalembu"], "x": round(xy["Masalembu"][0] + 10.0, 2),  # T24d
                         "y": round(xy["Masalembu"][1] + 4.0, 2)}


def test_t24b_label_groups_edges():
    # T24d: exactly 30 px apart (0.875 deg of longitude is 30 px) counts as within; 30.86 px does not
    assert [g["names"] for g in I.label_groups(_rows_at([("P", 0.0, 95.0), ("Q", 0.0, 95.875)]))] == [["P", "Q"]]
    assert [g["names"] for g in I.label_groups(_rows_at([("P", 0.0, 95.0), ("Q", 0.0, 95.9)]))] == [["P"], ["Q"]]
    # a row joins the group of the FIRST earlier row within reach, and groups keep the order they start in
    groups = I.label_groups(_rows_at([("P", 0.0, 95.0), ("Q", 0.0, 96.3125), ("R", 0.0, 95.65625)]))  # T24d
    assert [g["names"] for g in groups] == [["P", "R"], ["Q"]]
    assert groups[0]["x"] == 32.5 and groups[1]["x"] == 55.0  # T24d: 22.5 + 10 and 45 + 10
    with pytest.raises(ValueError):
        I.label_groups([])


def test_t24b_page():
    rows = _verdict_rows()
    doc = I.island_screen_doc(rows, run_id="islands-1", list_sha256=SHA, files={}, wall_s=1.0)
    html = I.render_islands_html(doc)
    assert '<meta charset="utf-8">' in html and I.MAP_CSS in html
    assert '<svg class="map" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 480" role="img">' in html  # T24d
    answer = '<p class="answer"><b>' + esc(I.answer_line(rows)) + "</b></p>"
    assert answer in html
    assert html.index("The list names 5 islands") < html.index(answer) < html.index(esc(I.NOTE))  # T24c
    assert re.findall(r"<th[^>]*>(.*?)</th>", html)[-1] == "Screen says"
    assert esc(I.verdict_text(rows[0])) in html
    assert html.count("<td>" + I.NOT_FETCHED + "</td>") >= 2          # D: wind cell and its verdict cell
    assert "0 rivers, 4 streams" in html and "3 rivers, 0 streams" in html
    assert "<script" not in html.lower()


def test_t24b_page_merged_labels_and_plurals():
    pts = [("Raas", -7.147953, 114.588171), ("Kangean", -6.919626, 115.273309), ("Sapudi", -7.118528, 114.33041)]
    rows = _rows_at(pts)
    rows[1] = _row(_isl_at("Kangean", -6.919626, 115.273309), water={"river": 0, "stream": 1})
    doc = I.island_screen_doc(rows, run_id="islands-1", list_sha256=SHA, files={}, wall_s=1.0)
    html = I.render_islands_html(doc)
    assert len(re.findall(r"<circle", html)) == 3
    texts = re.findall(r"<text[^>]*>(.*?)</text>", html)
    assert texts == ["Raas, Kangean, Sapudi"]
    assert "0 rivers, 1 stream<" in html


# ---------- T24c (written before the T24c code) ----------

def test_t24c_note_and_rule():
    assert I.NOTE == (
        "Written after the studies ran (post hoc). A convenience list, not a sample of PLN's 741 sites: each island is "
        "named in a news article as having a diesel plant (PLTD), and the tool checks the quote in the page it "
        "fetches; a found quote shows the words are on the page, not that the plant runs today. Only Karimunjawa has "
        "an hourly load, so only Karimunjawa is costed. Sun, wind and rivers are a first screen from free public "
        "data, not a resource assessment; nothing here costs wind, hydro or a grid link, and the nearest town is not "
        "a grid connection.")
    assert I.SCREEN_RULE == (
        "Screen rule (assumed): solar is worth a closer look at 3.5 kWh/kWp a day or more, the lower bound of the "
        "World Bank's favorable range; wind at class 3 or more on the NREL scale at 50 m (class 1, Poor, is the "
        "lowest); hydro needs at least one mapped river within 10 km (streams are listed but not counted), and then "
        "flow and head decide.")
    from autosolar import resources as RS
    assert "at %.1f kWh/kWp a day" % RS.SOLAR_LOOK_KWH_PER_KWP_DAY in I.SCREEN_RULE
    assert "class %d or more" % RS.WIND_LOOK_CLASS in I.SCREEN_RULE
    assert "within %.0f km" % RS.WATER_RADIUS_KM in I.SCREEN_RULE


def test_t24c_page_order_and_footer():
    rows = _verdict_rows()
    doc = I.island_screen_doc(rows, run_id="islands-1", list_sha256=SHA, files={}, wall_s=1.0)
    html = I.render_islands_html(doc)
    answer = '<p class="answer"><b>' + esc(I.answer_line(rows)) + "</b></p>"
    rule = "<p>" + esc(I.SCREEN_RULE) + "</p>"
    assert html.count(rule) == 1
    assert html.index(answer) < html.index(rule) < html.index(esc(I.NOTE))
    assert ("Rivers and towns: OpenStreetMap, counts of mapped features (measured); town distance in a straight line "
            "from the island point (computed). Coordinates: OpenStreetMap Nominatim.") in html
    assert "running a diesel plant" not in html


def test_t24c_town_cell_zero_km():
    def town_html(km):
        row = _row(place={"name": "Benteng", "place": "town", "km": km})
        doc = I.island_screen_doc([row], run_id="islands-1", list_sha256=SHA, files={}, wall_s=1.0)
        return I.render_islands_html(doc)
    assert "Benteng (town), 0 km in a straight line; the island point is in this town<" in town_html(0.3)
    assert "Benteng (town), 0 km in a straight line; the island point is in this town<" in town_html(0.0)
    html = town_html(0.6)
    assert "Benteng (town), 1 km in a straight line<" in html and "the island point is in this town" not in html


def test_t24c_not_costed_row_unchanged():
    row = _row(_isl_at("Q", -5.0, 112.0))
    assert row["costed"] == I.NOT_COSTED                                     # the stored value is unchanged
    doc = I.island_screen_doc([row], run_id="islands-1", list_sha256=SHA, files={}, wall_s=1.0)
    html = I.render_islands_html(doc)
    # T28: the cell is now the short NOT_COSTED_CELL (this line was missed when the T28 tests were written and was
    # found by the first run after the T28 code)
    assert "<td>" + esc(I.NOT_COSTED_CELL) + "</td>" in html and "open the full study" not in html


# ---------- T24d (written before the T24d code) ----------

import json  # noqa: E402
import pathlib  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
SQUARE = [[(100.0, -1.0), (101.0, -1.0), (101.0, 0.0), (100.0, 0.0)]]


def test_t24d_constants():
    assert I.MARKER_R_PX == 6.0
    assert I.LABEL_GAP_PX == 10.0
    assert I.UNDRAWN_TOL_KM == 2.0
    assert I.OSM_LINK_TEXT == "the point on OpenStreetMap"
    assert I.MAP_NOTE_HEAD == ("Each ring marks the island point from OpenStreetMap Nominatim; the link under each "
                               "island name in the table opens that point on OpenStreetMap.")
    assert I.MAP_NOTE_SMALL == "Too small for the land outline at this scale, so the ring sits on open sea: "
    lon_min, lon_max, lat_min, lat_max = I.MAP_BBOX_DEG
    assert I.MAP_WIDTH_PX / (lon_max - lon_min) == I.MAP_HEIGHT_PX / (lat_max - lat_min)  # same px a degree


def test_t24d_osm_url():
    assert I.osm_url(-5.879626, 110.432907) == (
        "https://www.openstreetmap.org/?mlat=-5.8796&mlon=110.4329#map=12/-5.8796/110.4329")
    assert I.osm_url(2.5, 109) == "https://www.openstreetmap.org/?mlat=2.5000&mlon=109.0000#map=12/2.5000/109.0000"
    for bad in ((True, 100.0), (0.0, False), (float("nan"), 100.0), (0.0, float("inf")), (90.1, 0.0),
                (-90.1, 0.0), (0.0, 180.1), (0.0, -180.1), ("1", 100.0), (None, 100.0)):
        with pytest.raises(ValueError):
            I.osm_url(*bad)


def _pt(name, lat, lon):
    return {"name": name, "lat_deg": lat, "lon_deg": lon}


def test_t24d_undrawn_names_inside_and_edge():
    # 0.01 deg of longitude near the equator is about 1.11 km, 0.05 deg about 5.6 km
    rows = [_pt("in", -0.5, 100.5), _pt("near", -0.5, 101.01), _pt("far", -0.5, 101.05),
            _pt("corner", 0.01, 101.01)]
    assert I.undrawn_names(rows, SQUARE) == ["far"]
    assert I.undrawn_names(rows, SQUARE, tol_km=0.0) == ["near", "far", "corner"]
    assert I.undrawn_names(rows, SQUARE, tol_km=10.0) == []
    assert I.undrawn_names(rows, None) == ["in", "near", "far", "corner"]
    assert I.undrawn_names(rows, []) == ["in", "near", "far", "corner"]


def test_t24d_undrawn_names_closing_edge_and_even_odd():
    # the edge from the last point back to the first counts
    assert I.undrawn_names([_pt("left", 0.5, 99.99)], [[(100.0, 0.0), (101.0, 0.0), (101.0, 1.0), (100.0, 1.0)]]) == []
    # a U shape: the point in the notch is outside the ring and about 33 km from it
    u_ring = [[(100.0, 0.0), (101.0, 0.0), (101.0, 1.0), (100.8, 1.0), (100.8, 0.2), (100.2, 0.2), (100.2, 1.0),
               (100.0, 1.0)]]
    assert I.undrawn_names([_pt("notch", 0.6, 100.5)], u_ring) == ["notch"]
    assert I.undrawn_names([_pt("arm", 0.6, 100.1)], u_ring) == []


def test_t24d_undrawn_names_rejects():
    for tol in (-0.1, float("nan"), float("inf"), True, "2"):
        with pytest.raises(ValueError):
            I.undrawn_names([_pt("a", 0.0, 100.0)], SQUARE, tol_km=tol)
    with pytest.raises(ValueError):
        I.undrawn_names("rows", SQUARE)
    with pytest.raises(ValueError):
        I.undrawn_names(["row"], SQUARE)


def test_t24d_map_note():
    assert I.map_note([]) == I.MAP_NOTE_HEAD
    assert I.map_note(["Derawan", "Balai"]) == (
        I.MAP_NOTE_HEAD + " Too small for the land outline at this scale, so the ring sits on open sea: "
        "Derawan, Balai.")
    for bad in ("Derawan", [1], None):
        with pytest.raises(ValueError):
            I.map_note(bad)


def _t24d_doc():
    alpha = I.parse_island_list(_doc(_island("Alpha", study=HASH, lat=-0.5, lon=100.5)))[0]
    rows = [_row(alpha), _row(_isl_at("Beta", -0.5, 105.0))]
    return rows, I.island_screen_doc(rows, run_id="islands-1", list_sha256=SHA, files={}, wall_s=1.0)


def test_t24d_page_rings_note_and_links():
    rows, doc = _t24d_doc()
    html = I.render_islands_html(doc, SQUARE)
    assert 'viewBox="0 0 960 480"' in html and I.MAP_CSS in html
    assert re.findall(r'<circle class="(\w+)"[^>]*\sr="6"', html) == ["costed", "island"]
    assert 'r="5"' not in html
    note = '<p class="mapnote">' + esc(I.map_note(["Beta"])) + "</p>"
    assert note in html
    assert html.index("</svg>") < html.index(note) < html.index("<table")
    link = '<a href="' + esc(I.osm_url(-0.5, 100.5)) + '">the point on OpenStreetMap</a>'
    assert "<td>Alpha<br>Somewhere, Java<br>" + link + "</td>" in html
    assert "mlat=-0.5000&amp;mlon=100.5000" in html
    assert esc(I.osm_url(-0.5, 105.0)) in html
    assert "Land outline: Natural Earth 1:10m (public domain)." in html
    assert "<script" not in html.lower()
    plain = I.render_islands_html(doc)
    assert '<p class="mapnote">' + esc(I.map_note(["Alpha", "Beta"])) + "</p>" in plain


def test_t24d_page_label_gap():
    rows, doc = _t24d_doc()
    html = I.render_islands_html(doc, SQUARE)
    xs = [float(x) for x in re.findall(r'<text x="([0-9.]+)"', html)]
    dot_x = [I.map_xy(-0.5, 100.5)[0], I.map_xy(-0.5, 105.0)[0]]
    assert xs == [round(dot_x[0] + 10.0, 2), round(dot_x[1] + 10.0, 2)]


def test_t24d_shipped_land_file_and_points():
    land_doc = json.loads((ROOT / "config" / "land_rings_indonesia.json").read_text(encoding="ascii"))
    assert land_doc["source"].startswith("Natural Earth 1:10m land, public domain")
    assert land_doc["bbox_deg"] == list(I.MAP_BBOX_DEG)
    land = I.parse_land(land_doc)
    rows = I.parse_island_list(json.loads((ROOT / "config" / "island_screen.json").read_text(encoding="ascii")))
    for row in rows:
        I.map_xy(row["lat_deg"], row["lon_deg"])     # every point is inside the new box
    # measured before the code (post hoc): the two islands too small for the 1:10m outline
    assert I.undrawn_names(rows, land) == ["Derawan", "Balai"]


def test_t24d_after_code_km_scale_uses_latitude():
    # written AFTER the T24d code (planted fault d4 was missed): at 60 deg north 1 deg of longitude is
    # 111.32 * cos(60 deg) = 55.66 km, so 0.03 deg is 1.67 km (drawn at 2 km) and not 3.34 km
    ring = [[(10.0, 59.0), (11.0, 59.0), (11.0, 61.0), (10.0, 61.0)]]
    assert I.undrawn_names([_pt("north", 60.0, 11.03)], ring) == []
    assert I.undrawn_names([_pt("north", 60.0, 11.05)], ring) == ["north"]
