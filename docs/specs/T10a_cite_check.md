# T10a: citation checker for sourced inputs (`autosolar/cite_check.py`)

## Why

Stage S3 replaces hand-entered inputs with values found by Muse Spark search. A model can misquote, misread a
table, or name a page that does not hold the number. This module checks one claimed value against its source by
script, and only then asks a second model whether the quote supports the value (plan R4, gate G6). Anything that
fails stays labelled assumed. This module makes no model call itself: the judge is a function passed in.

Measured behaviour this spec rests on (`docs/smoke/T10_search_probe.json`, made by `tools/probe_search.py` and
`tools/probe_search_quotes.py`): 4 of 4
answers named a URL that fetched with HTTP 200; 2 of 4 sources were PDFs; with PDF text extraction 3 of 4 quotes
appear verbatim after normalising; the fourth differs by one dropped token ("(IEA, 2020 )" quoted as "(IEA, )").
The DOI handle API answers HTTP 200 with `responseCode` 1 for a registered DOI and HTTP 404 with `responseCode`
100 for an unknown one.

## Allowed extra dependencies

`pypdf` (already added to `pyproject.toml` by the orchestrator). Nothing else beyond `AGENTS.md`. No network in
tests: every function that fetches takes `http_get`, called like `requests.get`.

## Public API

```python
from autosolar.cite_check import (USER_AGENT, MAX_SOURCE_BYTES, MIN_QUOTE_CHARS, CONTEXT_CHARS,
                                  MAX_PROMPT_CONTEXT_CHARS, SUPPORT_INSTRUCTIONS, FetchError, Source, QuoteMatch,
                                  Verdict, Claim, CitationCheck, normalise_text, html_to_text, pdf_pages,
                                  fetch_source, find_quote, numbers_in, parse_unit, convert_value, doi_resolves,
                                  support_verdict, check_citation)
```

### Constants

```python
USER_AGENT = "AutoSolarResearcher/0.1 (+https://github.com/havidaqoma/autosolar-researcher)"
MAX_SOURCE_BYTES = 25_000_000
MIN_QUOTE_CHARS = 20          # normalised characters
CONTEXT_CHARS = 400           # characters kept on each side of a matched quote
MAX_PROMPT_CONTEXT_CHARS = 3000
SUPPORT_INSTRUCTIONS: str     # any ASCII text that asks for the JSON answer described under support_verdict
```

`class FetchError(RuntimeError)`.

### Dataclasses (all `@dataclasses.dataclass`, field order as listed)

```python
Source(url: str, final_url: str, status_code: int, is_pdf: bool, pages: list[str], bytes_len: int)
QuoteMatch(found: bool, kind: str, page: int | None, start: int | None, end: int | None,
           skipped_source_tokens: int, missing_quote_tokens: int, context: str)
Verdict(supports: bool | None, reason: str, raw: str)
Claim(input_name: str, description: str, value: float | int, unit: str, url: str, doi: str | None,
      quote: str, title: str, currency_year: int | None)
CitationCheck(input_name: str, status: str, reasons: list[str], value_as_written: float, unit_as_written: str,
              value_converted: float | None, target_unit: str, url: str, final_url: str | None,
              is_pdf: bool | None, page: int | None, quote_kind: str, doi: str | None, doi_ok: bool | None,
              supports: bool | None, judge_reason: str, judge_name: str, context: str)
```

`QuoteMatch.kind` is `"exact"`, `"near"` or `"none"`. `CitationCheck.quote_kind` is one of those or `"not run"`.
`CitationCheck.status` is `"checked"` or `"assumed"`. `dataclasses.asdict(check)` must pass `json.dumps`.

### `normalise_text(text: str) -> str`

In this order: `html.unescape`; `unicodedata.normalize("NFKC", ...)`; replace U+2018 and U+2019 with `'`, U+201C
and U+201D with `"`, U+2010, U+2011, U+2012, U+2013, U+2014 and U+2212 with `-`; replace U+00A0, U+2009 and U+202F
with a space; delete U+00AD; lowercase; collapse every run of whitespace to one space; strip.

### `html_to_text(html_str: str) -> str`

Remove `<script>`, `<style>` and `<noscript>` elements with their content (case-insensitive, across lines),
replace every remaining tag with a space, then return `normalise_text` of the result.

### `pdf_pages(data: bytes) -> list[str]`

One string per page from `pypdf.PdfReader(io.BytesIO(data))`, `page.extract_text() or ""`, each passed through
`normalise_text`. Any exception from pypdf becomes `FetchError("pdf text extraction failed: <ExceptionName>")`.

### `fetch_source(url, http_get, *, timeout_s: float = 30.0) -> Source`

1. `url` must be a `str` starting with `http://` or `https://`, else `FetchError("url must start with http:// or
   https://")` and `http_get` is not called.
2. Call `http_get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout_s, allow_redirects=True)`. Any
   `requests.RequestException` becomes `FetchError("<ExceptionName>")`.
