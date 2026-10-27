# T04: PV model (`autosolar/pv.py`)

## Why

Stage S5 needs the hourly AC output of a fixed PV array on a diesel island. This task turns an hourly weather
table into hourly PV power and energy with pvlib, plus a few totals that the G3 gate (specific yield and
performance ratio) will check later. Weather download is a separate task (T05); here the weather table is given.

## Allowed extra dependencies

None beyond `AGENTS.md` (numpy, pandas, pvlib are already there). No network: everything here is local.

## Public API

```python
from autosolar.pv import PVDesign, PVResult, simulate_pv
```

- `@dataclass(frozen=True) class PVDesign` (all fields have defaults; units in names):
  - `tilt_deg: float = 10.0` (0 to 90 inclusive)
  - `azimuth_deg: float | None = None` (0 <= value < 360, pvlib convention: 0 north, 90 east, 180 south;
    `None` means facing the equator: 0.0 when the site latitude is below 0, else 180.0)
  - `dc_ac_ratio: float = 1.2` (greater than 0 and at most 3)
  - `gamma_pdc_per_degc: float = -0.004` (from -0.01 to 0 inclusive)
  - `system_loss_pct: float = 14.0` (0 to 50 inclusive; PVWatts style DC losses)
  - `eta_inv_nom_frac: float = 0.96` (greater than 0.5 and at most 1)
  - `albedo_frac: float = 0.2` (0 to 1 inclusive)
  - `transposition: str = "haydavies"` (`"haydavies"` or `"isotropic"`)
  - `faiman_u0_w_m2_k: float = 25.0`, `faiman_u1_w_s_m3_k: float = 6.84` (both greater than 0)
  - Any value out of range or a NaN: `ValueError` in `__post_init__`.
- `@dataclass(frozen=True) class PVResult`:
  - `hourly: pandas.DataFrame`, same index as the weather table (same time zone), float columns in this order:
    `zenith_deg`, `dni_w_m2`, `dhi_w_m2`, `poa_global_w_m2`, `temp_cell_degc`, `dc_kw`, `ac_kw`, `ac_kwh`.
  - `n_hours: int`, `is_full_year: bool` (`n_hours` is 8760 or 8784), `azimuth_deg: float` (the resolved value),
    `pdc0_kw: float`, `pac0_kw: float`, `energy_ac_kwh: float`, `specific_yield_kwh_kwp: float`,
    `insolation_ghi_kwh_m2: float`, `insolation_poa_kwh_m2: float`, `performance_ratio_frac: float | None`.
- `simulate_pv(weather: pandas.DataFrame, lat_deg: float, lon_deg: float, design: PVDesign = PVDesign(),
  pdc0_kw: float = 1.0) -> PVResult`

## Weather table contract (checked first; any failure is a `ValueError` with a clear message)

- A `pandas.DataFrame` whose index is a time zone aware `DatetimeIndex`. Each row is one hour; the index value is
  the START of the hour. At least 24 rows, strictly increasing, every step exactly one hour.
- Required columns: `ghi_w_m2` (0 to 1500), `temp_air_degc` (-30 to 60), `wind_speed_m_s` (0 to 60).
- Optional columns `dni_w_m2` (0 to 1500) and `dhi_w_m2` (0 to 1000): both or neither. Only one of them:
  `ValueError` (never guess the other).
- No NaN in any column that is used. Extra columns are ignored.
- `lat_deg` in -90 to 90, `lon_deg` in -180 to 180, `pdc0_kw > 0`; else `ValueError`.

## Model (follow these steps exactly)

1. `mid` = the index converted to UTC plus 30 minutes (the middle of each hour). All pvlib inputs below are
   pandas Series indexed by `mid`.
2. `sp = pvlib.solarposition.get_solarposition(mid, lat_deg, lon_deg)`. Use `sp["zenith"]` (true zenith, not
   apparent) and `sp["azimuth"]` everywhere below.
3. If `dni_w_m2` and `dhi_w_m2` are given, use them. Else
   `e = pvlib.irradiance.erbs(ghi, sp["zenith"], mid)` and use `e["dni"]`, `e["dhi"]`.
4. `dni_extra = pvlib.irradiance.get_extra_radiation(mid)`;
   `poa = pvlib.irradiance.get_total_irradiance(tilt_deg, azimuth_deg, sp["zenith"], sp["azimuth"], dni, ghi,
   dhi, dni_extra=dni_extra, albedo=albedo_frac, model=transposition)["poa_global"]`. A NaN in `poa`:
   `ValueError`. Negative values (rounding) are set to 0.
