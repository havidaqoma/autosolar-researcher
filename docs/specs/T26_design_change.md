# T26: which inputs would change the design

Status: spec and acceptance tests written first, by hand, after a literature round (prep, 1 Nov) and the owner's
go-ahead. Muse Code edits `autosolar/site.py` only. The acceptance tests are `tests/test_design_change.py`. No study
and no other module changes. After the code, the site is re-rendered with `tools/make_site.py` and the full suite is
run.

## Why

"Confirm these first" ranks inputs by how far a 20% move shifts the cost of the main design. That answers "how
sure is the price?". Before building, a second question matters more: if an input is wrong, would a different
plant be cheaper? A wide cost swing does not mean the choice changes. Langtry and Choudhary (Applied Energy 2025,
doi 10.1016/j.apenergy.2025.126549) found that load uncertainty moved the cost of a PV and battery system by about
30% (paper), yet knowing the load exactly was worth only 1.27% of lifetime cost (paper). They also note that this
kind of value only makes sense for inputs that can be measured before deciding.

Each study already holds the answer. For every input moved down and up, `report["sensitivity_table"]` keeps the
main design's cost at that value and the least cost design found by the same sweep at that value. In the example
study, the load 20% lower makes the main design cost 8.8% more than the best design for that load (6,000 kWp and
15,000 kWh); every other input stays under 0.4% (computed). This task shows that on every study page. No new
simulation: the numbers come from `report.json` only.

## 1. autosolar/site.py

### Constants

```
DESIGN_CHANGE_MIN_FRAC = 0.01
DESIGN_CHANGE_TOL = 1e-9
```

### design_change_rows(report) -> list[dict]

- `report` must be a dict, else `ValueError`. `table = report.get("sensitivity_table", [])`; it must be a list, else
  `ValueError`.
- A row of `table` is used only when all of these hold; any other row is skipped with no error (for example the
  rows with the note "no feasible design", whose least cost fields are NaN):
  - the row is a dict;
  - `input` is a non-empty `str`;
  - `factor` is a finite real, not `bool`, and not equal to 1.0;
  - `base_design_lcoe_usd_per_kwh` and `least_cost_lcoe_usd_per_kwh` are finite reals, not `bool`, above 0;
  - `least_cost_pv_kwp` and `least_cost_battery_kwh` are finite reals, not `bool`, 0 or more;
  - `same_design` is a `bool`.
- For a used row, `extra = base_design_lcoe_usd_per_kwh / least_cost_lcoe_usd_per_kwh - 1.0`. If
  `extra < -DESIGN_CHANGE_TOL`, raise `ValueError` with "least cost" in the message (the least cost design can
  never cost more than the main design at the same input value). Otherwise `extra = max(extra, 0.0)`.
- For each input, in order of its first used row, keep the used row with the largest `extra`. Equal values keep
  the earlier row.
- Returns a list with one dict per kept input, with exactly the keys `input` (str), `factor` (float),
  `extra_frac` (float, the `extra` above), `pv_kwp` (float, `least_cost_pv_kwp`), `battery_kwh` (float,
  `least_cost_battery_kwh`) and `same_design` (bool). The list is sorted by `extra_frac`, largest first; equal values
  keep the order of first appearance (a stable sort).
- `report` is never changed.

### design_change_section(report) -> str

- `rows = design_change_rows(report)`. When `rows` is empty, return `""`.
- Otherwise return `'<section id="design-change"><h2>Which inputs would change the design?</h2>'` + the parts
  below + `"</section>"`. All text goes through `esc`. Let `M = fmt(100 * DESIGN_CHANGE_MIN_FRAC, 0)` and
  `L(name) = SENSITIVITY_LABELS.get(name, name)`.
  1. `"<p>" + esc(T1) + "</p>"` with `T1` exactly:
     `"Confirm these first ranks inputs by how far they move the cost. Before building, a second question matters
     more: if an input is wrong, would another design be cheaper? For each input moved down and up, the study also
     found the least cost design at that value. The table shows how much more the main design costs than that
     design, for the worse of the two moves (computed)."`
  2. `_table(["Input", "Moved", "Least cost design at that value", "Main design costs more by"], cells)` with one
     row per item of `rows`, in order:
     - Input: `L(input)`;
     - Moved: `"down " + fmt(100 * (1 - factor), 0) + "%"` when `factor < 1`, else
       `"up " + fmt(100 * (factor - 1), 0) + "%"`;
     - Least cost design: `"Same as the main design"` when `same_design` is True, else
       `fmt(pv_kwp, 0) + " kWp and " + fmt(battery_kwh, 0) + " kWh"`;
     - Main design costs more by: `fmt(100 * extra_frac, 1) + "%"`.
  3. `big` = the labels `L(input)` of the items with `extra_frac >= DESIGN_CHANGE_MIN_FRAC`, in table order.
     - When `big` has one label: `"<p>" + esc(T3) + "</p>"` with
       `T3 = "Confirm before sizing the plant: " + big[0] + ". If this input is off by the amount above, the main
       design costs " + M + "% or more above the best design for that case. The other inputs move the price more
       than the plan (computed; the " + M + "% line is assumed)."`
     - When `big` has two or more labels: the same, with `", ".join(big)` in place of `big[0]` and
       `"If these inputs are off by the amounts above"` in place of `"If this input is off by the amount above"`.
     - When `big` is empty: `"<p>" + esc(T3) + "</p>"` with
       `T3 = "No input moved this way makes the main design cost " + M + "% or more above the best design for that
       case: the inputs move the price more than the plan (computed; the " + M + "% line is assumed)."`
  4. `"<p>" + esc(T4) + "</p>"` with `T4` exactly:
     `"This is the cost of a wrong input at one point each way, not an expected value: the study puts no odds on
     the inputs. Some inputs, such as the future diesel price, cannot be measured before building; for those, read
     the table as a check that the choice still holds."`

### render_study_html

Right after the `confirm_section(...)` call, append `design_change_section(report)` (an empty string adds nothing).
So the new section comes after "Confirm these first" and before the optional resources section and "How firm is
the answer". Nothing else on the page changes. ASCII only, no `<script>`.

## Rules for this task

- Muse Code edits `autosolar/site.py` only. It must not edit specs, tests or config.
- No network, no file writes, no new dependency.
- Units stay in names; bad input raises `ValueError` as stated above.

## Acceptance

`tests/test_design_change.py` passes. `tests/test_engineer_files.py::test_page_otherwise_unchanged_from_committed_page`
now also cuts the `design-change` section before comparing (changed with this spec, labelled in the test), so it
keeps checking that nothing else on the page changes. After the site is re-rendered, the full suite passes.

## Record (after the code)

- Before Muse Code ran: a reference build outside the repo passed all 46 tests in `tests/test_design_change.py`,
  then `autosolar/site.py` was restored from git.
- Muse Code: one run, 906 s, USD 0.012 (measured, `ledger/build_usage.jsonl`), edited `autosolar/site.py` only.
- Planted faults on Muse Code's build, one at a time: 9 of 9 caught (tie keeps later row, ascending sort, loose
  tolerance, factor 1 kept, line exclusive, up and down swapped, negative PV kept, non-bool same_design kept,
  section not placed). No test was added after the code.
