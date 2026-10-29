# T19: the two-model judge panel by default, and a plain refusal

Status: spec and tests (`tests/test_tools_t19.py`) written before the code. This task changes two orchestrator
tools, `tools/source.py` and `tools/ask.py`, which are glue around the engine. It does not touch `autosolar/`, so no
Muse Code run is needed. All earlier specs stay in force except where this spec changes them.

## Why

Since T17 the engine has a judge panel: the local Muse Glimmer judge casts votes 1 and 2 and `muse-wonder-1.0` casts
vote 3 (`autosolar.sourcing.judge_panel`). Only `tools/rejudge.py --panel` used it. A new search
(`tools/source.py`) still used the local judge for all 3 votes, although T17 says three votes from one model can
share one blind spot. All three AI judges in round 2 named this gap. From now on a new search uses the panel unless
told otherwise.

A question about a site the tool cannot study (more than 30 km from Karimunjawa, outside Indonesia, or not found)
ended in a Python traceback. It should end with a plain answer that says why.

## 1. tools/source.py

- New constant `PANEL_JUDGE_NAME`, the same string as `tools/rejudge.py` uses:
  `JUDGE_NAME + " (votes 1 and 2) and muse-wonder-1.0 (vote 3), yes needed in all 3 votes"` (3 is `JUDGE_VOTES`).
- New class `VoteLog(name, fn, log)`: calling it calls `fn(prompt)` and appends to `log` one dict with `judge`
  (the name) and `seconds` (rounded to 0.1), plus `raw` (the answer, at most 2000 characters) or `error`
  (`"<type>: <message>"`, at most 200 characters of message). An exception is appended and then raised again, so
  `support_verdict` still counts it as a judge error, which is a no.
- New function `build_judge(mode, *, local_fn, wonder_fn, log) -> (judge_fn, judge_name)`:
  - `"panel"`: `judge_panel(VoteLog("local", local_fn, log), VoteLog("wonder", wonder_fn, log))`, name
    `PANEL_JUDGE_NAME`. The tuple holds `JUDGE_VOTES` callables, local, local, wonder.
  - `"local"`: `VoteLog("local", local_fn, log)`, name `JUDGE_NAME` (the T10f behaviour, kept so earlier runs can
    be repeated). `wonder_fn` is never called.
  - Any other mode: `ValueError("judge mode must be panel or local")`.
- New function `build_parser()` returning the `argparse.ArgumentParser` of `main`. It adds
  `--judge {panel,local}` with default `panel`; the other options do not change.
- `main` builds the Wonder judge as `functools.partial(wonder_judge, client=client, run_id=run_id)` with the same
  client as the search (cost in the ledger, caps checked before each call), calls `build_judge`, and passes the
  result to `source_inputs`. The meta gets `judge_mode` and `votes` (the log). `judge_seconds` still lists the local
  judge's times.

## 2. tools/ask.py

- New tuple `REFUSALS = (UnsupportedSite, UnsupportedQuestion, SiteNotFound)`. `GeocodeError` is not in it: a
  service failure is not an answer about the site.
- New function `refusal_lines(exc, question, runs_dir) -> list[str]`:
  - Line 1: `"No study: " + str(exc) + "."`
  - For `UnsupportedSite` only, when the cached request file exists (`runs_dir/requests/<first 16 hex of
    sha256(question.strip())>.json`, the file `run_study` writes), line 2:
    `"<site name> (<display name>) is <d> km from Karimunjawa; the demand model covers sites within <r> km
    (computed)."`, with `d` from `haversine_km` to `KARIMUNJAWA_DEG` and `r` = `DEMAND_RADIUS_KM`, both with no
    decimals and a thousands comma.
  - Last line, always: `"The hourly load comes from one published study of Karimunjawa. A new site needs its own
    hourly load."`
- `main` catches `REFUSALS` around `run_study`, prints the lines and exits with code 2. Nothing else is caught.
- The CAMS address is read only when weather is needed (inside `weather_fn`), so a reused study or a refusal needs
  only the model key.

## Done when

- `tests/test_tools_t19.py` and the rest of the suite pass, with no network.
- Planted faults in the two tools are caught by the new tests.
- Text gate passes; ASCII only.
- One live smoke of each, by the rules in `docs/smoke/T19_SMOKE_RULES.md`, written before the runs.
