# T19 smoke runs: rules written before the runs

Two live runs check the T19 tools end to end. They are smoke runs: no study uses their output, and each is reported
as it comes out.

## 1. Refusal

- Command: `tools/ask.py "Is solar plus battery worth it for Bawean Island? It runs on diesel."` with the model
  key from the env file and no CAMS address set.
- Bawean is an island in the Java Sea that also runs on diesel, about 250 km east of Karimunjawa (assumed, from a
  map). Expected: one Muse Spark parse call (about USD 0.0001, from earlier parse calls in the ledger), one geocode,
  then the plain refusal and exit code 2.
- Run once. Then run the same command again: the request is cached, so the second run makes no model call. The
  second run is the one to show in the demo video.
- If the geocoder puts the site within 30 km of Karimunjawa, or the run ends any other way, that is reported and
  nothing is changed to make it pass.

## 2. A new search with the judge panel (the new default)

- Command: `tools/source.py --only diesel_min_load_frac --out <scratch folder>` with no `--judge` flag, so the
  default panel is used: the local Muse Glimmer judge casts votes 1 and 2 and muse-wonder-1.0 casts vote 3.
- One input only, to keep the cost small: one Muse Spark web search (USD 0.02 to 0.09 per input in earlier
  searches, ledger) and at most one Wonder vote (USD 0.013 to 0.030 in the T17 re-judge, ledger).
- Run once, no retry. Whatever the result (checked, assumed, a judge error), it is reported with every vote. The
  output is not used by any study and does not replace any input.
- Pass for the smoke: the run finishes, G6 passes on its file, the meta says `judge_mode` panel, and the votes in
  the meta follow the panel order (local, local, then Wonder) for every candidate that reached the judge.

## Results (added after the runs, Thursday 29 Oct)

### 1. Refusal: as expected

First run, one Muse Spark parse call (`study-20261029T151022-f8ca34`, USD 0.000134, measured), exit code 2:

```
No study: site outside the Karimunjawa demand source area.
Pulau Bawean (Pulau Bawean, Dayasawah, Gresik, Jawa Timur, 61181, Indonesia) is 247 km from Karimunjawa; the demand model covers sites within 30 km (computed).
The hourly load comes from one published study of Karimunjawa. A new site needs its own hourly load.
```

The second run printed the same three lines with exit code 2 and added no row to the ledger (measured: one parse
row for both runs). With the same tool, the Karimunjawa question with the example study's sourcing file printed
`run b4a44fc6d4c32339 reused` in 0.0 s with no CAMS address set and no new ledger row (measured).

### 2. New search with the judge panel: pass

`sourcing-20261029T151048-c7fb3e`, 106 s, judge mode `panel`, G6 passed (1 of 1 sourced inputs checked).

- diesel_min_load_frac: checked, 0.3 frac (docs), quote found exactly, page 15 of a microgrid symposium PDF ("Design
  and Control of Energy Storage System for Stand-alone ..."), as written "30 % of the generator rating".
- Votes in the meta, in order: local yes (10.1 s), local yes (35.8 s), Wonder yes (4.5 s), each with its reason.
- Cost (ledger, measured): web search USD 0.036662, Wonder vote USD 0.009796, together USD 0.046.

This file is not used by any study and replaces no input.
