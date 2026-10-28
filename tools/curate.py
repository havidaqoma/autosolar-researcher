"""Stage S5 curated run: replace weak inputs with hand picked values, write a post hoc sourcing file.

  python tools/curate.py runs/sourcing/<base>/sourcing.json [--curated ...] [--targets ...] [--runs ...]

Orchestrator glue around autosolar.curate (T16). No network and no model call.
Output: <runs>/curated-<stamp>/sourcing.json (G6 checked on read) and inputs.json.
"""
import argparse
import pathlib
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.curate import curate_run  # noqa: E402
from autosolar.sourcing import g6_check, read_sourcing  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="base sourcing.json path")
    ap.add_argument("--curated", default=str(ROOT / "config" / "curated_inputs.json"))
    ap.add_argument("--targets", default=str(ROOT / "config" / "sourcing_targets.json"))
    ap.add_argument("--runs", default=str(ROOT / "runs" / "sourcing"))
    args = ap.parse_args()
    run_id = "curated-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    folder = curate_run(args.base, args.curated, args.targets, args.runs, run_id)
    raw, rows, _meta = read_sourcing(folder / "sourcing.json")
    ok, detail = g6_check(rows, raw)
    print("folder " + str(folder))
    print("G6 " + str(ok) + " " + detail)


if __name__ == "__main__":
    main()
