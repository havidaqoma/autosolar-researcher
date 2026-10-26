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

- Meta Model API: Muse Spark (contributor mode) writes, searches and extracts; SAM 3.1 segments satellite images.
- Meta open weights: Muse Glimmer runs locally as the independent checker, so no model reviews its own work.
- Muse Code writes most of the code from short specs. An orchestrator (Hermes) writes the specs and the acceptance
  tests, runs the tests and logs the measured token use and cost of every Muse Code run in
  `ledger/build_usage.jsonl`.

## Licence

Code: MIT. See `LICENSE`.
