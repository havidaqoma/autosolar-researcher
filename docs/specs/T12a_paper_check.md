# T12a: paper check, the script part (checks P1 to P15 on numbers pulled from a PDF)

Status: spec by the orchestrator. Builder writes the new file `autosolar/paper_check.py` only.
Imports allowed: the standard library, `autosolar.cite_check` (`find_quote`, `numbers_in`, `normalise_text`).

## Why

The study uses one published paper (Hiron 2021) for its hourly load. A hand audit in prep found 14 of 15 checks
that could not be reconciled (paper). The product must do this by itself for any PDF study: Muse Spark reads the
PDF and returns the numbers as JSON (T12b, orchestrator prompt); this module checks that every number is really in
the PDF and then runs the frozen checks P1 to P15 (`prep/benchmark/GENERIC_CHECKS.md` in the private prep repo,
copied in section 5 below). Nothing in this module may hold a constant from any one paper.

## 1. Extraction JSON (what the model returns)

```
{"statements": [statement, ...], "schedule": schedule or null}
statement = {"quantity": str, "value": number, "count": int or null, "unit": str, "condition": str,
             "page": int, "place": str, "quote": str}
schedule  = {"page": int, "label": str, "period_h": number, "rows": [row, ...]}
row       = {"time": str, "load_kw": number, "pv_to_load_kw": number or null, "pv_total_kw": number or null,
             "pv_to_battery_kw": number or null, "battery_discharge_kw": number or null,
             "diesel_kw": number or null, "curtailed_kw": number or null}
```

- `quantity` is one of `QUANTITIES` (section 2). `value` is the number exactly as printed (no unit conversion, no
  multiplication). `count` is the number of identical units when the paper says for example "2 x 2.7 MW" (value 2.7,
  count 2); else null. `condition` is "" or a short text that separates statements that are not meant to be equal
  (a scenario, a height, a year). `place` is one of `PLACES`. `page` is the 1-based page in the PDF file.
- `pv_to_load_kw` is PV power that goes straight to the load; `pv_total_kw` is all PV output. A row may give one,
  both or neither.

## 2. Constants

```
PLACES = ("abstract", "text", "table", "caption", "conclusion")
CHECK_IDS = ("P1", ..., "P15")             # 15 ids in order
SIZE_QUANTITIES = ("pv_ac_kw", "pv_dc_kwp", "battery_size", "diesel_kw", "converter_kw")
```

`QUANTITIES` is a dict from quantity name to its dimension (section 3). Exactly these 37 names:

| quantity | dimension |
|---|---|
| pv_ac_kw, pv_dc_kwp, diesel_kw, converter_kw, battery_kw, peak_load_kw | power |
| battery_size | battery |
| pv_module_wp | power |
| pv_module_count | count |
| pv_module_area_m2, pv_area_m2 | area |
| load_kwh_day, pv_kwh_day, diesel_kwh_day | energy |
| load_kwh_yr, pv_kwh_yr, diesel_kwh_yr, energy_served_kwh_yr | energy |
| ghi_kwh_m2_yr | irradiation |
| wind_m_s | speed |
| lcoe_usd_per_kwh, base_coe_usd_per_kwh | money_per_energy |
| npc_usd, capex_usd, annual_cost_usd, cost_item_usd, om_cost_usd | money |
| pv_capex_usd_per_kw, diesel_capex_usd_per_kw | money_per_power |
| battery_capex_usd_per_kwh | money_per_energy |
| fuel_price_usd_per_l | money_per_volume |
| discount_rate_frac, renewable_fraction_frac, battery_rte_frac | fraction |
| project_life_yr | time |
| fuel_l_yr | volume |
| co2_kg_yr | mass |

## 3. Units

`unit_factor(unit: str, dimension: str) -> float | None` turns a unit as written into the factor to the canonical
unit of the dimension. Before the lookup the unit is lowercased, every whitespace character is removed,
`"\u00b2"` (superscript two) becomes `"2"`, then `"us$"` and then `"usd"` become `"$"`.
Unknown units give None. The table (after that cleaning):

