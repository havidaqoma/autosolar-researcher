"""Stage S3 run: source the target inputs by web search, check every citation, write a sourced inputs file.

  AUTOSOLAR_ENV_FILE=path/to/.env uv run python tools/source.py [--only name ...]
  ... tools/source.py --carry runs/sourcing/<earlier>/sourcing.json --only <inputs assumed there>
  ... tools/source.py --judge local   (the T10f rule: the local judge casts all 3 votes)

Orchestrator glue around autosolar.sourcing (T10b). The local support judge is Muse Glimmer on this PC
(llama-server, the config measured in the prep repo speed test); the tool starts it when it is not already up and
stops what it started. By default (T19) it casts votes 1 and 2 and muse-wonder-1.0 casts vote 3 (the T17 panel);
every vote is kept in the meta. Output: runs/sourcing/<run_id>/sourcing.json (G6 checked on read) and inputs.json, which
`tools/ask.py --inputs` reads. The model key is read from the environment or the env file and never printed.
"""
import argparse
import dataclasses
import functools
import json
import os
import pathlib
import subprocess
import sys
import time
import uuid

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from ask import env_value  # noqa: E402
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402
from autosolar.cite_check import JUDGE_VOTES  # noqa: E402
from autosolar.sourcing import (GLIMMER_URL, g6_check, glimmer_judge, judge_panel, load_targets,  # noqa: E402
                                read_sourcing, source_inputs, wonder_judge, write_sourcing)

LLAMA = pathlib.Path("F:/llm-models/llama-b11900/llama-server.exe")
MD = pathlib.Path("F:/llm-models/muse-glimmer")
SERVER = [str(LLAMA), "-m", str(MD / "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf"), "-a", "muse-glimmer",
          "-c", "32768", "-np", "1", "--host", "127.0.0.1", "--port", "8093", "--no-mmproj",
          "-md", str(MD / "dflash-Muse-Glimmer-30B-Q4_K_M.gguf"), "--spec-type", "draft-dflash", "-ngld", "99",
          "--spec-draft-n-max", "4"]
HEALTH = GLIMMER_URL.replace("/v1/chat/completions", "/health")
JUDGE_NAME = "Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low"
PANEL_JUDGE_NAME = (JUDGE_NAME + " (votes 1 and 2) and muse-wonder-1.0 (vote 3), yes needed in all "
                    + str(JUDGE_VOTES) + " votes")


def server_up():
    try:
        return requests.get(HEALTH, timeout=5).status_code == 200
    except requests.RequestException:
        return False


def start_server(log_path):
    log = open(log_path, "wb")
    proc = subprocess.Popen(SERVER, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(120):
        if server_up():
            return proc
        if proc.poll() is not None:
            break
        time.sleep(5)
    proc.terminate()
    sys.exit("Glimmer server did not come up; see " + str(log_path))


class TimedJudge:
    def __init__(self):
        self.seconds = []

    def __call__(self, prompt):
        t = time.perf_counter()
        try:
            return glimmer_judge(prompt)
        finally:
            self.seconds.append(round(time.perf_counter() - t, 1))


class VoteLog:
    """Wraps one judge and keeps every raw answer (or the error) with its time in seconds (T19)."""

    def __init__(self, name, fn, log):
        self.name, self.fn, self.log = name, fn, log

    def __call__(self, prompt):
        t = time.perf_counter()
        try:
            out = self.fn(prompt)
        except Exception as exc:
            self.log.append({"judge": self.name, "seconds": round(time.perf_counter() - t, 1),
                             "error": type(exc).__name__ + ": " + str(exc)[:200]})
            raise
        self.log.append({"judge": self.name, "seconds": round(time.perf_counter() - t, 1),
                         "raw": out[:2000] if isinstance(out, str) else repr(out)[:2000]})
        return out


def build_judge(mode, *, local_fn, wonder_fn, log):
    """Return (judge_fn, judge_name). "panel": local, local, Wonder (T17); "local": the local judge for all votes."""
    if mode == "panel":
        return judge_panel(VoteLog("local", local_fn, log), VoteLog("wonder", wonder_fn, log)), PANEL_JUDGE_NAME
    if mode == "local":
        return VoteLog("local", local_fn, log), JUDGE_NAME
    raise ValueError("judge mode must be panel or local")


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=str(ROOT / "config" / "sourcing_targets.json"))
    ap.add_argument("--inputs", default=str(ROOT / "config" / "default_inputs.json"))
    ap.add_argument("--only", nargs="*", help="input names to source (default: all targets)")
    ap.add_argument("--carry", help="earlier sourcing.json: keep its rows, search only the --only inputs (assumed)")
    ap.add_argument("--out", default=str(ROOT / "runs" / "sourcing"))
    ap.add_argument("--judge", choices=["panel", "local"], default="panel",
                    help="panel (default): local judge votes 1 and 2, muse-wonder-1.0 vote 3; local: all 3 local")
    return ap


