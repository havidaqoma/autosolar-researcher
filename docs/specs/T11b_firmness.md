# T11b: how firm is the answer (near ties, reserve case, land, the paper's size, true cost, scope)

Status: spec by the orchestrator. Builder writes the new file `autosolar/firmness.py` and edits
`autosolar/study.py` only. T09b and T10 stay in force except where this spec changes them. Needs T11a
(`DieselFleet.must_run_units`).

## Why

The report gives one least cost design as if it were exact. An energy engineer would ask six things the study can
already answer from its own numbers:

1. How many other designs cost almost the same? (8 designs are within 1% of the least LCOE in study
   ff628b57b3c357b1, from 6,750 to 8,250 kWp, computed.)
2. What if a diesel unit must run in every hour as a reserve? (T11a.)
3. Does the PV fit the land PLN set aside? (About 9 ha, press.)
4. What does the published design size give? (Hiron 2021: 3,889 modules of 320 Wp, paper.)
5. What did the study really cost, including the sourcing run that fed it?
6. What does the study not cover?

## 1. Check inputs file (written by the orchestrator)

`config/study_checks.json`, schema `autosolar.checks/1`, the same entry shape as the inputs file:
`{"schema": "autosolar.checks/1", "values": {name: {"value", "unit", "label", "note"}}}`.

`CHECK_NAMES = ("site_land_ha", "pv_mwdc_per_ha", "reference_pv_kwp", "diesel_must_run_units", "near_tie_frac")`

## 2. autosolar/firmness.py (new)

Imports allowed: the standard library, numpy, pandas, `autosolar.dispatch`, `autosolar.econ`, `autosolar.sweep`.
It must not import `autosolar.study`.

Constants:

- `CHECKS_SCHEMA = "autosolar.checks/1"`
- `CHECK_NAMES` as above.
- `LABELS`: the same tuple as `autosolar.study.LABELS` (copied, not imported).
- `OUT_OF_SCOPE`: a tuple of exactly these 8 strings, in this order:
  1. `"Grid stability: frequency and voltage control, grid forming inverters and protection for hours with no diesel running"`
  2. `"Land ownership, permits and the environmental review"`
  3. `"Site layout, shading, soil and access for construction"`
  4. `"Shipping to the island, local labour and construction time"`
  5. `"Financing terms, tariffs, subsidies and who pays"`
  6. `"Demand growth beyond the growth case, and new loads such as electric boats"`
  7. `"Battery ageing beyond the replacement rule, and salt air corrosion"`
  8. `"Diesel price risk beyond the sensitivity table"`
- `FIRM_SPECS`: a tuple of `(key, unit, label, decimals)` with exactly these 30 rows, in this order. A label of
  `"check"` means: take the label of the named check entry (column 5). Columns: key, unit, label, decimals, check.

| key | unit | label | decimals | check entry for the label |
|---|---|---|---|---|
| near_tie_pct | % | check | 1 | near_tie_frac |
| near_tie_count | designs | computed | 0 | |
| near_tie_pv_kwp_min | kWp | computed | 0 | |
| near_tie_pv_kwp_max | kWp | computed | 0 | |
| near_tie_battery_kwh_min | kWh | computed | 0 | |
| near_tie_battery_kwh_max | kWh | computed | 0 | |
| best_diesel_run_hours | h/yr | computed | 0 | |
| best_diesel_starts | starts/yr | computed | 0 | |
| best_no_diesel_hours | h/yr | computed | 0 | |
| reserve_units | units | check | 0 | diesel_must_run_units |
| reserve_pv_kwp | kWp | computed | 0 | |
| reserve_battery_kwh | kWh | computed | 0 | |
| reserve_lcoe_usd_per_kwh | USD/kWh | computed | 3 | |
| reserve_renewable_pct | % | computed | 1 | |
| reserve_fuel_l_yr | L/yr | computed | 0 | |
| reserve_main_design_lcoe_usd_per_kwh | USD/kWh | computed | 3 | |
| land_site_ha | ha | check | 1 | site_land_ha |
| land_pv_mwdc_per_ha | MWdc/ha | check | 2 | pv_mwdc_per_ha |
| land_need_ha | ha | computed | 1 | |
| land_max_pv_kwp | kWp | computed | 0 | |
| land_fits | (empty string) | computed | 0 | |
| land_pv_kwp | kWp | computed | 0 | |
| land_battery_kwh | kWh | computed | 0 | |
| land_lcoe_usd_per_kwh | USD/kWh | computed | 3 | |
| reference_pv_kwp | kWp | check | 0 | reference_pv_kwp |
| reference_lcoe_usd_per_kwh | USD/kWh | computed | 3 | |
| reference_renewable_pct | % | computed | 1 | |
| reference_fuel_saved_l_yr | L/yr | computed | 0 | |
| sourcing_cost_usd | USD | computed | 5 | |
| total_cost_usd | USD | computed | 5 | |

  In code, `FIRM_SPECS` holds 4-tuples `(key, unit, label, decimals)` where label is `"check"` for the 5 rows that
  name a check entry, and `FIRM_CHECK_LABEL = {"near_tie_pct": "near_tie_frac", "reserve_units":
  "diesel_must_run_units", "land_site_ha": "site_land_ha", "land_pv_mwdc_per_ha": "pv_mwdc_per_ha",
  "reference_pv_kwp": "reference_pv_kwp"}`.
