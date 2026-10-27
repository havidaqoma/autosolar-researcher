# Chart reader validation: rules fixed before the run

Written Tuesday 27 Oct, after the T03 code task started and before any validation call. Results go in
`chart_validation.json` and a separate section at the end of this file. Nothing above the results section changes
after the run.

## Why

Havid chose SAM 3.1's new job (D18): read the data series of charts in papers so the checker can compare a figure
with the paper's own text and tables. Before the report uses any number read from a chart, the reader must show
its error on charts whose true values are known.

## V1: synthetic charts with known values

- `tools/validate_chart_reader.py` renders 6 charts with matplotlib (seed 20261027, 1000 x 560 px, white
  background, plain fonts), runs `autosolar.chart_reader.read_chart` with the production adapters (SAM 3.1 for
  masks and tick label boxes, Muse Spark contributor for the label text) and compares with the true values.
- Charts 1 to 3: overlapping filled area charts like Excel's, 3 series each, 24 hourly points (x labels `H:00`
  every 3 hours, y labels with thousands commas). Series drawn back to front, and each back series is at least as
  high as every series in front of it at every hour (otherwise its hidden part cannot be read by anyone).
  Prompts: the fill colour plus "area" (for example "orange area"). Mode `top`, stacking `overlap`.
- Charts 4 to 6: line charts, 2 series each (blue and red, line width 2.5), mode `centre`, stacking `none`.
  Prompts "blue line" and "red line". Chart 4: x in hours (`H:00`); chart 5: x in percent 0 to 100 (number
  labels); chart 6: x in years 2015 to 2030 (number labels every 5 years, values at every year).
- Error of one point = absolute error divided by the y axis span (largest minus smallest y tick label printed on
  the chart). A point the reader returns as `None` counts as a miss.

V1 passes when all hold:
1. At least 5 of the 6 charts are read without an exception.
2. Over all points of the charts that were read: median error at most 1% of the span, and at least 95% of the
   points within 3% of the span (misses count as outside).

## V2: a real figure against the paper's own table

- Hiron et al. 2021 (Energies 14, 8311, CC BY 4.0) Figure 8, "Forecasting the daily electricity demand in 2022",
  the embedded image (1422 x 775 px) taken from the PDF without resampling. Overlapping area chart, three series;
  the back series "Predic. 2022" is the 2022 load forecast. Prompts in front to back order: "purple area" (Dec.
  2017), "green area" (Oct. 2018), "yellow area" (Predic. 2022). Mode `top`, stacking `overlap`, x labels
  `H:00`, x values 0 to 23.
- Truth: Table 6 of the same paper, hourly load, 24 values (sum 26,214 kWh per day, as typed into
  `prep/benchmark/hiron2021_audit.py` before this test).
- Error of one hour = absolute error divided by the y span printed on the chart.

V2 passes when all hold: 24 of 24 hours read; mean error at most 2% of the span; largest error at most 5% of
the span; daily sum within 2% of 26,214 kWh.

## What each outcome means

- Both pass: the report may use numbers read from charts, labelled "read from figure (SAM 3.1), validation
  error X%".
- V1 passes and V2 fails, or the reverse: chart readings appear in the report only as flags for a person to
  check, never as numbers in a result, and the report says why.
- Both fail: the chart reader is shown in the report as a tested and failed idea, with these numbers.

## Cost

SAM calls: V1 has 3 area charts x (3 series + 1 tick call) = 12 and 3 line charts x (2 series + 1 tick call) = 9;
V2 has 3 series + 1 tick call = 4. Total 25 SAM calls (USD 0.0625) plus 7 Muse Spark label calls, about USD 0.07
computed. No retry of a failed chart.
