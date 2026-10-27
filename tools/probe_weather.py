"""Orchestrator probe (not product code, not part of any test): measure what the free weather sources return.

Fetches through pvlib for Karimunjawa and saves the frames as CSV plus the metadata as JSON in
runs/weather_probe/, so the T05 spec can state measured library facts. Usage:
    uv run python tools/probe_weather.py
"""
import json
import os
import pathlib
import time

import pandas as pd
import pvlib
import requests

LAT, LON = -5.85, 110.43
EMAIL = os.environ["AUTOSOLAR_CAMS_EMAIL"]  # the address registered at soda-pro.com for CAMS; never hard coded
OUT = pathlib.Path("runs/weather_probe")
OUT.mkdir(parents=True, exist_ok=True)
log = {}


def keep(name, df, meta):
    df.to_csv(OUT / (name + ".csv"))
    log[name] = {"columns": list(df.columns), "rows": len(df), "index_tz": str(df.index.tz),
                 "first_index": str(df.index[0]), "last_index": str(df.index[-1]),
                 "dtypes": {c: str(t) for c, t in df.dtypes.items()}}
    (OUT / (name + "_meta.json")).write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")


t = time.time()
tmy = pvlib.iotools.get_pvgis_tmy(LAT, LON, outputformat="json", usehorizon=True, map_variables=True, timeout=60)
print("tmy return type", type(tmy), len(tmy) if isinstance(tmy, tuple) else "")
df, meta = (tmy[0], tmy[-1]) if isinstance(tmy, tuple) else (tmy, {})
keep("pvgis_tmy", df, {"items": [str(x)[:2000] for x in tmy[1:]]} if isinstance(tmy, tuple) else {})
print("tmy s", round(time.time() - t, 1))

raw = requests.get("https://re.jrc.ec.europa.eu/api/v5_3/tmy", params={"lat": LAT, "lon": LON, "outputformat": "json"},
                   timeout=60)
print("raw tmy http", raw.status_code)
(OUT / "pvgis_tmy_raw.json").write_text(raw.text, encoding="utf-8")

t = time.time()
npw = pvlib.iotools.get_nasa_power(LAT, LON, pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2020-12-31 23:00", tz="UTC"),
                                   parameters=["dni", "dhi", "ghi", "temp_air", "wind_speed"])
df, meta = (npw[0], npw[1]) if isinstance(npw, tuple) else (npw, {})
keep("nasa_power_2020", df, meta)
print("nasa s", round(time.time() - t, 1))

t = time.time()
cams = pvlib.iotools.get_cams(LAT, LON, "2020-01-01", "2020-12-31", email=EMAIL, identifier="cams_radiation",
                              time_step="1h", time_ref="UT", integrated=False, timeout=180)
df, meta = (cams[0], cams[1]) if isinstance(cams, tuple) else (cams, {})
keep("cams_2020", df, meta)
print("cams s", round(time.time() - t, 1))

mon = requests.get("https://power.larc.nasa.gov/api/temporal/monthly/point",
                   params={"parameters": "ALLSKY_SFC_SW_DWN", "community": "RE", "longitude": LON, "latitude": LAT,
                           "start": 2016, "end": 2024, "format": "JSON"}, timeout=60)
print("nasa monthly http", mon.status_code)
(OUT / "nasa_power_monthly_2016_2024.json").write_text(mon.text, encoding="utf-8")

gsa = requests.get("https://api.globalsolaratlas.info/data/lta", params={"loc": f"{LAT},{LON}"}, timeout=60)
print("gsa http", gsa.status_code)
(OUT / "gsa_lta.json").write_text(gsa.text, encoding="utf-8")

(OUT / "probe_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
print(json.dumps(log, indent=1)[:3000])
