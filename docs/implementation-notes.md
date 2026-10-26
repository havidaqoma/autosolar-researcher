# Implementation notes (build log for the orchestrator)

Short entries. Plan reference: the prep plan, section 7 (stages and gates) and section 10 (day by day).

## Deviations

- Muse Code shell commands do not run on this PC: its Windows sandbox needs a one time admin setup
  (`muse sandbox windows setup`, status `setup_required`). Muse Code writes files; the orchestrator runs the tests
  outside it and sends failures back with `tools/muse_task.py --feedback`. Revisit if Havid runs the setup.
- `tools/muse_task.py` calls the Muse Code binary directly, not the `muse.cmd` launcher, to avoid quoting problems
  and to keep the version fixed during the build.

## Discovered edge cases

- Muse Code loads personal skills from other coding agents on this PC by default; every run uses
  `--no-foreign-personal-context` so only this repo goes into the prompt (contributor mode may train on it).
- Muse Code's own instructions cost about 27,000 input tokens per call; most of them are cached on later calls of
  the same run (measured probe: 113,732 of 143,055 input tokens cached).

## Questions for review

- None yet.
