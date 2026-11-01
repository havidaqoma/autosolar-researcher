# T25: costs the study leaves out, as what-ifs, and a year by year cash flow (post hoc)

Status: spec and acceptance tests written first, by hand, after the owner asked whether the cost analysis covers
every cost (post hoc). Muse Code writes the new module `autosolar/cost_whatif.py` and the new tool
`tools/cost_whatif.py` only. The acceptance tests are `tests/test_cost_whatif.py`. No study, page or earlier
module changes. The orchestrator runs the tool after the code and commits its output in `docs/posthoc/`.

## Why

The study leaves some costs out (README, "What it does not cover"). Some of them favour solar: PV degradation,
battery ageing, grid-forming inverters, the island premium on shipped equipment. Some favour diesel: engine
overhauls and fuel price rises. The second model review of the example study also asked for a year by year cash
flow. This task re-costs the study's least cost design under each change, with the study's own dispatch and cost
functions on the study's own hourly file, and writes the cash flow. The six single changes and their sizes were
fixed in a scratch script before its first run (post hoc to the study); the three combined cases were added after
that run. Every size is assumed.

## 1. autosolar/cost_whatif.py

No network, no file writes. Uses `Battery`, `DieselFleet` and `dispatch` from `autosolar.dispatch`, and
`AnnualFlows`, `CostInputs`, `Design` and `component_schedule` from `autosolar.econ`. `bool` is refused wherever a
number is asked for. Bad input raises `ValueError`.

### Constants

- `COST_WHATIF_SCHEMA = "autosolar.cost_whatif/1"`
- `NOTE = "Re-costs the study's least cost design with the study's own dispatch and cost functions on its own hourly file. The design is not re-sized, so each row is a ceiling on that design's cost. The six single changes and their sizes were fixed before the first run; the three combined rows were added after it. Every change is assumed; every result is computed. Post hoc: none of this is in the study."`
- `CASE_KEYS = ("key", "label", "pv_degradation_frac_per_yr", "battery_life_minus_yr", "battery_power_plus_usd_per_kw", "capital_mult", "diesel_om_plus_usd_per_kwh", "fuel_escalation_frac_per_yr")`
- `ROW_KEYS = ("year", "capital_usd", "om_usd", "fuel_usd", "salvage_usd", "total_usd", "discounted_usd", "served_kwh", "discounted_kwh")`
- `CASES`: a tuple of 10 dicts, in this order, each with exactly the keys `CASE_KEYS` in that order. Values, in
  `CASE_KEYS` order after key and label (`battery_life_minus_yr` is an `int`, the others `float`):

| key | label | values |
|---|---|---|
| study | As in the study | 0.0, 0, 0.0, 1.0, 0.0, 0.0 |
| pv_degradation | PV output falls 0.5% a year | 0.005, 0, 0.0, 1.0, 0.0, 0.0 |
| battery_life | Battery lasts 2 years less | 0.0, 2, 0.0, 1.0, 0.0, 0.0 |
| grid_forming | Grid-forming inverters: battery power price +150 USD/kW | 0.0, 0, 150.0, 1.0, 0.0, 0.0 |
| island_capital | Island premium: PV and battery prices +30% | 0.0, 0, 0.0, 1.3, 0.0, 0.0 |
| solar_side | The four above at once | 0.005, 2, 150.0, 1.3, 0.0, 0.0 |
| diesel_overhaul | Diesel overhauls: diesel O&M +0.02 USD/kWh | 0.0, 0, 0.0, 1.0, 0.02, 0.0 |
| fuel_escalation | Fuel price rises 2% a year (real) | 0.0, 0, 0.0, 1.0, 0.0, 0.02 |
| diesel_side | The two diesel items at once | 0.0, 0, 0.0, 1.0, 0.02, 0.02 |
| all_six | All six at once | 0.005, 2, 150.0, 1.3, 0.02, 0.02 |

### apply_case(costs, case) -> CostInputs

- `costs` must be a `CostInputs`; `case` a dict holding at least the six number keys of `CASE_KEYS`.
- Checks: `pv_degradation_frac_per_yr` finite, `0 <= d < 1`; `battery_life_minus_yr` an `int`, 0 or more;
  `battery_power_plus_usd_per_kw` and `diesel_om_plus_usd_per_kwh` finite, 0 or more; `capital_mult` finite, above 0;
  `fuel_escalation_frac_per_yr` finite, above -1. `costs.battery_life_yr - battery_life_minus_yr` must be 1 or more.
- Returns a new `CostInputs` (`dataclasses.replace`); `costs` is not changed:
  - `pv_capex_usd_per_kwp = costs.pv_capex_usd_per_kwp * capital_mult`
  - `battery_capex_usd_per_kwh = costs.battery_capex_usd_per_kwh * capital_mult`
  - `battery_power_capex_usd_per_kw = (costs.battery_power_capex_usd_per_kw + battery_power_plus_usd_per_kw) * capital_mult`
  - `battery_life_yr = costs.battery_life_yr - battery_life_minus_yr` (an `int`)
  - `diesel_om_usd_per_kwh = costs.diesel_om_usd_per_kwh + diesel_om_plus_usd_per_kwh`
  - every other field unchanged (the fuel price too: escalation is applied in `cash_flow`).

