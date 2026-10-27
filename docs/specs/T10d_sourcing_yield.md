# T10d: sourcing yield fixes (PDF pages, open copies, unit wording, one retry)

Status: spec by the orchestrator. Builder edits `autosolar/cite_check.py` and `autosolar/sourcing.py` only.
T10a and T10b stay in force except where this spec changes them.

## Why

The first real sourcing run (`docs/smoke/T10_sourcing_run1.json`, measured) checked 1 of 7 inputs. The 6 failures:

| Input | Failure (measured) | Fix here |
|---|---|---|
| pv_capex_usd_per_kwp | `fetch: pdf text extraction failed: LimitReachedError` (IRENA 2022 outlook, 152 pages) | 1 |
| battery_capex_usd_per_kwh | `fetch: HTTP 403` (pmc.ncbi.nlm.nih.gov) | 2 |
| diesel_min_load_frac | `fetch: HTTP 403` (www.mdpi.com) | 2 |
| discount_rate_frac | `fetch: HTTP 403` (IRENA CDN) | 4 |
| pv_om_usd_per_kwp_yr | `unit: cannot convert USD/kWp to USD/kWp/yr` | 3, 4 |
| fuel_price_usd_per_l | `unit: bad unit 'IDR'` | 3, 4 |

Orchestrator probes (measured, scratch): pypdf fails on 3 of the 152 IRENA pages; the cited quote sits on page 56 and
is found exact when the 3 pages are skipped. Europe PMC serves the PMC article as XML (HTTP 200) and the quote is
found exact in it. The MDPI paper is served as a PDF from mdpi-res.com (HTTP 200).

## 1. PDF pages: one bad page does not sink the source

`pdf_pages(data)` keeps calling the module level name `PdfReader` (tests replace it).

- Opening the reader or listing `reader.pages` raises: `FetchError("pdf text extraction failed: " + type name)`,
  as now.
- A page whose `extract_text()` raises becomes the empty string `""`; the other pages are read as now.
- If the PDF has at least 1 page and every page raised: `FetchError("pdf text extraction failed: " + type name of
  the last page exception)`.

A skipped page can only make a quote harder to find, never easier, so no extra flag is recorded.

## 2. Open copies when the publisher blocks scripts

New constants in `cite_check.py`:

- `BLOCKED_STATUS = (401, 403, 429)`
- `MAX_MIRRORS = 4`
- `OPENALEX_WORK_URL = "https://api.openalex.org/works/doi:"`
- `EUROPE_PMC_XML_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"`

New function `mirror_urls(url, doi, http_get, *, timeout_s=30.0) -> list[str]`, open copies of the same work, in this
order:

1. If the host of `url` (lower case) is one of `pmc.ncbi.nlm.nih.gov`, `www.ncbi.nlm.nih.gov`, `ncbi.nlm.nih.gov`,
   `europepmc.org`, `www.europepmc.org` and the URL contains `PMC` followed by digits (regex `PMC[0-9]+`, first
   match): the Europe PMC XML URL for that id.
2. If `doi` is a string: strip it and drop one leading `https://doi.org/`, `http://doi.org/`, `https://dx.doi.org/`
   or `doi:` (prefix match ignores case), as `doi_resolves` does. If the rest matches `^10\.\d{4,9}/\S+$`, call
   `http_get(OPENALEX_WORK_URL + doi, headers={"User-Agent": USER_AGENT}, timeout=timeout_s)` once. Only on status
   200 with a JSON object body (`json.loads(resp.content.decode("utf-8"))`):
   - `ids.pmcid`: when a string containing `PMC[0-9]+`, the Europe PMC XML URL for that id;
   - then `pdf_url` of each entry of `locations`, in list order;
   - then `landing_page_url` of each entry of `locations`, in list order.
   A request exception, other status, bad JSON or a missing or wrongly typed field gives no DOI copies; never raise.
3. Keep only strings that start with `http://` or `https://`, drop the original `url` and repeats (exact string
   match, first one wins), and return at most the first `MAX_MIRRORS`.

No network call happens when `doi` is None or empty or not a DOI and the URL is not a PMC page.

Change in `check_citation`: when fetching `claim.url` fails with the message `"HTTP <code>"` for a code in
`BLOCKED_STATUS`, call `mirror_urls(claim.url, claim.doi, http_get, timeout_s=timeout_s)` and try each copy in order
with `fetch_source`. The first copy that fetches and where `find_quote(claim.quote, copy.pages).found` is true
becomes the source; stop there. Copies that fail to fetch or lack the quote are skipped.

- A copy was used: the `"fetch: HTTP <code>"` reason is removed. All later checks (quote, value in quote, DOI,
  judge) run on that copy as for any source, and `final_url`, `is_pdf`, `page` come from it.
