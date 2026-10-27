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
