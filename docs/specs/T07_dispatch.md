# T07: hourly dispatch of PV, battery and diesel (`autosolar/dispatch.py`)

## Why

Stage S5 needs, for one design (PV size, battery size, diesel fleet), the hour by hour flow of energy on the
island grid for a year: how much load PV serves, how much goes into and out of the battery, how much diesel runs
and burns, and what is curtailed or unserved. The diesel minimum load rule matters: a running generator may not
go below a set share of its rating, so at low net load it either charges the battery or wastes energy. The rule
set below is fixed so that every number is reproducible and can be checked by hand.

## Allowed extra dependencies

None beyond `AGENTS.md`. No network.

## Public API

```python
from autosolar.dispatch import Battery, DieselFleet, DispatchResult, dispatch, HOURLY_COLUMNS
```

```python
@dataclass(frozen=True)
class Battery:
    energy_kwh: float           # usable top of the range (nameplate), >= 0
    power_kw: float             # limit for charge and for discharge, AC side, >= 0
    round_trip_eff_frac: float  # in (0, 1]
    soc_min_frac: float         # in [0, 1)
    soc_initial_frac: float     # in [soc_min_frac, 1]

@dataclass(frozen=True)
class DieselFleet:
    unit_kw: float                               # rating of one generator, > 0
    n_units: int                                 # >= 1 (int, not bool)
    min_load_frac: float                         # in [0, 1)
    fuel_intercept_l_per_h_per_kw_rated: float   # >= 0, fuel per hour per kW of ONLINE rating
    fuel_slope_l_per_kwh: float                  # > 0, fuel per kWh of output
```

No defaults: every value comes from the caller with its own label and source. `energy_kwh == 0` requires
`power_kw == 0` (no battery). All fields are checked when `dispatch` is called; any bad field: `ValueError`
naming the field. Numbers must be finite real numbers; `bool` is never a number.

`HOURLY_COLUMNS` is this tuple, in this order:
`("load_kw", "pv_kw", "pv_to_load_kw", "pv_to_battery_kw", "pv_curtailed_kw", "battery_discharge_kw",
"diesel_kw", "diesel_to_load_kw", "diesel_to_battery_kw", "diesel_excess_kw", "diesel_units_on", "unserved_kw",
"soc_kwh", "fuel_l")`.

`dispatch(pv_kw: pandas.Series, load_kw: pandas.Series, battery: Battery, diesel: DieselFleet) -> DispatchResult`

Input checks (`ValueError`): both are `pandas.Series`; the indexes are equal (`pv_kw.index.equals(load_kw.index)`);
the index is a time zone aware `DatetimeIndex` with at least 24 rows and steps of exactly one hour; all values
numeric, finite and >= 0; `load_kw.sum() > 0`. `pv_kw` is the AC power the PV plant can deliver in each hour.

## The rule for each hour, in index order

Let `E = energy_kwh`, `P = power_kw`, `eta = sqrt(round_trip_eff_frac)` (same for charge and discharge),
`e_min = soc_min_frac * E`, `e_max = E`. The stored energy `s` starts at `soc_initial_frac * E`. Each row is one
hour, so kW and kWh have the same number. For hour `t` with `pv = pv_kw[t]` and `load = load_kw[t]`:

1. `pv_to_load = min(pv, load)`, `surplus = pv - pv_to_load`, `deficit = load - pv_to_load`.
2. If `surplus > 0` (then `deficit == 0`):
   `pv_to_battery = max(0, min(surplus, P, (e_max - s) / eta))`; `s += pv_to_battery * eta`;
   `pv_curtailed = surplus - pv_to_battery`. Diesel is off.
