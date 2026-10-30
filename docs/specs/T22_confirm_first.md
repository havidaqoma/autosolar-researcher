# T22: confirm these first, public field figures, and the hourly files behind each study

Status: spec by the orchestrator. Builder writes the new module `autosolar/engineer_files.py`, the new tool
`tools/engineer_files.py`, and edits `autosolar/site.py` and `tools/make_site.py` only. All earlier specs stay in
force. The orchestrator has written `tests/test_engineer_files.py` and `config/field_notes.json`.

## Why

Engineers who plan PV and battery systems spend weeks to months on a design study with PVsyst, HOMER and field data,
and they confirm every number against references or field records before they trust it. The study page already
labels every number. It does not yet say which numbers to confirm first, what the public field figures say, or
give an engineer the hourly series to check us in their own tool. This task adds all three. Nothing in the study
itself changes.

## 1. autosolar/engineer_files.py

No network, no file writes. Imports `Battery`, `DispatchResult` and `dispatch` from `autosolar.dispatch`.
Constants:

- `ENGINEER_FILES_SCHEMA = "autosolar.engineer_files/1"`, `REL_TOL = 1e-9`, `HOMER_LINES = 8760`.
- `HOURLY_CSV_COLUMNS = ("time_utc", "time_local", "ghi_w_m2", "temp_air_degc", "wind_speed_m_s", "load_kw",
  "pv_ac_kw_per_kwp", "pv_kw", "pv_to_load_kw", "pv_to_battery_kw", "pv_curtailed_kw", "battery_discharge_kw",
  "soc_kwh", "diesel_kw", "diesel_units_on", "unserved_kw", "fuel_l")`
- `NOTE = "Rebuilt from the study's inputs and cached weather. The study itself is unchanged."`

### main_design_dispatch(pv_ac_kw_per_kwp, load_kw, *, main_pv_kwp, main_battery_kwh, battery_hours, battery_template, diesel) -> DispatchResult

- `main_pv_kwp` and `main_battery_kwh`: finite reals, 0 or more; `battery_hours`: finite real above 0; `bool`
  refused for all three. `battery_template` must be a `Battery`. Else `ValueError`.
- The battery is built exactly as `autosolar.sweep.dispatch_grid` builds it: when `main_battery_kwh == 0`,
  `Battery(energy_kwh=0.0, power_kw=0.0, ...)`, else `Battery(energy_kwh=b, power_kw=b / battery_hours, ...)`,
  with `round_trip_eff_frac`, `soc_min_frac` and `soc_initial_frac` from the template.
- Returns `dispatch(pv_ac_kw_per_kwp * float(main_pv_kwp), load_kw, battery, diesel)`. Inputs are never changed.

### hourly_frame(weather_frame, pv_ac_kw_per_kwp, load_kw, result, local_tz) -> pd.DataFrame

- `weather_frame`: a DataFrame with a tz aware `DatetimeIndex` and the columns `ghi_w_m2`, `temp_air_degc`,
  `wind_speed_m_s`. `pv_ac_kw_per_kwp`, `load_kw` and `result.hourly` must have the same index as `weather_frame`
  (compared with `Index.equals`). `local_tz` a string that `tz_convert` accepts. Else `ValueError`.
- Returns a new DataFrame with a default `RangeIndex` and exactly the columns `HOURLY_CSV_COLUMNS` in that order:
  - `time_utc`: the index in UTC as text, format `"%Y-%m-%d %H:%M"`; `time_local`: the index in `local_tz`, same
    format.
  - the three weather columns from `weather_frame`; `load_kw` from `load_kw`; `pv_ac_kw_per_kwp` from
    `pv_ac_kw_per_kwp`;
  - `pv_kw`, `pv_to_load_kw`, `pv_to_battery_kw`, `pv_curtailed_kw`, `battery_discharge_kw`, `soc_kwh`,
    `diesel_kw`, `diesel_units_on`, `unserved_kw`, `fuel_l` from `result.hourly`.
- Values are copied as they are (no rounding).

### homer_load_lines(load_kw, local_tz) -> list[str]

- `load_kw`: a Series of finite reals with a tz aware `DatetimeIndex` of exactly `HOMER_LINES` hourly stamps.
  Else `ValueError`.
