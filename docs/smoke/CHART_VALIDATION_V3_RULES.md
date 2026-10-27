# Chart reader validation V3: rules fixed before the run

Havid chose one more test with fixed rules (Tuesday 27 Oct) after V1 and V2 both failed (results in
`CHART_VALIDATION_RULES.md`, commit 86cd1e1). This file is committed before any V3 call. Results go to
`chart_validation_v3.json` and to a final section added after the run.

## What changed since V1 and V2 (found in practice calls, not in the counted test)

1. Mask placement (our bug, in the T03 spec). SAM sends each mask as a raster local to its box, and when the box
   is large the raster is smaller than the box. Controlled check on a 1600 x 500 image with one red rectangle:
   the box was 1398 x 298 px and the raster 1024 x 218. Placed at its own size the mask matched the rectangle
   with intersection over union 0.531; stretched onto the box, 0.991 (measured, `tools/probe_mask_scale.py`,
   fixture `tests/fixtures/sam_wide_rect.txt`). On Hiron Figure 8 (1422 px wide) all three masks were
   squeezed into the left 1024 columns, so V2 could not have passed. V1 charts were 1000 px wide and not hit.
2. Edge columns. All 29 V1 misses were the first or last x value, where the sample column falls on the axis
   line and holds no mask pixel. New rule: fall back to the nearest usable column within 3 columns, skipping
   one pixel anti aliasing slivers (spec revision T03c, `docs/specs/T03_chart_reader.md`).
3. Prompts for patterned fills. On Hiron Figure 8, "green area" gave no object; "green checkered area" gave
   one (practice call). Prompts below name the pattern.

Practice calls after V1 and V2: 8 SAM calls (`docs/smoke/chart_practice.jsonl` and the wide rectangle
fixture), about USD 0.02 computed. Hiron Figure 8 is now a practice figure: it is run again below and reported,
but it does not count, because its prompts were chosen after looking at its masks.

## Code under test

`autosolar/chart_reader.py` at the T03c commit, which must pass the full test suite before the run. The run
uses the production adapters (`sam_segment_fn` with SAM 3.1, `spark_label_fn` with Muse Spark contributor) and
`tools/validate_chart_reader_v3.py`. No retry of a failed chart, no change of prompt after the run starts.

## V3a: six new synthetic charts (seed 20261028)

Rendered before this file was committed (sha256 prefix in brackets). Overlapping area charts draw the back
series first; each area starts at zero; the front one hides the ones behind. Prompts are written from the
colours and patterns below, the way a person reads a legend.

| Chart | Size (px) | Series, front to back, with the SAM prompt |
|---|---|---|
| area1 [e691df96cfd5] | 1400 x 700 | "orange area", "blue area", "green area" (flat fills) |
| area2 [3959d0c610c5] | 1400 x 700 | "purple striped area", "green striped area", "yellow striped area" |
| area3 [93a856a9715b] | 1400 x 700 | "green checkered area", "purple striped area", "yellow area" |
| line4 [5188c167b346] | 1000 x 560 | "blue line", "red line" (x labels H:00) |
| line5 [1e1163101710] | 1400 x 700 | "blue line", "red line" (x 0 to 100) |
| line6 [8e66bf69a691] | 1200 x 600 | "blue line", "red line" (x 2015 to 2030) |

Pass (same thresholds as V1): at least 5 of 6 charts read without error, median error of the read points at
most 0.01 of the y axis span, and at least 95% of all points within 0.03 of the span (a missed point counts as
outside).

## V3b: a real figure SAM has never seen

Hiron 2021 Figure 16 (LCOE against PV penetration, blue bars with a dotted trend line and two red dashed
lines; vector graphics on page 17 of the PDF). Rendered with pymupdf at 330 dpi from the clip
(169.8, 97.8, 418.5, 264.9) pt to `runs/chart_validation_v3/hiron_fig16.png`, 1141 x 767 px, sha256
6782b6b4177545a7710e2a65cd138aec81608f4377909adc0f183206736bf85a (checked by the script before any call).
Prompt: "blue bar" for the series LCOE; x values 10 to 100 in steps of 10.

Truth: the paper's Table 4 (299.554, 294.911, 290.269, 285.626, 280.983, 276.340, 271.697, 265.827, 261.184,
257.770 USD per MWh). The bar tops in the PDF drawing give 299.50 to 257.74, within 0.07 of Table 4
(computed from the vector coordinates), so the figure and the table agree.

Pass: all 10 bars read, mean error at most 0.02 of the y axis span (the span of the y ticks the axis fit used)
and largest error at most 0.05 of it.

## Practice figure (reported, not counted)

Hiron Figure 8 with prompts "purple striped area" (Dec. 2017, front), "green checkered area" (Oct. 2018),
"yellow striped area" (Predic. 2022, back), compared with Table 6 as in V2.

## Outcome, fixed now

- V3a and V3b pass: chart numbers may enter the report, each with the measured error of this test.
- V3a passes, V3b fails: chart numbers only as flags marked "not validated on a real figure".
- V3a fails: the chart reader stops. The report shows V1, V2 and V3 as a tested and failed idea. No fourth test.

## Cost

V3a: 21 SAM calls and 6 Muse Spark label calls. V3b: 2 SAM and 1 Muse Spark. Practice: 4 SAM and 1 Muse Spark.
27 SAM calls (USD 0.0675) and 8 label calls; at most USD 0.15 in total, computed from the API ledger.
