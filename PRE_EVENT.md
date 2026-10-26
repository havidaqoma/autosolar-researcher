# Work done before the event

The hackathon rules ask for new work only. This file lists everything that was prepared before kickoff (Tuesday
27 October 2026, 00:00 Malaysia time, MYT) and that this repo uses. Nothing in `autosolar/`, `tests/` or `tools/`
was written before kickoff.

The preparation lives in a separate private repo, because it holds local copies of papers that may not be shared.
Commit hashes and times (MYT, from git) are listed so the dates can be checked on request.

| Item | What it is | Prep commit |
|---|---|---|
| Project plan | Problem, stages, gates, data sources, budget, day by day plan | `52c1ab2`, Saturday 24 Oct 14:57, updated in later commits |
| Benchmark paper audit | Hand audit of Hiron et al. 2021 (Energies 14, 8311, CC BY 4.0) for Karimunjawa: 14 of 15 checks flagged, reviewed by an outside model | `52c1ab2` |
| Literature sweep | Related work search (OpenAlex, arXiv, Semantic Scholar) and a verified shortlist | `e24a255`, Saturday 24 Oct 15:57 |
| Frozen paper checks | Generic checks P1 to P15 and the scoring rule, fixed before the second paper was read | `93a703b`, Sunday 25 Oct 00:25 |
| Weather cross check | Annual irradiance for Karimunjawa from PVGIS, Global Solar Atlas, NASA POWER and CAMS | `52c1ab2`, `9216bc9` (Sunday 25 Oct 12:48) |
| Second test paper | Choice of an out of sample paper (Mathematics 11, 1248, version 2, CC BY 4.0) | `fda162f`, Sunday 25 Oct 16:52 |
| Satellite test images | Two cloud free Sentinel-2 crops of the island (Copernicus open data) for the SAM 3.1 test | `95c80f9`, Monday 26 Oct 01:09 |
| Muse Glimmer checks | Fit check on the local GPU, speed test rules, then the speed test run (rules fixed before the run) | `d018c5b`, `05a1b23` (Monday 26 Oct 23:13); run finished 23:57, results committed `98d4d83` at Tuesday 27 Oct 00:02 |

After kickoff the prep repo only received notes and setup checks (API key smoke test, budget update, docs saved);
all product code is here.
