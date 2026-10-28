# T15: more checks (battery power, island prices, load not served, diesel engine hours)

Status: spec by the orchestrator. Builder edits `autosolar/firmness.py`, `autosolar/study.py` and `autosolar/site.py`
only. T11b, T13, T13b and T14 stay in force except where this spec changes them. The orchestrator has already added
the new check input to `config/study_checks.json` and updated the old tests listed at the end.

## Why

The second Wonder review of study 84f23f2cd0b0f857 (review-20261028T061110-63e19f) left four points open that the
study can answer from data it already computes:

- Point 3: the battery power (4,750 kW) comes from an assumed 4 h duration and is never tested.
- Point 4: island costs (shipping, labour, EPC premium) may be far above the PV and battery prices used.
- Point 8: diesel overhaul and engine replacement are left out.
- Point 9: the study reports no actual load not served and nothing on battery wear.

A scratch run on the cached weather of that study (no network, no model call) gave these values (computed): the
battery charges at up to 4,555 kW (96% of its rating) and discharges at up to 1,422 kW; an 8 h duration gives
7,500 kWp with 19,000 kWh at 0.255 USD/kWh (1.4% above the 4 h answer); PV and battery capital prices can rise 189%
(PV to 3,239 USD/kWp, battery to 868 USD/kWh) before diesel only is cheaper; no load is left unserved; the battery
discharges 249 full cycles a year; diesel engine hours fall from 8,760 to 1,458 unit hours a year (83.4% cut).

## Changes

### autosolar/firmness.py

1. `OPTIONAL_CHECK_NAMES = ("diesel_unit_kw_alt", "battery_duration_h_alt")`. `load_checks` checks
   `battery_duration_h_alt` exactly like `diesel_unit_kw_alt` (dict with exactly value, unit, label, note; non-empty
   unit; label in `LABELS`; note a string; value a finite int or float that is not a bool and is above 0; int becomes
   float). The returned values dict holds it only when the file has it. Any key outside `CHECK_NAMES` and
   `OPTIONAL_CHECK_NAMES` still raises `ValueError`.
2. New tuple `DUR_KEYS`, in this order: `dur_alt_hours`, `dur_alt_pv_kwp`, `dur_alt_battery_kwh`,
   `dur_alt_battery_kw`, `dur_alt_lcoe_usd_per_kwh`, `dur_alt_change_pct`, `dur_alt_on_grid_edge`.
3. New tuple `MORE_KEYS` holding the nineteen keys of the table below in table order (it includes the seven
   `DUR_KEYS`). `FIRM_SPECS` gains these nineteen rows, in this order, right after `alt_reserve_lcoe_usd_per_kwh` and
   before `sourcing_cost_usd`:

   | key | unit | label | decimals |
   |---|---|---|---|
   | battery_peak_discharge_kw | kW | computed | 0 |
   | battery_peak_charge_kw | kW | computed | 0 |
   | battery_peak_use_pct | % | computed | 1 |
   | dur_alt_hours | h | check | 1 |
   | dur_alt_pv_kwp | kWp | computed | 0 |
   | dur_alt_battery_kwh | kWh | computed | 0 |
   | dur_alt_battery_kw | kW | computed | 0 |
   | dur_alt_lcoe_usd_per_kwh | USD/kWh | computed | 3 |
   | dur_alt_change_pct | % | computed | 1 |
   | dur_alt_on_grid_edge | (empty string) | computed | 0 |
   | capex_break_even_rise_pct | % | computed | 1 |
   | capex_break_even_pv_usd_per_kwp | USD/kWp | computed | 0 |
   | capex_break_even_battery_usd_per_kwh | USD/kWh | computed | 0 |
   | best_unserved_kwh_yr | kWh/yr | computed | 0 |
   | best_unserved_hours | h/yr | computed | 0 |
   | best_battery_cycles_yr | cycles/yr | computed | 0 |
   | engine_hours_diesel_only | unit h/yr | computed | 0 |
   | engine_hours_best | unit h/yr | computed | 0 |
   | engine_hours_cut_pct | % | computed | 1 |

   `FIRM_CHECK_LABEL` gains `"dur_alt_hours": "battery_duration_h_alt"`. `FIRM_TITLES` gains:

   - battery_peak_discharge_kw: `Battery power: highest discharge in any hour, main design`
   - battery_peak_charge_kw: `Battery power: highest charge in any hour, main design`
   - battery_peak_use_pct: `Battery power: highest hour as a share of the power rating`
   - dur_alt_hours: `Battery duration check: other duration (battery kWh per kW)`
   - dur_alt_pv_kwp: `Battery duration check: least cost PV size`
   - dur_alt_battery_kwh: `Battery duration check: least cost battery`
   - dur_alt_battery_kw: `Battery duration check: battery power rating`
   - dur_alt_lcoe_usd_per_kwh: `Battery duration check: least cost LCOE`
   - dur_alt_change_pct: `Battery duration check: change against the main least cost LCOE`
   - dur_alt_on_grid_edge: `Battery duration check: least cost design on the grid edge`
   - capex_break_even_rise_pct: `Island prices: rise in PV and battery capital prices before diesel only is cheaper`
   - capex_break_even_pv_usd_per_kwp: `Island prices: PV capital price at that point`
   - capex_break_even_battery_usd_per_kwh: `Island prices: battery energy capital price at that point`
   - best_unserved_kwh_yr: `Least cost design: load not served`
   - best_unserved_hours: `Least cost design: hours with some load not served`
   - best_battery_cycles_yr: `Least cost design: battery discharge in full battery cycles`
   - engine_hours_diesel_only: `Diesel engine hours: diesel only (hours times units running)`
   - engine_hours_best: `Diesel engine hours: least cost design`
   - engine_hours_cut_pct: `Diesel engine hours: cut by the least cost design`
