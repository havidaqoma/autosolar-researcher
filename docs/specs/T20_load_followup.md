# T20: what if the chart is right? The study at the lower load the chart implies

Status: spec by the orchestrator. Builder writes the new module `autosolar/load_followup.py`, the new tool
`tools/load_followup.py`, and edits `autosolar/site.py` and `tools/make_site.py` only. All earlier specs stay in
force. The orchestrator has written `tests/test_load_followup.py`.

## Why

T18b read the paper's own load chart (Figure 7 of Hiron et al. 2021) with SAM 3.1. The study's load, scaled back to
the chart's year, came out 30.4% above the chart's December 2018 curve, outside the +/-20% demand swing of the
sensitivity table. The study kept its load (changing an input after seeing the answer would be shopping for
numbers), so the page shows the warning but not its effect. Judges asked the obvious next question: does solar plus
battery still beat diesel if the chart is right? This task answers it with the engine, as a follow-up that is
labelled post hoc and never changes the study itself.

## 1. autosolar/load_followup.py

No network, no file writes. Imports `cost_table`, `dispatch_grid` and `least_cost` by name from `autosolar.sweep`.
Constants: `LOAD_FOLLOWUP_SCHEMA = "autosolar.load_followup/1"`, `REL_TOL = 1e-9`, and

`NOTE = "Added after the load check result (post hoc). The study's own answer and inputs are unchanged."`

### followup_cases(figure_check, swing_frac) -> list[dict]

- `figure_check` must be a dict whose `comparison` is a dict with `verdict` `"inside band"` or `"outside band"`,
  `ratio` and `mean_ratio` finite reals above 0 (`bool` refused), `basis_series` a non-empty string and `series` a
  non-empty list. Else `ValueError` with "comparison" in the message.
- `swing_frac`: finite real, above 0 and below 1, `bool` refused. Else `ValueError`.
- Returns exactly four dicts, in this order, each with exactly the keys `key`, `scale_frac`, `post_hoc`:
  1. `{"key": "chart_basis", "scale_frac": 1 / ratio, "post_hoc": True}`
  2. `{"key": "chart_mean", "scale_frac": 1 / mean_ratio, "post_hoc": True}`
  3. `{"key": "swing_low", "scale_frac": 1 - swing_frac, "post_hoc": False}`
  4. `{"key": "swing_high", "scale_frac": 1 + swing_frac, "post_hoc": False}`

Both chart cases are fixed here, before any number is computed: the basis day is the curve the paper says its load
comes from, and the mean covers all days in the chart. No other scale is added later.

### load_followup(pv_ac_kw_per_kwp, load_kw, pv_kwp_grid, battery_kwh_grid, *, battery_hours, battery_template, diesel, costs, co2_kg_per_l, unserved_max_frac, main_pv_kwp, main_battery_kwh, scales) -> list[dict]

- `scales`: a non-empty list or tuple of finite reals above 0 (`bool` refused). Else `ValueError`.
- Both grids must hold 0.0, and `main_pv_kwp` must be in the PV grid and `main_battery_kwh` in the battery grid
  (compared as floats). Else `ValueError`.
- For each scale `s`, in order: `points = dispatch_grid(pv_ac_kw_per_kwp, load_kw * s, pv_kwp_grid,
  battery_kwh_grid, battery_hours=..., battery_template=..., diesel=...)`, then
  `table = cost_table(points, costs, co2_kg_per_l)`. In the table, the diesel only row is the first row with
  `pv_kwp == 0` and `battery_kwh == 0`; the main row is the first row with the main sizes;
  `best = least_cost(table, unserved_max_frac)`. When `least_cost` raises `ValueError` (no feasible row), the four
  `best_*` values and `saving_pct` are None.
- One dict per scale with exactly these keys:
  - `scale_frac`: `s` as float.
  - `demand_kwh_yr`: `float((load_kw * s).sum())` (hourly kW summed over the year).
  - `diesel_only_lcoe_usd_per_kwh`, `diesel_only_unserved_frac`: from the diesel only row.
  - `best_pv_kwp`, `best_battery_kwh`, `best_lcoe_usd_per_kwh`: from `best`.
  - `best_renewable_pct`: `100 * best["renewable_fraction_frac"]`.
  - `saving_pct`: `100 * (1 - best_lcoe / diesel_only_lcoe)`.
  - `main_lcoe_usd_per_kwh`, `main_unserved_frac`: from the main row.
  - `main_saving_pct`: `100 * (1 - main_lcoe / diesel_only_lcoe)`.
  All numbers are Python floats. `load_kw` and the grids are never changed.

