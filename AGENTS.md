# Rules for coding agents in this repo

AutoSolar Researcher turns one question about a diesel-powered island into a checked solar and battery
pre-feasibility study. Correctness and honest numbers matter more than features.

## Layout

- `autosolar/`: the package. One module per pipeline stage (see `docs/specs/`).
- `tests/`: pytest tests. Tests written by the orchestrator are the acceptance tests for a task. Do not edit or
  delete them unless the task spec says so. You may add new test files.
- `docs/specs/`: task specs. Read the spec named in your task before writing code. Do not edit specs.
- `tools/`: build tooling (for example the Muse Code task runner). Do not edit unless the task says so.

## Hard rules

1. Units are part of every name: `_kwh`, `_kw`, `_kwp`, `_usd`, `_usd_per_kwh`, `_w_m2`, `_kwh_m2_yr`, `_degc`,
   `_l` (litres), `_kg`, `_pct`, `_s`. A value without a unit in its name or schema is a bug.
2. Never convert units silently and never guess a missing value. Raise `ValueError` with a clear message instead.
3. No network calls in unit tests. Code that calls an API takes the HTTP function as an argument or uses a client
   object that tests can replace.
4. Secrets: the only place a key comes from is the environment variable `MODEL_API_KEY`. Never write a key to a
   file, a log, an exception message or a test.
5. Never edit `.env`, `AGENTS.md`, `docs/specs/` or `tools/`.
6. Dependencies: standard library, numpy, pandas, pvlib, requests, jsonschema, pytest. Nothing else unless the spec
   allows it.
7. Text in code, comments and docs: ASCII only. No em dash, no en dash, no double hyphen used as a dash.
8. Keep functions small and typed. Short docstrings that say units.

## Running commands

The shell tool may be unavailable on this machine (Windows sandbox not set up). If a command cannot run, say so
plainly in your final answer and never describe test results you did not see. The orchestrator runs
`uv run pytest` after your task and sends back any failures.

## Final answer

End with: files changed, what each does, anything in the spec you could not do, and any assumption you made.
