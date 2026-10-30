"""Hourly engineer files behind one study page (T22).

  python tools/engineer_files.py --run <study hash>

Reads runs/studies/<run>/report.json and inputs.json, rebuilds the main design
dispatch from the cached weather only, and writes runs/engineer_files/<run_id>/
with hourly.csv, homer_load_kw.txt and engineer_files.json. Makes no network
call and no model call.
"""
import argparse
import hashlib
import json
import pathlib
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from autosolar.demand import LOCAL_TZ, build_demand_cases  # noqa: E402
from autosolar.engineer_files import (engineer_doc, homer_load_lines, hourly_frame,  # noqa: E402
                                      main_design_dispatch, reproduction_errors)
from autosolar.pv import PVDesign, simulate_pv  # noqa: E402
from autosolar.study import _design_objects, load_inputs  # noqa: E402
from autosolar.weather import build_weather_cases, cached_fetchers  # noqa: E402
from load_followup import CACHE_ONLY_EMAIL, no_network_fetchers  # noqa: E402


def write_ascii_lf(path: pathlib.Path | str, text: str) -> None:
    """Write ASCII text with LF newlines unchanged on any OS. Returns None."""
    pathlib.Path(path).write_bytes(text.encode("ascii"))


def _resolve(raw: str) -> pathlib.Path:
    """Path against the repo root when relative. Returns a path."""
    path = pathlib.Path(raw)
    if not path.is_absolute():
        return ROOT / path
    return path


def main(argv: list[str] | None = None) -> int:
    """Rebuild the hourly files and write their record. Returns 0, 2 or 3."""
    t0 = time.time()
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--runs", default="runs/studies")
    ap.add_argument("--out", default="runs/engineer_files")
    ap.add_argument("--weather-cache", default="runs/weather_cache")
    args = ap.parse_args(argv)
    run_dir = _resolve(str(args.runs)) / str(args.run)
    report_path = run_dir / "report.json"
    inputs_path = run_dir / "inputs.json"
    for path in (report_path, inputs_path):
        if not path.is_file():
            print("not found: " + str(path))
            return 2
    report = json.loads(report_path.read_text(encoding="ascii"))
    values, _raw = load_inputs(inputs_path)
    _costs, battery, diesel, battery_hours = _design_objects(values)
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
    main_pv_kwp = float(report["facts"]["best_pv_kwp"]["value"])
    main_battery_kwh = float(report["facts"]["best_battery_kwh"]["value"])
    result = main_design_dispatch(
        pv_ac_kw_per_kwp,
        load_kw,
        main_pv_kwp=main_pv_kwp,
        main_battery_kwh=main_battery_kwh,
        battery_hours=float(battery_hours),
        battery_template=battery,
        diesel=diesel,
    )
    frame = hourly_frame(weather.cases[weather.basis], pv_ac_kw_per_kwp, load_kw, result, LOCAL_TZ)
    lines = homer_load_lines(load_kw, LOCAL_TZ)
    errors = reproduction_errors(report, frame, result, weather.basis)
    run_id = "files-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    out_dir = _resolve(str(args.out)) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    write_ascii_lf(out_dir / "hourly.csv", frame.to_csv(index=False, lineterminator="\n"))
    write_ascii_lf(out_dir / "homer_load_kw.txt", "\n".join(lines) + "\n")
    files = {
        "hourly.csv": hashlib.sha256((out_dir / "hourly.csv").read_bytes()).hexdigest(),
        "homer_load_kw.txt": hashlib.sha256((out_dir / "homer_load_kw.txt").read_bytes()).hexdigest(),
    }
    doc = engineer_doc(
        report,
        run_id=run_id,
        basis_case=weather.basis,
        local_tz=LOCAL_TZ,
        frame=frame,
        result=result,
        homer_lines=lines,
        errors=errors,
        files=files,
        wall_s=float(time.time() - t0),
    )
    write_ascii_lf(out_dir / "engineer_files.json", json.dumps(doc, indent=2, ensure_ascii=True) + "\n")
    print(run_id)
    print("rows %d homer_lines %d" % (len(frame), len(lines)))
    print("sums " + json.dumps(doc["sums"], ensure_ascii=True))
    if errors:
        print("reproduced NO")
        for message in errors:
            print(message)
        return 3
    print("reproduced yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