### check_reproduction(report, base_row, low_row, high_row) -> list[str]

The follow-up is trusted only if the engine, given the study's own inputs, gives back the study's own numbers first.
Returns a list of messages, empty when everything matches; each message names the field that differs. Two floats
match when `abs(a - b) <= REL_TOL * max(1.0, abs(b))`; sizes must be equal as floats.

- `base_row` (scale 1.0) against `report["facts"][k]["value"]`: `best_pv_kwp`, `best_battery_kwh`,
  `best_lcoe_usd_per_kwh`, and `diesel_only_lcoe_usd_per_kwh`.
- `low_row` and `high_row` against the `report["sensitivity_table"]` row with `input == "demand"` and `factor`
  equal to the row's `scale_frac` (within 1e-12): `least_cost_pv_kwp` with `best_pv_kwp`,
  `least_cost_battery_kwh` with `best_battery_kwh`, `least_cost_lcoe_usd_per_kwh` with `best_lcoe_usd_per_kwh`,
  and `base_design_lcoe_usd_per_kwh` with `main_lcoe_usd_per_kwh`. A missing demand row gives one message with
  "demand" in it.

### followup_doc(report, figure_check, *, figure_check_id, run_id, base_row, cases, case_rows, errors, wall_s) -> dict

- `cases`: the list from `followup_cases`; `case_rows`: one row per case, same order and length (else
  `ValueError`); `errors`: the list from `check_reproduction`.
- Returns a JSON-able dict with exactly: `schema` (`LOAD_FOLLOWUP_SCHEMA`), `run_id`, `study_run_hash`
  (`report["run_hash"]`), `figure_check_run_id`, `basis_series` and `verdict` (from the comparison), `designs`
  (`len(report["grid"]["pv_kwp"]) * len(report["grid"]["battery_kwh"])`), `base` (a copy of `base_row`), `cases`
  (per case: a new dict with the case keys first, then the row keys), `reproduced` (`len(errors) == 0`),
  `reproduction_errors` (a list copy), `wall_s` (float) and `note` (`NOTE`).

## 2. tools/load_followup.py

`python tools/load_followup.py --run <study hash> --figure-check <figure check run id>`

- Optional: `--runs` (default `runs/studies`), `--figure-checks` (default `runs/figure_checks`), `--out` (default
  `runs/load_followups`), `--weather-cache` (default `runs/weather_cache`). Paths are relative to the repo root.
- Constants: `CACHE_ONLY_EMAIL = "cache-only@invalid"` (holds "@" for the weather input check and is never sent
  anywhere). `no_network_fetchers()` returns a `WeatherFetchers` whose six callables all raise `RuntimeError` with
  "no network" in the message.
