# T24: island screen. Sun, wind, rivers and the nearest town for named diesel islands, costed only where a load exists

Status: spec and acceptance tests written first, by hand. Muse Code writes the new module `autosolar/islands.py`
and the new tool `tools/island_screen.py`, and edits `tools/make_site.py` only. All earlier specs stay in force.
The acceptance tests are `tests/test_islands.py`, `tests/test_island_screen_tool.py` and the two tests marked T24
in `tests/test_make_site.py`.

## Why

PLN plans to replace diesel at 741 sites; the tool costs one island because it has only one hourly load. A
regional energy planner asked for the part a person cannot do quickly: a first screen of several places at once.
This task screens a short, fixed list of islands that run on diesel (each named in a news article whose quote the
tool re-checks in the fetched page) for sun, wind, rivers and the nearest mapped town, and says plainly that only
Karimunjawa is costed. It was written after the studies ran, so it is labelled post hoc. It must never cost an
island without an hourly load, and it must never call the nearest town a grid link.

## 1. autosolar/islands.py

Imports only the standard library, `autosolar.resources` (for `solar_band`, `wind_class`, `screen_verdicts`,
`PLACE_RADIUS_KM`, `WATER_RADIUS_KM`, `WIND_YEARS`, `SOURCES`), `autosolar.cite_check.find_quote`, and `SITE_CSS`
and `esc` from `autosolar.site`. No network at import time and no network anywhere in this module.

Constants (exact values):

```
ISLAND_LIST_SCHEMA = "autosolar.island_list/1"
ISLAND_SCREEN_SCHEMA = "autosolar.island_screen/1"
LAND_SCHEMA = "autosolar.land_rings/1"
MAP_BBOX_DEG = (94.0, 142.0, -11.5, 6.5)      # lon_min, lon_max, lat_min, lat_max
MAP_WIDTH_PX = 960
MAP_HEIGHT_PX = 360
QUOTE_MIN_CHARS = 20
NOT_COSTED = "no: no hourly load, so no cost; the tool refuses rather than guess"
NOT_FETCHED = "not fetched"
NO_TOWN = "none within 150 km"
QUOTE_FOUND = "quote found in the fetched page"
QUOTE_MISSING = "quote not in the fetched page"
NOTE = ("Written after the studies ran (post hoc). A convenience list, not a sample of PLN's 741 sites: each island "
        "is named in a news article as running a diesel plant (PLTD), and the tool checks the quote in the page it "
        "fetches. Only Karimunjawa has an hourly load, so only Karimunjawa is costed. Sun, wind and rivers are a "
        "first screen from free public data, not a resource assessment; nothing here costs wind, hydro or a grid "
        "link, and the nearest town is not a grid connection.")
SOURCES = {
    "nasa_power_hourly": resources.SOURCES["nasa_power_hourly"],
    "global_solar_atlas": resources.SOURCES["global_solar_atlas"],
    "overpass": resources.SOURCES["overpass"],
    "nominatim": "https://nominatim.openstreetmap.org/search",
    "natural_earth": "https://www.naturalearthdata.com/",
}
```

Every function raises `ValueError` on bad input. "Finite real" means an `int` or `float`, not `bool`, that is
finite.

### parse_island_list(doc) -> list

`doc` is a dict with `schema == ISLAND_LIST_SCHEMA` and `islands`, a non-empty list. Each island is a dict with
exactly these keys used (other keys are ignored): `name` (non-empty str, unique in the list), `region` (str),
`lat_deg` (finite real in [-90, 90]), `lon_deg` (finite real in [-180, 180]), `point` (str), `diesel` (dict) and
`study` (None, or a str of exactly 16 lowercase hex characters). `diesel` holds `url` (str starting with `http://`
or `https://`), `quote` (str with at least `QUOTE_MIN_CHARS` characters after strip), `outlet` (non-empty str),
`year` (int, not bool, from 1990 to 2100) and `label` (must equal `"press"`). Returns a new list of new dicts with
the keys `name`, `region`, `lat_deg`, `lon_deg`, `point`, `diesel` (a new dict with the five keys above) and
`study`, in input order, with `lat_deg` and `lon_deg` as `float`. A missing key or a wrong value raises.

### diesel_check(diesel, pages, error=None) -> dict

`diesel` is a dict with a str `quote`. When `pages` is None, `error` must be a non-empty str and the result is
`{"found": False, "status": "not fetched: " + error}`. Otherwise `pages` must be a list of str and the result is
`{"found": m.found, "status": QUOTE_FOUND if m.found else QUOTE_MISSING}` with `m = find_quote(quote, pages)`
(`found` as a Python bool).

### island_row(island, *, wind, gsa, water, place, place_fetched, diesel_result) -> dict