| dimension | canonical | units and factors |
|---|---|---|
| power | kW | w 0.001, kw 1, mw 1000, gw 1e6, wp 0.001, kwp 1, mwp 1000, kwac 1, mwac 1000, kwdc 1, mwdc 1000 |
| energy | kWh | wh 0.001, kwh 1, mwh 1000, gwh 1e6 |
| battery | kWh or Ah | kwh 1, mwh 1000, wh 0.001, ah 1, kah 1000, mah 1e6 (see below) |
| area | m2 | m2 1, ha 10000, km2 1e6 |
| irradiation | kWh/m2/yr | kwh/m2/yr 1, kwh/m2/year 1, kwh/m2/a 1, kwh/m2/day 365, kwh/m2/d 365, kwh/m2 1 |
| speed | m/s | m/s 1, km/h 1/3.6 |
| money_per_energy | $/kWh | $/kwh 1, $/mwh 0.001, cents/kwh 0.01, c/kwh 0.01 |
| money | $ | $ 1, k$ 1000, $k 1000, thousand$ 1000, million$ 1e6, m$ 1e6, $m 1e6 |
| money_per_power | $/kW | $/kw 1, $/kwp 1, $/mw 0.001, $/w 1000, $/wp 1000 |
| money_per_volume | $/L | $/l 1, $/liter 1, $/litre 1 |
| fraction | 1 | % 0.01, frac 1, "" 1 |
| time | yr | yr 1, year 1, years 1, a 1 |
| volume | L | l 1, liter 1, litre 1, liters 1, litres 1, kl 1000, ml 1e6 (megalitre; a millilitre is never meant in these papers) |
| mass | kg | kg 1, t 1000, ton 1000, tonne 1000, tons 1000, tonnes 1000, kt 1e6 |
| count | 1 | any unit: 1 |

`battery` has two sub units: energy (kwh, mwh, wh) and charge (ah, kah, mah). `unit_kind(unit, dimension)`
returns `"charge"` for the charge units of `battery` and the dimension name for everything else (None when unknown).
Two statements can be compared only when both factors are known and both kinds are equal.

The canonical value of a statement is `value * (count or 1) * factor`.

## 4. Functions

### parse_extraction(text: str) -> dict

- Strips a leading and trailing Markdown code fence (```json ... ``` or ``` ... ```) if present, then `json.loads`.
  Not JSON, or not a dict with exactly the keys `statements` and `schedule`: `ValueError`.
- Each statement is checked: exactly the 8 keys; `quantity` in `QUANTITIES`; `value` an int or float, not a bool,
  finite; `count` None or an int (not bool) >= 1; `unit`, `condition`, `quote` str; `page` an int >= 1; `place` in
  `PLACES`. A bad statement is not an error: it goes to the returned `"rejected"` list as
  `{"index": i, "reason": text}` and is left out.
- `schedule` is None or a dict with exactly the keys `page`, `label`, `period_h`, `rows`; every row has exactly the 8
  keys of section 1, `load_kw` a finite number >= 0, the others None or finite numbers >= 0. A bad schedule is
  replaced by None and a `{"index": "schedule", "reason": text}` entry goes to `"rejected"`.
- Returns `{"statements": [...], "schedule": ... or None, "rejected": [...]}`.

### verify_extraction(extraction: dict, pages: list[str]) -> dict

`pages` are the PDF page texts (as from `cite_check.pdf_pages`).

- A statement is kept only when all of these hold; else it goes to `"dropped"` with the first failing reason:
  - `find_quote(quote, pages)` finds it (`"quote not found in the PDF"`);
  - `float(value)` is in `numbers_in(quote)` (`"value not in the quote"`);
  - when `count` is not None, `float(count)` is in `numbers_in(quote)` (`"count not in the quote"`).
  A kept statement gets two new keys: `"found_page"` (the page `find_quote` gives) and `"quote_kind"`.
- The schedule is kept only when at least 95% of all its non-None row numbers are in
  `numbers_in(pages[page-2] + " " + pages[page-1] + " " + pages[page])`, using only the indexes from 0 to
  `len(pages) - 1` (a negative index is skipped, never wrapped). Else it is set
  to None and `{"what": "schedule", "reason": "schedule numbers not found on its page"}` goes to `"dropped"`. A kept
  schedule gets `"numbers_found_frac"`.
- Returns `{"statements": kept, "schedule": ..., "dropped": [{"what": quantity or "schedule", "page": page,
  "reason": text}], "rejected": extraction["rejected"]}`.

### run_checks(verified: dict, *, site_ghi_kwh_m2_yr: tuple[float, float] | None) -> list[CheckResult]

`CheckResult` is a frozen dataclass `(check_id: str, status: str, detail: str, pages: tuple[int, ...])`, status one
of `"flag"`, `"pass"`, `"not checkable"`. Returns exactly 15 results, one per id in `CHECK_IDS` order. `pages` is the
sorted unique `found_page` values (and the schedule page) the result uses. Every `detail` is ASCII, starts with
the evidence, and shows the numbers it compared with the units used (for example
`"pv_ac_kw: 990 kW (p11 text), 1,990 kW peak in schedule (p19)"`). Numbers in `detail` use `format(x, ",.4g")`.

