"""Ask one question, get one checked study. Thin wiring of the real services around autosolar.study.run_study.

  AUTOSOLAR_ENV_FILE=path/to/.env AUTOSOLAR_CAMS_EMAIL=<address registered at soda-pro.com> \
      uv run python tools/ask.py "Is solar plus battery worth it for Karimunjawa?"

The model key (MODEL_API_KEY) and the CAMS address are read from the environment or from the env file; neither is
printed or written. The CAMS address is read only when weather is fetched, so a reused study or a refusal needs only
the model key (T19). Service data are cached under runs/weather_cache/, studies land in runs/studies/<run_hash>/.
A question the tool cannot study (a site more than 30 km from Karimunjawa, outside Indonesia, or not found) ends
with a plain answer and exit code 2.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys
import time
import uuid

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402
from autosolar.request import SiteNotFound, UnsupportedQuestion  # noqa: E402
from autosolar.study import (DEMAND_RADIUS_KM, KARIMUNJAWA_DEG, UnsupportedSite, haversine_km,  # noqa: E402
                             run_study)
from autosolar.weather import build_weather_cases, cached_fetchers, default_fetchers  # noqa: E402


def env_value(name):
    if os.environ.get(name):
        return os.environ[name]
    env_file = pathlib.Path(os.environ.get("AUTOSOLAR_ENV_FILE", ROOT / ".env"))
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    sys.exit(name + " is not set (environment or AUTOSOLAR_ENV_FILE)")


REFUSALS = (UnsupportedSite, UnsupportedQuestion, SiteNotFound)
LOAD_LINE = "The hourly load comes from one published study of Karimunjawa. A new site needs its own hourly load."


def refusal_lines(exc, question, runs_dir):
    """Plain lines for a question the tool will not study (T19). Reads the request file run_study cached."""
    lines = ["No study: " + str(exc) + "."]
    if isinstance(exc, UnsupportedSite):
        name = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:16] + ".json"
        req_file = pathlib.Path(runs_dir) / "requests" / name
        if req_file.is_file():
            site = json.loads(req_file.read_text(encoding="utf-8"))["site"]
            d_km = haversine_km(site["lat_deg"], site["lon_deg"], *KARIMUNJAWA_DEG)
            lines.append("%s (%s) is %s km from Karimunjawa; the demand model covers sites within %s km (computed)."
                         % (site["name"], site["display_name"], format(round(d_km), ","),
                            format(round(DEMAND_RADIUS_KM), ",")))
    lines.append(LOAD_LINE)
    return lines


class LiveClient:
    """Passes live=True on every call, so the ledger applies the live caps (USD 2 per run, USD 5 per UTC day)."""

    def __init__(self, client):
        self._client = client

    def respond(self, *args, **kwargs):
        kwargs["live"] = True
        return self._client.respond(*args, **kwargs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question")
    ap.add_argument("--inputs", default=str(ROOT / "config" / "default_inputs.json"))
    ap.add_argument("--runs", default=str(ROOT / "runs" / "studies"))
    ap.add_argument("--live", action="store_true", help="count the calls as public live use (live caps apply)")
    ap.add_argument("--sourcing", default=None,
                    help="sourcing.json from tools/source.py; the study reads its inputs file and checks it (G6)")
    ap.add_argument("--checks", default=str(ROOT / "config" / "study_checks.json"),
                    help="check inputs for the firmness section (T11b); 'none' leaves the section out")
    args = ap.parse_args()
    checks = None if args.checks == "none" else args.checks
    if args.sourcing is not None:
        args.inputs = str(pathlib.Path(args.sourcing).with_name("inputs.json"))
    os.environ["MODEL_API_KEY"] = env_value("MODEL_API_KEY")
    fetchers = cached_fetchers(default_fetchers(), ROOT / "runs" / "weather_cache")

    def weather_fn(lat_deg, lon_deg):
        return build_weather_cases(lat_deg, lon_deg, env_value("AUTOSOLAR_CAMS_EMAIL"), fetchers)

    run_id = "study-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=120.0)
    if args.live:
        client = LiveClient(client)
    t = time.perf_counter()
    try:
        out = run_study(args.question, client=client, http_get=requests.get, weather_fn=weather_fn,
                        inputs_path=args.inputs, runs_dir=args.runs, run_id=run_id, sourcing_path=args.sourcing,
                        checks_path=checks)
    except REFUSALS as exc:
        for line in refusal_lines(exc, args.question, args.runs):
            print(line)
        sys.exit(2)
    print("run", out.run_hash, "reused" if out.reused else "new", round(time.perf_counter() - t, 1), "s")
    print("folder", out.run_dir)
    for key in ("best_pv_kwp", "best_battery_kwh", "best_lcoe_usd_per_kwh", "diesel_only_lcoe_usd_per_kwh",
                "best_renewable_pct", "fuel_saved_l_yr", "co2_saved_t_yr", "break_even_fuel_usd_per_l"):
        f = out.report["facts"][key]
        print(" ", key, f["text"], f["unit"], "(" + f["label"] + ")")
    print("gates", [(g["gate"], g["scope"], g["passed"]) for g in out.report["gates"]])
    if out.report.get("firmness") is not None:
        for item in out.report["firmness"]["items"]:
            print(" ", item["key"], item["text"], item["unit"], "(" + item["label"] + ")")


if __name__ == "__main__":
    main()
