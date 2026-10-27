# T03: chart reader (`autosolar/chart_reader.py`)

Status: spec by the orchestrator. Acceptance tests: `tests/test_chart_reader.py` (do not edit them).
Depends on: `autosolar/meta_client.py` (T02, done) only through the two adapter functions at the end.

## Why

SAM 3.1 cannot see roofs at 10 m (decision D17), but it outlines each data series of a chart in a paper. This
module turns those outlines into numbers, so the checker can compare a paper's figure with the paper's own text
and tables. Example: Hiron 2021 Figure 7 (hourly load on three days) against the text and Table 6.

## Allowed extra dependencies

`meta-sam-parser` (Meta's parser for the SAM output grammar, already in `pyproject.toml`) and `pillow` (read PNG
size, crop). Do not vendor or copy code from `meta-sam-parser`; import it.

## Coordinates (read this twice)

- Pixel `(col, row)` covers the square `[col, col + 1) x [row, row + 1)` in continuous image coordinates. Row 0
  is the top of the image.
- SAM box records from `meta_sam_parser` are already half-open: `left, top, right, bottom` with `right` and
  `bottom` excluded. A box's centre is `((left + right) / 2, (top + bottom) / 2)` in continuous coordinates.
- A tick label sits next to its tick, so its tick position is the box centre: the centre y for a y axis label,
  the centre x for an x axis label.
- The top edge of a filled area in column `col` is the continuous y `r`, where `r` is the smallest row index with
  a True mask pixel in that column (the top side of that pixel). The centre of a line in column `col` is
  `mean(rows) + 0.5` over the True rows in that column.
- An x value maps to the column `floor(x_axis.px(x) + 1e-6)` (the small term absorbs float error).

## Public API

```python
from autosolar.chart_reader import (ChartReadError, ObjectMask, AxisFit, ChartSpec, ChartReading,
    parse_sam_masks, parse_tick_label, fit_axis, top_edge_px, line_centre_px, series_values,
    parse_label_answer, read_chart, sam_segment_fn, spark_label_fn)
```

- `class ChartReadError(ValueError)`.
- `@dataclass(frozen=True) class ObjectMask`: `object_id: str`, `mask: numpy.ndarray` (bool, shape
  `(height, width)` of the whole image), `box_px: tuple[float, float, float, float]` (left, top, right, bottom,
  half-open), `confidence: float | None`.
- `parse_sam_masks(text: str, image_wh: tuple[int, int]) -> list[ObjectMask]`
  - Parse with `meta_sam_parser.image_segmentation_format().create_parser()`, `push(text, emit=False)`,
    `finish(meta_sam_parser.CompletedOutcome())`.
  - Any diagnostic with severity `"error"`: raise `ChartReadError` with its code and message.
  - One `ObjectMask` per `SegmentationMaskRecord`, in record order. Decode with
    `meta_sam_parser.decode_mask_to_raster` (bytes, one byte per pixel, row major, nonzero = inside) and place
    the raster into a full image array of shape `(image_wh[1], image_wh[0])` at the record's `bounds`
    (`left`, `top`). The raster must be exactly `mask.height x mask.width`, and the bounds must lie inside the
    image; otherwise raise `ChartReadError`. `box_px` = the record's bounds. `confidence` = the record's
    confidence. Box records without a mask are ignored. Text records are ignored.
- `parse_tick_label(text: str | None, kind: str) -> float | None`
  - `kind == "number"`: after `str.strip()`, accept `-?digits` with optional thousands commas in groups of 3
    and an optional decimal part (`"1400"`, `"1,400"`, `"-2.5"`, `"0"`). Return the float. Anything else
    (including `"2022."`, `"1,40"`, `"12:00"`, `""`, `None`) returns `None`.
  - `kind == "clock"`: accept `H:MM` or `HH:MM` with `0 <= H <= 24` and `0 <= MM < 60`; return hours as a float
    (`"14:00"` gives 14.0, `"0:30"` gives 0.5). `"24:30"` and anything else returns `None`.
  - Any other `kind`: raise `ValueError`.
