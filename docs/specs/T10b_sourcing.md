# T10b: stage S3, sourced inputs (`autosolar/sourcing.py`)

## Why

Every cost in `config/default_inputs.json` is labelled assumed. Stage S3 asks Muse Spark (contributor, web search
on) for one published value per target input, checks each claim with `autosolar.cite_check.check_citation`
(T10a), and writes a new inputs file in the same schema (`autosolar.inputs/1`), so `run_study` reads it with no
change. A value replaces the assumed one only when every check passed, including the support verdict of a
different model (Muse Glimmer, local; plan D14 and R4). Everything else stays exactly as it was, with the reason
recorded. Gate G6 checks that the inputs file and the sourcing rows agree.

Measured (`docs/smoke/T10_search_probe.json`): the search call below took 19 to 96 s and cost USD 0.018 to 0.067
per input; 4 of 4 answers were JSON with all fields.

## Allowed dependencies

As `AGENTS.md`, plus `autosolar.cite_check`. Do not import `autosolar.study` (it will import this module later).
No network in tests: the client, `http_get`, `judge_fn` and `post` are passed in.

## Public API

```python
from autosolar.sourcing import (SOURCING_SCHEMA, TARGETS_SCHEMA, TARGET_UNITS, SEARCH_INSTRUCTIONS,
                                SEARCH_ESTIMATE_USD, GLIMMER_URL, CHECKED_PREFIX, Target, SourcingRow, ascii_text,
                                load_targets, parse_answer, search_claim, glimmer_judge, source_inputs, g6_check,
                                write_sourcing, read_sourcing)
```

### Constants

```python
SOURCING_SCHEMA = "autosolar.sourcing/1"
TARGETS_SCHEMA = "autosolar.sourcing_targets/1"
TARGET_UNITS = ("USD/kWp", "USD/kW", "USD/kWh", "USD/kWp/yr", "USD/kWh/yr", "USD/L", "frac")
SEARCH_ESTIMATE_USD = 0.10
GLIMMER_URL = "http://127.0.0.1:8093/v1/chat/completions"
CHECKED_PREFIX = "S3 checked: "
```

`SEARCH_INSTRUCTIONS` is exactly this string (the measured probe prompt; `\n` are newlines):

```text
You find one published number for an energy model input. Use web search. Prefer reports from IRENA, IEA, NREL, ADB, World Bank, IESR, government sources or peer-reviewed papers, published in 2021 or later.\nReturn only one JSON object, no prose, no code fence, with keys:\n  "value": the number as written in the source (number),\n  "unit": the unit as written in the source (string),\n  "currency_year": the year the money is expressed in, or null (integer or null),\n  "url": the page or PDF where the number appears (string),\n  "doi": the DOI if the source has one, else null,\n  "title": the source title (string),\n  "quote": one sentence or table row copied exactly from the source that contains the number (string).\nIf you cannot find a source, return {"value": null, "reason": "..."}.
```

### Dataclasses (`@dataclasses.dataclass`, field order as listed)

```python
Target(input: str, target_unit: str, band_lo: float, band_hi: float, description: str, search_brief: str)
SourcingRow(input: str, status: str, label: str, value_used: float | int, unit: str,
            value_as_written: float | int | None, unit_as_written: str, currency_year: int | None, title: str,
            url: str, doi: str | None, doi_ok: bool | None, page: int | None, quote_kind: str, quote: str,
            supports: bool | None, judge_name: str, reasons: list[str], search_cost_usd: float)
```

`status` is `"checked"` or `"assumed"`. `dataclasses.asdict(row)` must pass `json.dumps`.

### `ascii_text(text: str) -> str`

Map U+2018 and U+2019 to `'`, U+201C and U+201D to `"`, U+2010 to U+2014 and U+2212 to `-`, U+00A0, U+2009 and
U+202F to a space; then `unicodedata.normalize("NFKD", ...)`, `.encode("ascii", "ignore").decode("ascii")`;
collapse whitespace runs to one space; strip. Case is kept.

### `load_targets(path) -> tuple[list[Target], float]`

Reads a UTF-8 JSON file. Raise `ValueError` (message names the problem) unless all of these hold:

- top level is a dict with exactly the keys `schema`, `note`, `fx_idr_per_usd`, `targets`; `schema ==
  TARGETS_SCHEMA`; `note` is a str.
- `fx_idr_per_usd` is a dict with exactly `value`, `label`, `note`; `value` a finite int or float (not bool) above
  0; `label == "assumed"`; `note` a str.
