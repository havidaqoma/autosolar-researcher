# Implementation notes (build log for the orchestrator)

Short entries. Plan reference: the prep plan, section 7 (stages and gates) and section 10 (day by day).

## Deviations

- Muse Code shell commands do not run on this PC: its Windows sandbox needs a one time admin setup
  (`muse sandbox windows setup`, status `setup_required`). Muse Code writes files; the orchestrator runs the tests
  outside it and sends failures back with `tools/muse_task.py --feedback`. Revisit if Havid runs the setup.
- `tools/muse_task.py` calls the Muse Code binary directly, not the `muse.cmd` launcher, to avoid quoting problems
  and to keep the version fixed during the build.
- T03 attempt 1: Muse Code could not run Python to look at the `meta-sam-parser` API, so it guessed it with
  duck typing and a regex fallback parser (794 lines, 2 of 64 tests failed). Fix: the orchestrator measured the
  library and added a "Library facts" section to the spec; attempt 2 used it directly (501 lines, 111 of 111).
  Lesson: when a task uses a third party library, put the measured API in the spec before the first attempt.

## Discovered edge cases

- Muse Code loads personal skills from other coding agents on this PC by default; every run uses
  `--no-foreign-personal-context` so only this repo goes into the prompt (contributor mode may train on it).
- Muse Code's own instructions cost about 27,000 input tokens per call; most of them are cached on later calls of
  the same run (measured probe: 113,732 of 143,055 input tokens cached).

- SAM 3.1 on Sentinel-2 crops (10 m pixels, 2 images, Tuesday 27 Oct): 0 objects for 18 of 19 concept prompts
  (building, roof, house, open field, water, solar panel, forest, beach, road, cloud, island, town, coral reef,
  sea). The one hit, "sea" on the island crop, is a single box covering 98% of the image. A synthetic control
  (prompt "red square" on 3 red, 2 yellow, 1 blue squares) returned exactly the 3 red squares, so the request
  and the parsing are right. Measured in `docs/smoke/sam_smoke.json`; 20 SAM calls, USD 0.05 computed.
- OpenAerialMap has no open drone or aerial images over Karimunjawa, Sumba, Kepulauan Seribu, Bawean or Selayar
  (API search, 0 results each; the same query returns 6 for Jakarta and 1,084 for all of Indonesia).
- `meta-sam-parser` is under the SAM License (read Tuesday 27 Oct): use and redistribution allowed; a
  redistribution must carry a copy of the licence; a publication of results must acknowledge the use of SAM
  Materials. The product depends on it through `pyproject.toml` and does not copy its code, so the README needs the
  acknowledgement only.
- Chart reader validation (rules fixed in fa03702, results in `docs/smoke/chart_validation.json`): every point it
  read on 6 synthetic charts was within 1.15% of the y span (median 0.13%), but it returned nothing for the first
  and last x value of every series (29 of 318 points), so V1 failed the 95% rule (90.9%). On Hiron 2021 Figure 8
  SAM found the purple hatched area but no object for "green area" (a green checked pattern), so V2 failed.
  Verdict by the fixed rule: tested and failed idea.
- SAM mask rasters are local to their box and smaller than the box when the box is large (measured: 1398 x 298
  box, 1024 x 218 raster). The T03 spec placed them at their own size, which squeezed every Hiron Figure 8 mask
  into the left 1024 columns. Found in practice calls, fixed in spec revision T03c with a real fixture test.
- Chart reader V3 (Havid chose one more test; rules fixed in 31a1bf1 before any V3 call, results in
  `docs/smoke/chart_validation_v3.json`): V3a PASS on 6 new synthetic charts (318 of 318 points read, median
  error 0.17% of the y span, 99.4% within 3%); V3b PASS on Hiron 2021 Figure 16, never seen before, against its
  Table 4 (10 of 10 bars, mean error 0.17%, largest 0.76% of the span). Verdict by the fixed rule: chart numbers
  may enter the report with the measured error. Weak spots, measured: the first or last x point holds the two
  synthetic misses over 3% (3.2% and 4.0%); on the practice Figure 8 the 0:00 and 23:00 hours were off by 10%
  and 32% of the span while the other 22 hours were within 1.6%; Muse Spark misread 6 of 10 x labels on
  Figure 16 and the leave one out axis fit dropped them.
