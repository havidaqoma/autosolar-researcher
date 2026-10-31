"""First screen of named diesel islands for sun, wind, rivers and towns.

Coordinates in deg, PV output in kWh per kWp, wind power density in W per m2,
distances in km, wall time in s. No network at import time or anywhere here.
"""

from __future__ import annotations

import math

from autosolar.cite_check import find_quote
from autosolar.resources import (
    HYDRO_CHECK,
    LOOK,
    PLACE_RADIUS_KM,
    SOURCES as RESOURCE_SOURCES,
    WATER_RADIUS_KM,
    WIND_YEARS,
    screen_verdicts,
    solar_band,
    wind_class,
)
from autosolar.site import SITE_CSS, esc

ISLAND_LIST_SCHEMA = "autosolar.island_list/1"
ISLAND_SCREEN_SCHEMA = "autosolar.island_screen/1"
LAND_SCHEMA = "autosolar.land_rings/1"
MAP_BBOX_DEG = (94.0, 142.0, -11.5, 6.5)
MAP_WIDTH_PX = 960
MAP_HEIGHT_PX = 360
QUOTE_MIN_CHARS = 20
NOT_COSTED = "no: no hourly load, so no cost; the tool refuses rather than guess"
NOT_FETCHED = "not fetched"
NO_TOWN = "none within 150 km"
QUOTE_FOUND = "quote found in the fetched page"
QUOTE_MISSING = "quote not in the fetched page"
NOTE = (
    "Written after the studies ran (post hoc). A convenience list, not a sample of PLN's 741 sites: each island "
    "is named in a news article as running a diesel plant (PLTD), and the tool checks the quote in the page it "
    "fetches. Only Karimunjawa has an hourly load, so only Karimunjawa is costed. Sun, wind and rivers are a "
    "first screen from free public data, not a resource assessment; nothing here costs wind, hydro or a grid "
    "link, and the nearest town is not a grid connection."
)
SOURCES = {
    "nasa_power_hourly": RESOURCE_SOURCES["nasa_power_hourly"],
    "global_solar_atlas": RESOURCE_SOURCES["global_solar_atlas"],
    "overpass": RESOURCE_SOURCES["overpass"],
    "nominatim": "https://nominatim.openstreetmap.org/search",
    "natural_earth": "https://www.naturalearthdata.com/",
}

_HEX = "0123456789abcdef"
_FOOTER = (
    "Sun: Global Solar Atlas (a Solargis model), long-term PV output at the optimum tilt. Wind: "
    "NASA POWER hourly at 50 m, 2016 to 2024 (computed). Rivers and towns: OpenStreetMap, counts of mapped features "
    "(measured). Coordinates: OpenStreetMap Nominatim. Land outline: Natural Earth (public domain). Diesel: press, "
    "quote re-checked by the tool."
)
LABEL_MERGE_PX = 20.0
MAP_CSS = ("svg.map{background:#eaf2fa;border:1px solid #c9d6e3}"
           "path.land{fill:#efe9da;stroke:#b8ad94;stroke-width:0.6}"
           "circle.island{fill:#1a4f9c;stroke:#ffffff;stroke-width:1.5}"
           "circle.costed{fill:#d9822b;stroke:#000000;stroke-width:1.5}"
           "svg.map text{fill:#222222;paint-order:stroke;stroke:#ffffff;stroke-width:3px}")
_HEADS = ("Island", "Diesel plant named in", "Sun (kWh/kWp a day)", "Wind at 50 m",
          "Rivers and streams within 10 km", "Nearest mapped town", "Costed here?",
          "Screen says")


def _finite_real(name_str: str, value: object) -> float:
    """Value as a finite float. Raises ValueError on bad input."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name_str + " must be a finite real: " + repr(value))
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " must be a finite real: " + repr(value))
    return out


def _check_study(value: object) -> str | None:
    """Study hash or None. Raises ValueError on bad input."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 16:
        raise ValueError("study must be None or 16 lowercase hex chars: " + repr(value))
    for char in value:
        if char not in _HEX:
            raise ValueError("study must be None or 16 lowercase hex chars: " + repr(value))
    return value


