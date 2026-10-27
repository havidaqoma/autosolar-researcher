"""Text gate for this repo: ASCII only, no em or en dash, no ' -- ', no banned filler words.

Usage: python tools/check_text.py [files...]   (default: every tracked .md, .py, .toml, .txt file)
Exit code 1 when any file fails.
"""
import pathlib
import re
import subprocess
import sys

BANNED = re.compile(r"\b(leverag\w*|empower\w*|robust\w*|crucial\w*|harness\w*|showcas\w*|seamless\w*|delv\w*|"
                    r"pivotal|paramount|moreover|furthermore|comprehensive\w*)\b", re.I)
DASH = re.compile("[\u2013\u2014]| -- ")
ROOT = pathlib.Path(__file__).resolve().parents[1]
SELF = pathlib.Path(__file__).resolve()


def files_to_check(args):
    if args:
        return [pathlib.Path(a) for a in args]
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.split()
    # tests/fixtures holds raw API output (base85 mask data), not prose
    return [ROOT / f for f in out if f.endswith((".md", ".py", ".toml", ".txt"))
            and not f.startswith("tests/fixtures/")]


def main(args):
    bad = 0
    for f in files_to_check(args):
        if f.resolve() == SELF:
            continue
        s = f.read_text(encoding="utf-8")
        problems = []
        n = sum(ord(c) > 127 for c in s)
        if n:
            problems.append(f"{n} non-ASCII")
        if DASH.search(s):
            problems.append(f"{len(DASH.findall(s))} dash")
        words = BANNED.findall(s)
        if words:
            problems.append(f"banned {sorted(set(w.lower() for w in words))}")
        if problems:
            bad += 1
            print(f"FAIL {f.relative_to(ROOT) if f.is_absolute() else f}: {', '.join(problems)}")
    print("text gate:", "FAIL" if bad else "PASS")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
