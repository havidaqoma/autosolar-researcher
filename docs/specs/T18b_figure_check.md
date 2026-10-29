# T18b: a second read of the load, from the paper's own chart, by SAM 3.1

Status: spec by the orchestrator. Builder writes the new module `autosolar/figure_check.py` and edits
`autosolar/site.py` only. All earlier specs stay in force. The orchestrator has written
`tests/test_figure_check.py`, the plan `config/figure_checks/hiron2021_fig7.json` and the image
`docs/figures/hiron2021_fig7.png`.

## Why

The study's hourly load is the weakest input: it comes from Table 6 of Hiron et al. 2021, which our own paper check
flags. The chart reader (SAM 3.1 finds each curve, Muse Spark reads the axis labels) passed its validation test
(`docs/smoke/CHART_VALIDATION_V3_RULES.md`), but no study uses it. The same paper prints the measured load of three
days in 2018 as a chart (Figure 7) and says its 2022 load comes from the December 2018 curve grown by 3.48% a year
(page 11). Reading that chart gives a second, independent look at the load the study rests on.

## 1. autosolar/figure_check.py

Imports `ChartReadError`, `ChartSpec`, `CHART_READER_VALIDATION` and `read_chart` by name from
`autosolar.chart_reader` (the tests replace `figure_check.read_chart`). No network, no file writes.

Constants: `FIGURE_PLAN_SCHEMA = "autosolar.figure_plan/1"`, `FIGURE_CHECK_SCHEMA = "autosolar.figure_check/1"`,
`MIN_HOURS = 12`.

### load_plan(path) -> dict

Reads one JSON object (UTF-8). Every rule below raises `ValueError` naming the field. The top level holds exactly
these keys:

- `schema`: equals `FIGURE_PLAN_SCHEMA`.
- `paper`, `figure`, `image`: non-empty strings (after `strip()`).
- `image_sha256`: 64 lowercase hex characters.
- `series`: a non-empty list of objects with exactly `name` and `prompt`, both non-empty strings; names unique. The
  order is front to back (the front curve first), as `ChartSpec` expects for overlapping areas.
- `x_kind`, `y_kind`: `"clock"` or `"number"`.
- `y_unit`: `"kWh"` (energy per hour of the day, so a value equals the average kW of that hour).
- `x_values`: exactly the 24 hours 0 to 23 in order, as numbers (`bool` refused). Returned as floats.
- `stacking`: `"overlap"` or `"none"`.
- `compare`: an object with exactly `table` (non-empty string), `basis_series` (one of the series names),
  `basis_note` (string), `table_year` and `figure_year` (`int`, not `bool`, `table_year >= figure_year`),
  `growth_frac_per_yr` (finite real, 0 to 0.5) and `band_frac` (finite real, above 0 and below 1).

Returns the plan as a dict (a new object; `x_values` as a list of floats).

### compare_load(values, status, table_kw, *, basis_series, table_year, figure_year, growth_frac_per_yr, band_frac) -> dict

- `values`: dict series name -> 24 values (float or None); `status`: dict with the same keys -> 24 strings (the
  chart reader's point status). At least one series. `table_kw`: 24 finite real numbers of at least 0 (`bool`
  refused). `basis_series` must be a key. The other arguments follow the plan rules. Else `ValueError`. Inputs are
  never changed.
- `years = table_year - figure_year`, `scale = (1 + growth_frac_per_yr) ** years`, and
  `table_at_figure_year_kw = [v / scale for v in table_kw]`.
- `hours`: the hours h (ascending) where every series has status `"validated"` and a value that is not None.
- Fewer than `MIN_HOURS` hours: verdict `"not checkable"`, reason `"fewer than 12 hours read and validated in every
  curve"`; `table_kwh`, `ratio`, `diff_pct`, `mean_ratio` are None and `series` is an empty list. The same verdict,
  with reason `"basis curve has no energy"`, when the basis series sums to 0 or less over the hours.
- Otherwise:
  - `table_kwh` = sum of `table_at_figure_year_kw[h]` over the hours.
  - `series`: one row per series in the order of `values`: `{"name", "kwh", "peak_kwh", "ratio"}` with `kwh` the sum
    over the hours, `peak_kwh` the largest value over the hours, and `ratio = table_kwh / kwh` (None when `kwh` is
    not above 0).
  - `ratio` = `table_kwh` / the basis series `kwh`; `diff_pct = 100 * (ratio - 1)`.
  - `mean_ratio` = `table_kwh` / the mean `kwh` of all series.
  - verdict `"inside band"` when `abs(ratio - 1) <= band_frac + 1e-12`, else `"outside band"`; reason `""`.
