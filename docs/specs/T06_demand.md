# T06: demand cases (`autosolar/demand.py`)

## Why

Stage S2 needs the island's hourly load for a year on the same hourly index as each weather case, so the
dispatch (T07) can balance PV, battery and diesel hour by hour. The first source is the one published load
profile for Karimunjawa (Hiron et al. 2021, Table 6), which passed the prep checks that can be applied to it. Two
scenario cases (tourist season, growth) are built from it with their inputs labelled. A stochastic RAMP case is
not part of this task.

## Allowed extra dependencies

None beyond `AGENTS.md`. No network.

## Public API

```python
from autosolar.demand import (HIRON_2021_LOAD_KW, HIRON_2021_SOURCE, HIRON_2021_DAILY_KWH_STATED,
                              HIRON_2021_PEAK_KW_STATED, HIRON_2021_GROWTH_FRAC_PER_YR, HIRON_2021_BASE_YEAR,
                              LOCAL_TZ, DemandCase, check_daily_profile, daily_profile_to_hourly,
                              build_demand_cases)
```

### Constants

- `HIRON_2021_LOAD_KW`: a tuple of 24 floats, the load column of Table 6 (p19), position `h` = the local hour that
  starts at `h:00` (WIB):
  `(1126.0, 1105.0, 1052.0, 1031.0, 1044.0, 1104.0, 1152.0, 1004.0, 995.0, 976.0, 942.0, 936.0, 949.0, 985.0,
  974.0, 934.0, 926.0, 1003.0, 1367.0, 1422.0, 1377.0, 1351.0, 1264.0, 1195.0)`. Sum 26214 kWh per day.
- `HIRON_2021_SOURCE = "Hiron et al. 2021, Energies 14, 8311, Table 6 (p19), doi:10.3390/en14248311"`.
- `HIRON_2021_DAILY_KWH_STATED = 26479.0` (text p12 prints "26,479 MWh" per day; the prep audit check C1 reads it
  as kWh, the only reading that fits the table).
- `HIRON_2021_PEAK_KW_STATED = 1422.0` (text p15).
- `HIRON_2021_GROWTH_FRAC_PER_YR = 0.0348` (text p11: "an increase in load of 3.48% per year").
- `HIRON_2021_BASE_YEAR = 2022` (the profile is the paper's load for 2022, p10 to p11).
- `LOCAL_TZ = "Asia/Jakarta"` (WIB, UTC+7; Karimunjawa is in Central Java).

### Functions

- `check_daily_profile(profile_kw, daily_kwh_expected: float, peak_kw_expected: float, tol_frac: float = 0.02)
  -> None`: `profile_kw` is any sequence of exactly 24 numbers (bool is not a number), each finite and >= 0. The
  sum must be within `tol_frac` of `daily_kwh_expected` (`abs(sum - expected) / expected <= tol_frac`) and the
  maximum within `tol_frac` of `peak_kw_expected` in the same way. Both expected values must be finite and > 0;
  `tol_frac` must be in [0, 0.5]. Any failure: `ValueError` whose message names the check that failed.
- `daily_profile_to_hourly(profile_kw, index: pandas.DatetimeIndex, local_tz: str = LOCAL_TZ) -> pandas.Series`:
  `profile_kw` as above (24 finite numbers >= 0). `index` must be a time zone aware `DatetimeIndex` with at least
  24 entries and steps of exactly one hour. Every stamp converted to `local_tz` must fall on a whole hour (minute
  0), else `ValueError` (a half hour zone cannot use an hourly profile). Returns a float64 Series named `load_kw`
  with the same index, value `profile_kw[stamp.tz_convert(local_tz).hour]`.

### Cases

```python
@dataclass(frozen=True)
class DemandCase:
    name: str                 # "paper", "tourist season" or "growth"
    load_kw: pandas.Series    # hourly, same index as the weather case, name "load_kw"
    label: str                # "paper" or "assumed scenario"
    source: str               # HIRON_2021_SOURCE for all three (the scenarios are built on it)
    annual_kwh: float         # load_kw.sum() (one hour steps, so kW per hour = kWh)
    peak_kw: float            # load_kw.max()
    notes: tuple[str, ...]
```

`build_demand_cases(index, *, profile_kw=HIRON_2021_LOAD_KW, season_months=(6, 7, 8, 12),
season_uplift_frac=0.15, growth_frac_per_yr=HIRON_2021_GROWTH_FRAC_PER_YR, base_year=HIRON_2021_BASE_YEAR,
target_year=2027, local_tz=LOCAL_TZ) -> dict[str, DemandCase]` with keys in this order: `"paper"`,
`"tourist season"`, `"growth"`.

Input checks (`ValueError`): `season_months` a non empty tuple or list of distinct ints in 1..12; `season_uplift_frac`
a finite number in [0, 1]; `growth_frac_per_yr` a finite number in [0, 0.2]; `base_year` and `target_year` ints
(not bool) with `base_year <= target_year`. Profile and index checks as in `daily_profile_to_hourly`.

- `"paper"`: `daily_profile_to_hourly(profile_kw, index, local_tz)`; label `"paper"`; notes
  `("profile repeated every day; local hour in " + local_tz,)`.
- `"tourist season"`: the paper series times `(1 + season_uplift_frac)` in every hour whose LOCAL month
  (`index.tz_convert(local_tz).month`) is in `season_months`, unchanged in other hours; label
  `"assumed scenario"`; notes `(f"season months {list(season_months)}, uplift {season_uplift_frac * 100:.1f}%
  (assumed)",)` (sorted months are not required; keep the order given).
- `"growth"`: the paper series times `(1 + growth_frac_per_yr) ** (target_year - base_year)`; label
  `"assumed scenario"`; notes `(f"growth {growth_frac_per_yr * 100:.2f}% per year from {base_year} to
  {target_year}",)`.

Every case Series is float64, named `load_kw`, with the given index.

## Done when

`uv run pytest` passes (all tests, including T01 to T05) and `AGENTS.md` rules hold.

## Test check by the orchestrator

The tests in `tests/test_demand.py` were run against a throwaway reference implementation of this spec (kept
outside the repo): 36 of 36 passed. So a failing test means the code differs from this spec.
