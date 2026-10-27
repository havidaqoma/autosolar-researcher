# T09b: one question in, one checked study out (`autosolar/study.py`)

## Why

This is the thin end to end path (plan day 4 checkpoint). One call takes the user's question and returns a run
folder with a JSON report and a Markdown report. It chains the stages built so far: S0 parse and geocode (T09a),
S1 weather (T05), S2 demand (T06), S5 PV and dispatch (T04, T07), S6 cost and design grid (T08, T08b), S6b
sensitivity, S8 report, and the deterministic gates. Every number in the Markdown report must also appear in the
JSON report (the frozen number scan), and every fact carries a unit and a label.

## Allowed extra dependencies

None beyond `AGENTS.md`. No network in tests: the model client, the HTTP function and the weather function are
passed in. Do not change other modules.

## Public API

```python
from autosolar.study import (INPUT_NAMES, INT_INPUT_NAMES, LABELS, REPORT_SCHEMA, KARIMUNJAWA_DEG,
                             DEMAND_RADIUS_KM, FACT_SPECS, UnsupportedSite, GateFailed, ReportNumberMismatch,
                             StudyOutput, load_inputs, haversine_km, fmt_number, number_tokens,
                             scan_report_numbers, render_markdown, run_study)
```

### Constants

```python
REPORT_SCHEMA = "autosolar.report/1"
LABELS = ("measured", "computed", "assumed", "press", "paper", "paper (abstract)", "docs")
KARIMUNJAWA_DEG = (-5.85, 110.43)
DEMAND_RADIUS_KM = 30.0
INPUT_NAMES = ("pv_capex_usd_per_kwp", "pv_om_usd_per_kwp_yr", "pv_life_yr", "battery_capex_usd_per_kwh",
               "battery_power_capex_usd_per_kw", "battery_om_usd_per_kwh_yr", "battery_life_yr",
               "diesel_om_usd_per_kwh", "fuel_price_usd_per_l", "discount_rate_frac", "project_life_yr",
               "currency_year", "battery_round_trip_eff_frac", "battery_soc_min_frac", "battery_soc_initial_frac",
               "battery_duration_h", "diesel_unit_kw", "diesel_n_units", "diesel_min_load_frac",
               "fuel_intercept_l_per_h_per_kw_rated", "fuel_slope_l_per_kwh", "co2_kg_per_l", "unserved_max_frac",
               "rf_target_frac", "swing_frac", "pv_kwp_step", "pv_kwp_max", "battery_kwh_step", "battery_kwh_max")
INT_INPUT_NAMES = ("pv_life_yr", "battery_life_yr", "project_life_yr", "currency_year", "diesel_n_units")
FACT_SPECS = (   # key, unit, label, decimals
    ("site_lat_deg", "deg", "docs", 4),
    ("site_lon_deg", "deg", "docs", 4),
    ("weather_spread_pct", "%", "computed", 1),
    ("demand_kwh_yr", "kWh/yr", "computed", 0),
    ("demand_peak_kw", "kW", "paper", 0),
    ("best_pv_kwp", "kWp", "computed", 0),
    ("best_battery_kwh", "kWh", "computed", 0),
    ("best_battery_kw", "kW", "computed", 0),
    ("best_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("best_npc_usd", "USD", "computed", 0),
    ("best_capex_usd", "USD", "computed", 0),
    ("best_renewable_pct", "%", "computed", 1),
    ("best_curtailed_pct", "%", "computed", 1),
    ("best_fuel_l_yr", "L/yr", "computed", 0),
    ("best_co2_t_yr", "t/yr", "computed", 0),
    ("diesel_only_lcoe_usd_per_kwh", "USD/kWh", "computed", 3),
    ("diesel_only_fuel_l_yr", "L/yr", "computed", 0),
    ("diesel_only_co2_t_yr", "t/yr", "computed", 0),
    ("fuel_saved_l_yr", "L/yr", "computed", 0),
    ("co2_saved_t_yr", "t/yr", "computed", 0),
    ("lcoe_change_pct", "%", "computed", 1),
    ("break_even_fuel_usd_per_l", "USD/L", "computed", 2),
    ("api_cost_usd", "USD", "computed", 5),
)
```

Exceptions: `class UnsupportedSite(ValueError)`, `class GateFailed(RuntimeError)`,
`class ReportNumberMismatch(RuntimeError)`.

### Small helpers

