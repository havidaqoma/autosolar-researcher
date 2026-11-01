# Fresh clone test

Question: does the repo install and pass its tests from a clean clone, with nothing from the build machine?

Commit tested: `97abf69` (main, T27). Earlier runs: `be510e9` passed 1847 of 1847, `a5d74d3` passed 1776 of 1776, `d792e4b` passed 1766 of 1766, `37104e5` FAILED 1 of 1762 (see
below), `780dc19` passed 1688 of 1688, `1d39af4` passed 1686 of 1686, `f3d0ab9` passed 1563 of 1563,
`2eac8e7` passed 1455 of 1455, `7db7b23` passed 1425 of 1425,
`35f29ea` passed 1316 of 1316.

Steps, run in a new folder on the build PC (Windows 11):

```
git clone <local repo> clone_test
cd clone_test
uv sync
uv run pytest -q -p no:cacheprovider -o addopts=""
```

Result (measured): `uv sync` made a new environment with Python 3.12.13, and pytest reported
`1888 passed, 322 warnings in 614.91s`, exit code 0. All 322 warnings come from pvlib calling a pandas function that
pandas plans to remove (`DatetimeIndex.dayofyear`); none comes from this repo's code.

The tests use no network. A live study needs the Meta Model API key and a CAMS account, as the README says.

## The failed run at 37104e5

At `37104e5` the clone test reported `1 failed, 1761 passed` (measured):
`tests/test_engineer_files.py::test_page_otherwise_unchanged_from_committed_page`. The consult round 1 commit
(`eedf824`) set a Muse Wonder review for the example study in `config/gallery.json` and rebuilt its page, but this
test still rendered the page without that review. Only three test files were run before that commit, so the gap
was not seen until this clone test. `d792e4b` makes the test render the page the way `tools/make_site.py` does
(with the review), and the clone test above passes at that commit.
