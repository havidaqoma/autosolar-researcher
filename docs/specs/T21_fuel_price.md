# T21: try another diesel price on the study page

Status: spec by the orchestrator. Builder edits `autosolar/site.py` only. All earlier specs stay in force. The
orchestrator has written `tests/test_fuel_price.py`.

## Why

Judges called the study page a static report with no what-if. The diesel price is the input a reader most wants to
move, and the page can answer it exactly without new runs: dispatch never reads the fuel price, so each design's
fuel use stays the same at any price, and its LCOE moves in a straight line with the price. The page stays a static
file with no script (CSS radio buttons only), so it works on GitHub Pages and keeps the T13 rule.

## The maths (why it is exact)

In `autosolar/econ.py` (path B, the LCOE the study reports) the yearly cost holds `fuel_l * fuel_price_usd_per_l`
and the LCOE divides by the load served in kWh. So, for one design,

`lcoe(p) = lcoe(p0) + (p - p0) * fuel_l_per_yr / served_kwh`, with `served_kwh = demand_kwh_yr * (1 - unserved_frac)`

where `p0` is the study's fuel price. The design table holds `lcoe_usd_per_kwh` at `p0`, `fuel_l_per_yr` and
`unserved_frac`; the report holds `demand_kwh_yr`. The tests check this against the engine's own fuel price rows of
the sensitivity table on two real studies.

## autosolar/site.py

Constants:

- `FUEL_PRICE_STEPS_USD_PER_L = tuple(round(0.2 + 0.1 * k, 2) for k in range(15))` (0.2 to 1.6 USD/L).
- `MAX_PRICE_STEPS = 24`.
- `FUEL_PRICE_CSS`: a string, appended inside the study page's one `<style>` element right after `SITE_CSS` (so the
  page still holds exactly one `<style>`). It holds these rules, and for every `i` in `range(MAX_PRICE_STEPS)` the
  two rules `"#fp%d:checked~.fp-outs #fpo%d{display:block}" % (i, i)` and
  `"#fp%d:checked~.fp-labels label[for=fp%d]{background:#1f5f99;color:#fff}" % (i, i)`:
  `.fp input{position:absolute;opacity:0;width:1px;height:1px}`,
  `.fp-labels label{display:inline-block;padding:4px 8px;margin:2px;border:1px solid #999;border-radius:4px;cursor:pointer}`,
  `.fp-out{display:none;margin:8px 0}`.
  The index page does not get these rules.

### price_grid(study_price_usd_per_l) -> list[float]

Finite real above 0 (`bool` refused), else `ValueError`. Returns `FUEL_PRICE_STEPS_USD_PER_L` as a list, plus the
study price when no step is within 1e-9 of it, sorted ascending.

### study_price_inputs(report) -> dict

Returns `{"fuel_price_usd_per_l", "unserved_max_frac", "demand_kwh_yr"}` as floats: the first two from the
`report["inputs_table"]` rows with those `name`s (their `value`), the last from
`report["facts"]["demand_kwh_yr"]["value"]`. A missing row or value gives `ValueError`.

### fuel_price_steps(table, *, study_price_usd_per_l, demand_kwh_yr, unserved_max_frac, prices_usd_per_l) -> list[dict]

- `table`: a non-empty DataFrame with the columns `pv_kwp`, `battery_kwh`, `lcoe_usd_per_kwh`, `fuel_l_per_yr`,
  `unserved_frac`, `renewable_fraction_frac`, holding a diesel only row (`pv_kwp == 0` and `battery_kwh == 0`).
  `study_price_usd_per_l` and `demand_kwh_yr`: finite reals above 0. `unserved_max_frac`: finite real from 0 to 1.
  `prices_usd_per_l`: a non-empty list or tuple of at most `MAX_PRICE_STEPS` finite reals above 0. `bool` is refused
  everywhere. Else `ValueError`. The table is never changed.
- For each price `p`, in the given order: a copy of the table with `lcoe_usd_per_kwh` replaced by `lcoe(p)` above;
  `best = autosolar.sweep.least_cost(copy, unserved_max_frac)` (the study's own feasibility and tie rule; its
  `ValueError` when no row is feasible passes through); the diesel only row is the first one in the copy.
