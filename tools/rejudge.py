"""Re-judge the checked rows of an earlier sourcing file under the T10f vote rule (orchestrator tool).

  uv run python tools/rejudge.py runs/sourcing/<run>/sourcing.json
  AUTOSOLAR_ENV_FILE=path/to/.env uv run python tools/rejudge.py --panel runs/sourcing/<run>/sourcing.json

Rule (docs/specs/T10f_judge_votes.md, pre-registered): every checked row is checked again with check_citation, where
the local judge must now say yes 3 times in a row. A row stays checked only when the new check is checked with the
same value (6 significant digits) and the same label. Any other outcome, a failed fetch included, sends the row back
to its assumed value from config/default_inputs.json with each new reason under a "re-judge: " prefix. Assumed rows
are carried unchanged. No search is made, so no model API cost. Output: runs/sourcing/<new run>/sourcing.json (G6
checked on read) and inputs.json.

--panel (docs/specs/T17_judge_panel.md, pre-registered): the same rule, but votes 1 and 2 come from the local judge
and vote 3 from muse-wonder-1.0 (Meta Model API, cost in the ledger). Every vote's raw answer is kept in the meta.
"""
import copy
import dataclasses
import functools
import json
import os
import pathlib
import sys
import time
import uuid

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from ask import env_value  # noqa: E402
from source import JUDGE_NAME, TimedJudge, server_up, start_server  # noqa: E402
from autosolar.cite_check import JUDGE_VOTES, Claim, check_citation  # noqa: E402
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402
from autosolar.sourcing import (CHECKED_PREFIX, SourcingRow, g6_check, load_targets, read_sourcing,  # noqa: E402
                                write_sourcing)

VOTE_JUDGE_NAME = JUDGE_NAME + ", yes needed in all " + str(JUDGE_VOTES) + " votes"
PANEL_JUDGE_NAME = (JUDGE_NAME + " (votes 1 and 2) and muse-wonder-1.0 (vote 3), yes needed in all "
                    + str(JUDGE_VOTES) + " votes")
LEDGER = ROOT / "ledger" / "api_usage.jsonl"


class VoteLog:
    """Wraps one judge and keeps every raw answer (or the error type) with its time in seconds."""

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


def ledger_cost(run_id):
    if not LEDGER.exists():
        return 0.0
    rows = [json.loads(line) for line in LEDGER.read_text(encoding="utf-8").splitlines() if line.strip()]
    return round(sum(r.get("cost_usd", 0.0) for r in rows if r.get("run_id") == run_id), 6)


def rejudge_row(row, target, entry_before, default_entry, *, http_get, judge, fx, judge_name=VOTE_JUDGE_NAME):
    """Return (new row, new inputs entry, record) for one checked row."""
    claim = Claim(input_name=row.input, description=target.description, value=row.value_as_written,
                  unit=row.unit_as_written, url=row.url, doi=row.doi, quote=row.quote, title=row.title,
                  currency_year=row.currency_year)
    check = check_citation(claim, http_get=http_get, judge_fn=judge, judge_name=judge_name,
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
            note = note.replace(old_tail, "; support judged by " + judge_name)
            entry = {"value": value, "unit": target.target_unit, "label": label, "note": note}
            new_row = dataclasses.replace(row, judge_name=judge_name, supports=True, doi_ok=check.doi_ok,
                                          page=check.page, quote_kind=check.quote_kind)
            record["status_after"] = "checked"
            return new_row, entry, record
        record["reasons"].append("value or label changed: %r %s vs %r %s" % (value, label, row.value_used, row.label))
    reasons = ["re-judge: " + r for r in record["reasons"]]
    entry = copy.deepcopy(default_entry)
    new_row = SourcingRow(row.input, "assumed", entry["label"], entry["value"], entry["unit"], row.value_as_written,
                          row.unit_as_written, row.currency_year, row.title, check.final_url or row.url, row.doi,
                          check.doi_ok, check.page, check.quote_kind, row.quote, check.supports, judge_name,
                          reasons, row.search_cost_usd)
    record["status_after"] = "assumed"
    return new_row, entry, record


def main():
    args = sys.argv[1:]
    panel = args[:1] == ["--panel"]
    if panel:
        args = args[1:]
    if len(args) != 1:
        sys.exit(__doc__)
    src = args[0]
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
    judge_name, rule = VOTE_JUDGE_NAME, "docs/specs/T10f_judge_votes.md"
    if panel:
        from autosolar.sourcing import judge_panel, wonder_judge
        os.environ["MODEL_API_KEY"] = env_value("MODEL_API_KEY")
        client = MetaClient(Ledger(LEDGER), timeout_s=600.0)
        wonder = functools.partial(wonder_judge, client=client, run_id=run_id)
        judge_name, rule = PANEL_JUDGE_NAME, "docs/specs/T17_judge_panel.md"
    http_get = functools.partial(requests.get)
    raw = copy.deepcopy(prior_raw)
    rows, records = [], []
    t = time.perf_counter()
    try:
        for r in prior_rows:
            if r.status != "checked":
                rows.append(r)
                continue
            row_judge, votes = judge, []
            if panel:
                row_judge = judge_panel(VoteLog("local", judge, votes), VoteLog("wonder", wonder, votes))
            new_row, entry, record = rejudge_row(r, by_target[r.input], prior_raw["values"][r.input],
                                                 defaults[r.input], http_get=http_get, judge=row_judge, fx=fx,
                                                 judge_name=judge_name)
            if panel:
                record["votes"] = votes
            rows.append(new_row)
            raw["values"][r.input] = entry
            records.append(record)
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=60)
    ok, detail = g6_check(rows, raw)
    meta = {"run_id": run_id, "rejudged_from": src, "source_run": prior_meta.get("run_id"),
            "rule": rule, "judge": judge_name, "judge_votes": JUDGE_VOTES, "api_cost_usd": ledger_cost(run_id),
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
        for v in rec.get("votes", []):
            print("     vote:", v["judge"], v["seconds"], "s", (v.get("raw") or v.get("error") or "")[:200])
        if any("judge error" in reason for reason in rec["reasons"]):
            print("  WARNING: a judge error sent", rec["input"], "back to assumed (fail closed, not retried)")
    print("API cost USD (ledger)", meta["api_cost_usd"])
    print("folder", out_dir)


if __name__ == "__main__":
    main()
