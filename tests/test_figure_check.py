"""Acceptance tests for T18b (autosolar/figure_check.py and its section in autosolar/site.py).

Written by the orchestrator. No network: read_chart is replaced by a fake that returns a known reading."""
import copy
import hashlib
import json
import re

import pandas as pd
import pytest

import autosolar.figure_check as fc
from autosolar.chart_reader import CHART_READER_VALIDATION, AxisFit, ChartReadError, ChartReading, ChartSpec
from autosolar.figure_check import (FIGURE_CHECK_SCHEMA, FIGURE_PLAN_SCHEMA, MIN_HOURS, compare_load, load_plan,
                                    run_figure_check)
from autosolar.site import figure_check_svg, render_study_html

PNG = b"\x89PNG fake image bytes for the sha check"
SHA = hashlib.sha256(PNG).hexdigest()
SCALE = 1.0348 ** 4


def plan_dict(**changes):
    raw = {
        "schema": "autosolar.figure_plan/1",
        "paper": "Hiron et al. 2021, Energies 14, 8311",
        "figure": "Figure 7, Daily power consumption (page 9)",
        "image": "docs/figures/hiron2021_fig7.png",
        "image_sha256": SHA,
        "series": [{"name": "31 Dec 2018", "prompt": "blue area"},
                   {"name": "27 Oct 2018", "prompt": "purple area"},
                   {"name": "28 Sep 2018", "prompt": "red area"}],
        "x_kind": "clock",
        "y_kind": "number",
        "y_unit": "kWh",
        "x_values": list(range(24)),
        "stacking": "overlap",
        "compare": {"table": "Hiron et al. 2021, Table 6", "basis_series": "31 Dec 2018",
                    "basis_note": "The paper grows the December 2018 curve by 3.48% a year (page 11).",
                    "table_year": 2022, "figure_year": 2018, "growth_frac_per_yr": 0.0348, "band_frac": 0.2},
    }
    raw.update(changes)
    return raw


def write_plan(tmp_path, raw):
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


# ---------- load_plan ----------

def test_constants():
    assert FIGURE_PLAN_SCHEMA == "autosolar.figure_plan/1"
    assert FIGURE_CHECK_SCHEMA == "autosolar.figure_check/1"
    assert MIN_HOURS == 12


def test_load_plan_ok(tmp_path):
    plan = load_plan(write_plan(tmp_path, plan_dict()))
    assert plan["x_values"] == [float(h) for h in range(24)]
    assert all(isinstance(v, float) for v in plan["x_values"])
    assert [s["name"] for s in plan["series"]] == ["31 Dec 2018", "27 Oct 2018", "28 Sep 2018"]
    assert plan["compare"]["basis_series"] == "31 Dec 2018" and plan["compare"]["table_year"] == 2022


def test_load_plan_real_file():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    path = root / "config" / "figure_checks" / "hiron2021_fig7.json"
    plan = load_plan(path)
    image = (root / plan["image"]).read_bytes()
    assert hashlib.sha256(image).hexdigest() == plan["image_sha256"]
    assert plan["compare"]["growth_frac_per_yr"] == 0.0348 and plan["compare"]["band_frac"] == 0.2