- `targets` is a non-empty list of dicts, each with exactly the keys `input`, `target_unit`, `band_lo`, `band_hi`,
  `description`, `search_brief`; `input`, `description` and `search_brief` non-empty ASCII str; `target_unit` in
  `TARGET_UNITS`; `band_lo` and `band_hi` finite numbers (not bool) with `band_lo < band_hi`; no `input` twice.

Returns the targets in file order (bands as float) and the fx value as float.

### `parse_answer(text: str) -> dict | None`

Strip; if it starts with three backticks drop the first line and anything from the last three backticks on; try
`json.loads`; if that fails, try `json.loads` on the first `re.search(r"\{.*\}", text, re.S)` match. Return the
result only if it is a dict, else None.

### `search_claim(client, run_id: str, target: Target) -> tuple[Claim | None, str, float]`

Returns `(claim, reason, cost_usd)`; exactly one of claim and reason is set (`reason == ""` when there is a claim).

1. Messages:
   `[{"role": "system", "content": SEARCH_INSTRUCTIONS}, {"role": "user", "content": "Input: " + target.input +
   " (" + target.target_unit + "). Find: " + target.search_brief + "."}]`
2. One call: `client.respond(run_id, "S3_search", messages, estimate_usd=SEARCH_ESTIMATE_USD,
   tools=[{"type": "web_search"}], include=["web_search_call.results"])`. Pass nothing else.
3. `autosolar.ledger.BudgetExceeded` propagates. Any other exception gives `(None, "search error: " +
   type(exc).__name__, 0.0)`.
4. `cost = float(result.cost_usd)`. `answer = parse_answer(result.text)`. Reasons, checked in this order:
   - answer None: `"search answer not JSON"`.
   - `answer.get("value") is None`: `"no source found: " + ascii_text(str(answer.get("reason") or ""))[:200]`.
   - value not a finite int or float, or a bool: `"search answer field value invalid"`.
   - `unit`, `url`, `quote` (in that order) not a non-empty str after strip: `"search answer field <key> invalid"`.
   - `doi` present and neither None nor str: `"search answer field doi invalid"`; an empty str counts as None.
   - `currency_year` present and neither None nor an int (bool is not an int here): `"search answer field
     currency_year invalid"`.
5. Else `Claim(input_name=target.input, description=target.description, value=answer["value"],
   unit=answer["unit"].strip(), url=answer["url"].strip(), doi=<str stripped or None>, quote=answer["quote"],
   title=answer["title"] if it is a str else "", currency_year=<int or None>)`.

### `glimmer_judge(prompt: str, *, post=requests.post, url: str = GLIMMER_URL, timeout_s: float = 900.0) -> str`

One call: `post(url, json=body, timeout=timeout_s)` with

```python
body = {"model": "muse-glimmer", "messages": [{"role": "user", "content": prompt}], "max_tokens": 8192,
        "temperature": 1.0, "top_p": 0.95, "top_k": 64, "chat_template_kwargs": {"reasoning_strength": "low"}}
```

Status other than 200: `RuntimeError("glimmer HTTP <code>")`. Return `resp.json()["choices"][0]["message"]
["content"]` when it is a str; any other shape (missing key, not a str): `RuntimeError("glimmer answer has no
content")`. Exceptions from `post` propagate (the checker turns them into a missing verdict).

### `source_inputs(base_raw: dict, targets: list[Target], *, client, run_id: str, http_get, judge_fn, judge_name: str, fx_idr_per_usd: float) -> tuple[dict, list[SourcingRow]]`

`base_raw` is a parsed inputs file (`{"schema", "note", "values": {name: {"value", "unit", "label", "note"}}}`).
`base_raw` is never changed; work on `copy.deepcopy(base_raw)`.

Before any call, for every target: `target.input` must be a key of `base_raw["values"]` and that entry's `unit`
must equal `target.target_unit`, else `ValueError` naming the input. Then, for each target in order:

1. `claim, reason, cost = search_claim(client, run_id, target)`.
2. No claim: row with `status "assumed"`, `reasons [reason]`, base entry unchanged.
3. Claim: `check = check_citation(claim, http_get=http_get, judge_fn=judge_fn, judge_name=judge_name,
   target_unit=target.target_unit, band_lo=target.band_lo, band_hi=target.band_hi,
   fx_idr_per_usd=fx_idr_per_usd)`.