- Returns a dict with exactly: `verdict`, `reason`, `hours`, `years`, `scale`, `table_at_figure_year_kw`,
  `table_kwh`, `series`, `basis_series`, `ratio`, `diff_pct`, `mean_ratio`, `band_frac`.

### run_figure_check(plan, image_png, table_kw, segment, read_labels) -> dict

1. `sha256(image_png)` must equal `plan["image_sha256"]`, else `ValueError` with "sha256" in the message. The table
   is checked as in `compare_load`. Both checks run before any read.
2. `ChartSpec(series={name: prompt, ...} in plan order, x_kind, y_kind, y_unit, stacking=plan stacking,
   x_values=tuple of the plan x values)`; `mode` stays `"top"`.
3. `read_chart(image_png, spec, segment, read_labels)`. A `ChartReadError` gives verdict `"not checkable"`, reason
   `"chart not read: " + str(error)`, `reading` None and `comparison` None. Any other exception is not caught.
4. Otherwise `comparison = compare_load(reading.values, reading.point_status, table_kw, ...)` with the plan's
   `compare` values (all but `table` and `basis_note`).
5. Returns a JSON-able dict with exactly: `schema` (`FIGURE_CHECK_SCHEMA`), `plan`, `image_sha256`, `table_kw` (list
   of floats), `verdict` and `reason` (from the comparison, or the read failure), `reading`, `comparison` and
   `validation` (a copy of `CHART_READER_VALIDATION`). `reading` holds `values`, `point_status`, `y_unit`,
   `sam_calls`, `label_calls`, `x_axis` and `y_axis`, each axis as `{"slope", "intercept", "used", "dropped",
   "max_resid"}` with lists for `used` and `dropped`.

## 2. site.py

- `figure_check_svg(result) -> str`: a line chart of the reading: one `<polyline>` per series through its hours that
  have a value (x = hour 0 to 23, y = kWh), and one dashed `<polyline>` (with `stroke-dasharray`) for
  `table_at_figure_year_kw`, with a legend that names each series and the scaled table. ASCII, all text escaped.
- `render_study_html(report, table, *, paper_check=None, review=None, figure_check=None)`. When `figure_check` is
  given, one section right after the paper section (or where the paper section would be):
  `<section id="figure-check"><h2>Second read of the load: SAM 3.1 reads the paper chart</h2>` holding:
  1. A paragraph: `<figure> of <paper>. SAM 3.1 found each curve in the image and Muse Spark read the axis labels;
     the values below were read off the image, not typed in.`
  2. When `reading` is None: `Not checkable: <reason>` and nothing else.
  3. Otherwise the SVG (in a `div class="scroll"`), then a table with headers `Day`, `Energy over the hours used
     (kWh)`, `Peak (kWh)`, `Study load scaled back, against this day`: one row per comparison series (name,
     `fmt(kwh, 0)`, `fmt(peak_kwh, 0)`, `fmt(ratio, 2)`), then the row `Study load, scaled back` with
     `fmt(table_kwh, 0)` and the largest scaled table value over the hours, `fmt(..., 0)`, and an empty cell.
  4. When the verdict is `"not checkable"` (reading present): `Not checkable: <reason>` instead of the table and
     the sentences below.
  5. Otherwise the sentences: `The study's load (<table>), scaled back <years> years at <growth pct, 2 decimals>% a
     year, is <abs(diff_pct), 1 decimal>% <above|below> the <basis_series> curve. <basis_note> That is
     <inside|outside> the +/-<band pct, 0 decimals>% demand swing of the sensitivity table.` Then `Over all <n> days
     the study's load is <abs(100 * (mean_ratio - 1)), 1 decimal>% <above|below> their mean.` Then `Hours used:
     <len(hours)> of 24 (read and validated in every curve; the first and last hour of a chart are not
     validated).` Then `Reader error in the chart reader test (measured): at most <real_figure_max_err_frac x 100,
     2 decimals>% of the axis span on a real figure and <synthetic_inner_max_err_frac x 100, 2 decimals>% on
     synthetic charts, away from the first and last point.` (values from `validation`).
  `above` when `diff_pct >= 0`, else `below`. Years and growth come from the plan's `compare`.
- With `figure_check=None` the page is exactly as before.

## Done when

- `tests/test_figure_check.py` and the rest of the suite pass. Text gate passes; ASCII only.

## Run rule (fixed before the run; the rules file is `docs/smoke/FIGURE_CHECK_RULES.md`)

The orchestrator tool `tools/figure_check.py` (not built here) runs the plan once with the production adapters
(`sam_segment_fn` on SAM 3.1, `spark_label_fn` on Muse Spark) and the study's table
`demand.HIRON_2021_LOAD_KW`. No retry, no prompt change after the run starts. The result is reported as it comes out.
