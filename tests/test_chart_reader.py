"""Acceptance tests for T03 (docs/specs/T03_chart_reader.md). Written by the orchestrator before the code."""
import base64
import io
import json
import math
import pathlib
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from autosolar.chart_reader import (AxisFit, ChartReadError, ChartReading, ChartSpec, ObjectMask, fit_axis,
                                    line_centre_px, parse_label_answer, parse_sam_masks, parse_tick_label,
                                    read_chart, sam_segment_fn, series_values, spark_label_fn, top_edge_px,
                                    CHART_READER_VALIDATION, point_status)

FIX = pathlib.Path(__file__).parent / "fixtures"


# ---------- parse_sam_masks: real SAM 3.1 output for a synthetic image with 3 red squares ----------

def control_text():
    return (FIX / "sam_control_squares.txt").read_text(encoding="ascii")


def test_parse_real_sam_output_three_squares():
    objs = parse_sam_masks(control_text(), (900, 600))
    assert [o.object_id for o in objs] == ["0", "1", "2"]
    assert [o.box_px for o in objs] == [(60, 80, 241, 261), (620, 80, 801, 261), (340, 340, 521, 521)]
    for o in objs:
        assert o.mask.shape == (600, 900) and o.mask.dtype == bool
        left, top, right, bottom = o.box_px
        rows, cols = np.nonzero(o.mask)
        assert rows.min() >= top and rows.max() < bottom and cols.min() >= left and cols.max() < right
        assert o.mask.sum() > 0.98 * 181 * 181
        assert o.confidence is None
    assert not objs[0].mask[0:80, :].any() and not objs[0].mask[:, 241:].any()


def test_parse_mask_outside_image_raises():
    with pytest.raises(ChartReadError):
        parse_sam_masks(control_text(), (300, 300))


def test_parse_no_objects_gives_empty_list():
    assert parse_sam_masks("", (900, 600)) == []
    assert parse_sam_masks("no objects found", (900, 600)) == []


# ---------- parse_tick_label ----------

@pytest.mark.parametrize("text,value", [("1400", 1400.0), ("1,400", 1400.0), (" 200 ", 200.0), ("0", 0.0),
                                        ("-2.5", -2.5), ("12,345.5", 12345.5)])
def test_tick_number_ok(text, value):
    assert parse_tick_label(text, "number") == value


@pytest.mark.parametrize("text", ["2022.", "1,40", "12:00", "", None, "kWh", "1 400", "1,4000"])
def test_tick_number_rejects(text):
    assert parse_tick_label(text, "number") is None


@pytest.mark.parametrize("text,value", [("14:00", 14.0), ("0:30", 0.5), ("0:00", 0.0), ("24:00", 24.0),
                                        ("08:15", 8.25)])
def test_tick_clock_ok(text, value):
    assert parse_tick_label(text, "clock") == pytest.approx(value)


@pytest.mark.parametrize("text", ["24:30", "25:00", "8:60", "1400", "8.00", None, "8:0"])
def test_tick_clock_rejects(text):
    assert parse_tick_label(text, "clock") is None


def test_tick_unknown_kind():
    with pytest.raises(ValueError):
        parse_tick_label("1", "date")


# ---------- fit_axis ----------

def test_fit_exact_line_and_inverse():
    ticks = [(250.0, 0.0), (200.0, 100.0), (150.0, 200.0), (100.0, 300.0)]
    f = fit_axis(ticks)
    assert isinstance(f, AxisFit)
    assert f.slope == pytest.approx(-2.0) and f.intercept == pytest.approx(500.0)
    assert f.used == (0, 1, 2, 3) and f.dropped == ()
    assert f.max_resid == pytest.approx(0.0, abs=1e-9)
    assert f.value(125.0) == pytest.approx(250.0)
    assert f.px(250.0) == pytest.approx(125.0)


def test_fit_drops_misread_tick():
    ticks = [(250.0, 0.0), (200.0, 100.0), (150.0, 200.0), (100.0, 300.0), (50.0, 4000.0)]
    f = fit_axis(ticks)
    assert f.dropped == (4,) and f.used == (0, 1, 2, 3)
    assert f.value(50.0) == pytest.approx(400.0)


def test_fit_keeps_small_noise():
    ticks = [(0.0, 0.0), (36.0, 1.0), (72.2, 2.0), (108.0, 3.0), (143.9, 4.0)]
    f = fit_axis(ticks)
    assert f.dropped == () and f.max_resid <= 0.01 * 4.0


