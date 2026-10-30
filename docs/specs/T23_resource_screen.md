# T23: which renewable fits this site? A first screen of sun, wind, hydro and distance, plus a PV model check

Status: spec by the orchestrator. Builder writes the new module `autosolar/resources.py`, the new tool
`tools/resource_screen.py`, and edits `autosolar/site.py` and `tools/make_site.py` only. All earlier specs (T22
included) stay in force. The orchestrator has written `tests/test_resources.py`.

## Why

Energy planners ask a wider question than "solar plus battery or diesel": which local renewable fits this place
at all? This task adds a small, honest first screen for one site from free public data: sun (Global Solar Atlas),
wind (NASA POWER hourly at 50 m), hydro (rivers mapped in OpenStreetMap) and distance to the nearest town (for a
grid link). Only solar, battery and diesel are costed; the screen says so. It also checks our PV model against two
outside PV models. It was written after the studies ran, so it is labelled post hoc.

## 1. autosolar/resources.py

Imports only the standard library, numpy and requests (requests only inside `default_resource_fetchers`).

Constants:

```
RESOURCE_SCHEMA = "autosolar.resource_screen/1"
WIND_YEARS = (2016, 2024)
WATER_RADIUS_KM = 10.0
PLACE_RADIUS_KM = 150.0
EARTH_RADIUS_KM = 6371.0088
R_DRY_AIR_J_PER_KG_K = 287.05
WIND_CLASSES = ((200.0, 1, "Poor"), (300.0, 2, "Marginal"), (400.0, 3, "Fair"), (500.0, 4, "Good"),
                (600.0, 5, "Excellent"), (800.0, 6, "Outstanding"), (2000.0, 7, "Superb"))
WIND_LOOK_CLASS = 3
SOLAR_LOOK_KWH_PER_KWP_DAY = 3.5
SOLAR_EXCELLENT_KWH_PER_KWP_DAY = 4.5
WATERWAY_KINDS = ("river", "stream", "canal", "drain", "ditch")
LOOK = "worth a closer look"
NOT_ON_SCREEN = "not on this screen"
HYDRO_CHECK = "check flow and head on site"
NOTE = ("Written after the studies ran (post hoc). The PV model gaps for Karimunjawa were seen before this check was "
        "written. Only solar, battery and diesel are costed; this screen does not cost wind, hydro or a grid link.")
SOURCES = {
    "nasa_power_hourly": "https://power.larc.nasa.gov/api/temporal/hourly/point",
    "pvgis_pvcalc": "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc",
    "global_solar_atlas": "https://api.globalsolaratlas.info/data/lta",
    "overpass": "https://overpass-api.de/api/interpreter",
    "world_bank_pv_potential": "https://documents1.worldbank.org/curated/en/466331592817725242/pdf/Global-Photovoltaic-Power-Potential-by-Country.pdf",
    "nrel_wind_classes": "https://support.ul-renewables.com/windographer/def-wind-power-class.htm",
}
```

Every function below raises `ValueError` on bad input. "Finite real" means an `int` or `float` (not `bool`) that is
finite.

### haversine_km(lat1_deg, lon1_deg, lat2_deg, lon2_deg) -> float

Great circle distance on a sphere of radius `EARTH_RADIUS_KM`. Latitudes in [-90, 90], longitudes in [-180, 180],
all finite reals.

### air_density_kg_m3(temp_degc, pressure_kpa) -> np.ndarray

Two 1-D array likes of the same non-zero length, all finite; temperatures above -90 and below 70; pressures above
30 and below 120. Returns `pressure_kpa * 1000 / (R_DRY_AIR_J_PER_KG_K * (temp_degc + 273.15))` as float64.

### wind_from_power(payload) -> dict

Parses a NASA POWER hourly point JSON payload. `payload["properties"]["parameter"]` must hold the dicts `WS50M`
(m/s), `T2M` (degC) and `PS` (kPa), keyed by `"YYYYMMDDHH"` text; the three key sets must be equal. The fill value is
`payload["header"]["fill_value"]` when present, else -999.0. Hours where any of the three equals the fill value are
dropped. A negative wind speed that is not the fill value is a `ValueError`. Fewer than 8760 hours left: `ValueError`.
Keys are taken in sorted order. Returns a dict with exactly:

- `hours`: int, hours kept; `dropped_hours`: int;
- `first`, `last`: the first and last kept key;
- `mean_speed_m_s`: mean of the kept speeds;
- `mean_density_kg_m3`: mean of `air_density_kg_m3` over the kept hours;
- `power_density_w_m2`: mean over the kept hours of `0.5 * density * speed ** 3`;
- `monthly_mean_speed_m_s`: list of 12 floats, the mean kept speed for each calendar month (month from key
  characters 4 and 5), January first; a month with no kept hour is a `ValueError`.