def _bad_plans():
    out = []
    for key in ("schema", "paper", "figure", "image", "image_sha256", "series", "x_kind", "y_kind", "y_unit",
                "x_values", "stacking", "compare"):
        raw = plan_dict()
        del raw[key]
        out.append(("missing " + key, raw))
    out.append(("extra key", plan_dict(note="x")))
    out.append(("schema", plan_dict(schema="autosolar.figure_plan/2")))
    out.append(("empty paper", plan_dict(paper=" ")))
    out.append(("sha upper", plan_dict(image_sha256=SHA.upper())))
    out.append(("sha short", plan_dict(image_sha256=SHA[:63])))
    out.append(("no series", plan_dict(series=[])))
    out.append(("series dup", plan_dict(series=[{"name": "a", "prompt": "x"}, {"name": "a", "prompt": "y"}])))
    out.append(("series no prompt", plan_dict(series=[{"name": "31 Dec 2018", "prompt": ""}])))
    out.append(("series extra", plan_dict(series=[{"name": "31 Dec 2018", "prompt": "x", "c": 1}])))
    out.append(("x kind", plan_dict(x_kind="time")))
    out.append(("y unit", plan_dict(y_unit="kW")))
    out.append(("x values 23", plan_dict(x_values=list(range(23)))))
    out.append(("x values shifted", plan_dict(x_values=list(range(1, 25)))))
    out.append(("x values bool", plan_dict(x_values=[True] + list(range(1, 24)))))
    out.append(("stacking", plan_dict(stacking="stacked")))
    for k, v in (("basis_series", "1 Jan 2018"), ("table_year", 2017), ("table_year", 2022.0),
                 ("figure_year", True), ("growth_frac_per_yr", -0.01), ("growth_frac_per_yr", 0.6),
                 ("growth_frac_per_yr", float("nan")), ("band_frac", 0.0), ("band_frac", 1.0), ("table", ""),
                 ("basis_note", 3)):
        raw = plan_dict()
        raw["compare"][k] = v
        out.append(("compare " + k, raw))
    raw = plan_dict()
    raw["compare"]["extra"] = 1
    out.append(("compare extra", raw))
    raw = plan_dict()
    del raw["compare"]["band_frac"]
    out.append(("compare missing", raw))
    return out


@pytest.mark.parametrize("name,raw", _bad_plans(), ids=[n for n, _ in _bad_plans()])
def test_load_plan_rejects(tmp_path, name, raw):
    with pytest.raises(ValueError):
        load_plan(write_plan(tmp_path, raw))


def test_load_plan_rejects_non_object(tmp_path):
    p = tmp_path / "plan.json"
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError):
        load_plan(p)


# ---------- compare_load ----------

TABLE = [1000.0] * 24


def reading(basis=800.0, other=900.0, third=850.0):
    values = {"31 Dec 2018": [basis] * 24, "27 Oct 2018": [other] * 24, "28 Sep 2018": [third] * 24}
    status = {k: ["edge_not_validated"] + ["validated"] * 22 + ["edge_not_validated"] for k in values}
    values["27 Oct 2018"][5] = None
    status["27 Oct 2018"][5] = "not_read"
    return values, status


KW = dict(basis_series="31 Dec 2018", table_year=2022, figure_year=2018, growth_frac_per_yr=0.0348, band_frac=0.2)


def test_compare_inside_band():
    values, status = reading()
    c = compare_load(values, status, TABLE, **KW)
    hours = [h for h in range(1, 23) if h != 5]
    assert c["hours"] == hours and c["years"] == 4
    assert c["scale"] == pytest.approx(SCALE, rel=1e-12)
    assert c["table_at_figure_year_kw"] == pytest.approx([1000.0 / SCALE] * 24, rel=1e-12)
    t_kwh = 21 * 1000.0 / SCALE
    assert c["table_kwh"] == pytest.approx(t_kwh, rel=1e-12)
    assert [s["name"] for s in c["series"]] == ["31 Dec 2018", "27 Oct 2018", "28 Sep 2018"]
    assert c["series"][0]["kwh"] == pytest.approx(800.0 * 21) and c["series"][0]["peak_kwh"] == 800.0
    assert c["series"][1]["ratio"] == pytest.approx(t_kwh / (900.0 * 21), rel=1e-12)
    assert c["ratio"] == pytest.approx(t_kwh / (800.0 * 21), rel=1e-12)
    assert c["diff_pct"] == pytest.approx(100.0 * (t_kwh / (800.0 * 21) - 1.0), rel=1e-12)
    assert c["mean_ratio"] == pytest.approx(t_kwh / (850.0 * 21), rel=1e-12)
    assert c["verdict"] == "inside band" and c["reason"] == "" and c["band_frac"] == 0.2
    assert c["basis_series"] == "31 Dec 2018"


