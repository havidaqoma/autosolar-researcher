"""Read chart numbers from SAM masks and tick labels. Lengths in px, money in USD."""

from __future__ import annotations

import base64
import io
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable

import meta_sam_parser
import numpy as np
from PIL import Image


class ChartReadError(ValueError):
    """Raised when a chart cannot be read. Text in str."""


@dataclass(frozen=True)
class ObjectMask:
    """One SAM object. Mask in bool, box in px, confidence in score."""

    object_id: str
    mask: np.ndarray
    box_px: tuple[float, float, float, float]
    confidence: float | None


@dataclass(frozen=True)
class AxisFit:
    """Linear axis map. Pixels in px, values in axis units."""

    slope: float
    intercept: float
    used: tuple[int, ...]
    dropped: tuple[int, ...]
    max_resid: float

    def value(self, px: float) -> float:
        """Map pixel to axis value. Input in px, output in axis units."""
        return self.slope * px + self.intercept

    def px(self, value: float) -> float:
        """Map axis value to pixel. Input in axis units, output in px."""
        return (value - self.intercept) / self.slope


_NUMBER_RE = re.compile(r"-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?")
_CLOCK_RE = re.compile(r"(\d{1,2}):(\d{2})")


def parse_tick_label(text: str | None, kind: str) -> float | None:
    """Parse one tick label. Input in str, output in axis units."""
    if kind == "number":
        if text is None:
            return None
        s = text.strip()
        if not s:
            return None
        if not _NUMBER_RE.fullmatch(s):
            return None
        return float(s.replace(",", ""))
    if kind == "clock":
        if text is None:
            return None
        s = text.strip()
        m = _CLOCK_RE.fullmatch(s)
        if not m:
            return None
        h = int(m.group(1))
        mins = int(m.group(2))
        if h < 0 or h > 24 or mins < 0 or mins >= 60:
            return None
        if h == 24 and mins != 0:
            return None
        return h + mins / 60.0
    raise ValueError("unknown tick kind: " + str(kind))


def _line_fit(px_list: list[float], val_list: list[float]) -> tuple[float, float]:
    """Least squares line. Pixels in px, values in axis units."""
    px_arr = np.asarray(px_list, dtype=float)
    val_arr = np.asarray(val_list, dtype=float)
    coef = np.polyfit(px_arr, val_arr, 1)
    return float(coef[0]), float(coef[1])


def fit_axis(
    ticks: list[tuple[float, float]],
    *,
    max_resid_frac: float = 0.01,
    min_ticks: int = 3,
) -> AxisFit:
    """Fit value per px line with outlier drops. Pixels in px."""
    if len(ticks) < min_ticks:
        raise ChartReadError("need at least " + str(min_ticks) + " ticks")
    used: list[int] = list(range(len(ticks)))
    dropped: list[int] = []
    while True:
        if len(used) < min_ticks:
            raise ChartReadError("too few ticks remain")
        pxs = [float(ticks[i][0]) for i in used]
        vals = [float(ticks[i][1]) for i in used]
        if len(set(pxs)) < min_ticks or len(set(vals)) < min_ticks:
            raise ChartReadError("too few distinct ticks")
        slope, icept = _line_fit(pxs, vals)
        resids = [abs(v - (slope * p + icept)) for p, v in zip(pxs, vals)]
        top_resid = max(resids)
        span = max(vals) - min(vals)
        if top_resid <= max_resid_frac * span:
            order = sorted(used)
            return AxisFit(
                slope=slope,
                intercept=icept,
                used=tuple(order),
                dropped=tuple(sorted(dropped)),
                max_resid=float(top_resid),
            )
        if len(used) <= min_ticks:
            # Dropping one more would leave too few.
            loo = _loo_resids(ticks, used)
            best = max(loo[i] for i in used)
            cands = [i for i in used if loo[i] == best]
            dropped.append(min(cands))
            raise ChartReadError("ticks do not agree")
        loo = _loo_resids(ticks, used)
        best = max(loo[i] for i in used)
        cands = [i for i in used if loo[i] == best]
        pick = min(cands)
        used.remove(pick)
        dropped.append(pick)


