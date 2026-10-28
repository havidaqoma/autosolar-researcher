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
`docs/site/5ee65dcd3350bec1.html`; the run with curated inputs (post hoc) is `docs/site/4a0c0eedd47b2672.html`, with
the latest Muse Wonder review. Both were re-judged by two models (see Checks) and give the same numbers as the
earlier runs f86df9819fa150a7 and 579f414386fe2d58, which stay in the gallery. Raw run files are under
`docs/site/data/`.

## The Karimunjawa answer (study 5ee65dcd3350bec1, same numbers as f86df9819fa150a7; computed unless labelled)

| | |
|---|---|
| Answer | Yes. Solar plus battery cuts the cost of electricity from 0.354 to 0.251 USD/kWh (-29.1%). With the larger diesel units the source paper also prints, the cut is from 0.410 to 0.260 USD/kWh (-36.7%) |
| Least cost design | 7,250 kWp of PV and 19,000 kWh of battery, 85.8% renewable, 3,104,445 litres of diesel saved a year |
| Near tie | 8 designs are within 1% (assumed threshold) of the least cost, from 6,750 to 8,250 kWp |
| Diesel price where PV starts to pay | 0.27 USD/L |
| Reserve case | If one diesel unit must run in every hour, the least cost design shrinks to 1,500 kWp and 1,000 kWh at 0.336 USD/kWh, and the main design would cost 0.414 USD/kWh, more than diesel only |
| Diesel unit size | Hiron 2021 prints 2 x 1.8 MW (p7, used above) and 2 x 2.7 MW (p1 and Table 1) (paper). With 2.7 MW units the least cost design is 7,500 kWp and 19,000 kWh at 0.260 USD/kWh. If one 2.7 MW unit must run in every hour, the main design would cost 0.519 USD/kWh and the best design is 750 kWp with no battery at 0.400 USD/kWh, only 2.4% below diesel only |
| Battery power | The battery's power rating (4,750 kW) comes from an assumed 4 h duration. The main design uses up to 96% of it, for charging (4,555 kW); discharge never needs more than the 1,422 kW peak load. With an 8 h battery (assumed, so half the power rating) the least cost design is 7,500 kWp and 19,000 kWh at 0.255 USD/kWh, 1.4% more |
| Island prices | PV and battery capital prices could rise 189% together (to 3,239 USD/kWp and 868 USD/kWh) before diesel only is cheaper. Shipping and labour, which the study leaves out, would have to nearly triple them to change the answer |
| Reliability and wear | The least cost design leaves 0 kWh of load not served in the simulated year and cycles the battery 249 times a year. Diesel engine hours fall from 8,760 to 1,458 unit hours a year (-83.4%), so the overhaul costs left out would favour solar |
| Land | The main design needs 8.3 ha of the 9 ha set aside (press), at 0.87 MWdc per ha (paper) |
| Published design size | 1,244 kWp of PV (paper), no battery: 0.336 USD/kWh |
| Model API cost behind the study | USD 0.43, almost all of it the web search that sourced the inputs, plus USD 0.085 for the two-model re-judge (measured, ledger) |

What this means for PLN: solar pays at every size we tried. How big to build depends on one engineering question
the study cannot answer: can the island grid run on inverters alone for 7,302 hours a year (computed), or must a
diesel unit always spin? The first answer holds with either diesel unit size in the source paper. The second one
depends on it: if a unit must spin and the units are the larger ones, solar barely pays.

## Second run with curated inputs (post hoc, study 4a0c0eedd47b2672, same numbers as 579f414386fe2d58)

The study above kept 3 of its 7 sourced inputs at assumed values (battery capex, battery O&M, discount rate), and
3 more battery inputs were never sourced (power capex, life, efficiency). Its diesel price passed the checks, but
it comes from a palm oil article that gives one rupiah price, converted at an assumed exchange rate. After
pre-registration the build agent (Hermes) replaced these 7 values by hand, the checked diesel price included,
with values from named documents (`config/curated_inputs.json`, applied by `tools/curate.py`). Each one is marked
"curated post hoc" in the report and on the page. The first study stays as it is.