def test_compare_outside_band_above_and_below():
    values, status = reading(basis=600.0)
    c = compare_load(values, status, TABLE, **KW)
    assert c["verdict"] == "outside band" and c["diff_pct"] > 20.0
    values, status = reading(basis=1300.0)
    c = compare_load(values, status, TABLE, **KW)
    assert c["diff_pct"] < 0.0
    assert c["verdict"] == ("inside band" if abs(c["ratio"] - 1.0) <= 0.2 else "outside band")
    values, status = reading(basis=1100.0)
    c = compare_load(values, status, TABLE, **dict(KW, band_frac=0.1))
    assert c["ratio"] == pytest.approx(1000.0 / SCALE / 1100.0) and c["verdict"] == "outside band"


def test_compare_band_edge_counts_inside():
    values, status = reading(basis=1000.0 / SCALE / 1.2)
    c = compare_load(values, status, TABLE, **KW)
    assert c["ratio"] == pytest.approx(1.2, rel=1e-12) and c["verdict"] == "inside band"


def test_compare_peak_uses_hours_only():
    values, status = reading()
    values["31 Dec 2018"][0] = 5000.0          # edge hour, not used
    values["31 Dec 2018"][7] = 950.0
    c = compare_load(values, status, TABLE, **KW)
    assert c["series"][0]["peak_kwh"] == 950.0
    assert c["series"][0]["kwh"] == pytest.approx(800.0 * 20 + 950.0)


def test_compare_not_checkable_few_hours():
    values, status = reading()
    for h in range(1, 12):
        status["28 Sep 2018"][h] = "not_read"
        values["28 Sep 2018"][h] = None
    c = compare_load(values, status, TABLE, **KW)
    assert len([h for h in range(24) if all(status[k][h] == "validated" for k in status)]) == 11
    assert c["verdict"] == "not checkable" and "12" in c["reason"]
    assert c["ratio"] is None and c["table_kwh"] is None and c["series"] == [] and c["mean_ratio"] is None
    assert c["diff_pct"] is None and len(c["hours"]) == 11


def test_compare_validated_none_value_not_used():
    values, status = reading()
    values["28 Sep 2018"][9] = None              # status says validated but no value: hour not used
    c = compare_load(values, status, TABLE, **KW)
    assert 9 not in c["hours"] and len(c["hours"]) == 20


def test_compare_inputs_not_changed():
    values, status = reading()
    v0, s0, t0 = copy.deepcopy(values), copy.deepcopy(status), list(TABLE)
    compare_load(values, status, TABLE, **KW)
    assert values == v0 and status == s0 and TABLE == t0


@pytest.mark.parametrize("mutate", [
    lambda v, s, t, k: t.pop(),
    lambda v, s, t, k: t.__setitem__(3, float("nan")),
    lambda v, s, t, k: t.__setitem__(3, -1.0),
    lambda v, s, t, k: t.__setitem__(3, True),
    lambda v, s, t, k: v["31 Dec 2018"].pop(),
    lambda v, s, t, k: s["31 Dec 2018"].pop(),
    lambda v, s, t, k: s.pop("28 Sep 2018"),
    lambda v, s, t, k: k.__setitem__("basis_series", "1 Jan 2018"),
    lambda v, s, t, k: k.__setitem__("figure_year", 2023),
    lambda v, s, t, k: k.__setitem__("band_frac", 0.0),
    lambda v, s, t, k: k.__setitem__("growth_frac_per_yr", -0.1),
    lambda v, s, t, k: v.clear() or s.clear(),
])
def test_compare_rejects(mutate):
    values, status = reading()
    table, kw = list(TABLE), dict(KW)
    mutate(values, status, table, kw)
    with pytest.raises(ValueError):
        compare_load(values, status, table, **kw)


# ---------- run_figure_check ----------

AX = AxisFit(slope=2.0, intercept=-1.0, used=(0, 1, 2), dropped=(3,), max_resid=0.01)


class FakeRead:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []

    def __call__(self, image_png, spec, segment, read_labels):
        self.calls.append((image_png, spec, segment, read_labels))
        if self.fail:
            raise ChartReadError(self.fail)
        values, status = reading()
        return ChartReading(values=values, y_unit="kWh", x_axis=AX, y_axis=AX, ticks=[{"text": "0"}],
                            plot_box_px=(1.0, 2.0, 3.0, 4.0), sam_calls=4, label_calls=1, point_status=status)


