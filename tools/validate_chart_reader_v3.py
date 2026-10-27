"""Chart reader validation V3 (rules: docs/smoke/CHART_VALIDATION_V3_RULES.md). Orchestrator tooling.

  uv run --with matplotlib python tools/validate_chart_reader_v3.py render   # synthetic charts only, no API call
  uv run --with matplotlib python tools/validate_chart_reader_v3.py run

Reads runs/chart_validation_v3/hiron_fig16.png (rendered from the paper PDF before the run, sha256 in the
rules) and runs/sam_fig/hiron_fig8_native.png (practice figure, reported but not counted). Writes
runs/chart_validation_v3/*.png and docs/smoke/chart_validation_v3.json.
"""
import hashlib
import io
import json
import os
import pathlib
import statistics
import sys
import time

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "runs" / "chart_validation_v3"
SEED = 20261028
FIG16_SHA = "6782b6b4177545a7710e2a65cd138aec81608f4377909adc0f183206736bf85a"
# Hiron 2021 Table 4: LCOE (USD per MWh) at PV penetration 10..100 %.
TABLE4_LCOE = [299.554, 294.911, 290.269, 285.626, 280.983, 276.340, 271.697, 265.827, 261.184, 257.770]
# Hiron 2021 Table 6 hourly load (kWh per hour), as in the V1 and V2 test.
TABLE6_LOAD_KWH = [1126, 1105, 1052, 1031, 1044, 1104, 1152, 1004, 995, 976, 942, 936,
                   949, 985, 974, 934, 926, 1003, 1367, 1422, 1377, 1351, 1264, 1195]
HATCH = {"flat": None, "striped": "////", "checkered": "xxxx"}


def clock_fmt(v, _pos=None):
    return f"{int(round(v))}:00"


def render_charts():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MultipleLocator

    plt.rcParams["hatch.linewidth"] = 2.0
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    charts = []
    # front to back: (colour, pattern)
    area_sets = [(("orange", "flat"), ("blue", "flat"), ("green", "flat")),
                 (("purple", "striped"), ("green", "striped"), ("yellow", "striped")),
                 (("green", "checkered"), ("purple", "striped"), ("yellow", "flat"))]
    for k, layers in enumerate(area_sets, 1):
        hours = np.arange(24.0)
        back = np.clip(1000 + np.cumsum(rng.normal(0, 60, 24)), 700, 1700)
        middle = back - rng.uniform(60, 260, 24)
        front = middle - rng.uniform(60, 260, 24)
        series = [front, middle, back]
        fig, ax = plt.subplots(figsize=(14, 7), dpi=100)
        for vals, (col, pat) in reversed(list(zip(series, layers))):
            if pat == "flat":
                ax.fill_between(hours, 0, vals, color=col, linewidth=0)
            else:
                ax.fill_between(hours, 0, vals, facecolor="white", edgecolor=col, hatch=HATCH[pat], linewidth=0)
        ax.set_xlim(0, 23)
        ax.set_ylim(0, 2000)
        ax.xaxis.set_major_locator(MultipleLocator(3))
        ax.xaxis.set_major_formatter(FuncFormatter(clock_fmt))
        ax.yaxis.set_major_locator(MultipleLocator(400))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:,.0f}"))
        ax.set_xlabel("Hour")
        ax.set_ylabel("kWh")
        fig.tight_layout()
        prompts = {f"{c} {'' if p == 'flat' else p + ' '}area".replace("  ", " "): v
                   for (c, p), v in zip(layers, series)}
        charts.append({"name": f"area{k}", "fig": fig, "kind": "area", "x_kind": "clock",
                       "x_values": hours.tolist(), "y_span": 2000.0,
                       "series": {p: v.round(3).tolist() for p, v in prompts.items()}})
    line_defs = [("line4", "clock", np.arange(24.0), 3, (0.0, 23.0), (10, 5.6)),
                 ("line5", "number", np.arange(0.0, 101.0, 10.0), 20, (0.0, 100.0), (14, 7)),
                 ("line6", "number", np.arange(2015.0, 2031.0), 5, (2015.0, 2030.0), (12, 6))]
    for name, x_kind, xs, step, xlim, size in line_defs:
        n = len(xs)
        blue = 0.30 + np.cumsum(rng.normal(0, 0.008, n))
        red = blue + rng.uniform(0.02, 0.06) + np.cumsum(rng.normal(0, 0.006, n))
        fig, ax = plt.subplots(figsize=size, dpi=100)
        ax.plot(xs, blue, color="blue", linewidth=2.5)
        ax.plot(xs, red, color="red", linewidth=2.5)
        ax.set_xlim(*xlim)
        ax.set_ylim(0.20, 0.45)
        ax.xaxis.set_major_locator(MultipleLocator(step))
        if x_kind == "clock":
            ax.xaxis.set_major_formatter(FuncFormatter(clock_fmt))
        else:
            ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:.0f}"))
        ax.yaxis.set_major_locator(MultipleLocator(0.05))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:.2f}"))
        ax.set_ylabel("USD per kWh")
        fig.tight_layout()
        charts.append({"name": name, "fig": fig, "kind": "line", "x_kind": x_kind, "x_values": xs.tolist(),
                       "y_span": 0.25, "series": {"blue line": blue.round(5).tolist(),
                                                  "red line": red.round(5).tolist()}})
    for c in charts:
        buf = io.BytesIO()
        c.pop("fig").savefig(buf, format="png", dpi=100)
        c["png"] = buf.getvalue()
        (OUT / f"{c['name']}.png").write_bytes(c["png"])
        c["png_sha256"] = hashlib.sha256(c["png"]).hexdigest()
    plt.close("all")
    return charts


