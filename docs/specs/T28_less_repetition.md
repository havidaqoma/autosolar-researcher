# T28: less repetition on the gallery and island pages (post hoc)

Status: spec and test changes written first, with the general AI coding assistant (not Muse Code), on Tuesday 3 Nov
after the feature freeze (commit `3b8a59d`); the code change that follows them was written the same way, not by
Muse Code. Made
at the owner's request after he read the live pages ("so many repetitions"). Page layout only: no number, no input,
no study and no check changes. Every study page stays byte-identical; only `docs/site/index.html` and
`docs/site/islands.html` change.

## What was wrong (measured on the live pages)

- Gallery: 7 cards; 6 are titled just "Karimunjawa", the same question is printed 6 times, and the two answers
  are printed 3 times each, because 4 cards are earlier builds of the same two studies. Each card is one big link,
  so every line is underlined.
- Island page: the "Costed here?" cell repeats one 66-character sentence on 10 of 11 rows, and "Screen says"
  repeats "wind: not on this screen" on all 11 rows.

## 1. autosolar/site.py: render_index_html(cards)

Each card is `{"href", "site", "question", "headline", "run_hash"}` as in T13, plus optional keys:
`"title"` (str; default `site`), `"note"` (str or None), `"earlier"` (bool; default False) and `"same_as"`
(str or None).

- Main cards (`earlier` false), in order, each `<div class="study">` holding: `<h2><a href="HREF">TITLE</a></h2>`;
  `<p>QUESTION</p>` only when the question differs from the previous main card's question; `<p>HEADLINE</p>`;
  `<p>NOTE</p>` when a note is given; `<p>Run RUN_HASH</p>`. Only the title is a link.
- When any card is earlier: `<h2>Earlier builds, kept for the record</h2>`, the sentence
  `EARLIER_NOTE = "Earlier pages of the studies above, built before some sections were added."`, then one table
  with heads `Run`, `Inputs and judge`, `Answer`; one row per earlier card in order: the run hash as a link to its
  page, the note (or empty), and `"same as: " + same_as` when `same_as` is set, else the headline.
- No `<a class="study">` any more. `"No studies yet."` stays for an empty list. All text through `esc`.
- `SITE_CSS` is not changed (every study page holds it, and they must stay byte-identical); the index adds a small
  `INDEX_CSS` of its own for the card divider and the earlier-builds table.

## 2. tools/make_site.py

Cards carry `title` (`entry["title"]` or the site name), `note` (`entry.get("note")`, no longer joined to the
headline with " | "), and `earlier` (`entry.get("earlier", False)`). For an earlier card, `same_as` is the title of
the first main card before it whose headline is identical (computed, so the page never claims a match the
reports do not show); otherwise None. Page entries (`"page"` key) get the same keys, earlier false.

`config/gallery.json`: titles for the two main studies, `"earlier": true` on the 4 earlier builds, and their notes
without the words "Earlier build, kept for the record" (the section head says it).

## 3. autosolar/islands.py

- `NOT_COSTED_CELL = "no: no hourly load"` is what the "Costed here?" cell shows for an island that is not costed.
  `NOT_COSTED` stays as the value stored in each row (the saved run keeps it).
- `TABLE_NOTE = "Costed here: the tool costs an island only when it has an hourly load; without one it refuses
  rather than guess. Screen says: only what passes the screen rule above."` is printed once, in a `<p>` right
  before the table.
- `verdict_text(row)`: the parts `"solar: X"`, `"wind: X"`, `"hydro: X"` in that order, leaving out every part
  whose verdict is `NOT_ON_SCREEN`, joined with "; ". When all three are left out it returns
  `NOTHING_PASSES = "nothing passes this screen"`. A row without verdicts still gives `NOT_FETCHED`.

## Done when

- The changed tests in `tests/test_site.py`, `tests/test_make_site.py` and `tests/test_islands.py` pass, and the full
  suite passes.
- `tools/make_site.py` and a re-render of the saved island screen change only `index.html` and `islands.html`.
- `tools/check_text.py` passes on the changed files; the pages stay ASCII with no script.