@pytest.mark.parametrize("ticks", [[], [(1.0, 1.0), (2.0, 2.0)], [(1.0, 5.0), (2.0, 5.0), (3.0, 5.0)],
                                   [(1.0, 1.0), (1.0, 2.0), (1.0, 3.0)]])
def test_fit_too_few_raises(ticks):
    with pytest.raises(ChartReadError):
        fit_axis(ticks)


def test_fit_raises_when_dropping_leaves_too_few():
    with pytest.raises(ChartReadError):
        fit_axis([(0.0, 0.0), (10.0, 100.0), (20.0, 5.0), (30.0, 900.0)])


# ---------- edges and series ----------

def block_mask():
    m = np.zeros((10, 8), bool)
    m[3:10, 2] = True      # area from row 3 down
    m[4:7, 4] = True       # line rows 4, 5, 6
    return m


def test_top_edge_and_line_centre():
    m = block_mask()
    assert top_edge_px(m, 2) == 3.0
    assert line_centre_px(m, 4) == pytest.approx(5.5)
    assert top_edge_px(m, 0) is None and line_centre_px(m, 0) is None
    assert top_edge_px(m, 8) is None and top_edge_px(m, -1) is None


def test_series_values_modes():
    m = block_mask()
    x_axis = AxisFit(slope=1.0, intercept=0.0, used=(0, 1), dropped=(), max_resid=0.0)
    y_axis = AxisFit(slope=-10.0, intercept=100.0, used=(0, 1), dropped=(), max_resid=0.0)
    assert series_values(m, [2.5, -4.0], x_axis, y_axis) == [pytest.approx(70.0), None]
    assert series_values(m, [4.9], x_axis, y_axis, mode="centre") == [pytest.approx(45.0)]
    with pytest.raises(ValueError):
        series_values(m, [2.0], x_axis, y_axis, mode="bottom")


# ---------- revision T03c: edge columns and box local rasters ----------

def edge_mask():
    m = np.zeros((20, 20), bool)
    m[8:20, 5:15] = True      # filled area, columns 5..14, top row 8
    m[19, 4] = True           # one pixel anti aliasing sliver left of the area
    return m


IDENT_X = AxisFit(slope=1.0, intercept=0.0, used=(0, 1), dropped=(), max_resid=0.0)
ROW_Y = AxisFit(slope=-1.0, intercept=20.0, used=(0, 1), dropped=(), max_resid=0.0)   # value = 20 - row


def test_edge_column_skips_sliver_and_uses_nearest_usable():
    m = edge_mask()
    # c0 = 3 is empty; column 4 is a 1 px sliver (below 0.25 * 12); column 5 is the nearest usable one
    assert series_values(m, [3.2], IDENT_X, ROW_Y) == [pytest.approx(12.0)]
    # c0 = 17 is empty; column 14 (3 to the left) is usable
    assert series_values(m, [17.5], IDENT_X, ROW_Y) == [pytest.approx(12.0)]
    # c0 = 18: the window 15..21 holds no True pixel
    assert series_values(m, [18.0], IDENT_X, ROW_Y) == [None]
    # c0 = 4 is not empty (the sliver itself), so it is used as is
    assert series_values(m, [4.0], IDENT_X, ROW_Y) == [pytest.approx(1.0)]


def test_edge_column_tie_takes_left_and_window_limit():
    m = np.zeros((20, 20), bool)
    m[3:20, 2] = True
    m[7:20, 6] = True
    assert series_values(m, [4.0], IDENT_X, ROW_Y) == [pytest.approx(17.0)]       # left column 2, top row 3
    m2 = np.zeros((20, 20), bool)
    m2[3:20, 10] = True
    assert series_values(m2, [6.0], IDENT_X, ROW_Y) == [None]                     # 4 columns away: outside
    assert series_values(m2, [7.0], IDENT_X, ROW_Y) == [pytest.approx(17.0)]      # 3 columns away: inside


def test_edge_column_centre_mode():
    m = np.zeros((20, 20), bool)
    m[4:7, 8] = True       # line rows 4..6, centre 5.5
    assert series_values(m, [9.5], IDENT_X, ROW_Y, mode="centre") == [pytest.approx(14.5)]


