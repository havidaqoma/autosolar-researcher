# T05: weather cases (`autosolar/weather.py`)

## Why

Stage S1 needs hourly weather for the site from several free sources, because the sources disagree (18.8%
across four sources at Karimunjawa, `prep/data/xcheck4.json` in the prep repo). The study sizes on one source
(CAMS, the basis, fixed in the plan) and carries the others as cases. This task fetches the sources, turns each
into the T04 weather table (`ghi_w_m2`, `temp_air_degc`, `wind_speed_m_s`, hourly, index = start of the hour,
time zone aware) and reports the annual totals and their spread. `autosolar.pv.simulate_pv` then runs on each case.

## Allowed extra dependencies

None beyond `AGENTS.md` (numpy, pandas, pvlib, requests are already there). Unit tests never touch the network:
every fetch goes through a `WeatherFetchers` object, and tests pass fakes.

## Public API

```python
from autosolar.weather import (WeatherCases, WeatherFetchers, annual_totals_cams_monthly,
                               annual_totals_nasa_monthly, build_weather_cases, cached_fetchers, default_fetchers,
                               ghi_from_pvlib, gsa_annual_ghi_kwh_m2, meteo_from_pvlib, scale_ghi_to_annual,
                               spread_pct, weather_table, year_closest_to_mean)
```

Module constants: `YEAR_FROM = 2016`, `YEAR_TO = 2024` (the period for the year rule; CAMS returns nothing before
2016 at Karimunjawa, measured), `RANGE_REQUIRED_PCT = 10.0`, `CASE_NAMES = ("CAMS", "NASA POWER",
"PVGIS-ERA5 TMY", "GSA scaled")`, `BASIS = "CAMS"`.

### Hourly frames from pvlib

Shared index check for both functions below (any failure is a `ValueError`): `df` is a `pandas.DataFrame`, its
index is a time zone aware `DatetimeIndex`, at least 24 rows, every step exactly one hour.

- `ghi_from_pvlib(df) -> pandas.Series`: needs column `ghi` (W/m2). Values must be numbers, no NaN, none below 0
  (this also catches the NASA fill value -999), none above 1500. Returns a float64 Series named `ghi_w_m2` with
  the same index.
- `meteo_from_pvlib(df) -> pandas.DataFrame`: needs columns `temp_air` (degC, -30 to 60) and `wind_speed` (m/s, 0 to
  60), no NaN. Returns float64 columns `temp_air_degc`, `wind_speed_m_s` in that order, same index.
- `weather_table(ghi: pandas.Series, meteo: pandas.DataFrame) -> pandas.DataFrame`: `ghi.index.equals(meteo.index)`
  must hold, else `ValueError`. Returns columns `ghi_w_m2`, `temp_air_degc`, `wind_speed_m_s` in that order.

### Annual totals and the year rule

- `annual_totals_cams_monthly(df) -> dict[int, float]` (kWh/m2 per year): `df` is the pvlib CAMS frame for
  `time_step="1M", integrated=True`: column `ghi` in Wh/m2 per month, `DatetimeIndex` (naive or aware). Group by
  `df.index.year`; every year present must have exactly 12 rows; no NaN, no negative value; else `ValueError`.
  Total = sum / 1000. Keys in increasing year order.
- `annual_totals_nasa_monthly(payload: dict) -> dict[int, float]` (kWh/m2 per year): the NASA POWER monthly JSON.
  Values under `payload["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]`; a key of 6 characters ending in `"13"`
  (for example `"201613"`) is the annual value of year `int(key[:4])`, given as a mean per DAY in kWh/m2/day.
  Total = value * 366 for a leap year (`calendar.isleap`), else value * 365. A missing path, no annual key, a
  value that is not a number, or a value below 0 (fill is -999): `ValueError`. Keys in increasing year order.
- `gsa_annual_ghi_kwh_m2(payload: dict) -> float`: `payload["annual"]["data"]["GHI"]` (Global Solar Atlas,
  kWh/m2 per year). Missing, not a number, NaN, or not above 0: `ValueError`.
- `year_closest_to_mean(totals: dict[int, float]) -> int`: the year whose total is closest to the mean of all
  totals; on a tie the earliest year. Empty dict or a non finite value: `ValueError`.
- `spread_pct(totals: dict[str, float]) -> float`: `(max - min) / min * 100`. Fewer than 2 values, a non finite
  value, or a value not above 0: `ValueError`.
- `scale_ghi_to_annual(weather: pandas.DataFrame, target_kwh_m2: float) -> pandas.DataFrame`: a copy whose
  `ghi_w_m2` is multiplied by `target_kwh_m2 / (weather["ghi_w_m2"].sum() / 1000)`; other columns and the index
  unchanged. `target_kwh_m2` not above 0 or not finite, a zero GHI sum, or any scaled value above 1500:
  `ValueError`.

### Fetchers

