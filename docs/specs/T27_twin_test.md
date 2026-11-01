# T27: twin test of the checking step (post hoc)

Status: spec and acceptance tests written first, by hand, after the literature round (prep, 1 Nov) and the owner's
go-ahead. Muse Code writes `autosolar/twin_test.py` and `tools/twin_test.py` only. The acceptance tests are
`tests/test_twin_test.py` (41 tests). Everything in this spec, the items rule, the twin sizes, the number of votes and the
numbers to report, is fixed before the first judge call. The test is run once; a crash resumes from the vote cache,
it does not start again.

## Why

A study uses a sourced value only when a script finds the quote in its source, finds the claimed number inside the
quote, and three judges then say the quote supports the value (Muse Glimmer twice on our own GPU, Muse Wonder last).
A recent test of language models (arXiv 2610.38096) found that a model can compute a limit correctly and still call
an impossible design solved. So the question for this product: if a value is wrong by a little, which layer stops
it? This task gives the checker copies of each value with the number moved by 1%, 10% and 30%, down and up, and
counts what each layer stops. It also counts how often the local judge turns down a true value (a false alarm).

The Wonder vote is not run here, to keep Meta model spending at zero for tests. The judge sees the quote as its
source context; in a study it sees about 400 characters of source text around the quote (`CONTEXT_CHARS` in
`autosolar/cite_check.py`). Inputs are described neutrally (no region, no real or nominal): this test asks about the
number, not about whether the value fits the study.

## 1. autosolar/twin_test.py

### Constants

```
TWIN_SCHEMA = "autosolar.twin_test/1"
SHIFTS_FRAC = (-0.30, -0.10, -0.01, 0.0, 0.01, 0.10, 0.30)
LEVELS_FRAC = (0.0, 0.01, 0.10, 0.30)
VOTES = 3
TWIN_STATUSES = ("checked", "curated")
TWIN_DESCRIPTIONS = {
    "pv_capex_usd_per_kwp": "installed capital cost of a solar PV plant per kW",
    "pv_om_usd_per_kwp_yr": "annual fixed operation and maintenance cost of a solar PV plant per kW",
    "battery_capex_usd_per_kwh": "capital cost of the energy part of a lithium-ion battery storage system",
    "battery_om_usd_per_kwh_yr": "annual fixed operation and maintenance cost of a lithium-ion battery storage system",
    "battery_power_capex_usd_per_kw": "capital cost of the power part of a lithium-ion battery storage system",
    "battery_life_yr": "technical lifetime of a lithium-ion battery storage system",
    "battery_round_trip_eff_frac": "round-trip efficiency of a lithium-ion battery storage system",
    "fuel_price_usd_per_l": "price of industrial diesel fuel per litre",
    "discount_rate_frac": "discount rate or cost of capital for renewable energy projects",
    "diesel_min_load_frac": "minimum load of a diesel generator as a share of its rated power",
}
NOTE = (
    "Post hoc test, written after the studies. Each checked or curated value is given to the checker again with its "
    "number moved by 1%, 10% and 30%, down and up. The script check needs the claimed number inside the quote. The "
    "local judge (votes 1 and 2 in a study) sees the claimed value, the quote, the source title and URL; here the "
    "quote stands in for the source text around it. The Wonder vote (vote 3 in a study) is not run, to keep Meta "
    "model spending at zero. In a study a value is used only if every check passes."
)
```

A real number below means an `int` or `float` that is not a `bool` and is finite.

### value_in_quote(value, quote) -> bool

`value` must be a real number and `quote` a `str`, else `ValueError`. Returns True when any number `n` in
`cite_check.numbers_in(quote)` has `abs(n - float(value)) <= 1e-9 * max(1, abs(float(value)))` (the same rule
`check_citation` uses), else False.

### twin_value(value, shift_frac)

`value` and `shift_frac` must be real numbers, else `ValueError`.
- `shift_frac == 0.0`: return `int(float(value))` when `float(value).is_integer()`, else `float(value)`.
- Otherwise `y = float(format(float(value) * (1 + shift_frac), ".4g"))`. If `y == float(value)`, raise `ValueError`.
  Return `int(y)` when `y.is_integer()`, else `y`.

Examples: `twin_value(1119, -0.01) == 1108`, `twin_value(0.35, 0.01) == 0.3535`, `twin_value(24.38, -0.30) == 17.07`,
`twin_value(14000, 0.30) == 18200` (an `int`), `twin_value(25, 0.0) == 25` (an `int`), `twin_value(9.4, 0.0) == 9.4`.

