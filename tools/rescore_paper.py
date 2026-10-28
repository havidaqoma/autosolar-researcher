"""Score saved paper check runs again with the current checks (no model call, no cost).

  uv run python tools/rescore_paper.py runs/paper_checks/<run_id>/paper_check.json [...]

The extraction of every run is kept in its paper_check.json (verified statements and schedule), so a fix to the
checks can be applied to old runs by script. Prints one JSON line per run with the as-run and the new flags.
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.paper_check import run_checks, summary  # noqa: E402


def rescore(path):
    d = json.loads(pathlib.Path(path).read_text(encoding="ascii"))
    rng = tuple(d["site_ghi_kwh_m2_yr"])
    new = run_checks(d["verified"], site_ghi_kwh_m2_yr=rng)
    return {"run_id": d["run_id"], "label": d["label"], "as_run": d["summary"]["flagged_ids"],
            "rescored": summary(new)["flagged_ids"],
            "rescored_results": [{"check_id": r.check_id, "status": r.status, "detail": r.detail,
                                  "pages": list(r.pages)} for r in new]}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        r = rescore(p)
        print(json.dumps({k: r[k] for k in ("run_id", "as_run", "rescored")}))
