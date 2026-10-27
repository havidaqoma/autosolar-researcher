"""Re-judge the checked rows of an earlier sourcing file under the T10f vote rule (orchestrator tool).

  uv run python tools/rejudge.py runs/sourcing/<run>/sourcing.json

Rule (docs/specs/T10f_judge_votes.md, pre-registered): every checked row is checked again with check_citation, where
the local judge must now say yes 3 times in a row. A row stays checked only when the new check is checked with the
same value (6 significant digits) and the same label. Any other outcome, a failed fetch included, sends the row back
to its assumed value from config/default_inputs.json with each new reason under a "re-judge: " prefix. Assumed rows
are carried unchanged. No search is made, so no model API cost. Output: runs/sourcing/<new run>/sourcing.json (G6
checked on read) and inputs.json.
"""
import copy
import dataclasses
import functools
import json
import pathlib
import sys
import time
import uuid

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from source import JUDGE_NAME, TimedJudge, server_up, start_server  # noqa: E402
from autosolar.cite_check import JUDGE_VOTES, Claim, check_citation  # noqa: E402
from autosolar.sourcing import (CHECKED_PREFIX, SourcingRow, g6_check, load_targets, read_sourcing,  # noqa: E402
                                write_sourcing)

VOTE_JUDGE_NAME = JUDGE_NAME + ", yes needed in all " + str(JUDGE_VOTES) + " votes"


def rejudge_row(row, target, entry_before, default_entry, *, http_get, judge, fx):
    """Return (new row, new inputs entry, record) for one checked row."""
    claim = Claim(input_name=row.input, description=target.description, value=row.value_as_written,
                  unit=row.unit_as_written, url=row.url, doi=row.doi, quote=row.quote, title=row.title,
                  currency_year=row.currency_year)
    check = check_citation(claim, http_get=http_get, judge_fn=judge, judge_name=VOTE_JUDGE_NAME,
                           target_unit=target.target_unit, band_lo=target.band_lo, band_hi=target.band_hi,
                           fx_idr_per_usd=fx)
    record = {"input": row.input, "status_before": row.status, "judge_calls": check.judge_calls,
              "supports": check.supports, "judge_reason": check.judge_reason, "reasons": list(check.reasons)}
    if check.status == "checked":
        value = float(format(check.value_converted, ".6g"))
        label = "paper" if check.doi_ok is True else "docs"
        if value == row.value_used and label == row.label:
            old_tail = "; support judged by " + row.judge_name
            note = entry_before["note"]
            if note.count(old_tail) != 1:
                sys.exit(row.input + ": note does not name the old judge once")
            note = note.replace(old_tail, "; support judged by " + VOTE_JUDGE_NAME)
            entry = {"value": value, "unit": target.target_unit, "label": label, "note": note}
            new_row = dataclasses.replace(row, judge_name=VOTE_JUDGE_NAME, supports=True, doi_ok=check.doi_ok,
                                          page=check.page, quote_kind=check.quote_kind)
            record["status_after"] = "checked"
            return new_row, entry, record
        record["reasons"].append("value or label changed: %r %s vs %r %s" % (value, label, row.value_used, row.label))
    reasons = ["re-judge: " + r for r in record["reasons"]]
    entry = copy.deepcopy(default_entry)
    new_row = SourcingRow(row.input, "assumed", entry["label"], entry["value"], entry["unit"], row.value_as_written,
                          row.unit_as_written, row.currency_year, row.title, check.final_url or row.url, row.doi,
                          check.doi_ok, check.page, check.quote_kind, row.quote, check.supports, VOTE_JUDGE_NAME,
                          reasons, row.search_cost_usd)
    record["status_after"] = "assumed"
    return new_row, entry, record


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = sys.argv[1]
    prior_raw, prior_rows, prior_meta = read_sourcing(src)  # G6 checked on read
    targets, fx = load_targets(ROOT / "config" / "sourcing_targets.json")
    if prior_meta.get("fx_idr_per_usd") != fx:
        sys.exit("earlier run used a different fx")
    by_target = {t.input: t for t in targets}
    if sorted(r.input for r in prior_rows) != sorted(by_target):
        sys.exit("earlier run has a different target list")
    defaults = json.loads((ROOT / "config" / "default_inputs.json").read_text(encoding="utf-8"))["values"]
    for name in by_target:
        if defaults[name]["note"].startswith(CHECKED_PREFIX):
            sys.exit(name + ": default input note looks checked")
    run_id = "rejudge-" + time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    out_dir = ROOT / "runs" / "sourcing" / run_id
    out_dir.mkdir(parents=True)
    proc = None if server_up() else start_server(out_dir / "glimmer_server.log")
    judge = TimedJudge()
    http_get = functools.partial(requests.get)
    raw = copy.deepcopy(prior_raw)
    rows, records = [], []
    t = time.perf_counter()
    try:
        for r in prior_rows:
            if r.status != "checked":
                rows.append(r)
                continue
            new_row, entry, record = rejudge_row(r, by_target[r.input], prior_raw["values"][r.input],
                                                 defaults[r.input], http_get=http_get, judge=judge, fx=fx)
            rows.append(new_row)
            raw["values"][r.input] = entry
            records.append(record)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=60)
    ok, detail = g6_check(rows, raw)
    meta = {"run_id": run_id, "rejudged_from": src, "source_run": prior_meta.get("run_id"),
            "rule": "docs/specs/T10f_judge_votes.md", "judge": VOTE_JUDGE_NAME, "judge_votes": JUDGE_VOTES,
            "judge_seconds": judge.seconds, "fx_idr_per_usd": fx, "wall_s": round(time.perf_counter() - t, 1),
            "search_cost_usd": 0.0, "rejudge": records, "prior_meta": prior_meta, "g6": [ok, detail]}
    write_sourcing(out_dir / "sourcing.json", raw, rows, meta)
    read_sourcing(out_dir / "sourcing.json")
    (out_dir / "inputs.json").write_text(json.dumps(raw, indent=1, ensure_ascii=True) + "\n", encoding="utf-8")
    print("run", run_id, meta["wall_s"], "s", "judge s", judge.seconds)
    print("G6", ok, detail)
    for rec in records:
        print(" ", rec["input"], rec["status_before"], "->", rec["status_after"], "| judge calls", rec["judge_calls"],
              "| supports", rec["supports"], "|", rec["judge_reason"][:160])
        for reason in rec["reasons"]:
            print("     reason:", reason[:200])
    print("folder", out_dir)


if __name__ == "__main__":
    main()
