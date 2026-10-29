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

## Results

(Added after the runs.)