3. If `deficit > 0`: `max_dis = max(0, min(P, (s - e_min) * eta))`.
   - If `deficit <= max_dis + 1e-9`: `battery_discharge = deficit`. Diesel is off.
   - Otherwise the diesel must run. `rem = deficit - max_dis`,
     `units = min(n_units, ceil(rem / unit_kw - 1e-9))`, `cap = units * unit_kw`, `d_min = min_load_frac * cap`.
     - `rem > cap` (the fleet is too small): `diesel = cap`, `diesel_to_load = cap`,
       `battery_discharge = max_dis`, `unserved = rem - cap`.
     - `d_min <= rem <= cap`: `diesel = rem`, `diesel_to_load = rem`, `battery_discharge = max_dis`.
     - `rem < d_min` (minimum load binds): `diesel = d_min`, `diesel_to_load = min(deficit, d_min)`,
       `battery_discharge = deficit - diesel_to_load` (this is below `max_dis`). If `battery_discharge == 0`
       the leftover `left = d_min - diesel_to_load` charges the battery:
       `diesel_to_battery = max(0, min(left, P, (e_max - s) / eta))`, and `diesel_excess = left -
       diesel_to_battery` (wasted). When the battery discharges in this hour it does not also charge.
     - `diesel_units_on = units` whenever the diesel runs, else 0.
   - Then `s -= battery_discharge / eta` and `s += diesel_to_battery * eta`.
4. If `pv == load`: nothing flows apart from `pv_to_load`.
5. `soc_kwh` = `s` at the END of the hour. `fuel_l = diesel_units_on * unit_kw *
   fuel_intercept_l_per_h_per_kw_rated + fuel_slope_l_per_kwh * diesel` (zero when the diesel is off).

Every quantity not set in an hour is 0. For speed loop over plain Python floats (`.tolist()`), not over pandas
rows; one year with a battery should take well under one second.

## Output

```python
@dataclass(frozen=True)
class DispatchResult:
    hourly: pandas.DataFrame       # index = input index, columns HOURLY_COLUMNS in that order
    load_kwh: float                # sum of load_kw
    load_served_kwh: float         # load_kwh - unserved_kwh
    unserved_kwh: float
    unserved_frac: float           # unserved_kwh / load_kwh
    pv_available_kwh: float        # sum of pv_kw
    pv_used_kwh: float             # sum of pv_to_load_kw + pv_to_battery_kw
    pv_curtailed_kwh: float
    battery_charge_kwh: float      # sum of pv_to_battery_kw + diesel_to_battery_kw (AC side)
    battery_discharge_kwh: float
    diesel_kwh: float              # sum of diesel_kw
    diesel_excess_kwh: float
    fuel_l: float
    diesel_run_hours: int          # hours with diesel_units_on > 0
    diesel_starts: int             # hours with units on > 0 whose previous hour had 0 (the first hour counts)
    soc_start_kwh: float           # soc_initial_frac * energy_kwh
    soc_end_kwh: float             # last soc_kwh
    renewable_fraction_frac: float # max(0, 1 - (diesel_kwh - diesel_excess_kwh) / load_served_kwh); 0 if nothing served
```

All columns are float64 except `diesel_units_on`, which is int64. Totals are Python `float` (counts are `int`).

## Checks the tests apply (so the code must keep them)

- `pv_kw == pv_to_load_kw + pv_to_battery_kw + pv_curtailed_kw` and
  `load_kw == pv_to_load_kw + battery_discharge_kw + diesel_to_load_kw + unserved_kw` in every hour.
- `diesel_kw == diesel_to_load_kw + diesel_to_battery_kw + diesel_excess_kw` in every hour.
- `soc_kwh[t] == soc_kwh[t-1] + eta * (pv_to_battery_kw + diesel_to_battery_kw)[t] - battery_discharge_kw[t] / eta`,
  `e_min <= soc_kwh <= e_max` (rounding up to 1e-6 kWh).
- Charge and discharge are never both above zero in one hour; both stay at or below `P`.
- A running diesel never runs below `min_load_frac * diesel_units_on * unit_kw` or above `diesel_units_on * unit_kw`.
- `unserved_kw > 0` only in hours where all units run at full rating.

## Done when

`uv run pytest` passes (all tests, including earlier tasks) and `AGENTS.md` rules hold.

## Test check by the orchestrator

The tests in `tests/test_dispatch.py` were run against a throwaway reference implementation of this spec (kept
outside the repo): 51 of 51 passed, one full year in 0.02 s. The hand worked day in the tests was computed on
paper from the rule above. So a failing test means the code differs from this spec.
