# T16: curated inputs (post hoc)

Status: spec by the orchestrator. Builder creates `autosolar/curate.py` and `tools/curate.py` and edits
`autosolar/sourcing.py`, `autosolar/study.py` and `autosolar/site.py` only. All earlier specs stay in force except
where this spec changes them. The orchestrator has already written `config/curated_inputs.json` and
`tests/test_curated.py`.

## Why

Seven study inputs were weak: battery energy price, battery power price, battery O&M, battery life and battery
round trip efficiency were assumed; the discount rate was assumed; the diesel price came from a passing remark in a
palm oil article. The orchestrator found each value by hand in a named document (the Danish Energy Agency and EA
Energy Analyses technology catalogue for Indonesia, an IEA commentary on the cost of capital, and the Pertamina
industrial fuel list) and wrote them to `config/curated_inputs.json`. The land check input `pv_mwdc_per_ha` keeps
its US median (0.87 MWdc per ha, paper): the catalogue range for Indonesia (0.77 to 1.67 MWdc per ha, docs) holds it,
and the catalogue central value would loosen the check after the fact, so it is not changed.

These values were chosen after the rules of this project were written, so they are post hoc. Every place that shows
them must say so. Study f86df9819fa150a7 stays as it is and is reported next to the new study.

Decision rule, written before the new study runs: the new study becomes the first gallery card and the demo example
whichever way its numbers move; the old study stays in the gallery; the README shows both.

## Data file `config/curated_inputs.json`

A JSON object with exactly the keys `schema` (the string `autosolar.curated/1`), `note` (a string) and `entries` (a
non-empty list). Each entry is an object with exactly these keys:

| key | type and rule |
|---|---|
| input | string matching `^[a-z][a-z0-9_]*$`; no two entries share one |
| value | finite int or float above 0, not a bool |
| unit | non-empty ASCII string |
| label | `paper` or `docs` |
| title | non-empty ASCII string |
| url | ASCII string that starts with `https://` |
| doi | null or a non-empty ASCII string |
| page | null or an int of 1 or more, not a bool |
| quote_kind | `exact` or `table` |
| quote | non-empty ASCII string of at most 600 characters |
| value_as_written | null or a finite int or float, not a bool |
| unit_as_written | ASCII string |
| currency_year | null or an int from 1990 to 2100, not a bool |
| derivation | non-empty ASCII string of at most 600 characters |

## Changes

### autosolar/sourcing.py

1. New constants `CURATED_PREFIX = "S5 curated post hoc: "` and
   `CURATED_JUDGE = "none (picked by hand after pre-registration)"` (here so `g6_check` can use it).
2. `g6_check` gains a branch for `row.status == "curated"`. It passes when all hold: `row.reasons == []`,
   `row.supports is None`, `row.judge_name == CURATED_JUDGE`, `row.quote_kind in ("exact", "table")`,
   `row.label in ("paper", "docs")`, the input
   entry is a dict, its `label` equals `row.label`, its `value` equals `row.value_used`, its `unit` equals
   `row.unit`, and its `note` is a string that starts with
   `CURATED_PREFIX + str(row.title) + "; " + str(row.url)`. Otherwise it returns
   `(False, row.input + ": curated row does not match its input")`. The existing early return for an input entry
   that is not a dict also gives this curated message when the row status is `curated`.
3. The `assumed` branch also needs the note not to start with `CURATED_PREFIX`.
4. After the row loop, an input whose note starts with `CURATED_PREFIX` but has no row returns
   `(False, name + ": curated note without a sourcing row")`. This runs in the same loop as the existing checked
   note test, checked note first.
5. The pass detail stays exactly as it is when no row is curated. With K curated rows (K above 0) it gains the
   suffix `", " + str(K) + " curated post hoc"`.

### autosolar/curate.py (new)

Imports from `autosolar.sourcing` only (plus the standard library). Names:

- `CURATED_SCHEMA = "autosolar.curated/1"`
- `CURATED_JUDGE`: imported from `autosolar.sourcing` and exported under the same name.
- `ENTRY_KEYS`: tuple of the fourteen entry keys in the order of the table above.
- `CuratedEntry`: frozen dataclass with those fourteen fields in that order.
- `load_curated(path) -> tuple[list[CuratedEntry], str]`: reads the file, checks every rule of the data file
  section, and returns the entries in file order and the SHA-256 hex digest of the raw file bytes. Any broken rule
  raises `ValueError`.
- `curated_note(entry) -> str`: `CURATED_PREFIX + title + "; " + url`, then `"; page " + str(page)` when page is
  not null, then `"; quote " + quote_kind`, then `"; as written " + format(value_as_written, "g") + " " +
  unit_as_written` when value_as_written is not null, then `"; currency year " + str(currency_year)` when that is
  not null, then `"; " + derivation`.
