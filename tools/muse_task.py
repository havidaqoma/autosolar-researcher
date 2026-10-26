"""Run one Muse Code task headless and log its measured usage and computed cost.

Usage:
    python tools/muse_task.py T01 docs/specs/T01_ledger.md [--steps 40] [--effort high] [--timeout 1800]
    python tools/muse_task.py T01b docs/specs/T01_ledger.md --feedback build_logs/T01_pytest.txt

Muse Code always runs on muse-spark-1.3-contributor (rule D15: its default model is billed at the standard price).
The API key comes from the environment variable MODEL_API_KEY, or from the file named by AUTOSOLAR_ENV_FILE
(default: .env in the repo root). The key is never printed or logged.

Outputs: build_logs/<task>.jsonl (raw event stream, not committed) and one line in ledger/build_usage.jsonl
(model, tokens, computed USD, wall time, files written, final answer).
"""
import argparse
import glob
import json
import os
import pathlib
import subprocess
import sys
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL = "muse-spark-1.3-contributor"
# USD per 1M tokens, contributor mode (Meta pricing page, docs): input, cached input, output
PRICE = {"input": 0.10, "cached": 0.002, "output": 0.20}
BUILD_CAP_USD = float(os.environ.get("AUTOSOLAR_BUILD_CAP_USD", "60"))
STALL_S = 600


def load_key() -> str:
    key = os.environ.get("MODEL_API_KEY", "")
    if key:
        return key
    env_file = pathlib.Path(os.environ.get("AUTOSOLAR_ENV_FILE", ROOT / ".env"))
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("MODEL_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("MODEL_API_KEY not found")


def muse_exe() -> str:
    found = sorted(glob.glob(os.path.join(os.environ["LOCALAPPDATA"], "Programs", "muse", "muse-bin-*.exe")))
    if not found:
        sys.exit("Muse Code binary not found")
    return found[-1]


def spent_so_far(ledger: pathlib.Path) -> float:
    if not ledger.exists():
        return 0.0
    return sum(json.loads(l).get("cost_usd_computed", 0.0) for l in ledger.read_text(encoding="utf-8").splitlines() if l)


def cost(u: dict) -> float:
    fresh = u.get("input_tokens", 0) - u.get("cached_tokens", 0)
    return (fresh * PRICE["input"] + u.get("cached_tokens", 0) * PRICE["cached"]
            + u.get("output_tokens", 0) * PRICE["output"]) / 1e6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task")
    ap.add_argument("spec")
    ap.add_argument("--steps", type=int, default=40)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--feedback", help="file with test output to fix")
    a = ap.parse_args()

    ledger = ROOT / "ledger" / "build_usage.jsonl"
    ledger.parent.mkdir(exist_ok=True)
    if spent_so_far(ledger) >= BUILD_CAP_USD:
        sys.exit(f"build cap reached: USD {spent_so_far(ledger):.2f} of {BUILD_CAP_USD}")
    logs = ROOT / "build_logs"
    logs.mkdir(exist_ok=True)

    prompt = (f"Task {a.task}. Read AGENTS.md, then the spec {a.spec}, then the acceptance tests it names. "
              "Write the code so the acceptance tests pass. Follow every rule in AGENTS.md.")
    if a.feedback:
        prompt += (f" The orchestrator ran the tests after your last attempt; the output is in {a.feedback}. "
                   "Fix the code so these failures go away. Do not edit the acceptance tests.")
    cmd = [muse_exe(), "exec", "--json", "--model", MODEL, "--reasoning-effort", a.effort,
           "--trust-workspace", "--approval-mode", "never", "--sandbox-network", "restricted",
           "--no-foreign-personal-context", "--disable-web-tools", "--max-model-steps", str(a.steps), prompt]
    env = dict(os.environ, META_API_KEY=load_key())

    t0 = time.time()
    out_path, err_path = logs / f"{a.task}.jsonl", logs / f"{a.task}.err"
    last = [time.time()]
    with open(out_path, "w", encoding="utf-8") as out, open(err_path, "w", encoding="utf-8") as err:
        p = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=err, text=True,
                             encoding="utf-8", errors="replace")

        def pump():
            for line in p.stdout:
                out.write(line)
                out.flush()
                last[0] = time.time()

        th = threading.Thread(target=pump, daemon=True)
        th.start()
        killed = None
        while p.poll() is None:
            time.sleep(5)
            if time.time() - t0 > a.timeout:
                killed = "timeout"
            elif time.time() - last[0] > STALL_S:
                killed = "stall"
            if killed:
                p.kill()
                break
        p.wait()
        th.join(timeout=10)

    usage, final, files, tools = {}, "", set(), {}
    for line in out_path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind, pl = e.get("payload_type", ""), e.get("payload", {})
        if kind == "run.usage":
            for m in pl.get("models", []):
                u = usage.setdefault(m["model"], {})
                for k in ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens", "calls"):
                    u[k] = u.get(k, 0) + m.get(k, 0)
        elif kind == "run.terminal.completed":
            final = pl.get("text", "")
        elif kind == "tool.result":
            ef = pl.get("edit_facts") or pl.get("correlation_facts") or {}
            name = ef.get("tool_name", "?")
            tools[name] = tools.get(name, 0) + 1
            for k in ("path", "file_path"):
                if isinstance(ef.get(k), str):
                    files.add(ef[k])

    wrong = [m for m in usage if m != MODEL]
    row = {
        "task": a.task, "spec": a.spec, "feedback": a.feedback, "started_unix": round(t0),
        "wall_s": round(time.time() - t0, 1), "rc": p.returncode, "killed": killed, "effort": a.effort,
        "usage": usage, "cost_usd_computed": round(sum(cost(u) for u in usage.values()), 6),
        "wrong_model": wrong, "tool_results": tools, "files_reported": sorted(files),
        "final_answer": final[:3000], "muse_version": pathlib.Path(muse_exe()).stem,
    }
    with open(ledger, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps({k: row[k] for k in ("task", "wall_s", "rc", "killed", "usage", "cost_usd_computed",
                                           "wrong_model", "tool_results")}, indent=1))
    if wrong:
        print("WARNING: usage billed to a model other than", MODEL, wrong)


if __name__ == "__main__":
    main()
