# T11a: a reserve case with diesel units that always run

Status: spec by the orchestrator. Builder edits `autosolar/dispatch.py` only.
T07 stays in force except where this spec changes it. `autosolar/sweep.py` and `autosolar/study.py` do not change
in this task.

## Why

In the least cost Karimunjawa design (study ff628b57b3c357b1, computed) the diesel runs 1,458 of 8,760 hours and
starts 217 times a year. In the other hours the battery alone holds the island grid. That needs grid forming
inverters and a reserve plan, which the study does not model. The PLN engineer quoted in the press calls the new
PV plant an additional plant next to the diesel plant, each one backing up the other (press). So the report needs
a bounding case where some diesel units run in every hour. This task adds that option to the dispatch. A later task (T11b)
uses it in the report.

## 1. DieselFleet

- New last field: `must_run_units: int = 0`. It is the number of diesel units that run in every hour.
- Old calls that do not name it keep working, and give exactly the results they gave before (same floats).
- Check in `__post_init__`, with `ValueError` messages that contain the field name `must_run_units`:
  - it must be an `int` (numpy integers are fine), never a `bool` and never a float;
  - `0 <= must_run_units <= n_units`.
- When `must_run_units >= 1`, `min_load_frac` must be at most 0.5. Otherwise raise a `ValueError` whose message
  contains `min_load_frac`. (With this limit, any hour that needs more units than the must run units already
  loads them above their minimum load, so the rule below never has to push extra diesel into the battery while the
  battery is discharging.)

## 2. The rule for each hour when must_run_units = m >= 1

Names as in T07: `eta = sqrt(round_trip_eff_frac)`, `e_min = soc_min_frac * energy_kwh`,
`e_max = energy_kwh`, `s` is the stored energy in kWh, `unit_kw`, `n = n_units`, `f = min_load_frac`.
When m = 0 the T07 rule runs unchanged.

1. `d_must = m * unit_kw * f`. The must run units make at least this much in kW.
2. `a = min(load, d_must)` is diesel to load first. `load_left = load - a`. `spare = d_must - a`.
3. `pv_to_load = min(pv, load_left)`, `surplus = pv - pv_to_load`, `deficit = load_left - pv_to_load`.
4. If `surplus > 0`: PV charges the battery as in T07:
   `room = max(0, (e_max - s) / eta)`, `pv_to_battery = min(surplus, power_kw, room)`,
   `s += pv_to_battery * eta`, `pv_curtailed = surplus - pv_to_battery`.
5. If `spare > 0` (this only happens when load < d_must, so `deficit` is 0): the spare diesel charges the battery
   with what is left: `power_left = power_kw - pv_to_battery`, `room = max(0, (e_max - s) / eta)`,
   `diesel_to_battery = min(spare, power_left, room)`, `s += diesel_to_battery * eta`,
   `diesel_excess = spare - diesel_to_battery`.
6. If `deficit > 0`: `headroom = max(0, (s - e_min) * eta)`, `max_dis = min(headroom, power_kw)`.
   - If `deficit <= max_dis + 1e-9`: `battery_discharge = deficit`; the diesel stays at `d_must` with m units on.
   - Otherwise `rem = deficit - max_dis`, `need = d_must + rem`,
     `units = ceil(need / unit_kw - 1e-9)` limited to the range `[m, n]`, `cap = units * unit_kw`.
     `battery_discharge = max_dis`. If `need > cap`: diesel makes `cap`, all of it to load, and
     `unserved = need - cap`. Else diesel makes `need`, all of it to load.
   - Then `s -= battery_discharge / eta`.
7. In every hour `diesel_units_on >= m` and `diesel_kw >= d_must`. `diesel_to_load = a` plus any diesel above
   `d_must` from step 6. Fuel stays `units_on * unit_kw * fuel_intercept + fuel_slope * diesel_kw`.
8. Totals, `diesel_run_hours`, `diesel_starts` and `renewable_fraction_frac` use the T07 formulas. With m >= 1
   the diesel runs in every hour, so `diesel_run_hours` is the number of hours and `diesel_starts` is 1.

## 3. Hand worked day (in the tests)

Same battery and diesel as the T07 hand day (unit 100 kW, 2 units, min load 0.3, intercept 0.08, slope 0.25;
battery 100 kWh, 50 kW, round trip 0.81, minimum 0.2, start 0.5) with `must_run_units = 1`, so `d_must = 30`.
PV and load for hours 0 to 8 are (80, 30), (80, 30), (0, 40), (0, 120), (0, 10), (0, 250), (0, 25), (0, 33),
(50, 50); hours 9 to 23 are (0, 0). The orchestrator worked it on paper; the tests hold every column.

## Done when

- `tests/test_must_run.py` passes, and every test that passed before still passes.
- `tools/check_text.py` passes on `autosolar/dispatch.py`; the file stays ASCII; no new import.

## Test check by the orchestrator

- Reference build in scratch (the spec applied to a copy of `dispatch.py`): all 42 tests in `tests/test_must_run.py`
  pass; the full suite passes 825 of 825 (783 old plus 42 new).
- 20 planted faults, each caught: field default 1; bool accepted; float accepted; upper bound off by one; no limit on
  min load; floor from all units; PV served before the floor; spare diesel wasted; spare charge ignores the PV
  charge; spare charge without the efficiency; battery covers the floor; need without the floor; extra units from 1
  not from the must run count; battery idle when more diesel runs; unserved energy lost; discharge without the
  efficiency; old rule always used; fuel without the no load part; excess not booked; curtailment lost.
