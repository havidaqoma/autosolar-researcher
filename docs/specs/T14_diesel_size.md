# T14: diesel unit size check (a second fleet size when the sources disagree)

Status: spec by the orchestrator. Builder edits `autosolar/firmness.py`, `autosolar/study.py` and `autosolar/site.py`
only. T11b, T13 and T13b stay in force except where this spec changes them. The orchestrator has already added the
new check input to `config/study_checks.json` and updated the old tests listed at the end.

## Why

The Karimunjawa inputs take the diesel fleet from Hiron et al. 2021. The paper prints two fleet sizes: 2 x 2.7 MW on
p1 and in Table 1, and 2 x 1.8 MW on p7 (the field section, with the feeder voltages). The study uses 1.8 MW units. A
scratch rerun of study 59eba198a2af900c with 2.7 MW units (same weather, load, grid and costs) moved the diesel only
cost from 0.354 to 0.410 USD/kWh, the least cost design from 7,250 kWp to 7,500 kWp, and the reserve case (one unit
always on) from 1,500 kWp at 0.336 to 750 kWp at 0.400 USD/kWh (computed). Bigger units burn more fuel at low load
and set a higher floor, so the size matters. When the sources disagree, the study must report both answers, not pick
one in silence.

## Changes

### autosolar/firmness.py

1. New constant `OPTIONAL_CHECK_NAMES = ("diesel_unit_kw_alt",)`.
2. `load_checks`: the keys of `values` must hold every name in `CHECK_NAMES` and may also hold names from
   `OPTIONAL_CHECK_NAMES`; any other key, or a missing required key, raises `ValueError` as before. An optional entry
   is checked like the float checks (dict with exactly value, unit, label, note; non-empty unit; label in `LABELS`;
   note a string; value a finite int or float that is not a bool and is above 0; int becomes float). The returned
   values dict holds `diesel_unit_kw_alt` only when the file has it.
3. New `ALT_KEYS` tuple, in this order: `alt_diesel_unit_kw`, `alt_diesel_only_lcoe_usd_per_kwh`, `alt_pv_kwp`,
   `alt_battery_kwh`, `alt_lcoe_usd_per_kwh`, `alt_saving_pct`, `alt_on_grid_edge`,
   `alt_reserve_main_design_lcoe_usd_per_kwh`, `alt_reserve_pv_kwp`, `alt_reserve_battery_kwh`,
   `alt_reserve_lcoe_usd_per_kwh`.
4. `FIRM_SPECS` gains eleven rows, in the `ALT_KEYS` order, placed right after `reference_fuel_saved_l_yr` and before
   `sourcing_cost_usd`:

   | key | unit | label | decimals |
   |---|---|---|---|
   | alt_diesel_unit_kw | kW | check | 0 |
   | alt_diesel_only_lcoe_usd_per_kwh | USD/kWh | computed | 3 |
   | alt_pv_kwp | kWp | computed | 0 |
   | alt_battery_kwh | kWh | computed | 0 |
   | alt_lcoe_usd_per_kwh | USD/kWh | computed | 3 |
   | alt_saving_pct | % | computed | 1 |
   | alt_on_grid_edge | (empty string) | computed | 0 |
   | alt_reserve_main_design_lcoe_usd_per_kwh | USD/kWh | computed | 3 |
   | alt_reserve_pv_kwp | kWp | computed | 0 |
   | alt_reserve_battery_kwh | kWh | computed | 0 |
   | alt_reserve_lcoe_usd_per_kwh | USD/kWh | computed | 3 |

   `FIRM_CHECK_LABEL` gains `"alt_diesel_unit_kw": "diesel_unit_kw_alt"`. `FIRM_TITLES` gains:

   - alt_diesel_unit_kw: `Diesel unit size check: other unit rating in the sources`
   - alt_diesel_only_lcoe_usd_per_kwh: `Diesel unit size check: diesel only LCOE`
   - alt_pv_kwp: `Diesel unit size check: least cost PV size`
   - alt_battery_kwh: `Diesel unit size check: least cost battery`
   - alt_lcoe_usd_per_kwh: `Diesel unit size check: least cost LCOE`
   - alt_saving_pct: `Diesel unit size check: saving against diesel only`
   - alt_on_grid_edge: `Diesel unit size check: least cost design on the grid edge`
   - alt_reserve_main_design_lcoe_usd_per_kwh: `Diesel unit size check: that design with the reserve units always on`
   - alt_reserve_pv_kwp: `Diesel unit size check: reserve case PV size`
   - alt_reserve_battery_kwh: `Diesel unit size check: reserve case battery`
   - alt_reserve_lcoe_usd_per_kwh: `Diesel unit size check: reserve case LCOE`
