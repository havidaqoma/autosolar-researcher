"""Run one figure check plan (rules: docs/smoke/FIGURE_CHECK_RULES.md). Orchestrator tooling.

  AUTOSOLAR_ENV_FILE=path/to/.env uv run python tools/figure_check.py config/figure_checks/hiron2021_fig7.json

Calls SAM 3.1 and Muse Spark through the chart reader once, no retry. Writes
runs/figure_checks/<run id>/figure_check.json and prints the run id and the verdict.
"""
import json
import os
import pathlib
import secrets
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autosolar.chart_reader import sam_segment_fn, spark_label_fn  # noqa: E402
from autosolar.demand import HIRON_2021_LOAD_KW  # noqa: E402
from autosolar.figure_check import load_plan, run_figure_check  # noqa: E402
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: figure_check.py <plan.json>")
    plan_path = pathlib.Path(sys.argv[1])
    plan = load_plan(plan_path)
    image = (ROOT / plan["image"]).read_bytes()
    env_file = pathlib.Path(os.environ.get("AUTOSOLAR_ENV_FILE", ROOT / ".env"))
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("MODEL_API_KEY="):
            os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip()
    run_id = "figure-" + time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=180.0)
    t0 = time.time()
    out = run_figure_check(plan, image, list(HIRON_2021_LOAD_KW), sam_segment_fn(client, run_id),
                           spark_label_fn(client, run_id))
    out["run_id"] = run_id
    out["plan_path"] = plan_path.as_posix()
    out["wall_s"] = round(time.time() - t0, 1)
    run_dir = ROOT / "runs" / "figure_checks" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "figure_check.json").write_text(json.dumps(out, indent=2) + "\n", encoding="ascii")
    c = out["comparison"] or {}
    print(run_id, out["verdict"], out["reason"], "ratio", c.get("ratio"), "hours", len(c.get("hours") or []))


if __name__ == "__main__":
    main()