- One dict per price with exactly:
  - `price_usd_per_l` (float), `diesel_only_lcoe_usd_per_kwh`,
  - `best_pv_kwp`, `best_battery_kwh`, `best_lcoe_usd_per_kwh`, `best_renewable_pct`
    (`100 * renewable_fraction_frac`),
  - `saving_pct`: `100 * (1 - best_lcoe / diesel_only_lcoe)`,
  - `diesel_only_wins`: `True` when the best row has `pv_kwp == 0` and `battery_kwh == 0`,
  - `on_grid_edge`: `True` when not `diesel_only_wins` and the best `pv_kwp` equals the table's largest `pv_kwp` or
    the best `battery_kwh` equals the table's largest `battery_kwh`,
  - `is_study_price`: `abs(p - study_price_usd_per_l) <= 1e-9`.
  Numbers are Python floats, flags Python bools.

### fuel_price_section(report, table) -> str

`inputs = study_price_inputs(report)`, `prices = price_grid(p0)`, `steps = fuel_price_steps(...)`, `n = len(table)`.
Returns, with all text through `esc` and numbers through `fmt`:

```
<section id="fuel-price"><h2>Try another diesel price</h2>
<p>INTRO</p>
<div class="fp">
INPUTS (one per step, in order: <input type="radio" name="fp" id="fpI"> with " checked" before ">" on the study
        price step only)
<div class="fp-labels">LABELS (<label for="fpI">TEXT</label>; TEXT is fmt(p, 2), plus " (study)" on the study price)</div>
<div class="fp-outs">OUTS (<p class="fp-out" id="fpoI">LINE</p>)</div>
</div>
<p>FOOT</p></section>
```

(no newlines needed; the order of the parts is what matters). `I` counts from 0.

- INTRO: `"Pick a diesel price in USD per litre. The page re-costs all " + fmt(n, 0) + " designs of this study at that
  price; every other input stays as in the study, which used " + fmt(p0, 2) + " USD/L."`
- LINE when not `diesel_only_wins`: `"At " + fmt(p, 2) + " USD/L: diesel only costs " + fmt(d0, 3) + " USD/kWh. The
  least cost design is " + fmt(pv, 0) + " kWp of PV and " + fmt(bat, 0) + " kWh of battery at " + fmt(best, 3) +
  " USD/kWh, " + fmt(saving, 1) + "% less, with " + fmt(ren, 0) + "% of the energy from the sun (computed)."`, and
  when `on_grid_edge` add `" It sits on the edge of the design grid, so a larger design may cost less."`
- LINE when `diesel_only_wins`: `"At " + fmt(p, 2) + " USD/L: diesel only, at " + fmt(d0, 3) + " USD/kWh, is the
  least cost choice; no design with PV or battery beats it (computed)."`
- FOOT: `"How: a design's fuel use does not depend on the price, so its cost moves in a straight line with it. At 20%
  below and above the study price these are the same numbers as the fuel price rows of What moves the cost."` and,
  when `report["facts"]["break_even_fuel_usd_per_l"]["value"]` is not None,
  `" Below " + fmt(value, 2) + " USD/L, diesel only is cheapest (break-even from the study)."`

### render_study_html

Always adds `fuel_price_section(report, table)` right after the answer section's closing `</section>` (before the
`firm` section, or before `designs` when there is no firmness). No `<script>`, ASCII only. Everything else on the
page stays as it was.

## Acceptance

`tests/test_fuel_price.py` passes, and the full suite still passes. Muse must not edit specs, tests or config.

## Test record (added by the orchestrator after the build)

- Before Muse Code ran, the 44 tests passed on a throwaway reference build in a scratch folder (never committed),
  and the site and study tests still passed with it (265 tests).
- Muse Code build: 44 of 44 pass (915 s, USD 0.017, measured, `ledger/build_usage.jsonl`).
- Planted faults in `autosolar/site.py`: 10 of 11 caught at first. The missed one marked the grid edge by PV size
  only. One test (`test_battery_edge_alone_counts`) was added after the code and is labelled so in the test file;
  then 11 of 11 caught, 45 tests.