5. New function:

   ```
   def diesel_size_case(pv_kw_per_kwp, load_kw, pv_grid, battery_grid, *, battery_hours, battery_template, diesel,
                        unit_kw, must_run_units, costs, co2_kg_per_l, unserved_max_frac) -> dict
   ```

   - `unit_kw` must be a real number (not a bool), finite and above 0, else `ValueError`.
   - The fleet is `dataclasses.replace(diesel, unit_kw=float(unit_kw))`; every other fleet field is kept.
   - Run `dispatch_grid` on the given grids with that fleet, then `cost_table(points, costs, co2_kg_per_l)`.
   - The table must hold the diesel only row (`pv_kwp == 0.0` and `battery_kwh == 0.0`), else `ValueError`.
   - Pick with `least_cost(table, unserved_max_frac)`. Then call `reserve_case` with the same series, grids, battery
     template, battery hours, costs, CO2 factor and unserved limit, `diesel` set to the new fleet,
     `must_run_units=must_run_units`, and the pick as the main design.
   - Return `{"unit_kw", "diesel_only_lcoe_usd_per_kwh", "pv_kwp", "battery_kwh", "lcoe_usd_per_kwh", "saving_pct",
     "on_grid_edge", "reserve_main_design_lcoe_usd_per_kwh", "reserve_pv_kwp", "reserve_battery_kwh",
     "reserve_lcoe_usd_per_kwh"}` with floats for sizes and money, `saving_pct = 100 * (1 - lcoe /
     diesel_only_lcoe)`, `on_grid_edge = bool(on_grid_edge(table, pick))`, and the four reserve values taken from the
     `reserve_case` result (`main_design_lcoe_usd_per_kwh`, `pv_kwp`, `battery_kwh`, `lcoe_usd_per_kwh`; the last
     three may be None when no reserve design meets the limit).
   - When `least_cost` raises `ValueError` (no design meets the unserved limit), do not call `reserve_case`; return
     the same keys with `pv_kwp`, `battery_kwh`, `lcoe_usd_per_kwh`, `saving_pct` and the four reserve values set to
     None, `on_grid_edge` False, and the diesel only LCOE still given.
6. `firmness.py` still does not import `autosolar.study`.

### autosolar/study.py

1. In `run_study`, when the checks values hold `diesel_unit_kw_alt`, call `diesel_size_case` with the same PV
   series, load, final grids, battery template, battery hours, fleet, must run units, costs, CO2 factor and unserved
   limit that the reserve case uses, and add the eleven `ALT_KEYS` to the firmness values: `alt_diesel_unit_kw` is
   the check value; each other `alt_<name>` key takes the result value `<name>` (for example `alt_pv_kwp` from
   `pv_kwp`, `alt_reserve_pv_kwp` from `reserve_pv_kwp`). Without the check, nothing new runs.
2. `firm_items(values, checks_raw)`: rows whose key is in `ALT_KEYS` are left out when `checks_raw["values"]` has no
   `diesel_unit_kw_alt` entry, even if `values` holds those keys. Otherwise every row is emitted as before.
   `alt_on_grid_edge` is shown like `land_fits`: value `bool(val)`, text `yes` or `no`.
3. The sources list gains a `Check input <name>: <note>` line for `diesel_unit_kw_alt` when the file has it and its
   label is press or paper, after the lines for `CHECK_NAMES` (same rule as those).
4. The main answer, gates, range table and run hash rule do not change (the hash already covers the checks file).

### autosolar/site.py

`caveats(report)` returns six lines when the firmness items hold `alt_diesel_unit_kw`, five lines otherwise. The new
line goes third, right after the reserve line. With `U` = text of `alt_diesel_unit_kw`, `D` = text of
`alt_diesel_only_lcoe_usd_per_kwh` and `N` = text of `reserve_units`:

- When `alt_lcoe_usd_per_kwh` has value None: `Diesel unit size: with units of U kW instead, diesel only costs D
  USD/kWh and no design in the grid meets the unserved limit.`
- Otherwise the line is `Diesel unit size: with units of U kW instead, diesel only costs D USD/kWh and the least cost
  design is P kWp with B kWh at L USD/kWh (S% below diesel only); if N diesel unit(s) must run in every hour, that
  design would cost M USD/kWh` followed by ` and the least cost design is RP kWp with RB kWh at RL USD/kWh.` or, when
  `alt_reserve_lcoe_usd_per_kwh` has value None, ` and no design in the grid meets the unserved limit.` Here P, B, L,
  S, M, RP, RB, RL are the texts of `alt_pv_kwp`, `alt_battery_kwh`, `alt_lcoe_usd_per_kwh`, `alt_saving_pct`,
  `alt_reserve_main_design_lcoe_usd_per_kwh`, `alt_reserve_pv_kwp`, `alt_reserve_battery_kwh` and
  `alt_reserve_lcoe_usd_per_kwh`.

The other five lines keep their text and order. Update the docstring to say five or six lines.

## Done when

- `tests/test_diesel_size.py` passes, and every other test passes, including the old tests the orchestrator updated
  for this spec: in `tests/test_firmness.py` the spec count (41), the index of `total_cost_usd` (40),
  `FIRM_CHECK_LABEL`, the default checks file keys, the yes or no text of `alt_on_grid_edge`, the four check source
  lines and the 41 markdown lines; in `tests/test_site_polish.py` the six caveat lines.
- `tools/check_text.py` passes on the three edited files; they stay ASCII.

## Test check by the orchestrator

- Reference build in scratch (the changes above applied to a copy of HEAD 50f2908): all tests in
  `tests/test_diesel_size.py` pass; the full suite passes 1,065 of 1,065 (1,019 old, some of them updated, plus 46
  new).
- 25 planted faults, each caught: the optional key rejected; any extra key accepted; the optional value not checked;
  the unit size ignored; the fleet rebuilt with other fields lost; the saving given as a share; no feasible design
  raising; a bool unit accepted; the new rows after the cost rows; the new rows kept without the check; the edge flag
  shown as a number; the study passing the main unit size; the study using part of the grid; no source line; a
  source line for any label; the caveat line placed last; no None branch in the caveat; the caveat line always
  present; the saving missing from the caveat; the reserve run on the main fleet; the reserve units fixed at 1; the
  reserve run on the wrong main design; the reserve values mapped wrong in the study; the study passing the wrong
  must run units; no None branch for the reserve part of the caveat.
- One planted fault was equivalent and is not counted: dropping the diesel only row check changes nothing, because
  `dispatch_grid` already refuses a grid whose first PV or battery size is not 0.