- `FIRM_TITLES`: a dict with one title per key, no digits in any title:

| key | title |
|---|---|
| near_tie_pct | Near tie: share above the least LCOE that still counts as a tie |
| near_tie_count | Near tie: designs within that share |
| near_tie_pv_kwp_min | Near tie: smallest PV size |
| near_tie_pv_kwp_max | Near tie: largest PV size |
| near_tie_battery_kwh_min | Near tie: smallest battery |
| near_tie_battery_kwh_max | Near tie: largest battery |
| best_diesel_run_hours | Least cost design: hours the diesel runs |
| best_diesel_starts | Least cost design: diesel starts |
| best_no_diesel_hours | Least cost design: hours the battery and PV hold the grid with no diesel |
| reserve_units | Reserve case: diesel units that run in every hour |
| reserve_pv_kwp | Reserve case: least cost PV size |
| reserve_battery_kwh | Reserve case: least cost battery |
| reserve_lcoe_usd_per_kwh | Reserve case: least cost LCOE |
| reserve_renewable_pct | Reserve case: renewable share |
| reserve_fuel_l_yr | Reserve case: diesel fuel |
| reserve_main_design_lcoe_usd_per_kwh | Reserve case: LCOE of the main design |
| land_site_ha | Land: area set aside for the PV plant |
| land_pv_mwdc_per_ha | Land: PV per hectare |
| land_need_ha | Land: area the main design needs |
| land_max_pv_kwp | Land: largest PV that fits |
| land_fits | Land: main design fits |
| land_pv_kwp | Land: least cost PV size that fits |
| land_battery_kwh | Land: battery with that PV |
| land_lcoe_usd_per_kwh | Land: LCOE of that design |
| reference_pv_kwp | Published design size: PV only |
| reference_lcoe_usd_per_kwh | Published design size: LCOE |
| reference_renewable_pct | Published design size: renewable share |
| reference_fuel_saved_l_yr | Published design size: diesel fuel saved |
| sourcing_cost_usd | Cost of the web search that sourced the inputs |
| total_cost_usd | Total model API cost behind this study |

Functions (every `ValueError` message must name the field or say what is wrong):

### load_checks(path) -> tuple[dict, dict]

- Reads JSON (utf-8). Top level must be a dict with `schema == CHECKS_SCHEMA`, and `values` a dict whose keys are
  exactly `CHECK_NAMES` (any order). Otherwise `ValueError`.
- Each entry must be a dict with exactly the keys `value`, `unit`, `label`, `note`; `unit` a non-empty str;
  `label` in `LABELS`; `note` a str. Otherwise `ValueError`.
- `diesel_must_run_units`: `type(value) is int` and `value >= 1`.
- The other 4: an int or float, never a bool, finite, and above 0. `near_tie_frac` also at most 0.2.
- Returns `(values, raw)`: values by name (the int stays an int, the others become float), and the parsed file.

### near_tie_band(table, unserved_max_frac, tie_frac) -> dict

