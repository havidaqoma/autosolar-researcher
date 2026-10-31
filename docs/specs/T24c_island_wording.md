# T24c: island screen page wording after an outside review

Status: spec and acceptance tests written first, by hand, after an outside review of the island page
(opencode, deepseek-v4.1-flash at max effort, six findings, all accepted; post hoc). Muse Code edits
`autosolar/islands.py` only. T24 and T24b stay in force except where this spec changes them. The acceptance tests
are the tests under "T24c" in `tests/test_islands.py`; four T24 or T24b test lines change with this spec, each
marked `# T24c`.

## Why

The reviewer found: the verdict words have no stated cut-offs on this page; streams are listed but never said to
be left out of the hydro verdict; "running a diesel plant" claims more than a found quote shows (one article only
says PLN shipped two diesel units to the island, another is from 2017); town distances are straight lines but do
not say so, and Selayar's 0 km looks like a bug (its point is its main town); and the one costed row shows a bare
run hash as its link text.

## Changes to autosolar/islands.py

1. `NOTE` becomes exactly:

   `"Written after the studies ran (post hoc). A convenience list, not a sample of PLN's 741 sites: each island is named in a news article as having a diesel plant (PLTD), and the tool checks the quote in the page it fetches; a found quote shows the words are on the page, not that the plant runs today. Only Karimunjawa has an hourly load, so only Karimunjawa is costed. Sun, wind and rivers are a first screen from free public data, not a resource assessment; nothing here costs wind, hydro or a grid link, and the nearest town is not a grid connection."`

2. New constant `SCREEN_RULE`, exactly:

   `"Screen rule (assumed): solar is worth a closer look at 3.5 kWh/kWp a day or more, the lower bound of the World Bank's favorable range; wind at class 3 or more on the NREL scale at 50 m (class 1, Poor, is the lowest); hydro needs at least one mapped river within 10 km (streams are listed but not counted), and then flow and head decide."`

3. `_FOOTER` becomes exactly:

   `"Sun: Global Solar Atlas (a Solargis model), long-term PV output at the optimum tilt. Wind: NASA POWER hourly at 50 m, 2016 to 2024 (computed). Rivers and towns: OpenStreetMap, counts of mapped features (measured); town distance in a straight line from the island point (computed). Coordinates: OpenStreetMap Nominatim. Land outline: Natural Earth (public domain). Diesel: press, quote re-checked by the tool."`

4. Counts paragraph in `render_islands_html` becomes:

   `"The list names %d islands, each with a news article that says it has a diesel plant (PLTD); the tool found the quote in the fetched page for %d. Fully screened: %d. Costed: %d (%s), the only island with an hourly load."`

   with the same values as before, escaped with `esc`.

5. Right after the answer paragraph (T24b) and before the note paragraph: `"<p>" + esc(SCREEN_RULE) + "</p>"`.

6. Town cell: `"%s (%s), %.0f km in a straight line" % (name, place, km)`, and when `"%.0f" % km == "0"` append
   `"; the island point is in this town"`. Escaped with `esc`. The NO_TOWN and NOT_FETCHED cells do not change.

7. Costed cell, when the row is costed (`costed` starts with `"yes"`; the hash is the text after `"yes: study "`):
   `'<a href="' + esc(hash) + '.html">yes: open the full study</a> (run ' + esc(hash) + ")"`. The stored row value
   `"yes: study <hash>"` does not change. Rows that are not costed do not change.

## Rules for this task

- Edit `autosolar/islands.py` only. Do not edit tests, specs, config or tools.
- No new dependency; no `<script>`; ASCII only.