Names below: `S(q)` = the kept statements of quantity q, in input order; `canon(s)` = its canonical value;
`rows` = the schedule rows (when there is a schedule); `col(c)` = the list of that column with None as 0, used only
when at least one row has a number in it.

- **P1 One quantity, one value.** For every quantity not in `SIZE_QUANTITIES` and not `cost_item_usd`, group `S(q)` by `condition`. A group
  of 2 or more fails when two members cannot be compared (unknown factor or different kinds) or when
  `max(canon) - min(canon) > 0.01 * min(abs(canon))`. Flag when any group fails (detail lists every failing group);
  pass when at least one group of 2 or more exists and none fails; else not checkable. `pages` are the found pages
  of every statement in a group of 2 or more (P6 the same).
- **P6 Sizes stated consistently.** The same rule as P1 over the 5 `SIZE_QUANTITIES` (grouped by quantity and
  condition). Flag when any fails; pass when a group of 2 or more exists; else not checkable.
- **P2 Energy balance.** Needs rows with `load_kw`. For each row: when `pv_to_load_kw` is not None,
  `supply = pv_to_load + diesel + discharge` (None as 0); else when `pv_total_kw` is not None,
  `supply = pv_total + diesel + discharge - pv_to_battery - curtailed`; else the row is skipped. A row fails when
  `abs(supply - load) > 0.02 * load` (and when load is 0, when supply > 0.001). Flag when any row fails (detail:
  count of failing rows of rows checked, then up to 8 rows as `time supply vs load`); pass when rows were checked
  and none failed; not checkable when no row could be checked.
- **P15 Time totals.** Hours per row = `period_h`. For each name in (`load`, `pv`, `diesel`):
  - schedule day total: `load` = sum of `load_kw`; `pv` = sum of `pv_total_kw` when any row has it, else sum of
    `pv_to_load_kw + pv_to_battery_kw`; `diesel` = sum of `diesel_kw`; each times `period_h`, and only when the
    schedule has `24 / period_h` rows (rounded) and the column has numbers.
  - compare each `S(name_kwh_day)` with the schedule day total; each `S(name_kwh_yr)` with the schedule day total
    x 365; each `S(name_kwh_yr)` with each `S(name_kwh_day)` x 365. A pair fails when the two differ by more than
    2% of the smaller. Flag when any pair fails; pass when a pair exists and none fails; else not checkable.
- **P3 PV yield is possible.** PV energy per year = the first of: `canon(S(pv_kwh_yr)[0])`;
  `canon(S(pv_kwh_day)[0]) * 365`; schedule pv day total (as in P15, and only when it is above 0) x 365. PV size
  in kWp = the first of:
  `canon(S(pv_dc_kwp)[0])`; `canon(S(pv_module_count)[0]) * canon(S(pv_module_wp)[0])` (W to kW by the power
  factor); `canon(S(pv_ac_kw)[0])`. `yield = energy / size`. Flag when `yield < low * 0.65` or `yield > high * 0.90`
  where `(low, high) = site_ghi_kwh_m2_yr`; else pass. Not checkable when energy, size or the site range is
  missing.
- **P4 Storage.** Needs rows where `pv_to_battery_kw` or `battery_discharge_kw` has numbers. `charge = sum
  pv_to_battery * period_h`, `out = sum battery_discharge * period_h`, `rte` = `canon(S(battery_rte_frac)[0])` else
  0.95. Flag when `out > charge * rte * 1.0`; else pass. Not checkable without both columns.
- **P5 Power within rating.** For PV: rating = max of `canon` over `S(pv_ac_kw)`; hourly PV = `pv_total_kw` when not
  None, else `pv_to_load_kw + pv_to_battery_kw + curtailed_kw` (None as 0). For diesel: rating = max `canon` over
  `S(diesel_kw)`, hourly = `diesel_kw`. For battery: rating = max over `S(battery_kw)`, hourly =
  `battery_discharge_kw`. A component fails when any hour is above `rating * 1.01`. Flag when any fails (detail:
  component, worst hour, its kW, rating); pass when at least one component had both a rating and hourly numbers;
  else not checkable.
- **P7 Area.** For each `S(pv_area_m2)` with `S(pv_module_count)` and `S(pv_module_area_m2)`: `ratio = canon(area)
  / (canon(count[0]) * canon(module_area[0]))`. Flag when any ratio is outside 1.0 to 3.0; pass when at least one
  ratio was computed; else not checkable.
