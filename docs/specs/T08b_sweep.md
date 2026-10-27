# T08b: design grid, least cost search and sensitivity (`autosolar/sweep.py`)

## Why

Stages S6 and S6b: run the hourly dispatch (T07) for a grid of PV sizes and battery sizes, cost every design with
both LCOE paths (T08), pick the least cost design, flag it when it sits on the edge of the grid (then the grid
must be widened), find the diesel price below which diesel only would still win, and check whether the choice
holds when the main inputs move by 20%.

## Allowed extra dependencies

None beyond `AGENTS.md`. No network. Uses `autosolar.dispatch` and `autosolar.econ` (do not change them).

## Public API

```python
from autosolar.sweep import (GridPoint, dispatch_grid, cost_table, TABLE_COLUMNS, least_cost, on_grid_edge,
                             high_renewable, break_even_fuel_price_usd_per_l, sensitivity_table,
                             SENSITIVITY_COLUMNS, SENSITIVITY_INPUTS)
```

```python
@dataclass(frozen=True)
class GridPoint:
    design: Design            # autosolar.econ.Design
    result: DispatchResult    # autosolar.dispatch.DispatchResult
```

### `dispatch_grid(pv_ac_kw_per_kwp, load_kw, pv_kwp_grid, battery_kwh_grid, *, battery_hours, battery_template, diesel) -> list[GridPoint]`

- `pv_ac_kw_per_kwp`: hourly AC output of 1 kWp (the `ac_kw` column of `simulate_pv` with `pdc0_kw=1.0`), a
  `pandas.Series`; `load_kw`: hourly load, same index (index checks are left to `dispatch`).
- `pv_kwp_grid`, `battery_kwh_grid`: lists or tuples of finite numbers (not bool), strictly increasing, the first
  value exactly 0 (so the diesel only design is always in the grid); the PV grid has at least 2 values, the
  battery grid at least 1 (it may be just `[0]`). Else `ValueError`.
- `battery_hours`: finite number > 0; the battery power of a design is `battery_kwh / battery_hours`.
- `battery_template`: a `Battery`; its `round_trip_eff_frac`, `soc_min_frac` and `soc_initial_frac` are used,
  its `energy_kwh` and `power_kw` are ignored. For `battery_kwh == 0` use `energy_kwh=0, power_kw=0`.
- `diesel`: a `DieselFleet`, the same for every design.
- Order: PV outer loop, battery inner loop (`for pv in pv_kwp_grid: for b in battery_kwh_grid:`). For each pair
  call `dispatch(pv_ac_kw_per_kwp * pv, load_kw, battery, diesel)` and keep
  `GridPoint(Design(pv_kwp=float(pv), battery_kwh=float(b), battery_kw=float(b) / battery_hours), result)`.

### `cost_table(points, costs, co2_kg_per_l) -> pandas.DataFrame`

One row per point, same order, default `RangeIndex`, columns `TABLE_COLUMNS` in this order:

`("pv_kwp", "battery_kwh", "battery_kw", "lcoe_usd_per_kwh", "lcoe_path_a_usd_per_kwh", "npc_usd",
"capex_initial_usd", "fuel_l_per_yr", "diesel_kwh_per_yr", "co2_t_per_yr", "renewable_fraction_frac",
"unserved_frac", "pv_curtailed_frac", "diesel_starts", "diesel_run_hours")`

Values from `econ.evaluate(point.design, AnnualFlows(r.load_served_kwh, r.fuel_l, r.diesel_kwh), costs,
co2_kg_per_l)` and from the dispatch result `r`. `pv_curtailed_frac = r.pv_curtailed_kwh / r.pv_available_kwh`,
0 when `pv_available_kwh == 0`. `diesel_starts` and `diesel_run_hours` are int64; all other columns float64.
`LcoeTwinMismatch` from `evaluate` propagates. Empty `points`: `ValueError`.

### Picking designs

- `least_cost(table, unserved_max_frac) -> pandas.Series`: among rows with `unserved_frac <= unserved_max_frac`
  (feasible), the row with the lowest `lcoe_usd_per_kwh`; ties go to the earliest row. Return the row as
  `table.loc[label]`, so `row.name` is its index label (the same holds for `high_renewable`). `unserved_max_frac`
  finite in [0, 1]. No feasible row: `ValueError`.
- `on_grid_edge(table, row) -> bool`: True when `row.pv_kwp == table.pv_kwp.max()` or
  `row.battery_kwh == table.battery_kwh.max()`. (0 is a natural lower bound, so the low edge is not flagged.)
- `high_renewable(table, rf_target_frac, unserved_max_frac) -> pandas.Series | None`: among feasible rows with
  `renewable_fraction_frac >= rf_target_frac`, the lowest LCOE row (ties: earliest); `None` when there is none.
  `rf_target_frac` finite in [0, 1].

### `break_even_fuel_price_usd_per_l(points, costs, co2_kg_per_l, unserved_max_frac) -> float`

The fuel price below which the diesel only design (the point with `pv_kwp == 0` and `battery_kwh == 0`) is the
least cost feasible design. Every LCOE is a straight line in the fuel price `p`: `lcoe(p) = a + s * p` with
`a` = the LCOE at `p = 0` (evaluate with `fuel_price_usd_per_l=0.0`, via `dataclasses.replace`) and
`s = fuel_l / load_served_kwh`. With `a0, s0` for diesel only: for every other feasible point with `s < s0`,
`p_i = (a_i - a0) / (s0 - s_i)`. Return `max(0.0, min(p_i))`; return `math.inf` when no feasible point has
`s < s0`. The diesel only point must be feasible, else `ValueError`.

### `sensitivity_table(pv_ac_kw_per_kwp, load_kw, pv_kwp_grid, battery_kwh_grid, *, battery_hours, battery_template, diesel, costs, co2_kg_per_l, unserved_max_frac, swing_frac=0.2) -> pandas.DataFrame`

`SENSITIVITY_INPUTS = ("pv_capex_usd_per_kwp", "battery_capex_usd_per_kwh", "fuel_price_usd_per_l",
"discount_rate_frac", "demand")`. `swing_frac` finite in (0, 1).

First find the base least cost design (dispatch grid, cost table, `least_cost`). Then for each input in that
order and each factor in `(1 - swing_frac, 1 + swing_frac)` in that order, build one row:

- cost inputs: `dataclasses.replace(costs, **{name: value * factor})`, re cost the SAME dispatched points;
- `"demand"`: dispatch the grid again with `load_kw * factor`, then cost it with the base costs.

Columns `SENSITIVITY_COLUMNS` in this order: `("input", "factor", "base_design_lcoe_usd_per_kwh",
"least_cost_pv_kwp", "least_cost_battery_kwh", "least_cost_lcoe_usd_per_kwh", "same_design", "note")`.
`base_design_lcoe_usd_per_kwh` is the LCOE of the base least cost design (same pv_kwp and battery_kwh) in that
case. `same_design` is True when the case's least cost design equals the base one. When a case has no feasible
row, the three `least_cost_*` values are NaN, `same_design` is False and `note` is `"no feasible design"`;
otherwise `note` is `""`. 10 rows, default `RangeIndex`.

## Done when

`uv run pytest` passes (all tests, including earlier tasks) and `AGENTS.md` rules hold.

## Test check by the orchestrator

The tests in `tests/test_sweep.py` were run against a throwaway reference implementation of this spec, on top of
the throwaway T07 and T08 references (kept outside the repo): 22 of 22 passed. So a failing test means the code
differs from this spec.
