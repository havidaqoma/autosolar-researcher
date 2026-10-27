# T10c: the study reads the sourced inputs; report polish (`autosolar/study.py`)

## Why

T10b writes a sourcing file (`autosolar.sourcing/1`) whose inputs passed gate G6. The study must be able to run on
it, show which inputs are sourced and why the others stay assumed, and carry G6 in its checks. The first live
report (`docs/examples/T09_karimunjawa_report.md`) also reads badly: raw fact keys, gate details with 16 digits,
and two range rows that sit on the grid edge with no flag. This task changes `autosolar/study.py` only. Everything
in `docs/specs/T09b_study.md` still holds except where this spec says otherwise.

## Allowed dependencies

As `AGENTS.md`, plus `autosolar.sourcing` (T10b). No network in tests.

## Changes

### 1. New keyword `sourcing_path`

`run_study(question, *, client, http_get, weather_fn, inputs_path, runs_dir, run_id, sourcing_path=None)`.

Right after `values, raw = load_inputs(inputs_path)` (step 1, before the request cache, the model or the
geocoder), when `sourcing_path` is not None:

- `s_raw, s_rows, s_meta = autosolar.sourcing.read_sourcing(sourcing_path)` (it raises `ValueError` itself when
  the file fails G6; let it propagate).
- If `s_raw != raw`: raise `ValueError("inputs file does not match the sourcing file")`.

### 2. Run hash

`_run_hash` payload: unchanged when `sourcing_path` is None (so earlier run hashes stay the same). With a sourcing
file the payload dict gets one more key, `"sourcing": [dataclasses.asdict(r) for r in s_rows]`; same
`json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=True)`, sha256, first 16 hex characters.

### 3. Gate G6

With a sourcing file only: right after the `"G5 weather spread"` row, add
`_gate("G6 sourced inputs", "inputs", ok, detail)` with `ok, detail = g6_check(s_rows, raw)`. If not ok, raise
`GateFailed("gate failed: G6 sourced inputs: " + detail)`. Without a sourcing file there is no G6 row (the gate
order of T09b is unchanged).

### 4. Report key `sourcing`

`report["sourcing"]` is None without a sourcing file. With one it is `{"meta": s_meta, "rows": rows}` where each
row is `dataclasses.asdict(r)` plus `"cells"`:

```python
[r.input, r.status, str(r.value_used), r.unit, r.label,
 "none" if r.value_as_written is None else format(r.value_as_written, "g") + " " + r.unit_as_written,
 r.title or "none", r.url or "none", "none" if r.page is None else str(r.page), r.quote_kind,
 "; ".join(r.reasons) or "none"]
```

### 5. Sources

With a sourcing file, after the weather notes, append one string per row with `status == "checked"`, in row
order: `"Sourced input " + r.input + ": " + (r.title or "untitled") + ", " + r.url` plus `", doi:" + r.doi`
when `r.doi` is a non-empty str.

### 6. Markdown: `## Sourced inputs`

`render_markdown` reads `report.get("sourcing")` (older reports have no key). When it is not None, insert this
block after the Inputs table and before `## Sources`:

```
## Sourced inputs

<c> of <n> inputs were sourced by web search and checked: the quote was found in the fetched source, the value appears in the quote, the DOI resolves when one is given, and the support judge (<judge>) agreed. The others keep their assumed value; the last column says why.

| Input | Status | Value used | Unit | Label | As written | Source | URL | Page | Quote match | Why kept assumed |
|---|---|---|---|---|---|---|---|---|---|---|
| <cells> |                                       one line per row
```

`c` = rows with status `"checked"`, `n` = all rows, `judge` = `meta["judge"]` when it is a str, else
`"not named"`. Cells and the judge name go through the same ASCII cleaning as every other inserted string.

### 7. Readable answer lines

New constant `FACT_TITLES: dict[str, str]`, keys in the same order as `FACT_SPECS`, values exactly:

| key | title |
|---|---|
| site_lat_deg | Site latitude |
| site_lon_deg | Site longitude |
| weather_spread_pct | Spread of annual sunshine across the weather sources |
| demand_kwh_yr | Annual electricity demand |
| demand_peak_kw | Peak demand |
| best_pv_kwp | Least cost design: PV size |
| best_battery_kwh | Least cost design: battery energy |
| best_battery_kw | Least cost design: battery power |
| best_lcoe_usd_per_kwh | Least cost design: cost of electricity (LCOE) |
| best_npc_usd | Least cost design: net present cost |
| best_capex_usd | Least cost design: up front capital cost |
| best_renewable_pct | Least cost design: renewable share |
| best_curtailed_pct | Least cost design: PV energy curtailed |
| best_fuel_l_yr | Least cost design: diesel fuel |
| best_co2_t_yr | Least cost design: CO2 |
| diesel_only_lcoe_usd_per_kwh | Diesel only: cost of electricity (LCOE) |
| diesel_only_fuel_l_yr | Diesel only: diesel fuel |
| diesel_only_co2_t_yr | Diesel only: CO2 |
| fuel_saved_l_yr | Diesel fuel saved |
| co2_saved_t_yr | CO2 saved |
| lcoe_change_pct | Change in cost of electricity against diesel only |
| break_even_fuel_usd_per_l | Diesel price at which PV starts to pay |
| api_cost_usd | Model API cost of this study |

Answer lines become `- <title>: <text> <unit> (<label>)` (was the key with `_` replaced by a space).

### 8. Gate details without long decimals

- G3: `"yield kWh/kWp " + fmt_number(y, 0) + ", PR " + ("none" if pr is None else fmt_number(pr, 2))` with
  `y = pv.specific_yield_kwh_kwp`, `pr = pv.performance_ratio_frac`.
- G2: `"soc band kWh [%s, %s], discharge kWh %s against stored kWh %s"` with each of the four numbers through
  `fmt_number(x, 0)`.
- G4: `"worst margin kW above min load: " + fmt_number(worst_kw, 1)` (the `"diesel never runs"` case stays).
- G8: `"max twin gap frac: %.1e" % worst`.
- G1, G5, G6 and G7 details are unchanged.

### 9. Grid edge note

A range row or a sensitivity row whose own least cost design has `pv_kwp == max(final pv grid)` or
`battery_kwh == max(final battery grid)` and whose note is `""` gets the note `"on grid edge"` (the note cell
changes with it). Rows without a feasible design keep their note. This includes the main range row; the answer
facts carry no such note (gate G7 covers the main design).

## Done when

`uv run pytest` passes (all tests, including `tests/test_study.py` and the new `tests/test_study_sourcing.py`),
and `autosolar/study.py` is ASCII only.

## Test check by the orchestrator

- A throwaway reference implementation (outside the repo) passes 74 of 74 tests in `tests/test_study.py` and
  `tests/test_study_sourcing.py` (and 58 of 58 in `tests/test_sourcing.py` alongside).
- The orchestrator changed one line of `tests/test_study.py` (`test_markdown`): the answer line it pins now uses the
  title from `FACT_TITLES`.
- 24 planted mutations of that reference each fail at least one test, among them: no G6 row, G6 after G7, hash
  ignoring the rows, hash key added without a sourcing file, no mismatch check, DOI dropped from sources, assumed
  rows in sources, answer lines with the key, block after Sources, judge fallback text, page cell without none,
  reasons joined with commas, value as written via str, checked count over all rows, no sourcing key, edge note
  only on PV, no edge note on range or sensitivity rows, and each gate detail format.
