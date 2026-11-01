"""Post hoc twin test of the checking step: run shifted values through the script and judge.

  python tools/twin_test.py [--site docs/site] [--out docs/posthoc] [--judge none|glimmer] [--votes 3]

Orchestrator glue around autosolar.twin_test (T27). With --judge none (the default) no judge runs and no
server is touched. With --judge glimmer the local judge votes on every twin and each vote is appended to
<out>/twin_test_votes.jsonl as it lands, so a crash resumes from the cache instead of starting again.
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import source  # noqa: E402
from autosolar.twin_test import (NOTE, TWIN_SCHEMA, collect_items, make_twins, render_md, run_votes,  # noqa: E402
                                 summarise)


def build_parser() -> argparse.ArgumentParser:
    """Build the twin test argument parser. Output parser."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="docs/site")
    ap.add_argument("--out", default="docs/posthoc")
    ap.add_argument("--judge", choices=["none", "glimmer"], default="none")
    ap.add_argument("--votes", type=int, default=3)
    return ap


def _resolve(path_arg: str) -> pathlib.Path:
    """Resolve a CLI path against the repo root. Output path."""
    path = pathlib.Path(path_arg)
    if not path.is_absolute():
        path = ROOT / path
    return path


def _read_cache(cache: pathlib.Path, judge: str) -> dict:
    """Read kept votes for one judge. Output done keyed by (key, vote)."""
    done: dict = {}
    if not cache.is_file():
        return done
    for line in cache.read_text(encoding="utf-8").splitlines():
        if line.strip() == "":
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("judge") != judge:
            continue
        try:
            key = (rec["key"], rec["vote"])
        except KeyError:
            continue
        done[key] = {"key": rec["key"], "vote": rec["vote"], "supports": rec.get("supports"),
                     "reason": rec.get("reason", ""), "raw": rec.get("raw", "")}
    return done


def main(argv=None, judge_fn=None) -> int:
    """Run the twin test and write its report. Output exit code."""
    args = build_parser().parse_args(argv)
    site = _resolve(args.site)
    out = _resolve(args.out)
    items, skipped = collect_items(site)
    twins = make_twins(items)
    if args.judge == "none":
        judge = "none (script layer only)"
        votes = 0
        done: dict = {}
    else:
        judge = source.JUDGE_NAME
        votes = args.votes
        if isinstance(votes, bool) or not isinstance(votes, int) or votes < 1:
            build_parser().error("--votes must be an int of 1 or more")
        out.mkdir(parents=True, exist_ok=True)
        cache = out / "twin_test_votes.jsonl"
        done = _read_cache(cache, judge)
        handle = open(cache, "a", encoding="ascii", newline="\n")

        def on_vote(record: dict) -> None:
            """Append one vote to the cache. Output none."""
            handle.write(json.dumps({"judge": judge, **record}, sort_keys=True) + "\n")
            handle.flush()

        fn = judge_fn
        proc = None
        if fn is None:
            from autosolar.sourcing import glimmer_judge as fn
            if not source.server_up():
                log_dir = ROOT / "runs" / "twin_test"
                log_dir.mkdir(parents=True, exist_ok=True)
                proc = source.start_server(log_dir / "glimmer_server.log")
        try:
            run_votes(items, twins, fn, votes, done, on_vote=on_vote)
        finally:
            handle.close()
            if proc is not None:
                proc.terminate()
    summary = summarise(twins, done, votes)
    doc_twins = []
    for twin in twins:
        twin_votes = [done[(twin["key"], num)] for num in range(1, votes + 1)
                      if (twin["key"], num) in done]
        doc_twins.append({**twin, "votes": twin_votes})
    doc = {"schema": TWIN_SCHEMA, "note": NOTE, "judge": judge, "votes": votes, "items": items,
           "skipped": skipped, "twins": doc_twins, "summary": summary}
    out.mkdir(parents=True, exist_ok=True)
    (out / "twin_test.json").write_bytes((json.dumps(doc, indent=1) + "\n").encode("ascii"))
    (out / "twin_test.md").write_bytes(render_md(doc).encode("ascii"))
    for row in summary:
        print("%s %d/%d %d/%d %d/%d" % (row["level_frac"], row["script_caught"], row["n_twins"],
                                        row["votes_not_yes"], row["votes_total"],
                                        row["panel_caught"], row["panel_runs"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
