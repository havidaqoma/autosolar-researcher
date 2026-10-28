# S00 Sandbox smoke check (no code)

Purpose: the Windows sandbox for Muse Code is now set up (`muse sandbox windows check` reports status=ready,
measured). Before the next build task, check that Muse Code can run the test suite itself inside the sandbox
with the network restricted.

This task writes no code and has no acceptance tests. Do not create, edit or delete any file.

Steps:

1. Run this shell command from the repo root:
   `uv run pytest -q -p no:cacheprovider -o addopts="" tests/test_diesel_size.py`
2. If step 1 cannot run or fails before collecting tests, run this one instead:
   `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -o addopts="" tests/test_diesel_size.py`
Second attempt (S00b, rerun as S00c after a sandbox lock timeout): the first attempt found `uv` missing from the sandbox PATH and the venv base Python
unreadable by the sandbox user (measured, build_logs/S00_run.out). The orchestrator moved the venv base Python to
F:\uv-python, which the sandbox user can read. Run only the command in step 2.

3. In your final answer, give for each command you ran: the command, whether it ran, and the last line of its
   output copied exactly. If a command could not run, quote the error exactly. Never describe a result you did
   not see.

Third run (S00d): S00c ran step 2 inside the sandbox with exit code 0 and the line `46 passed, 26 warnings in
58.39s` (measured, build_logs/S00c.jsonl). It also left a folder `pytest-of-havid aqoma` in the repo root that only
the sandbox account can open. In S00d, run only these two commands, in this order, and report them as in step 3:

4. `Remove-Item -LiteralPath 'pytest-of-havid aqoma' -Recurse -Force`
5. `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider -o addopts="" --basetemp build_logs\pytest_sandbox tests/test_diesel_size.py`

The folder removal in step 4 is the one allowed exception to the rule above about deleting files.