def _loo_resids(
    ticks: list[tuple[float, float]], used: list[int]
) -> dict[int, float]:
    """Leave one out residual per tick. Pixels in px, output in axis units."""
    out: dict[int, float] = {}
    for i in used:
        others = [j for j in used if j != i]
        pxs = [float(ticks[j][0]) for j in others]
        vals = [float(ticks[j][1]) for j in others]
        if len(others) >= 2 and len(set(pxs)) >= 2:
            s, b = _line_fit(pxs, vals)
            pred = s * float(ticks[i][0]) + b
        elif others:
            # Single other point: residual is absolute value gap.
            pred = float(ticks[others[0]][1])
        else:
            pred = float(ticks[i][1])
        out[i] = abs(float(ticks[i][1]) - pred)
    return out


def top_edge_px(mask: np.ndarray, col: int) -> float | None:
    """Top filled pixel side in a column. Input in px, output in px."""
    if mask.ndim != 2:
        return None
    h_px, w_px = mask.shape
    c = int(col)
    if c != col or c < 0 or c >= w_px:
        return None
    rows = np.nonzero(mask[:, c])[0]
    if rows.size == 0:
        return None
    return float(int(rows.min()))


def line_centre_px(mask: np.ndarray, col: int) -> float | None:
    """Mean row centre of a line in a column. Input in px, output in px."""
    if mask.ndim != 2:
        return None
    h_px, w_px = mask.shape
    c = int(col)
    if c != col or c < 0 or c >= w_px:
        return None
    rows = np.nonzero(mask[:, c])[0]
    if rows.size == 0:
        return None
    return float(np.mean(rows)) + 0.5


def series_values(
    mask: np.ndarray,
    x_values: list[float] | tuple[float, ...],
    x_axis: AxisFit,
    y_axis: AxisFit,
    *,
    mode: str = "top",
) -> list[float | None]:
    """Sample one outline at axis values. Pixels in px."""
    if mode not in ("top", "centre"):
        raise ValueError("unknown mode: " + str(mode))
    out: list[float | None] = []
    for x in x_values:
        col_px = math.floor(x_axis.px(float(x)) + 1e-6)
        pix: float | None
        if mode == "top":
            pix = top_edge_px(mask, col_px)
        else:
            pix = line_centre_px(mask, col_px)
        out.append(None if pix is None else y_axis.value(pix))
    return out


def parse_label_answer(text: str, n: int) -> list[str | None]:
    """Parse label model answer. Counts in crops, output in str."""
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0 or end < start:
        raise ChartReadError("label answer holds no list")
    try:
        data = json.loads(text[start : end + 1])
    except Exception as exc:
        raise ChartReadError("label answer is not JSON") from exc
    if not isinstance(data, list):
        raise ChartReadError("label answer holds no list")
    out: list[str | None] = [None] * n
    seen: set[int] = set()
    for item in data:
        if not isinstance(item, dict):
            raise ChartReadError("label item is not an object")
        if "crop" not in item or "text" not in item:
            raise ChartReadError("label item needs crop and text")
        crop = item["crop"]
        val = item["text"]
        if type(crop) is not int:
            raise ChartReadError("label crop is not an int")
        if crop < 1 or crop > n:
            raise ChartReadError("label crop out of range")
        if crop in seen:
            raise ChartReadError("label crop appears twice")
        if val is not None and not isinstance(val, str):
            raise ChartReadError("label text must be str or null")
        seen.add(crop)
        out[crop - 1] = val
    return out


@dataclass(frozen=True)
class ChartSpec:
    """Chart read plan. Pixels in px, values in axis units."""

    series: dict[str, str]
    x_kind: str
    y_kind: str
    y_unit: str
    mode: str = "top"
    stacking: str = "overlap"
    tick_prompt: str = "number"
    x_values: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        """Check the plan. Raises ValueError on bad input."""
        if not isinstance(self.y_unit, str) or self.y_unit == "":
            raise ValueError("y_unit is required")
        if not self.series:
            raise ValueError("series is required")
        if len(self.x_values) == 0:
            raise ValueError("x_values is required")
        if self.x_kind not in ("number", "clock"):
            raise ValueError("unknown x_kind: " + str(self.x_kind))
        if self.y_kind not in ("number", "clock"):
            raise ValueError("unknown y_kind: " + str(self.y_kind))
        if self.mode not in ("top", "centre"):
            raise ValueError("unknown mode: " + str(self.mode))
        if self.stacking not in ("overlap", "none"):
            raise ValueError("unknown stacking: " + str(self.stacking))