- `main(argv=None) -> int`:
  1. Reads `<runs>/<run>/report.json` and `<runs>/<run>/inputs.json`, and
     `<figure-checks>/<figure-check>/figure_check.json`. A missing file prints `not found: <path>` and returns 2.
  2. Values come from `autosolar.study.load_inputs(<inputs.json>)`; cost, battery and diesel objects from
     `autosolar.study._design_objects(values)`.
  3. Weather: `build_weather_cases(lat, lon, CACHE_ONLY_EMAIL, cached_fetchers(no_network_fetchers(),
     <weather-cache>))` with `lat, lon = report["weather_coords_deg"]`. The PV series is
     `simulate_pv(weather.cases[weather.basis], lat, lon, PVDesign(), 1.0).hourly["ac_kw"]`; the load is
     `build_demand_cases(weather.cases[weather.basis].index)["paper"].load_kw`. Same calls as `run_study`.
  4. Grids: `report["grid"]["pv_kwp"]` and `report["grid"]["battery_kwh"]` (the study's final grid). Main sizes:
     the facts `best_pv_kwp` and `best_battery_kwh`.
  5. `cases = followup_cases(figure_check, values["swing_frac"])`; rows for the scales `[1.0]` plus the four case
     scales, in one `load_followup` call; `errors = check_reproduction(report, rows[0], <swing_low row>,
     <swing_high row>)`.
  6. `run_id = "followup-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid4 hex[:6]`; writes
     `<out>/<run_id>/load_followup.json` (ASCII, indent 2) from `followup_doc`, always, so a failed reproduction is
     kept for audit.
  7. Prints the run id, one line per case (key, scale, diesel only LCOE, best design, best LCOE, saving) and
     `reproduced yes` or `reproduced NO` with the messages. Returns 0 when reproduced, else 3.
- Makes no network call and no model call.

## 3. autosolar/site.py

`render_study_html(report, table, *, paper_check=None, review=None, figure_check=None, load_followup=None)`.
With `load_followup=None` the page is byte for byte what it was before this task.

When `load_followup` is given:

- `figure_check` must also be given, `load_followup["reproduced"]` must be `True`, and
  `load_followup["study_run_hash"]` must equal `report["run_hash"]`. Else `ValueError`. The site never shows a
  follow-up that did not first give back the study's own numbers.
- Inside the figure check section, just before its closing `</section>`, add `_load_followup_html(load_followup)`:
  - `<h3>If the chart is right</h3>`
  - A paragraph: `"Added after the load check result (post hoc), so the answer above is unchanged. The engine
    re-ran all " + designs + " designs at each load below (computed). Before that, it gave back this study's own
    answer and the two demand rows of What moves the cost, to within one part in a billion."` (`designs` formatted
    with `fmt(..., 0)`.)
  - A headline paragraph for the `chart_basis` case, where `pct = fmt(100 * (1 - scale_frac), 1)`:
    - when `saving_pct` is not None and above 0: `"If the load is what the " + basis_series + " curve implies ("
      + pct + "% lower), the least cost design is " + pv + " kWp of PV and " + bat + " kWh of battery at " + best
      + " USD/kWh against " + d0 + " for diesel only: " + saving + "% less (computed)."`
    - otherwise: `"If the load is what the " + basis_series + " curve implies (" + pct + "% lower), no design with
      PV or battery beats diesel only at " + d0 + " USD/kWh (computed)."`
    - (pv, bat with `fmt(..., 0)`; best, d0 with `fmt(..., 3)`; saving with `fmt(..., 1)`; if `scale_frac` is
      above 1 the word "lower" becomes "higher" and pct uses the absolute value.)
  - A table (with `_table`) with the headers `["Load case", "Load (kWh/yr)", "Diesel only (USD/kWh)",
    "Least cost design", "Its cost (USD/kWh)", "Below diesel only", "Main design (USD/kWh)"]` and one row per case
    in order. Load case names: `chart_basis` -> `"Chart day: " + basis_series + " (post hoc)"`, `chart_mean` ->
    `"Chart, mean of all days (post hoc)"`, `swing_low` -> `"Demand -" + p + "% (sensitivity row)"`, `swing_high` ->
    `"Demand +" + p + "% (sensitivity row)"` with `p = fmt(100 * abs(scale_frac - 1), 0)`. Cells: load
    `fmt(..., 0)`; LCOEs `fmt(..., 3)`; design `pv + " kWp + " + bat + " kWh"` or `"none feasible"` when
    `best_pv_kwp` is None; its cost `""` when None; saving `fmt(..., 1) + "%"` or `""` when None.
  - A last paragraph: `"Main design: the study's answer, " + pv + " kWp + " + bat + " kWh, at each load. Other inputs
    stay as in the study."` with the sizes from `load_followup["base"]`.
- All text through `esc`; ASCII only.

## 4. tools/make_site.py

A gallery entry may hold `"load_followup": "<follow-up run id>"`. When present, read
`runs/load_followups/<id>/load_followup.json`, copy it to `docs/site/data/<run>/load_followup.json`, and pass it as
`load_followup=` to `render_study_html`. Entries without the key are built as before.

## Acceptance

`tests/test_load_followup.py` passes, and the full suite still passes. Muse must not edit specs, tests or config.

## Test record (added by the orchestrator after the build)

- The tests were red before the code (module not written). They were not run against a reference build first.
- Muse Code build: 63 of 63 tests pass (1,046 s, USD 0.035, measured, `ledger/build_usage.jsonl`).
- Planted faults in `autosolar/load_followup.py`, `autosolar/site.py` and `tools/load_followup.py`: 21 of 22
  caught. The one that got through (a grid without 0 kWp allowed) is stopped by `dispatch_grid` itself, which
  refuses a grid whose first value is not 0.
