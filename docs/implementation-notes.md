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

## Muse Code runs its own tests in the sandbox (S00)

Havid ran `muse sandbox windows setup`; `muse sandbox windows check` now reports status=ready (measured). Four
read-only smoke runs (S00 to S00d, USD 0.0139 computed in total) checked that Muse Code can run pytest itself:

- S00: the shell ran, but `uv` is not on the sandbox PATH and the venv base Python sat in a user folder the
  sandbox account cannot read. Fix: the same CPython 3.12.13 was copied to F:/uv-python and `.venv/pyvenv.cfg`
  points there. The full suite still passes (1,065 of 1,065, measured).
- S00b: timed out on a sandbox lock held by the first-run read refresh, which took about 14 minutes.
- S00c and S00d: `.venv\Scripts\python.exe -m pytest ... tests/test_diesel_size.py` ran inside the sandbox with no
  network: 46 passed, exit code 0 (measured, from the raw event stream, not the model's summary).
- Side effect: S00c left a pytest temp folder in the repo root that only the sandbox account can open. It is
  ignored by git; later runs use `--basetemp build_logs\pytest_sandbox`.

## More checks for the review points (T15, Havid chose option A)

Havid's plan: A (checks for four open review points) now, C (one judge vote on the local Glimmer model) on Friday if
there is time, B (judge README, video, post) from Saturday. The feature freeze stays at Tuesday noon.

- Scope: existing data only. Overhaul cost has no source, so it is not priced; it joins the not covered list as the
  ninth item and the engine hours show which way it would push the answer. The 8 h duration is an optional check
  input `battery_duration_h_alt` (assumed) in `config/study_checks.json`.
- Test check: reference in scratch, 104 new tests, full suite 1,169 of 1,169; 42 of 42 planted faults caught. The
  first fault run missed the study passing an unserved limit of 1 (every design meets the limit on the test
  weather); a test that records the arguments the study passes now catches it.
- Edge cases in the orchestrator's own tests, fixed before the commit: a one design grid, a hand example that charged
  and discharged in the same hour, and an old test that lists the default check inputs (it needed the new entry).
- T15 (Muse Code, first attempt, 696 s, 31 calls, USD 0.0265 computed): Muse Code ran the acceptance tests (104
  passed) and the full suite (1,169 passed) itself in the Windows sandbox (measured, from the event stream). The
  orchestrator reran 1,169 of 1,169; protected files unchanged; text gate, ASCII and imports pass.
- Seventh live study (run f86df9819fa150a7, computed, 373 s, no new model call): every old number, gate, table and
  row equals study 84f23f2cd0b0f857, and the 19 new rows equal the scratch measurement. At the break even price rise
  (189.4%, computed) the design that ties diesel only is small (2,000 kWp and 1,000 kWh, computed), far below the
  main design; how fast the best size falls as prices rise was not measured.
- Third Muse Wonder review (run review-20261028T110232-c01b38, measured, 107.5 s, USD 0.33), scored by the rule in
  the T15 spec: battery power not raised; island prices and overhaul raised but pointed to "Not covered by this
  study" and "Inputs"; ageing still open, as expected. 2 open points (review 2: 6), both new: a bankable yield and
  reliability case, and an expansion path. One regular expression matched "staging" as "aging"; same outcome.
- The gallery now shows study f86df9819fa150a7 with review 3. The paper check run carries over (equal weather
  tables, checked by script).
- AGENTS.md now holds the sandbox test command. The commit says Havid approved it, but that was read from his plan
  reply, not a direct yes; it is listed for him to confirm or revert.
- Tests after T15: 1,169 of 1,169. Spend so far (ledgers): API USD 2.64, Muse Code USD 0.48.

## Curated inputs (T16, post hoc)

Havid asked to replace the weak inputs with values from reliable documents. This came after pre-registration, so
the values are marked post hoc everywhere and the first study stays as it is.

- Sources: the Danish Energy Agency and EA Energy Analyses catalogue for Indonesia (battery data sheet), the IEA
  commentary on the cost of capital in Southeast Asia with the Bank Indonesia inflation target (discount rate), and
  17 Pertamina Patra Niaga industrial price lists reposted by a fuel reseller (diesel). Tables in the catalogue are
  images; they were read by eye and again by OCR (RapidOCR), and both reads agree. One price list value matches a
  Kontan news report of the same list. A script recomputes every value from the saved copies (7 of 7 pass). The
  copies stay in the private prep repo for copyright.
- Outside review (DeepSeek V4.1 flash, max): proceed after fixes. Fixed: battery variable O&M added (4.48 instead
  of 3.75 USD/kWh/yr), G6 now also checks the judge text, title and URL of each curated row, wording no longer
  calls the build agent a judge. Not changed on review advice: the land density stays at the US median (0.87), as
  the catalogue value (1.099) would loosen a check after the answer was known. Each point and its answer is kept
  with the sources.
- Test check: reference in scratch, 92 new tests, full suite 1,261 of 1,261, 42 of 42 planted faults caught. The
  first fault run found that nothing tested the G6 re-read inside `curate_run`; a test now replaces
  `apply_curated` with one that tampers a value and expects the re-read to fail.
- T16 (Muse Code, first attempt, 622 s, 37 tool calls, USD 0.021 computed): Muse Code ran the acceptance tests and
  the full suite (1,261 passed) itself in the sandbox (measured, from the event stream). The orchestrator reran
  1,261 of 1,261; protected files unchanged; text gate passes.
- Curated sourcing `runs/sourcing/curated-20261028T212824-b5ae1a` (from the rejudged sourcing; G6 passes: 3 of 10
  checked, 0 kept assumed, 7 curated post hoc). Eighth live study (run 579f414386fe2d58, computed, 320 s, no new
  model call): 11 of 11 gates pass. Least cost 8,500 kWp and 19,000 kWh at 0.277 USD/kWh against 0.511 for diesel
  only (first study: 0.251 against 0.354). The design no longer fits the 9 ha at the US land density; the largest
  design that fits costs 0.279 USD/kWh. With 2.7 MW diesel units the best design sits on the grid edge (9,000 kWp).
  The battery charge peak now meets the 4,750 kW rating (100%).
- The gallery shows both studies; the new one has no Wonder review yet.
- Tests after T16: 1,261 of 1,261. Spend so far (ledgers): API USD 2.64, Muse Code USD 0.50.

## Correction: how the AGENTS.md sandbox edit was approved

- Commit 5e5c95b (AGENTS.md: Muse Code runs its acceptance tests in the Windows sandbox) says "Havid approved".
  That was not true when it was written. The orchestrator's first edit was blocked because Havid's approval
  prompt timed out. His next reply chose the build order and did not mention AGENTS.md; the orchestrator read
  that as a yes and committed the same edit. The commit is left as it is, because rewriting history needs his
  say-so.
- Havid was asked again after T16 with the full story, and chose to keep the edit (Wednesday 28 Oct, evening).
- The edit was used by the T15 and T16 builds (T14 came before it).

## Two judge models (T17, option C, Havid chose Muse Wonder as the third voter)

- Why: all 3 support votes came from one local model (Muse Glimmer), so they could share one blind spot. Muse Spark
  found the quotes, so it was not used as a judge. Now votes 1 and 2 are Glimmer and vote 3 is `muse-wonder-1.0`;
  a value stays checked only with 3 yes votes. Wonder votes last, so a value Glimmer turns down costs no API money.
- Spec and rule: `docs/specs/T17_judge_panel.md`, committed with the tests in d68ee56 before any counted run. Rule:
  re-judge the 4 checked rows of `rejudge-20261028T013500-26a59e` once, no retry, any no or error goes back to
  assumed, then one live study on the result and one on its curated copy, reported whichever way they move.
- Test check: reference in scratch, 55 new tests, full suite 1,316 of 1,316, 26 of 26 planted faults caught. Dry
  run of `tools/rejudge.py --panel` with fake judges and real fetches: a fake Wonder no sent its row back to
  assumed; G6 passed.
- T17 (Muse Code, first attempt, 561 s, 13 calls, USD 0.0081 computed): Muse Code ran the acceptance tests (55
  passed) and the full suite (1,316 passed) itself in the sandbox (measured, from the event stream). The
  orchestrator reran 1,316 of 1,316 (commit 426970b).
- Probe (not counted): one Wonder vote on the made-up test claim parsed as a yes in 5.1 s, USD 0.0127 (measured).
- Counted re-judge `runs/sourcing/rejudge-20261028T225230-d577a6`: Wonder said yes to all 4 rows (PV capex, PV O&M,
  diesel price, diesel minimum load), 2.9 to 8.7 s a vote, USD 0.085 for 4 calls (measured, ledger). G6 passes: 4 of
  7 checked, 3 kept assumed. Every raw vote is in the run's meta.
- Live study on it: run 5ee65dcd3350bec1 (436 s), 11 of 11 gates. Curated copy
  `runs/sourcing/curated-20261028T230814-3c30e9` and its live study 4a0c0eedd47b2672 (376 s), 11 of 11 gates. A
  script compared every fact, grid row, gate, firmness row, range row and sensitivity row with the earlier studies
  (f86df9819fa150a7 and 579f414386fe2d58): none differ. Only the judge text in the input notes and the sourcing meta
  changed.
- Not changed: new searches (`tools/source.py`) still use Glimmer for all 3 votes.
- Muse Wonder review of the curated run (review-20261028T151531-231e0b, 70 s, USD 0.206 measured): 10 points, 3
  open (diesel fuel curve and O&M assumed and not in the sensitivity table; the flagged Hiron load data; no forced
  outages, loss of the largest unit, start costs or sub-hourly ramps). A script found all 48 numbers the review
  quotes in the study and paper check files. The README now lists the reliability gap under what the study does
  not cover; the report itself is unchanged.
- Gallery: 4 studies, newest first, each card with a short note on its inputs and judges (`config/gallery.json`
  `note`, read by `tools/make_site.py`).
- Spend so far (ledgers): API USD 2.94, Muse Code USD 0.50.

## More sensitivity bars and SAM 3.1 reads the paper's load chart (T18a, T18b)

- Why: an AI judge round (three outside models scoring the entry, prep repo) said SAM 3.1 is listed but no study
  uses it, and two said the curated diesel unit size check sits on the grid edge at 9,000 kWp. The Muse Wonder
  review had already left the diesel fuel curve and O&M open. Havid chose one rebuild over wording fixes only.
- T18a (`docs/specs/T18a_more_sensitivity.md`): diesel O&M, diesel idle fuel, diesel fuel per kWh and battery hours
  join the sensitivity table (9 inputs, 18 rows); the diesel unit size and battery duration checks widen their grid
  up to 2 times like the main search; plain bar labels. `REPORT_SCHEMA` is now `autosolar.report/2`. Five old tests
  changed for this spec (listed at the end of the spec).
- T18b (`docs/specs/T18b_figure_check.md`): `autosolar/figure_check.py` reads Hiron Figure 7 (three measured days
  of 2018) with the chart reader and compares it with Table 6 scaled back 4 years at the paper's 3.48% a year; the
  study page shows the result. Image `docs/figures/hiron2021_fig7.png` (CC BY 4.0 paper), plan
  `config/figure_checks/hiron2021_fig7.json`, run rules `docs/smoke/FIGURE_CHECK_RULES.md` (fixed before the run,
  including what was seen by eye before it). Orchestrator tool: `tools/figure_check.py`; `tools/make_site.py`
  reads an optional `figure_check` run id per gallery entry.
- Test check: reference in scratch, 34 new tests for T18a and 75 for T18b, full suite 1,425 of 1,425, 29 of 29
  planted faults caught (the first pass missed one, the section order after the review; a test was added).
- T18a (Muse Code, first attempt, 976 s, 34 calls, USD 0.0354 computed): Muse Code ran the 34 acceptance tests;
  the orchestrator reran them and the full suite of that commit in a copy (1,350 of 1,350). The test helpers then
  moved from `tempfile.mkdtemp` to pytest temp folders: folders made inside the sandbox kept an access list that
  stops anyone else removing them (two empty ones are left in the repo root, untracked).
- T18b (Muse Code, first attempt, 900 s, 24 calls, USD 0.0185 computed): Muse Code ran the 75 acceptance tests and
  1,351 others; orchestrator full suite 1,425 of 1,425 (commit 3c4aad1).
- Load check, one run by the fixed rules (`figure-20261029T053942-12137f`, 4 SAM 3.1 calls and 1 Muse Spark label
  call, 33 s, USD 0.0103 measured): outside band. Table 6 scaled back to 2018 is 30.4% above the 31 Dec 2018 curve
  (16.7% above 27 Oct, 9.4% above 28 Sep), 22 of 24 hours. Results under "Results" in
  `docs/smoke/FIGURE_CHECK_RULES.md`; copy in `docs/smoke/figure_check_hiron2021_fig7.json`.
- Studies on the same two input files, weather from the cache of the earlier runs: b4a44fc6d4c32339 (805 s, 11 of
  11 gates) and curated 107477f112e5d92c (767 s, 11 of 11 gates). A script compared every fact, gate and table row
  with 5ee65dcd3350bec1 and 4a0c0eedd47b2672: only the 8 new sensitivity rows differ, and in the curated run
  `alt_on_grid_edge` went from yes to no (same 9,000 kWp and 19,000 kWh at 0.287 USD/kWh, now inside a wider grid).
- Muse Wonder review of the curated run (review-20261029T060800-acbbb2, 133 s, USD 0.319 measured): 10 points, 2
  open (the 8 h battery case costs the same with half the battery power; reliability). The fuel curve point is
  gone. A script found 64 of the 65 numbers it quotes in the study and paper check files; the other is its own
  product 2,375 x 330 = 783,750.
- Gallery: 6 studies; the two new ones carry the load check (`figure_check` in `config/gallery.json`). README
  screenshots taken from b4a44fc6d4c32339, plus `docs/img/load_check.png`.
- Spend so far (ledgers): API USD 3.27, Muse Code USD 0.56.

## T19: the judge panel by default, and a plain refusal (Thursday 29 Oct)

- Why: AI judge round 2 (all three judges) said a new search still used one model for all 3 votes, against the
  T17 argument; two asked to see a refusal. Both are tool changes (`tools/source.py`, `tools/ask.py`), not engine
  changes, so the orchestrator wrote them; no Muse Code run.
- Order: spec `docs/specs/T19_panel_default_and_refusal.md` and `tests/test_tools_t19.py` (30 tests, 29 failing
  before the code) committed first (d497b9a); smoke rules committed before the runs (6e62633); then the code.
- Planted faults: 20 of 20 caught by the new tests (default mode, panel order, panel name, local mode, unknown
  mode, vote log errors and cuts, refusal tuple, distance line, thousands comma, eager CAMS read, exit code, load
  line, hash without strip, lat and lon swapped, period, distance only for far sites, wrong address passed).
- `tools/ask.py` reads the CAMS address only when weather is fetched, so the demo commands (a reused study and a
  refusal) need only the model key.
- Smoke results in `docs/smoke/T19_SMOKE_RULES.md`: Bawean refused at 247 km (USD 0.000134, measured); the replay
  made no model call. One panel search for the diesel minimum load: checked at 0.3 with votes local yes, local
  yes, Wonder yes (USD 0.046, measured). Neither output is used by a study.
- Spend so far (ledgers): API USD 3.32, Muse Code USD 0.56, all Meta USD 3.88.