- `haversine_km(lat1_deg, lon1_deg, lat2_deg, lon2_deg) -> float`, earth radius 6371.0088 km.
- `fmt_number(value, decimals) -> str`: `f"{value:,.{decimals}f}"` (comma thousands separator); a result that is a
  negative zero (for example `"-0"` or `"-0.0"`) loses its minus sign. `value` must be a finite real number (not
  bool) and `decimals` an int in 0..8, else `ValueError`.
- `number_tokens(text) -> list[str]`: all matches, in order, of the regex
  `(?<![A-Za-z0-9_.])\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z0-9_])`. So "1,250.5 kWp" gives `["1,250.5"]`, while
  "m2", "G3", "S0_parse" and hex like "3f9a" give nothing.
- `scan_report_numbers(md_text, report) -> list[str]`: the sorted unique tokens of `md_text` that are not among the
  tokens of any string value found anywhere inside `report` (walk dicts and lists; dict keys and non string
  scalars are ignored). An empty list means the scan passed.

### `load_inputs(path) -> tuple[dict, dict]`

Reads a JSON file shaped like `config/default_inputs.json` and returns `(values, raw)`, where `raw` is the parsed
file and `values` maps each name in `INPUT_NAMES` to its value. `ValueError` when: the top level is not a dict;
`schema != "autosolar.inputs/1"`; `values` is not a dict whose keys are exactly the set of `INPUT_NAMES`; an entry
is not a dict with exactly the keys `value`, `unit`, `label`, `note`; `unit` is not a non-empty string; `label` is
not in `LABELS`; `note` is not a string; a name in `INT_INPUT_NAMES` has a value that is not an int (bool is not an
int); any other value is not a finite int or float (bool rejected); `pv_kwp_step`, `battery_kwh_step` are not > 0;
`pv_kwp_max`, `battery_kwh_max` are not a whole multiple (to 1e-9) of their step, or are smaller than the step.
Other ranges are checked later by the dataclasses of T07 and T08.

### `run_study(question, *, client, http_get, weather_fn, inputs_path, runs_dir, run_id) -> StudyOutput`

```python
@dataclass(frozen=True)
class StudyOutput:
    run_hash: str
    run_dir: Path
    report: dict
    markdown: str
    reused: bool
```

`weather_fn(lat_deg, lon_deg) -> WeatherCases` (T05). `runs_dir` is a path (str or Path); create folders as needed.
Steps, in this order:

1. `question` must be a str with 1 to 2000 characters after strip (else `ValueError`). `values, raw =
   load_inputs(inputs_path)`.
2. Request cache: `req_file = runs_dir / "requests" / (sha256(question.strip().encode("utf-8")).hexdigest()[:16]
   + ".json")`. If it exists, rebuild `StudyRequest` and `Site` from its `"request"` and `"site"` entries (no
   model call, no geocoder call). Else `req = parse_question(question, client, run_id)`, `check_request(req)`,
   `site = geocode(req.site_name, http_get)`, then write `{"request": asdict(req), "site": asdict(site)}` to
   `req_file`. When read from the cache, still call `check_request(req)`.
3. If `haversine_km(site.lat_deg, site.lon_deg, *KARIMUNJAWA_DEG) > DEMAND_RADIUS_KM`: raise `UnsupportedSite`
   (the only demand source so far is the Karimunjawa profile of Hiron et al. 2021).
4. `lat_w, lon_w = round(site.lat_deg, 2), round(site.lon_deg, 2)` (weather and PV use these).
   `run_hash = sha256(json.dumps({"schema": REPORT_SCHEMA, "weather_coords_deg": [lat_w, lon_w], "inputs": raw},
   sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()[:16]`;
   `run_dir = runs_dir / run_hash`. If `run_dir / "report.json"` exists: load it, read `run_dir / "report.md"`,
   return `StudyOutput(run_hash, run_dir, report, markdown, reused=True)` without calling `weather_fn`.
5. `weather = weather_fn(lat_w, lon_w)`. For each name in `autosolar.weather.CASE_NAMES` that is in
   `weather.cases`, in that order: `pv = simulate_pv(weather.cases[name], lat_w, lon_w, PVDesign(), 1.0)`.
   Gate G3: passed when `1100 <= pv.specific_yield_kwh_kwp <= 1800` and `pv.performance_ratio_frac` is not None
   and `0.65 <= pv.performance_ratio_frac <= 0.90`. If the basis case (`weather.basis`) fails: raise
   `GateFailed` (nothing written to `run_dir`). The kWp output used below is `pv.hourly["ac_kw"]`.