def parse_island_list(doc: dict) -> list:
    """Islands from a list doc. Coordinates in deg. Returns new dicts."""
    if not isinstance(doc, dict):
        raise ValueError("doc must be a dict")
    if doc.get("schema") != ISLAND_LIST_SCHEMA:
        raise ValueError("doc schema must be " + ISLAND_LIST_SCHEMA)
    islands = doc.get("islands")
    if not isinstance(islands, list) or not islands:
        raise ValueError("islands must be a non-empty list")
    seen: set[str] = set()
    out: list[dict] = []
    for item in islands:
        if not isinstance(item, dict):
            raise ValueError("island must be a dict")
        for key in ("name", "region", "lat_deg", "lon_deg", "point", "diesel", "study"):
            if key not in item:
                raise ValueError("island missing key: " + key)
        name = item["name"]
        if not isinstance(name, str) or name == "":
            raise ValueError("name must be a non-empty str: " + repr(name))
        if name in seen:
            raise ValueError("name must be unique: " + repr(name))
        seen.add(name)
        region = item["region"]
        if not isinstance(region, str):
            raise ValueError("region must be a str: " + repr(region))
        lat = _finite_real("lat_deg", item["lat_deg"])
        if not -90.0 <= lat <= 90.0:
            raise ValueError("lat_deg must be within -90 to 90: " + repr(item["lat_deg"]))
        lon = _finite_real("lon_deg", item["lon_deg"])
        if not -180.0 <= lon <= 180.0:
            raise ValueError("lon_deg must be within -180 to 180: " + repr(item["lon_deg"]))
        point = item["point"]
        if not isinstance(point, str):
            raise ValueError("point must be a str: " + repr(point))
        diesel = item["diesel"]
        if not isinstance(diesel, dict):
            raise ValueError("diesel must be a dict")
        for key in ("url", "quote", "outlet", "year", "label"):
            if key not in diesel:
                raise ValueError("diesel missing key: " + key)
        url = diesel["url"]
        if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError("diesel url must start with http:// or https://: " + repr(url))
        quote = diesel["quote"]
        if not isinstance(quote, str) or len(quote.strip()) < QUOTE_MIN_CHARS:
            raise ValueError("diesel quote must hold at least 20 chars: " + repr(quote))
        outlet = diesel["outlet"]
        if not isinstance(outlet, str) or outlet == "":
            raise ValueError("diesel outlet must be a non-empty str: " + repr(outlet))
        year = diesel["year"]
        if type(year) is not int or not 1990 <= year <= 2100:
            raise ValueError("diesel year must be an int from 1990 to 2100: " + repr(year))
        if diesel["label"] != "press":
            raise ValueError("diesel label must be press: " + repr(diesel["label"]))
        study = _check_study(item["study"])
        out.append({"name": name, "region": region, "lat_deg": float(lat), "lon_deg": float(lon),
                    "point": point,
                    "diesel": {"url": url, "quote": quote, "outlet": outlet, "year": year,
                               "label": "press"},
                    "study": study})
    return out


def diesel_check(diesel: dict, pages: list | None, error: str | None = None) -> dict:
    """Quote check for one island. Pages hold text. Returns found and status."""
    if not isinstance(diesel, dict):
        raise ValueError("diesel must be a dict")
    quote = diesel.get("quote")
    if not isinstance(quote, str):
        raise ValueError("diesel quote must be a str")
    if pages is None:
        if not isinstance(error, str) or error == "":
            raise ValueError("error must be a non-empty str when pages is None")
        return {"found": False, "status": "not fetched: " + error}
    if not isinstance(pages, list):
        raise ValueError("pages must be a list of str")
    for page in pages:
        if not isinstance(page, str):
            raise ValueError("pages must be a list of str")
    match = find_quote(quote, pages)
    if match.found:
        return {"found": True, "status": QUOTE_FOUND}
    return {"found": False, "status": QUOTE_MISSING}


