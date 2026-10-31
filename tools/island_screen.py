"""Screen named diesel islands for sun, wind, rivers and towns (T24).

  python tools/island_screen.py [--list config/island_screen.json] [--out runs/island_screens]
      [--cache runs/island_cache] [--site docs/site] [--land config/land_rings_indonesia.json]
      [--cache-only]

Reads the island list, fetches each part on its own, and writes
runs/island_screens/<run_id>/island_screen.json plus docs/site/islands.html.
Makes no model call.
"""

import argparse
import hashlib
import json
import pathlib
import sys
import time
import uuid

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autosolar.cite_check import fetch_source  # noqa: E402
from autosolar.islands import (  # noqa: E402
    diesel_check,
    island_row,
    island_screen_doc,
    parse_island_list,
    parse_land,
    render_islands_html,
)
from autosolar.resources import (  # noqa: E402
    PLACE_RADIUS_KM,
    WATER_RADIUS_KM,
    WIND_YEARS,
    cached_resource_fetchers,
    default_resource_fetchers,
    gsa_lta,
    nearest_place,
    no_network_resource_fetchers,
    place_query,
    water_query,
    waterway_counts,
    wind_from_power,
)
from autosolar.weather import default_fetchers as default_weather_fetchers  # noqa: E402


def _resolve(raw: str) -> pathlib.Path:
    """Path against the repo root when relative. Returns a path."""
    path = pathlib.Path(str(raw))
    if not path.is_absolute():
        return ROOT / path
    return path


def _message(exc: Exception) -> str:
    """Exception text cut to 200 chars. Returns str."""
    return (type(exc).__name__ + ": " + str(exc))[:200]


def main(argv: list[str] | None = None, fetchers: object = None,
         gsa_fetch: object = None, source_get: object = None) -> int:
    """Run the island screen and write its record. Returns 0 or 2."""
    t0 = time.time()
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="config/island_screen.json")
    ap.add_argument("--out", default="runs/island_screens")
    ap.add_argument("--cache", default="runs/island_cache")
    ap.add_argument("--site", default="docs/site")
    ap.add_argument("--land", default="config/land_rings_indonesia.json")
    ap.add_argument("--cache-only", action="store_true")
    args = ap.parse_args(argv)
    cache_only = bool(args.cache_only)
    cache_path = _resolve(str(args.cache))
    list_path = _resolve(str(args.list))
    try:
        raw = list_path.read_bytes()
    except OSError as exc:
        print("bad list: " + str(exc))
        return 2
    try:
        islands = parse_island_list(json.loads(raw.decode("ascii")))
    except ValueError as exc:
        print("bad list: " + str(exc))
        return 2
    if fetchers is not None:
        base = fetchers
    elif cache_only:
        base = no_network_resource_fetchers()
    else:
        base = default_resource_fetchers()
    cached = cached_resource_fetchers(base, cache_path)  # type: ignore[arg-type]
    if gsa_fetch is not None:
        gsa_base = gsa_fetch
    elif cache_only:
        def _no_gsa(lat_deg: float, lon_deg: float) -> dict:
            raise RuntimeError("no network: cached data only")

        gsa_base = _no_gsa
    else:
        gsa_base = default_weather_fetchers().gsa
    if source_get is not None:
        http_get = source_get
    elif cache_only:
        def _no_source(*pos: object, **key: object) -> object:
            raise requests.ConnectionError("no network: cached data only")

        http_get = _no_source
    else:
        http_get = requests.get

    def _cached_gsa(lat_deg: float, lon_deg: float) -> dict:
        """GSA payload from the JSON file cache. Coordinates in deg."""
        name = "gsa_%.4f_%.4f.json" % (float(lat_deg), float(lon_deg))
        path = cache_path / name
        if path.is_file():
            return json.loads(path.read_text(encoding="ascii"))
        out = gsa_base(float(lat_deg), float(lon_deg))
        path.write_text(json.dumps(out, ensure_ascii=True), encoding="ascii")
        return out

    def _source_pages(url: str) -> list:
        """Source pages for a URL, cached as JSON. Returns page texts."""
        name = "source_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + ".json"
        path = cache_path / name
        if path.is_file():
            payload = json.loads(path.read_text(encoding="ascii"))
            return list(payload["pages"])
        src = fetch_source(url, http_get)  # type: ignore[arg-type]
        payload = {"url": src.url, "final_url": src.final_url,
                   "status_code": src.status_code, "pages": list(src.pages)}
        path.write_text(json.dumps(payload, ensure_ascii=True), encoding="ascii")
        return list(src.pages)

    rows: list[dict] = []
    for island in islands:
        lat = float(island["lat_deg"])
        lon = float(island["lon_deg"])
        errors: dict[str, str] = {}
        try:
            wind = wind_from_power(cached.nasa_wind_hourly(lat, lon, WIND_YEARS[0],
                                                           WIND_YEARS[1]))
        except Exception as exc:
            wind = None
            errors["wind"] = _message(exc)
        try:
            gsa = gsa_lta(_cached_gsa(lat, lon))
        except Exception as exc:
            gsa = None
            errors["solar"] = _message(exc)
        try:
            water = waterway_counts(cached.overpass(water_query(lat, lon, WATER_RADIUS_KM)))
        except Exception as exc:
            water = None
            errors["hydro"] = _message(exc)
        try:
            place = nearest_place(cached.overpass(place_query(lat, lon, PLACE_RADIUS_KM)),
                                  lat, lon)
            place_fetched = True
        except Exception as exc:
            place = None
            place_fetched = False
            errors["nearest_town"] = _message(exc)
        try:
            diesel_result = diesel_check(island["diesel"], _source_pages(island["diesel"]["url"]))
        except Exception as exc:
            message = _message(exc)
            errors["diesel"] = message
            diesel_result = diesel_check(island["diesel"], None, error=message)
        row = island_row(island, wind=wind, gsa=gsa, water=water, place=place,
                         place_fetched=place_fetched, diesel_result=diesel_result)
        row["errors"] = errors
        rows.append(row)
    cache_path.mkdir(parents=True, exist_ok=True)
    files = {}
    for path in sorted(cache_path.iterdir()):
        if path.is_file():
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    run_id = "islands-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    doc = island_screen_doc(rows, run_id=run_id,
                            list_sha256=hashlib.sha256(raw).hexdigest(), files=files,
                            wall_s=float(time.time() - t0))
    out_dir = _resolve(str(args.out)) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "island_screen.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    land_path = _resolve(str(args.land))
    if land_path.is_file():
        land = parse_land(json.loads(land_path.read_text(encoding="ascii")))
    else:
        land = None
    site_path = _resolve(str(args.site))
    site_path.mkdir(parents=True, exist_ok=True)
    (site_path / "islands.html").write_text(render_islands_html(doc, land),
                                            encoding="ascii")
    data_path = site_path / "data" / "islands"
    data_path.mkdir(parents=True, exist_ok=True)
    (data_path / "island_screen.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    print(run_id)
    for row in rows:
        if row["diesel"]["found"]:
            line = str(row["name"]) + ": quote found"
        else:
            line = (str(row["name"]) + ": quote NOT found ("
                    + str(row["diesel"]["status"]) + ")")
        if row["missing"]:
            line += "; missing: " + ", ".join(row["missing"])
        print(line)
    counts = doc["counts"]
    print("islands %d, quote found %d, fully screened %d, costed %d"
          % (counts["islands"], counts["diesel_quote_found"], counts["fully_screened"],
             counts["costed"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