def test_parse_stretches_box_local_raster():
    # Real SAM 3.1 output for tests/fixtures/wide_rect.png (1600 x 500): a red rectangle covering columns
    # 100..1499 and rows 100..399. SAM sent a 1024 x 218 raster for a 1398 x 298 box.
    text = (FIX / "sam_wide_rect.txt").read_text(encoding="ascii")
    objs = parse_sam_masks(text, (1600, 500))
    assert len(objs) == 1
    o = objs[0]
    assert o.mask.shape == (500, 1600) and o.mask.dtype == bool
    assert o.box_px == (101, 101, 1499, 399)
    truth = np.zeros((500, 1600), bool)
    truth[100:400, 100:1500] = True
    iou = np.logical_and(o.mask, truth).sum() / np.logical_or(o.mask, truth).sum()
    assert iou >= 0.98
    assert not o.mask[:, :101].any() and not o.mask[:, 1499:].any()
    assert not o.mask[:101, :].any() and not o.mask[399:, :].any()


# ---------- parse_label_answer ----------

def test_label_answer_fenced_and_missing():
    text = 'Sure.\n```json\n[{"crop": 2, "text": "1,200"}, {"crop": 1, "text": null}]\n```'
    assert parse_label_answer(text, 3) == [None, "1,200", None]


@pytest.mark.parametrize("text", ["no list here", "[{\"crop\": 1, \"text\": \"a\"},]", "[{\"crop\": 4}]",
                                  "[{\"crop\": 0, \"text\": \"a\"}]", "[1, 2]",
                                  "[{\"crop\": 1, \"text\": \"a\"}, {\"crop\": 1, \"text\": \"b\"}]",
                                  "[{\"crop\": \"1\", \"text\": \"a\"}]"])
def test_label_answer_errors(text):
    with pytest.raises(ChartReadError):
        parse_label_answer(text, 3)


# ---------- ChartSpec ----------

def spec(**kw):
    base = dict(series={"A": "blue area", "B": "orange area"}, x_kind="clock", y_kind="number", y_unit="kwh",
                x_values=tuple(float(h) for h in range(10)))
    base.update(kw)
    return ChartSpec(**base)


@pytest.mark.parametrize("kw", [dict(y_unit=""), dict(series={}), dict(x_values=()), dict(x_kind="date"),
                                dict(mode="bottom"), dict(stacking="stacked")])
def test_chartspec_rejects(kw):
    with pytest.raises(ValueError):
        spec(**kw)


# ---------- read_chart on a synthetic chart with known values ----------
# Image 400 x 300. x: hour h at column 50 + 30 h. y: value = 500 - 2 * row (row 250 is 0, row 50 is 400).
# Both series span columns 40 to 349. Series A (front): top row 150 everywhere (value 200). Series B (behind):
# top row 100 + 3 * ((col - 35) // 30) for col < 305 (constant within 15 px of each hour column, value 300 - 6 h),
# equal to A from col 305 on (B fully hidden there). Steps sit between hour columns, so float rounding in
# x_axis.px cannot move a sample onto a different step.

W, H = 400, 300


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (W, H), "white").save(buf, format="PNG")
    return buf.getvalue()


def mask_from_tops(tops):
    m = np.zeros((H, W), bool)
    for col, top in tops.items():
        m[top:250, col] = True
    return m


