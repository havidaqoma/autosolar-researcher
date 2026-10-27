# T10e: the judge sees the source title and URL; percent units with a descriptor

Status: spec by the orchestrator. Builder edits `autosolar/cite_check.py` only.
T10a to T10d stay in force except where this spec changes them. `autosolar/sourcing.py` does not change.

## Why

Sourcing run 2 (`docs/smoke/T10_sourcing_run2.json`, measured) left 4 of 7 inputs assumed. Two failures come from
this module, not from the web:

| Input | Failure (measured) | Fix here |
|---|---|---|
| discount_rate_frac | judge says not supported: "the provided source context does not specify that the study concerns solar PV or renewable energy projects in Indonesia". The source title is "100% Renewable Electricity in Indonesia", but the judge never sees a title. | 1, 2, 3 |
| diesel_min_load_frac | `unit: unknown currency in unit '% of its rated capacity'` | 4 |

Orchestrator probe (measured, scratch): for the 4 run 2 sources that could be fetched, the title claimed by the search
appears in the fetched source text (4 of 4, `normalise_text` substring match), the Indonesia PDF included.

The title comes from the search model, the same model that proposes the value. So the judge sees a title only when
the fetched source text contains it. The search cannot steer the judge with a made up title.

## 1. Title only when the source shows it

New constant `MIN_TITLE_CHARS = 12`.

New function `title_in_source(title, pages) -> bool`. True only when all of these hold:

- `title` is a `str` and `pages` is a `list` whose items are all `str`;
- `t = normalise_text(title)` has at least `MIN_TITLE_CHARS` characters;
- `t` is a substring of `normalise_text(" ".join(pages))`.

Anything else gives False. It never raises.

## 2. Judge prompt

New constants `MAX_PROMPT_TITLE_CHARS = 300` and `MAX_PROMPT_URL_CHARS = 500`.

`SUPPORT_INSTRUCTIONS` becomes exactly:

```
"Decide if the quote and source context state the claimed value. "
'Answer with one JSON object {"supports": true or false, "reason": "<one sentence>"}. '
"Use supports true only when the quote and context state this value, "
"in this unit, for the thing described. "
"The source title and URL show what the whole source is about, for example the country it covers, "
"but the value itself must come from the quote and context. "
"Use supports false otherwise. Keep reason to one sentence."
```

New signature: `support_verdict(judge_fn, claim, context, *, source_title=None, source_url=None) -> Verdict`.

The prompt is exactly:

```
SUPPORT_INSTRUCTIONS + "\n\nInput: " + claim.description
+ "\nSource title: " + TITLE
+ "\nSource URL: " + URL
+ "\nClaimed value: " + str(claim.value) + " " + claim.unit
+ "\nQuote: " + claim.quote
+ "\nSource context:\n" + context[:MAX_PROMPT_CONTEXT_CHARS]
```

- `TITLE` is `source_title.strip()[:MAX_PROMPT_TITLE_CHARS]` when `source_title` is a `str` whose strip is not empty,
  else the text `(not shown)`.
- `URL` is `source_url.strip()[:MAX_PROMPT_URL_CHARS]` under the same rule, else `(not shown)`.

Parsing of the judge answer does not change.

## 3. check_citation passes them

When the judge runs (no script reason), `check_citation` calls

```
support_verdict(judge_fn, claim, context,
                source_title=claim.title if title_in_source(claim.title, source.pages) else None,
                source_url=source.final_url)
```

where `source` is the source the quote was found in (the open copy when a mirror was used). The title check uses all
pages of that source, not only the quote page. Nothing else in `check_citation` changes: same reasons, same order,
same `CitationCheck` fields.

## 4. Percent units with a descriptor

`parse_unit` also returns `"%"` when `s0 = unit.strip().lower()` fully matches

```
(%|percent)\s+of\s+[a-z]+(\s+[a-z]+)*
```

for example `% of its rated capacity` or `percent of rated power`. The words after "of" stay in `claim.unit`, which
the judge sees on the "Claimed value" line. The check runs before the existing rules; every unit that parsed before
parses to the same result. Examples that still raise `ValueError`: `% of`, `% of rated power (kW)`, `% of 50 kW`,
`% off peak`, `%of capacity`, `% of rated-power`.

A "%" unit converts only to a `frac` target (existing `_FACTORS`), so a percent of something else cannot become a cost.

## Run 3 rule (pre-registered before the run)

- The orchestrator adds `--carry <sourcing.json>` to `tools/source.py` (an orchestrator tool, not built here). It
  reads the earlier file with `read_sourcing` (G6 must pass), uses its inputs as the base, searches only the `--only`
  inputs, each of which must be `assumed` in the earlier file, and keeps the earlier rows of every other input
  unchanged. The new file must pass G6. Its meta names the carried run and inputs; its search cost counts only the
  new searches.
- Honesty check first (free, local judge): re-run `tools/probe_judge.py` on the 4 saved probe claims with the new
  prompt. The planted trap (a nominal WACC quoted for a real discount rate target) must still get supports false.
  If it flips to true, run 3 does not start and this prompt change is reverted.
- Run 3 is `tools/source.py --carry runs/sourcing/sourcing-20261027T233157-a911c1/sourcing.json --only
  battery_capex_usd_per_kwh battery_om_usd_per_kwh_yr discount_rate_frac diesel_min_load_frac`, with the same
  targets file, judge and live caps. It runs once. Every row is reported as it comes out; no target is re-run by hand.
- Then one live study with `tools/ask.py --live --sourcing` on the run 3 file. Results go in a separate section of
  the notes.

## Done when

- `tests/test_judge_title.py`, `tests/test_cite_check.py` and the rest of the suite pass.
- Text gate passes; ASCII only.

## Test check by the orchestrator

- A throwaway reference implementation (outside the repo) passes 281 of 281 tests in `tests/test_judge_title.py`
  (82), `tests/test_cite_check.py` (68), `tests/test_sourcing.py` (58), `tests/test_sourcing_yield.py` (57) and
  `tests/test_study_sourcing.py` (16).
- The orchestrator changed one place in `tests/test_cite_check.py`: the exact prompt in
  `test_support_verdict_prompt_and_parse` now carries the two `(not shown)` lines (section 2).
- 34 of 34 planted mutations fail at least one test: title length 11, title and URL caps, instruction sentence dropped
  or reworded, no length check, tuple pages accepted, title not normalised, first page only, pages joined without a
  space, no item type check, no strip, truncate before strip, other placeholder, no cap, blank shown, URL line before
  title line, other line label, title always passed, title never passed, claim URL instead of the final URL,
  normalised title shown, title checked on the quote page only, and ten percent rule faults (digits, hyphen, no space
  before "of", "off", prefix match, returns frac, "pct", case sensitive, "percentage", rule missing, trailing period).
- The `--carry` rule in `tools/source.py` was checked offline on the run 2 file: carried rows plus 4 unchanged rows
  pass G6 (3 of 7); leaving out the carried rows fails G6; one new checked row passes G6 (4 of 7); re-searching a
  checked input, a different fx and a duplicate row are refused.