- Weather sources at Karimunjawa (T05 product code on the live services, Tuesday 27 Oct, 64 s with an empty
  cache; output in `runs/`, not committed): the year closest to the 2016 to 2024 mean is 2020 for both CAMS and
  NASA POWER. Annual GHI: CAMS 1680.2, NASA POWER 1825.8, PVGIS-ERA5 TMY 2026.7, GSA scaled 1776.8 kWh/m2; spread
  20.6% (8.7% without ERA5), so every study must show the range. At tilt 10 facing north the T04 model gives
  1311 (CAMS) to 1584 (ERA5) kWh/kWp, performance ratio 0.77 for all four. The ERA5 TMY total differs by 0.24%
  from the prep cross-check value (2021.8, PVGIS PVcalc multi year mean, a different PVGIS product). CAMS gives
  irradiance only, so its case takes temperature and wind from NASA POWER of the same year.

## Questions for review

- SAM 3.1 role: test 2 (rules fixed in 12696c9 before the run) gave 0 objects on 12 of 12 zoomed, contrast
  stretched tiles, so SAM leaves the satellite role (D17). Havid picked the chart reader as the new role (D18).
- Chart reader edge points: Havid approved (Tuesday 27 Oct) marking the first and last x value of each series as
  "edge, not validated" (T03d, `point_status`). Away from the edges the V3 synthetic error was at most 1.32% of
  the span (median 0.17%); at the edges up to 3.96% (computed from `docs/smoke/chart_validation_v3.json`).

- First end to end study (T09, run cbf756b46b12a736, `docs/examples/T09_karimunjawa_report.md`): one question in,
  report out, no manual step, all 10 gate rows passed. With the costs still assumed, the least cost design is
  7,750 kWp PV and 19,000 kWh battery (computed), LCOE 0.235 USD/kWh against 0.355 USD/kWh for diesel only
  (computed), renewable share 87.5% (computed). Hiron et al. 2021 proposed 0.99 MW AC of PV (paper). The gap comes
  from the assumed costs and the least cost goal, so no claim rests on it until stage S3 brings sourced costs.
- Side rows can sit on the grid edge. Only the main case widens its grid; the growth demand row and the demand
  +20% sensitivity row both picked 9,000 kWp, the top of the widened grid (computed). Their LCOE values are upper
  bounds, not optima. The next report task must mark such rows in the note column.
- One live study took 336 s (measured, `runs/T09_live_check.txt`), most of it the weather fetch and the design
  grids. A repeat of the same question with the same inputs is read back from `runs/studies/<run_hash>/` with no
  service call.

- Side row edge flag done (T10c, Tuesday 27 Oct): range and sensitivity rows whose pick sits on the grid edge now
  carry an edge note, and the report answer lines use readable titles.
- First real sourcing run (stage S3, `docs/smoke/T10_sourcing_run1.json`, measured): 7 searches, USD 0.276, 322 s.
  1 of 7 inputs checked (battery O&M 7 USD/kWh/yr, MDPI open PDF, quote exact, judge yes in 9.7 s). The other 6
  stayed assumed for script reasons, not because the judge said no: 3 publisher pages answered HTTP 403 to the
  script (PMC, MDPI, an IRENA CDN), 1 IRENA PDF of 152 pages failed in pypdf on 3 pages and was dropped whole, and
  the search model wrote 2 units the checker could not read (a bare IDR, and USD/kWp for a yearly cost). T10d
  answers each of these (page tolerance, open copies via Europe PMC and OpenAlex, unit wording in the prompt, one
  feedback search). A judge no or an out of band value never triggers a second search, so the retry cannot shop
  for a number.

- Second sourcing run after T10d (`docs/smoke/T10_sourcing_run2.json`, measured): 812 s, USD 0.670 for 11 searches
  (4 inputs took a second search). 3 of 7 inputs checked: PV capex 1119 USD/kW (Frontiers 2024, quote near), PV
  O&M 24.38 US$/kW per year (Scientific Reports 2022, quote near), diesel 14000 IDR per litre (FFTC page, quote
  exact, found on search try 2; fx 16500 assumed). The judge said no twice (an IEA battery figure for general
  storage projects, a 5 % discount rate). Two MDPI pages still answered HTTP 403 after 4 open copies each.
  The two longest searches read about 2 million input tokens each; that is the cost driver to watch.
