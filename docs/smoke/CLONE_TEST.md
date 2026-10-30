# Fresh clone test

Question: does the repo install and pass its tests from a clean clone, with nothing from the build machine?

Commit tested: `f3d0ab9` (main). Earlier runs: `2eac8e7` passed 1455 of 1455, `7db7b23` passed 1425 of 1425,
`35f29ea` passed 1316 of 1316.

Steps, run in a new folder on the build PC (Windows 11):

```
git clone <local repo> clone_test
cd clone_test
uv sync
uv run pytest -q -p no:cacheprovider -o addopts=""
```

Result (measured): `uv sync` made a new environment with Python 3.12.13, and pytest reported
`1563 passed, 322 warnings in 704.97s`, exit code 0. All 322 warnings come from pvlib calling a pandas function that
pandas plans to remove (`DatetimeIndex.dayofyear`); none comes from this repo's code.

The tests use no network. A live study needs the Meta Model API key and a CAMS account, as the README says.
