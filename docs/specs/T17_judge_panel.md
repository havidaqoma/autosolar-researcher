# T17: two judge models (the local judge twice, then Muse Wonder)

Status: spec by the orchestrator. Builder edits `autosolar/cite_check.py` and `autosolar/sourcing.py` only. All
earlier specs stay in force except where this spec changes them. The orchestrator has already written
`tests/test_judge_panel.py`.

## Why

Since T10f a sourced value counts as checked only when the support judge says yes 3 times in a row. All 3 votes come
from one model, the local Muse Glimmer judge, so they are not independent: three samples of one model can share the
same blind spot. From now on the third vote comes from a second model, `muse-wonder-1.0`, called through the Meta
Model API. Muse Spark finds the quotes, so Spark never votes on its own work. Wonder votes last, so a value the local
judge turns down costs no API money.

## 1. cite_check.py: a judge panel in support_votes

`support_votes(judge_fn, claim, context, *, source_title=None, source_url=None, votes=JUDGE_VOTES)` keeps its
signature, its return value and its stop rule. The new part:

- `votes` is checked first, exactly as before (`ValueError("votes must be an int >= 1")`).
- When `judge_fn` is a `list`, raise `ValueError("a judge panel must be a tuple")` before any judge call.
- When `judge_fn` is a `tuple` it is a panel. It must hold exactly `votes` items and every item must be callable.
  Otherwise raise `ValueError("a judge panel must hold votes callables")` before any judge call (an empty tuple
  included).
- With a panel, vote k (counting from 0) calls `support_verdict(judge_fn[k], ...)` with the same arguments as every
  other vote, so every judge sees the same prompt. The first verdict whose `supports` is not `True` ends the vote, as
  before, and later judges are not called.
- Anything else is used exactly as before: the same `judge_fn` for every vote.
- `check_citation` does not change. It already passes `judge_fn` through with `votes=JUDGE_VOTES`, so a panel given
  to `check_citation` must hold 3 judges. `judge_calls` then also tells which judge ended the vote.

## 2. sourcing.py: the Wonder judge

New constants:

```
WONDER_MODEL = "muse-wonder-1.0"
WONDER_JUDGE_STAGE = "S3_judge"
WONDER_JUDGE_ESTIMATE_USD = 0.25
```

New function `wonder_judge(prompt, *, client, run_id) -> str`:

- Makes exactly one call: `client.respond(run_id, WONDER_JUDGE_STAGE, prompt,
  estimate_usd=WONDER_JUDGE_ESTIMATE_USD, model=WONDER_MODEL, store=False)`. No other keyword is passed (no tools,
  no reasoning setting, no live flag). The client records the cost in the ledger and checks the caps before the call.
- Returns `result.text` when it is a non-empty `str` after `strip()`. Otherwise raises
  `RuntimeError("wonder answer has no text")`.
- Any exception from the client is not caught here. `support_verdict` turns it into a verdict with no answer
  (`judge error: <type>`), so a failed or refused Wonder call can never let a value in.

New function `judge_panel(local_fn, wonder_fn) -> tuple`:

- Both arguments must be callable, else `ValueError("judges must be callable")`.
- Returns the tuple `(local_fn, local_fn, wonder_fn)`, whose length equals `JUDGE_VOTES`.

`source_inputs` and the rest of `sourcing.py` do not change.

## Re-judge rule (written and committed before the run)

The orchestrator tool `tools/rejudge.py --panel` (not built here) checks the pre-registered sourcing file again:

- Input: `runs/sourcing/rejudge-20261028T013500-26a59e/sourcing.json`, the file behind study f86df9819fa150a7. It has
  4 checked rows: PV capex, PV O&M, diesel price and diesel minimum load. No search call is made.
- Each checked row is checked again with `check_citation` and the panel `judge_panel(local judge, Wonder judge)`.
  The claim is rebuilt from the row exactly as in the T10f re-judge.
- A row stays checked only when the new check is `checked` with the same `value_used` (6 significant digits) and the
  same label. Any other outcome sends it back to its assumed value from `config/default_inputs.json` with each new
  reason under a `re-judge: ` prefix. A judge error, a failed fetch or a refused API call counts as a no.
- Assumed rows are carried unchanged. The run is made once. No row is judged again by hand and nothing is retried.
- Then one live study runs on the new file (compared with f86df9819fa150a7). Then `tools/curate.py` applies
  `config/curated_inputs.json` (unchanged) to the new file and one live study runs on that (compared with
  579f414386fe2d58). Both are reported as they come out, whichever way the numbers move. The older studies stay in
  the gallery.
- Spend: at most 4 Wonder calls, estimated at USD 0.25 each before the call (the cap check). The real cost is read
  from the ledger.
- Before the run, one probe call sends Wonder the support prompt for a made-up claim (the test claim: a diesel set
  kept above 30% of its rated capacity, with its own quote as context). It only checks that the answer parses. It is
  not counted, it is not one of the 4 rows, and its cost is in the ledger.

## Done when

- `tests/test_judge_panel.py` and the rest of the suite pass.
- Text gate passes; ASCII only.

## Test check by the orchestrator

- Reference build in scratch (this spec applied to copies of `cite_check.py` and `sourcing.py`): 1,316 of 1,316 (1,261 old plus 55 new) tests
  pass, including the new tests in `tests/test_judge_panel.py`. No old test was changed.
- Planted faults: 26 of 26 caught by the tests (panel length, order, callable checks, list refusal, early stop,
  Wonder model, stage, estimate, store flag, extra keywords, empty text, error handling, panel order).
- Dry run of `tools/rejudge.py --panel` on the reference copy with fake judges and real fetches: all 4 rows reached
  the judges; a fake Wonder no sent its row back to the assumed value; G6 passed; every vote was logged.