3. `status_code != 200` gives `FetchError("HTTP <code>")`. `len(content) > MAX_SOURCE_BYTES` gives
   `FetchError("source larger than MAX_SOURCE_BYTES")`.
4. `is_pdf` is `content[:5] == b"%PDF-"` (the content type header is not trusted). Pages: `pdf_pages(content)`
   for a PDF, else `[html_to_text(content.decode("utf-8", errors="replace"))]`.
5. If every page is empty after strip: `FetchError("no text in source")`.
6. `final_url` is `resp.url` when it is a non-empty string, else `url`. `bytes_len` is `len(content)`.

### `find_quote(quote: str, pages: list[str]) -> QuoteMatch`

Both sides are compared after `normalise_text` (pages from `fetch_source` already are; normalise again anyway).
Offsets and `context` refer to the normalised page text.

- Let `q = normalise_text(quote)`. If `len(q) < MIN_QUOTE_CHARS`: not found.
- Exact: the first page (in order) whose text contains `q`; `start` is the first index, `end = start + len(q)`,
  kind `"exact"`, skipped and missing 0.
- Near (only when no page has an exact match): tokens are `re.finditer(r"[a-z0-9]+", text)` with their spans.
  Quote tokens `qt` need at least 5 tokens, else not found. `max_missing = len(qt) // 10`,
  `max_skipped = max(3, len(qt) // 10)`. For each page in order, for each source token index `i` (in order)
  whose token equals `qt[0]`: set `k = i + 1`, `last = i`, `missing = 0`, `skipped = 0`; for each later quote
  token, look at source tokens `k, k + 1, k + 2, k + 3` (those that exist) and take the first equal one at
  index `f`: then `skipped += f - k`, `k = f + 1`, `last = f`; if none is equal, `missing += 1` (k unchanged).
  Give up on this `i` as soon as `missing > max_missing` or `skipped > max_skipped`. The first `i` that gets
  through all quote tokens wins: kind `"near"`, `start` = start of token `i`, `end` = end of token `last`.
- `context = page[max(0, start - CONTEXT_CHARS): end + CONTEXT_CHARS]`. `page` is 1-based.
- Not found: `QuoteMatch(False, "none", None, None, None, 0, 0, "")`.

### `numbers_in(text: str) -> list[float]`

Sorted list of the distinct float values of every match (overlapping allowed) of these three patterns on `text`,
with `,` and spaces removed before `float()`:

```python
r"(?<![0-9])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![0-9])"   # 1,119 and 11,420.5
r"(?<![0-9])\d{1,3}(?: \d{3})+(?:\.\d+)?(?![0-9])"   # 2 571 (thin space after normalising)
r"(?<![0-9])\d+(?:\.\d+)?(?![0-9])"                  # 192 and 9.4
```

### `parse_unit(unit: str) -> str`

Returns a canonical unit or raises `ValueError` naming the unit. Steps on `s = unit.strip().lower()` with all
spaces removed:

1. `s` in `{"%", "percent", "pct", "%/yr", "%/year", "%peryear", "%pa"}` gives `"%"`; `s` in `{"frac",
   "fraction"}` gives `"frac"`.
2. Replace `"-yr"` and `"-year"` with `"/yr"`, then every `"per"` with `"/"`.
3. Currency prefix, checked in this order: `"us$"`, `"usd"`, `"$"` give `USD`; `"idr"`, `"rp"` give `IDR`. No
   prefix: `ValueError`. Strip a `"."` right after the prefix (as in `rp./l`).
4. The rest must start with `"/"`. Split it on `"/"`, drop empty parts; 1 or 2 parts, else `ValueError`.
5. Map each part: `kwh` kWh, `mwh` MWh, `kw` kW, `kwp` kWp, `mw` MW, `mwp` MWp, `w` W, `wp` Wp, `l`, `lt`,
   `ltr`, `liter`, `litre`, `liters`, `litres` L, `yr`, `year`, `a`, `annum` yr. Unknown part: `ValueError`.
6. Return `"<CUR>/" + "/".join(parts)`, for example `"USD/kW/yr"` or `"IDR/L"`.

### `convert_value(value, unit_canonical: str, target_unit: str, *, fx_idr_per_usd: float | None = None) -> float`

Allowed pairs (factor multiplies the value). Any other pair: `ValueError`. Any `IDR/...` source unit uses the USD
factor of the same denominator divided by `fx_idr_per_usd`, which must be a finite number above 0, else
`ValueError("IDR value needs fx_idr_per_usd")`. `value` must be a finite int or float (not bool).

| target_unit | source unit: factor |
|---|---|
| `USD/kWp` | `USD/kWp` 1, `USD/kW` 1, `USD/Wp` 1000, `USD/W` 1000, `USD/MWp` 0.001, `USD/MW` 0.001 |
| `USD/kW` | `USD/kW` 1, `USD/W` 1000, `USD/MW` 0.001 |
| `USD/kWh` | `USD/kWh` 1, `USD/MWh` 0.001 |
| `USD/kWp/yr` | `USD/kWp/yr` 1, `USD/kW/yr` 1, `USD/MWp/yr` 0.001, `USD/MW/yr` 0.001 |
| `USD/kWh/yr` | `USD/kWh/yr` 1, `USD/MWh/yr` 0.001 |
| `USD/L` | `USD/L` 1 |
| `frac` | `%` 0.01, `frac` 1 |