### yearly_flows(pv_ac_kw_per_kwp, load_kw, *, design, battery_template, diesel, project_life_yr, pv_degradation_frac_per_yr) -> list[AnnualFlows]

- `design` a `Design`, `battery_template` a `Battery`, `diesel` a `DieselFleet`; `project_life_yr` an `int`, 1 or
  more; `pv_degradation_frac_per_yr` finite, `0 <= d < 1`. The two series go to `dispatch` as they are.
- The battery: when `design.battery_kwh == 0`, `Battery(energy_kwh=0.0, power_kw=0.0, ...)`, else
  `Battery(energy_kwh=design.battery_kwh, power_kw=design.battery_kw, ...)`, with `round_trip_eff_frac`,
  `soc_min_frac` and `soc_initial_frac` from the template.
- Year `y` (1 to `n`): `result = dispatch(pv_ac_kw_per_kwp * (float(design.pv_kwp) * (1.0 - d) ** (y - 1)), load_kw,
  battery, diesel)` and `AnnualFlows(load_served_kwh=result.load_served_kwh, fuel_l=result.fuel_l,
  diesel_kwh=result.diesel_kwh)`.
- When `d == 0` or `design.pv_kwp == 0`, dispatch once, with `pv_ac_kw_per_kwp * float(design.pv_kwp)`, and repeat
  that `AnnualFlows` for every year.
- Returns a list of `n` `AnnualFlows`, year 1 first.

### cash_flow(design, flows, costs, fuel_escalation_frac_per_yr=0.0) -> list[dict]

- `design` a `Design`; `costs` a `CostInputs`; `flows` a list of exactly `costs.project_life_yr` `AnnualFlows`;
  `fuel_escalation_frac_per_yr` finite, above -1.
- `n = costs.project_life_yr`, `r = costs.discount_rate_frac`. `pv_cap = design.pv_kwp * costs.pv_capex_usd_per_kwp`;
  `bat_cap = design.battery_kwh * costs.battery_capex_usd_per_kwh + design.battery_kw * costs.battery_power_capex_usd_per_kw`.
  Replacement years and salvage come from `component_schedule(pv_cap, costs.pv_life_yr, n)` and
  `component_schedule(bat_cap, costs.battery_life_yr, n)`.
- Returns `n + 1` dicts, years 0 to `n`, each with exactly the keys `ROW_KEYS` in that order; `year` an `int`, all
  other values `float`:
  - Year 0: `capital_usd = pv_cap + bat_cap`; `om_usd`, `fuel_usd`, `salvage_usd`, `served_kwh` and
    `discounted_kwh` are 0.0; `total_usd = capital_usd`; `discounted_usd = total_usd`.
  - Year `y` from 1 to `n`, with `f = flows[y - 1]`:
    - `capital_usd`: the sum of the replacement amounts in year `y` (PV and battery), 0.0 when none;
    - `om_usd = design.pv_kwp * costs.pv_om_usd_per_kwp_yr + design.battery_kwh * costs.battery_om_usd_per_kwh_yr + f.diesel_kwh * costs.diesel_om_usd_per_kwh`;
    - `fuel_usd = f.fuel_l * costs.fuel_price_usd_per_l * (1 + fuel_escalation_frac_per_yr) ** (y - 1)`;
    - `salvage_usd = -(pv salvage + battery salvage)` in year `n`, else 0.0;
    - `total_usd = capital_usd + om_usd + fuel_usd + salvage_usd`;
    - `discounted_usd = total_usd / (1 + r) ** y`;
    - `served_kwh = f.load_served_kwh`; `discounted_kwh = served_kwh / (1 + r) ** y`.

### summary(rows) -> dict

- `rows`: a non-empty list of dicts holding `discounted_usd` and `discounted_kwh`; the sum of `discounted_kwh` must
  be above 0.
- Returns `{"npc_usd": sum of discounted_usd, "lcoe_usd_per_kwh": npc_usd / sum of discounted_kwh}`.

### run_cases(pv_ac_kw_per_kwp, load_kw, *, design, battery_template, diesel, costs) -> list[dict]

- For each case in `CASES`, in order: `c2 = apply_case(costs, case)`; the main design's flows and cash flow use
  `design`; the diesel only flows and cash flow use `Design(pv_kwp=0.0, battery_kwh=0.0, battery_kw=0.0)`. Both use
  `yearly_flows(..., project_life_yr=costs.project_life_yr, pv_degradation_frac_per_yr=<the case's>)` and
  `cash_flow(<design>, <flows>, c2, <the case's fuel_escalation_frac_per_yr>)`, then `summary`.
