# AutoSolar Researcher

Work in progress, built during the Meta Global AI Developer Hackathon (kickoff Tuesday 27 October 2026, 00:00
Malaysia time).

One question about a diesel-powered island in Indonesia goes in. A checked solar and battery pre-feasibility study
comes out: weather from four sources, roof and land area from satellite images, hourly simulation, battery and
diesel dispatch, cost of energy, CO2, and a check of the published study for the same island. Every number is
traced to a source or a run file, and deterministic checks stand between every stage.

What was prepared before the event is listed in `PRE_EVENT.md`. Everything else in this repo was written during
the event.

## How it is built

- Meta Model API: Muse Spark (contributor mode) writes, searches and extracts; SAM 3.1 reads charts in published
  papers (it finds each data series and the axis labels, and Muse Spark reads the label text), so a figure can be
  checked against the paper's own tables. Roof and land area come from Google Open Buildings and ESA WorldCover.
- Meta open weights: Muse Glimmer runs locally as the independent checker, so no model reviews its own work.
- Muse Code writes most of the code from short specs. An orchestrator (Hermes) writes the specs and the acceptance
  tests, runs the tests and logs the measured token use and cost of every Muse Code run in
  `ledger/build_usage.jsonl`.

## Chart reader: how far it can be trusted

Tested twice with rules committed before each run (`docs/smoke/CHART_VALIDATION_RULES.md` and
`docs/smoke/CHART_VALIDATION_V3_RULES.md`). The first test failed: it missed the end points of each series, a
plain colour prompt found no hatched area, and a mask placement bug of ours broke wide images. All three were
fixed (the prompt now names the fill pattern). The second test passed on six new synthetic charts
and on a real paper figure it had never seen (Hiron et al. 2021, Figure 16 against the paper's Table 4). Away from
the ends of a series the read values were within 1.3% of the axis span (median 0.17%). The first and last point
of a series were less reliable, so every report marks them "edge, not validated".

## Acknowledgements

This project uses SAM Materials from Meta: the SAM 3.1 model through the Meta Model API and the `meta-sam-parser`
package (installed as a dependency, not copied here), both under the SAM License.

## Licence

Code: MIT. See `LICENSE`.