- `k` is the position of the first stamp whose time in `local_tz` is 1 January, 00:00. No such stamp: `ValueError`
  with "midnight" in the message.
- Returns `format(v, ".6f")` for each value of `load_kw` in the order `k, k+1, ..., n-1, 0, 1, ..., k-1`, so the
  first line is local midnight on 1 January (HOMER's single column import starts at midnight on 1 January). The
  sum of the values is unchanged.

### reproduction_errors(report, frame, result, basis_case) -> list[str]

The files are trusted only if they give back the study's own numbers. Two floats match when
`abs(a - b) <= REL_TOL * max(1.0, abs(b))`. Returns a list of messages, empty when all match; each message
starts with the field name, then `": got "`, the value, `" want "`, the value.

- `demand_kwh_yr`: `frame["load_kw"].sum()` against `report["facts"]["demand_kwh_yr"]["value"]`.
- `demand_peak_kw`: `frame["load_kw"].max()` against `report["facts"]["demand_peak_kw"]["value"]`.
- `yield_kwh_kwp_yr`: `frame["pv_ac_kw_per_kwp"].sum()` against `yield_kwh_kwp_yr` of the
  `report["weather_table"]` row whose `case` equals `basis_case`. No such row: one message starting with
  `"weather_table"`.
- `best_fuel_l_yr`: `frame["fuel_l"].sum()` against `report["facts"]["best_fuel_l_yr"]["value"]`.
- When `report.get("firmness")` is a dict, for each of these firmness items that is present (matched by `key`):
  `best_unserved_kwh_yr` against `frame["unserved_kw"].sum()`, `best_diesel_run_hours` against
  `result.diesel_run_hours`, `best_diesel_starts` against `result.diesel_starts`. Missing items are skipped.

### engineer_doc(report, *, run_id, basis_case, local_tz, frame, result, homer_lines, errors, files, wall_s) -> dict

Returns a JSON-able dict with exactly: `schema`, `run_id`, `study_run_hash` (`report["run_hash"]`), `basis_case`,
`local_tz`, `rows` (`len(frame)`), `columns` (list of the frame's columns), `homer_lines` (`len(homer_lines)`),
`sums` (a dict with exactly `load_kwh`, `peak_kw`, `pv_kwh_per_kwp`, `fuel_l`, `unserved_kwh` from the frame as
floats, and `diesel_run_hours`, `diesel_starts` from `result` as ints), `files` (a copy of `files`, a dict of file
name to sha256 hex text), `reproduced` (`len(errors) == 0`), `reproduction_errors` (a list copy), `wall_s` (float)
and `note` (`NOTE`).

## 2. tools/engineer_files.py

`python tools/engineer_files.py --run <study hash>`

- Optional: `--runs` (default `runs/studies`), `--out` (default `runs/engineer_files`), `--weather-cache` (default
  `runs/weather_cache`). Relative paths are against the repo root. Imports `CACHE_ONLY_EMAIL` and
  `no_network_fetchers` from `tools/load_followup.py` (same folder).
- `main(argv=None) -> int`:
  1. Reads `<runs>/<run>/report.json` and `<runs>/<run>/inputs.json`. A missing file prints `not found: <path>` and
     returns 2, and nothing is written.
  2. Same rebuild as `tools/load_followup.py`: `values` from `load_inputs`; `costs, battery, diesel, battery_hours`
     from `_design_objects(values)`; weather from `build_weather_cases` with the cache only fetchers; the PV series
     `simulate_pv(weather.cases[weather.basis], lat, lon, PVDesign(), 1.0).hourly["ac_kw"]`; the load
     `build_demand_cases(weather.cases[weather.basis].index)["paper"].load_kw`.
  3. `result = main_design_dispatch(...)` with the facts `best_pv_kwp` and `best_battery_kwh`;
     `frame = hourly_frame(weather.cases[weather.basis], pv, load, result, LOCAL_TZ)` with `LOCAL_TZ` from
     `autosolar.demand`; `lines = homer_load_lines(load, LOCAL_TZ)`;
     `errors = reproduction_errors(report, frame, result, weather.basis)`.
  4. `run_id = "files-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid4 hex[:6]`. Writes into `<out>/<run_id>/`:
     `hourly.csv` (`frame.to_csv(index=False, lineterminator="\n")`, ASCII), `homer_load_kw.txt` (the lines joined
     with `"\n"` plus a final `"\n"`, ASCII), then `engineer_files.json` (ASCII, indent 2) from `engineer_doc` with
     `files` = the sha256 of the two written files. Always written, so a failed check is kept for audit.
  5. Prints the run id, the rows, the sums, and `reproduced yes` or `reproduced NO` with the messages. Returns 0
     when reproduced, else 3.
- Makes no network call and no model call.

## 3. autosolar/site.py

New constants:

```
FIELD_ASKS = {
    "pv_capex_usd_per_kwp": "Installed PV prices from recent island tenders, shipping included",
    "battery_capex_usd_per_kwh": "Installed battery prices from recent tenders, shipping included",
    "fuel_price_usd_per_l": "Diesel price delivered to the island, with tax and shipping",
    "discount_rate_frac": "The real discount rate the owner or lender uses",
    "demand": "Metered hourly load for a full year, or at least monthly kWh sent out",
    "diesel_om_usd_per_kwh": "Diesel plant O&M cost records",
    "fuel_intercept_l_per_h_per_kw_rated": "Litres and kWh from the plant logs, by hour or by day",
    "fuel_slope_l_per_kwh": "Litres and kWh from the plant logs, by hour or by day",
    "battery_duration_h": "Battery power rating offered for this energy size",
}
FIELD_ASK_DEFAULT = "Field records for this input"
FIELD_NOTE_KEYS = ("site", "key", "item", "value", "decimals", "unit", "label", "date", "source", "url", "quote",
                   "compare", "note")
FIELD_COMPARES = ("energy_kwh_per_day", "fuel_l_per_kwh", "peak_kw")
```

### check_field_note(note) -> dict

A note is valid when it is a dict with exactly the keys `FIELD_NOTE_KEYS`; `value` a finite real (not `bool`);
`decimals` an int from 0 to 6 (not `bool`); `label` one of `"press"`, `"docs"`, `"paper"`, `"measured"`; `url`
a string that starts with `"http://"` or `"https://"`; `compare` None or one of `FIELD_COMPARES`; every other key
a non-empty string, except `note`, which may be empty. Returns the same dict; else `ValueError`.

### confirm_section(report, *, field_notes=None, engineer_files=None) -> str

Returns `'<section id="confirm"><h2>Confirm these first</h2>' + ... + "</section>"`, all text through `esc`:

1. `<p>This page is a first screen, made in minutes from public data. It is not a design study. Before anyone builds
   on it, confirm the inputs below with field data, from the top, and check the result in your own tool.</p>`
2. When `report.get("firmness")` is a dict whose items include the keys `best_no_diesel_hours` and
   `reserve_main_design_lcoe_usd_per_kwh`: `<p class="ask">` + text + `</p>` with the text
   `"An engineering question comes first: can the island grid run on batteries and inverters alone? The main design
   runs with no diesel for " + H + " hours a year (computed). If " + U + " must run in every hour, the main design
   costs " + R + " USD/kWh, " + W + " diesel only at " + D + " USD/kWh (computed)."` where `H = fmt(hours, 0)`,
   `R = fmt(reserve main, 3)`, `D = fmt(facts diesel_only_lcoe_usd_per_kwh, 3)`, `W` is `"more than"` when the
   reserve value is above the diesel only value, else `"not more than"`, and `U` is `"one diesel unit"` when the
   item `reserve_units` is missing or equals 1, else `fmt(units, 0) + " diesel units"`.
3. The ranking table, from `report["sensitivity_table"]`. Group rows by `input` in order of first appearance. An
   input needs one row with `factor` below 1 (low) and one above 1 (high); other inputs are left out. The spread
   is `abs(high base_design_lcoe_usd_per_kwh - low base_design_lcoe_usd_per_kwh)`. Sort by spread, largest first;
   equal spreads keep their first appearance order. When at least one input is left, add `_table` with headers
   `["Rank", "Input", "Value in this study", "Main design cost, input down / up (USD/kWh)", "Field data to ask
   for"]` and one row per input:
   - Rank `str(i)` from 1; Input `SENSITIVITY_LABELS.get(name, name)`;
   - Value: for `demand`, `fmt(facts demand_kwh_yr value, 0) + " kWh/yr (" + facts demand_kwh_yr label + ")"`;
     otherwise from the `report["inputs_table"]` row with that `name`: `cells[1] + " " + unit + " (" + label +
     ")"`, or `""` when there is no row;
   - Cost: `fmt(low base, 3) + " / " + fmt(high base, 3)`;
   - Ask: `FIELD_ASKS.get(name, FIELD_ASK_DEFAULT)`.
   Then `<p>Each input is moved P% down and up, the swing in the inputs table. The order is by how far the cost of
   the main design moves (computed).</p>` with `P = fmt(100 * (1 - low factor of the first ranked input), 0)`.
4. When `field_notes` is a non-empty list (each passed through `check_field_note`): `<h3>Public field figures for
   this site</h3>`, `<p>From the press and public documents, not from the operator's records. They can be old or
   rounded. They show where to look; they do not replace the study's inputs.</p>`, and `_table` with headers
   `["Item", "Public figure", "Date", "Source and quote", "This study", "Study / public"]`, one row per note in the
   given order:
   - Item: `item`; Public figure: `fmt(value, decimals) + " " + unit + " (" + label + ")"`, plus `"; " + note`
     when `note` is not empty; Date: `date`; Source and quote: `source + ": \"" + quote + "\" " + url`.
   - This study and the ratio, by `compare`, with `F = report["facts"]`:
     - `energy_kwh_per_day`: `s = F demand_kwh_yr value / 365`, text `fmt(s, 0) + " kWh a day (computed)"`;
     - `fuel_l_per_kwh`: `s = F diesel_only_fuel_l_yr value / F demand_kwh_yr value`, text
       `fmt(s, 3) + " L/kWh, diesel only (computed)"`;
     - `peak_kw`: `s = F demand_peak_kw value`, text `fmt(s, 0) + " kW (" + F demand_peak_kw label + ")"`;
     - None: both cells `""`.
     - Ratio cell: `fmt(s / value, 2) + "x"` (when `compare` is not None).
5. When `engineer_files` is given: it must be a dict with `reproduced` `True` and `study_run_hash` equal to
   `report["run_hash"]`, else `ValueError` (the page never links files that did not first give back the study's
   numbers). Add `<h3>Check us in your own tool</h3>`, `<p>The hourly series behind this page, rebuilt from the
   study's inputs and cached weather. Before writing them, the tool gave back this study's yearly demand, peak load,
   PV yield, and the main design's fuel, load not served, diesel hours and starts, to within one part in a billion
   (computed).</p>` and a list:
   - `<ul><li><a href="data/RUN/files/hourly.csv">hourly.csv</a>: ` + text + `</li>` with the text
     `fmt(rows, 0) + " rows, one per hour: weather, load, PV per kWp and the main design's energy flow, in UTC and
     local time."`
   - `<li><a href="data/RUN/files/homer_load_kw.txt">homer_load_kw.txt</a>: ` + text + `</li></ul>` with the text
     `"the load in kW, one value per line, " + fmt(homer_lines, 0) + " lines, starting at local midnight on 1
     January (the single column layout in HOMER's import formats)."`
   - `RUN` is `report["run_hash"]`; the link text and `href` go through `esc`.

`render_study_html` gains two keyword arguments, `field_notes: list | None = None` and
`engineer_files: dict | None = None`, and inserts `confirm_section(report, field_notes=field_notes,
engineer_files=engineer_files)` right after the fuel price section and before "How firm is the answer". Every
study page gets the section; nothing else on the page changes. ASCII only, no `<script>`.

## 4. tools/make_site.py

- If `config/field_notes.json` exists, read it (`{"schema": "autosolar.field_notes/1", "notes": [...]}`) and pass
  `field_notes=` the notes whose `site` equals `report["site"]["name"]`, or nothing when there are none.
- A gallery entry may hold `"engineer_files": "<run id>"`. When present, copy `hourly.csv`, `homer_load_kw.txt` and
  `engineer_files.json` from `runs/engineer_files/<id>/` to `docs/site/data/<run>/files/` and pass the loaded
  `engineer_files.json` as `engineer_files=`. Entries without the key are built as before.

## Acceptance

`tests/test_engineer_files.py` passes, and the full suite still passes. Muse must not edit specs, tests or config.

## T22b: same bytes on every OS (added after the code)

On Windows, `Path.write_text` turns each `"\n"` into `"\r\n"`, so the sha256 in `engineer_files.json` would differ
from a Linux build of the same files. Builder edits `tools/engineer_files.py` only:

- Add `write_ascii_lf(path, text) -> None`: writes `text.encode("ascii")` with `Path.write_bytes`, so no newline is
  changed on any OS; text that is not ASCII raises `UnicodeEncodeError`.
- Use it for all three files (`hourly.csv`, `homer_load_kw.txt`, `engineer_files.json`); the tool no longer calls
  `write_text`.

Tests: `test_tool_writes_lf_ascii_bytes` and `test_tool_has_no_write_text` in `tests/test_engineer_files.py`
(written after the T22 code, labelled so).

## Planted faults (run on Muse Code's build after it passed)

24 faults, each planted in the built code and run against `tests/test_engineer_files.py`: 23 caught (computed). The
one that passed: the HOMER file not rotated to local midnight, because the test load repeats every day. A test with
a load that never repeats was added after the code (labelled so in the test file); it fails on that fault and passes
on the build. Script: kept with the build files.

## T22c: wording after an outside review (added after the code)

An outside review (DeepSeek, Friday 30 Oct) found four places where the page says less than it knows, or more.
Builder edits `autosolar/site.py` only. Every other line of T22 and T23 stays in force.

1. `_confirm_question`: when the firmness items `reserve_pv_kwp`, `reserve_battery_kwh` and
   `reserve_lcoe_usd_per_kwh` are all present with finite real values, append one sentence after the existing
   text, inside the same `<p class="ask">`: `" Under that rule the least cost design is " + fmt(P, 0) + " kWp and "
   + fmt(B, 0) + " kWh at " + fmt(L, 3) + " USD/kWh, " + W + " diesel only (computed; see How firm is the
   answer)."` where `W` is `"below"` when `L < diesel only LCOE` and `"not below"` otherwise. When any of the three
   is missing or not a finite real, the sentence is left out and the rest stays as it is. Why: the first sentence
   alone reads as "solar loses"; the same rule's least cost design still beats diesel in the example (0.336
   against 0.354).
2. `FIELD_COMPARES` becomes `("energy_kwh_per_day", "fuel_l_per_kwh", "peak_kw", "fuel_l_per_day")`. For
   `"fuel_l_per_day"` the "This study" cell is `fmt(facts["diesel_only_fuel_l_yr"]["value"] / 365.0, 0) + " L a
   day, diesel only (computed)"`, and "Study / public" is the study value over the public value, as for the
   others. Why: the cell was blank, and the daily fuel (2.50 times the press figure) belongs next to the litres per
   kWh (0.76 times).
3. For `"fuel_l_per_kwh"` the "This study" cell becomes `fmt(value, 3) + " L/kWh, diesel only, idle fuel included
   (computed)"`. Why: the inputs table shows the fuel curve at 0.25 L/kWh; the field row shows the year's litres
   over the year's kWh, which also counts idle fuel and part load.
4. Two strings in `resources_section` (T23): the sun cell ends `"(Global Solar Atlas, a Solargis model; docs)"`
   instead of `"(Global Solar Atlas, measured)"`, because PVOUT is a model output; the hydro cell reads
   `"<n> river and <m> stream lines mapped within <r> km, nearby islands included (OpenStreetMap, measured)"`,
   because a 10 km circle reaches the neighbouring islands.

Config (orchestrator, same commit as this section): in `config/field_notes.json` the first item becomes
"Electricity produced a day", with a note on what the article covers and the figure grown to the study year, and
the "Diesel fuel a day" item compares with `"fuel_l_per_day"`.

Tests: the T22 and T23 tests that pin these strings were updated after the code, labelled so, plus
`test_confirm_question_least_cost_under_rule` and `test_field_fuel_per_day`.