All values are plain Python `int`, `float`, `str` or `list` (JSON-able).

### wind_class(power_density_w_m2) -> tuple

A finite real, 0 or more. Returns `(class_number, name)` from the first `WIND_CLASSES` entry whose upper bound is
above the value, so 199.9 is `(1, "Poor")` and 200.0 is `(2, "Marginal")`. 2000 or more returns `(8, "Above
Superb")`.

### solar_band(pvout_kwh_per_kwp_day) -> str

A finite real above 0. Above `SOLAR_EXCELLENT_KWH_PER_KWP_DAY`: `"excellent"`; else at least
`SOLAR_LOOK_KWH_PER_KWP_DAY`: `"favorable middle range"`; else `"lower end"` (the bands of the World Bank report in
`SOURCES`).

### gsa_lta(payload) -> dict

From a Global Solar Atlas LTA payload: `pvout_kwh_per_kwp_yr` = `payload["annual"]["data"]["PVOUT_csi"]` (finite
real above 0) and `opta_deg` = `payload["annual"]["data"]["OPTA"]` (finite real from 0 to 90). Returns a dict with
exactly those two keys as floats.

### pvgis_yield(payload) -> float

`payload["outputs"]["totals"]["fixed"]["E_y"]`, a finite real above 0, as float.

### water_query(lat_deg, lon_deg, radius_km) -> str and place_query(lat_deg, lon_deg, radius_km) -> str

`radius_km` a finite real above 0 and at most 500; the coordinates as in `haversine_km`. With `m = round(radius_km *
1000)`:

- `water_query`: `'[out:json][timeout:90];way["waterway"](around:%d,%.6f,%.6f);out tags;' % (m, lat, lon)`
- `place_query`: `'[out:json][timeout:90];node["place"~"^(city|town)$"](around:%d,%.6f,%.6f);out;' % (m, lat,
  lon)`

### waterway_counts(payload) -> dict

`payload["elements"]` must be a list (else `ValueError`). Counts elements by their `tags.waterway` value. Returns a
dict with exactly: one int per name in `WATERWAY_KINDS`, `other` (int, any other or missing value), `named_rivers`
(sorted list of the distinct non-empty `tags.name` values of the `river` elements) and `osm_base`
(`payload["osm3s"]["timestamp_osm_base"]` when present, else `""`).

### nearest_place(payload, lat_deg, lon_deg) -> dict | None

Among the elements of `payload["elements"]` (a list, else `ValueError`) that have finite `lat` and `lon` and a
`tags.place` of `"city"` or `"town"`, the one nearest by `haversine_km`; on a tie, the smaller `tags.name`. Returns
`{"name": tags.name or "", "place": tags.place, "km": distance}`, or `None` when no element qualifies.

### pv_yield_checks(report, *, pvgis_e_y_kwh_per_kwp, gsa_pvout_kwh_per_kwp_yr) -> list

Both values finite reals above 0. Returns two dicts, in this order, each with exactly `service`, `case`,
`theirs_kwh_per_kwp_yr`, `ours_kwh_per_kwp_yr` and `gap_pct`:

1. `service` `"PVGIS PVcalc (JRC), ERA5"`, `case` `"PVGIS-ERA5 TMY"`, theirs = the PVGIS value;
2. `service` `"Global Solar Atlas PVOUT (Solargis)"`, `case` `"GSA scaled"`, theirs = the GSA value.

`ours` is `yield_kwh_kwp_yr` of the `report["weather_table"]` row whose `case` matches (no row: `ValueError`).
`gap_pct = (ours - theirs) / theirs * 100`.

### screen_verdicts(*, pvout_kwh_per_kwp_day, wind_class_number, rivers) -> dict

Returns exactly `{"solar": ..., "wind": ..., "hydro": ...}`: solar `LOOK` when `pvout_kwh_per_kwp_day >=
SOLAR_LOOK_KWH_PER_KWP_DAY`, else `NOT_ON_SCREEN`; wind `LOOK` when `wind_class_number >= WIND_LOOK_CLASS`, else
`NOT_ON_SCREEN`; hydro `HYDRO_CHECK` when `rivers >= 1`, else `NOT_ON_SCREEN`. `pvout_kwh_per_kwp_day` a finite
real; `wind_class_number` an int from 1 to 8 and `rivers` an int 0 or more (neither `bool`).

### screen_doc(report, *, run_id, wind, gsa, pvgis_e_y_kwh_per_kwp, water, place, files, wall_s) -> dict

Returns a JSON-able dict with exactly:

