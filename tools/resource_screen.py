"""Screen sun, wind, hydro and grid distance for one study (T23).

  python tools/resource_screen.py --run <study hash> [--cache-only]

Reads runs/studies/<run>/report.json, fetches NASA POWER hourly wind, PVGIS
PVcalc yield, GSA optimum tilt output (from the study weather cache) and
OpenStreetMap waterways and towns, and writes
runs/resource_screens/<run_id>/resource_screen.json. Makes no model call.
"""

import argparse
import hashlib
import json
import pathlib
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from autosolar.pv import PVDesign  # noqa: E402
from autosolar.resources import (PLACE_RADIUS_KM, WATER_RADIUS_KM, WIND_YEARS,  # noqa: E402
                                 cached_resource_fetchers, default_resource_fetchers, gsa_lta,
                                 nearest_place, no_network_resource_fetchers, place_query,
                                 pvgis_yield, screen_doc, water_query, waterway_counts,
                                 wind_from_power)
from autosolar.weather import cached_fetchers as cached_weather_fetchers  # noqa: E402
from load_followup import no_network_fetchers  # noqa: E402  (tools/load_followup.py)


def _resolve(raw: str) -> pathlib.Path:
    """Path against the repo root when relative. Returns a path."""
    path = pathlib.Path(str(raw))
    if not path.is_absolute():
        return ROOT / path
    return path


def main(argv: list[str] | None = None, fetchers: object = None) -> int:
    """Run the resource screen and write its record. Returns 0 or 2."""
    t0 = time.time()
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--runs", default="runs/studies")
    ap.add_argument("--out", default="runs/resource_screens")
    ap.add_argument("--cache", default="runs/resource_cache")
    ap.add_argument("--weather-cache", default="runs/weather_cache")
    ap.add_argument("--cache-only", action="store_true")
    args = ap.parse_args(argv)
    report_path = _resolve(str(args.runs)) / str(args.run) / "report.json"
    if not report_path.is_file():
        print("not found: " + str(report_path))
        return 2
    report = json.loads(report_path.read_text(encoding="ascii"))
    if fetchers is not None:
        base = fetchers
    elif bool(args.cache_only):
        base = no_network_resource_fetchers()
    else:
        base = default_resource_fetchers()
    cached = cached_resource_fetchers(base, _resolve(str(args.cache)))  # type: ignore[arg-type]
    lat_w, lon_w = report["weather_coords_deg"]
    lat = float(report["site"]["lat_deg"])
    lon = float(report["site"]["lon_deg"])
    lat_w_f = float(lat_w)
    lon_w_f = float(lon_w)
    design = PVDesign()
    wind = wind_from_power(cached.nasa_wind_hourly(lat_w_f, lon_w_f, WIND_YEARS[0], WIND_YEARS[1]))
    gsa_cache = cached_weather_fetchers(no_network_fetchers(), _resolve(str(args.weather_cache)))
    gsa = gsa_lta(gsa_cache.gsa(lat_w_f, lon_w_f))
    pvgis = pvgis_yield(cached.pvgis_pvcalc(lat_w_f, lon_w_f, design.tilt_deg, design.system_loss_pct))
    water_text = water_query(lat, lon, WATER_RADIUS_KM)
    place_text = place_query(lat, lon, PLACE_RADIUS_KM)
    water = waterway_counts(cached.overpass(water_text))
    place = nearest_place(cached.overpass(place_text), lat, lon)
    run_id = "resources-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    cache_dir = _resolve(str(args.cache))
    weather_cache_dir = _resolve(str(args.weather_cache))
    nasa_name = "nasa_wind_%.4f_%.4f_%d_%d.json" % (lat_w_f, lon_w_f, WIND_YEARS[0], WIND_YEARS[1])
    pvgis_name = "pvgis_pvcalc_%.4f_%.4f_t%g_l%g.json" % (lat_w_f, lon_w_f, design.tilt_deg,
                                                         design.system_loss_pct)
    water_name = "overpass_%s.json" % hashlib.sha256(water_text.encode("utf-8")).hexdigest()[:16]
    place_name = "overpass_%s.json" % hashlib.sha256(place_text.encode("utf-8")).hexdigest()[:16]
    gsa_name = "gsa_%.4f_%.4f.json" % (lat_w_f, lon_w_f)
    files = {}
    for name, path in ((nasa_name, cache_dir / nasa_name), (pvgis_name, cache_dir / pvgis_name),
                       (water_name, cache_dir / water_name), (place_name, cache_dir / place_name),
                       (gsa_name, weather_cache_dir / gsa_name)):
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    doc = screen_doc(report, run_id=run_id, wind=wind, gsa=gsa, pvgis_e_y_kwh_per_kwp=pvgis,
                     water=water, place=place, files=files, wall_s=float(time.time() - t0))
    out_dir = _resolve(str(args.out)) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "resource_screen.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    print(run_id)
    print("solar band: " + str(doc["solar"]["band"]))
    print("wind class: %d %s" % (doc["wind"]["class_number"], doc["wind"]["class_name"]))
    print("rivers: %d" % water["river"])
    if place is None:
        print("nearest: none")
    else:
        print("nearest: %s (%s) %.1f km" % (place["name"], place["place"], place["km"]))
    for row in doc["pv_checks"]:
        print("%s gap: %+.1f%%" % (row["service"], row["gap_pct"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
