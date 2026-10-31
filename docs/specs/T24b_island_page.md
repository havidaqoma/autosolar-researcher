# T24b: island screen page. Say the answer, show the verdicts, style the map, keep labels apart

Status: spec and acceptance tests written first, by hand, after the first real island screen run (post hoc, run
islands-20261101T003206-c916e6, 11 islands). Muse Code edits `autosolar/islands.py` only. T24 stays in force except
where this spec changes it. The acceptance tests are the tests under "T24b" in `tests/test_islands.py`; two T24
test lines change with this spec (`"1 rivers, 2 streams"` becomes `"1 river, 2 streams"`, and the header list
gains `Screen says`).

## Why

The first render showed four problems. The page works out a verdict for every island but never shows it, so a
reader cannot see the answer. The map has no colours of its own: SVG fills default to black, and `SITE_CSS` sets
none, so land and dots would share one colour. Three islands off Madura (Raas, Sapudi, Kangean) sit within 20 px
of each other on the map, and their labels overlap. "1 rivers" reads wrong.

## Changes to autosolar/islands.py

New constants (exact values):

```
LABEL_MERGE_PX = 20.0
MAP_CSS = ("svg.map{background:#eaf2fa;border:1px solid #c9d6e3}"
           "path.land{fill:#efe9da;stroke:#b8ad94;stroke-width:0.6}"
           "circle.island{fill:#1a4f9c;stroke:#ffffff;stroke-width:1.5}"
           "circle.costed{fill:#d9822b;stroke:#000000;stroke-width:1.5}"
           "svg.map text{fill:#222222;paint-order:stroke;stroke:#ffffff;stroke-width:3px}")
```

### answer_line(rows) -> str

`rows` is a list of row dicts (as in a screen doc). Let `screened` be the rows whose `verdicts` is a dict. Count
`solar_n` = screened rows with `verdicts["solar"] == resources.LOOK`, `wind_n` = screened rows with
`verdicts["wind"] == resources.LOOK`, `hydro_n` = screened rows with `verdicts["hydro"] == resources.HYDRO_CHECK`.
Returns exactly:

`"On this screen, of the M islands with every part fetched: solar is worth a closer look on S, wind at 50 m on W, and R have a mapped river to check for flow and head on site."`

with M = len(screened), S = solar_n, W = wind_n, R = hydro_n. When `screened` is empty it returns
`"No island has every part fetched, so the screen gives no verdict."`. A non-list raises `ValueError`.

### verdict_text(row) -> str

`row` is a row dict. When `row["verdicts"]` is None returns `NOT_FETCHED`. Otherwise returns
`"solar: " + v["solar"] + "; wind: " + v["wind"] + "; hydro: " + v["hydro"]`.

### label_groups(rows) -> list

`rows` is a non-empty list of row dicts. Dots are placed with `map_xy(row["lat_deg"], row["lon_deg"])`. Walk the
rows in order. A row joins the group of the first earlier row whose dot lies within `LABEL_MERGE_PX` of its own dot
(straight line distance in px, `<=` counts as within); otherwise it starts a new group. Returns one dict per group,
in the order the groups start: `{"names": [names in row order], "x": largest dot x in the group + 7.0,
"y": the first row's dot y + 4.0}` with x and y rounded to 2 decimals.

### render_islands_html(doc, land=None)

Same as T24, with these changes:

1. The head holds `<meta charset="utf-8">` and the style is `SITE_CSS + MAP_CSS`.
2. Right after the counts paragraph, a new paragraph `<p class="answer"><b>` + `esc(answer_line(rows))` +
   `</b></p>`.
3. The svg tag is `<svg class="map" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 360" role="img">`.
4. Map text: one `<text>` per group from `label_groups(rows)`, at the group's x and y, holding the escaped names
   joined by `", "`. Circles stay one per row as in T24.
5. The table gets an eighth column after `Costed here?`: `<th>Screen says</th>`, with `esc(verdict_text(row))` in
   each row.
6. Rivers cell: `"1 river"` when the count is 1, else `"%d rivers"`; `"1 stream"` when 1, else `"%d streams"`;
   joined by `", "` (for example `"1 river, 2 streams"`, `"0 rivers, 0 streams"`). `NOT_FETCHED` as before.

## Rules for this task

- Edit `autosolar/islands.py` only. Do not edit tests, specs, config or tools.
- No new dependency; no `<script>`; ASCII only.