def seg(image_png, prompt):
    raise AssertionError("not called with the fake reader")


def lab(crops):
    raise AssertionError("not called with the fake reader")


@pytest.fixture
def plan(tmp_path):
    return load_plan(write_plan(tmp_path, plan_dict()))


def test_run_builds_the_chart_spec(monkeypatch, plan):
    fake = FakeRead()
    monkeypatch.setattr(fc, "read_chart", fake)
    out = run_figure_check(plan, PNG, TABLE, seg, lab)
    assert len(fake.calls) == 1
    image, spec, s_fn, l_fn = fake.calls[0]
    assert image == PNG and s_fn is seg and l_fn is lab
    assert isinstance(spec, ChartSpec)
    assert list(spec.series.items()) == [("31 Dec 2018", "blue area"), ("27 Oct 2018", "purple area"),
                                         ("28 Sep 2018", "red area")]
    assert (spec.x_kind, spec.y_kind, spec.y_unit, spec.stacking, spec.mode) == ("clock", "number", "kWh",
                                                                                  "overlap", "top")
    assert spec.x_values == tuple(float(h) for h in range(24))
    assert out["schema"] == FIGURE_CHECK_SCHEMA and out["image_sha256"] == SHA
    assert out["verdict"] == "inside band" and out["reason"] == ""
    assert out["comparison"] == compare_load(*reading(), TABLE, **KW)
    assert out["table_kw"] == TABLE and out["plan"] == plan
    assert out["validation"] == CHART_READER_VALIDATION and out["validation"] is not CHART_READER_VALIDATION


def test_run_reading_block(monkeypatch, plan):
    monkeypatch.setattr(fc, "read_chart", FakeRead())
    out = run_figure_check(plan, PNG, TABLE, seg, lab)
    r = out["reading"]
    assert r["values"] == reading()[0] and r["point_status"] == reading()[1]
    assert r["y_unit"] == "kWh" and r["sam_calls"] == 4 and r["label_calls"] == 1
    for axis in ("x_axis", "y_axis"):
        assert r[axis] == {"slope": 2.0, "intercept": -1.0, "used": [0, 1, 2], "dropped": [3], "max_resid": 0.01}
    json.dumps(out)


def test_run_chart_not_read(monkeypatch, plan):
    monkeypatch.setattr(fc, "read_chart", FakeRead(fail="series not found: 28 Sep 2018"))
    out = run_figure_check(plan, PNG, TABLE, seg, lab)
    assert out["verdict"] == "not checkable"
    assert out["reason"] == "chart not read: series not found: 28 Sep 2018"
    assert out["reading"] is None and out["comparison"] is None and out["schema"] == FIGURE_CHECK_SCHEMA
    json.dumps(out)


def test_run_other_errors_pass_through(monkeypatch, plan):
    def boom(*a):
        raise RuntimeError("network down")
    monkeypatch.setattr(fc, "read_chart", boom)
    with pytest.raises(RuntimeError, match="network down"):
        run_figure_check(plan, PNG, TABLE, seg, lab)


def test_run_refuses_wrong_image(monkeypatch, plan):
    fake = FakeRead()
    monkeypatch.setattr(fc, "read_chart", fake)
    with pytest.raises(ValueError, match="sha256"):
        run_figure_check(plan, PNG + b"x", TABLE, seg, lab)
    assert fake.calls == []


def test_run_refuses_bad_table_before_reading(monkeypatch, plan):
    fake = FakeRead()
    monkeypatch.setattr(fc, "read_chart", fake)
    with pytest.raises(ValueError):
        run_figure_check(plan, PNG, TABLE[:23], seg, lab)
    assert fake.calls == []


# ---------- site ----------

def result(monkeypatch=None, fail=None):
    import autosolar.figure_check as mod
    keep = mod.read_chart
    mod.read_chart = FakeRead(fail=fail)
    try:
        import tempfile
        import pathlib
        d = pathlib.Path(tempfile.mkdtemp(prefix="t18b_"))
        return run_figure_check(load_plan(write_plan(d, plan_dict())), PNG, TABLE, seg, lab)
    finally:
        mod.read_chart = keep