- `feas` = rows with `unserved_frac <= unserved_max_frac`. No rows: `ValueError("no feasible row ...")`.
- `low` = the least `lcoe_usd_per_kwh` in `feas`. `band` = rows of `feas` with
  `lcoe_usd_per_kwh <= low * (1 + tie_frac)`.
- Returns `{"count": int, "pv_kwp_min": float, "pv_kwp_max": float, "battery_kwh_min": float,
  "battery_kwh_max": float, "lcoe_max_usd_per_kwh": float}` over `band`.

### land_check(table, unserved_max_frac, main_pv_kwp, land_ha, pv_mwdc_per_ha) -> dict

- `need_ha = main_pv_kwp / (1000 * pv_mwdc_per_ha)`; `max_pv_kwp = land_ha * pv_mwdc_per_ha * 1000`.
- `fits = main_pv_kwp <= max_pv_kwp * (1 + 1e-9)` (a Python bool).
- `within` = rows with `pv_kwp <= max_pv_kwp * (1 + 1e-9)`. The pick is `autosolar.sweep.least_cost(within,
  unserved_max_frac)`. When `within` is empty or `least_cost` raises `ValueError`, the pick values are None.
- Returns `{"need_ha", "max_pv_kwp", "fits", "pv_kwp", "battery_kwh", "lcoe_usd_per_kwh"}` (floats or None,
  `fits` a bool).

### reserve_case(pv_kw_per_kwp, load_kw, pv_grid, battery_grid, *, battery_hours, battery_template, diesel, must_run_units, costs, co2_kg_per_l, unserved_max_frac, main_pv_kwp, main_battery_kwh) -> dict