`island` is one dict from `parse_island_list`. `wind` is None or a dict holding finite reals `mean_speed_m_s` and
`power_density_w_m2` (as from `resources.wind_from_power`). `gsa` is None or a dict holding a finite real
`pvout_kwh_per_kwp_yr` above 0 (as from `resources.gsa_lta`). `water` is None or a dict holding ints `river` and
`stream`, 0 or more (as from `resources.waterway_counts`). `place` is None or a dict with `name` (str), `place`
(str) and `km` (finite real, 0 or more). `place_fetched` is a bool; when it is False, `place` must be None.
`diesel_result` is a dict with a bool `found` and a str `status`. Returns:

```
{
  "name", "region", "lat_deg", "lon_deg", "point": copied from island,
  "diesel": a new dict: the island's five diesel keys plus "found" and "status" from diesel_result,
  "solar": None if gsa is None, else {"pvout_kwh_per_kwp_yr": yr, "pvout_kwh_per_kwp_day": yr / 365.0,
           "band": solar_band(yr / 365.0)},
  "wind": None if wind is None, else {"mean_speed_m_s", "power_density_w_m2", "class_number", "class_name"}
          with the class from wind_class(power_density_w_m2),
  "hydro": None if water is None, else {"river": int, "stream": int},
  "nearest_town": None, or {"name", "place", "km"} when place is a dict,
  "nearest_town_status": "fetched" when place is a dict, NO_TOWN when place_fetched and place is None,
                         NOT_FETCHED when not place_fetched,
  "verdicts": screen_verdicts(pvout_kwh_per_kwp_day=..., wind_class_number=..., rivers=water["river"]) when solar,
              wind and hydro are all present, else None,
  "costed": "yes: study " + island["study"] when study is a str, else NOT_COSTED,
  "missing": sorted list of the part names "hydro", "nearest_town", "solar", "wind" that were not fetched
             (nearest_town counts as missing only when not place_fetched),
}
```

### island_screen_doc(rows, *, run_id, list_sha256, files, wall_s) -> dict

`rows` is a non-empty list of dicts from `island_row` (a caller may add an `errors` key to each). `run_id` is a str
starting with `islands-`. `list_sha256` is 64 lowercase hex characters. `files` maps str to str. `wall_s` is a
finite real, 0 or more. Returns `{"schema": ISLAND_SCREEN_SCHEMA, "run_id", "list_sha256", "note": NOTE,
"counts": {...}, "rows": [copies of rows], "files": copy of files, "wall_s": float, "sources": copy of SOURCES}`
where counts are `islands` (number of rows), `diesel_quote_found` (rows with `diesel.found` True),
`fully_screened` (rows whose `missing` is empty) and `costed` (rows whose `costed` starts with `"yes"`).

### map_xy(lat_deg, lon_deg) -> tuple

Equirectangular position in pixels: `x = (lon - lon_min) / (lon_max - lon_min) * MAP_WIDTH_PX`,
`y = (lat_max - lat) / (lat_max - lat_min) * MAP_HEIGHT_PX`, each rounded to 2 decimals, returned as
`(x, y)` floats. A point outside `MAP_BBOX_DEG` (edges included are inside) raises.

### parse_land(doc) -> list

`doc` is a dict with `schema == LAND_SCHEMA` and `rings`, a list (may be empty) of rings; each ring is a list of at
least 4 points; each point is a list or tuple of two finite reals `[lon, lat]`. Returns a list of rings, each a
list of `(lon, lat)` float tuples.

### render_islands_html(doc, land=None) -> str

`doc` is a dict from `island_screen_doc`; `land` is None or a list from `parse_land`. Returns one ASCII HTML page,
starting with `<!DOCTYPE html>`, with no `<script` anywhere (any case). It uses `SITE_CSS` inline and `esc` for
every piece of text that comes from the doc. It holds, in this order:

1. `<title>AutoSolar Researcher: island screen</title>`, a link `href="index.html"` back to the gallery, and an
   `<h1>` with the text `Which diesel islands could use solar or wind? A first screen of N islands`
   (N = `counts.islands`).
2. One paragraph with the counts: `N islands are named in a news article as running a diesel plant; the tool found
   the quote in the fetched page for K. Fully screened: M. Costed: C (` + the names of the costed rows joined by
   `, ` + `), the only island with an hourly load.` with N, K, M, C from `counts`.
3. A paragraph with `NOTE`.
4. An inline `<svg>` with `viewBox="0 0 960 360"`. When `land` is given, one `<path class="land" d="...">` per
   ring: `M x y` for the first point and `L x y` for the rest, then `Z`, with points placed by the same formula as
   `map_xy` but without the inside check (land may run past the box). Then one `<circle>` per row at `map_xy`
   of the row (class `costed` when the row is costed, else class `island`), and one `<text>` per row holding the
   escaped name.