def island_row(island: dict, *, wind: dict | None, gsa: dict | None, water: dict | None,
               place: dict | None, place_fetched: bool, diesel_result: dict) -> dict:
    """Screen row for one island. Speeds in m per s, yields in kWh per kWp."""
    if not isinstance(island, dict):
        raise ValueError("island must be a dict")
    for key in ("name", "region", "lat_deg", "lon_deg", "point", "diesel", "study"):
        if key not in island:
            raise ValueError("island missing key: " + key)
    if not isinstance(place_fetched, bool):
        raise ValueError("place_fetched must be a bool: " + repr(place_fetched))
    if not place_fetched and place is not None:
        raise ValueError("place must be None when not fetched")
    if wind is not None:
        if not isinstance(wind, dict):
            raise ValueError("wind must be a dict or None")
        try:
            mean_m_s = _finite_real("mean_speed_m_s", wind["mean_speed_m_s"])
            power_w_m2 = _finite_real("power_density_w_m2", wind["power_density_w_m2"])
        except KeyError as exc:
            raise ValueError("wind must hold mean_speed_m_s and power_density_w_m2") from exc
    if gsa is not None:
        if not isinstance(gsa, dict):
            raise ValueError("gsa must be a dict or None")
        try:
            pvout = _finite_real("pvout_kwh_per_kwp_yr", gsa["pvout_kwh_per_kwp_yr"])
        except KeyError as exc:
            raise ValueError("gsa must hold pvout_kwh_per_kwp_yr") from exc
        if not pvout > 0.0:
            raise ValueError("pvout_kwh_per_kwp_yr must be above 0: " + repr(pvout))
    if water is not None:
        if not isinstance(water, dict):
            raise ValueError("water must be a dict or None")
        try:
            river = water["river"]
            stream = water["stream"]
        except KeyError as exc:
            raise ValueError("water must hold river and stream") from exc
        for label, count in (("river", river), ("stream", stream)):
            if isinstance(count, bool) or not isinstance(count, int):
                raise ValueError(label + " must be an int 0 or more: " + repr(count))
            if count < 0:
                raise ValueError(label + " must be an int 0 or more: " + repr(count))
    if place is not None:
        if not isinstance(place, dict):
            raise ValueError("place must be a dict or None")
        for key in ("name", "place", "km"):
            if key not in place:
                raise ValueError("place missing key: " + key)
        if not isinstance(place["name"], str):
            raise ValueError("place name must be a str")
        if not isinstance(place["place"], str):
            raise ValueError("place place must be a str")
        _finite_real("km", place["km"])
        if float(place["km"]) < 0.0:
            raise ValueError("km must be 0 or more: " + repr(place["km"]))
    if not isinstance(diesel_result, dict):
        raise ValueError("diesel_result must be a dict")
    if "found" not in diesel_result or "status" not in diesel_result:
        raise ValueError("diesel_result must hold found and status")
    found = diesel_result["found"]
    status = diesel_result["status"]
    if type(found) is not bool:
        raise ValueError("diesel found must be a bool: " + repr(found))
    if not isinstance(status, str):
        raise ValueError("diesel status must be a str")
    diesel = island["diesel"]
    row: dict = {"name": island["name"], "region": island["region"],
                 "lat_deg": island["lat_deg"], "lon_deg": island["lon_deg"],
                 "point": island["point"],
                 "diesel": {"url": diesel["url"], "quote": diesel["quote"],
                            "outlet": diesel["outlet"], "year": diesel["year"],
                            "label": diesel["label"], "found": bool(found), "status": status}}
    if gsa is None:
        row["solar"] = None
        day = None
    else:
        yr = float(gsa["pvout_kwh_per_kwp_yr"])
        day = yr / 365.0
        row["solar"] = {"pvout_kwh_per_kwp_yr": yr, "pvout_kwh_per_kwp_day": day,
                        "band": solar_band(day)}
    if wind is None:
        row["wind"] = None
        number = None
    else:
        number, cname = wind_class(float(wind["power_density_w_m2"]))
        row["wind"] = {"mean_speed_m_s": float(wind["mean_speed_m_s"]),
                       "power_density_w_m2": float(wind["power_density_w_m2"]),
                       "class_number": int(number), "class_name": str(cname)}
    if water is None:
        row["hydro"] = None
    else:
        row["hydro"] = {"river": int(water["river"]), "stream": int(water["stream"])}
    if place is None:
        row["nearest_town"] = None
        row["nearest_town_status"] = NO_TOWN if place_fetched else NOT_FETCHED
    else:
        row["nearest_town"] = {"name": place["name"], "place": place["place"],
                               "km": float(place["km"])}
        row["nearest_town_status"] = "fetched"
    if row["solar"] is not None and row["wind"] is not None and row["hydro"] is not None:
        row["verdicts"] = screen_verdicts(pvout_kwh_per_kwp_day=float(day),
                                          wind_class_number=int(number),
                                          rivers=int(water["river"]))
    else:
        row["verdicts"] = None
    study = island["study"]
    row["costed"] = "yes: study " + study if isinstance(study, str) else NOT_COSTED
    missing: list[str] = []
    if gsa is None:
        missing.append("solar")
    if wind is None:
        missing.append("wind")
    if water is None:
        missing.append("hydro")
    if not place_fetched:
        missing.append("nearest_town")
    row["missing"] = sorted(missing)
    return row