- `fleet = dataclasses.replace(diesel, must_run_units=must_run_units)` (the caller's `diesel` is not changed).
- `points = dispatch_grid(pv_kw_per_kwp, load_kw, pv_grid, battery_grid, battery_hours=..., battery_template=...,
  diesel=fleet)`, `table = cost_table(points, costs, co2_kg_per_l)`.
- `main_design_lcoe_usd_per_kwh`: the `lcoe_usd_per_kwh` of the row with `pv_kwp == main_pv_kwp` and
  `battery_kwh == main_battery_kwh`. No such row: `ValueError`.
- The pick is `least_cost(table, unserved_max_frac)`. Returns `{"units": int(must_run_units), "pv_kwp", "battery_kwh",
  "lcoe_usd_per_kwh", "renewable_pct" (100 * renewable_fraction_frac), "fuel_l_yr" (fuel_l_per_yr),
  "main_design_lcoe_usd_per_kwh", "on_grid_edge" (sweep.on_grid_edge(table, pick), a bool)}`. When `least_cost`
  raises `ValueError`, the 5 pick values are None and `on_grid_edge` is False.

### reference_design(pv_kw_per_kwp, load_kw, pv_kwp, *, battery_hours, battery_template, diesel, costs, co2_kg_per_l) -> dict

- PV only at `pv_kwp` (must be a real number above 0, not a bool, else `ValueError`):
  `points = dispatch_grid(pv_kw_per_kwp, load_kw, [0.0, float(pv_kwp)], [0.0], battery_hours=..., battery_template=...,
  diesel=diesel)`, `table = cost_table(points, costs, co2_kg_per_l)`. Row 0 is diesel only, row 1 the PV design.
- Returns `{"pv_kwp": float(pv_kwp), "lcoe_usd_per_kwh", "renewable_pct" (100 * frac), "fuel_l_yr",
  "fuel_saved_l_yr" (row 0 fuel minus row 1 fuel), "unserved_frac"}` from those rows.

### study_cost(api_cost_usd, sourcing_rows) -> dict

- `sourcing_rows` None: sourcing cost 0.0. Else the sum of `row.search_cost_usd` over the rows.
- Returns `{"sourcing_cost_usd": float, "total_cost_usd": api_cost_usd + sourcing}`.

## 3. autosolar/study.py

- `run_study` gains a last keyword `checks_path: object = None`.
- When `checks_path` is None: nothing changes. No new report content, the run hash rule is unchanged, and
  `report["firmness"]` is None.
- When it is given: `load_checks(checks_path)` runs before the cached request is read (a bad file raises before any
  call). The run hash payload gains the key `"checks"` with the raw checks file (only then, so old run hashes stay
  the same): `_run_hash` takes it as a last optional argument.
- After the facts are built, with `table`, `best`, `best_result`, `pv_grid`, `battery_grid` (after any widening),
  `basis_kw`, `paper_load`, `battery`, `diesel`, `costs`, the study computes:
  - `band = near_tie_band(table, unserved_max_frac, near_tie_frac)`
  - `land = land_check(table, unserved_max_frac, best_pv_kwp, site_land_ha, pv_mwdc_per_ha)`
  - `reserve = reserve_case(basis_kw, paper_load, pv_grid, battery_grid, ..., must_run_units=diesel_must_run_units,
    ..., main_pv_kwp=best_pv_kwp, main_battery_kwh=best_battery_kwh)`
  - `ref = reference_design(basis_kw, paper_load, reference_pv_kwp, ...)`
  - `cost = study_cost(float(req.cost_usd), s_rows)`
  - from the main design: `best_diesel_run_hours = best["diesel_run_hours"]`, `best_diesel_starts =
    best["diesel_starts"]`, `best_no_diesel_hours = len(best_result.hourly) - best_diesel_run_hours`.
- Values per key: `near_tie_pct` = 100 * near_tie_frac; the band, reserve, land and reference keys map to the dict
  entries of the same meaning; `reserve_units` = diesel_must_run_units; `land_site_ha` and `land_pv_mwdc_per_ha` and
  `reference_pv_kwp` are the check values.
- New public function `firm_items(values: dict, checks_raw: dict) -> list[dict]` in `study.py`: `values` holds one
  value per `FIRM_SPECS` key. It returns one item per `FIRM_SPECS` row, in order:
  `{"key", "title", "value", "unit", "label", "text"}`. `label` is resolved through `FIRM_CHECK_LABEL` and
  `checks_raw` (never `"check"`). `text` is `fmt_number(float(value), decimals)`, except: a None value keeps value
  None and gets text `"none"`; `land_fits` keeps the bool as value and gets text `"yes"` or `"no"`.
- `report["firmness"] = {"items": firm_items(...), "out_of_scope": list(OUT_OF_SCOPE), "checks": raw_checks}`.
- Sources: for each check entry whose label is `press` or `paper`, in `CHECK_NAMES` order, the line
  `"Check input " + name + ": " + note` is added to `report["sources"]` after the existing lines.

## 4. render_markdown

When `report.get("firmness")` is None (or missing): the output does not change.

Otherwise two sections are added:

- `## How firm is the answer`, right after the `## Answer` list and before `## Weather sources`: a blank line, then
  one line per item, `"- " + title + ": " + text + " " + unit + " (" + label + ")"`; when unit is the empty string
  the line is `"- " + title + ": " + text + " (" + label + ")"`. All parts pass through the same cleaning as the
  answer lines.
- `## Not covered by this study`, right before `## Sources`: a blank line, then `"- " + line` for each
  `out_of_scope` line.

Every number in the markdown must still appear in the report (the existing check).

## Done when

- `tests/test_firmness.py` passes, and every test that passed before still passes.
- `tools/check_text.py` passes on both files; both stay ASCII; no import outside the list above.

## Test check by the orchestrator

- Reference build in scratch (the spec applied to a copy of the product after T11a): all 52 tests in
  `tests/test_firmness.py` pass; the full suite passes 877 of 877 (825 old plus 52 new).
- 27 planted faults, each caught: band without the feasibility filter; tie share doubled; band count as a float;
  land need without the 1000; fits inverted; land pick limited by the main size; reserve without the must run
  units; main design LCOE taken from the pick; reserve share not in percent; fuel saved with the wrong sign;
  reference rows swapped; sourcing cost left out of the total; tie share limit 0.5; float units accepted; no label
  check; zero accepted; run hash without the checks; check labels fixed to assumed; fits text reversed; other text
  for none; unit always added; scope section after the sources; assumed check notes added to the sources; a fixed
  8,760 hour year; checks dropped from the report; near tie share not in percent; reserve case on a cut grid.
