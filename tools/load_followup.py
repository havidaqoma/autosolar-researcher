"""Post hoc follow-up at the load the paper chart implies (T20).

  python tools/load_followup.py --run <study hash> --figure-check <figure check run id>

Reads runs/studies/<run>/report.json and inputs.json plus
runs/figure_checks/<id>/figure_check.json, re-runs the study grid at the chart
loads from the weather cache only, and writes
runs/load_followups/<run_id>/load_followup.json. Makes no network call and no model call.
"""
import argparse
import json
import pathlib
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autosolar.demand import build_demand_cases  # noqa: E402
from autosolar.load_followup import (check_reproduction, followup_cases, followup_doc,  # noqa: E402
                                     load_followup)
from autosolar.pv import PVDesign, simulate_pv  # noqa: E402
from autosolar.study import _design_objects, load_inputs  # noqa: E402
from autosolar.weather import WeatherFetchers, build_weather_cases, cached_fetchers  # noqa: E402

CACHE_ONLY_EMAIL = "cache-only@invalid"


def no_network_fetchers() -> WeatherFetchers:
    """Fetchers that only raise. Every callable reports no network. Returns fetchers."""

    def _fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("no network: cached weather only")

    return WeatherFetchers(
        cams_monthly=_fail,  # type: ignore[arg-type]
        cams_hourly=_fail,  # type: ignore[arg-type]
        nasa_monthly=_fail,  # type: ignore[arg-type]
        nasa_hourly=_fail,  # type: ignore[arg-type]
        pvgis_tmy=_fail,  # type: ignore[arg-type]
        gsa=_fail,  # type: ignore[arg-type]
    )


def _resolve(raw: str) -> pathlib.Path:
    """Path against the repo root when relative. Returns a path."""
    path = pathlib.Path(raw)
    if not path.is_absolute():
        return ROOT / path
    return path


def main(argv: list[str] | None = None) -> int:
    """Run the load follow-up and write its record. Returns 0, 2 or 3."""
    t0 = time.time()
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--figure-check", required=True)
    ap.add_argument("--runs", default="runs/studies")
    ap.add_argument("--figure-checks", default="runs/figure_checks")
    ap.add_argument("--out", default="runs/load_followups")
    ap.add_argument("--weather-cache", default="runs/weather_cache")
    args = ap.parse_args(argv)
    run_dir = _resolve(str(args.runs)) / str(args.run)
    fig_path = _resolve(str(args.figure_checks)) / str(args.figure_check) / "figure_check.json"
    report_path = run_dir / "report.json"
    inputs_path = run_dir / "inputs.json"
    for path in (report_path, inputs_path, fig_path):
        if not path.is_file():
            print("not found: " + str(path))
            return 2
    report = json.loads(report_path.read_text(encoding="ascii"))
    figure_check = json.loads(fig_path.read_text(encoding="ascii"))
    values, _raw = load_inputs(inputs_path)
    costs, battery, diesel, battery_hours = _design_objects(values)
    lat, lon = report["weather_coords_deg"]
    weather = build_weather_cases(
        float(lat),
        float(lon),
        CACHE_ONLY_EMAIL,
        cached_fetchers(no_network_fetchers(), _resolve(str(args.weather_cache))),
    )
    pv_ac_kw_per_kwp = simulate_pv(
        weather.cases[weather.basis], float(lat), float(lon), PVDesign(), 1.0
    ).hourly["ac_kw"]
    load_kw = build_demand_cases(weather.cases[weather.basis].index)["paper"].load_kw
    pv_grid = list(report["grid"]["pv_kwp"])
    battery_grid = list(report["grid"]["battery_kwh"])
    main_pv_kwp = float(report["facts"]["best_pv_kwp"]["value"])
    main_battery_kwh = float(report["facts"]["best_battery_kwh"]["value"])
    cases = followup_cases(figure_check, float(values["swing_frac"]))
    scales = [1.0] + [float(case["scale_frac"]) for case in cases]
    rows = load_followup(
        pv_ac_kw_per_kwp,
        load_kw,
        pv_grid,
        battery_grid,
        battery_hours=float(battery_hours),
        battery_template=battery,
        diesel=diesel,
        costs=costs,
        co2_kg_per_l=float(values["co2_kg_per_l"]),
        unserved_max_frac=float(values["unserved_max_frac"]),
        main_pv_kwp=main_pv_kwp,
        main_battery_kwh=main_battery_kwh,
        scales=scales,
    )
    errors = check_reproduction(report, rows[0], rows[3], rows[4])
    run_id = "followup-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    doc = followup_doc(
        report,
        figure_check,
        figure_check_id=str(args.figure_check),
        run_id=run_id,
        base_row=rows[0],
        cases=cases,
        case_rows=rows[1:],
        errors=errors,
        wall_s=float(time.time() - t0),
    )
    out_dir = _resolve(str(args.out)) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "load_followup.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=True) + "\n", encoding="ascii"
    )
    print(run_id)
    for case in doc["cases"]:
        if case["best_pv_kwp"] is None:
            design = "none feasible"
            best = ""
        else:
            design = "%s kWp + %s kWh" % (case["best_pv_kwp"], case["best_battery_kwh"])
            best = " best %s USD/kWh" % (case["best_lcoe_usd_per_kwh"],)
        if case["saving_pct"] is None:
            saving = ""
        else:
            saving = " saving %s%%" % (case["saving_pct"],)
        print(
            "%s scale %s diesel only %s USD/kWh best %s%s%s"
            % (
                case["key"],
                case["scale_frac"],
                case["diesel_only_lcoe_usd_per_kwh"],
                design,
                best,
                saving,
            )
        )
    if errors:
        print("reproduced NO")
        for message in errors:
            print(message)
        return 3
    print("reproduced yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
