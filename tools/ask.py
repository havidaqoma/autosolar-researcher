"""Ask one question, get one checked study. Thin wiring of the real services around autosolar.study.run_study.

  AUTOSOLAR_ENV_FILE=path/to/.env AUTOSOLAR_CAMS_EMAIL=<address registered at soda-pro.com> \
      uv run python tools/ask.py "Is solar plus battery worth it for Karimunjawa?"

The model key (MODEL_API_KEY) and the CAMS address are read from the environment or from the env file; neither is
printed or written. The CAMS address is read only when weather is fetched, so a reused study or a refusal needs only
the model key (T19). Service data are cached under runs/weather_cache/, studies land in runs/studies/<run_hash>/.
While the study runs (about 10 minutes), one line is printed when it reaches a new stage and a still-working line
after 30 s of quiet (tests/test_ask_progress.py). The lines only report: the study code and its results are unchanged.
A question the tool cannot study (a site more than 30 km from Karimunjawa, outside Indonesia, or not found) ends
with a plain answer and exit code 2.
"""
import argparse
import functools
import hashlib
import json
import os
import pathlib
import sys
import threading
import time
import uuid

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import autosolar.study as study_module  # noqa: E402
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402
from autosolar.request import SiteNotFound, UnsupportedQuestion  # noqa: E402
from autosolar.study import (DEMAND_RADIUS_KM, KARIMUNJAWA_DEG, UnsupportedSite, haversine_km,  # noqa: E402
                             run_study)
from autosolar.weather import CASE_NAMES, build_weather_cases, cached_fetchers, default_fetchers  # noqa: E402


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

# Functions run_study calls by name in autosolar.study, and what the terminal says when the study reaches them.
STAGES = (
    ("parse_question", "Muse Spark reads the question"),
    ("geocode", "OpenStreetMap finds the place"),
    ("simulate_pv", "pvlib: hourly solar output for each weather case"),
    ("build_demand_cases", "hourly load from the published Karimunjawa study"),
    ("dispatch_grid", "hour-by-hour run of every solar and battery size on the grid"),
    ("cost_table", "cost of electricity for every design"),
    ("sensitivity_table", "sensitivity: costs and load moved down and up"),
    ("reserve_case", "firmness: diesel units kept running as a reserve"),
    ("diesel_size_case", "firmness: the design search with another diesel unit size"),
    ("duration_case", "firmness: the design search with another battery duration"),
)
WEATHER_LABEL = "weather: %d hourly cases (%s); files saved before are reused" % (len(CASE_NAMES), ", ".join(CASE_NAMES))


class Progress:
    """Prints one line when the study reaches a new stage, and a still-working line after heartbeat_s of quiet.
    Only fixed labels and the elapsed time are printed: no URL, key or address."""

    def __init__(self, out=None, heartbeat_s=30.0, clock=time.perf_counter):
        self.out = out
        self.heartbeat_s = float(heartbeat_s)
        self.clock = clock
        self.t0 = clock()
        self.last = self.t0
        self.label = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def _say(self, text):
        e = int(self.clock() - self.t0)
        print("[%d:%02d] %s" % (e // 60, e % 60, text), file=self.out or sys.stdout, flush=True)
        self.last = self.clock()

    def stage(self, label):
        with self._lock:
            if label != self.label:
                self.label = label
                self._say(label)

    def wrap(self, fn, label):
        @functools.wraps(fn)
        def reported(*args, **kwargs):
            self.stage(label)
            return fn(*args, **kwargs)
        return reported

    def tick(self):
        with self._lock:
            if self.label is not None and self.clock() - self.last >= self.heartbeat_s:
                self._say("still working, last step: " + self.label)

    def _loop(self):
        while not self._stop.wait(min(1.0, self.heartbeat_s)):
            self.tick()

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="ask-progress", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)

    def running(self):
        return self._thread is not None and self._thread.is_alive()


SUMMARY_KEYS = ("best_pv_kwp", "best_battery_kwh", "best_lcoe_usd_per_kwh", "diesel_only_lcoe_usd_per_kwh")


def summary_lines(report, run_hash, reused, elapsed_s):
    """The last three lines: the answer, the checks and the run hash, short enough to stay on screen."""
    facts = [report["facts"][key] for key in SUMMARY_KEYS]
    labels = {f["label"] for f in facts}

    def value(f):
        return f["text"] + " " + f["unit"] + ("" if len(labels) == 1 else " (" + f["label"] + ")")

    answer = "Answer: %s solar and %s battery at %s; diesel only %s" % tuple(value(f) for f in facts)
    if len(labels) == 1:
        answer += " (" + labels.pop() + ")"
    gates = report["gates"]
    return [answer, "Checks: %d of %d passed" % (sum(1 for g in gates if g["passed"]), len(gates)),
            "run %s %s %s s" % (run_hash, "reused" if reused else "new", elapsed_s)]


def instrument(module, progress, stages=STAGES):
    """Swap each named function in module for a wrapper that reports its stage; returns the originals."""
    missing = [name for name, _ in stages if not callable(getattr(module, name, None))]
    if missing:
        raise ValueError("no such function to report: " + ", ".join(missing))
    saved = {}
    for name, label in stages:
        saved[name] = getattr(module, name)
        setattr(module, name, progress.wrap(saved[name], label))
    return saved


def restore(module, saved):
    for name, fn in saved.items():
        setattr(module, name, fn)
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

    progress = Progress()

    def weather_fn(lat_deg, lon_deg):
        progress.stage(WEATHER_LABEL)
        return build_weather_cases(lat_deg, lon_deg, env_value("AUTOSOLAR_CAMS_EMAIL"), fetchers)

    run_id = "study-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=120.0)
    if args.live:
        client = LiveClient(client)
    t = time.perf_counter()
    saved = instrument(study_module, progress)
    progress.start()
    try:
        out = run_study(args.question, client=client, http_get=requests.get, weather_fn=weather_fn,
                        inputs_path=args.inputs, runs_dir=args.runs, run_id=run_id, sourcing_path=args.sourcing,
                        checks_path=checks)
    except REFUSALS as exc:
        progress.stop()
        restore(study_module, saved)
        for line in refusal_lines(exc, args.question, args.runs):
            print(line)
        sys.exit(2)
    finally:
        progress.stop()
        restore(study_module, saved)
    elapsed_s = round(time.perf_counter() - t, 1)
    print("run", out.run_hash, "reused" if out.reused else "new", elapsed_s, "s")
    print("folder", out.run_dir)
    for key in ("best_pv_kwp", "best_battery_kwh", "best_lcoe_usd_per_kwh", "diesel_only_lcoe_usd_per_kwh",
                "best_renewable_pct", "fuel_saved_l_yr", "co2_saved_t_yr", "break_even_fuel_usd_per_l"):
        f = out.report["facts"][key]
        print(" ", key, f["text"], f["unit"], "(" + f["label"] + ")")
    print("gates", [(g["gate"], g["scope"], g["passed"]) for g in out.report["gates"]])
    if out.report.get("firmness") is not None:
        for item in out.report["firmness"]["items"]:
            print(" ", item["key"], item["text"], item["unit"], "(" + item["label"] + ")")
    print()
    for line in summary_lines(out.report, out.run_hash, out.reused, elapsed_s):
        print(line)


if __name__ == "__main__":
    main()
