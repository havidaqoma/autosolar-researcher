# Fresh clone test

Question: does the repo install and pass its tests from a clean clone, with nothing from the build machine?

Commit tested: `35f29ea` (main).

Steps, run in a new folder on the build PC (Windows 11):

```
git clone <local repo> clone_test
cd clone_test
uv sync
uv run pytest -q -p no:cacheprovider -o addopts=""
```

Result (measured): `uv sync` made a new environment with Python 3.12.13, and pytest reported
`1316 passed, 298 warnings in 346.19s`, exit code 0. All 298 warnings come from pvlib calling a pandas function that
pandas plans to remove (`DatetimeIndex.dayofyear`); none comes from this repo's code.

The tests use no network. A live study needs the Meta Model API key and a CAMS account, as the README says.