```python
@dataclass(frozen=True)
class WeatherFetchers:
    cams_monthly: Callable[[float, float, int, int, str], pandas.DataFrame]   # lat, lon, year_from, year_to, email
    cams_hourly: Callable[[float, float, int, str], pandas.DataFrame]         # lat, lon, year, email
    nasa_monthly: Callable[[float, float, int, int], dict]                    # lat, lon, year_from, year_to
    nasa_hourly: Callable[[float, float, int], pandas.DataFrame]              # lat, lon, year
    pvgis_tmy: Callable[[float, float], pandas.DataFrame]                     # lat, lon
    gsa: Callable[[float, float], dict]                                       # lat, lon
```

- `default_fetchers() -> WeatherFetchers` makes NO network call itself. Its callables do exactly this:
  - `cams_monthly`: `pvlib.iotools.get_cams(lat, lon, f"{year_from}-01-01", f"{year_to}-12-31", email=email,
    identifier="cams_radiation", time_step="1M", time_ref="UT", integrated=True, timeout=180)[0]`
  - `cams_hourly`: `pvlib.iotools.get_cams(lat, lon, f"{year}-01-01", f"{year}-12-31", email=email,
    identifier="cams_radiation", time_step="1h", time_ref="UT", integrated=False, timeout=180)[0]`
  - `nasa_monthly`: `requests.get("https://power.larc.nasa.gov/api/temporal/monthly/point", params={"parameters":
    "ALLSKY_SFC_SW_DWN", "community": "RE", "longitude": lon, "latitude": lat, "start": year_from, "end": year_to,
    "format": "JSON"}, timeout=60)`, then `raise_for_status()`, then `.json()`.
  - `nasa_hourly`: `pvlib.iotools.get_nasa_power(lat, lon, pandas.Timestamp(f"{year}-01-01", tz="UTC"),
    pandas.Timestamp(f"{year}-12-31 23:00", tz="UTC"), parameters=["ghi", "temp_air", "wind_speed"])[0]`
  - `pvgis_tmy`: `pvlib.iotools.get_pvgis_tmy(lat, lon, outputformat="json", usehorizon=True, map_variables=True,
    timeout=60)[0]`
  - `gsa`: `requests.get("https://api.globalsolaratlas.info/data/lta", params={"loc": f"{lat},{lon}"}, timeout=60)`,
    then `raise_for_status()`, then `.json()`.
- `cached_fetchers(base: WeatherFetchers, cache_dir: pathlib.Path) -> WeatherFetchers`: same signatures; each call
  first looks for its file in `cache_dir` (created if missing) and calls `base` only when the file is not there.
  File names, with `la = f"{lat:.4f}"` and `lo = f"{lon:.4f}"` (the e-mail is never part of a name):
  `cams_monthly_{la}_{lo}_{year_from}_{year_to}.csv`, `cams_hourly_{la}_{lo}_{year}.csv`,
  `nasa_monthly_{la}_{lo}_{year_from}_{year_to}.json`, `nasa_hourly_{la}_{lo}_{year}.csv`, `pvgis_tmy_{la}_{lo}.csv`,
  `gsa_{la}_{lo}.json`. A frame is written with `df.to_csv(path)` and read back with
  `pandas.read_csv(path, index_col=0)` followed by `index = pandas.to_datetime(index, utc=True)`. A dict is
  written with `json.dump` (UTF-8) and read back with `json.load`.

### Building the cases

```python
@dataclass(frozen=True)
class WeatherCases:
    basis: str                                  # BASIS
    cases: dict[str, pandas.DataFrame]          # keys in CASE_NAMES order; each a weather_table(...) result
    years: dict[str, int | None]                # data year per case; None for the TMY
    annual_ghi_kwh_m2: dict[str, float]         # per case: cases[k]["ghi_w_m2"].sum() / 1000
    spread_pct_all: float                       # spread_pct(annual_ghi_kwh_m2)
    spread_pct_no_era5: float                   # same without "PVGIS-ERA5 TMY"
    range_required: bool                        # spread_pct_all > RANGE_REQUIRED_PCT
    cams_annual_totals_kwh_m2: dict[int, float]
    nasa_annual_totals_kwh_m2: dict[int, float]
    gsa_annual_ghi_kwh_m2: float
    notes: list[str]
```

`build_weather_cases(lat_deg: float, lon_deg: float, cams_email: str, fetchers: WeatherFetchers) -> WeatherCases`.
Steps, in this order:

1. Check `lat_deg` in -90 to 90, `lon_deg` in -180 to 180 (finite numbers), `cams_email` a string containing
   `"@"`; else `ValueError`.
2. `cams_tot = annual_totals_cams_monthly(fetchers.cams_monthly(lat, lon, YEAR_FROM, YEAR_TO, cams_email))`. Its
   years must be exactly `YEAR_FROM..YEAR_TO`, else `ValueError`. `cams_year = year_closest_to_mean(cams_tot)`.