| Input | First study | Curated | Source of the curated value |
|---|---|---|---|
| Battery energy capex | 300 USD/kWh (assumed) | 390 USD/kWh (docs) | Danish Energy Agency and EA Energy Analyses, Technology Data for the Indonesian Power Sector 2024, lithium-ion data sheet, 2023 column |
| Battery power capex | 100 USD/kW (assumed) | 330 USD/kW (docs) | same data sheet |
| Battery O&M | 5 USD/kWh/yr (assumed) | 4.48 USD/kWh/yr (docs) | same data sheet, fixed plus variable at one cycle a day |
| Battery life | 12 yr (assumed) | 15 yr (docs) | same data sheet |
| Battery round trip efficiency | 0.9 (assumed) | 0.9 (docs) | same data sheet, AC |
| Discount rate, real | 0.08 (assumed) | 0.0673 (docs) | IEA: median cost of capital for solar PV in Indonesia 9.4% nominal, with the Bank Indonesia 2.5% inflation target |
| Diesel price | 0.848 USD/L (docs, checked) | 1.26 USD/L (docs) | median of 17 Pertamina Patra Niaga industrial price lists (B40, Java), before tax and before shipping to the island |

| | First study | Curated |
|---|---|---|
| Diesel only | 0.354 USD/kWh | 0.511 USD/kWh |
| Least cost design | 7,250 kWp and 19,000 kWh at 0.251 USD/kWh | 8,500 kWp and 19,000 kWh at 0.277 USD/kWh |
| Cut against diesel only | -29.1% | -45.7% |
| Renewable share | 85.8% | 89.6% |
| Diesel price where PV starts to pay | 0.27 USD/L | 0.24 USD/L |
| Capital prices could rise before diesel only is cheaper | 189% | 365% |
| One diesel unit must always run | best 0.336 USD/kWh, 5.1% below diesel only | best 0.461 USD/kWh (4,250 kWp, 11,000 kWh), 9.9% below diesel only |
| Land at 0.87 MWdc per ha (paper) | 8.3 ha, fits the 9 ha | 9.8 ha, does not fit; the largest design that fits (7,750 kWp) costs 0.279 USD/kWh |

The answer gets stronger, not weaker: the higher fuel price raises diesel only far more than the dearer battery
raises the solar design. At the high discount rate in the sensitivity table (0.081, 1.2 times) the least cost design
costs 0.297 USD/kWh, still far below diesel only. Three limits of the curated values: the fuel price is a depot
price before tax and sea transport, so the island price is higher (this would favour solar further); the battery
prices are at the catalogue's price level of 2022 and battery prices have fallen since (also favouring solar); and
the discount rate is a solar PV rate applied to the battery as well (the IEA says battery finance costs more). The
catalogue's own land density for Indonesia (9.1 thousand m2 per MWp, docs) would fit the main design in 7.7 ha; we
kept the US median because changing a check value after seeing the answer would loosen the check. With the larger
2.7 MW diesel units the least cost design sits on the edge of the design grid (9,000 kWp), so the best size there
may be larger. Copies of the source pages, a second read of the table images by OCR and a script that recomputes
each value are kept with the build files.

## How it works

| Stage | What runs | Meta tooling |
|---|---|---|
| S1 question | the question becomes a site and a study type | Muse Spark (contributor) |
| S2 weather | CAMS, NASA POWER, PVGIS-ERA5 and Global Solar Atlas; the spread between them becomes a range | |
| S3 inputs | web search with citations for 7 cost inputs; each quote must be found in the fetched source, the DOI must resolve, and the judges must say the quote supports the value 3 times in a row | Muse Spark web search; Muse Glimmer (open weights, local) votes 1 and 2, Muse Wonder vote 3 |
| S4 to S6 | pvlib PV model, hourly dispatch with diesel minimum load, LCOE two ways, a grid of 925 designs, sensitivity and range tables | |
| S7 paper check | Muse Spark reads the whole PDF and returns its numbers as JSON constrained by a schema; scripts keep a number only if its quote is in the PDF text, then run 15 frozen checks | Muse Spark native PDF input and structured output |
| S8 report | Markdown, JSON and a static HTML page with charts; every number in the text must appear in the report data | |
| S9 review | a second model lists what it would question and where the report answers it | Muse Wonder |
| Build | Muse Code wrote the code from short specs; the orchestrator (Hermes) wrote the specs and acceptance tests | Muse Code (contributor) |

SAM 3.1 is wired in as a chart reader and passed its second validation (see below), but no study uses it yet.

## Checks

- Eleven gates on every study (G1 energy balance, G2 battery, G3 PV physics per weather source, G4 diesel minimum
  load, G5 weather spread, G6 sourced inputs match the inputs file, G7 grid edge, G8 two LCOE formulas agree).
- Citations: a value is "checked" only with a found quote, a resolving DOI when one is given, and 3 yes votes.
  Otherwise it keeps its assumed value and the report says why. 4 of 7 inputs are checked in the example; battery
  capex, battery O&M and the discount rate are still assumed. The post hoc run above replaces 7 inputs by hand from
  named documents; G6 checks every curated row against its entry.