- `@dataclass(frozen=True) class AxisFit`: `slope: float` (value per pixel), `intercept: float`,
  `used: tuple[int, ...]` and `dropped: tuple[int, ...]` (indices into the input tick list, ascending),
  `max_resid: float` (largest absolute residual of the used ticks, in axis value units).
  Methods `value(px: float) -> float` and `px(value: float) -> float` (exact inverses).
- `fit_axis(ticks: list[tuple[float, float]], *, max_resid_frac: float = 0.01, min_ticks: int = 3) -> AxisFit`
  - `ticks` = `(pixel_position, value)` pairs. Least squares straight line `value = slope * px + intercept`.
  - While the largest absolute residual is above `max_resid_frac * (max value - min value of the used ticks)`:
    drop the single tick with the largest leave one out residual and fit again. The leave one out residual of a
    tick is its absolute residual against the line fitted to the other used ticks (a plain residual is not
    enough: a misread tick at the end of the axis pulls the line towards itself). On a tie, drop the one that
    comes first in the input.
  - Raise `ChartReadError` when fewer than `min_ticks` ticks remain, or fewer than `min_ticks` distinct values
    or distinct pixel positions remain at any point (this covers an empty list).
- `top_edge_px(mask, col) -> float | None` and `line_centre_px(mask, col) -> float | None`: as defined in
  Coordinates. `None` when the column is outside the mask array or has no True pixel.
- `series_values(mask, x_values, x_axis, y_axis, *, mode="top") -> list[float | None]`
  - For each x: `col = floor(x_axis.px(x) + 1e-6)`; `mode == "top"` uses `top_edge_px`, `mode == "centre"` uses
    `line_centre_px`; the value is `y_axis.value(pixel)`, or `None` when the pixel is `None`. Other modes:
    `ValueError`.
- `parse_label_answer(text: str, n: int) -> list[str | None]`
  - The answer of the label reading model. Take the substring from the first `[` to the last `]` and parse it as
    JSON. It must be a list of objects with keys `crop` (int, 1 based) and `text` (str or null). Return a list of
    length `n` where item `i` holds the text for crop `i + 1`; crops not mentioned are `None`. Raise
    `ChartReadError` when there is no list, the JSON is invalid, an item is not an object with an int `crop`, or
    a `crop` is outside `1..n` or appears twice.
- `@dataclass(frozen=True) class ChartSpec`: `series: dict[str, str]` (series name to SAM prompt, in the order
  the areas are drawn from front to back), `x_kind: str` and `y_kind: str` (`"number"` or `"clock"`),
  `y_unit: str` (required, not empty; for example `"kwh"`), `mode: str = "top"`, `stacking: str = "overlap"`
  (`"overlap"` or `"none"`), `tick_prompt: str = "number"`, `x_values: tuple[float, ...]`.
  - `stacking == "overlap"`: filled areas all start at zero and the front ones hide the back ones, so the
    outline of series k is the union of the masks of series 0 to k (front to back). `"none"`: each series uses
    only its own mask.
  - Empty `y_unit`, empty `series`, empty `x_values` or an unknown kind, mode or stacking: `ValueError`.
- `@dataclass class ChartReading`: `values: dict[str, list[float | None]]` (series name to values at
  `spec.x_values`), `y_unit: str`, `x_axis: AxisFit`, `y_axis: AxisFit`, `ticks: list[dict]` (one dict per tick
  candidate box: `box_px`, `text`, `axis` (`"x"`, `"y"` or `None`), `value`), `plot_box_px: tuple[float, float,
  float, float]`, `sam_calls: int`, `label_calls: int`.