@dataclass
class ChartReading:
    """Numbers read from one chart. Pixels in px."""

    values: dict[str, list[float | None]]
    y_unit: str
    x_axis: AxisFit
    y_axis: AxisFit
    ticks: list[dict]
    plot_box_px: tuple[float, float, float, float]
    sam_calls: int
    label_calls: int


def _png_size(image_png: bytes) -> tuple[int, int]:
    """PNG size. Input in bytes, output in px."""
    with Image.open(io.BytesIO(image_png)) as img:
        return int(img.size[0]), int(img.size[1])


def read_chart(
    image_png: bytes,
    spec: ChartSpec,
    segment: Callable[[bytes, str], list[ObjectMask]],
    read_labels: Callable[[list[bytes]], list[str | None]],
) -> ChartReading:
    """Run the chart pipeline. Pixels in px, values in axis units."""
    w_px, h_px = _png_size(image_png)
    sam_calls = 0
    label_calls = 0
    masks: dict[str, np.ndarray] = {}
    order: list[str] = list(spec.series.keys())
    for name in order:
        prompt = spec.series[name]
        objs = segment(image_png, prompt)
        sam_calls += 1
        if not objs:
            raise ChartReadError("series not found: " + str(name))
        union = np.zeros((h_px, w_px), dtype=bool)
        for o in objs:
            union = union | np.asarray(o.mask, dtype=bool)
        masks[name] = union
    union_all = np.zeros((h_px, w_px), dtype=bool)
    for name in order:
        union_all = union_all | masks[name]
    rows, cols = np.nonzero(union_all)
    if rows.size == 0:
        raise ChartReadError("empty plot")
    left_px = float(int(cols.min()))
    top_px = float(int(rows.min()))
    right_px = float(int(cols.max()) + 1)
    bottom_px = float(int(rows.max()) + 1)
    plot_box = (left_px, top_px, right_px, bottom_px)
    with Image.open(io.BytesIO(image_png)) as img:
        full = img.convert("RGB")
        cands = segment(image_png, spec.tick_prompt)
        sam_calls += 1
        crops: list[bytes] = []
        for o in cands:
            l, t, r, b = o.box_px
            x0 = max(0, math.floor(float(l)) - 3)
            y0 = max(0, math.floor(float(t)) - 3)
            x1 = min(w_px, math.ceil(float(r)) + 3)
            y1 = min(h_px, math.ceil(float(b)) + 3)
            if x1 <= x0 or y1 <= y0:
                raise ChartReadError("tick box outside image")
            part = full.crop((x0, y0, x1, y1))
            buf = io.BytesIO()
            part.save(buf, format="PNG")
            crops.append(buf.getvalue())
        texts = read_labels(crops)
        label_calls += 1
    if len(texts) != len(cands):
        raise ChartReadError("label count mismatch")
    ticks: list[dict] = []
    for o, txt in zip(cands, texts):
        l, t, r, b = (float(v) for v in o.box_px)
        if r <= left_px:
            axis: str | None = "y"
            val = parse_tick_label(txt, spec.y_kind)
        elif t >= bottom_px:
            axis = "x"
            val = parse_tick_label(txt, spec.x_kind)
        else:
            axis = None
            val = None
        ticks.append({"box_px": o.box_px, "text": txt, "axis": axis, "value": val})
    y_ticks = [
        ((float(d["box_px"][1]) + float(d["box_px"][3])) / 2.0, float(d["value"]))
        for d in ticks
        if d["axis"] == "y" and d["value"] is not None
    ]
    x_ticks = [
        ((float(d["box_px"][0]) + float(d["box_px"][2])) / 2.0, float(d["value"]))
        for d in ticks
        if d["axis"] == "x" and d["value"] is not None
    ]
    y_axis = fit_axis(y_ticks)
    x_axis = fit_axis(x_ticks)
    outlines: dict[str, np.ndarray] = {}
    if spec.stacking == "overlap":
        acc = np.zeros((h_px, w_px), dtype=bool)
        for name in order:
            acc = acc | masks[name]
            outlines[name] = acc.copy()
    else:
        for name in order:
            outlines[name] = masks[name]
    values: dict[str, list[float | None]] = {}
    for name in order:
        values[name] = series_values(
            outlines[name], spec.x_values, x_axis, y_axis, mode=spec.mode
        )
    return ChartReading(
        values=values,
        y_unit=spec.y_unit,
        x_axis=x_axis,
        y_axis=y_axis,
        ticks=ticks,
        plot_box_px=plot_box,
        sam_calls=sam_calls,
        label_calls=label_calls,
    )