- Second live study (`docs/examples/T10_karimunjawa_report.md`, run 71c5bed5603853e6, computed, 221 s, cached
  question parse so model cost about USD 0.0001): with the 3 checked inputs the least cost design is 7,250 kWp PV
  plus 19,000 kWh battery, 0.251 USD/kWh against 0.354 for diesel only (-29.1 %), 85.8 % renewable, 3.10 million
  litres of diesel saved per year. All 11 gate rows pass, G6 included. Battery cost, discount rate and minimum
  diesel load are still assumed, so the answer is still a placeholder until those are sourced.

## T10e and sourcing run 3 (Wednesday 28 Oct)

Rule first: the run 3 rule and the `--carry` option were committed in the T10e spec (b584550) before any run.

- T10e (built by Muse Code on the first attempt, 175 s, USD 0.0106 computed): the judge now sees the source URL,
  and the source title only when the fetched text contains it, so the search model cannot steer the judge with a
  made up title. A percent unit with a descriptor such as "% of its rated capacity" now reads as a percent, and a
  percent still converts only to a fraction. 753 of 753 tests pass.
- Honesty check (`docs/smoke/T10e_judge_probe.json`, measured, local judge, 3 runs): the planted trap (a nominal
  WACC quoted for a real discount rate) still got supports false in 3 of 3 runs with the title shown. The other
  verdicts drift between runs because the judge samples at temperature 1.0: the general battery figure went no, yes,
  yes and the scenario diesel price went no, yes, no. A sourcing run asks the judge once per row, so one sampled
  verdict decides each row.
- Run 3 (`docs/smoke/T10_sourcing_run3.json`, measured): 316 s, USD 0.245 for 6 searches. It carried the 3 checked
  rows of run 2 unchanged and searched only the 4 assumed inputs. 1 new input checked: diesel minimum load 25 % of
  rated power (MDPI Energies 2021, open PDF, page 8, quote exact, DOI resolves). Still assumed: battery capex (judge
  no to a general storage figure, the same call as in the first probe), battery O&M (50 USD/kWh/yr, outside the
  band), discount rate (HTTP 403, then a connection error). The title change was not tested on the discount rate,
  because the search did not return the Indonesia paper this time. G6 passes with 4 of 7.
- Third live study (`docs/examples/T10e_karimunjawa_report.md`, run 9f9ac2afa1f46b43, computed, 472 s, cached
  question parse so no model cost): the least cost design stays 7,250 kWp PV plus 19,000 kWh battery at 0.251
  USD/kWh against 0.354 for diesel only, 85.8 % renewable, 3,104,445 litres of diesel saved per year (study 2:
  3,104,707). The minimum load change moves 851 of 925 grid designs by up to 0.0039 USD/kWh, but only 0.000006
  USD/kWh at the chosen design. The 7,500 kWp design is now 0.000005 USD/kWh behind, so the pick between the two
  is a tie in practice. All 11 gate rows pass.

## T10f: the judge must say yes 3 times in a row (Wednesday 28 Oct)

Rule first: the vote rule and the re-judge rule were committed in the T10f spec (067edee) before any run.

- Why: the T10e honesty check showed the local judge gives different verdicts to the same claim at temperature
  1.0 (2 of 4 probe claims flipped between runs), and a sourcing run asked it once per row.
- T10f (built by Muse Code on the first attempt, 70 s, USD 0.0061 computed): `support_votes` asks the judge up to
  3 times with the same prompt and stops at the first answer that is not yes. A row is checked only after 3 yes
  answers. `CitationCheck.judge_calls` records the calls. 783 of 783 tests pass; the orchestrator's reference
  caught 19 of 19 planted faults.
- Re-judge (`docs/smoke/T10f_rejudge.json`, measured, `tools/rejudge.py`, 156 s, 12 local judge calls, no model
  API cost): all 4 rows checked so far got 3 of 3 yes, so all 4 stay checked with the same values. G6 passes with
  4 of 7. The tool fails closed: a row that cannot be fetched again goes back to its assumed value.
- Fourth live study (`docs/examples/T10f_karimunjawa_report.md`, run ff628b57b3c357b1, computed, 321 s, no model
  cost): all 925 grid designs are identical to the third study, so the answer stands: 7,250 kWp PV plus 19,000 kWh
  battery at 0.251 USD/kWh against 0.354 for diesel only. All 11 gate rows pass. The report now names the vote rule.