- `read_chart(image_png: bytes, spec: ChartSpec, segment, read_labels) -> ChartReading`
  - `segment(image_png: bytes, prompt: str) -> list[ObjectMask]` and `read_labels(crops: list[bytes]) ->
    list[str | None]` are injected (tests pass fakes; production passes the adapters below).
  - Steps:
    1. Image size from the PNG with pillow.
    2. For each series, in order: `segment(image_png, prompt)`. No object: raise `ChartReadError` naming the
       series. The series mask is the union of all returned objects.
    3. `plot_box_px` = bounding box (half-open) of the union of all series masks.
    4. `segment(image_png, spec.tick_prompt)` gives tick label candidates (their `box_px`). Crop each box from
       the image as PNG bytes: the integer region `floor(left) - 3`, `floor(top) - 3`, `ceil(right) + 3`,
       `ceil(bottom) + 3` (right and bottom excluded), clipped to the image. Call
       `read_labels` once with all crops in candidate order. A result list of the wrong length:
       `ChartReadError`.
    5. Axis of a candidate: `"y"` if its box `right <= plot left`, else `"x"` if its box `top >= plot bottom`,
       else `None`. Value: `parse_tick_label(text, y_kind or x_kind)`. Candidates with axis `None` or value
       `None` are not used.
    6. `fit_axis` on y ticks `(centre y, value)` and on x ticks `(centre x, value)` with the defaults. Errors
       propagate.
    7. Series outlines per `stacking`, then `series_values(outline, spec.x_values, x_axis, y_axis,
       mode=spec.mode)`.
  - `sam_calls` = number of `segment` calls, `label_calls` = number of `read_labels` calls.
- Adapters (thin, used in production):
  - `sam_segment_fn(client, run_id: str, *, stage: str = "chart-sam")` returns a `segment` function that sends
    one `sam-3.1` request through `client.respond(run_id, stage, input, estimate_usd=0.0025, model="sam-3.1",
    images=1, metadata={"include_confidence": "true"})` with input
    `[{"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt},
    {"type": "input_image", "image_url": "data:image/png;base64,..."}]}]`, then returns
    `parse_sam_masks(result.text, image size)`.
  - `spark_label_fn(client, run_id: str, *, stage: str = "chart-labels")` returns a `read_labels` function that
    sends one request with the default model through `client.respond(run_id, stage, input, estimate_usd=0.01,
    reasoning_effort="low")`. The input is one user message: first an `input_text` that asks for each crop's
    printed text as JSON (`[{"crop": n, "text": "..."}]`, null when a crop holds no single readable label), then
    for each crop an `input_text` `"Crop i:"` followed by its `input_image` (PNG data URL). Returns
    `parse_label_answer(result.text, len(crops))`. Zero crops: return `[]` without a call.

## Done when

`uv run pytest` passes (all tests, including T01 and T02), no test touches the network, and `AGENTS.md` rules
hold.

## Library facts (checked by the orchestrator with meta-sam-parser 0.1.0, after attempt 1)

Your sandbox cannot run Python, so these facts were measured for you. Use them directly. Do not guess the API
with `getattr`, `hasattr`, duck typing or a regex fallback parser: delete `_manual_masks`, `_split_data`,
`_try_decode`, `_rec_*`, `_mask_size`, `_is_mask_record`, `_looks_like_diags`, `_diag_parts`, `_split_finish`,
`_BOX_RE`, `_BOX_SIMPLE_RE` and `_MASK_RE`. Attempt 1 failed 2 tests because that guessing code never reached the
library's records.

```python
import meta_sam_parser as m
p = m.image_segmentation_format().create_parser()
p.push(text, emit=False)
fin = p.finish(m.CompletedOutcome())      # ParserFinish, fields: events, result
res = fin.result                          # ImageSegmentationResult, fields: media, revision, records,
                                          #   diagnostics (tuple), raw_output, outcome
for d in res.diagnostics:                 # SegmentationDiagnostic: severity ("warning" or "error"), code,
    ...                                   #   message, line, raw
for rec in res.records:                   # SegmentationBoxRecord or SegmentationMaskRecord
    isinstance(rec, m.SegmentationMaskRecord)
    # SegmentationMaskRecord fields: kind ("mask"), order, object_id (str), identity, revision,
    #   mask (SegmentationMask: encoding, payload, width, height), bounds (SegmentationMaskBounds: left, top,
    #   right, bottom; right and bottom excluded), frame, confidence (float or None)
    raster = m.decode_mask_to_raster(rec.mask)   # bytes, len == mask.width * mask.height, row major
```

Measured on `tests/fixtures/sam_control_squares.txt`: records are Box, Mask, Box, Mask, Box, Mask; diagnostics
is empty; the second record has object_id "0", bounds (60, 80, 241, 261), mask encoding "lossless", width 181,
height 181, confidence None, raster length 32761. An empty text gives no records and no diagnostics.
