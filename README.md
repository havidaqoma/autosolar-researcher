# AutoSolar Researcher

Ask one question about an island that runs on diesel. Get back a checked solar plus battery pre-feasibility study:
weather from four sources, an hourly simulation of PV, battery and diesel for every design on a grid, the cost of
electricity, the fuel and CO2 saved, cited cost inputs, a check of the published study for the same island, a
second model's review, and a plain list of what the study does not cover.

Indonesia's state utility PLN plans to replace diesel generators at 741 sites with solar and batteries (press,
[Bloomberg Technoz](https://www.bloombergtechnoz.com/detail-news/105965/pln-bakal-ganti-2-396-pltd-dengan-plts-3-21-gwp-bess-9-03-gwh)).
Each site needs a first study like this before anyone spends money on a detailed one. It is a first screen, not
a replacement for a detailed design in PVsyst or HOMER: each latest study page says which inputs to confirm first
and gives the hourly files to re-run the answer in such a tool.

Built during the Meta Global AI Developer Hackathon. What was prepared before the event is listed in
`PRE_EVENT.md`.

What it cost (measured ledgers): Muse Code wrote the engine, all 11,359 lines of `autosolar/` (22 files, `wc -l`),
for USD 0.71. It did not write the specs or the tests: each task's spec and acceptance tests were written first,
and Muse Code wrote code until they passed (the git history shows the order). One full study, with a fresh web
search for its prices, costs about USD 0.50 in Meta model calls. All Meta model spending for the whole hackathon,
smoke tests, chart reader tests and reviews included: USD 4.03.

## For judges

- Scope: one island today. The tool answers for Karimunjawa; the demand model covers sites within 30 km of it and
  refuses other sites rather than guess. A new site needs its own hourly load. Asked about Bawean, another diesel
  island in the Java Sea, it answers "No study" and says the site is 247 km away (computed,
  `docs/smoke/T19_SMOKE_RULES.md`).
- Try it on the page: each study page has "Try another diesel price". Click a price from 0.20 to 1.60 USD/L
  and the page shows the least cost design at that price, re-costed over all 925 designs (computed; plain HTML
  and CSS, no script). It is an exact re-cost within the model, not a guess between points: a design's fuel
  use does not depend on the price, and at 20% below and above the study price it gives the same numbers as
  the sensitivity table.
- Confirm these first (latest study pages): the 9 inputs ranked by how far each moves the cost of the main design,
  each with the field data to ask for (in the example the discount rate comes first). Next to them, public field
  figures from the press, each with its quote: in 2017, less than a year after 24 hour power began (May 2016, same
  article), the island's plant made
  8,000 kWh a day on 4,000 L of diesel (press, Kompas). The study's load is 3.28 times that, and its diesel uses
  0.382 L/kWh against 0.50 in the press (computed). The study does not use these figures; a load that much lower is
  outside what it tested (the lowest case is 23.3% lower), so the metered load is the first thing to get. Then
  two hourly files to check us in your own tool: `hourly.csv` (8,760 hours of weather, load, PV and the main
  design's energy flow) and the load as one column for HOMER. Before writing them, the tool must give back the
  study's yearly numbers (it did, to within one part in a billion, computed; `docs/specs/T22_confirm_first.md`).
- Which renewable fits this site (post hoc, `docs/specs/T23_resource_screen.md`): sun 4.05 kWh/kWp a day (Global
  Solar Atlas), the World Bank's favorable middle range; wind 4.44 m/s and 91 W/m2 at 50 m (NASA POWER, hourly 2016
  to 2024, computed), class 1 (Poor) on the NREL scale, though a coarse grid can miss local wind; 1 river and 2
  streams mapped within 10 km (OpenStreetMap); the nearest town on the map is 78 km away. Only solar, battery and
  diesel are costed. The same section checks our PV model on outside weather: +1.4% against PVGIS and -3.3%
  against Global Solar Atlas (Solargis), computed. No Meta model call (the API ledger stayed at 179 lines,
  measured).
- When the checks say no (example study page, Inputs table): the judge refused a battery price of USD 192/kWh,
  because the quote gives a system level storage cost, not the installed price of a lithium-ion battery; the
  range check threw out a battery upkeep cost of 50 USD/kWh/yr before any vote, as outside the allowed 0.5 to
  30; when a site blocked the download (HTTP 403), the tool searched a second time. A value that fails keeps its assumed value and the page
  says why: 3 of the 7 sourced inputs stayed assumed (these two, and the discount rate, where both downloads
  failed).
- If the load chart is right (post hoc): the load check finds the study's load 30.4% above the paper's
  December 2018 curve (18.2% above the mean of the three days it plots). At the load that curve implies (23.3%
  lower, computed), solar plus battery still wins: 5,750 kWp and 15,000 kWh at 0.257 USD/kWh against 0.388 for
  diesel only, 33.7% less (computed). Before it reports, the tool must give back the study's own numbers; the
  rules for this re-run were committed before it ran (`docs/smoke/T20_T21_SMOKE_RULES.md`).
- Built during the event: all code in `autosolar/`, `tools/` and `tests/`, every spec in `docs/specs/`, every study
  and the static site. `PRE_EVENT.md` lists what was prepared before kickoff (plan, paper audit, weather cross check,
  Glimmer speed test), with commit times.
- Without cloning: the six pictures below are from the example study. With a clone, open `docs/site/index.html`.

![Answer section of the example study](docs/img/answer.png)

![Every design we costed and what moves the cost](docs/img/designs.png)

![SAM 3.1 reads the paper's load chart: a second read of the load](docs/img/load_check.png)

![Try another diesel price: the page at 0.60 USD/L after one click](docs/img/fuel_price.png)

![Confirm these first: inputs ranked by how far they move the cost, with the field data to ask for](docs/img/confirm.png)

![Which renewable fits this site, and our PV model against two outside models](docs/img/resources.png)

- Meta tools, when each runs and how its output is checked:

| Tool | Job | When it runs | How its output is checked |
|---|---|---|---|
| Muse Spark (Meta Model API) | Turns the question into a site; searches the web for cost inputs and cites them; reads the whole source paper as a PDF and returns its numbers as JSON bound by a schema | Every study | A quote must be found in the fetched page or PDF text, a DOI must resolve, then 15 frozen paper checks run on the numbers |
| Muse Glimmer (open weights, 30B, on our own 16 GB GPU with llama.cpp) | Judge: does the quote support the value? | Every new search and every re-check: votes 1 and 2 | A value is "checked" only with 3 yes votes; otherwise it stays assumed and the report says why |
| Muse Wonder (Meta Model API) | Judge vote 3, and a second model review of the finished report | Vote 3 in every new search (`tools/source.py`, the default since T19) and in the re-check (`tools/rejudge.py --panel`), only after Glimmer said yes twice; the review runs after a study. Every checked input in the example study b4a44fc6d4c32339 passed this panel; the curated run starts from the same file | Every number the review quotes is looked up in the study files (64 of 65 in the last review; the other is the reviewer's own product of two of them, and it is right, computed) |
| SAM 3.1 (Meta Model API) | Reads values off chart images: here, Figure 7 of the source paper (three measured days of load), as a second read of the load the study uses | Once per figure (4 SAM calls and 1 Muse Spark label call, USD 0.01, measured); the latest study pages show the result | Rules fixed before each run. The reader test failed first, then passed (see "Chart reader"). The load check found the study's load 30.4% above the paper's own December 2018 curve (computed) |
| Muse Code (contributor model) | Wrote the engine (`autosolar/`) from short specs. It did not write the specs or the tests; of the run tools in `tools/` it wrote three and edited one (T20 to T23) | Build time | Each spec and its acceptance tests are written before the code, and the tests are checked to catch planted faults (last two tasks: 23 of 24 and 22 of 23; for each, one test was added after the code, then all caught; computed) |

- Checks: 1,686 unit tests with no network, and a fresh clone passes all of them (measured, `docs/smoke/CLONE_TEST.md`).
  Eleven gates run on every study (G3 runs once for each of the 4 weather sources). What the study cannot source stays
  "assumed", and the page says so.
- Cost: Muse Code USD 0.71 (46 runs, 4.9 hours; it read 63 million tokens, 93% from cache, and wrote 0.79
  million). Meta Model API USD 3.32 (179 calls, 451 web searches). USD 4.03 in all (measured ledgers).
- Limits: see "What it does not cover" and the open review points under "Checks".

## See it

Open `docs/site/index.html` in a browser (no server, no script, no internet needed). The example study is
`docs/site/b4a44fc6d4c32339.html`; the run with curated inputs (post hoc) is `docs/site/107477f112e5d92c.html`, with
the latest Muse Wonder review. Both start from the input file whose 4 checked values were re-judged by two models
(see Checks; the curated run then replaces 7 values by hand, the diesel price among them). They come from the latest
build. Every number matches the earlier runs 5ee65dcd3350bec1 and 4a0c0eedd47b2672 (and f86df9819fa150a7 and
579f414386fe2d58 before them), except that "What moves the cost" now has 9 inputs and the curated diesel unit size
check no longer sits on the grid edge (computed, a script compared every fact, gate and table row). The earlier runs
stay in the gallery. Raw run files are under `docs/site/data/`.

## The Karimunjawa answer (study b4a44fc6d4c32339, same numbers as 5ee65dcd3350bec1; computed unless labelled)

"Computed" says where a number comes from: the code calculated it from the inputs. It is only as good as those
inputs, and many of them are assumed, among them all battery prices, the discount rate and the diesel fuel curve.
The "Inputs" table on each page labels every one, and "What moves the cost" shows how much 9 of them matter.

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
| What moves the cost | 9 inputs, each moved 20% down and up. The discount rate, PV price and battery price move the chosen design's cost most (0.233 to 0.269 USD/kWh). The diesel fuel curve and diesel O&M, which are assumed, move it less than the diesel price does (0.245 to 0.257 against 0.241 to 0.261 USD/kWh) |
| Load check (SAM 3.1) | The study's hourly load (Hiron Table 6) is 30.4% above the paper's own December 2018 curve, once scaled back by the paper's 3.48% a year, and 18.2% above the mean of the three days the paper plots. That is outside the +/-20% demand swing. At 0.8 times the demand, the nearest case in the table, the chosen design costs 0.278 USD/kWh and the least cost design is 6,000 kWp and 15,000 kWh at 0.256 USD/kWh. At the load the chart implies (post hoc) the least cost design is 5,750 kWp and 15,000 kWh at 0.257 USD/kWh against 0.388 for diesel only |
| Other diesel prices | On the page, at 0.60 USD/L the least cost design is 4,000 kWp and 7,000 kWh, 13.0% below diesel only; at 1.20 USD/L it is 8,250 kWp and 19,000 kWh, 44.9% below |
| Published design size | 1,244 kWp of PV (paper), no battery: 0.336 USD/kWh |
| Model API cost behind the study | USD 0.43, almost all of it the web search that sourced the inputs, plus USD 0.085 for the two-model re-judge (measured, ledger) |

What this means for PLN: solar plus battery pays if the batteries and inverters can carry the grid on their own.
That is one engineering question the study cannot answer: can the island grid run on inverters alone for 7,302
hours a year (computed), or must a diesel unit always spin? If one must, the main design costs more than diesel
only (0.414 against 0.354 USD/kWh), the best design shrinks to 1,500 kWp, and with the larger diesel units it is
only 2.4% below diesel only. The load check adds a second caution: if the island uses less power than Table 6
says, the right design is smaller (5,750 kWp and 15,000 kWh at the load the chart implies), but it still costs
a third less than diesel only (post hoc, computed).

## Second run with curated inputs (post hoc, study 107477f112e5d92c, same numbers as 4a0c0eedd47b2672)

The study above kept 3 of its 7 sourced inputs at assumed values (battery capex, battery O&M, discount rate), and
3 more battery inputs were never sourced (power capex, life, efficiency). Its diesel price passed the checks, but
it comes from a palm oil article that gives one rupiah price, converted at an assumed exchange rate. After
pre-registration these 7 values were replaced by hand, the checked diesel price included,
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

The cut against diesel only grows (45.7% against 29.1%) because the higher fuel price raises diesel only far more
than the dearer battery raises the solar design. Not all of it is better news: the least cost design no longer
fits the land (row above), and if one diesel unit must always run, the main design costs 0.533 USD/kWh, more than
diesel only (0.511). At the high discount rate in the sensitivity table (0.081, 1.2 times) the least cost design
costs 0.297 USD/kWh, still far below diesel only. Three limits of the curated values: the fuel price is a depot
price before tax and sea transport, so the island price is higher (this would favour solar further); the battery
prices are at the catalogue's price level of 2022 and battery prices have fallen since (also favouring solar); and
the discount rate is a solar PV rate applied to the battery as well (the IEA says battery finance costs more). The
catalogue's own land density for Indonesia (9.1 thousand m2 per MWp, docs) would fit the main design in 7.7 ha; we
kept the US median because changing a check value after seeing the answer would loosen the check. With the larger
2.7 MW diesel units the least cost design is 9,000 kWp and 19,000 kWh at 0.287 USD/kWh. That check now widens its
grid like the main search does, and 9,000 kWp is no longer on the edge (computed). Four cases in "What moves the
cost" (PV price down, diesel price up, demand up, fuel per kWh up) still pick 9,000 kWp at the edge of their grid;
the page marks each one. Copies of the source pages, a second read of the table images by OCR and a script that recomputes
each value are kept with the build files.

## How it works

| Stage | What runs | Meta tooling |
|---|---|---|
| S1 question | the question becomes a site and a study type | Muse Spark (contributor) |
| S2 weather | CAMS, NASA POWER, PVGIS-ERA5 and Global Solar Atlas; the spread between them becomes a range | |
| S3 inputs | web search with citations for 7 cost inputs; each quote must be found in the fetched source, the DOI must resolve, and the judges must say the quote supports the value 3 times in a row | Muse Spark web search; Muse Glimmer (open weights, local) votes 1 and 2, Muse Wonder vote 3 |
| S4 to S6 | pvlib PV model, hourly dispatch with diesel minimum load, LCOE two ways, a grid of 925 designs, sensitivity and range tables | |
| S7 paper check | Muse Spark reads the whole PDF and returns its numbers as JSON constrained by a schema; scripts keep a number only if its quote is in the PDF text, then run 15 frozen checks | Muse Spark native PDF input and structured output |
| S7b load check | SAM 3.1 finds each load curve in a chart of the same paper, Muse Spark reads the axis labels, and a script compares the read curves with the load the study uses | SAM 3.1, Muse Spark |
| S8 report | Markdown, JSON and a static HTML page with charts; every number in the text must appear in the report data | |
| S9 review | a second model lists what it would question and where the report answers it | Muse Wonder |
| S10 confirm and screen | inputs ranked by how far they move the cost, public field figures with quotes, hourly files that must give back the study's numbers, and a screen of sun, wind, rivers and distance from free public data (post hoc) | |
| Build | Muse Code wrote the code from short specs, with acceptance tests written before the code | Muse Code (contributor) |

## Checks

- Eleven gate checks on every study: 8 gates, with G3 run once for each of the 4 weather sources (G1 energy
  balance, G2 battery, G3 PV physics, G4 diesel minimum load, G5 weather spread, G6 sourced inputs match the inputs file, G7 grid edge, G8 two LCOE formulas agree).
- Citations: a value is "checked" only with a found quote, a resolving DOI when one is given, and 3 yes votes.
  Otherwise it keeps its assumed value and the report says why. 4 of 7 inputs are checked in the example; battery
  capex, battery O&M and the discount rate are still assumed. The post hoc run above replaces 7 inputs by hand from
  named documents; G6 checks every curated row against its entry.
- Two judge models: three votes from one model can share one blind spot, and Muse Spark found the quotes, so it
  must not judge them. So the 4 checked values were judged again: Muse Glimmer (local) gives votes 1 and 2, Muse
  Wonder gives vote 3, and any no or error sends the value back to its assumed value. The rule was committed before
  the run (`docs/specs/T17_judge_panel.md`). Wonder said yes to all 4 (measured, 4 calls, USD 0.085), so nothing
  changed. Since T19 a new search (`tools/source.py`) uses the same panel by default; `--judge local` keeps the
  old rule for repeating earlier runs. One smoke search with the default (one input, USD 0.046, measured) checked
  the diesel minimum load at 30% with the votes local yes, local yes, Wonder yes (`docs/smoke/T19_SMOKE_RULES.md`).
- Paper check, in sample: on Hiron 2021 (Energies 14, 8311, the paper that gives the island's hourly load) the
  frozen checks cover 13 of the 14 items a hand audit could not reconcile. With the frozen prompt the tool found 11,
  8 and 11 of them in 3 runs (measured), with no extra flags, including a 990 kW PV plant that delivers 1,990 kW at
  11:00. The prompt was tuned on this paper, so this shows only that the tool can be set up to find what a careful
  reader found. It is not evidence that it works on other papers; the next point tests that.
- Paper check, out of sample: on a second paper with a published correction (Mathematics 11, 1248, original
  version) the tool flagged none of the 3 corrected numbers and raised no flag a person could confirm (measured,
  3 runs). So the claim that the checks find errors in papers they were not written for is NOT supported yet. The
  corrected items were in a figure and a paragraph about existing power plants, which no frozen check looks at.
- Load check (SAM 3.1, rules fixed before the run in `docs/smoke/FIGURE_CHECK_RULES.md`): the paper says its 2022
  load is the December 2018 curve grown by 3.48% a year. SAM 3.1 read the three 2018 days of its Figure 7 (22 of 24
  hours read and validated, 4 SAM calls, USD 0.01, measured). Table 6 scaled back is 30.4% above the 31 Dec 2018
  curve, 16.7% above 27 Oct and 9.4% above 28 Sep (computed). The reader's error in its test was at most 1.32% of
  the axis span (measured), so read these as about 30%, 17% and 9%. For Table 6 to come from the December curve the
  growth would have to be about 10.6% a year. So the load the study uses may be too high, by more than the demand
  swing it tests. The study still uses Table 6: changing an input after seeing the answer would be shopping for
  numbers. The study page shows the check in its own section instead, on the same page as the answer.
- If the chart is right (post hoc, `docs/specs/T20_load_followup.md`): after the load check result, the engine
  re-ran all 925 designs at two loads read from the chart and at the two demand rows of the sensitivity table.
  Before it reports, it must give back the study's own answer and those two rows (it did, to within one part in
  a billion). Example study: at the 31 Dec 2018 curve (23.3% lower) the least cost design is 5,750 kWp and
  15,000 kWh at 0.257 USD/kWh, 33.7% below diesel only; at the mean of the three days (15.4% lower, computed),
  6,250 kWp and 16,000 kWh at 0.254 USD/kWh, 32.0% below (computed). Curated run (page 107477f112e5d92c):
  49.4% and 48.0% below (computed). Diesel only wins in none of the four load cases. The study's headline is
  not changed; the result is shown in the load check section, marked post hoc. The re-run made no model call
  (the ledger did not grow, measured).
- A published comparison: Syah et al. (IEEE IES, doi 10.1109/IES67184.2025.11160749) report a lowest cost of
  0.263 USD/kWh for Karimunjawa with PV, wind, battery and diesel (paper, abstract only; we did not read the
  full text). It adds wind and uses its own inputs, so it is a comparison, not a check; our 0.251 USD/kWh
  (computed) is in the same range. Our resource screen puts the wind at 50 m in class 1 from a coarse grid; we
  cannot see the paper's wind data.
- Second model review, curated run, latest build (review-20261029T060800-acbbb2): Muse Wonder raised 10 points; 2
  are not answered by the report: why the 8 h battery case costs the same although half the battery power is
  cheaper, and reliability beyond the hourly energy balance (no forced outages, loss of the largest unit or
  sub-hourly ramps). The earlier review's point that the diesel fuel curve and O&M are not in the sensitivity table
  is gone now that both are. 64 of the 65 numbers the review quotes are in the study files; the other, 783,750 USD,
  is the reviewer's own product of two of them (2,375 kW x 330 USD/kW), and it is right (computed).
- Second model review, curated run, earlier build: 10 points, 3 open (the fuel curve and O&M, the flagged Hiron
  load data, reliability).
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
degradation (0.25 to 0.5% a year in the Indonesian catalogue, docs). The hourly load comes from the Hiron paper,
which our own check flags, and the SAM 3.1 load check finds it 30.4% above the paper's own December 2018 curve; the
page says so. Wind, hydro and a grid link are screened, not costed. The public field figures are from the press
(2017 and 2025), not from the operator's records.

## Next

- Many sites at once: run the resource screen and the study over a list of diesel sites and show them on one map.
  Prior art does the map part already: the World Bank ESMAP Global Electrification Platform, built on the open
  OnSSET tool from KTH (https://www.onsset.org/), maps the least cost way to supply each settlement. This tool would
  add a checked, cited, hourly study per site, not replace that map.
- Wind and hydro in the cost model, for sites where the screen says they are worth a closer look.
- Field data in place of the paper load: the metered hourly load and the plant's fuel logs from the operator.

## Run it

```
uv sync
uv run pytest                     # 1,686 tests, no network
AUTOSOLAR_ENV_FILE=path/to/.env AUTOSOLAR_CAMS_EMAIL=<address registered at soda-pro.com> \
  uv run python tools/ask.py "Is solar plus battery worth it for Karimunjawa? The island runs on diesel."
uv run python tools/paper_check.py <paper.pdf> --study runs/studies/<hash>
uv run python tools/review.py runs/studies/<hash> --paper runs/paper_checks/<id>
uv run python tools/figure_check.py config/figure_checks/hiron2021_fig7.json
uv run python tools/load_followup.py --run <hash> --figure-check <id>
uv run python tools/engineer_files.py --run <hash>     # hourly.csv and the HOMER load file, after a self check
uv run python tools/resource_screen.py --run <hash>   # sun, wind, rivers, distance; PV model check
uv run python tools/make_site.py
```

The env file holds `MODEL_API_KEY` (Meta Model API). The demand model covers sites within 30 km of Karimunjawa;
other sites are refused rather than guessed.

## Cost (measured ledgers)

- `ledger/api_usage.jsonl`: every paid model call with tokens and computed USD. Total so far USD 3.32, including
  smoke tests, chart reader tests, three sourcing runs, 15 paper check runs, five reviews, the two-model re-judge,
  one load check, one smoke search with the judge panel and one refused question.
- `ledger/build_usage.jsonl`: 46 Muse Code runs (42 that wrote the product, 4 sandbox smoke runs), USD 0.71 and
  4.9 hours in total. Muse Code read 63.3 million input tokens (93% from cache) and wrote 0.79 million output
  tokens.
- All Meta model spending: USD 4.03.
- A live study costs USD 0.0001 to parse the question plus whatever new sourcing it needs; a paper check costs
  about USD 0.013, a load check USD 0.01 and a review USD 0.25 to 0.33.

## Chart reader: how far it can be trusted

Tested twice with rules committed before each run (`docs/smoke/CHART_VALIDATION_RULES.md` and
`docs/smoke/CHART_VALIDATION_V3_RULES.md`). The first test failed: it missed the end points of each series, a
plain colour prompt found no hatched area, and a mask placement bug of ours broke wide images. All three were
fixed (the prompt now names the fill pattern). The second test passed on six new synthetic charts and on a real
paper figure it had never seen (Hiron et al. 2021, Figure 16 against the paper's Table 4). Away from the ends of a
series the read values were within 1.3% of the axis span (median 0.17%). The first and last point of a series were
less reliable, so every report marks them "edge, not validated". Since then it has one real job: the load check
above.

## How it was built

Every task has a spec in `docs/specs/` and acceptance tests written before the code. Up to T19, each test file
was checked against a reference build and against planted faults before Muse Code ran (recorded at the end of
each spec). For T20 to T23 the planted faults ran on Muse Code's build after it passed; one gap each in T21, T22
and T23 was closed with a test added after the code, labelled so. Three small fixes after the first live runs
(T22b, T23b, T23c) kept the same order: spec and failing test first, then Muse Code. Muse Code wrote the code in a
sandbox and ran the tests itself. It did not write the specs or the tests. Of the run tools in `tools/` it wrote
`tools/load_followup.py`, `tools/engineer_files.py` and `tools/resource_screen.py` and edited `tools/make_site.py`
(T20 to T23); T19 changed two others, with its own spec and tests first. The log of what
was decided and why is
`docs/implementation-notes.md`.

## Acknowledgements

This project uses SAM Materials from Meta: the SAM 3.1 model through the Meta Model API and the `meta-sam-parser`
package (installed as a dependency, not copied here), both under the SAM License. The example page quotes short
passages of Hiron et al. 2021 (Energies, CC BY 4.0) in its paper check and shows its Figure 7 as read by SAM
3.1; the figure image is in `docs/figures/`, with credit in the plan file.

## Licence

Code: MIT. See `LICENSE`.
