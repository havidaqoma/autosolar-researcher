"""Chart reader validation V1 and V2 (rules: docs/smoke/CHART_VALIDATION_RULES.md). Orchestrator tooling.

  uv run --with matplotlib python tools/validate_chart_reader.py render     # V1 charts only, no API call
  uv run --with matplotlib python tools/validate_chart_reader.py run <hiron_fig8.png>

Writes runs/chart_validation/*.png and docs/smoke/chart_validation.json.
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
OUT = ROOT / "runs" / "chart_validation"
SEED = 20261027
# Hiron 2021 Table 6 hourly load (kWh per hour), as typed in prep/benchmark/hiron2021_audit.py before this test.
TABLE6_LOAD_KWH = [1126, 1105, 1052, 1031, 1044, 1104, 1152, 1004, 995, 976, 942, 936,
                   949, 985, 974, 934, 926, 1003, 1367, 1422, 1377, 1351, 1264, 1195]


def clock_fmt(v, _pos=None):
    return f"{int(round(v))}:00"


def render_charts():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MultipleLocator

    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    charts = []
    area_sets = [("blue", "orange", "green"), ("red", "blue", "yellow"), ("purple", "green", "orange")]
    for k, colours in enumerate(area_sets, 1):
        hours = np.arange(24.0)
        back = 1000 + np.cumsum(rng.normal(0, 60, 24))
        back = np.clip(back, 700, 1700)
        middle = back - rng.uniform(60, 260, 24)
        front = middle - rng.uniform(60, 260, 24)
        series = [front, middle, back]                 # front to back
        fig, ax = plt.subplots(figsize=(10, 5.6), dpi=100)
        for vals, col in reversed(list(zip(series, colours))):   # draw back first
            ax.fill_between(hours, 0, vals, color=col, linewidth=0)
        ax.set_xlim(0, 23)
        ax.set_ylim(0, 2000)
        ax.xaxis.set_major_locator(MultipleLocator(3))
        ax.xaxis.set_major_formatter(FuncFormatter(clock_fmt))
        ax.yaxis.set_major_locator(MultipleLocator(400))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:,.0f}"))
        ax.set_xlabel("Hour")
        ax.set_ylabel("kWh")
        fig.tight_layout()
        charts.append({"name": f"area{k}", "fig": fig, "kind": "area", "x_kind": "clock",
                       "x_values": hours.tolist(), "y_span": 2000.0,
                       "series": {f"{c} area": v.round(3).tolist() for c, v in zip(colours, series)}})
    line_defs = [("line4", "clock", np.arange(24.0), 3, (0.0, 23.0)),
                 ("line5", "number", np.arange(0.0, 101.0, 10.0), 20, (0.0, 100.0)),
                 ("line6", "number", np.arange(2015.0, 2031.0), 5, (2015.0, 2030.0))]
    for name, x_kind, xs, step, xlim in line_defs:
        n = len(xs)
        blue = 0.30 + np.cumsum(rng.normal(0, 0.008, n))
        red = blue + rng.uniform(0.02, 0.06) + np.cumsum(rng.normal(0, 0.006, n))
        fig, ax = plt.subplots(figsize=(10, 5.6), dpi=100)
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
    out = []
    for r, t in zip(read, truth):
        out.append(None if r is None else abs(r - t) / span)
    return out


def run(fig8_path):
    from autosolar.chart_reader import ChartSpec, read_chart, sam_segment_fn, spark_label_fn
    from autosolar.ledger import Ledger
    from autosolar.meta_client import MetaClient

    if not os.environ.get("MODEL_API_KEY"):
        env_file = pathlib.Path(os.environ.get("AUTOSOLAR_ENV_FILE", ROOT / ".env"))
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("MODEL_API_KEY="):
                os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip()
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=180.0)
    run_id = "chart-validation"
    seg, lab = sam_segment_fn(client, run_id), spark_label_fn(client, run_id)
    res = {"rules": "docs/smoke/CHART_VALIDATION_RULES.md", "seed": SEED, "started_unix": round(time.time()),
           "v1": [], "v2": None}
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
                e = errors(r.values[name], truth, c["y_span"])
                row["series"][name] = {"truth": truth, "read": r.values[name], "err_frac": e}
        except Exception as ex:  # counted by the rules, never retried
            row.update({"ok": False, "error": f"{type(ex).__name__}: {str(ex)[:300]}"})
        row["wall_s"] = round(time.time() - t0, 1)
        res["v1"].append(row)
        print(c["name"], "ok" if row["ok"] else row["error"], flush=True)
    pts = [e for row in res["v1"] if row["ok"] for s in row["series"].values() for e in s["err_frac"]]
    ok_charts = sum(r["ok"] for r in res["v1"])
    vals = [e for e in pts if e is not None]
    med = statistics.median(vals) if vals else None
    within = (sum(1 for e in pts if e is not None and e <= 0.03) / len(pts)) if pts else 0.0
    res["v1_summary"] = {"charts_ok": ok_charts, "points": len(pts), "misses": sum(e is None for e in pts),
                         "median_err_frac": med, "share_within_3pct": round(within, 4),
                         "pass": ok_charts >= 5 and med is not None and med <= 0.01 and within >= 0.95}
    print("V1", res["v1_summary"], flush=True)

    png8 = pathlib.Path(fig8_path).read_bytes()
    spec8 = ChartSpec(series={"Dec. 2017": "purple area", "Oct. 2018": "green area", "Predic. 2022": "yellow area"},
                      x_kind="clock", y_kind="number", y_unit="kwh", mode="top", stacking="overlap",
                      x_values=tuple(float(h) for h in range(24)))
    v2 = {"figure": "Hiron 2021 Figure 8 (embedded image, 1422 x 775)", "png_sha256": hashlib.sha256(png8).hexdigest()}
    try:
        r = read_chart(png8, spec8, seg, lab)
        ys = [t["value"] for t in r.ticks if t["axis"] == "y" and t["value"] is not None]
        used_y = [ys[i] for i in r.y_axis.used] if ys else []
        span = (max(used_y) - min(used_y)) if used_y else None
        read = r.values["Predic. 2022"]
        e = errors(read, TABLE6_LOAD_KWH, span) if span else []
        got = [x for x in read if x is not None]
        v2.update({"ok": True, "y_span": span, "truth_kwh": TABLE6_LOAD_KWH, "read_kwh": read, "err_frac": e,
                   "other_series": {k: v for k, v in r.values.items() if k != "Predic. 2022"},
                   "ticks": [{k: t[k] for k in ("text", "axis", "value")} for t in r.ticks],
                   "y_axis_dropped": list(r.y_axis.dropped), "x_axis_dropped": list(r.x_axis.dropped)})
        hours_read = len(got)
        mean_e = statistics.mean([x for x in e if x is not None]) if got else None
        max_e = max([x for x in e if x is not None]) if got else None
        day_sum = sum(got) if hours_read == 24 else None
        v2["summary"] = {"hours_read": hours_read, "mean_err_frac": mean_e, "max_err_frac": max_e,
                         "day_sum_kwh": day_sum,
                         "day_sum_rel_err": (abs(day_sum - 26214) / 26214) if day_sum else None}
        v2["summary"]["pass"] = (hours_read == 24 and mean_e <= 0.02 and max_e <= 0.05
                                 and v2["summary"]["day_sum_rel_err"] <= 0.02)
    except Exception as ex:
        v2.update({"ok": False, "error": f"{type(ex).__name__}: {str(ex)[:300]}", "summary": {"pass": False}})
    res["v2"] = v2
    print("V2", v2.get("summary"), flush=True)
    (ROOT / "docs" / "smoke" / "chart_validation.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "render":
        for ch in render_charts():
            print(ch["name"], ch["png_sha256"][:12], {k: len(v) for k, v in ch["series"].items()})
    else:
        run(sys.argv[2])