def island_screen_doc(rows: list, *, run_id: str, list_sha256: str, files: dict,
                      wall_s: float) -> dict:
    """Screen record for the island list. Wall time in s. Returns a dict."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows must be a non-empty list")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("rows must hold dicts")
    if not isinstance(run_id, str) or not run_id.startswith("islands-"):
        raise ValueError("run_id must start with islands-: " + repr(run_id))
    if not isinstance(list_sha256, str) or len(list_sha256) != 64:
        raise ValueError("list_sha256 must be 64 lowercase hex chars")
    for char in list_sha256:
        if char not in _HEX:
            raise ValueError("list_sha256 must be 64 lowercase hex chars")
    if not isinstance(files, dict):
        raise ValueError("files must map str to str")
    for key, value in files.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("files must map str to str")
    wall = _finite_real("wall_s", wall_s)
    if not wall >= 0.0:
        raise ValueError("wall_s must be 0 or more: " + repr(wall_s))
    found = sum(1 for r in rows if isinstance(r.get("diesel"), dict)
                and r["diesel"].get("found") is True)
    full = sum(1 for r in rows if r.get("missing") == [])
    costed = sum(1 for r in rows if isinstance(r.get("costed"), str)
                 and str(r["costed"]).startswith("yes"))
    return {"schema": ISLAND_SCREEN_SCHEMA, "run_id": run_id, "list_sha256": list_sha256,
            "note": NOTE,
            "counts": {"islands": len(rows), "diesel_quote_found": int(found),
                       "fully_screened": int(full), "costed": int(costed)},
            "rows": [dict(r) for r in rows], "files": dict(files), "wall_s": float(wall),
            "sources": dict(SOURCES)}


def _project(lon_deg: float, lat_deg: float) -> tuple:
    """Map position in px for lon and lat in deg. No inside check."""
    lon = float(lon_deg)
    lat = float(lat_deg)
    lon_min, lon_max, lat_min, lat_max = MAP_BBOX_DEG
    x = (lon - lon_min) / (lon_max - lon_min) * MAP_WIDTH_PX
    y = (lat_max - lat) / (lat_max - lat_min) * MAP_HEIGHT_PX
    return (round(x, 2), round(y, 2))


def map_xy(lat_deg: float, lon_deg: float) -> tuple:
    """Map position in px for lat and lon in deg. Raises outside the box."""
    lat = _finite_real("lat_deg", lat_deg)
    lon = _finite_real("lon_deg", lon_deg)
    lon_min, lon_max, lat_min, lat_max = MAP_BBOX_DEG
    if not lon_min <= lon <= lon_max:
        raise ValueError("lon_deg outside the map box: " + repr(lon_deg))
    if not lat_min <= lat <= lat_max:
        raise ValueError("lat_deg outside the map box: " + repr(lat_deg))
    x, y = _project(lon, lat)
    return (float(x), float(y))


def parse_land(doc: dict) -> list:
    """Land rings for the map. Ring points hold lon and lat in deg."""
    if not isinstance(doc, dict):
        raise ValueError("doc must be a dict")
    if doc.get("schema") != LAND_SCHEMA:
        raise ValueError("doc schema must be " + LAND_SCHEMA)
    rings = doc.get("rings")
    if not isinstance(rings, list):
        raise ValueError("rings must be a list")
    out: list[list[tuple]] = []
    for ring in rings:
        if not isinstance(ring, list) or len(ring) < 4:
            raise ValueError("each ring must hold at least 4 points")
        one: list[tuple] = []
        for point in ring:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("each point must hold two finite reals: " + repr(point))
            lon = _finite_real("lon", point[0])
            lat = _finite_real("lat", point[1])
            one.append((float(lon), float(lat)))
        out.append(one)
    return out


def _sun_cell(row: dict) -> str:
    """Sun table cell. Output in kWh per kWp a day. Returns HTML."""
    solar = row.get("solar")
    if solar is None:
        return esc(NOT_FETCHED)
    return esc("%.2f, %s" % (float(solar["pvout_kwh_per_kwp_day"]), str(solar["band"])))


def _wind_cell(row: dict) -> str:
    """Wind table cell. Speed in m per s, density in W per m2. Returns HTML."""
    wind = row.get("wind")
    if wind is None:
        return esc(NOT_FETCHED)
    return esc("%.2f m/s, %.0f W/m2, class %d (%s)"
               % (float(wind["mean_speed_m_s"]), float(wind["power_density_w_m2"]),
                  int(wind["class_number"]), str(wind["class_name"])))


def _hydro_cell(row: dict) -> str:
    """Rivers table cell. Counts are ints. Returns HTML."""
    hydro = row.get("hydro")
    if hydro is None:
        return esc(NOT_FETCHED)
    rivers_n = int(hydro["river"])
    streams_n = int(hydro["stream"])
    river_txt = "1 river" if rivers_n == 1 else "%d rivers" % rivers_n
    stream_txt = "1 stream" if streams_n == 1 else "%d streams" % streams_n
    return esc(river_txt + ", " + stream_txt)


def answer_line(rows: list) -> str:
    """One line verdict counts for a screen. Counts are ints. Returns str."""
    if not isinstance(rows, list):
        raise ValueError("rows must be a list: " + repr(rows))
    screened = [r for r in rows if isinstance(r, dict) and isinstance(r.get("verdicts"), dict)]
    if not screened:
        return "No island has every part fetched, so the screen gives no verdict."
    solar_n = sum(1 for r in screened if r["verdicts"].get("solar") == LOOK)
    wind_n = sum(1 for r in screened if r["verdicts"].get("wind") == LOOK)
    hydro_n = sum(1 for r in screened if r["verdicts"].get("hydro") == HYDRO_CHECK)
    return ("On this screen, of the %d islands with every part fetched: "
            "solar is worth a closer look on %d, wind at 50 m on %d, and %d have a "
            "mapped river to check for flow and head on site."
            % (len(screened), int(solar_n), int(wind_n), int(hydro_n)))


def verdict_text(row: dict) -> str:
    """Verdict words for one row. Returns str."""
    if not isinstance(row, dict):
        raise ValueError("row must be a dict")
    verdicts = row.get("verdicts")
    if verdicts is None:
        return NOT_FETCHED
    return ("solar: " + str(verdicts["solar"]) + "; wind: " + str(verdicts["wind"])
            + "; hydro: " + str(verdicts["hydro"]))


def label_groups(rows: list) -> list:
    """Label groups for close dots. Positions in px. Returns dicts."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows must be a non-empty list")
    dots_px: list[tuple] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("rows must hold dicts")
        dots_px.append(map_xy(row["lat_deg"], row["lon_deg"]))
    names: list[str] = [str(r["name"]) for r in rows]
    group_idx: list[int] = []
    groups: list[dict] = []
    members: list[list[int]] = []
    for i in range(len(rows)):
        placed = None
        for j in range(i):
            dx_px = float(dots_px[i][0]) - float(dots_px[j][0])
            dy_px = float(dots_px[i][1]) - float(dots_px[j][1])
            if (dx_px * dx_px + dy_px * dy_px) ** 0.5 <= LABEL_MERGE_PX:
                placed = group_idx[j]
                break
        if placed is None:
            placed = len(groups)
            groups.append({})
            members.append([])
        group_idx.append(placed)
        members[placed].append(i)
    out: list[dict] = []
    for idx_list in members:
        top_x_px = max(float(dots_px[i][0]) for i in idx_list) + 7.0
        first_y_px = float(dots_px[idx_list[0]][1]) + 4.0
        out.append({"names": [names[i] for i in idx_list],
                    "x": round(top_x_px, 2), "y": round(first_y_px, 2)})
    return out


