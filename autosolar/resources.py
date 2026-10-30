"""First screen of local renewables for one site: sun, wind, hydro and grid distance.

Sun output in kWh per kWp, wind power density in W per m2, air density in kg
per m3, distances in km, temperature in degC, pressure in kPa, tilt in deg and
losses in pct. Only the standard library and numpy at import time; requests is
imported inside default_resource_fetchers only.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

RESOURCE_SCHEMA = "autosolar.resource_screen/1"
WIND_YEARS = (2016, 2024)
WATER_RADIUS_KM = 10.0
PLACE_RADIUS_KM = 150.0
EARTH_RADIUS_KM = 6371.0088
R_DRY_AIR_J_PER_KG_K = 287.05
WIND_CLASSES = ((200.0, 1, "Poor"), (300.0, 2, "Marginal"), (400.0, 3, "Fair"),
                (500.0, 4, "Good"), (600.0, 5, "Excellent"), (800.0, 6, "Outstanding"),
                (2000.0, 7, "Superb"))
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

USER_AGENT = ("autosolar-researcher/1 (resource screen; "
              "https://github.com/havidaqoma/autosolar-researcher)")

_OVERPASS_RETRY_URL = "https://overpass.kumi.systems/api/interpreter"

_REAL_TYPES = (int, float, np.integer, np.floating)


def _finite_real(name_str: str, value: object) -> float:
    """Value as a finite float. Raises ValueError on bad input."""
    if isinstance(value, bool) or not isinstance(value, _REAL_TYPES):
        raise ValueError(name_str + " must be a finite real: " + repr(value))
    out = float(value)  # type: ignore[arg-type]
    if not math.isfinite(out):
        raise ValueError(name_str + " must be a finite real: " + repr(value))
    return out


def _check_int(name_str: str, value: object) -> int:
    """Value as an int. Raises ValueError on bad input."""
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(name_str + " must be an int: " + repr(value))
    return int(value)  # type: ignore[arg-type]


def _check_lat(name_str: str, value: object) -> float:
    """Latitude in deg. Raises ValueError on bad input."""
    out = _finite_real(name_str, value)
    if not -90.0 <= out <= 90.0:
        raise ValueError(name_str + " must be within -90 to 90: " + repr(value))
    return out


def _check_lon(name_str: str, value: object) -> float:
    """Longitude in deg. Raises ValueError on bad input."""
    out = _finite_real(name_str, value)
    if not -180.0 <= out <= 180.0:
        raise ValueError(name_str + " must be within -180 to 180: " + repr(value))
    return out


def _check_radius(name_str: str, value: object) -> float:
    """Radius in km. Raises ValueError on bad input."""
    out = _finite_real(name_str, value)
    if not 0.0 < out <= 500.0:
        raise ValueError(name_str + " must be above 0 and at most 500: " + repr(value))
    return out


def haversine_km(lat1_deg: float, lon1_deg: float, lat2_deg: float, lon2_deg: float) -> float:
    """Great circle distance in km on a sphere of EARTH_RADIUS_KM. Inputs in deg."""
    lat1 = _check_lat("lat1_deg", lat1_deg)
    lon1 = _check_lon("lon1_deg", lon1_deg)
    lat2 = _check_lat("lat2_deg", lat2_deg)
    lon2 = _check_lon("lon2_deg", lon2_deg)
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lam = math.radians(lon2 - lon1)
    mid = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lam / 2.0) ** 2
    mid = min(1.0, max(0.0, mid))
    return float(2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(mid)))


def air_density_kg_m3(temp_degc: object, pressure_kpa: object) -> np.ndarray:
    """Dry air density in kg per m3. Temperature in degC, pressure in kPa."""
    try:
        temp = np.asarray(temp_degc, dtype=np.float64)
        pres = np.asarray(pressure_kpa, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError("inputs must be 1-D array likes of finite reals") from exc
    if temp.ndim != 1 or pres.ndim != 1:
        raise ValueError("inputs must be 1-D array likes of the same non-zero length")
    if temp.shape[0] != pres.shape[0] or temp.shape[0] == 0:
        raise ValueError("inputs must be 1-D array likes of the same non-zero length")
    if bool((~np.isfinite(temp)).any()) or bool((~np.isfinite(pres)).any()):
        raise ValueError("inputs must hold finite values")
    if bool(((temp <= -90.0) | (temp >= 70.0)).any()):
        raise ValueError("temperatures must be above -90 and below 70 degC")
    if bool(((pres <= 30.0) | (pres >= 120.0)).any()):
        raise ValueError("pressures must be above 30 and below 120 kPa")
    return (pres * 1000.0 / (R_DRY_AIR_J_PER_KG_K * (temp + 273.15))).astype(np.float64)


def _payload_dict(payload: object, *keys: str) -> object:
    """Nested payload value. Raises ValueError when a key is missing."""
    node = payload
    try:
        for key in keys:
            if not isinstance(node, dict):
                raise ValueError("payload must hold dicts at " + repr(key))
            node = node[key]
    except KeyError as exc:
        raise ValueError("payload is missing " + repr(key)) from exc
    return node


def wind_from_power(payload: dict) -> dict:
    """Wind summary from a NASA POWER hourly point payload. Speeds in m per s."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    param = _payload_dict(payload, "properties", "parameter")
    if not isinstance(param, dict):
        raise ValueError("payload properties parameter must be a dict")
    try:
        speed_d = param["WS50M"]
        temp_d = param["T2M"]
        pres_d = param["PS"]
    except KeyError as exc:
        raise ValueError("payload parameter must hold WS50M, T2M and PS") from exc
    for name_str, series in (("WS50M", speed_d), ("T2M", temp_d), ("PS", pres_d)):
        if not isinstance(series, dict):
            raise ValueError("payload parameter " + name_str + " must be a dict")
    keys = set(speed_d)
    if keys != set(temp_d) or keys != set(pres_d):
        raise ValueError("WS50M, T2M and PS must share the same keys")
    header = payload.get("header")
    fill = -999.0
    if isinstance(header, dict) and "fill_value" in header:
        fill = _finite_real("fill_value", header["fill_value"])
    ordered = sorted(keys)
    for key in ordered:
        if not isinstance(key, str) or len(key) != 10 or not key.isdigit():
            raise ValueError("keys must be YYYYMMDDHH text: " + repr(key))
        month = int(key[4:6])
        if not 1 <= month <= 12:
            raise ValueError("keys must hold a month from 01 to 12: " + repr(key))
    kept_keys: list[str] = []
    kept_speed: list[float] = []
    kept_temp: list[float] = []
    kept_pres: list[float] = []
    dropped = 0
    for key in ordered:
        raw_w = speed_d[key]
        raw_t = temp_d[key]
        raw_p = pres_d[key]
        for name_str, raw in (("WS50M", raw_w), ("T2M", raw_t), ("PS", raw_p)):
            if isinstance(raw, bool) or not isinstance(raw, _REAL_TYPES):
                raise ValueError("payload " + name_str + " must hold finite reals: " + repr(raw))
        if raw_w == fill or raw_t == fill or raw_p == fill:
            dropped += 1
            continue
        spd = float(raw_w)  # type: ignore[arg-type]
        tmp = float(raw_t)  # type: ignore[arg-type]
        prs = float(raw_p)  # type: ignore[arg-type]
        if not (math.isfinite(spd) and math.isfinite(tmp) and math.isfinite(prs)):
            raise ValueError("kept hours must hold finite values")
        if spd < 0.0:
            raise ValueError("wind speed must not be negative: " + repr(raw_w))
        kept_keys.append(key)
        kept_speed.append(spd)
        kept_temp.append(tmp)
        kept_pres.append(prs)
    if len(kept_keys) < 8760:
        raise ValueError("fewer than 8760 hours kept: " + str(len(kept_keys)))
    rho = air_density_kg_m3(np.array(kept_temp, dtype=np.float64), np.array(kept_pres, dtype=np.float64))
    vel = np.array(kept_speed, dtype=np.float64)
    monthly: list[float] = []
    for month in range(1, 13):
        vals = [spd for key, spd in zip(kept_keys, kept_speed) if int(key[4:6]) == month]
        if not vals:
            raise ValueError("month %02d has no kept hour" % month)
        monthly.append(float(sum(vals) / len(vals)))
    return {
        "hours": int(len(kept_keys)),
        "dropped_hours": int(dropped),
        "first": kept_keys[0],
        "last": kept_keys[-1],
        "mean_speed_m_s": float(sum(kept_speed) / len(kept_speed)),
        "mean_density_kg_m3": float(np.mean(rho)),
        "power_density_w_m2": float(np.mean(0.5 * rho * vel ** 3)),
        "monthly_mean_speed_m_s": monthly,
    }