4. `OUT_OF_SCOPE` gains a ninth line at the end: `Diesel overhaul and engine replacement costs, which grow with
   engine hours`.
5. Five new functions. Each raises `ValueError` on bad input. A "real number" below means an int or float that is not
   a bool and is finite.

   ```
   def battery_power_use(hourly, battery_kw) -> dict
   ```

   - `hourly` is a DataFrame with at least one row and the columns `battery_discharge_kw`, `pv_to_battery_kw` and
     `diesel_to_battery_kw`; `battery_kw` is a real number of at least 0.
   - Returns `{"peak_discharge_kw", "peak_charge_kw", "peak_use_pct"}`: the largest `battery_discharge_kw`; the
     largest hourly sum `pv_to_battery_kw + diesel_to_battery_kw` (summed row by row, then the largest); and
     `100 * max(peak_discharge_kw, peak_charge_kw) / battery_kw`, or None when `battery_kw` is 0. All floats.

   ```
   def duration_case(pv_kw_per_kwp, load_kw, pv_grid, battery_grid, *, battery_hours, battery_template, diesel,
                     costs, co2_kg_per_l, unserved_max_frac, main_lcoe_usd_per_kwh) -> dict
   ```

   - `battery_hours` and `main_lcoe_usd_per_kwh` are real numbers above 0.
   - Run `dispatch_grid` on the given grids with `battery_hours`, then `cost_table`, then `least_cost`.
   - Returns `{"hours", "pv_kwp", "battery_kwh", "battery_kw", "lcoe_usd_per_kwh", "change_pct", "on_grid_edge"}`:
     `hours` is `float(battery_hours)`; the sizes and LCOE come from the pick; `change_pct = 100 * (lcoe /
     main_lcoe_usd_per_kwh - 1)`; `on_grid_edge = bool(on_grid_edge(table, pick))`.
   - When `least_cost` raises `ValueError`, return the same keys with `pv_kwp`, `battery_kwh`, `battery_kw`,
     `lcoe_usd_per_kwh` and `change_pct` set to None, `on_grid_edge` False and `hours` still given.

   ```
   def capex_break_even(points, costs, co2_kg_per_l, unserved_max_frac) -> dict
   ```

   - `points` is a non-empty list of `GridPoint` with at least one diesel only point (design `pv_kwp == 0.0` and
     `battery_kwh == 0.0`).
   - `L0` is the `lcoe_usd_per_kwh` of the first diesel only point under `costs`.
   - Let `c0 = dataclasses.replace(costs, pv_capex_usd_per_kwp=0.0, battery_capex_usd_per_kwh=0.0,
     battery_power_capex_usd_per_kw=0.0)`. For every point that is not diesel only and whose `unserved_frac` is at
     most `unserved_max_frac`: `a` is its LCOE under `c0`, `b` its LCOE under `costs` minus `a`. Keep the point when
     `b > 0` and take `k = (L0 - a) / b`. The LCOE is a straight line in the capital price scale, so `k` is the scale
     at which that point costs the same as diesel only.
   - `factor` is the largest `k` over the kept points. When no point is kept, or `factor` is at most 0, return
     `{"factor": None, "rise_pct": None, "pv_capex_usd_per_kwp": None, "battery_capex_usd_per_kwh": None}`.
   - Otherwise return `{"factor": factor, "rise_pct": 100 * (factor - 1), "pv_capex_usd_per_kwp": factor *
     costs.pv_capex_usd_per_kwp, "battery_capex_usd_per_kwh": factor * costs.battery_capex_usd_per_kwh}`. All
     floats; `rise_pct` is below 0 when diesel only is already cheaper.

   ```
   def run_stats(result, battery_kwh) -> dict
   ```

   - `result` is a `DispatchResult`; `battery_kwh` is a real number of at least 0.
   - Returns `{"unserved_kwh": float(result.unserved_kwh), "unserved_hours": <int count of rows of result.hourly with
     unserved_kw above 0>, "battery_cycles": float(result.battery_discharge_kwh) / battery_kwh}`, with
     `battery_cycles` None when `battery_kwh` is 0.

   ```
   def engine_hours(diesel_only, design) -> dict
   ```

   - Both are `DispatchResult`. Unit hours are the float sum of the `diesel_units_on` column of `hourly`.
   - Returns `{"diesel_only_unit_hours", "design_unit_hours", "cut_pct"}` with `cut_pct = 100 * (1 - design /
     diesel_only)`, or None when the diesel only unit hours are 0.