3. `nasa_tot = annual_totals_nasa_monthly(fetchers.nasa_monthly(lat, lon, YEAR_FROM, YEAR_TO))`, same year check.
   `nasa_year = year_closest_to_mean(nasa_tot)`.
4. `nasa_cams_year = fetchers.nasa_hourly(lat, lon, cams_year)`. If `nasa_year == cams_year`, reuse that frame for
   the NASA POWER case (call `nasa_hourly` once); else call `fetchers.nasa_hourly(lat, lon, nasa_year)`.
5. Cases:
   - `"CAMS"`: `weather_table(ghi_from_pvlib(fetchers.cams_hourly(lat, lon, cams_year, cams_email)),
     meteo_from_pvlib(nasa_cams_year))` (CAMS gives irradiance only, so temperature and wind come from NASA POWER of
     the same year; the indexes must match, which `weather_table` checks).
   - `"NASA POWER"`: `weather_table(ghi_from_pvlib(f), meteo_from_pvlib(f))` with `f` the NASA frame of `nasa_year`.
   - `"PVGIS-ERA5 TMY"`: the same with `f = fetchers.pvgis_tmy(lat, lon)`.
   - `"GSA scaled"`: `scale_ghi_to_annual(cases["CAMS"], gsa)` with `gsa = gsa_annual_ghi_kwh_m2(fetchers.gsa(lat,
     lon))` (the Global Solar Atlas gives a long term annual total only, so the basis hourly shape is scaled).
6. `years = {"CAMS": cams_year, "NASA POWER": nasa_year, "PVGIS-ERA5 TMY": None, "GSA scaled": cams_year}`.
7. `notes`, exactly these three strings in this order:
   `f"CAMS case: temperature and wind from NASA POWER {cams_year}"`,
   `f"GSA scaled case: CAMS {cams_year} hourly shape scaled to the GSA long term annual GHI"`,
   `"PVGIS-ERA5 TMY case: months from different years, stamped 1990 by pvlib"`.

## Library facts (measured by the orchestrator on Tuesday 27 Oct, pvlib 0.16.1, Karimunjawa -5.85, 110.43)

Saved responses are in `tests/fixtures/weather/` (the hourly files keep the first 48 rows only).

- `get_cams(...)`, `get_nasa_power(...)` and `get_pvgis_tmy(...)` each return a 2 item tuple `(data, metadata)`.
- CAMS hourly 2020: 8784 rows, UTC index at the START of each hour (the `Observation period` column reads
  `2020-01-01T00:00:00.0/2020-01-01T01:00:00.0` for the 00:00 row); columns include `ghi`, `dni`, `dhi` and the
  text column `Observation period`; no temperature, no wind; no NaN.
- CAMS monthly (`time_step="1M"`, `integrated=True`): index is the LAST day of the month, no time zone (January 2016
  is `2016-01-31`), `ghi` in Wh/m2 per month; 108 rows for 2016 to 2024.
- NASA POWER hourly 2020: 8784 rows, UTC index, columns `ghi`, `temp_air`, `wind_speed` (wind at 10 m: `WS10M`);
  units Wh/m2 per hour for irradiance (equal to the mean W/m2 of that hour); fill value -999 (none present).
- PVGIS TMY: 8760 rows, UTC index from `1990-01-01 00:00`, columns include `ghi`, `temp_air`, `wind_speed` (10 m);
  `radiation_db` is `PVGIS-ERA5` here (no SARAH coverage), months picked from 2005 to 2023.
- Timing check: for all three hourly sources the correlation between GHI and the cosine of the solar zenith peaks
  when the sun position is taken 20 to 30 minutes after the index stamp, so the index is the start of the hour,
  as the T04 contract assumes.
- From the saved monthly files: CAMS totals 2016 to 2024 have mean 1701.6 kWh/m2 and the closest year is 2020
  (1680.2); NASA POWER totals have mean 1823.9 and the closest year is 2020 (1825.8). Global Solar Atlas GHI is
  1776.8203125.

## Test check by the orchestrator

The tests in `tests/test_weather.py` were run against a throwaway reference implementation of the steps above
(kept outside the repo): 45 of 45 passed. The same reference then ran once on the live services (125 s): years
CAMS 2020 and NASA POWER 2020; annual GHI CAMS 1680.2, NASA POWER 1825.8, PVGIS-ERA5 TMY 2026.7, GSA scaled 1776.8
kWh/m2 (spread 20.6%, 8.7% without ERA5, so the range is required); `simulate_pv` at tilt 10 facing north gave
1311 to 1584 kWh/kWp with a performance ratio of 0.77 for every case. So a failing test means the code differs from
this spec.

## Done when

`uv run pytest` passes (all tests, including T01 to T04), no test touches the network, and `AGENTS.md` rules hold.