- Limit that stays: 3 yes answers from one sampled model are stronger evidence than 1, but they are not
  independent reviews. A second judge model is the next step if a checked value is ever disputed.

## T11 to T13: how firm is the answer, the paper check, the study page (Wednesday 28 Oct)

Asked by Havid after T10f: "can you deep thinking what to improve?" The answer was that the engine was done but
the judge-facing parts were not, and that an energy engineer would catch six gaps. He chose: HTML gallery plus a
recorded run, build the paper check, use the 9 ha from the press as the land limit.

- T11a (Muse Code, first attempt, 152 s, USD 0.0162 computed): `DieselFleet.must_run_units`, so a reserve case
  can keep diesel units running in every hour. 42 tests with a hand worked day; 20 of 20 planted faults caught.
- T11b (Muse Code, first attempt, 460 s, USD 0.0256 computed): `autosolar/firmness.py` and a report section "How
  firm is the answer" plus "Not covered by this study". Check inputs live in `config/study_checks.json`: 9 ha of
  land (press), 0.87 MWdc per ha (paper: Bolinger and Bolinger, IEEE J. Photovoltaics, median US fixed-tilt
  plants), the published PV size 1,244.48 kWp (paper: 3,889 modules of 320 Wp), one must-run unit (assumed), a 1%
  near tie (assumed). 52 tests; 27 of 27 planted faults caught.
- Fifth live study (run 59eba198a2af900c, computed, 424 s): the main answer is unchanged (7,250 kWp plus 19,000
  kWh, 0.251 against 0.354 USD/kWh). New: 8 designs are within 1% (6,750 to 8,250 kWp); the main design runs the
  diesel 1,458 h a year and starts it 217 times, so the battery and PV hold the grid alone for 7,302 h. With one
  diesel unit running in every hour the least cost design shrinks to 1,500 kWp plus 1,000 kWh at 0.336 USD/kWh, and
  the main design would cost 0.414 USD/kWh, more than diesel only. That is the biggest open question for PLN:
  can the island grid run on inverters alone? The main design needs 8.3 ha of the 9.0 ha. The published size
  (1,244 kWp, PV only) gives 0.336 USD/kWh. The true model cost behind the study is USD 0.43 (computed), almost
  all of it the web search that sourced the inputs; the old cost line showed only the question parse.
- T12a (Muse Code, first attempt, 525 s, USD 0.0277 computed): `autosolar/paper_check.py` keeps a number only if
  its quote is in the PDF text layer, then runs the frozen checks P1 to P15. 85 tests; 34 of 34 planted faults.
  T12a2 (60 s, USD 0.0078): table cells fall back to the numbers on their page, because a PDF text layer prints a
  table's headers apart from its values. T12b (70 s, USD 0.0050): structured output (`text.format` with a JSON
  Schema) in the Meta client. T12c (45 s, USD 0.0042): `store` flag, because a 16 MB PDF sent inline is refused when
  the response is stored (HTTP 413, measured).
- Paper check on Hiron 2021 (in-sample, measured, `docs/smoke/T12_paper_hiron_v1.json` and
  `T12_paper_hiron_v2_v4.json`, 3 runs per prompt version, about USD 0.01 a run): v1 found 8, 3 and 1 of the 13
  hand audit items the frozen checks cover (two runs wrote numbers as strings); v2 found 1, 10 and 1 (two runs broke
  the JSON); with structured output v3 found 11, 9 and 11 and v4 found 11, 8 and 11 with no extra flags. The
  990 kW plant that delivers 1,990 kW at 11:00 (P5) is flagged in all 6 structured runs. The prompt was tuned on
  this paper, so these numbers say the tool can find what a careful reader finds, not how well it generalises.
  Prompt v4 was frozen (sha e8517bdf125f52f8) before the out-of-sample paper 2 runs.
- Muse Wonder review (run review-20261028T035915-48ee2e, measured, 130 s, USD 0.29): 10 points, 3 not answered in
  the report (battery sizing and life, reliability beyond an hourly balance, a year-by-year cash flow). Its first
  point is the reserve case. One point misreads gate G2 (equal discharge and stored energy is expected when the
  battery ends where it started); the page shows the points as the reviewer wrote them.