def series_masks():
    top_a = {c: 150 for c in range(40, 350)}
    top_b = {c: (100 + 3 * ((c - 35) // 30) if c < 305 else 150) for c in range(40, 350)}
    a = mask_from_tops(top_a)
    b_visible = np.zeros((H, W), bool)
    for c in range(40, 350):
        b_visible[top_b[c]:top_a[c], c] = True
    return a, b_visible


def tick_objects():
    objs = []
    for py in (250, 200, 150, 100, 50):        # y labels left of the plot, values 0..400
        objs.append((5, py - 6, 35, py + 6))
    for h in (0, 2, 4, 6, 8, 10):              # x labels under the plot
        c = 50 + 30 * h
        objs.append((c - 12, 260, c + 12, 274))
    objs.append((200, 20, 230, 35))            # text inside the figure, not a tick
    out = []
    for i, box in enumerate(objs):
        m = np.zeros((H, W), bool)
        m[box[1]:box[3], box[0]:box[2]] = True
        out.append(ObjectMask(object_id=str(i), mask=m, box_px=tuple(float(v) for v in box), confidence=0.6))
    return out


TICK_TEXTS = ["0", "100", "200", "300", "4000", "0:00", "2:00", "4:00", "6:00", "8:00", "10:00", "2022."]


class Fakes:
    def __init__(self, labels=None, empty_series=None):
        a, b = series_masks()
        self.by_prompt = {"blue area": [ObjectMask("0", a, (40.0, 150.0, 350.0, 250.0), 0.9)],
                          "orange area": [ObjectMask("0", b, (40.0, 100.0, 305.0, 150.0), 0.8)],
                          "number": tick_objects()}
        if empty_series:
            self.by_prompt[empty_series] = []
        self.labels = TICK_TEXTS if labels is None else labels
        self.segment_prompts = []
        self.crops = []

    def segment(self, image_png, prompt):
        self.segment_prompts.append(prompt)
        return self.by_prompt[prompt]

    def read_labels(self, crops):
        self.crops.append(crops)
        return list(self.labels)


def test_read_chart_overlap_values():
    f = Fakes()
    r = read_chart(png_bytes(), spec(), f.segment, f.read_labels)
    assert isinstance(r, ChartReading)
    assert r.y_unit == "kwh"
    assert r.values["A"] == [pytest.approx(200.0)] * 10
    assert r.values["B"] == [pytest.approx(300.0 - 6 * h) for h in range(9)] + [pytest.approx(200.0)]
    assert r.plot_box_px == (40, 100, 350, 250)
    assert r.y_axis.dropped == (4,)
    assert r.x_axis.slope == pytest.approx(1 / 30)
    assert [t["axis"] for t in r.ticks] == ["y"] * 5 + ["x"] * 6 + [None]
    assert r.ticks[4]["value"] == 4000.0 and r.ticks[11]["value"] is None
    assert r.sam_calls == 3 and r.label_calls == 1
    assert f.segment_prompts == ["blue area", "orange area", "number"]


def test_read_chart_crops_are_padded_pngs():
    f = Fakes()
    read_chart(png_bytes(), spec(), f.segment, f.read_labels)
    crops = f.crops[0]
    assert len(crops) == 12
    first = Image.open(io.BytesIO(crops[0]))
    assert first.format == "PNG" and first.size == (30 + 6, 12 + 6)


def test_read_chart_no_stacking_leaves_hidden_part_empty():
    f = Fakes()
    r = read_chart(png_bytes(), spec(stacking="none"), f.segment, f.read_labels)
    assert r.values["B"][9] is None
    assert r.values["B"][0] == pytest.approx(300.0)


def test_read_chart_series_not_found():
    f = Fakes(empty_series="orange area")
    with pytest.raises(ChartReadError, match="B"):
        read_chart(png_bytes(), spec(), f.segment, f.read_labels)


def test_read_chart_label_count_mismatch():
    f = Fakes(labels=TICK_TEXTS[:-1])
    with pytest.raises(ChartReadError):
        read_chart(png_bytes(), spec(), f.segment, f.read_labels)


def test_read_chart_too_few_y_ticks():
    texts = list(TICK_TEXTS)
    texts[0:5] = ["0", "x", "y", "z", "w"]
    f = Fakes(labels=texts)
    with pytest.raises(ChartReadError):
        read_chart(png_bytes(), spec(), f.segment, f.read_labels)


# ---------- adapters with a fake client ----------

class FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def respond(self, run_id, stage, input, **kw):
        self.calls.append({"run_id": run_id, "stage": stage, "input": input, **kw})
        return SimpleNamespace(text=self.text, cost_usd=0.0)


def test_sam_adapter_request_and_parse():
    client = FakeClient(control_text())
    seg = sam_segment_fn(client, "run-1")
    png = (FIX / "control_squares.png").read_bytes()
    objs = seg(png, "red square")
    assert len(objs) == 3 and objs[0].mask.shape == (600, 900)
    c = client.calls[0]
    assert c["run_id"] == "run-1" and c["stage"] == "chart-sam"
    assert c["model"] == "sam-3.1" and c["images"] == 1 and c["estimate_usd"] == 0.0025
    assert c["metadata"] == {"include_confidence": "true"}
    content = c["input"][0]["content"]
    assert c["input"][0]["role"] == "user"
    assert content[0] == {"type": "input_text", "text": "red square"}
    assert content[1]["type"] == "input_image"
    url = content[1]["image_url"]
    assert url.startswith("data:image/png;base64,") and base64.b64decode(url.split(",", 1)[1]) == png


def test_spark_adapter_request_and_parse():
    client = FakeClient('```json\n[{"crop": 1, "text": "200"}, {"crop": 2, "text": null}]\n```')
    read = spark_label_fn(client, "run-1")
    crops = [png_bytes(), png_bytes()]
    assert read(crops) == ["200", None]
    c = client.calls[0]
    assert c["stage"] == "chart-labels" and c["estimate_usd"] == 0.01 and c["reasoning_effort"] == "low"
    assert c.get("model", "muse-spark-1.3-contributor") == "muse-spark-1.3-contributor"
    assert c.get("images", 0) == 0
    content = c["input"][0]["content"]
    assert len(content) == 1 + 2 * 2
    assert content[0]["type"] == "input_text" and "json" in content[0]["text"].lower()
    assert content[1] == {"type": "input_text", "text": "Crop 1:"}
    assert content[2]["type"] == "input_image" and content[2]["image_url"].startswith("data:image/png;base64,")
    assert content[3] == {"type": "input_text", "text": "Crop 2:"}


def test_spark_adapter_zero_crops_no_call():
    client = FakeClient("[]")
    assert spark_label_fn(client, "run-1")([]) == []
    assert client.calls == []


def test_axisfit_inverse_round_trip():
    f = AxisFit(slope=0.0277, intercept=-16.0, used=(0, 1, 2), dropped=(), max_resid=0.0)
    for px in (0.0, 577.5, 1405.25):
        assert f.px(f.value(px)) == pytest.approx(px)
    assert not math.isnan(f.value(1.0))
    json.dumps({"slope": f.slope})


# ---------- revision T03d: point status and the validation record ----------

def test_point_status_basic_and_none_wins():
    xs = (0.0, 1.0, 2.0, 3.0, 4.0)
    assert point_status(xs, [1.0, None, 2.0, 3.0, 4.0]) == [
        "edge_not_validated", "not_read", "validated", "validated", "edge_not_validated"]
    assert point_status(xs, [None, 1.0, 2.0, 3.0, None]) == [
        "not_read", "validated", "validated", "validated", "not_read"]


def test_point_status_unordered_and_repeated_edges():
    assert point_status([5.0, 1.0, 3.0], [1.0, 2.0, 3.0]) == ["edge_not_validated", "edge_not_validated", "validated"]
    assert point_status([1.0, 1.0, 2.0, 3.0, 3.0], [0.1] * 5) == ["edge_not_validated"] * 2 + ["validated"] + [
        "edge_not_validated"] * 2
    assert point_status([7.0], [2.0]) == ["edge_not_validated"]


@pytest.mark.parametrize("xs, vals", [((), []), ((1.0, 2.0), [1.0]), ((1.0,), [1.0, 2.0])])
def test_point_status_rejects(xs, vals):
    with pytest.raises(ValueError):
        point_status(xs, vals)


def test_read_chart_fills_point_status():
    f = Fakes()
    r = read_chart(png_bytes(), spec(), f.segment, f.read_labels)
    assert set(r.point_status) == {"A", "B"}
    assert r.point_status["A"] == ["edge_not_validated"] + ["validated"] * 8 + ["edge_not_validated"]
    r2 = read_chart(png_bytes(), spec(stacking="none"), f.segment, f.read_labels)
    assert r2.point_status["B"][9] == "not_read"
    assert r2.point_status["B"][0] == "edge_not_validated"
    assert r2.point_status["B"][1:9] == ["validated"] * 8


def test_chartreading_point_status_has_default():
    fit = AxisFit(slope=1.0, intercept=0.0, used=(0, 1), dropped=(), max_resid=0.0)
    r = ChartReading(values={}, y_unit="kwh", x_axis=fit, y_axis=fit, ticks=[], plot_box_px=(0.0, 0.0, 1.0, 1.0),
                     sam_calls=0, label_calls=0)
    assert r.point_status == {}


def test_validation_record_matches_saved_v3_results():
    root = pathlib.Path(__file__).resolve().parents[1]
    v = CHART_READER_VALIDATION
    assert v["source"] == "docs/smoke/chart_validation_v3.json" and v["rules_commit"] == "31a1bf1"
    d = json.loads((root / v["source"]).read_text(encoding="utf-8"))
    inner, edge = [], []
    for row in d["v3a"]:
        for s in row["series"].values():
            e = s["err_frac"]
            for i, x in enumerate(e):
                (edge if i in (0, len(e) - 1) else inner).append(x)
    inner.sort()
    n = len(inner)
    median = inner[n // 2] if n % 2 else (inner[n // 2 - 1] + inner[n // 2]) / 2
    assert v["synthetic_inner_median_err_frac"] == round(median, 4)
    assert v["synthetic_inner_max_err_frac"] == round(max(inner), 4)
    assert v["synthetic_edge_max_err_frac"] == round(max(edge), 4)
    assert v["real_figure_mean_err_frac"] == round(d["v3b"]["summary"]["mean_err_frac"], 4)
    assert v["real_figure_max_err_frac"] == round(d["v3b"]["summary"]["max_err_frac"], 4)
    assert set(v) == {"source", "rules_commit", "synthetic_inner_median_err_frac", "synthetic_inner_max_err_frac",
                      "synthetic_edge_max_err_frac", "real_figure_mean_err_frac", "real_figure_max_err_frac"}