- No copy was used and the list was not empty: keep the fetch reason and append
  `"mirror: no open copy with the quote (<n> tried)"` with n the list length.
- Empty list: reasons as before (only the fetch reason).
- Other fetch failures (404, timeouts, size, no text): no copies are tried.

Call order for `http_get`: the claim URL, the OpenAlex lookup (if any), the copies in order (until one is used), then
the DOI handle check, then the judge.

## 3. Unit wording in the search prompt

`SEARCH_INSTRUCTIONS` changes in two places only. First line ends `...published in 2021 or later. Prefer open access
sources.` and the unit line becomes:

```
  "unit": the unit as written in the source, including what it is per (for example USD/kWh/yr or IDR/L), never a bare currency (string),
```

The exact constant is in `tests/test_sourcing.py` (`EXPECTED_INSTRUCTIONS`).

## 4. One more search when a script check fails

New in `sourcing.py`:

- `MAX_SEARCH_TRIES = 2`
- `NO_RETRY_PREFIXES = ("judge says not supported", "judge gave no verdict", "no source found")`
- `search_claim(client, run_id, target, feedback="")`: the user message is the T10b text, plus `" " + feedback` when
  `feedback` is not empty. Everything else as T10b.
- `retry_feedback(reasons, url) -> str | None`: None when any reason starts with one of `NO_RETRY_PREFIXES` or
  contains `"outside band"`, or when `reasons` is empty. Otherwise
  `"A previous answer could not be used: " + ascii_text("; ".join(reasons))[:300] + "."`, then
  `" Do not use " + ascii_text(url) + "."` when `url` is not empty, then `" Find a different source."`

Why these rules: a judge "no" or an out-of-band value is a finding about the number, so searching again would shop for
a different answer. A fetch, unit, quote or DOI failure says nothing about the number, so one more search is fair.

`source_inputs`, per target:

1. Try 1 as in T10b. Its reasons are `[reason]` when no claim came back, else the check reasons. Checked: row as
   T10b, done.
2. Else `fb = retry_feedback(reasons_1, claim_1.url if claim_1 else "")`. None: row as T10b (one try, reasons as
   they are), done.
3. Else try 2: `search_claim(..., feedback=fb)` then the same check. `search_cost_usd` of the row is
   `cost_1 + cost_2`.
   - Try 2 checked: the checked row and input as T10b from try 2, with `"; found on search try 2"` appended at the
     very end of the input note.
   - Try 2 not checked: an assumed row. Its claim fields (value and unit as written, currency year, title, url, doi,
     doi_ok, page, quote_kind, quote, supports) come from try 2 when try 2 returned a claim, else from try 1 (the T10b
     no-claim values when neither returned one). `reasons` is `["try 1: " + r for r in reasons_1] +
     ["try 2: " + r for r in reasons_2]`.
4. `BudgetExceeded` from either try propagates, as in T10b.

At most `MAX_SEARCH_TRIES` searches per target. G6, the file format and `SourcingRow` fields do not change.

## Run 2 rule (pre-registered before the run)

Run 2 uses the same `config/sourcing_targets.json` (7 targets, same bands, fx 16500 assumed), the same judge (local
Muse Glimmer, low strength), `tools/source.py` unchanged, and the live caps. It runs once. Every row is reported as it
comes out; no target is re-run by hand. Results go in a separate section of the notes, next to run 1.

## Done when

- `tests/test_sourcing_yield.py`, `tests/test_sourcing.py` and `tests/test_cite_check.py` pass with the rest of the
  suite.
- Text gate passes; ASCII only.

## Test check by the orchestrator

- A throwaway reference implementation (outside the repo) passes 199 of 199 tests in `tests/test_sourcing_yield.py`
  (57), `tests/test_sourcing.py` (58), `tests/test_cite_check.py` (68) and `tests/test_study_sourcing.py` (16).
- The orchestrator changed two places in `tests/test_sourcing.py`: `EXPECTED_INSTRUCTIONS` (section 3) and the DOI
  test, which now gets a second search (section 4; a DOI failure is a retry case).
- 34 planted mutations of that reference each fail at least one test: every bad page raises, all bad pages pass, first
  page error named, only 403 blocked, 404 tries copies, fetch reason kept after a copy is used, mirror reason words,
  copy used without the quote, copy fetch error stops the loop, mirror reason with no copies, no cap, no dedupe,
  original URL kept, landing pages before PDFs, PMC rule on any host, OpenAlex call without User-Agent, fixed
  timeout, OpenAlex status ignored, OpenAlex pmcid dropped, DOI prefix case, scheme not checked, no retry, retry after
  a judge no, retry after a band failure, feedback cut at 200, no URL in feedback, URL not made ASCII, feedback not
  sent, cost not summed, no try 2 note, no try prefixes, claim fields kept from try 1, retry on empty reasons, and the
  open access line dropped.