5. `temp_cell = pvlib.temperature.faiman(poa, temp_air, wind_speed, u0=faiman_u0_w_m2_k, u1=faiman_u1_w_s_m3_k)`.
6. `dc_kw = pvlib.pvsystem.pvwatts_dc(poa, temp_cell, pdc0_kw, gamma_pdc_per_degc) * (1 - system_loss_pct / 100)`.
7. `pac0_kw = pdc0_kw / dc_ac_ratio`;
   `ac_kw = pvlib.inverter.pvwatts(dc_kw, pac0_kw / eta_inv_nom_frac, eta_inv_nom_frac)`.
8. `ac_kwh = ac_kw * 1.0` (one hour per row). Build `hourly` on the ORIGINAL index (values by position).
9. Totals: `energy_ac_kwh` = sum of `ac_kwh`; `specific_yield_kwh_kwp = energy_ac_kwh / pdc0_kw`;
   `insolation_ghi_kwh_m2` = sum of `ghi_w_m2` / 1000; `insolation_poa_kwh_m2` = sum of `poa_global_w_m2` / 1000;
   `performance_ratio_frac = specific_yield_kwh_kwp / insolation_poa_kwh_m2`, or `None` when the POA insolation
   is 0.

## Library facts (measured by the orchestrator with pvlib 0.16.1 in this repo's environment)

- `pvlib.solarposition.get_solarposition(time, latitude, longitude, ...)` returns a DataFrame with columns
  `apparent_zenith`, `zenith`, `apparent_elevation`, `elevation`, `azimuth`, `equation_of_time` (degrees).
- `pvlib.irradiance.erbs(ghi, zenith, datetime_or_doy, min_cos_zenith=0.065, max_zenith=87)` returns a DataFrame
  with columns `dni`, `dhi`, `kt` when `ghi` is a Series. Pass Series indexed by `mid`. pvlib 0.16.1 itself
  emits a `Pandas4Warning` ("DatetimeIndex.dayofyear is deprecated") from inside pvlib; it is harmless, leave it.
- `pvlib.irradiance.get_extra_radiation(datetime_or_doy, ...)` returns a Series (W/m2).
- `pvlib.irradiance.get_total_irradiance(surface_tilt, surface_azimuth, solar_zenith, solar_azimuth, dni, ghi,
  dhi, dni_extra=None, airmass=None, albedo=0.25, surface_type=None, model='isotropic', ...)` returns a DataFrame
  with columns `poa_global`, `poa_direct`, `poa_diffuse`, `poa_sky_diffuse`, `poa_ground_diffuse`. The
  `haydavies` model needs `dni_extra`. At night it can return values like 2e-12 instead of 0.
- `pvlib.temperature.faiman(poa_global, temp_air, wind_speed=1.0, u0=25.0, u1=6.84)` returns a Series (degC).
- `pvlib.pvsystem.pvwatts_dc(effective_irradiance, temp_cell, pdc0, gamma_pdc, temp_ref=25.0, k=None,
  cap_adjustment=False)`: output has the unit of `pdc0` (kW in, kW out); 0 when irradiance is 0.
- `pvlib.inverter.pvwatts(pdc, pdc0, eta_inv_nom=0.96, eta_inv_ref=0.9637)`: here `pdc0` is the inverter DC
  input limit and the AC output never exceeds `eta_inv_nom * pdc0`; `pdc = 0` gives 0 (no NaN, no warning);
  measured `pvwatts([0.0, 0.5, 2.0], 1.0, 0.96)` = `[0.0, 0.4811, 0.96]`.
- Measured with these steps at lat -5.85, lon 110.43, a clear sky year (pvlib `haurwitz`), 27 degC, 2 m/s and
  the default design: specific yield 2013.1 kWh/kWp, performance ratio 0.7529 (a test pins these).

## Done when

`uv run pytest` passes (all tests, including T01 to T03), no test touches the network, and `AGENTS.md` rules hold.

## Test check by the orchestrator

The tests in `tests/test_pv.py` were run against a throwaway reference implementation of the steps above (kept
outside the repo): 49 of 49 passed. So a failing test means the code differs from this spec.