### `doi_resolves(doi: str, http_get, *, timeout_s: float = 30.0) -> bool`

1. Strip; remove a leading `https://doi.org/`, `http://doi.org/`, `https://dx.doi.org/` or `doi:` (prefix match
   ignoring case). If the result does not match `^10\.\d{4,9}/\S+$`, return False without a call.
2. `http_get("https://doi.org/api/handles/" + doi, headers={"User-Agent": USER_AGENT}, timeout=timeout_s)`. A
   `requests.RequestException` becomes `FetchError("doi check: <ExceptionName>")`.
3. HTTP 404: False. HTTP 200: `json.loads(resp.content.decode("utf-8"))["responseCode"] == 1` (a body that does
   not parse gives False). Any other status: `FetchError("doi check HTTP <code>")`.

### `support_verdict(judge_fn, claim: Claim, context: str) -> Verdict`

Prompt, exactly:

```python
SUPPORT_INSTRUCTIONS + "\n\nInput: " + claim.description + "\nClaimed value: " + str(claim.value) + " "
+ claim.unit + "\nQuote: " + claim.quote + "\nSource context:\n" + context[:MAX_PROMPT_CONTEXT_CHARS]
```

`SUPPORT_INSTRUCTIONS` asks for one JSON object `{"supports": true or false, "reason": "<one sentence>"}`, true
only when the quote and context state this value, in this unit, for the thing described. It must contain the
literal text `"supports"` and `"reason"` and be ASCII only.

Call `judge_fn(prompt)` once. It returns a string. Parse: strip; if it starts with three backticks drop the first
line and anything from the last three backticks on; try `json.loads`; if that fails, try `json.loads` on the
first `re.search(r"\{.*\}", text, re.S)` match. A dict with a bool `"supports"` and a str `"reason"` gives
`Verdict(supports, reason[:500], raw[:2000])`. Anything else gives `Verdict(None, "unparsed judge answer",
raw[:2000])`. If `judge_fn` raises, `Verdict(None, "judge error: <ExceptionName>", "")`.

### `check_citation(claim, *, http_get, judge_fn, judge_name: str, target_unit: str, band_lo: float, band_hi: float, fx_idr_per_usd: float | None = None, timeout_s: float = 30.0) -> CitationCheck`

`claim.value` must be a finite int or float (not bool), else `ValueError`. Steps, collecting reason strings:

1. Unit: `parse_unit(claim.unit)` then `convert_value(...)`. A `ValueError` adds `"unit: <message>"` and leaves
   `value_converted` None. Else if the converted value is outside `[band_lo, band_hi]` add
   `"value <converted:g> <target_unit> outside band [<band_lo:g>, <band_hi:g>]"`.
2. Fetch: `fetch_source(claim.url, http_get, timeout_s=timeout_s)`. A `FetchError` adds `"fetch: <message>"`
   and skips steps 3 and 4 (`quote_kind` stays `"not run"`).
3. Quote: `find_quote(claim.quote, source.pages)`. Not found adds `"quote not found in source"`.
4. Value: only when the quote was found. The value is in the quoted text when some number in
   `numbers_in(page_text[start:end])` (the normalised page text of the matched page) equals `claim.value` within
   `1e-9 * max(1, abs(claim.value))`. Else add `"value not in the quoted source text"`.
5. DOI: only when `claim.doi` is a non-empty string. False adds `"doi does not resolve"`; a `FetchError` adds
   `"doi check failed: <message>"`.
6. Judge: only when no reason was added so far (no model money spent on a claim that already failed).
   `supports` False adds `"judge says not supported: <reason>"`; None adds `"judge gave no verdict: <reason>"`.

`status` is `"checked"` when `reasons` is empty, else `"assumed"`. `judge_reason` is the verdict reason or `""`
when the judge did not run; `supports` None when it did not run. `context` is the match context, else `""`.
`page`, `final_url` and `is_pdf` come from the match and the source when present, else None.

## Done when

`uv run pytest tests/test_cite_check.py` passes, the full suite still passes, and the module is ASCII only.

## Test check by the orchestrator

- A throwaway reference implementation (outside the repo) passes 68 of 68 tests in `tests/test_cite_check.py`.
- 8 planted mutations of that reference each fail at least one test: no near match, a 5 token look-ahead window,
  skipped DOI check, judge run after a failed check, no value check, PDF chosen by content type, no space-grouped
  numbers, script text kept.
- The reference run on the saved source bytes of the 4 probe answers (judge stubbed) gives script checks pass for
  4 of 4: quote kinds exact, near, exact, exact; PDF pages 6 and 27 (measured, `docs/smoke/T10_search_probe.json`).