- `curated_line(count_curated: int, count_rows: int) -> str`: returns
  `str(count_curated) + " of " + str(count_rows) + " inputs were curated by hand after pre-registration (post hoc), "
  "from the documents named in the table. Quote match exact means the quote is word for word from the page; table "
  "means the value was read by eye from a table image and no script checked it."`
- `apply_curated(inputs_raw, rows, entries, targets) -> tuple[dict, list[SourcingRow], list[dict]]`:
  1. Works on a deep copy of `inputs_raw` and never changes its arguments.
  2. For each entry, in order: the input must be a key of `inputs_raw["values"]` holding a dict, else
     `ValueError`. Its `unit` must equal the entry unit, else `ValueError`. If the old value is an int (not a bool)
     the entry value must be an int, else `ValueError`; if the old value is a float the new value is stored as a
     float. If a target in `targets` has the same input, the value must lie within its `band_lo` and `band_hi`
     (both ends allowed), else `ValueError`.
  3. The input entry becomes `{"value": stored_value, "unit": unit, "label": label, "note": curated_note(entry)}`.
  4. The new row is `SourcingRow(input, "curated", label, stored_value, unit, value_as_written, unit_as_written,
     currency_year, title, url, doi, None, page, quote_kind, quote, None, CURATED_JUDGE, [], 0.0)` (fields in
     dataclass order: `doi_ok` and `supports` are None, `search_cost_usd` is 0.0); `stored_value` is the value
     written to the input entry in step 3 (a float when the old value was a float).
  5. Row order: base rows keep their order. The first base row for a curated input is replaced in place by the new
     row and any further base rows for that input are dropped. Curated inputs with no base row are appended in
     entry order.
  6. The third return value lists `dataclasses.asdict(row)` for every dropped or replaced base row, in base order.
- `curate_run(base_sourcing_path, curated_path, targets_path, runs_dir, run_id) -> Path`:
  1. `read_sourcing(base_sourcing_path)` (G6 checked), `load_targets(targets_path)`, `load_curated(curated_path)`,
     then `apply_curated(base_inputs, base_rows, entries, targets)`, called through the module-level name
     `apply_curated` (a test replaces it). All of this runs before any folder is made, so a bad file writes nothing.
  2. Folder `Path(runs_dir) / run_id`; if it exists raise `ValueError`; else create it with parents.
  3. Meta, exactly these keys: `run_id`, `post_hoc` (True), `curated_from` (str of the base path), `curated_file`
     (str of the curated path), `curated_sha256`, `curated_inputs` (entry inputs in file order), `replaced_rows`,
     `judge` (base meta `judge` when it is a string, else None), `fx_idr_per_usd` (base meta value, else None),
     `base_meta` (the base meta).
  4. `write_sourcing(folder / "sourcing.json", new_inputs, new_rows, meta)` and `folder / "inputs.json"` holding
     `json.dumps(new_inputs, indent=1, ensure_ascii=True) + "\n"`.
  5. `read_sourcing` on the new file (G6 must pass, else its `ValueError` goes up), then return the folder.

### tools/curate.py (new)

Same import and ROOT pattern as `tools/source.py`. Positional `base` (a sourcing.json path); `--curated` default
`ROOT/config/curated_inputs.json`; `--targets` default `ROOT/config/sourcing_targets.json`; `--runs` default
`ROOT/runs/sourcing`. Run id `"curated-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]`. Calls
`curate_run`, then prints `folder <path>` and the G6 detail. No network and no model call.

### autosolar/study.py

1. Sources: in the loop over sourcing rows, a curated row adds
   `"Curated input (post hoc) " + input + ": " + (title or "untitled") + ", " + url`, then `", page " + str(page)`
   when page is not None, then `", doi:" + doi` when doi is a non-empty string. Lines keep row order, mixed with the
   checked lines.
2. Markdown `## Sourced inputs`: when K curated rows exist (K above 0), a blank line and `curated_line(K, N)` (N =
   all sourcing rows) come right after the intro paragraph and before the blank line and table header. With no
   curated row the block is unchanged.
3. Row cells are unchanged (status `curated` shows in the Status column; "Why kept assumed" is `none`).

### autosolar/site.py

In the inputs section, when the report has sourcing and K curated rows (K above 0), add
`'<p class="posthoc">' + esc(curated_line(K, N)) + "</p>"` right before the sourcing table. No other change.

## Not in scope

Sea transport of diesel to the island, taxes on diesel, the lower heating value of B40 against pure diesel, and PV
degradation (0.25 to 0.5 percent a year in the same catalogue) stay out of the model and are named in the README.
The first three would raise the cost of diesel power; the last would lower PV output.