def errors(read, truth, span):
    return [None if r is None else abs(r - t) / span for r, t in zip(read, truth)]


def real_figure(read_chart, ChartSpec, seg, lab, png, spec, name, truth):
    row = {"png_sha256": hashlib.sha256(png).hexdigest()}
    try:
        r = read_chart(png, spec, seg, lab)
        ys = [t for t in r.ticks if t["axis"] == "y" and t["value"] is not None]
        used = [ys[i]["value"] for i in r.y_axis.used]
        span = max(used) - min(used)
        read = r.values[name]
        e = errors(read, truth, span)
        got = [x for x in e if x is not None]
        row.update({"ok": True, "y_span": span, "truth": truth, "read": read, "err_frac": e,
                    "all_series": r.values, "sam_calls": r.sam_calls, "label_calls": r.label_calls,
                    "ticks": [{k: t[k] for k in ("text", "axis", "value")} for t in r.ticks],
                    "y_axis_dropped": list(r.y_axis.dropped), "x_axis_dropped": list(r.x_axis.dropped),
                    "summary": {"read": len(got), "of": len(truth),
                                "mean_err_frac": statistics.mean(got) if got else None,
                                "max_err_frac": max(got) if got else None}})
    except Exception as ex:  # counted by the rules, never retried
        row.update({"ok": False, "error": f"{type(ex).__name__}: {str(ex)[:300]}",
                    "summary": {"read": 0, "of": len(truth)}})
    return row


