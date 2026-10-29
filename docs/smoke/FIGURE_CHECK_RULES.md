# Figure check rules: SAM 3.1 reads Hiron Figure 7 (fixed before the run)

Written by the orchestrator before the run. Spec: `docs/specs/T18b_figure_check.md`. Plan:
`config/figure_checks/hiron2021_fig7.json`.

## What is compared

- The study's hourly load is Table 6 of Hiron et al. 2021 (`demand.HIRON_2021_LOAD_KW`, 2022 values).
- Page 11 of the paper: "Based on the load curve in December 2018, it can be assumed that the load curve in the
  year of PLTS plant development is 2022, considering an increase in load of 3.48% per year."
- Figure 7 (page 9) prints three measured days of 2018: 31 Dec, 27 Oct and 28 Sep, as overlapping areas (blue in
  front, then purple, then red at the back). The y axis is kWh per hour.
- The check scales Table 6 back 4 years at 3.48% a year and compares its energy over the read hours with the
  31 Dec 2018 curve. The band is +/-20%, the demand swing the sensitivity table already uses. Inside the band: the
  sensitivity table covers the gap. Outside: the page says the load may be off by more than the table tests.

## Image

- `docs/figures/hiron2021_fig7.png`: the image object Im11 of page 9 of the paper PDF, saved as PNG at its native
  size (1442 x 710 px), sha256 `7ffd38f0cf28343f3348a3bc9b94a64d611e2f0e7c6e8f25987fbd7b9df57bd4`. The paper is CC BY
  4.0, so the figure may be shared with credit.

## Run

- `tools/figure_check.py` runs the plan once: SAM 3.1 for the three areas (`blue area`, `purple area`, `red
  area`) and Muse Spark for the axis labels, through the same chart reader that passed its V3 test. About 4 SAM
  calls and 1 to 2 label calls, under USD 0.05 computed.
- No retry and no prompt change after the run starts. A failed read is reported as "not checkable" with its
  reason. The result goes on the new study pages as it comes out, whatever the verdict.

## What was seen before these rules

- The exploratory probe after SAM test 2 (`docs/smoke/sam_fig_probe.json`, 3 calls) ran the same three prompts on
  this figure and got one object each. It read no numbers.
- The orchestrator looked at the figure by eye while writing the plan. By eye, the 31 Dec 2018 curve sits near
  600 to 1,000 kWh, lower than Table 6 scaled back (about 810 to 1,240 kWh), so the verdict may well be "outside
  band". The band and the basis curve were fixed from the sensitivity table and the paper text, not from this
  look, and they do not change after the run.

## Results

(Added after the run.)
