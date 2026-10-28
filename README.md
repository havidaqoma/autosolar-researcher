# AutoSolar Researcher

Ask one question about an island that runs on diesel. Get back a checked solar plus battery pre-feasibility study:
weather from four sources, an hourly simulation of PV, battery and diesel for every design on a grid, the cost of
electricity, the fuel and CO2 saved, cited cost inputs, a check of the published study for the same island, a
second model's review, and a plain list of what the study does not cover.

Indonesia's state utility PLN plans to replace diesel generators at 741 sites with solar and batteries (press).
Each site needs a first study like this before anyone spends money on a detailed one.

Built during the Meta Global AI Developer Hackathon. What was prepared before the event is listed in
`PRE_EVENT.md`.

## See it

Open `docs/site/index.html` in a browser (no server, no script, no internet needed). The example study is
`docs/site/84f23f2cd0b0f857.html`. Its raw run files are under `docs/site/data/`.

## The Karimunjawa answer (study 84f23f2cd0b0f857, all numbers computed unless labelled)

| | |
|---|---|
| Answer | Yes. Solar plus battery cuts the cost of electricity from 0.354 to 0.251 USD/kWh (-29.1%). With the larger diesel units the source paper also prints, the cut is from 0.410 to 0.260 USD/kWh (-36.7%) |
| Least cost design | 7,250 kWp of PV and 19,000 kWh of battery, 85.8% renewable, 3,104,445 litres of diesel saved a year |
| Near tie | 8 designs are within 1% (assumed threshold) of the least cost, from 6,750 to 8,250 kWp |
| Diesel price where PV starts to pay | 0.27 USD/L |
| Reserve case | If one diesel unit must run in every hour, the least cost design shrinks to 1,500 kWp and 1,000 kWh at 0.336 USD/kWh, and the main design would cost 0.414 USD/kWh, more than diesel only |
| Diesel unit size | Hiron 2021 prints 2 x 1.8 MW (p7, used above) and 2 x 2.7 MW (p1 and Table 1) (paper). With 2.7 MW units the least cost design is 7,500 kWp and 19,000 kWh at 0.260 USD/kWh. If one 2.7 MW unit must run in every hour, the main design would cost 0.519 USD/kWh and the best design is 750 kWp with no battery at 0.400 USD/kWh, only 2.4% below diesel only |
| Land | The main design needs 8.3 ha of the 9 ha set aside (press), at 0.87 MWdc per ha (paper) |
| Published design size | 1,244 kWp of PV (paper), no battery: 0.336 USD/kWh |
| Model API cost behind the study | USD 0.43, almost all of it the web search that sourced the inputs |

What this means for PLN: solar pays at every size we tried. How big to build depends on one engineering question
the study cannot answer: can the island grid run on inverters alone for 7,302 hours a year (computed), or must a
diesel unit always spin? The first answer holds with either diesel unit size in the source paper. The second one
depends on it: if a unit must spin and the units are the larger ones, solar barely pays.

## How it works

| Stage | What runs | Meta tooling |
|---|---|---|
| S1 question | the question becomes a site and a study type | Muse Spark (contributor) |
| S2 weather | CAMS, NASA POWER, PVGIS-ERA5 and Global Solar Atlas; the spread between them becomes a range | |
| S3 inputs | web search with citations for 7 cost inputs; each quote must be found in the fetched source, the DOI must resolve, and a local judge must say the quote supports the value 3 times in a row | Muse Spark web search; Muse Glimmer (open weights, local) as judge |
| S4 to S6 | pvlib PV model, hourly dispatch with diesel minimum load, LCOE two ways, a grid of 925 designs, sensitivity and range tables | |
| S7 paper check | Muse Spark reads the whole PDF and returns its numbers as JSON constrained by a schema; scripts keep a number only if its quote is in the PDF text, then run 15 frozen checks | Muse Spark native PDF input and structured output |
| S8 report | Markdown, JSON and a static HTML page with charts; every number in the text must appear in the report data | |
| S9 review | a second model lists what it would question and where the report answers it | Muse Wonder |
| Build | Muse Code wrote the code from short specs; the orchestrator (Hermes) wrote the specs and acceptance tests | Muse Code (contributor) |

SAM 3.1 is wired in as a chart reader and passed its second validation (see below), but no study uses it yet.

## Checks

- Eleven gates on every study (G1 energy balance, G2 battery, G3 PV physics per weather source, G4 diesel minimum
  load, G5 weather spread, G6 sourced inputs match the inputs file, G7 grid edge, G8 two LCOE formulas agree).