6. `firmness.py` still does not import `autosolar.study`.

### autosolar/study.py

1. In `run_study`, inside the firmness block (only when a checks file is given), using the final grids, the final
   `points` and table, the least cost pick `best` and its `DispatchResult`:
   - `battery_peak_*` from `battery_power_use(best_result.hourly, float(best["battery_kw"]))` (`peak_discharge_kw`,
     `peak_charge_kw`, `peak_use_pct`).
   - `capex_break_even_rise_pct`, `capex_break_even_pv_usd_per_kwp`, `capex_break_even_battery_usd_per_kwh` from
     `capex_break_even(points, costs, co2_kg_per_l, unserved_max_frac)` (`rise_pct`, `pv_capex_usd_per_kwp`,
     `battery_capex_usd_per_kwh`).
   - `best_unserved_kwh_yr`, `best_unserved_hours`, `best_battery_cycles_yr` from `run_stats(best_result,
     best_battery_kwh)` (`unserved_kwh`, `unserved_hours`, `battery_cycles`).
   - `engine_hours_diesel_only`, `engine_hours_best`, `engine_hours_cut_pct` from `engine_hours(<result of the diesel
     only point of the final points>, best_result)`.
   - When the checks values hold `battery_duration_h_alt`: the seven `DUR_KEYS` from `duration_case` with the same
     PV series, load, final grids, battery template, fleet, costs, CO2 factor and unserved limit as the main sweep,
     `battery_hours` set to the check value and `main_lcoe_usd_per_kwh` set to the main least cost LCOE.
     `dur_alt_hours` is the check value; each other `dur_alt_<name>` key takes the result value `<name>`.
2. `firm_items(values, checks_raw)`: rows whose key is in `DUR_KEYS` are left out when `checks_raw["values"]` has no
   `battery_duration_h_alt` entry (the `ALT_KEYS` rule stays). `dur_alt_on_grid_edge` is shown like `land_fits`:
   value `bool(val)`, text `yes` or `no`.
3. The sources list gains a `Check input <name>: <note>` line for each name of `OPTIONAL_CHECK_NAMES`, in that order,
   when the file has it and its label is press or paper, after the lines for `CHECK_NAMES`.
4. The main answer, gates, range table and run hash rule do not change.

### autosolar/site.py

`caveats(report)` adds two lines when the firmness items hold `capex_break_even_rise_pct`; without that item the
output is the same as before. The two lines go right after the reserve line, or right after the diesel unit size
line when that line is present, island prices first. Let `R` be the text of `capex_break_even_rise_pct`, `P` the text
of `capex_break_even_pv_usd_per_kwp`, `B` the text of `capex_break_even_battery_usd_per_kwh`, `C` the text of
`engine_hours_cut_pct`, `E` the text of `engine_hours_best` and `D` the text of `engine_hours_diesel_only`.

- Island prices, value of `capex_break_even_rise_pct` None: `Island prices: no design in the grid beats diesel only
  at any PV and battery capital price above zero.`
