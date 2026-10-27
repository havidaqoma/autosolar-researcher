"""Stage S3 run: source the target inputs by web search, check every citation, write a sourced inputs file.

  AUTOSOLAR_ENV_FILE=path/to/.env uv run python tools/source.py [--only name ...]

Orchestrator glue around autosolar.sourcing (T10b). The support judge is Muse Glimmer on this PC (llama-server, the
config measured in the prep repo speed test); the tool starts it when it is not already up and stops what it
started. Output: runs/sourcing/<run_id>/sourcing.json (G6 checked on read) and inputs.json, which
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
from autosolar.sourcing import (GLIMMER_URL, g6_check, glimmer_judge, load_targets, read_sourcing,  # noqa: E402
                                source_inputs, write_sourcing)

LLAMA = pathlib.Path("F:/llm-models/llama-b11900/llama-server.exe")
MD = pathlib.Path("F:/llm-models/muse-glimmer")
SERVER = [str(LLAMA), "-m", str(MD / "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf"), "-a", "muse-glimmer",
          "-c", "32768", "-np", "1", "--host", "127.0.0.1", "--port", "8093", "--no-mmproj",
          "-md", str(MD / "dflash-Muse-Glimmer-30B-Q4_K_M.gguf"), "--spec-type", "draft-dflash", "-ngld", "99",
          "--spec-draft-n-max", "4"]
HEALTH = GLIMMER_URL.replace("/v1/chat/completions", "/health")
JUDGE_NAME = "Muse Glimmer 30B Q4_K_M, local llama.cpp, reasoning low"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", default=str(ROOT / "config" / "sourcing_targets.json"))
    ap.add_argument("--inputs", default=str(ROOT / "config" / "default_inputs.json"))
    ap.add_argument("--only", nargs="*", help="input names to source (default: all targets)")
    ap.add_argument("--out", default=str(ROOT / "runs" / "sourcing"))
    args = ap.parse_args()
    targets, fx = load_targets(args.targets)
    if args.only:
        unknown = sorted(set(args.only) - {t.input for t in targets})
        if unknown:
            sys.exit("not in targets: " + ", ".join(unknown))
        targets = [t for t in targets if t.input in args.only]
    base_raw = json.loads(pathlib.Path(args.inputs).read_text(encoding="utf-8"))
    os.environ["MODEL_API_KEY"] = env_value("MODEL_API_KEY")
    run_id = "sourcing-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    out_dir = pathlib.Path(args.out) / run_id
    out_dir.mkdir(parents=True)
    proc = None if server_up() else start_server(out_dir / "glimmer_server.log")
    judge = TimedJudge()
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=300.0)
    http_get = functools.partial(requests.get)
    t = time.perf_counter()
    try:
        raw, rows = source_inputs(base_raw, targets, client=client, run_id=run_id, http_get=http_get,
                                  judge_fn=judge, judge_name=JUDGE_NAME, fx_idr_per_usd=fx)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=60)
    ok, detail = g6_check(rows, raw)
    meta = {"run_id": run_id, "targets": args.targets, "base_inputs": args.inputs, "judge": JUDGE_NAME,
            "judge_seconds": judge.seconds, "fx_idr_per_usd": fx, "wall_s": round(time.perf_counter() - t, 1),
            "search_cost_usd": round(sum(r.search_cost_usd for r in rows), 6), "g6": [ok, detail]}
    write_sourcing(out_dir / "sourcing.json", raw, rows, meta)
    read_sourcing(out_dir / "sourcing.json")
    (out_dir / "inputs.json").write_text(json.dumps(raw, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    print("run", run_id, meta["wall_s"], "s", "search USD", meta["search_cost_usd"], "judge s", judge.seconds)
    print("G6", ok, detail)
    for r in rows:
        d = dataclasses.asdict(r)
        print(" ", r.input, r.status, r.value_used, r.unit, "(" + r.label + ")", r.quote_kind, "page", r.page,
              "| as written", d["value_as_written"], d["unit_as_written"], "|", r.title[:60], "|", r.url[:90])
        for reason in r.reasons:
            print("     reason:", reason[:200])
    print("folder", out_dir)


if __name__ == "__main__":
    main()
