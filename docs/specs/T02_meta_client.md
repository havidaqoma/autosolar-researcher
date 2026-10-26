# T02: Meta Model API client (`autosolar/meta_client.py`)

Status: spec by the orchestrator. Acceptance tests: `tests/test_meta_client.py` (do not edit them).
Depends on: `autosolar/ledger.py` (T01, done).

## Why

One small wrapper for every paid call to the Meta Model API (Responses API). It enforces the cost rules before a
call, logs the measured usage after it, retries only when retrying is safe, and never leaks the API key.

## API facts (Meta docs)

- `POST https://api.meta.ai/v1/responses` with header `Authorization: Bearer <key>` and a JSON body
  `{"model": ..., "input": ..., ...}`. Optional body fields used here: `tools` (list), `reasoning`
  (`{"effort": "low" | "medium" | "high"}`), `include` (list), `metadata` (dict).
- A successful response is JSON with `model`, `id`, `output` (list of items) and `usage`. Items of type
  `message` hold `content` parts; parts of type `output_text` carry `text` and `annotations`. An annotation of
  type `url_citation` carries `url`, `title`, `start_index`, `end_index`. Each item of type `web_search_call` is
  one billed search query.
- `usage` = `{"input_tokens", "input_tokens_details": {"cached_tokens"}, "output_tokens",
  "output_tokens_details": {"reasoning_tokens"}}`. The details objects may be missing; treat missing as 0.
- Rate limit headers on success: `x-ratelimit-limit-requests`, `x-ratelimit-remaining-requests`,
  `x-ratelimit-limit-tokens`, `x-ratelimit-remaining-tokens`.
- `sam-3.1` is billed per image, not per token.

## Public API

```python
from autosolar.meta_client import MetaClient, MetaAPIError, Result, STANDARD_SPARK_MODELS, DEFAULT_MODEL
```

- `DEFAULT_MODEL = "muse-spark-1.3-contributor"`.
- `STANDARD_SPARK_MODELS = frozenset({"muse-spark-1.3", "muse-spark-1.2", "muse-spark-1.1"})`.
- `class MetaAPIError(RuntimeError)`.
- `@dataclass class Result`: `text: str`, `citations: list[dict]` (keys `url`, `title`, `start_index`,
  `end_index`), `web_searches: int`, `usage: dict` (the counts passed to the ledger), `cost_usd: float`,
  `response_id: str | None`, `model: str`, `rate_limit: dict[str, str]` (the four headers that are present),
  `raw: dict`.
- `MetaClient(ledger, *, api_key=None, base_url="https://api.meta.ai/v1", post=None, sleep=time.sleep,
  max_retries=4, timeout_s=300.0)`
  - `api_key=None` reads the environment variable `MODEL_API_KEY`. Missing or empty: raise `RuntimeError` that
    says the variable is not set.
  - `post` defaults to `requests.post`. It is called as `post(url, headers=..., json=..., timeout=...)` and
    returns an object with `status_code`, `headers`, `text` and `json()`.
- `MetaClient.respond(run_id, stage, input, *, estimate_usd, model=DEFAULT_MODEL, live=False, tools=None,
  reasoning_effort=None, include=None, metadata=None, allow_standard=False, images=0) -> Result`

## Rules for `respond`, in order

1. Before any HTTP call:
   - `model` in `STANDARD_SPARK_MODELS` and `allow_standard` false: raise `ValueError` (rule D15: contributor
     mode by default).
   - `model` not in the ledger `PRICES`: raise `UnknownModel` (use the ledger's function or table).
   - A per image model (ledger kind `per_image`) needs `images >= 1`, else `ValueError`. A token model needs
     `images == 0`, else `ValueError`.
   - `ledger.check(run_id, estimate_usd, live=live)`; let `BudgetExceeded` propagate.
2. Build the body: `model`, `input`, and only the optional fields that were given (`reasoning_effort` becomes
   `{"reasoning": {"effort": ...}}`).
3. Send. Retry on status 429, 500, 502, 503, 504 and on `requests.ConnectionError` or `requests.Timeout`: wait
   `sleep(0.5 * 2 ** attempt + random.uniform(0, 0.25))` seconds (attempt 0, 1, 2, ...), at most `max_retries`
   retries, then raise `MetaAPIError`. Any other non 200 status: raise `MetaAPIError` at once, no retry.
4. Every `MetaAPIError` message contains the status code (if any) and at most 500 characters of the response
   body, with every occurrence of the API key replaced by `<key>`. The key must never appear in any exception
   message, in `Result`, or in the ledger.
5. On 200: for a token model, record in the ledger `input_tokens`, `cached_tokens`, `output_tokens`,
   `reasoning_tokens` and `search_queries` (the number of `web_search_call` items). A token model response
   without `usage` raises `MetaAPIError` (a call that cannot be costed must be seen). For a per image model,
   record `images=images` and ignore any token counts in the response.
6. After recording: if the response names a `model` different from the requested one, raise `MetaAPIError`
   (the cost row stays in the ledger).
7. Return the `Result`. `text` is every `output_text` part of every `message` item joined with "" in order.

## Done when

`uv run pytest` passes (all tests, including T01), no test touches the network, and `AGENTS.md` rules hold.