- `schema` (`RESOURCE_SCHEMA`), `run_id`, `study_run_hash` (`report["run_hash"]`);
- `site`: `{"name", "lat_deg", "lon_deg"}` from `report["site"]`; `weather_coords_deg`: a list copy of the report's;
- `solar`: `{"pvout_kwh_per_kwp_yr", "pvout_kwh_per_kwp_day" (yr / 365), "opta_deg", "band"}` (band from
  `solar_band` of the daily value);
- `wind`: a copy of `wind` plus `"years": list(WIND_YEARS)`, `"class_number"` and `"class_name"` from `wind_class`
  of its `power_density_w_m2`;
- `hydro`: a copy of `water` plus `"radius_km": WATER_RADIUS_KM`;
- `grid`: `{"nearest": place (a dict copy or None), "radius_km": PLACE_RADIUS_KM}`;
- `pv_checks`: `pv_yield_checks(report, ...)` with the PVGIS value and the GSA PVOUT;
- `verdicts`: `screen_verdicts(...)` with the daily PV output, the wind class number and `water["river"]`;
- `files`: a copy of `files` (file name to sha256 hex text); `wall_s` (float); `sources`: a copy of `SOURCES`;
  `note`: `NOTE`.

### ResourceFetchers, default_resource_fetchers(), no_network_resource_fetchers(), cached_resource_fetchers(base, cache_dir)

```
@dataclass(frozen=True)
class ResourceFetchers:
    nasa_wind_hourly: Callable[[float, float, int, int], dict]   # lat, lon, first year, last year
    pvgis_pvcalc: Callable[[float, float, float, float], dict]   # lat, lon, tilt_deg, loss_pct
    overpass: Callable[[str], dict]                              # query text
```

- `default_resource_fetchers()`: live fetchers built with `requests` (creation makes no call). NASA POWER: GET
  `SOURCES["nasa_power_hourly"]` with `parameters=WS50M,T2M,PS`, `community=RE`, `longitude`, `latitude`,
  `start=<y0>0101`, `end=<y1>1231`, `format=JSON`, `time-standard=UTC`, timeout 300. PVGIS: GET
  `SOURCES["pvgis_pvcalc"]` with `lat`, `lon`, `peakpower=1`, `loss`, `angle` (tilt), `aspect` 180 when lat is below
  0 else 0 (facing the equator, as `autosolar.pv` does), `usehorizon=1`, `raddatabase=PVGIS-ERA5`,
  `outputformat=json`, timeout 120. Overpass: POST `data=query` to `SOURCES["overpass"]`, timeout 180; on any
  error, one retry at `https://overpass.kumi.systems/api/interpreter`. Each raises on a non 2xx status and returns
  `resp.json()`.
- `no_network_resource_fetchers()`: every callable raises `RuntimeError("no network: cached data only")`.
- `cached_resource_fetchers(base, cache_dir)`: `base` must be a `ResourceFetchers` (else `ValueError`). Returns new
  fetchers that read a JSON file in `cache_dir` when it exists, else call `base`, write the payload (ASCII,
  `json.dumps(payload, ensure_ascii=True)`, creating the folder) and return it. File names: NASA
  `nasa_wind_{lat:.4f}_{lon:.4f}_{y0}_{y1}.json`; PVGIS `pvgis_pvcalc_{lat:.4f}_{lon:.4f}_t{tilt:g}_l{loss:g}.json`;
  Overpass `overpass_{h}.json` where `h` is the first 16 hex characters of the sha256 of the query text (UTF-8).

## 2. tools/resource_screen.py

`python tools/resource_screen.py --run <study hash> [--cache-only]`

- Optional: `--runs` (default `runs/studies`), `--out` (default `runs/resource_screens`), `--cache` (default
  `runs/resource_cache`), `--weather-cache` (default `runs/weather_cache`). Relative paths are against the repo
  root. Imports `no_network_fetchers` from `tools/load_followup.py` (same folder).
