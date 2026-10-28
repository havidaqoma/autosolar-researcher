# T12a2: table numbers in the paper check

Status: spec by the orchestrator. Builder edits `autosolar/paper_check.py` only. T12a stays in force except where
this spec changes it.

## Why

The first paper check run on the Hiron PDF (measured, run paper-20261028T032011-c5c686) kept 34 statements and
dropped 24. Most drops were table cells: a PDF text layer prints a table as all its headers first and then all its
values (for example `battery (mah) dpp system (mw) ... 1.41 11.300 0.99 4.1 2 x 2.7 257.770 18`), so no quote the
model copies from the visible table is ever found. Table cells have no sentence around them. For them the check
must fall back to the number itself.

## Change to verify_extraction

A statement whose `place` is `"table"` and whose quote is not found by `find_quote` is still kept when:

- `float(value)` is in `numbers_in(text)`, where `text` is the stated page and its neighbours, joined the same way
  as for the schedule (`pages[page-2]`, `pages[page-1]`, `pages[page]`, only indexes 0 to `len(pages) - 1`); and
- when `count` is not None, `float(count)` is in the same numbers.

Such a statement gets `"found_page"` = its stated `page` and `"quote_kind"` = `"table number"`. When the number is
not there either, it is dropped with the reason `"table number not found on its page"`.

Everything else is unchanged: a table statement whose quote is found goes through the normal value and count
checks; a statement with any other `place` whose quote is not found is dropped as before with
`"quote not found in the PDF"`.

## Done when

- `tests/test_paper_check_table.py` passes, and every test that passed before still passes.
- `tools/check_text.py` passes on `autosolar/paper_check.py`; it stays ASCII.

## Test check by the orchestrator

- Reference build in scratch (the change applied to a copy of the T12a reference): all 7 tests in
  `tests/test_paper_check_table.py` pass; the full suite passes 969 of 969 (962 old plus 7 new).
- One existing test changed: the end to end test in `tests/test_paper_check.py` gave its net present cost
  statement the place `text`, so it still tests a quote that is not found (as a table cell it would now fall back
  to the page numbers).
- 8 planted faults, each caught: rule off; rule for every place; own page only; page index wraps; count not
  checked; wrong found page; wrong quote kind; old drop reason.
