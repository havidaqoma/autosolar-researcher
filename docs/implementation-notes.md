# Implementation notes (build log for the orchestrator)

Short entries. Plan reference: the prep plan, section 7 (stages and gates) and section 10 (day by day).

## Deviations

- Muse Code shell commands do not run on this PC: its Windows sandbox needs a one time admin setup
  (`muse sandbox windows setup`, status `setup_required`). Muse Code writes files; the orchestrator runs the tests
  outside it and sends failures back with `tools/muse_task.py --feedback`. Revisit if Havid runs the setup.
- `tools/muse_task.py` calls the Muse Code binary directly, not the `muse.cmd` launcher, to avoid quoting problems
  and to keep the version fixed during the build.

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

## Questions for review

- SAM 3.1 role: test 2 (rules fixed in 12696c9 before the run) gave 0 objects on 12 of 12 zoomed, contrast
  stretched tiles, so SAM leaves the satellite role. New role is Havid's choice; the chart probe
  (`docs/smoke/sam_fig_probe.json`) found one object per data series on the paper's Figure 7.