- `main(argv=None, fetchers=None) -> int`:
  1. Reads `<runs>/<run>/report.json`. Missing: prints `not found: <path>`, returns 2, writes nothing.
  2. `base` = `fetchers` when given, else `no_network_resource_fetchers()` with `--cache-only`, else
     `default_resource_fetchers()`; `f = cached_resource_fetchers(base, <cache>)`.
  3. `lat_w, lon_w` = `report["weather_coords_deg"]`; `lat, lon` = `report["site"]["lat_deg"]`, `["lon_deg"]`.
     `wind = wind_from_power(f.nasa_wind_hourly(lat_w, lon_w, *WIND_YEARS))`;
     `gsa = gsa_lta(cached_fetchers(no_network_fetchers(), <weather cache>).gsa(lat_w, lon_w))` (the study's own
     cached file, never fetched again); `pvgis = pvgis_yield(f.pvgis_pvcalc(lat_w, lon_w, PVDesign().tilt_deg,
     PVDesign().system_loss_pct))`; `water = waterway_counts(f.overpass(water_query(lat, lon, WATER_RADIUS_KM)))`;
     `place = nearest_place(f.overpass(place_query(lat, lon, PLACE_RADIUS_KM)), lat, lon)`.
  4. `run_id = "resources-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid4 hex[:6]`. `files` maps the base name of
     each cache file read in step 3 (the four resource files and the GSA file) to its sha256. Writes
     `<out>/<run_id>/resource_screen.json` (ASCII, indent 2) from `screen_doc`.
  5. Prints the run id, the solar band, the wind class, the river count, the nearest place and the two PV gaps.
     Returns 0.
- Makes no model call.

## 3. autosolar/site.py

### resources_section(report, screen) -> str

- `screen` None: returns `""`.
- Else `screen` must be a dict with `schema` equal to `RESOURCE_SCHEMA` and `study_run_hash` equal to
  `report["run_hash"]`, else `ValueError`.
- Returns `'<section id="resources"><h2>Which renewable fits this site?</h2>' + ... + "</section>"`, all text through
  `esc`:
  1. `<p>A first screen of other local resources, from free public data. The costs on this page cover solar,
     battery and diesel only; wind, hydro and a grid link are not costed here.</p>`
  2. `_table` with headers `["Resource", "Public data", "Screen reading", "Next check"]` and four rows, with
     `S = screen["solar"]`, `W = screen["wind"]`, `H = screen["hydro"]`, `G = screen["grid"]`, `V =
     screen["verdicts"]`:
     - `["Sun", "PV output " + fmt(S day, 2) + " kWh/kWp a day, " + fmt(S yr, 0) + " a year (Global Solar Atlas,
       measured)", "World Bank band: " + S band + " (docs); " + V solar, "Costed on this page"]`
     - `["Wind", "Mean " + fmt(W mean_speed_m_s, 2) + " m/s and " + fmt(W power_density_w_m2, 0) + " W/m2 at 50 m,
       hourly " + str(years[0]) + " to " + str(years[1]) + " (NASA POWER, coarse MERRA-2 grid; computed)", "Class
       " + str(class_number) + ", " + class_name + ", on the NREL scale (docs); " + V wind, "Global Wind Atlas or a
       mast on site; a coarse grid can miss local wind"]`
     - `["Hydro", fmt(H river, 0) + " river and " + fmt(H stream, 0) + " stream lines mapped within " +
       fmt(H radius_km, 0) + " km (OpenStreetMap, measured)", V hydro, "Flow and head from a field survey"]`
     - `["Grid link", T, "Not screened", "Cost of a grid link or sea cable"]` with `T = "Nearest town or city on the
       map: " + name + " (" + place + "), " + fmt(km, 0) + " km in a straight line (computed)"` when
       `G["nearest"]` is a dict, else `"No town or city on the map within " + fmt(G radius_km, 0) + " km"`.
  3. `<p>Screen rule (assumed): solar is worth a closer look at 3.5 kWh/kWp a day or more, the lower bound of the
     World Bank&#x27;s favorable range; wind at class 3 or more; hydro needs at least one mapped river within 10
     km, and then flow and head decide.</p>` (the apostrophe comes from `esc`).
  4. `<h3>Is our PV model close to outside models?</h3>` and `_table` with headers `["Outside model", "Their PV
     output (kWh/kWp a year)", "Our model on their weather (kWh/kWp a year)", "Gap"]`, one row per
     `screen["pv_checks"]` item: `service`, `fmt(theirs, 0)`, `fmt(ours, 0)`, and the gap as `"+"` or `"-"` (minus
     for a value below 0) + `fmt(abs(gap), 1) + "%"`.
  5. `<p>Same site and panel tilt; the loss chains differ, so a gap of a few percent is expected. Computed after the
     studies ran (post hoc).</p>`

`render_study_html` gains the keyword argument `resource_screen: dict | None = None` and inserts
`resources_section(report, resource_screen)` right after the T22 confirm section and before "How firm is the
answer". Pages without a screen do not change. ASCII only, no `<script>`.

## 4. tools/make_site.py

A gallery entry may hold `"resource_screen": "<run id>"`. When present, copy
`runs/resource_screens/<id>/resource_screen.json` to `docs/site/data/<run>/resource_screen.json` and pass it as
`resource_screen=`. Entries without the key are built as before.

## Acceptance

`tests/test_resources.py` passes, and the full suite still passes. Muse must not edit specs, tests or config.