4. `check.status == "checked"`: replace the entry with
   `{"value": float(format(check.value_converted, ".6g")), "unit": target.target_unit, "label": "paper" if
   check.doi_ok is True else "docs", "note": note}` where `note` is built as

   ```python
   CHECKED_PREFIX + ascii_text(claim.title or "untitled") + "; " + check.final_url
   + ("; page " + str(check.page) if check.is_pdf else "")
   + "; quote " + check.quote_kind
   + "; as written " + format(claim.value, "g") + " " + ascii_text(claim.unit)
   + ("; currency year " + str(claim.currency_year) if claim.currency_year is not None else "")
   + ("; fx " + format(fx_idr_per_usd, "g") + " IDR per USD assumed" if <canonical unit starts with "IDR/"> else "")
   + "; support judged by " + judge_name
   ```

   (canonical unit: `autosolar.cite_check.parse_unit(claim.unit)`).
5. `check.status == "assumed"`: base entry unchanged, `reasons = list(check.reasons)`.

Row fields: `input` the target input; `status`; `label`, `value_used` and `unit` from the entry as it stands after
this step; from the claim when there is one, else the empty values: `value_as_written` (`claim.value` / None),
`unit_as_written` (`claim.unit` / `""`), `currency_year` (/ None), `title` (`ascii_text(claim.title)` / `""`), `url`
(`check.final_url or claim.url` / `""`), `doi` (`claim.doi` / None), `quote` (`ascii_text(claim.quote)` / `""`); from
the check when it ran, else None or `"not run"`: `doi_ok`, `page` (as `check.page`, so 1 for a matched HTML page),
`quote_kind`, `supports`; `judge_name` always;
`reasons` (empty when checked); `search_cost_usd` the `cost` from step 1.

Returns `(new_raw, rows)`, rows in target order.

### `g6_check(rows: list[SourcingRow], inputs_raw: dict) -> tuple[bool, str]`

Gate G6. Walk the rows in order; the first problem found gives `(False, "<input>: <problem>")`:

- `row.input` not in `inputs_raw["values"]`: problem `"not in inputs"`.
- `status "checked"` needs all of: `reasons == []`, `supports is True`, `quote_kind in ("exact", "near")`, entry
  `label == row.label` and `row.label in ("paper", "docs")`, entry `value == row.value_used`, entry `unit ==
  row.unit`, entry note starts with `CHECKED_PREFIX`. Else problem `"checked row does not match its input"`.
- `status "assumed"` needs: `reasons` non-empty, entry `label == row.label`, entry `value == row.value_used`, entry
  note does not start with `CHECKED_PREFIX`. Else problem `"assumed row does not match its input"`.
- any other status: problem `"unknown status"`.

Then, any entry in `inputs_raw["values"]` whose note starts with `CHECKED_PREFIX` but has no row: `(False, "<name>:
checked note without a sourcing row")` (first such name in dict order). Else `(True, "<c> of <n> sourced inputs
checked, <a> kept assumed")` with `c` checked rows, `n` rows, `a` assumed rows.

### `write_sourcing(path, inputs_raw: dict, rows: list[SourcingRow], meta: dict) -> None`

Writes UTF-8 JSON `{"schema": SOURCING_SCHEMA, "meta": meta, "inputs": inputs_raw, "rows": [asdict(row), ...]}`
with `indent=1` and `ensure_ascii=True`. Creates parent folders.

### `read_sourcing(path) -> tuple[dict, list[SourcingRow], dict]`

Reads it back: schema must equal `SOURCING_SCHEMA`; each row dict must have exactly the `SourcingRow` field names;
then `g6_check` must pass. Any failure: `ValueError` (for G6: `"sourcing file fails G6: " + detail`). Returns
`(inputs_raw, rows, meta)`.

## Done when

`uv run pytest tests/test_sourcing.py` passes, the full suite still passes, and the module is ASCII only.

## Test check by the orchestrator

- A throwaway reference implementation (outside the repo) passes 58 of 58 tests in `tests/test_sourcing.py`, both
  on top of the reference checker and on top of the committed `autosolar/cite_check.py` (T10a).
- 15 planted mutations of that reference each fail at least one test, among them: label always paper, base inputs
  changed in place, budget stop swallowed, target unit not checked, targets checked lazily, fx note dropped, G6
  skipping the value, G6 missing a forged checked note, G6 accepting an assumed row without a reason, read without
  G6, empty DOI kept, bool currency year accepted, value not rounded, wrong Glimmer strength, live flag passed by
  the module.
- `glimmer_judge` uses the request body of the measured Glimmer speed test (port 8093, sampling 1.0/0.95/64,
  reasoning strength low; `prep/glimmer/SPEED_TEST.md` in the prep repo: median 1492 tokens written per low check,
  so `max_tokens` 8192 leaves room).
