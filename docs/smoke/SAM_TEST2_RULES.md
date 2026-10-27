# SAM 3.1 test 2: rules fixed before the run

Written Tuesday 27 Oct, before any test 2 call. Results go in `sam_test2.json` and a separate section at the end of
this file. Nothing above the results section changes after the run.

## Why

Test 1 (`sam_smoke.json`): 0 objects on 18 of 19 concept prompts on two Sentinel-2 crops at 10 m per pixel, and
the one hit was a box over 98% of the image. A synthetic control returned 3 of 3 red squares, so the API path is
right. Havid approved one more cheap test, then a decision.

## What changes in test 2

1. Zoom: tiles of 128 x 128 native pixels (1.28 km) upscaled 8 times to 1024 x 1024, and one tile of 256 x 256
   native pixels (2.56 km) upscaled 4 times. Lanczos resampling. Upscaling adds no detail; it only makes each
   house a blob of about 8 x 8 pixels instead of 1 pixel.
2. Contrast stretch per band, 2nd to 98th percentile of the tile, to 0 to 255.
3. Both dates: scene S2C_49MDP_20260909 and scene S2C_49MDP_20250709 (Copernicus Sentinel-2 L2A true colour,
   Earth Search, the same scenes as test 1).
4. The tile position is chosen by code, not by eye: the 128 pixel window inside the test 1 village crop with the
   most OpenStreetMap building centroids, among windows with no empty pixels and under 2% very bright pixels
   (cloud) on both dates. The 256 pixel tile has the same centre.

## Reference

OpenStreetMap buildings (ways tagged `building`) over the main island, from the Overpass API, snapshot saved as
centroids in `osm_buildings_karimunjawa.json` (OpenStreetMap contributors, ODbL). Used only to say where buildings
are; OSM may miss buildings, so recall is a lower bound on what SAM finds.

## Calls (12, USD 0.0025 each, USD 0.03 computed)

| Tile | Prompts |
|---|---|
| A: 2026 date, 128 px x8 | building, roof, house, village |
| B: 2025 date, 128 px x8 | building, roof, house, village |
| C: 2025 date, 256 px x4 | building, village, forest, beach |

Non streaming, `include_confidence` on, through `autosolar.meta_client` so every call is in `ledger/api_usage.jsonl`.

## Measures (boxes only; masks are not decoded in this test)

Per call: number of objects; largest box as a share of the tile; precision = share of SAM boxes that contain at
least one OSM building centroid; recall = share of OSM building centroids in the tile that fall inside at least
one SAM box.

## Verdict rule

- **Roof role passes** if, for at least one of the wordings building, roof, house, BOTH tiles A and B give: at
  least 3 objects, no box over 25% of the tile, precision at least 0.5 and recall at least 0.2.
- **Settlement role passes** if the prompt village (or building) on at least 2 of the 3 tiles gives at least one
  box of at most 50% of the tile that holds at least 50% of the tile's OSM building centroids.
- Decision:
  - Roof role passes: keep plan card B (SAM measures roof area, scored against Open Buildings, gates G9 and G13).
  - Only the settlement role passes: SAM outlines the settlement and open land at a coarse level; roof area comes
    from Google Open Buildings; the report labels SAM as coarse.
  - Neither passes: SAM leaves the satellite role. Roofs come from Open Buildings, land cover from ESA WorldCover,
    and the report shows both failed tests with their numbers. Havid picks a new SAM role.
- Any call that errors counts as a fail for that call; it is not retried silently.