- Two judge models: three votes from one model can share one blind spot, and Muse Spark found the quotes, so it
  must not judge them. So the 4 checked values were judged again: Muse Glimmer (local) gives votes 1 and 2, Muse
  Wonder gives vote 3, and any no or error sends the value back to its assumed value. The rule was committed before
  the run (`docs/specs/T17_judge_panel.md`). Wonder said yes to all 4 (measured, 4 calls, USD 0.085), so nothing
  changed. New searches (`tools/source.py`) still use the local judge for all 3 votes; the two-model check is
  `tools/rejudge.py --panel`.
- Paper check, in sample: on Hiron 2021 (Energies 14, 8311, the paper that gives the island's hourly load) the
  frozen checks cover 13 of the 14 items a hand audit could not reconcile. With the frozen prompt the tool found 11,
  8 and 11 of them in 3 runs (measured), with no extra flags, including a 990 kW PV plant that delivers 1,990 kW at
  11:00. The prompt was tuned on this paper, so this shows the tool can find what a careful reader finds.
- Paper check, out of sample: on a second paper with a published correction (Mathematics 11, 1248, original
  version) the tool flagged none of the 3 corrected numbers and raised no flag a person could confirm (measured,
  3 runs). So the claim that the checks find errors in papers they were not written for is NOT supported yet. The
  corrected items were in a figure and a paragraph about existing power plants, which no frozen check looks at.
- Second model review, curated run: Muse Wonder raised 10 points; 3 are not answered by the report: the diesel
  fuel curve and diesel O&M are assumed and not in the sensitivity table; the Hiron load data are used although our
  own check flags that paper; and reliability is an hourly energy balance only (no forced outages, loss of the
  largest unit, start costs or sub-hourly ramps). Every number the review quotes was found in the study files
  (computed check, 48 of 48). The other 7 points name sections where the report answers them.
- Second model review, example study (earlier): Muse Wonder raised 10 points; 2 are not answered by the report (a
  bankable yield and reliability case behind the 0 kWh not served, and an expansion path for demand growth). They
  are shown as open. The review before the last build left 6 open; the last build answered four of them with new
  checks (battery power, island prices, load not served and battery cycles, diesel engine hours), scored by a rule
  written before the review ran (`docs/specs/T15_more_checks.md`). Read honestly, only battery power dropped off the
  list: the reviewer now points island costs and diesel overhaul to the list of what is not covered, and still asks
  about ageing. Two reviews of nearly the same report differ, so read the list as a reader's questions, not as a
  score.

## What it does not cover

Grid stability and grid-forming inverters, land ownership and permits, site layout, shipping and construction,
financing and tariffs, demand growth beyond the growth case, battery ageing beyond the replacement rule, diesel
price risk beyond the sensitivity table, diesel overhaul and engine replacement, and reliability beyond the hourly
energy balance (forced outages, loss of the largest unit, sub-hourly ramps). Left out against diesel:
sea transport and taxes on fuel, and the lower heating value of B40 biodiesel. Left out against solar: PV
degradation (0.25 to 0.5% a year in the Indonesian catalogue, docs). The hourly load comes from the Hiron paper, which our own check flags; the
report says so.

## Run it

```
uv sync
uv run pytest                     # 1,316 tests, no network
AUTOSOLAR_ENV_FILE=path/to/.env AUTOSOLAR_CAMS_EMAIL=<address registered at soda-pro.com> \
  uv run python tools/ask.py "Is solar plus battery worth it for Karimunjawa? The island runs on diesel."
uv run python tools/paper_check.py <paper.pdf> --study runs/studies/<hash>
uv run python tools/review.py runs/studies/<hash> --paper runs/paper_checks/<id>
uv run python tools/make_site.py
```

The env file holds `MODEL_API_KEY` (Meta Model API). The demand model covers sites within 30 km of Karimunjawa;
other sites are refused rather than guessed.

## Cost (measured ledgers)

- `ledger/api_usage.jsonl`: every paid model call with tokens and computed USD. Total so far USD 2.94, including
  smoke tests, chart reader tests, three sourcing runs, 15 paper check runs, four reviews and the two-model
  re-judge.
- `ledger/build_usage.jsonl`: 37 Muse Code runs (33 that wrote the product, 4 sandbox smoke runs), USD 0.50 and
  2.4 hours in total.
- A live study costs USD 0.0001 to parse the question plus whatever new sourcing it needs; a paper check costs
  about USD 0.013 and a review USD 0.25 to 0.33.

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