6. Objects from `values`: `CostInputs` (its 12 fields have the same names), `Battery` template
   (`energy_kwh=1.0, power_kw=1.0`, `round_trip_eff_frac=battery_round_trip_eff_frac`,
   `soc_min_frac=battery_soc_min_frac`, `soc_initial_frac=battery_soc_initial_frac`), `DieselFleet(unit_kw=
   diesel_unit_kw, n_units=diesel_n_units, min_load_frac=diesel_min_load_frac, fuel_intercept_l_per_h_per_kw_rated,
   fuel_slope_l_per_kwh)`, `battery_hours = battery_duration_h`.
7. Main case: basis weather, demand case `"paper"` from `build_demand_cases(<basis weather index>)`. Grids:
   `[i * step for i in range(round(max / step) + 1)]` as floats. `points = dispatch_grid(...)`, `table =
   cost_table(points, costs, co2_kg_per_l)`, `best = least_cost(table, unserved_max_frac)`. Widening, at most 2
   times: while `on_grid_edge(table, best)` and widened < 2: for each axis where `best` sits on the maximum, the
   new maximum is `ceil(max * 1.5 / step) * step`; rebuild grid, points, table and best; widened += 1.
8. `break_even = break_even_fuel_price_usd_per_l(points, costs, co2, unserved_max_frac)` (`math.inf` becomes
   `None` in the report). `sens = sensitivity_table(<basis kW per kWp>, <paper load>, <final grids>, ...,
   swing_frac=values["swing_frac"])`.
9. Range rows, in this order. First the main row (basis weather, demand "paper"). Then each other weather case
   in `CASE_NAMES` order that passed G3, with the "paper" demand built on THAT case's index. Then the demand
   cases `"tourist season"` and `"growth"` on the basis weather. Every row uses the final grids from step 7; it
   holds `weather`, `demand`, `pv_kwp`, `battery_kwh`, `lcoe_usd_per_kwh` (its own least cost row) and
   `base_design_lcoe_usd_per_kwh` (the LCOE in that case of the main `best` design, same pv_kwp and battery_kwh),
   and `note` (`""`). When a case has no feasible design (`least_cost` raises `ValueError`) the three least cost
   values are `None` and `note` is `"no feasible design"`. A weather case that failed G3 is left out of the range.
10. Gates (list of dicts with `gate`, `scope`, `passed` (bool), `detail` (str)), in this order:
    one `"G3 PV physics"` row per weather case (scope = case name); then, on the dispatch result of the main
    `best` design: `"G1 energy balance"` (the three hourly balances of the T07 spec close to 1e-6 kW),
    `"G2 battery"` (SOC within `[soc_min_frac * E - 1e-6, E + 1e-6]` and `battery_discharge_kwh <=
    battery_charge_kwh * rte + (soc_start_kwh - soc_end_kwh) * sqrt(rte) + 1e-6`), `"G4 diesel"` (every hour with
    units on has `diesel_kw >= min_load_frac * units * unit_kw - 1e-6`); then `"G5 weather spread"` (passed when
    `not weather.range_required` or the range has at least 2 weather rows); `"G7 grid edge"` (passed when the
    final `best` is not on the grid edge; detail says how many times the grid was widened); `"G8 LCOE twins"`
    (passed when the largest `abs(lcoe_path_a - lcoe) / lcoe` over the main table is <= 0.001). The scope of
    G1, G2, G4, G7, G8 is `"main design"`, of G5 `"weather"`. A failed G1, G2, G4 or G8 raises `GateFailed`.
11. Facts: `report["facts"][key] = {"value": v, "unit": unit, "label": label, "text": fmt_number(v, decimals)}`
    for every entry of `FACT_SPECS`, with `v` a Python float, except `break_even_fuel_usd_per_l` when there is no
    break even (`value` None, `text` "not reached in grid"). Definitions: site lat and lon from `site`;
    `weather_spread_pct = weather.spread_pct_all`; demand from the "paper" case on the basis index
    (`annual_kwh`, `peak_kw`); `best_*` from the `best` row (`_pct` values are 100 times the `_frac` columns;
    `best_battery_kw` from the `battery_kw` column); `diesel_only_*` from the row with `pv_kwp == 0` and
    `battery_kwh == 0`; `fuel_saved_l_yr` and `co2_saved_t_yr` are diesel only minus best;
    `lcoe_change_pct = 100 * (best_lcoe / diesel_only_lcoe - 1)`; `api_cost_usd = req.cost_usd`.