- Value at least 0: `Island prices: PV and battery capital prices can rise R% (PV to P USD/kWp, battery to B USD/kWh)
  before diesel only is cheaper.`
- Value below 0: `Island prices: diesel only is cheaper now; PV and battery capital prices must fall F% (PV to P
  USD/kWp, battery to B USD/kWh) before a design with PV beats it.` where F is R without its leading minus sign.
- Engine hours, value of `engine_hours_cut_pct` above 0: `Diesel engine hours: the least cost design cuts engine
  hours by C% (E against D unit hours a year), so overhaul and engine replacement costs, left out here, would favour
  it.`
- Otherwise (None or at most 0): `Diesel engine hours: the least cost design runs E unit hours a year against D for
  diesel only; overhaul and engine replacement costs are left out.`

Update the docstring to say five to eight lines.

## Done when

- `tests/test_more_checks.py` passes, and every other test passes, including the old tests the orchestrator updated
  for this spec: in `tests/test_firmness.py` the spec count (60), the index of `total_cost_usd` (59),
  `OUT_OF_SCOPE` (9 lines), `FIRM_CHECK_LABEL`, the default checks file keys and the 60 markdown lines; in
  `tests/test_diesel_size.py` the optional names, the row after the diesel unit size rows, the row counts without
  the optional checks and the caveat counts; in `tests/test_site_polish.py` the eight caveat lines.
- `tools/check_text.py` passes on the three edited files; they stay ASCII.
- Run the T15 tests and then the full suite inside the sandbox before you finish (see AGENTS.md).

## Review rule (written before the build and before any new review)

After the build the orchestrator runs one new live study (same question, same sourcing file, cached weather and
cached question parse, so no new model call is expected) and one Wonder review with the same paper check
(paper-20261028T035325-b646fb). One review only; no reruns to shop for a better result. The four target topics are
matched with these case-insensitive regular expressions on each point's text:

- T3 battery power: `battery power|duration|power rating|charge power|discharge power|c-rate|kw of battery`
- T4 island prices: `shipping|logistic|epc|delivered cost|labou?r|island premium|construction|capital price`
- T8 diesel overhaul: `overhaul|engine hours|sunk|diesel capital|capacity.retention|engine replacement`
- T9 load not served and wear: `unserved|reliab|loss of load|capacity.fade|degradation|ageing|aging|augmentation|cycles`

For each topic the outcome is one of: not raised (no point matches), raised and marked addressed (every matching
point has a non-null `addressed_in`), or raised and open (any matching point has `addressed_in` null). The result
section lists every point of the new review with its `addressed_in`, gives the total open count, and names any new
open points. The open count is a reader's list of questions, not a score: two reviews of a near identical report
gave 3 and 6 open points. Expected before the run: T9 may stay open, because PV degradation and battery capacity fade
are still not modelled.

## Test check by the orchestrator

- Reference build in scratch (the changes above applied to a copy of HEAD 5e5c95b): all 104 tests in
  `tests/test_more_checks.py` pass; the full suite passes 1,169 of 1,169 (1,065 old, some of them updated, plus 104
  new).
- 42 planted faults, each caught: the duration check not optional; an optional value of zero, a bool or not finite
  accepted; the charge peak from PV only; the charge peak as the sum of the two maxima; the use share from discharge
  only; a zero power rating giving 0 instead of None; the duration ignored; the change given as a share; no feasible
  design raising; a bool duration accepted; the battery power price left out of the capital price scale; designs over
  the unserved limit kept; the smallest scale taken instead of the largest; the rise given as the scale; the battery
  price not scaled; a scale at or below 0 kept; the first point taken as diesel only; hours without unserved load
  counted; cycles counted both ways; engine hours taken as diesel run hours; the cut sign flipped; the overhaul line
  missing; a title swapped; the wrong decimals; the check label lost; the duration rows kept without the check; the
  edge flag shown as a number; battery power use on kWh; cycles on kW; engine hours of the design against itself;
  the study passing the main duration; the study comparing with a fixed LCOE; no source line for the duration check;
  the study passing no unserved limit to the price check; the engine line before the island line; the minus sign kept
  in a fall; a zero rise read as a fall; a zero cut read as a cut; the two new lines always present; and the diesel
  unit size line dropped when the new lines are added.
- The first run of the planted faults missed one (the study passing an unserved limit of 1 to the price check),
  because on the test weather every design already meets the limit. A test that records the arguments the study
  passes was added; it catches that fault, and the reference still passes it.