def sam_segment_fn(
    client: Any, run_id: str, *, stage: str = "chart-sam"
) -> Callable[[bytes, str], list[ObjectMask]]:
    """Build a segment function on sam-3.1. Money in USD, images in images."""

    def segment(image_png: bytes, prompt: str) -> list[ObjectMask]:
        url = "data:image/png;base64," + base64.b64encode(image_png).decode("ascii")
        content = [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": url},
        ]
        model_input = [{"type": "message", "role": "user", "content": content}]
        result = client.respond(
            run_id,
            stage,
            model_input,
            estimate_usd=0.0025,
            model="sam-3.1",
            images=1,
            metadata={"include_confidence": "true"},
        )
        w_px, h_px = _png_size(image_png)
        return parse_sam_masks(result.text, (w_px, h_px))

    return segment


def spark_label_fn(
    client: Any, run_id: str, *, stage: str = "chart-labels"
) -> Callable[[list[bytes]], list[str | None]]:
    """Build a crop label function. Money in USD."""

    def read_labels(crops: list[bytes]) -> list[str | None]:
        if len(crops) == 0:
            return []
        ask = (
            "Return the printed text of each crop as JSON: "
            '[{"crop": n, "text": "..."}] with null '
            "when a crop holds no single readable label."
        )
        content: list[dict] = [{"type": "input_text", "text": ask}]
        for i, png in enumerate(crops, start=1):
            url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
            content.append({"type": "input_text", "text": "Crop " + str(i) + ":"})
            content.append({"type": "input_image", "image_url": url})
        model_input = [{"type": "message", "role": "user", "content": content}]
        result = client.respond(
            run_id,
            stage,
            model_input,
            estimate_usd=0.01,
            reasoning_effort="low",
        )
        return parse_label_answer(result.text, len(crops))

    return read_labels


# SAM mask parsing


def parse_sam_masks(text: str, image_wh: tuple[int, int]) -> list[ObjectMask]:
    """Parse SAM output into full image masks. Sizes in px."""
    w_px, h_px = int(image_wh[0]), int(image_wh[1])
    fmt = meta_sam_parser.image_segmentation_format()
    parser = fmt.create_parser()
    parser.push(text, emit=False)
    fin = parser.finish(meta_sam_parser.CompletedOutcome())
    res = fin.result
    for diag in res.diagnostics:
        if diag.severity == "error":
            raise ChartReadError(str(diag.code) + ": " + str(diag.message))
    masks: list[ObjectMask] = []
    for rec in res.records:
        if not isinstance(rec, meta_sam_parser.SegmentationMaskRecord):
            continue
        left = float(rec.bounds.left)
        top = float(rec.bounds.top)
        right = float(rec.bounds.right)
        bottom = float(rec.bounds.bottom)
        mw_px = int(rec.mask.width)
        mh_px = int(rec.mask.height)
        raster = meta_sam_parser.decode_mask_to_raster(rec.mask)
        buf = bytes(raster)
        if len(buf) != mw_px * mh_px:
            raise ChartReadError("mask raster size mismatch")
        if left < 0 or top < 0 or right > w_px or bottom > h_px:
            raise ChartReadError("mask bounds outside image")
        if left + mw_px > w_px or top + mh_px > h_px:
            raise ChartReadError("mask raster outside image")
        cells = np.frombuffer(buf, dtype=np.uint8).reshape(mh_px, mw_px) != 0
        full = np.zeros((h_px, w_px), dtype=bool)
        full[int(top): int(top) + mh_px, int(left): int(left) + mw_px] = cells
        conf = rec.confidence
        masks.append(
            ObjectMask(
                object_id=str(rec.object_id),
                mask=full,
                box_px=(left, top, right, bottom),
                confidence=None if conf is None else float(conf),
            )
        )
    return masks