def run():
    from autosolar.chart_reader import ChartSpec, read_chart, sam_segment_fn, spark_label_fn
    from autosolar.ledger import Ledger
    from autosolar.meta_client import MetaClient

    env_file = pathlib.Path(os.environ.get("AUTOSOLAR_ENV_FILE", ROOT / ".env"))
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("MODEL_API_KEY="):
            os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip()
    fig16 = (OUT / "hiron_fig16.png").read_bytes()
    if hashlib.sha256(fig16).hexdigest() != FIG16_SHA:
        raise SystemExit("hiron_fig16.png differs from the file fixed in the rules")
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=180.0)
    run_id = "chart-validation-v3"
    seg, lab = sam_segment_fn(client, run_id), spark_label_fn(client, run_id)
    res = {"rules": "docs/smoke/CHART_VALIDATION_V3_RULES.md", "seed": SEED, "started_unix": round(time.time()),
           "v3a": [], "v3b": None, "practice_fig8": None}
    for c in render_charts():
        spec = ChartSpec(series={k: k for k in c["series"]}, x_kind=c["x_kind"], y_kind="number", y_unit="test",
                         mode="top" if c["kind"] == "area" else "centre",
                         stacking="overlap" if c["kind"] == "area" else "none", x_values=tuple(c["x_values"]))
        row = {"name": c["name"], "png_sha256": c["png_sha256"], "y_span": c["y_span"]}
        t0 = time.time()
        try:
            r = read_chart(c["png"], spec, seg, lab)
            row.update({"ok": True, "sam_calls": r.sam_calls, "label_calls": r.label_calls,
                        "x_axis_dropped": list(r.x_axis.dropped), "y_axis_dropped": list(r.y_axis.dropped),
                        "series": {}})
            for name, truth in c["series"].items():
                row["series"][name] = {"truth": truth, "read": r.values[name],
                                       "err_frac": errors(r.values[name], truth, c["y_span"])}
        except Exception as ex:  # counted by the rules, never retried
            row.update({"ok": False, "error": f"{type(ex).__name__}: {str(ex)[:300]}"})
        row["wall_s"] = round(time.time() - t0, 1)
        res["v3a"].append(row)
        print(c["name"], "ok" if row["ok"] else row["error"], flush=True)
    pts = [e for row in res["v3a"] if row["ok"] for s in row["series"].values() for e in s["err_frac"]]
    vals = [e for e in pts if e is not None]
    ok_charts = sum(r["ok"] for r in res["v3a"])
    med = statistics.median(vals) if vals else None
    within = (sum(1 for e in vals if e <= 0.03) / len(pts)) if pts else 0.0
    res["v3a_summary"] = {"charts_ok": ok_charts, "points": len(pts), "misses": sum(e is None for e in pts),
                          "median_err_frac": med, "share_within_3pct": round(within, 4),
                          "pass": ok_charts >= 5 and med is not None and med <= 0.01 and within >= 0.95}
    print("V3a", res["v3a_summary"], flush=True)

    spec16 = ChartSpec(series={"LCOE": "blue bar"}, x_kind="number", y_kind="number", y_unit="usd_per_mwh",
                       mode="top", stacking="none", x_values=tuple(float(p) for p in range(10, 101, 10)))
    v3b = real_figure(read_chart, ChartSpec, seg, lab, fig16, spec16, "LCOE", TABLE4_LCOE)
    s = v3b["summary"]
    s["pass"] = bool(v3b["ok"] and s["read"] == 10 and s["mean_err_frac"] <= 0.02 and s["max_err_frac"] <= 0.05)
    res["v3b"] = v3b
    print("V3b", s, flush=True)

    fig8 = (ROOT / "runs" / "sam_fig" / "hiron_fig8_native.png").read_bytes()
    spec8 = ChartSpec(series={"Dec. 2017": "purple striped area", "Oct. 2018": "green checkered area",
                              "Predic. 2022": "yellow striped area"},
                      x_kind="clock", y_kind="number", y_unit="kwh", mode="top", stacking="overlap",
                      x_values=tuple(float(h) for h in range(24)))
    p8 = real_figure(read_chart, ChartSpec, seg, lab, fig8, spec8, "Predic. 2022", TABLE6_LOAD_KWH)
    if p8["ok"] and p8["summary"]["read"] == 24:
        p8["summary"]["day_sum_kwh"] = sum(p8["read"])
    res["practice_fig8"] = p8
    print("practice Fig 8", p8["summary"], flush=True)
    (ROOT / "docs" / "smoke" / "chart_validation_v3.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "render":
        for ch in render_charts():
            print(ch["name"], ch["png_sha256"][:12], list(ch["series"]))
    else:
        run()