- Citations: a value is "checked" only with a found quote, a resolving DOI when one is given, and 3 yes votes from
  the judge. Otherwise it keeps its assumed value and the report says why. 4 of 7 inputs are checked in the
  example; battery capex, battery O&M and the discount rate are still assumed.
- Paper check, in sample: on Hiron 2021 (Energies 14, 8311, the paper that gives the island's hourly load) the
  frozen checks cover 13 of the 14 items a hand audit could not reconcile. With the frozen prompt the tool found 11,
  8 and 11 of them in 3 runs (measured), with no extra flags, including a 990 kW PV plant that delivers 1,990 kW at
  11:00. The prompt was tuned on this paper, so this shows the tool can find what a careful reader finds.
- Paper check, out of sample: on a second paper with a published correction (Mathematics 11, 1248, original
  version) the tool flagged none of the 3 corrected numbers and raised no flag a person could confirm (measured,
  3 runs). So the claim that the checks find errors in papers they were not written for is NOT supported yet. The
  corrected items were in a figure and a paragraph about existing power plants, which no frozen check looks at.
- Second model review: Muse Wonder raised 10 points on the example study; 6 are not answered by the report
  (the demand data, a battery power set by an assumed 4 h duration, delivered island costs, the fuel price, diesel
  overhaul and replacement, reliability and ageing outputs). They are shown as open. An earlier review of the same
  answer, before the diesel unit size check, left 3 points open, one of them the unit size. Two reviews of nearly
  the same report differ, so read the list as a reader's questions, not as a score.

## What it does not cover

Grid stability and grid-forming inverters, land ownership and permits, site layout, shipping and construction,
financing and tariffs, demand growth beyond the growth case, battery ageing beyond the replacement rule, and diesel
price risk beyond the sensitivity table. The hourly load comes from the Hiron paper, which our own check flags; the
report says so.

## Run it

```
uv sync
uv run pytest                     # 1,065 tests, no network
AUTOSOLAR_ENV_FILE=path/to/.env AUTOSOLAR_CAMS_EMAIL=<address registered at soda-pro.com> \
  uv run python tools/ask.py "Is solar plus battery worth it for Karimunjawa? The island runs on diesel."
uv run python tools/paper_check.py <paper.pdf> --study runs/studies/<hash>
uv run python tools/review.py runs/studies/<hash> --paper runs/paper_checks/<id>
uv run python tools/make_site.py
```

The env file holds `MODEL_API_KEY` (Meta Model API). The demand model covers sites within 30 km of Karimunjawa;
other sites are refused rather than guessed.

## Cost (measured ledgers)

- `ledger/api_usage.jsonl`: every paid model call with tokens and computed USD. Total so far USD 2.31, including
  smoke tests, chart reader tests, three sourcing runs, 15 paper check runs and two reviews.
- `ledger/build_usage.jsonl`: 30 Muse Code runs that wrote the product, USD 0.43 and 1.8 hours in total.
- A live study costs USD 0.0001 to parse the question plus whatever new sourcing it needs; a paper check costs
  about USD 0.013 and a review USD 0.25 to 0.29.

## Chart reader: how far it can be trusted

Tested twice with rules committed before each run (`docs/smoke/CHART_VALIDATION_RULES.md` and
`docs/smoke/CHART_VALIDATION_V3_RULES.md`). The first test failed: it missed the end points of each series, a
plain colour prompt found no hatched area, and a mask placement bug of ours broke wide images. All three were
fixed (the prompt now names the fill pattern). The second test passed on six new synthetic charts and on a real
paper figure it had never seen (Hiron et al. 2021, Figure 16 against the paper's Table 4). Away from the ends of a
series the read values were within 1.3% of the axis span (median 0.17%). The first and last point of a series were
less reliable, so every report marks them "edge, not validated".

## How it was built

Every task has a spec in `docs/specs/` and acceptance tests written before the code. Before Muse Code ran, the
orchestrator checked each test file against its own reference and against planted faults (each spec ends with
"Test check by the orchestrator"). The log of what was decided and why is `docs/implementation-notes.md`.

## Acknowledgements

This project uses SAM Materials from Meta: the SAM 3.1 model through the Meta Model API and the `meta-sam-parser`
package (installed as a dependency, not copied here), both under the SAM License. The example page quotes short
passages of Hiron et al. 2021 (Energies, CC BY 4.0) in its paper check.

## Licence

Code: MIT. See `LICENSE`.