def wind_class(power_density_w_m2: float) -> tuple:
    """NREL wind class number and name for power density in W per m2."""
    value = _finite_real("power_density_w_m2", power_density_w_m2)
    if value < 0.0:
        raise ValueError("power_density_w_m2 must be 0 or more: " + repr(power_density_w_m2))
    for upper, number, name in WIND_CLASSES:
        if value < upper:
            return (number, name)
    return (8, "Above Superb")


def solar_band(pvout_kwh_per_kwp_day: float) -> str:
    """World Bank band for daily PV output in kWh per kWp."""
    value = _finite_real("pvout_kwh_per_kwp_day", pvout_kwh_per_kwp_day)
    if not value > 0.0:
        raise ValueError("pvout_kwh_per_kwp_day must be above 0: " + repr(pvout_kwh_per_kwp_day))
    if value > SOLAR_EXCELLENT_KWH_PER_KWP_DAY:
        return "excellent"
    if value >= SOLAR_LOOK_KWH_PER_KWP_DAY:
        return "favorable middle range"
    return "lower end"


def gsa_lta(payload: dict) -> dict:
    """Yearly PV output in kWh per kWp and optimum tilt in deg from a GSA payload."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    data = _payload_dict(payload, "annual", "data")
    if not isinstance(data, dict):
        raise ValueError("payload annual data must be a dict")
    try:
        raw_pvout = data["PVOUT_csi"]
        raw_opta = data["OPTA"]
    except KeyError as exc:
        raise ValueError("payload annual data must hold PVOUT_csi and OPTA") from exc
    pvout = _finite_real("PVOUT_csi", raw_pvout)
    if not pvout > 0.0:
        raise ValueError("PVOUT_csi must be above 0: " + repr(raw_pvout))
    opta = _finite_real("OPTA", raw_opta)
    if not 0.0 <= opta <= 90.0:
        raise ValueError("OPTA must be from 0 to 90: " + repr(raw_opta))
    return {"pvout_kwh_per_kwp_yr": float(pvout), "opta_deg": float(opta)}


def pvgis_yield(payload: dict) -> float:
    """Yearly PV output in kWh per kWp from a PVGIS PVcalc payload."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    raw = _payload_dict(payload, "outputs", "totals", "fixed", "E_y")
    value = _finite_real("E_y", raw)
    if not value > 0.0:
        raise ValueError("E_y must be above 0: " + repr(raw))
    return float(value)


