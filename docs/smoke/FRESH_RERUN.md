# Fresh re-run of the example study (measured)

Question: does the example study come out the same when nothing is reused? The AI judges (round 3) noted that the
demo's first command prints `reused`, so nothing is computed on camera. This file records one re-run in an empty
runs folder.

## What was run (Saturday 31 Oct, evening, at commit 40324ff)

- `tools/ask.py` with the example question ("Is solar plus battery worth it for Karimunjawa? The island runs on
  diesel."), the same sourcing file as the example study
  (`runs/sourcing/rejudge-20261028T225230-d577a6/sourcing.json`) and `--runs` pointed at an empty folder outside
  the repo.
- Weather came from the local cache `runs/weather_cache/` only: a wrapper script replaced every weather fetcher with
  one that raises, so no weather service was called (measured: the run finished, so no fetch was needed).
- One Meta model call was made, the question parse (USD 0.000128, computed from tokens, logged in
  `ledger/api_usage.jsonl`). A first attempt stopped before the study because the CAMS address variable was unset;
  its question parse is logged too.

## Result (measured)

| Check | Result |
|---|---|
| Run hash | b4a44fc6d4c32339, the same as the committed example study |
| Time | 603.9 s on the build laptop (the 925 designs, the reserve rule and the sensitivity runs) |
| `design_table.csv`, `sensitivity.csv`, `inputs.json`, `site.json`, `report.md` | byte-identical to `runs/studies/b4a44fc6d4c32339/` |
| `report.json` | 23 facts and 11 gates compared with `docs/site/data/b4a44fc6d4c32339/report.json`: all equal except the question-parse cost (USD 0.0001275 vs 0.0001285, one token count) and the total cost that includes it |
| `request.json` | differs only in that same parse cost |

So the answer (7,250 kWp and 19,000 kWh at 0.251 USD/kWh vs 0.354 diesel only) is recomputed, not stored: an empty
folder gives the same hash and the same tables. The weather and the sourced prices are inputs kept on disk; a run
that also refreshes them is a new study with a new hash.

## How to do it for the video

With the CAMS address set as for any run, point `--runs` at an empty folder outside the repo (`runs/` is ignored by
git):

```
uv run python tools/ask.py "Is solar plus battery worth it for Karimunjawa? The island runs on diesel." \
  --sourcing runs/sourcing/rejudge-20261028T225230-d577a6/sourcing.json --runs <empty folder>
```

It prints `new` instead of `reused` and takes about 10 minutes, so a recording needs a cut or a time-lapse that says
so on screen.