### collect_items(site_dir) -> tuple[list[dict], list[dict]]

- `site_dir` is a path (str or `pathlib.Path`). For each folder name `h` in `sorted(os.listdir(site_dir / "data"))`
  whose `report.json` exists, read it (UTF-8). Its rows are `report["sourcing"]["rows"]` when `report` has a
  `"sourcing"` dict with a `"rows"` list, else none.
- A row is a candidate when it is a dict and `row.get("status") in TWIN_STATUSES`. Candidates are deduplicated on
  `(input, repr(value_as_written), unit_as_written, quote)`, keeping the first seen (folders in sorted order, rows in
  file order).
- A kept candidate goes to `skipped` with one reason, checked in this order:
  - `"no number or quote"` when `value_as_written` is not a real number or `quote` is not a non-empty `str`;
  - `"no description"` when `input` is not a key of `TWIN_DESCRIPTIONS`;
  - `"value not in quote"` when `value_in_quote(value_as_written, quote)` is False.
  A skipped entry is `{"study": h, "input": ..., "status": ..., "value": value_as_written, "unit": unit_as_written,
  "reason": ...}` (`row.get` for each field).
- Any other kept candidate is an item: `{"id": "i%02d" % n, "study": h, "input", "status", "value":
  value_as_written, "unit": unit_as_written, "quote", "title", "url", "doi", "currency_year"}`, numbered from 1 in
  order. `title` and `url` are the row's value when it is a `str`, else `""`; `doi` is the row's value when it is a
  non-empty `str`, else `None`; `currency_year` is the row's value when it is an `int` and not a `bool`, else `None`.
- Returns `(items, skipped)`. With the committed site this gives 10 items and 1 skipped row (a curated diesel price,
  "value not in quote").

### make_twins(items) -> list[dict]

For each item in order, for each `s` in `SHIFTS_FRAC` in order, one dict `{"key": item["id"] + ":" + format(s,
"+.2f"), "item": item["id"], "shift_frac": s, "value": twin_value(item["value"], s), "script_caught": not
value_in_quote(<that value>, item["quote"])}`.

### claim_for(item, value) -> cite_check.Claim

`Claim(input_name=item["input"], description=TWIN_DESCRIPTIONS[item["input"]], value=value, unit=item["unit"],
url=item["url"], doi=item["doi"], quote=item["quote"], title=item["title"], currency_year=item["currency_year"])`.

### run_votes(items, twins, judge_fn, votes, done, on_vote=None) -> dict

- `votes` must be an `int`, not a `bool`, and 1 or more, else `ValueError`. `done` is a dict keyed by
  `(twin key, vote number)`.
- For each twin in order, for `k` in `1..votes`: when `(key, k)` is in `done`, skip it. Otherwise call
  `cite_check.support_verdict(judge_fn, claim_for(item, twin["value"]), item["quote"], source_title=item["title"] or
  None, source_url=item["url"] or None)` with the twin's item, and store `record = {"key": key, "vote": k,
  "supports": verdict.supports, "reason": verdict.reason, "raw": verdict.raw}` as `done[(key, k)]`; then call
  `on_vote(record)` when `on_vote` is not None.
- Every twin goes to the judge, the ones the script stops included: the point is what the judge does alone.
- Returns `done` (the same dict).

### summarise(twins, done, votes) -> list[dict]

One dict per level `L` in `LEVELS_FRAC`, in order, over the twins with `round(abs(shift_frac), 2) == L`:
- `level_frac`: `L`; `n_twins`: how many; `script_caught`: how many have `script_caught` True;
- `votes_total`: how many `(key, k)` with `k` in `1..votes` are in `done`; `votes_not_yes`: of those, how many have
  `supports` not True; `votes_no_verdict`: of those, how many have `supports` None;
- `panel_runs`: how many twins have both `(key, 1)` and `(key, 2)` in `done` (0 when `votes < 2`); `panel_caught`:
  of those, how many have `supports` not True in vote 1 or in vote 2 (the rule in a study, where the local judge
  votes first and second and any answer but yes stops the value).

For level 0.0 every "caught" count is a false alarm: a true value turned down.

### render_md(doc) -> str

`doc` has the keys `schema`, `note`, `judge`, `votes`, `items`, `skipped`, `twins`, `summary`. Returns ASCII text,
every free text field passed through `autosolar.sourcing.ascii_text`, lines joined with `"\n"`, ending with
`"\n"`:

```
# Twin test of the checking step (post hoc)