def water_query(lat_deg: float, lon_deg: float, radius_km: float) -> str:
    """Overpass query for mapped waterways. Coordinates in deg, radius in km."""
    lat = _check_lat("lat_deg", lat_deg)
    lon = _check_lon("lon_deg", lon_deg)
    radius = _check_radius("radius_km", radius_km)
    metres = int(round(radius * 1000.0))
    return '[out:json][timeout:90];way["waterway"](around:%d,%.6f,%.6f);out tags;' % (metres, lat, lon)


def place_query(lat_deg: float, lon_deg: float, radius_km: float) -> str:
    """Overpass query for mapped cities and towns. Coordinates in deg, radius in km."""
    lat = _check_lat("lat_deg", lat_deg)
    lon = _check_lon("lon_deg", lon_deg)
    radius = _check_radius("radius_km", radius_km)
    metres = int(round(radius * 1000.0))
    return '[out:json][timeout:90];node["place"~"^(city|town)$"](around:%d,%.6f,%.6f);out;' % (metres, lat, lon)


def waterway_counts(payload: dict) -> dict:
    """Counts of mapped waterways by kind. Radius choice is recorded by the caller."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("payload elements must be a list")
    counts = {kind: 0 for kind in WATERWAY_KINDS}
    other = 0
    names: set[str] = set()
    for element in elements:
        tags = element.get("tags") if isinstance(element, dict) else None
        kind = tags.get("waterway") if isinstance(tags, dict) else None
        if isinstance(kind, str) and kind in counts:
            counts[kind] += 1
        else:
            other += 1
        if kind == "river" and isinstance(tags, dict):
            label = tags.get("name")
            if isinstance(label, str) and label:
                names.add(label)
    osm_base = ""
    snap = payload.get("osm3s")
    if isinstance(snap, dict):
        stamp = snap.get("timestamp_osm_base")
        if isinstance(stamp, str):
            osm_base = stamp
    out: dict = dict(counts)
    out["other"] = int(other)
    out["named_rivers"] = sorted(names)
    out["osm_base"] = osm_base
    return out


def nearest_place(payload: dict, lat_deg: float, lon_deg: float) -> dict | None:
    """Nearest mapped city or town in km. Coordinates in deg."""
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    elements = payload.get("elements")
    if not isinstance(elements, list):
        raise ValueError("payload elements must be a list")
    lat = _check_lat("lat_deg", lat_deg)
    lon = _check_lon("lon_deg", lon_deg)
    best: tuple | None = None
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags")
        if not isinstance(tags, dict):
            continue
        kind = tags.get("place")
        if kind not in ("city", "town"):
            continue
        raw_lat = element.get("lat")
        raw_lon = element.get("lon")
        if isinstance(raw_lat, bool) or not isinstance(raw_lat, _REAL_TYPES):
            continue
        if isinstance(raw_lon, bool) or not isinstance(raw_lon, _REAL_TYPES):
            continue
        cand_lat = float(raw_lat)  # type: ignore[arg-type]
        cand_lon = float(raw_lon)  # type: ignore[arg-type]
        if not (math.isfinite(cand_lat) and math.isfinite(cand_lon)):
            continue
        dist_km = haversine_km(lat, lon, cand_lat, cand_lon)
        raw_name = tags.get("name")
        name = raw_name if isinstance(raw_name, str) and raw_name else ""
        if best is None or dist_km < best[0] or (dist_km == best[0] and name < best[1]):
            best = (dist_km, name, kind, raw_name if isinstance(raw_name, str) and raw_name else "")
    if best is None:
        return None
    return {"name": best[3], "place": best[2], "km": float(best[0])}


def pv_yield_checks(report: dict, *, pvgis_e_y_kwh_per_kwp: float,
                    gsa_pvout_kwh_per_kwp_yr: float) -> list:
    """Our weather-table yields against two outside PV models. Yields in kWh per kWp."""
    theirs_pvgis = _finite_real("pvgis_e_y_kwh_per_kwp", pvgis_e_y_kwh_per_kwp)
    if not theirs_pvgis > 0.0:
        raise ValueError("pvgis_e_y_kwh_per_kwp must be above 0: " + repr(pvgis_e_y_kwh_per_kwp))
    theirs_gsa = _finite_real("gsa_pvout_kwh_per_kwp_yr", gsa_pvout_kwh_per_kwp_yr)
    if not theirs_gsa > 0.0:
        raise ValueError("gsa_pvout_kwh_per_kwp_yr must be above 0: " + repr(gsa_pvout_kwh_per_kwp_yr))
    if not isinstance(report, dict):
        raise ValueError("report must be a dict")
    table = report.get("weather_table")
    if not isinstance(table, list):
        raise ValueError("report weather_table must be a list")

    def _ours(case_str: str) -> float:
        for row in table:
            if isinstance(row, dict) and row.get("case") == case_str:
                if "yield_kwh_kwp_yr" not in row:
                    raise ValueError("weather_table row holds no yield_kwh_kwp_yr: " + repr(case_str))
                return _finite_real("yield_kwh_kwp_yr", row["yield_kwh_kwp_yr"])
        raise ValueError("weather_table holds no row for case: " + repr(case_str))

    rows = []
    for service, case, theirs in (("PVGIS PVcalc (JRC), ERA5", "PVGIS-ERA5 TMY", theirs_pvgis),
                                  ("Global Solar Atlas PVOUT (Solargis)", "GSA scaled", theirs_gsa)):
        ours = _ours(case)
        rows.append({
            "service": service,
            "case": case,
            "theirs_kwh_per_kwp_yr": float(theirs),
            "ours_kwh_per_kwp_yr": float(ours),
            "gap_pct": float((ours - theirs) / theirs * 100.0),
        })
    return rows


def screen_verdicts(*, pvout_kwh_per_kwp_day: float, wind_class_number: int, rivers: int) -> dict:
    """One-line verdicts per resource. PV output in kWh per kWp a day."""
    pvout = _finite_real("pvout_kwh_per_kwp_day", pvout_kwh_per_kwp_day)
    if isinstance(wind_class_number, bool) or not isinstance(wind_class_number, (int, np.integer)):
        raise ValueError("wind_class_number must be an int from 1 to 8: " + repr(wind_class_number))
    number = int(wind_class_number)
    if not 1 <= number <= 8:
        raise ValueError("wind_class_number must be an int from 1 to 8: " + repr(wind_class_number))
    if isinstance(rivers, bool) or not isinstance(rivers, (int, np.integer)):
        raise ValueError("rivers must be an int 0 or more: " + repr(rivers))
    count = int(rivers)
    if count < 0:
        raise ValueError("rivers must be an int 0 or more: " + repr(rivers))
    return {
        "solar": LOOK if pvout >= SOLAR_LOOK_KWH_PER_KWP_DAY else NOT_ON_SCREEN,
        "wind": LOOK if number >= WIND_LOOK_CLASS else NOT_ON_SCREEN,
        "hydro": HYDRO_CHECK if count >= 1 else NOT_ON_SCREEN,
    }


def screen_doc(report: dict, *, run_id: str, wind: dict, gsa: dict, pvgis_e_y_kwh_per_kwp: float,
               water: dict, place: dict | None, files: dict, wall_s: float) -> dict:
    """Resource screen record for one study. Yields in kWh per kWp, wall time in s."""
    if not isinstance(report, dict):
        raise ValueError("report must be a dict")
    if not isinstance(run_id, str):
        raise ValueError("run_id must be a string: " + repr(run_id))
    if not isinstance(wind, dict):
        raise ValueError("wind must be a dict")
    if not isinstance(gsa, dict):
        raise ValueError("gsa must be a dict")
    if not isinstance(water, dict):
        raise ValueError("water must be a dict")
    if place is not None and not isinstance(place, dict):
        raise ValueError("place must be a dict or None")
    if not isinstance(files, dict):
        raise ValueError("files must be a dict")
    for key, value in files.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("files must map file names to sha256 hex text")
    wall = _finite_real("wall_s", wall_s)
    try:
        run_hash = report["run_hash"]
        site = report["site"]
        site_name = site["name"]
        site_lat = site["lat_deg"]
        site_lon = site["lon_deg"]
        coords = report["weather_coords_deg"]
    except (KeyError, TypeError) as exc:
        raise ValueError("report must hold run_hash, site and weather_coords_deg") from exc
    if not isinstance(site_name, str):
        raise ValueError("report site name must be a string")
    site_lat_f = _finite_real("site lat_deg", site_lat)
    site_lon_f = _finite_real("site lon_deg", site_lon)
    if not isinstance(coords, (list, tuple)):
        raise ValueError("report weather_coords_deg must be a list")
    try:
        power = wind["power_density_w_m2"]
        pvout_yr = gsa["pvout_kwh_per_kwp_yr"]
        opta = gsa["opta_deg"]
        river_count = water["river"]
    except KeyError as exc:
        raise ValueError("wind, gsa and water must hold their headline values") from exc
    power_f = _finite_real("power_density_w_m2", power)
    pvout_f = _finite_real("pvout_kwh_per_kwp_yr", pvout_yr)
    if not pvout_f > 0.0:
        raise ValueError("pvout_kwh_per_kwp_yr must be above 0")
    opta_f = _finite_real("opta_deg", opta)
    if not 0.0 <= opta_f <= 90.0:
        raise ValueError("opta_deg must be from 0 to 90")
    day = float(pvout_f / 365.0)
    number, class_name = wind_class(power_f)
    wind_out = dict(wind)
    wind_out["years"] = list(WIND_YEARS)
    wind_out["class_number"] = int(number)
    wind_out["class_name"] = str(class_name)
    water_out = dict(water)
    water_out["radius_km"] = float(WATER_RADIUS_KM)
    checks = pv_yield_checks(report, pvgis_e_y_kwh_per_kwp=pvgis_e_y_kwh_per_kwp,
                             gsa_pvout_kwh_per_kwp_yr=pvout_f)
    verdicts = screen_verdicts(pvout_kwh_per_kwp_day=day, wind_class_number=number,
                               rivers=river_count)
    return {
        "schema": RESOURCE_SCHEMA,
        "run_id": run_id,
        "study_run_hash": run_hash,
        "site": {"name": site_name, "lat_deg": float(site_lat_f), "lon_deg": float(site_lon_f)},
        "weather_coords_deg": list(coords),
        "solar": {
            "pvout_kwh_per_kwp_yr": float(pvout_f),
            "pvout_kwh_per_kwp_day": day,
            "opta_deg": float(opta_f),
            "band": solar_band(day),
        },
        "wind": wind_out,
        "hydro": water_out,
        "grid": {
            "nearest": None if place is None else dict(place),
            "radius_km": float(PLACE_RADIUS_KM),
        },
        "pv_checks": checks,
        "verdicts": verdicts,
        "files": dict(files),
        "wall_s": float(wall),
        "sources": dict(SOURCES),
        "note": NOTE,
    }


@dataclass(frozen=True)
class ResourceFetchers:
    """Callables that fetch the raw resource payloads. Latitudes in deg."""

    nasa_wind_hourly: Callable[[float, float, int, int], dict]
    pvgis_pvcalc: Callable[[float, float, float, float], dict]
    overpass: Callable[[str], dict]


def default_resource_fetchers() -> ResourceFetchers:
    """Live fetchers built with requests. Creating them makes no call."""
    import requests

    def _nasa(lat_deg: float, lon_deg: float, year_from: int, year_to: int) -> dict:
        lat = _finite_real("lat_deg", lat_deg)
        lon = _finite_real("lon_deg", lon_deg)
        first = _check_int("year_from", year_from)
        last = _check_int("year_to", year_to)
        params = {"parameters": "WS50M,T2M,PS", "community": "RE", "longitude": lon, "latitude": lat,
                  "start": "%d0101" % first, "end": "%d1231" % last, "format": "JSON",
                  "time-standard": "UTC"}
        resp = requests.get(SOURCES["nasa_power_hourly"], params=params, timeout=300,
                              headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.json()

    def _pvgis(lat_deg: float, lon_deg: float, tilt_deg: float, loss_pct: float) -> dict:
        lat = _finite_real("lat_deg", lat_deg)
        lon = _finite_real("lon_deg", lon_deg)
        tilt = _finite_real("tilt_deg", tilt_deg)
        loss = _finite_real("loss_pct", loss_pct)
        params = {"lat": lat, "lon": lon, "peakpower": 1, "loss": loss, "angle": tilt,
                  "aspect": 180 if lat < 0.0 else 0, "usehorizon": 1, "raddatabase": "PVGIS-ERA5",
                  "outputformat": "json"}
        resp = requests.get(SOURCES["pvgis_pvcalc"], params=params, timeout=120,
                              headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.json()

    def _overpass(query: str) -> dict:
        if not isinstance(query, str):
            raise ValueError("query must be a string: " + repr(query))
        try:
            resp = requests.post(SOURCES["overpass"], data={"data": query}, timeout=180,
                                 headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.json()
        except Exception:
            retry = requests.post(_OVERPASS_RETRY_URL, data={"data": query}, timeout=180,
                                  headers={"User-Agent": USER_AGENT})
            retry.raise_for_status()
            return retry.json()

    return ResourceFetchers(nasa_wind_hourly=_nasa, pvgis_pvcalc=_pvgis, overpass=_overpass)


def no_network_resource_fetchers() -> ResourceFetchers:
    """Fetchers that only raise. Every callable reports no network."""

    def _fail(*args: object, **kwargs: object) -> dict:
        raise RuntimeError("no network: cached data only")

    return ResourceFetchers(nasa_wind_hourly=_fail, pvgis_pvcalc=_fail, overpass=_fail)  # type: ignore[arg-type]


def cached_resource_fetchers(base: ResourceFetchers, cache_dir: object) -> ResourceFetchers:
    """Fetchers with a JSON file cache in cache_dir. Latitudes in deg."""
    if not isinstance(base, ResourceFetchers):
        raise ValueError("base must be a ResourceFetchers: " + repr(base))
    cache = Path(cache_dir)  # type: ignore[arg-type]
    cache.mkdir(parents=True, exist_ok=True)

    def _read_or_fetch(path: Path, fetch: Callable[[], dict]) -> dict:
        if path.is_file():
            return json.loads(path.read_text(encoding="ascii"))
        out = fetch()
        path.write_text(json.dumps(out, ensure_ascii=True), encoding="ascii")
        return out

    def _nasa(lat_deg: float, lon_deg: float, year_from: int, year_to: int) -> dict:
        lat = _finite_real("lat_deg", lat_deg)
        lon = _finite_real("lon_deg", lon_deg)
        first = _check_int("year_from", year_from)
        last = _check_int("year_to", year_to)
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / ("nasa_wind_%.4f_%.4f_%d_%d.json" % (lat, lon, first, last))
        return _read_or_fetch(path, lambda: base.nasa_wind_hourly(lat, lon, first, last))

    def _pvgis(lat_deg: float, lon_deg: float, tilt_deg: float, loss_pct: float) -> dict:
        lat = _finite_real("lat_deg", lat_deg)
        lon = _finite_real("lon_deg", lon_deg)
        tilt = _finite_real("tilt_deg", tilt_deg)
        loss = _finite_real("loss_pct", loss_pct)
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / ("pvgis_pvcalc_%.4f_%.4f_t%g_l%g.json" % (lat, lon, tilt, loss))
        return _read_or_fetch(path, lambda: base.pvgis_pvcalc(lat, lon, tilt, loss))

    def _overpass(query: str) -> dict:
        if not isinstance(query, str):
            raise ValueError("query must be a string: " + repr(query))
        cache.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
        path = cache / ("overpass_%s.json" % digest)
        return _read_or_fetch(path, lambda: base.overpass(query))

    return ResourceFetchers(nasa_wind_hourly=_nasa, pvgis_pvcalc=_pvgis, overpass=_overpass)
