"""Stage S9 review: a second model (Muse Wonder) reads a finished study report and lists what it would question.

  AUTOSOLAR_ENV_FILE=path/to/.env uv run python tools/review.py runs/studies/<hash> [--paper runs/paper_checks/<id>]

Orchestrator glue. The reviewer is never the model that wrote the study (the study's text comes from scripts and
Muse Spark; the reviewer is muse-wonder-1.0). One paid call. Every point names the report section that already
answers it, or null. A section name that is not a heading of the report is replaced by null and counted, so the
reviewer cannot claim an answer the report does not hold. Output: runs/reviews/<run_id>/review.json and review.md.
The model key is read from the environment or the env file and never printed.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from ask import env_value  # noqa: E402
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402

MODEL = "muse-wonder-1.0"
MAX_POINTS = 10
PROMPT = (
    "You are an independent reviewer. Another system wrote the pre-feasibility study below for an island power "
    "grid. Read all of it. List at most 10 points that a careful power engineer, utility planner or investor would "
    "raise: numbers that look wrong or unsupported, risks the study leaves out, methods that do not fit the "
    "question, and claims stronger than the evidence. Be specific and quote the number you question. For each "
    "point, give the heading of the report section that already answers it, copied exactly as written without the "
    "## marks, or null when no section answers it. Return only JSON, no prose: "
    "{\"points\": [{\"point\": text, \"addressed_in\": heading or null}]}\n\n"
)


def headings(md):
    return [m.group(1).strip() for m in re.finditer(r"^## (.+)$", md, flags=re.M)]


def parse_points(text, heads):
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    data = json.loads(t)
    if not isinstance(data, dict) or not isinstance(data.get("points"), list):
        raise ValueError("review must be a dict with a points list")
    points, fixed = [], 0
    for p in data["points"][:MAX_POINTS]:
        if not isinstance(p, dict) or not isinstance(p.get("point"), str) or not p["point"].strip():
            continue
        a = p.get("addressed_in")
        if a is not None and (not isinstance(a, str) or a.strip().lstrip("#").strip() not in heads):
            a, fixed = None, fixed + 1
        elif isinstance(a, str):
            a = a.strip().lstrip("#").strip()
        points.append({"point": p["point"].strip(), "addressed_in": a})
    return points, fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("study")
    ap.add_argument("--paper", default=None, help="paper check run folder to append to the report text")
    args = ap.parse_args()
    os.environ["MODEL_API_KEY"] = env_value("MODEL_API_KEY")
    study = pathlib.Path(args.study)
    md = (study / "report.md").read_text(encoding="ascii")
    if args.paper is not None:
        md = md + "\n" + (pathlib.Path(args.paper) / "paper_check.md").read_text(encoding="ascii").replace(
            "# Paper check:", "## The published study we used:", 1)
    heads = headings(md)
    run_id = "review-" + time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6]
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=600.0)
    t0 = time.time()
    res = client.respond(run_id, "S9_review", PROMPT + md, estimate_usd=0.80, model=MODEL)
    wall = round(time.time() - t0, 1)
    try:
        points, fixed = parse_points(res.text, heads)
        error = None
    except (ValueError, json.JSONDecodeError) as exc:
        points, fixed, error = [], 0, type(exc).__name__ + ": " + str(exc)[:200]
    out = {"schema": "autosolar.review/1", "run_id": run_id, "study": study.name, "model": res.model,
           "usage": res.usage, "cost_usd": res.cost_usd, "wall_s": wall,
           "report_sha256": hashlib.sha256(md.encode("ascii")).hexdigest(),
           "prompt_sha256": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(), "points": points,
           "headings_replaced_by_null": fixed, "parse_error": error, "raw_text": res.text}
    run_dir = ROOT / "runs" / "reviews" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "review.json").write_text(json.dumps(out, indent=2, ensure_ascii=True), encoding="ascii")
    lines = ["# Second model review (" + res.model + ")", ""]
    for p in points:
        lines.append("- " + p["point"] + " [" + (p["addressed_in"] or "open") + "]")
    (run_dir / "review.md").write_text("\n".join(lines).encode("ascii", "replace").decode("ascii") + "\n",
                                       encoding="ascii")
    print(run_id, "wall", wall, "s USD", res.cost_usd, "points", len(points), "open",
          sum(1 for p in points if p["addressed_in"] is None), "replaced", fixed, "error", error)


if __name__ == "__main__":
    main()
