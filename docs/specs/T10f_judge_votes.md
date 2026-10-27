# T10f: the support judge must say yes 3 times in a row

Status: spec by the orchestrator. Builder edits `autosolar/cite_check.py` only.
T10a to T10e stay in force except where this spec changes them. `autosolar/sourcing.py` does not change.

## Why

The honesty check for T10e (`docs/smoke/T10e_judge_probe.json`, measured) asked the local judge about the same 4
probe claims in 3 runs. The judge samples at temperature 1.0, and 2 of the 4 claims got different answers between
runs (a general battery figure: no, yes, yes; a scenario diesel price: no, yes, no). A sourcing run asks once per
row, so one lucky yes can let a value in. From now on a value counts as supported only when the judge says yes
3 times in a row with the same prompt. The first answer that is not yes ends the vote.

## 1. Constant

`JUDGE_VOTES = 3`

## 2. support_votes

New function:

```
support_votes(judge_fn, claim, context, *, source_title=None, source_url=None, votes=JUDGE_VOTES)
    -> tuple[Verdict, int]
```

- `votes` must be an `int`, not a `bool`, and at least 1. Anything else raises `ValueError("votes must be an int
  >= 1")` before any judge call.
- It calls `support_verdict(judge_fn, claim, context, source_title=source_title, source_url=source_url)` up to
  `votes` times. Every call uses the same arguments, so every prompt is the same.
- It returns at the first verdict whose `supports` is not `True` (False or None): `(that verdict, number of calls
  made so far)`.
- When all `votes` verdicts are `True` it returns `(the last verdict, votes)`.
- `support_verdict` and its prompt do not change.

## 3. check_citation

- `CitationCheck` gains one last field `judge_calls: int = 0`: the number of judge calls made for this claim.
- Where `check_citation` called `support_verdict` it now calls `support_votes(...)` with the same `judge_fn`,
  `claim`, `context`, `source_title` and `source_url` (T10e rules) and `votes=JUDGE_VOTES`.
- `supports` and `judge_reason` come from the returned verdict; `judge_calls` is the returned count.
- The reason text does not change: `"judge says not supported: " + reason` when the stopping verdict is False,
  `"judge gave no verdict: " + reason` when it is None. So a late no is still never retried by a second search
  (`NO_RETRY_PREFIXES` in `sourcing.py`).
- When the judge does not run (any script reason), `judge_calls` is 0 and `judge_fn` is never called.

Effect on stage S3: a checked row costs 3 local judge calls, a row the judge turns down costs 1 to 3.

## Re-judge rule (pre-registered before the run)

The 4 rows checked so far were each judged by a single call. The orchestrator tool `tools/rejudge.py` (not built
here) checks them again under this rule:

- Input: the run 3 file `runs/sourcing/sourcing-20261028T005706-df102a/sourcing.json` (read with `read_sourcing`,
  so G6 must pass). No search call is made and no model API cost is spent; the judge is the local one.
- Each checked row is checked again with `check_citation`: the claim is rebuilt from the row (description, target
  unit and band from `config/sourcing_targets.json`; value and unit as written; the row URL, DOI, quote, title and
  currency year) with the same fx.
- A row stays checked only when the new check is `checked` and gives the same `value_used` (6 significant digits)
  and the same label. Its note and `judge_name` then name the vote rule.
- Any other outcome sends the row back to its assumed value from `config/default_inputs.json`, with every new
  reason kept under a `re-judge: ` prefix. This includes a fetch that fails now: the rule fails closed.
- Rows that were already assumed are carried unchanged. Nothing is searched again.
- The output file must pass G6. Its meta names the source run and, per checked row, the judge calls, the verdict
  and the reason. A copy is saved as `docs/smoke/T10f_rejudge.json`.
- The re-judge runs once. Then one live study runs on the new file with `tools/ask.py --live --sourcing`. Both are
  reported as they come out; no row is judged again by hand.

## Done when

- `tests/test_judge_votes.py` and the rest of the suite pass.
- Text gate passes; ASCII only.

## Test check by the orchestrator

- Reference build in scratch (the spec applied to a copy of `cite_check.py`): 783 of 783 tests pass (753 old plus
  30 in `tests/test_judge_votes.py`).
- Existing tests changed by the orchestrator, counts only: a checked row now makes 3 judge calls, so the pinned call
  counts in `test_cite_check.py` (1 line), `test_judge_title.py` (8 lines, the same prompt 3 times),
  `test_sourcing.py` (3 + 3 + 3 + 1 calls) and `test_sourcing_yield.py` (2 lines) were updated, and the
  `CitationCheck` field list gained `judge_calls`. No reason text or verdict check changed.
- 19 planted faults, each caught: vote count 2 and 4; field default 1; bool, float and zero votes accepted; other
  error text; stop only on False; stop only on None; never stop; count off by one; full count on a stop; one vote
  short; wrong count when all say yes; title dropped; URL dropped; check_citation with 1 vote; judge_calls not
  stored; judge_calls starting at 1.
