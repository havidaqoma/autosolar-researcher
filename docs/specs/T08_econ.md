# T08: cost of electricity (`autosolar/econ.py`)

## Why

Stage S6 ranks designs by levelised cost of electricity (LCOE). Gate G8 asks for two independent code paths that
must agree to 0.1%: path A sums discounted yearly cash flows, path B uses the capital recovery factor (CRF). A
slip in one path (a wrong discount rate, a missed replacement) then shows up as a mismatch instead of a silent
wrong number. The existing diesel plant is treated as already paid for (its capital cost is sunk); diesel enters
through fuel and a variable O&M cost per kWh.

## Allowed extra dependencies

None beyond `AGENTS.md`. No network.

## Public API

```python
from autosolar.econ import (CostInputs, Design, AnnualFlows, EconResult, LcoeTwinMismatch, LCOE_TWIN_TOL_FRAC,
                            crf, component_schedule, lcoe_path_a, lcoe_path_b, evaluate)
```

```python
LCOE_TWIN_TOL_FRAC = 0.001

class LcoeTwinMismatch(RuntimeError): ...

@dataclass(frozen=True)
class CostInputs:
    pv_capex_usd_per_kwp: float
    pv_om_usd_per_kwp_yr: float
    pv_life_yr: int
    battery_capex_usd_per_kwh: float
    battery_power_capex_usd_per_kw: float
    battery_om_usd_per_kwh_yr: float
    battery_life_yr: int
    diesel_om_usd_per_kwh: float
    fuel_price_usd_per_l: float
    discount_rate_frac: float
    project_life_yr: int
    currency_year: int

@dataclass(frozen=True)
class Design:
    pv_kwp: float
    battery_kwh: float
    battery_kw: float

@dataclass(frozen=True)
class AnnualFlows:            # one year of operation, from the dispatch (T07)
    load_served_kwh: float
    fuel_l: float
    diesel_kwh: float
```

Checks (`ValueError` naming the field), run by every public function that takes the object: money and quantity
fields finite and >= 0 (`bool` is never a number); `discount_rate_frac` in [0, 0.5]; `pv_life_yr`,
`battery_life_yr`, `project_life_yr` ints (not bool) in 1..60; `currency_year` int in 2000..2100;
`load_served_kwh > 0`.

### Functions

- `crf(rate_frac: float, years: int) -> float`: `rate * (1 + rate) ** years / ((1 + rate) ** years - 1)`, and
  `1 / years` when `rate == 0`. Same checks as above (`rate` in [0, 0.5], `years` int in 1..60).
- `component_schedule(capex_usd: float, life_yr: int, project_life_yr: int) -> tuple[list[tuple[int, float]],
  float]`: replacement events and the salvage value at the end of the project. A component is installed in
  year 0 and replaced (same cost, no price change) in every year `k * life_yr` with `k >= 1` and
  `k * life_yr < project_life_yr`. The last unit installed (year `last`) has `remaining = life_yr -
  (project_life_yr - last)` years left at the end; salvage = `capex_usd * remaining / life_yr` when
  `remaining > 0`, else 0. Returns `([(year, capex_usd), ...], salvage_usd)`. With `capex_usd == 0` the list is
  still returned with zero costs (or may be empty) and salvage is 0.
- Shared quantities for both paths, for a design `d`, flows `f` and costs `c`:
  - initial capital `capex0 = d.pv_kwp * c.pv_capex_usd_per_kwp + d.battery_kwh * c.battery_capex_usd_per_kwh +
    d.battery_kw * c.battery_power_capex_usd_per_kw`;
  - PV and battery are separate components: `component_schedule(pv capex, pv_life_yr, N)` and
    `component_schedule(battery capex (energy plus power part), battery_life_yr, N)`, `N = project_life_yr`;
  - yearly cost `annual = d.pv_kwp * c.pv_om_usd_per_kwp_yr + d.battery_kwh * c.battery_om_usd_per_kwh_yr +
    f.fuel_l * c.fuel_price_usd_per_l + f.diesel_kwh * c.diesel_om_usd_per_kwh`, the same in years 1..N;
  - energy `f.load_served_kwh` in each of years 1..N.
- `lcoe_path_a(d, f, c) -> float` (USD per kWh): build the cash flow of every year `y = 0..N` (year 0: `capex0`;
  years 1..N: `annual` plus the replacement costs that fall in that year; year N also minus both salvage values),
  then `sum(cf[y] / (1 + r) ** y) / sum(E / (1 + r) ** y for y in 1..N)`. Path A must NOT call `crf`.
- `lcoe_path_b(d, f, c) -> float` (USD per kWh): net present cost `npc = capex0 + sum(cost / (1 + r) ** year
  over the replacement events) - (salvage_pv + salvage_battery) / (1 + r) ** N + annual / crf(r, N)`, then
  `npc * crf(r, N) / E`. Path B must NOT loop over the years 1..N.
- `evaluate(d, f, c, co2_kg_per_l: float) -> EconResult`: computes both paths; if
  `abs(a - b) / b > LCOE_TWIN_TOL_FRAC` raise `LcoeTwinMismatch` with both values in the message (gate G8).
  `evaluate` must call `lcoe_path_a` and `lcoe_path_b` through the module (plain calls by name), so a test can
  replace one of them. `co2_kg_per_l` finite and >= 0.

```python
@dataclass(frozen=True)
class EconResult:
    lcoe_usd_per_kwh: float          # path B
    lcoe_path_a_usd_per_kwh: float
    lcoe_path_b_usd_per_kwh: float
    twin_gap_frac: float             # abs(a - b) / b
    npc_usd: float                   # path B net present cost
    capex_initial_usd: float         # capex0
    annual_cost_usd: float           # annual
    fuel_cost_usd_per_yr: float      # f.fuel_l * c.fuel_price_usd_per_l
    co2_t_per_yr: float              # f.fuel_l * co2_kg_per_l / 1000
    currency_year: int
```

## Done when

`uv run pytest` passes (all tests, including earlier tasks) and `AGENTS.md` rules hold.

## Test check by the orchestrator

The tests in `tests/test_econ.py` were run against a throwaway reference implementation of this spec (kept
outside the repo): 45 of 45 passed. Expected values in the tests are hand arithmetic. So a failing test means the
code differs from this spec.
