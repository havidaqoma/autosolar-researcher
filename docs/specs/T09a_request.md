# T09a: question to site (`autosolar/request.py`)

## Why

Stage S0. A user types one question ("Is solar plus battery worth it for Karimunjawa?"). The model only reads the
question: it names the place, the country, the kind of question and the language. The coordinates come from a
geocoder (OpenStreetMap Nominatim), never from the model, and must fall inside Indonesia.

Measured first (orchestrator probes, `tools/probe_parse.py`, `runs/parse_probe/probe.json`, and
`runs/geocode_probe/*.json`):

- With `PARSE_INSTRUCTIONS` below, `muse-spark-1.3-contributor` returned one bare JSON object with exactly the
  four keys for 5 of 5 test questions (English and Indonesian), 4.6 to 5.9 s and USD 0.00012 to 0.00017 per call.
  Two answers had spaces after the colons and three did not, so parse with `json.loads`, not by string matching.
- Nominatim answers HTTP 200 with a JSON list (empty for an unknown place). `lat` and `lon` are strings. Without a
  country filter "Sumba" also matches places in the Faroe Islands and Kenya, so the call always sends
  `countrycodes`. "Karimunjawa" gives the village (-5.8796265, 110.4329073) first; "Pulau Karimunjawa" gives the
  island (-5.8296718, 110.4686350).

## Allowed extra dependencies

None beyond `AGENTS.md`. No network in tests (both the model client and the HTTP function are passed in).

## Public API

```python
from autosolar.request import (PARSE_INSTRUCTIONS, QUESTION_TYPES, NOMINATIM_URL, USER_AGENT, INDONESIA_BBOX_DEG,
                               StudyRequest, Site, ParseError, SiteNotFound, GeocodeError, UnsupportedQuestion,
                               parse_question, check_request, geocode)
```

Constants (copy exactly):

```python
PARSE_INSTRUCTIONS = (
    "You turn a user question into a JSON object. Return only the JSON object, no prose, no code fence.\n"
    "Keys:\n"
    '  "site_name": the place the question is about, as written by the user (string, or null if none),\n'
    '  "country": the country of that place in English (string, or null if unknown),\n'
    '  "question_type": "pv_battery_for_diesel_grid" if the user asks whether or how much solar PV and/or '
    'battery storage to add to a power system, else "other",\n'
    '  "language": the ISO 639-1 code of the question.\n'
    "Do not guess coordinates. Do not add other keys."
)
QUESTION_TYPES = ("pv_battery_for_diesel_grid", "other")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "AutoSolarResearcher/0.1 (+https://github.com/havidaqoma/autosolar-researcher)"
INDONESIA_BBOX_DEG = (-11.5, 6.5, 94.5, 141.5)   # lat_min, lat_max, lon_min, lon_max
```

Exceptions: `class ParseError(ValueError)`, `class SiteNotFound(ValueError)`, `class UnsupportedQuestion(ValueError)`,
`class GeocodeError(RuntimeError)`.

```python
@dataclass(frozen=True)
class StudyRequest:
    question: str             # stripped
    site_name: str | None
    country: str | None
    question_type: str        # one of QUESTION_TYPES
    language: str             # two lowercase ASCII letters
    model: str                # result.model of the call
    cost_usd: float           # result.cost_usd of the call

@dataclass(frozen=True)
class Site:
    query: str                # the text sent to the geocoder
    name: str                 # result "name"
    display_name: str         # result "display_name"
    lat_deg: float
    lon_deg: float
    osm_type: str
    osm_id: int
    addresstype: str
    n_candidates: int         # length of the returned list
    source: str               # always "OpenStreetMap Nominatim"
```

### `parse_question(question, client, run_id, *, estimate_usd=0.01) -> StudyRequest`

- `question` must be a `str`; after `.strip()` it must hold 1 to 2000 characters. Else `ValueError`.
- Make exactly one call:
  `client.respond(run_id, "S0_parse", [{"role": "system", "content": PARSE_INSTRUCTIONS}, {"role": "user",
  "content": question_stripped}], estimate_usd=estimate_usd)`. Pass nothing else (the client picks its default
  model). Do not catch the client's exceptions. No retry.
- Read `result.text`: strip it; if it starts with three backticks, drop the first line and a final line of three
  backticks. Then `json.loads`. Any of the following raises `ParseError` whose message holds at most the first 300
  characters of the text: not valid JSON; not a dict; keys not exactly `{"site_name", "country", "question_type",
  "language"}`; `site_name` not a non-empty string after strip and not None; `country` not a string and not None;
  `question_type` not in `QUESTION_TYPES`; `language` not exactly two lowercase ASCII letters.
- Strings are stored stripped.

### `check_request(req: StudyRequest) -> None`

Raise `UnsupportedQuestion` (message says why) when `question_type != "pv_battery_for_diesel_grid"`, when
`site_name is None`, or when `country` is not `"Indonesia"` (compare after `.strip().lower()`; `None` is not
Indonesia). Otherwise return None.

### `geocode(site_name, http_get, *, country_code="id", timeout_s=30.0) -> Site`

- `site_name`: non-empty string after strip, else `ValueError`. `country_code`: two lowercase ASCII letters,
  else `ValueError`. Both are checked before any call.
- Exactly one call: `http_get(NOMINATIM_URL, params={"q": site_name_stripped, "format": "jsonv2", "limit": 3,
  "countrycodes": country_code}, headers={"User-Agent": USER_AGENT}, timeout=timeout_s)`. The return value acts
  like a `requests.Response`: `.status_code` and `.json()`.
- `status_code != 200`: `GeocodeError` naming the status. `.json()` fails or is not a list: `GeocodeError`.
  Empty list: `SiteNotFound` naming the query.
- Use the FIRST element (the geocoder's own ranking). `lat` and `lon` become floats (they arrive as strings; a
  value that does not convert, or is not finite, raises `GeocodeError`). Missing keys (`name`, `display_name`,
  `lat`, `lon`, `osm_type`, `osm_id`, `addresstype`): `GeocodeError`. `osm_id` becomes `int`. An empty `name`
  falls back to `site_name_stripped`.
- When `country_code == "id"` the point must lie inside `INDONESIA_BBOX_DEG` (bounds included), else `ValueError`.

## Done when

`uv run pytest` passes (all tests, including earlier tasks) and `AGENTS.md` rules hold.

## Test check by the orchestrator

The tests in `tests/test_request.py` were run against a throwaway reference implementation of this spec (kept
outside the repo): 43 of 43 passed. So a failing test means the code differs from this spec.