def carry_plan(carry_path, all_targets, only, fx):
    """Check an earlier sourcing file for --carry. Returns its inputs, the rows kept as they are, and its run id.

    Rule (T10e run 3): only inputs that were assumed in the earlier run are searched again; every other row is kept
    unchanged, so no checked value is replaced or shopped for."""
    prior_raw, prior_rows, prior_meta = read_sourcing(carry_path)  # G6 checked on read
    by_input = {r.input: r for r in prior_rows}
    names = [t.input for t in all_targets]
    if sorted(by_input) != sorted(names) or len(prior_rows) != len(names):
        sys.exit("carry run has a different target list")
    if prior_meta.get("fx_idr_per_usd") != fx:
        sys.exit("carry run used a different fx")
    for name in only:
        if by_input[name].status != "assumed":
            sys.exit(name + " is checked in the carried run; only assumed inputs are searched again")
    carried = [by_input[n] for n in names if n not in set(only)]
    return prior_raw, carried, prior_meta.get("run_id")


def merge_rows(carried, new_rows, all_targets):
    """Carried rows plus new rows, in target file order, one row per target."""
    order = [t.input for t in all_targets]
    rows = sorted(list(carried) + list(new_rows), key=lambda r: order.index(r.input))
    if [r.input for r in rows] != order:
        sys.exit("merged rows do not cover each target once")
    return rows


def main():
    args = build_parser().parse_args()
    all_targets, fx = load_targets(args.targets)
    targets = all_targets
    if args.only:
        unknown = sorted(set(args.only) - {t.input for t in targets})
        if unknown:
            sys.exit("not in targets: " + ", ".join(unknown))
        targets = [t for t in targets if t.input in args.only]
    carried, carried_run = [], None
    if args.carry:
        if not args.only:
            sys.exit("--carry needs --only")
        base_raw, carried, carried_run = carry_plan(args.carry, all_targets, args.only, fx)
    else:
        base_raw = json.loads(pathlib.Path(args.inputs).read_text(encoding="utf-8"))
    os.environ["MODEL_API_KEY"] = env_value("MODEL_API_KEY")
    run_id = "sourcing-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    out_dir = pathlib.Path(args.out) / run_id
    out_dir.mkdir(parents=True)
    proc = None if server_up() else start_server(out_dir / "glimmer_server.log")
    judge = TimedJudge()
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=300.0)
    votes = []
    wonder = functools.partial(wonder_judge, client=client, run_id=run_id)
    judge_fn, judge_name = build_judge(args.judge, local_fn=judge, wonder_fn=wonder, log=votes)
    http_get = functools.partial(requests.get)
    t = time.perf_counter()
    try:
        raw, new_rows = source_inputs(base_raw, targets, client=client, run_id=run_id, http_get=http_get,
                                      judge_fn=judge_fn, judge_name=judge_name, fx_idr_per_usd=fx)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=60)
    rows = merge_rows(carried, new_rows, all_targets) if args.carry else new_rows
    ok, detail = g6_check(rows, raw)
    meta = {"run_id": run_id, "targets": args.targets, "base_inputs": args.carry or args.inputs, "judge": judge_name,
            "judge_mode": args.judge, "votes": votes, "judge_seconds": judge.seconds, "fx_idr_per_usd": fx,
            "wall_s": round(time.perf_counter() - t, 1),
            "search_cost_usd": round(sum(r.search_cost_usd for r in new_rows), 6), "g6": [ok, detail]}
    if args.carry:
        meta["carried_from"] = carried_run
        meta["carried_inputs"] = [r.input for r in carried]
        meta["searched_inputs"] = [r.input for r in new_rows]
    write_sourcing(out_dir / "sourcing.json", raw, rows, meta)
    read_sourcing(out_dir / "sourcing.json")
    (out_dir / "inputs.json").write_text(json.dumps(raw, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    print("run", run_id, meta["wall_s"], "s", "search USD", meta["search_cost_usd"], "judge s", judge.seconds)
    print("G6", ok, detail)
    for r in rows:
        d = dataclasses.asdict(r)
        print(" ", r.input, "(carried)" if r in carried else "", r.status, r.value_used, r.unit, "(" + r.label + ")", r.quote_kind, "page", r.page,
              "| as written", d["value_as_written"], d["unit_as_written"], "|", r.title[:60], "|", r.url[:90])
        for reason in r.reasons:
            print("     reason:", reason[:200])
    for v in votes:
        print("  vote:", v["judge"], v["seconds"], "s", (v.get("raw") or v.get("error") or "")[:160])
    print("folder", out_dir)


if __name__ == "__main__":
    main()
