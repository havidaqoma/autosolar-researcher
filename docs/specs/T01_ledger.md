# T01: cost ledger (`autosolar/ledger.py`)

Status: spec by the orchestrator. Acceptance tests: `tests/test_ledger.py` (do not edit them).

## Why

Every paid Meta API call must be logged with its model, its usage and its cost, and a study must stop before it
goes over its budget. Budget rules from the plan: USD 5 per study, a global pause at USD 100, and for the live demo
USD 2 per run and USD 5 per UTC day.

## Prices (Meta pricing page, pay as you go)

| Model id | Unit | Price |
|---|---|---|
| `muse-spark-1.3-contributor`, `muse-spark-1.2-contributor` | per 1M tokens | input 0.10, cached input 0.002, output 0.20 |
| `muse-spark-1.3`, `muse-spark-1.2`, `muse-spark-1.1` | per 1M tokens | input 1.25, cached input 0.15, output 4.25 |
| `muse-wonder-1.0` | per 1M tokens | input 4.00, cached input 0.20, output 20.00 |
| `sam-3.1` | per image | 0.0025 |
| `muse-image-1.0` | per generated image | 0.01 |
| `muse-voice-transcribe-1.0` | per second of audio | 0.18 per hour = 0.00005 per second |
| `muse-glimmer-local` | local open weights | 0 |
| web search grounding (token models only) | per query | 0.0025 |

`input_tokens` includes `cached_tokens`. Fresh input = input minus cached. `output_tokens` already includes
reasoning tokens; never add reasoning tokens again.

## Public API

```python
from autosolar.ledger import (PRICES, WEB_SEARCH_USD_PER_QUERY, UnknownModel, BudgetExceeded,
                              call_cost_usd, Ledger)
```

- `PRICES: dict[str, dict]`: one entry per model id above. Each entry has `"kind"`: one of `"tokens"`,
  `"per_image"`, `"per_audio_s"`, `"free"`, plus its price fields.
- `WEB_SEARCH_USD_PER_QUERY = 0.0025`.
- `class UnknownModel(ValueError)`.
- `class BudgetExceeded(RuntimeError)`: the message names the cap that would be broken and the numbers.
- `call_cost_usd(model, *, input_tokens=0, cached_tokens=0, output_tokens=0, reasoning_tokens=0, images=0,
  audio_s=0, search_queries=0) -> float` (USD).
  - Unknown model: raise `UnknownModel`.
  - Any negative count, or `cached_tokens > input_tokens`: raise `ValueError`.
  - `reasoning_tokens` is accepted for logging only and does not change the cost.
  - Wrong unit for the model: raise `ValueError`. Token counts or search queries given to a per image, per audio
    or free model; images or audio given to a token model; images given to an audio model and so on.
    Exception: `muse-glimmer-local` accepts token counts (logged, cost 0) but no images, audio or search.
- `class Ledger(path, *, study_cap_usd=5.0, total_cap_usd=100.0, live_run_cap_usd=2.0, live_daily_cap_usd=5.0,
  clock=time.time)`
  - The ledger is a JSON lines file at `path`. A missing file means nothing spent. It is read on every query, so
    two `Ledger` objects on the same file see the same totals.
  - `record(run_id, stage, model, *, live=False, **usage) -> dict`: computes the cost with `call_cost_usd`,
    appends one line and returns the row. Row keys: `ts_unix` (float, from `clock()`), `run_id`, `stage`,
    `model`, `live` (bool), `usage` (dict of the counts passed), `cost_usd` (float). An unknown usage key (for
    example `tokens_in`) raises `ValueError` and writes nothing. `record` never refuses because of a cap: the
    call has already happened and must be logged.
  - `rows() -> list[dict]`. A line that is not valid JSON raises `ValueError` (never skip it silently).
  - `spent_usd(run_id=None, live_day=None) -> float`: total of all rows; or of one run; or, with `live_day` (a
    `datetime.date`), of live rows whose UTC date of `ts_unix` is that day.
  - `check(run_id, estimate_usd, *, live=False) -> None`: call before a paid call. Raises `BudgetExceeded` if
    adding `estimate_usd` would take any of these above its cap: the run total (study cap), the ledger total
    (total cap), and when `live` is true also the run total (live run cap) and the live total for the UTC day of
    `clock()` (live daily cap). Exactly equal to a cap is allowed: compare with a tolerance of 1e-9 USD so float
    sums such as 4.9 + 0.1 count as equal to 5.0. Negative estimate: `ValueError`.

## Done when

`uv run pytest tests/test_ledger.py` passes, the module has no network code, and the rules in `AGENTS.md` hold.