def _town_cell(row: dict) -> str:
    """Town table cell. Distance in km. Returns HTML."""
    town = row.get("nearest_town")
    if isinstance(town, dict):
        return esc("%s (%s), %.0f km" % (str(town["name"]), str(town["place"]),
                                         float(town["km"])))
    if row.get("nearest_town_status") == NO_TOWN:
        return esc(NO_TOWN)
    return esc(NOT_FETCHED)


def _costed_cell(row: dict) -> str:
    """Costed table cell. Returns HTML."""
    costed = str(row.get("costed", ""))
    if costed.startswith("yes"):
        study = costed[len("yes: study "):]
        return '<a href="' + esc(study) + '.html">' + esc(costed) + "</a>"
    return esc(NOT_COSTED)


def render_islands_html(doc: dict, land: list | None = None) -> str:
    """Island screen page. Positions in px. Returns ASCII HTML."""
    if not isinstance(doc, dict):
        raise ValueError("doc must be a dict")
    counts = doc.get("counts")
    rows = doc.get("rows")
    if not isinstance(counts, dict) or not isinstance(rows, list):
        raise ValueError("doc must hold counts and rows")
    for key in ("islands", "diesel_quote_found", "fully_screened", "costed"):
        if key not in counts:
            raise ValueError("counts missing key: " + key)
    if land is not None and not isinstance(land, list):
        raise ValueError("land must be a list or None")
    num = int(counts["islands"])
    costed_names = [str(r["name"]) for r in rows
                    if isinstance(r.get("costed"), str) and str(r["costed"]).startswith("yes")]
    parts = ["<!DOCTYPE html>", '<html><head><meta charset="utf-8">',
             "<title>AutoSolar Researcher: island screen</title>",
             "<style>" + SITE_CSS + MAP_CSS + "</style></head><body>"]
    parts.append('<p><a href="index.html">back to gallery</a></p>')
    parts.append("<h1>" + esc("Which diesel islands could use solar or wind? A first screen of "
                              "%d islands" % num) + "</h1>")
    parts.append("<p>" + esc("%d islands are named in a news article as running a diesel plant; "
                             "the tool found the quote in the fetched page for %d. Fully screened: "
                             "%d. Costed: %d (%s), the only island with an hourly load."
                             % (num, int(counts["diesel_quote_found"]),
                                int(counts["fully_screened"]), int(counts["costed"]),
                                ", ".join(costed_names))) + "</p>")
    parts.append('<p class="answer"><b>' + esc(answer_line(rows)) + "</b></p>")
    parts.append("<p>" + esc(str(doc.get("note", NOTE))) + "</p>")
    svg = ['<svg class="map" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 360" role="img">']
    if land:
        for ring in land:
            if not ring:
                raise ValueError("land rings must not be empty")
            first = ring[0]
            x0, y0 = _project(float(first[0]), float(first[1]))
            segs = ["M %.2f %.2f" % (x0, y0)]
            for point in ring[1:]:
                xp, yp = _project(float(point[0]), float(point[1]))
                segs.append("L %.2f %.2f" % (xp, yp))
            segs.append("Z")
            svg.append('<path class="land" d="' + " ".join(segs) + '"></path>')
    for row in rows:
        x, y = map_xy(float(row["lat_deg"]), float(row["lon_deg"]))
        cls = "costed" if str(row.get("costed", "")).startswith("yes") else "island"
        svg.append('<circle class="%s" cx="%.2f" cy="%.2f" r="5"></circle>' % (cls, x, y))
    for group in label_groups(rows):
        svg.append('<text x="%.2f" y="%.2f" font-size="11">%s</text>'
                   % (float(group["x"]), float(group["y"]),
                      esc(", ".join(str(n) for n in group["names"]))))
    svg.append("</svg>")
    parts.append("".join(svg))
    table = ["<table><tr>"]
    for head in _HEADS:
        table.append("<th>" + esc(head) + "</th>")
    table.append("</tr>")
    for row in rows:
        diesel = row.get("diesel", {})
        table.append("<tr>")
        table.append("<td>" + esc(str(row["name"])) + "<br>" + esc(str(row["region"])) + "</td>")
        table.append("<td>" + '<a href="' + esc(str(diesel.get("url", ""))) + '">'
                     + esc(str(diesel.get("outlet", ""))) + " "
                     + esc(str(diesel.get("year", ""))) + "</a>" + ": "
                     + esc(str(diesel.get("status", ""))) + " " + "<q>"
                     + esc(str(diesel.get("quote", ""))) + "</q></td>")
        table.append("<td>" + _sun_cell(row) + "</td>")
        table.append("<td>" + _wind_cell(row) + "</td>")
        table.append("<td>" + _hydro_cell(row) + "</td>")
        table.append("<td>" + _town_cell(row) + "</td>")
        table.append("<td>" + _costed_cell(row) + "</td>")
        table.append("<td>" + esc(verdict_text(row)) + "</td>")
        table.append("</tr>")
    table.append("</table>")
    parts.append("".join(table))
    parts.append("<p>" + esc(_FOOTER) + "</p>")
    parts.append("</body></html>")
    page = "".join(parts)
    page.encode("ascii")
    if "<script" in page.lower():
        raise ValueError("page must hold no script")
    return page