12. Report dict (ASCII only JSON, `allow_nan=False`):
    `{"schema": REPORT_SCHEMA, "run_hash", "question" (stripped), "request": asdict(req), "site": asdict(site),
    "weather_coords_deg": [lat_w, lon_w], "facts", "weather_table", "range_table", "sensitivity_table", "gates",
    "inputs_table", "sources", "grid": {"pv_kwp": [...], "battery_kwh": [...], "widened": int}}`.
    Table rows are dicts holding the numbers plus `"cells"`: the list of strings the Markdown shows:
    - `weather_table` rows: `case`, `year` (int or None), `ghi_kwh_m2_yr` (from `weather.annual_ghi_kwh_m2`),
      `yield_kwh_kwp_yr`, `performance_ratio_frac`, `g3_passed`; cells `[case, str(year) or "none", fmt 0, fmt 0,
      fmt 2, "yes" or "no"]`.
    - `range_table` rows as in step 9; cells `[weather, demand, fmt 0, fmt 0, fmt 3, fmt 3, note]` with `"none"`
      for a None value.
    - `sensitivity_table` rows: the columns of `SENSITIVITY_COLUMNS` (NaN becomes None, `same_design` a bool);
      cells `[input, fmt factor 2, fmt 3, fmt 0, fmt 0, fmt 3, "yes" or "no", note]` with `"none"` for None.
    - `inputs_table` rows: `name`, `value`, `unit`, `label`, `note`; cells `[name, str(value), unit, label, note]`.
    - `gates` rows also carry cells `[gate, scope, "yes" or "no", detail]`.
    - `sources`: list of strings, at least `HIRON_2021_SOURCE`, one line naming OpenStreetMap Nominatim (data
      OpenStreetMap contributors, ODbL), one line naming the four weather sources, plus every string in
      `weather.notes`.
13. `markdown = render_markdown(report)`; `bad = scan_report_numbers(markdown, report)`; if `bad`: raise
    `ReportNumberMismatch` listing the tokens (nothing written to `run_dir`).
14. Write to `run_dir`: `request.json`, `site.json`, `inputs.json` (raw), `design_table.csv` (the final main table,
    no index), `sensitivity.csv` (no index), `report.md`, and LAST `report.json` (its presence marks a finished
    run). Return `StudyOutput(run_hash, run_dir, report, markdown, reused=False)`.

### `render_markdown(report) -> str`

ASCII only: every inserted string goes through `unicodedata.normalize("NFKD", s).encode("ascii",
"ignore").decode("ascii")` and has `|` replaced by `/`. Lines, in this order:

```
# AutoSolar pre-feasibility study: <site name>

Question: <question>

Run <run_hash>. Labels: measured (service data saved with the run), computed (this run), paper, docs, assumed.

## Answer

- <key with "_" replaced by " ">: <text> <unit> (<label>)          one line per FACT_SPECS entry, in order

## Weather sources

| Case | Year | GHI kWh/m2/yr (measured) | Yield kWh/kWp/yr (computed) | PR (computed) | G3 passed |
|---|---|---|---|---|---|
| <cells joined by " | "> |                                         one line per row

## Range of the answer

| Weather | Demand | PV kWp | Battery kWh | LCOE USD/kWh | LCOE of the main design USD/kWh | Note |

## Sensitivity

| Input | Factor | LCOE of the main design USD/kWh | Least cost PV kWp | Least cost battery kWh | Least cost LCOE USD/kWh | Same design | Note |

## Checks

| Gate | Scope | Passed | Detail |

## Inputs

| Name | Value | Unit | Label | Note |

## Sources

- <source>                                                          one line per source
```

Each table has its header line, the `|---|` line with one `---` per column, then one line per row
(`"| " + " | ".join(cells) + " |"`). A blank line separates blocks. The text ends with one newline.

## Done when

`uv run pytest` passes (all tests, including earlier tasks) and `AGENTS.md` rules hold.

## Test check by the orchestrator

The tests in `tests/test_study.py` were run against a throwaway reference implementation of this spec (kept
outside the repo, on top of the committed T04 to T09a modules): 58 of 58 passed in 40 s. So a failing test means
the code differs from this spec. `config/default_inputs.json` is owned by the orchestrator; do not edit it.