- T13 (Muse Code, 120 s, USD 0.0143) and T13b (340 s, USD 0.0289): `autosolar/site.py` writes one self contained
  HTML page per study (inline SVG heat map of every design, tornado chart, weather bars, no script) and a gallery
  index; `tools/make_site.py` builds `docs/site/` from `config/gallery.json`. The answer section now lists the five
  caveats next to the headline.
- Tests: 1,010 of 1,010 pass.
- Paper 2, out of sample (`docs/smoke/T12_paper2.json`, measured, frozen prompt v4, 3 runs, USD 0.045 in total):
  the original version of Mathematics 11, 1248 (Basra; its correction notice changes two numbers in Figure 1 and
  the cost numbers of one paragraph). None of the 3 scored items was flagged in any run. As run, the flags were
  P1 and P11, P1, P8 and P11, and P11. A hand check found P1 (the same number with the same empty unit) and P8 (a
  unit with no time period read as per year) false; both were bugs against the frozen check text and were fixed in
  T12d (85 s, USD 0.0080), and every saved run was scored again by script (`tools/rescore_paper.py`, no model
  call). After the fix only P11 remains in all 3 runs, and it is not confirmed: the paper gives the battery cost per
  battery unit (120 USD), not per kWh. Hiron scores did not change. By eye, the paper's result of 8,683,501 kW of PV
  and 26.7 million batteries looks wrong, but no frozen check compares sizes with the load, so the tool says
  nothing about it. The README therefore says the paper 2 test does not support a claim of finding errors in papers
  the checks were not written for.
- Tests after T12d: 1,019 of 1,019 pass. Spend so far (ledgers): API USD 2.06, Muse Code USD 0.41.

## Diesel unit size range (Havid approved the range plus polish)

The Hiron paper prints two diesel fleet sizes: 2 x 2.7 MW on p1 and in Table 1, and 2 x 1.8 MW on p7 with the
feeder voltages (paper). The study uses 1.8 MW units. Rather than pick one in silence, the study now reports both.

- Scratch measurement first (no model call): the saved design grid of study 59eba198a2af900c rerun with 2.7 MW units
  gave diesel only 0.410 USD/kWh, least cost 7,500 kWp plus 19,000 kWh at 0.260, and a reserve case of 750 kWp, no
  battery, at 0.400 (computed). Bigger units burn more fuel at low load and set a higher floor when one must run.
- T14 (Muse Code, first attempt, 270 s, USD 0.0200 computed): optional check input `diesel_unit_kw_alt` in
  `config/study_checks.json` (2,700 kW, paper); `firmness.diesel_size_case` reruns the design search and the
  reserve case with that unit size; 11 new rows in "How firm is the answer" and a sixth caveat next to the
  headline. 46 new tests; 25 of 25 planted faults caught; one more fault was equivalent (dispatch_grid already
  refuses a grid without the 0 kWp, 0 kWh design) and is not counted.
- Sixth live study (run 84f23f2cd0b0f857, computed, 510 s, no new model call: the question parse came from the
  request cache, and the saved sourcing and cached weather were reused): every main number, gate and range row
  equals study 59eba198a2af900c, and the 2.7 MW rows equal
  the scratch measurement to the last digit. With 2.7 MW units the answer stays yes (0.260 against 0.410 USD/kWh,
  -36.7%), but if one unit must run in every hour the main design would cost 0.519 and the best design, 750 kWp with
  no battery at 0.400, is only 2.4% below diesel only. So the reserve question matters more with the larger units.
- The gallery now shows study 84f23f2cd0b0f857. Its paper check is still run paper-20261028T035325-b646fb, made
  against study 59eba198a2af900c; the paper check reads only the study's weather table, and the two weather tables
  are equal (checked by script), so the result carries over.
- Second Muse Wonder review (run review-20261028T061110-63e19f, measured, 104 s, USD 0.25): 10 points, 6 not
  answered (demand data, a battery power set by the assumed 4 h duration, delivered island costs, the fuel price,
  diesel overhaul and replacement, reliability and ageing outputs). The first review had 3 open, one of them the
  diesel unit size, which T14 answers. The two lists differ on nearly the same report, so the README presents them
  as a reader's questions, not a score.
- Tests after T14: 1,065 of 1,065 pass. Spend so far (ledgers): API USD 2.31, Muse Code USD 0.43.