- **P8 Resource input.** For each `S(ghi_kwh_m2_yr)` (canonical kWh/m2/yr): flag when below `low / 1.15` or above
  `high * 1.15`. Pass when at least one statement was checked and none flagged. Not checkable without statements
  or without the site range. (Wind has no independent source here, so wind is not checked by P8.)
- **P9 Costs add up.** Items are `S(cost_item_usd)`; an item's `condition` names the total it belongs to (one of
  `npc_usd`, `capex_usd`, `annual_cost_usd`). For each of those three totals that has both items and statements,
  `sum(canon(items))` is compared with each statement; a pair fails when they differ by more than 1% of the
  stated total. Flag when any pair fails; pass when a pair exists; else not checkable.
- **P10 Cost of energy recomputes.** Needs `S(npc_usd)`, `S(discount_rate_frac)`, `S(project_life_yr)`, an energy
  per year (first of `S(energy_served_kwh_yr)`, `S(load_kwh_yr)`) and `S(lcoe_usd_per_kwh)`. With the first of
  each: `crf = r * (1 + r) ** n / ((1 + r) ** n - 1)`, `lcoe_calc = npc * crf / energy`. Flag when any LCOE
  statement differs from `lcoe_calc` by more than 5% of `lcoe_calc`; else pass. Not checkable when any input is
  missing or `r` is 0.
- **P11 Economics reproducible.** Required: `discount_rate_frac`, `project_life_yr`, `om_cost_usd`, plus
  `pv_capex_usd_per_kw` when any PV size statement exists (`pv_ac_kw` or `pv_dc_kwp`), `battery_capex_usd_per_kwh`
  when `battery_size` is stated, and `diesel_capex_usd_per_kw` and `fuel_price_usd_per_l` when `diesel_kw` is
  stated. Flag (detail `"not reproducible: missing " + names`) when any required quantity has no kept statement;
  else pass. Never not checkable.
- **P12 Fuel use.** `fuel_l_yr[0] / diesel_kwh_yr[0]` (canonical): flag outside 0.20 to 0.45; else pass; not
  checkable when either is missing.
- **P13 Renewable fraction.** Computed share = `1 - diesel_kwh_yr[0] / served`, served = the first of
  `energy_served_kwh_yr`, `load_kwh_yr`. Flag when any `S(renewable_fraction_frac)` differs from it by more than
  0.02 (2 percentage points); else pass; not checkable when an input is missing.
- **P14 Emissions.** `co2_kg_yr[0] / fuel_l_yr[0]`: flag outside 2.5 to 2.8; else pass; not checkable when
  missing.

### summary(results: list[CheckResult]) -> dict

`{"flags": n, "passes": n, "not_checkable": n, "flagged_ids": [ids in order]}`.

## 5. Frozen checks (copied from prep, never edited)

P1 one quantity one value (1%); P2 energy balance (2%); P3 PV yield in site GHI x 0.65 to x 0.90; P4 battery out
not above in x round trip efficiency (stated, else 0.95); P5 power within rating (1%); P6 sizes consistent; P7 area
factor 1.0 to 3.0; P8 resource input within 15%; P9 costs add up (1%); P10 LCOE recomputes (5%); P11 economics
reproducible; P12 fuel 0.20 to 0.45 L/kWh; P13 renewable share within 2 points; P14 CO2 2.5 to 2.8 kg/L; P15 time
totals (2%). A check that lacks the numbers it needs reports "not checkable", which is not a flag (P11 aside, as
the frozen text says).

## Done when

- `tests/test_paper_check.py` passes, and every test that passed before still passes.
- `tools/check_text.py` passes on `autosolar/paper_check.py`; it stays ASCII; no import outside the list above.

## Test check by the orchestrator

- Reference build in scratch (the spec written as a reference `paper_check.py`): all 85 tests in
  `tests/test_paper_check.py` pass; the full suite with them passes 910 of 910 (825 then present plus 85 new).
- 34 planted faults, each caught: MW factor; day to year factor; USD not mapped; charge kind lost; bool value
  accepted; float count accepted; code fence not stripped; value check off; count check off; schedule kept at 50%;
  page index wraps; count ignored; 5% tolerance in P1; conditions merged; sizes in P1; P2 at 5%; P2 total form keeps
  the battery charge; P15 without 365; P15 ignores the time step; P3 upper bound 1.0; P3 uses a zero total; P4
  ignores the stated efficiency; P5 uses the smallest rating; P5 ignores PV to battery; P7 upper bound 5; P8 without
  the 15% margin; P9 at 5%; P10 without the capital recovery factor; P11 without O&M; P11 without the fuel price;
  P12, P13 and P14 ranges widened; summary counting passes as flags.