5. A `<table>` with one header row with exactly these `<th>` cells in order: `Island`, `Diesel plant named in`,
   `Sun (kWh/kWp a day)`, `Wind at 50 m`, `Rivers and streams within 10 km`, `Nearest mapped town`,
   `Costed here?`; then one `<tr>` per row in doc order. Cells:
   - Island: name, a `<br>`, region.
   - Diesel: an `<a href="url">` with `outlet year` as its text, then `: ` and the row's `diesel.status`, then
     the quote inside `<q>...</q>`.
   - Sun: `"%.2f, %s" % (pvout_kwh_per_kwp_day, band)`, or `NOT_FETCHED`.
   - Wind: `"%.2f m/s, %.0f W/m2, class %d (%s)" % (mean, power, class_number, class_name)`, or `NOT_FETCHED`.
   - Rivers: `"%d rivers, %d streams" % (river, stream)`, or `NOT_FETCHED`.
   - Town: `"%s (%s), %.0f km" % (name, place, km)` when fetched, `NO_TOWN`, or `NOT_FETCHED`.
   - Costed: when the row is costed, `<a href="<study>.html">` with text `yes: study <study>`; else `NOT_COSTED`.
6. A footer paragraph: `Sun: Global Solar Atlas (a Solargis model), long-term PV output at the optimum tilt. Wind:
   NASA POWER hourly at 50 m, 2016 to 2024 (computed). Rivers and towns: OpenStreetMap, counts of mapped features
   (measured). Coordinates: OpenStreetMap Nominatim. Land outline: Natural Earth (public domain). Diesel: press,
   quote re-checked by the tool.`

## 2. tools/island_screen.py

```
python tools/island_screen.py [--list config/island_screen.json] [--out runs/island_screens]
    [--cache runs/island_cache] [--site docs/site] [--land config/land_rings_indonesia.json] [--cache-only]
```

`main(argv=None, fetchers=None, gsa_fetch=None, source_get=None) -> int`. Relative paths resolve against the repo
root. Makes no model call.

- Reads and parses the list with `parse_island_list`; a missing file or a `ValueError` prints `bad list: <reason>`
  and returns 2.
- `fetchers` is a `resources.ResourceFetchers` (default: `default_resource_fetchers()`, or
  `no_network_resource_fetchers()` with `--cache-only`), wrapped with `resources.cached_resource_fetchers(base,
  <cache>)`. `gsa_fetch(lat_deg, lon_deg) -> dict` (default: `autosolar.weather.default_fetchers().gsa`, or a
  function that raises `RuntimeError("no network: cached data only")` with `--cache-only`) is wrapped with a JSON
  cache file `<cache>/gsa_%.4f_%.4f.json`. `source_get` is the http function passed to
  `cite_check.fetch_source` (default: `requests.get`, or a function that raises
  `requests.ConnectionError("no network: cached data only")` with `--cache-only`); a fetched source is cached as
  `<cache>/source_<first 16 hex of sha256 of the url>.json` holding `{"url", "final_url", "status_code",
  "pages"}`, and a cached file is used without fetching.
- For each island, each part is fetched on its own, and one failing part never stops the others or the run:
  wind = `wind_from_power(cached.nasa_wind_hourly(lat, lon, WIND_YEARS[0], WIND_YEARS[1]))`; gsa =
  `gsa_lta(cached gsa)`; water = `waterway_counts(cached.overpass(water_query(lat, lon, WATER_RADIUS_KM)))`;
  place = `nearest_place(cached.overpass(place_query(lat, lon, PLACE_RADIUS_KM)), lat, lon)`; diesel =
  `diesel_check(diesel, source pages)`. When a part raises any `Exception`, that part is None (for the source:
  `diesel_check(diesel, None, error=<message>)`), and the row gets `errors[<part>] = <message>` where the parts are
  `wind`, `solar`, `hydro`, `nearest_town` and `diesel`, and `<message>` is `type(exc).__name__ + ": " + str(exc)`
  cut to 200 characters. Every row gets an `errors` dict (empty when nothing failed).
- `files` maps the name of every cache file the run read or wrote to its sha256 hex.
- `run_id = "islands-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid4 hex[:6]`; `list_sha256` is the sha256 of
  the list file's bytes.
- Writes `<out>/<run_id>/island_screen.json` (indent 2, ASCII, trailing newline), `<site>/islands.html` from
  `render_islands_html(doc, land)` where `land = parse_land(<land file>)` when that file exists, else None, and a
  copy of the JSON at `<site>/data/islands/island_screen.json`.
- Prints the run id, one line per island `<name>: quote found` or `<name>: quote NOT found (<status>)`, followed by
  `; missing: <parts>` when any part is missing, and a last line
  `islands N, quote found K, fully screened M, costed C`. Returns 0.

## 3. tools/make_site.py

A `config/gallery.json` entry under `studies` that has a `page` key is a page card, not a study: it holds `page`
(file name in `docs/site/`), `title`, `question`, `text` and `run`. For such an entry `make_site` reads no run
folder and copies nothing; it appends `{"href": page, "site": title, "question": question, "headline": text,
"run_hash": run}` to the cards at that entry's place in the list, and prints `card <page>`. Study entries work as
before.

## 4. Rules for this task

- No network in unit tests; the tests pass fake fetchers.
- No new dependency. No change to any study page, to `autosolar/site.py` or to any other module.
- The page has no `<script>`. Every number on it carries its source in the footer.
- Do not edit the tests, this spec, `config/island_screen.json` or `config/land_rings_indonesia.json`.
