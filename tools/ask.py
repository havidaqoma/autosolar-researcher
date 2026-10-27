"""Ask one question, get one checked study. Thin wiring of the real services around autosolar.study.run_study.

  AUTOSOLAR_ENV_FILE=path/to/.env AUTOSOLAR_CAMS_EMAIL=<address registered at soda-pro.com> \
      uv run python tools/ask.py "Is solar plus battery worth it for Karimunjawa?"

The model key (MODEL_API_KEY) and the CAMS address are read from the environment or from the env file; neither is
printed or written. Service data are cached under runs/weather_cache/, studies land in runs/studies/<run_hash>/.
"""
import argparse
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
from autosolar.study import run_study  # noqa: E402
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
    args = ap.parse_args()
    os.environ["MODEL_API_KEY"] = env_value("MODEL_API_KEY")
    cams_email = env_value("AUTOSOLAR_CAMS_EMAIL")
    fetchers = cached_fetchers(default_fetchers(), ROOT / "runs" / "weather_cache")

    def weather_fn(lat_deg, lon_deg):
        return build_weather_cases(lat_deg, lon_deg, cams_email, fetchers)

    run_id = "study-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=120.0)
    if args.live:
        client = LiveClient(client)
    t = time.perf_counter()
    out = run_study(args.question, client=client, http_get=requests.get, weather_fn=weather_fn,
                    inputs_path=args.inputs, runs_dir=args.runs, run_id=run_id)
    print("run", out.run_hash, "reused" if out.reused else "new", round(time.perf_counter() - t, 1), "s")
    print("folder", out.run_dir)
    for key in ("best_pv_kwp", "best_battery_kwh", "best_lcoe_usd_per_kwh", "diesel_only_lcoe_usd_per_kwh",
                "best_renewable_pct", "fuel_saved_l_yr", "co2_saved_t_yr", "break_even_fuel_usd_per_l"):
        f = out.report["facts"][key]
        print(" ", key, f["text"], f["unit"], "(" + f["label"] + ")")
    print("gates", [(g["gate"], g["scope"], g["passed"]) for g in out.report["gates"]])


if __name__ == "__main__":
    main()