- Flows may be reused between cases with the same degradation; the results must not change.
- Returns 10 dicts with exactly these keys in this order: `key`, `label`, `main_lcoe_usd_per_kwh`,
  `diesel_only_lcoe_usd_per_kwh`, `main_npc_usd`, `diesel_only_npc_usd`, `main_vs_diesel_pct`, where
  `main_vs_diesel_pct = (main_lcoe_usd_per_kwh / diesel_only_lcoe_usd_per_kwh - 1) * 100`.

### render_md(doc) -> str

- `doc`: a dict with `schema == COST_WHATIF_SCHEMA`, `run_hash` (a str), `cases` (as from `run_cases`),
  `cash_flow_main` and `cash_flow_diesel_only` (as from `cash_flow`). Else `ValueError`.
- Number formats: USD/kWh `"%.3f"`; the percent `"%+.1f%%"`; USD amounts `format(int(round(x)), ",d")`.
- Returns these lines joined with `"\n"`, plus a final `"\n"`:

```
# Costs the study leaves out: what if? (study <run_hash>, post hoc)

<NOTE>

| Change (assumed) | Solar plus battery (USD/kWh) | Diesel only (USD/kWh) | Solar plus battery against diesel only |
|---|---|---|---|
| <label> | <main lcoe> | <diesel only lcoe> | <main_vs_diesel_pct> |      (one line per case, in order)

## Year by year cash flow, main design (USD, computed)

| Year | Capital | O&M | Fuel | Salvage | Total | Discounted |
|---|---|---|---|---|---|---|
| <year> | <capital> | <om> | <fuel> | <salvage> | <total> | <discounted> |   (one line per row)
| NPC | | | | | | <npc_usd from summary> |

## Year by year cash flow, diesel only (USD, computed)

(the same header, separator, rows and NPC line for cash_flow_diesel_only)
```

## 2. tools/cost_whatif.py

`main(argv=None) -> int`, run as `python tools/cost_whatif.py --run <study hash>`. Options: `--run` (required),
`--site` (default `docs/site`), `--out` (default `docs/posthoc`). Relative paths are taken from the repo root.

1. Reads `<site>/data/<run>/report.json` and `<site>/data/<run>/files/hourly.csv`.
2. From `report["inputs_table"]` (rows with `name` and `value`): the 12 `CostInputs` fields (`pv_life_yr`,
   `battery_life_yr`, `project_life_yr` and `currency_year` as `int`, the rest `float`); the battery template
   `Battery(energy_kwh=1.0, power_kw=1.0, round_trip_eff_frac=<battery_round_trip_eff_frac>,
   soc_min_frac=<battery_soc_min_frac>, soc_initial_frac=<battery_soc_initial_frac>)`; and
   `DieselFleet(unit_kw=<diesel_unit_kw>, n_units=int(<diesel_n_units>), min_load_frac=<diesel_min_load_frac>,
   fuel_intercept_l_per_h_per_kw_rated=<...>, fuel_slope_l_per_kwh=<...>)`. The design: `Design(pv_kwp=<facts
   best_pv_kwp value>, battery_kwh=<facts best_battery_kwh value>, battery_kw=<facts best_battery_kw value>)`.
3. From `hourly.csv`: the index is `pd.to_datetime(time_utc, format="%Y-%m-%d %H:%M")` made UTC
   (`tz_localize("UTC")`); `pv_ac_kw_per_kwp` and `load_kw` become float Series on that index.
4. Runs `run_cases`, and builds `cash_flow_main` and `cash_flow_diesel_only` for the `study` case (no change).
5. Reproduction gate: the study case's `main_lcoe_usd_per_kwh` must match facts `best_lcoe_usd_per_kwh`, its
   `diesel_only_lcoe_usd_per_kwh` must match facts `diesel_only_lcoe_usd_per_kwh`, and `summary(cash_flow_main)`
   `npc_usd` must match facts `best_npc_usd`, each within a relative 1e-9. If any fails: print a line that starts
   with `REPRODUCTION FAILED`, write nothing, return 1.
6. Writes, creating `<out>`, ASCII with `"\n"` line ends:
   - `<out>/<run>_cost_whatif.json`: `json.dumps(doc, indent=1) + "\n"` with `doc = {"schema", "run_hash", "note":
     NOTE, "inputs": {the 12 cost inputs by name, "pv_kwp", "battery_kwh", "battery_kw"}, "cases", "cash_flow_main",
     "cash_flow_diesel_only"}`, in that key order;
   - `<out>/<run>_cost_whatif.md`: `render_md(doc)`.
7. Prints one line per case, `<key> <main lcoe %.4f> <diesel only lcoe %.4f>`, and returns 0.

## Rules for this task

- Write `autosolar/cost_whatif.py` and `tools/cost_whatif.py` only. Do not edit tests, specs, config, other modules,
  pages or `docs/posthoc/`.
- No new dependency; ASCII only; units in names; `ValueError` on bad input.
