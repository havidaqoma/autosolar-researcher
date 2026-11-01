# T24d: island map that shows where each island really is

Status: spec and acceptance tests written first, by hand, after the owner reported that the dots on the island
map look "very off and wrong" (post hoc). Muse Code edits `autosolar/islands.py` only. T24, T24b and T24c stay in
force except where this spec changes them. The acceptance tests are the tests under "T24d" in
`tests/test_islands.py`; the T24 and T24b test lines that pin the old map change with this spec, each marked
`# T24d`. The new land file `config/land_rings_indonesia.json` is data, made before this spec by a script outside
the repo (Natural Earth 1:10m land, public domain; simplified and rounded), and is committed with this spec.

## Why

The island points are right: each of the 11 points sits on its island when drawn on OpenStreetMap tiles
(checked by hand at zoom 9 to 13, post hoc). The map makes them look wrong:

- The old land outline (Natural Earth 1:50m) leaves out 7 of the 11 islands, so 7 dots sit on open sea.
- At 20 px a degree, a filled dot 10 px wide is about 55 km across. It covers the coast next to offshore
  islands (Derawan looks like it is on Borneo; Raas and Sapudi look like they are on Madura).
- Nothing on the page lets a reader check a point.

## Changes to autosolar/islands.py

1. Map box and size: `MAP_BBOX_DEG = (95.0, 123.0, -9.5, 4.5)`, `MAP_WIDTH_PX = 960`, `MAP_HEIGHT_PX = 480`
   (34.29 px a degree both ways). `map_xy` and `_project` keep their formulas. The SVG `viewBox` is built from
   the constants: `'viewBox="0 0 %d %d"' % (MAP_WIDTH_PX, MAP_HEIGHT_PX)`, so the page shows `viewBox="0 0 960 480"`.
2. Markers are rings, not filled dots, so the island inside stays visible. New constant `MARKER_R_PX = 6.0`;
   every circle is written with `r="6"`. `MAP_CSS` becomes exactly:

   `"svg.map{background:#eaf2fa;border:1px solid #c9d6e3}path.land{fill:#efe9da;stroke:#b8ad94;stroke-width:0.6}circle.island{fill:none;stroke:#1a4f9c;stroke-width:2.5}circle.costed{fill:none;stroke:#d9822b;stroke-width:3.5}svg.map text{fill:#222222;paint-order:stroke;stroke:#ffffff;stroke-width:3px}p.mapnote{font-size:0.9em}"`

3. Labels: `LABEL_MERGE_PX = 30.0` (about 0.9 deg at the new scale; keeps Raas, Kangean and Sapudi on one label).
   New constant `LABEL_GAP_PX = 10.0`: a label's `x` is the largest dot `x` in its group plus `LABEL_GAP_PX`
   (was plus 7). Its `y` stays the first dot's `y` plus 4. Grouping rules do not change.
4. New constant `UNDRAWN_TOL_KM = 2.0` and new function `undrawn_names(rows, land, tol_km=UNDRAWN_TOL_KM)`:
   - `rows`: list of dicts with `name`, `lat_deg`, `lon_deg`. `land`: `None` or a list of rings as returned by
     `parse_land` (points are `(lon, lat)` in deg). `tol_km`: finite real, at least 0, else `ValueError`.
     `rows` not a list, or a row not a dict, raises `ValueError`.
   - A row is drawn when its point is inside any ring (even-odd ray rule on lon and lat) or within `tol_km` of any
     ring edge. Edge distance: flat projection around the point, `dx_km = dlon * 111.32 * cos(lat of the point)`
     and `dy_km = dlat * 110.57`, shortest distance to each segment (the closing segment from the last point back
     to the first counts).
   - Returns the names of rows that are not drawn, in row order. With `land` `None` or empty, every name.
5. New constants and function for the line under the map:
   - `MAP_NOTE_HEAD = "Each ring marks the island point from OpenStreetMap Nominatim; the link under each island name in the table opens that point on OpenStreetMap."`
   - `MAP_NOTE_SMALL = "Too small for the land outline at this scale, so the ring sits on open sea: "`
   - `map_note(names)`: `MAP_NOTE_HEAD` alone when `names` is empty; otherwise
     `MAP_NOTE_HEAD + " " + MAP_NOTE_SMALL + ", ".join(names) + "."`. `names` not a list of str raises `ValueError`.
   - The page puts `'<p class="mapnote">' + esc(map_note(undrawn_names(rows, land))) + "</p>"` right after
     `</svg>` and before the table.
6. New function `osm_url(lat_deg, lon_deg)`: finite reals (bool rejected), lat in -90 to 90, lon in -180 to 180,
   else `ValueError`. Returns exactly
   `"https://www.openstreetmap.org/?mlat=%.4f&mlon=%.4f#map=12/%.4f/%.4f" % (lat, lon, lat, lon)`.
7. New constant `OSM_LINK_TEXT = "the point on OpenStreetMap"`. The first table cell of each row becomes
   `esc(name) + "<br>" + esc(region) + '<br><a href="' + esc(osm_url(lat, lon)) + '">' + esc(OSM_LINK_TEXT) + "</a>"`.
8. `_FOOTER`: the words `Land outline: Natural Earth (public domain).` become
   `Land outline: Natural Earth 1:10m (public domain).` Nothing else in the footer changes.

## Not changed

Island points, verdicts, the table columns, counts, answer line, note, screen rule, the land file schema, and
`parse_land`. The tool (`tools/island_screen.py`) and `make_site` are not edited.

## Rules for this task

- Edit `autosolar/islands.py` only. Do not edit tests, specs, config or tools.
- No new dependency; no `<script>`; ASCII only; units in names; `ValueError` on bad input.