def test_svg():
    svg = figure_check_svg(result())
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    lines = re.findall(r"<polyline [^>]*>", svg)
    assert len(lines) == 4
    assert sum("stroke-dasharray" in ln for ln in lines) == 1
    for name in ("31 Dec 2018", "27 Oct 2018", "28 Sep 2018"):
        assert name in svg
    svg.encode("ascii")


@pytest.fixture(scope="module")
def page_parts():
    import tempfile
    import pathlib
    import test_study as ts
    from autosolar.study import run_study
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="t18b_page_"))
    out = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                    inputs_path=ts.small_inputs(tmp), runs_dir=tmp / "runs", run_id="t18b")
    return out.report, pd.read_csv(out.run_dir / "design_table.csv")


def section(page):
    assert page.count('<section id="figure-check">') == 1
    return page.split('<section id="figure-check">', 1)[1].split("</section>", 1)[0]


def test_page_section(page_parts):
    report, table = page_parts
    page = render_study_html(report, table, figure_check=result())
    sec = section(page)
    assert "<h2>Second read of the load: SAM 3.1 reads the paper chart</h2>" in sec
    assert "Figure 7, Daily power consumption (page 9)" in sec and "Hiron et al. 2021, Energies 14, 8311" in sec
    assert "<svg" in sec
    c = result()["comparison"]
    assert "%.1f%% above the 31 Dec 2018 curve" % c["diff_pct"] in sec
    assert "That is inside the +/-20% demand swing of the sensitivity table." in sec
    assert "The paper grows the December 2018 curve by 3.48% a year (page 11)." in sec
    assert "4 years at 3.48% a year" in sec
    assert "Hours used: 21 of 24" in sec
    for name in ("31 Dec 2018", "27 Oct 2018", "28 Sep 2018"):
        assert "<td>" + name + "</td>" in sec
    assert "<td>16,800</td>" in sec          # 800 kWh x 21 hours
    assert "<td>%.2f</td>" % c["series"][0]["ratio"] in sec
    assert "0.76%" in sec and "1.32%" in sec   # reader error in the validation test (measured)
    page.encode("ascii")


def test_page_section_outside_and_below(page_parts, monkeypatch):
    report, table = page_parts
    r = result()
    r["comparison"] = compare_load(*reading(basis=1300.0), TABLE, **dict(KW, band_frac=0.1))
    r["verdict"] = r["comparison"]["verdict"]
    sec = section(render_study_html(report, table, figure_check=r))
    assert "below the 31 Dec 2018 curve" in sec
    assert "That is outside the +/-10% demand swing of the sensitivity table." in sec


def test_page_section_not_checkable(page_parts):
    report, table = page_parts
    sec = section(render_study_html(report, table, figure_check=result(fail="empty plot")))
    assert "Not checkable: chart not read: empty plot" in sec
    assert "<svg" not in sec


def test_page_without_figure_check_has_no_section(page_parts):
    report, table = page_parts
    page = render_study_html(report, table)
    assert 'id="figure-check"' not in page
    assert page == render_study_html(report, table, figure_check=None)


def test_section_comes_after_paper_section(page_parts):
    report, table = page_parts
    paper = {"summary": {"flags": 1, "passes": 2, "not_checkable": 3},
             "results": [{"check_id": "P1", "status": "pass", "pages": [1], "detail": "d"}]}
    review = {"model": "m", "points": [{"point": "p", "addressed_in": None}]}
    page = render_study_html(report, table, paper_check=paper, review=review, figure_check=result())
    assert page.index('<section id="paper">') < page.index('<section id="figure-check">')
    assert page.index('<section id="figure-check">') < page.index('<section id="review">')
    page = render_study_html(report, table, review=review, figure_check=result())
    assert page.index('<section id="range">') < page.index('<section id="figure-check">')
    assert page.index('<section id="figure-check">') < page.index('<section id="review">')