<note>

Judge: <judge>. Votes per twin: <votes>. Items: <len(items)>. Twins: <len(twins)>.

| Number given to the checker | Twins | Script: number not in the quote | Local judge, single votes: not yes | Local judge, votes 1 and 2 as in a study: not yes |
|---|---|---|---|---|
<one row per summary entry>

## Items

<one line per item>

## Skipped

<one line per skipped row, or "None.">
```

- Row label: `"True value"` for level 0.0, else `"Moved " + format(100 * L, "g") + "%"` (so `Moved 1%`,
  `Moved 10%`, `Moved 30%`).
- Count cells are `"<k> of <n>"`: script `script_caught of n_twins`; single votes `votes_not_yes of votes_total`;
  panel `panel_caught of panel_runs`. A votes cell is `"not run"` when its total (`votes_total` or `panel_runs`) is 0.
- Item line: `"- " + id + ": " + input + " (" + status + ", study " + study + "): " + format(value, "g") + " " + unit +
  '; quote: "' + ascii_text(quote)[:200] + '"'` (the quote is made ASCII first, then cut to 200 characters).
- Skipped line: `"- " + input + " (" + status + ", study " + study + "): " + reason`.

## 2. tools/twin_test.py

```
python tools/twin_test.py [--site docs/site] [--out docs/posthoc] [--judge none|glimmer] [--votes 3]
```

`main(argv=None, judge_fn=None) -> int`. Paths are relative to the repo root unless absolute.

1. `items, skipped = collect_items(site)`; `twins = make_twins(items)`.
2. `--judge none` (the default): no judge, no server and no network; `judge = "none (script layer only)"`, `votes =
   0`, `done = {}`.
3. `--judge glimmer`: `judge = source.JUDGE_NAME` (from `tools/source.py`), `votes = --votes` (an int, 1 or more,
   else exit with an error). The vote cache is `<out>/twin_test_votes.jsonl`: every line is a JSON object with the
   keys `judge`, `key`, `vote`, `supports`, `reason`, `raw`; lines whose `judge` equals `judge` fill `done` (key
   `(key, vote)`); other lines are ignored. When `judge_fn` is None, the tool uses `glimmer_judge` from
   `autosolar.sourcing`, starting the local server with `source.start_server(ROOT / "runs" / "twin_test" /
   "glimmer_server.log")` when `source.server_up()` is False (creating that folder) and stopping it at the end when it
   started it. When `judge_fn` is given (tests), the tool uses it and never touches the server. `run_votes` runs
   with an `on_vote` that appends the record plus `"judge"` to the cache as one line (`json.dumps(..., sort_keys=True)`
   then `"\n"`) and flushes.
4. `summary = summarise(twins, done, votes)`. `doc = {"schema": TWIN_SCHEMA, "note": NOTE, "judge": judge, "votes":
   votes, "items": items, "skipped": skipped, "twins": [twin plus "votes": [done[(key, k)] for k in 1..votes when
   present]], "summary": summary}` in that key order.
5. Writes, creating `<out>`, ASCII with `"\n"` line ends: `<out>/twin_test.json` (`json.dumps(doc, indent=1) +
   "\n"`) and `<out>/twin_test.md` (`render_md(doc)`).
6. Prints one line per summary row (`level script_caught/n_twins votes_not_yes/votes_total
   panel_caught/panel_runs`) and returns 0.

## Rules for this task

- Write `autosolar/twin_test.py` and `tools/twin_test.py` only. Do not edit tests, specs, config, other modules,
  pages or `docs/posthoc/`.
- No new dependency; ASCII only; units in names where a value has a unit; `ValueError` on bad input.
- No network in the module. The tool reaches the network only through the local judge server, and only with
  `--judge glimmer` and no `judge_fn`.

## What will be reported (fixed now)

The README gets one short paragraph with the table from `docs/posthoc/twin_test.md` after one run with `--judge
glimmer --votes 3`: how many moved twins the script stops, how many the local judge alone turns down at each size
(single votes and the two-vote rule), how many true values it turns down, and how many answers gave no verdict. The
counts are reported as they come out, with the run's judge name, whatever they show.
