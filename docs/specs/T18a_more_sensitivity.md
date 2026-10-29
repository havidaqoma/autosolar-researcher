# T18a: more inputs in "What moves the cost", plain labels, and the two alt checks widen the grid

Status: spec by the orchestrator. Builder edits `autosolar/sweep.py`, `autosolar/firmness.py`, `autosolar/study.py`
and `autosolar/site.py` only. All earlier specs stay in force except where this spec changes them. The orchestrator
has written `tests/test_t18a.py` and changed four old tests (listed at the end).

## Why

- The second model review of the curated study and three outside reads of the entry: the diesel fuel curve and
  diesel O&M are assumed, yet they are not in the sensitivity table. Battery hours are only in the duration check.
- Curated study: the diesel unit size check (2.7 MW units) picked 9,000 kWp, the largest PV size on the grid, so its
  least cost design may be larger. The main design search widens its grid when the answer sits on the edge; the
  diesel unit size check and the battery duration check do not.
- The bar labels of "What moves the cost" are raw input names and run into the bars.

## 1. sweep.py

### 1a. Grid helpers (public, same rules as the private ones in study.py)

- `size_grid(step, top) -> list[float]`: `count = round(top / step)`, returns `[float(i * step) for i in
  range(count + 1)]`. `step` must be a finite real number above 0 and `top` a finite real number of at least 0;
  `bool` and non numbers are refused. Else `ValueError` naming the argument.
- `widen_grid(grid, step) -> list[float]`: `top = max(grid)`, `grown = ceil(top * 1.5 / step - 1e-9) * step`,
  returns `size_grid(step, grown)`. Empty `grid` or a bad `step` raises `ValueError`.
- `study._size_grid` and `study._widen_grid` keep their names and give the same results (they may call these).

### 1b. sensitivity_table

`SENSITIVITY_INPUTS` gains four names at the end, in this order:

```
"diesel_om_usd_per_kwh", "fuel_intercept_l_per_h_per_kw_rated", "fuel_slope_l_per_kwh", "battery_duration_h"
```

So the table has 9 inputs and 18 rows (factor `1 - swing` then `1 + swing` for each input, as before).

- `diesel_om_usd_per_kwh` is a `CostInputs` field: scaled like the other cost inputs, on the base dispatch.
- `fuel_intercept_l_per_h_per_kw_rated` and `fuel_slope_l_per_kwh` are `DieselFleet` fields: the fleet with that
  one field times the factor (`dataclasses.replace`), a new `dispatch_grid` on the base load and base battery hours,
  then `cost_table` with the base costs.
- `battery_duration_h`: a new `dispatch_grid` with `battery_hours` times the factor, base fleet and base costs.
- Every other rule of the table is unchanged: `base_design_lcoe_usd_per_kwh` is the LCOE of the base least cost
  design (same row index) in the case table, `same_design`, the `"no feasible design"` row, the columns.
- The inputs passed in (costs, fleet) are never changed.

## 2. firmness.py: the alt checks widen the grid

`diesel_size_case` and `duration_case` get three new keyword-only arguments:

```
pv_step_kwp: float | None = None, battery_step_kwh: float | None = None, widen_max: int = 0
```

- `widen_max` must be an `int` of at least 0 (`bool` refused), else `ValueError`. When `widen_max > 0`, both steps
  must be finite real numbers above 0, else `ValueError("grid steps are required to widen")`. Checks run before any
  dispatch.
- After the first search: while the least cost design is on the grid edge (`on_grid_edge`) and fewer than
  `widen_max` widenings were made: widen the PV grid with `widen_grid(pv_grid, pv_step_kwp)` when the design's PV
  size equals the largest PV size of the grid, widen the battery grid the same way when its battery size equals the
  largest battery size, run the dispatch and cost table again on the new grids, pick the least cost design again,
  and count one widening. This is the rule the main search in `study.py` already uses.
- `diesel_size_case` runs its `reserve_case` on the final grids. Its diesel only LCOE is the 0 kWp, 0 kWh row.
- `on_grid_edge` in the result is judged on the final table.
- Both result dicts gain `"widened"`: the number of widenings made (0 when the first search finds no feasible
  design, and 0 with the default `widen_max=0`, which keeps the old behaviour exactly).

## 3. study.py

- `REPORT_SCHEMA = "autosolar.report/2"`: the report's sensitivity table changed, so runs made before this task are
  not reused for new runs.
- The calls to `diesel_size_case` and `duration_case` pass `pv_step_kwp` and `battery_step_kwh` (the study's grid
  steps from the inputs file) and `widen_max=2`.
- Nothing else changes; the firmness items keep their keys.

## 4. site.py

- New constant `SENSITIVITY_LABELS`:

| input | label |
|---|---|
| pv_capex_usd_per_kwp | PV price |
| battery_capex_usd_per_kwh | Battery price |
| fuel_price_usd_per_l | Diesel price |
| discount_rate_frac | Discount rate |
| demand | Demand |
| diesel_om_usd_per_kwh | Diesel O&M |
| fuel_intercept_l_per_h_per_kw_rated | Diesel idle fuel |
| fuel_slope_l_per_kwh | Diesel fuel per kWh |
| battery_duration_h | Battery hours |

- `tornado_svg`: each bar's text is `"<label>: <low> to <high> USD/kWh"` with the label from `SENSITIVITY_LABELS`,
  or the raw input name when it has none (escaped as all text is). The SVG is 720 wide; bars run from x 340 to
  x 700; the text starts at x 8. Order, widths, the base line and everything else stay as they are.
- `render_study_html`: right after the tornado, inside the sensitivity section, one paragraph:
  `Each bar moves one input down and up by the swing in the inputs table and shows the LCOE of the chosen design.`

## Done when

- `tests/test_t18a.py` and the rest of the suite pass.
- Text gate passes; ASCII only.

## Old tests changed by the orchestrator (for this spec only)

- `tests/test_sweep.py`: the input tuple, 18 rows, the factor list, and the value loop skips the three rows that
  need a new dispatch (they are checked in `test_t18a.py`).
- `tests/test_study.py`: `REPORT_SCHEMA` is `autosolar.report/2`; the sensitivity table has 18 rows.
- `tests/test_site.py`: `test_tornado` looks for the plain labels.
