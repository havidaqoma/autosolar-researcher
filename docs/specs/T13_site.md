# T13: a study page a judge can open (static HTML with charts)

Status: spec by the orchestrator. Builder writes the new file `autosolar/site.py` only.
Imports allowed: the standard library (`html`, `math`, and so on) and pandas. No other package, no JavaScript.

## Why

The study report is a long Markdown file with tables only. A judge has about three minutes. This module turns one
study run (its `report.json` and `design_table.csv`), and when they exist a paper check and a review, into one
self contained HTML page with three charts, and builds an index page that lists several runs. The pages need no
server and no internet: CSS is inline, charts are inline SVG, there is no script.

## 1. Rules for every page

- The output is a `str` that is pure ASCII. Every text that comes from a report, paper check or review goes through
  `esc`. `esc(text)` is `html.escape(str(text), quote=True)` and then every non-ASCII character becomes `&#N;` (its
  decimal code point).
- No `<script`, no `<iframe`, no `<link`, no `<img`, no `@import`, and no `src=` anywhere. Links to sources are
  plain `<a href="...">` with an escaped URL; only `http://` and `https://` URLs become links, other text stays text.
- The page starts with `<!DOCTYPE html>` and has `<meta charset="utf-8">` and one `<style>` block (constant
  `SITE_CSS`, written by the builder: plain readable layout, max width about 1000 px, a light background).
- The same inputs always give the same string (no time stamps, no random ids).
- Every number shown outside the charts is a `text` field (or `cells` entry) from the report, the paper check or
  the review, copied as it is. Charts may format numbers with `fmt(x, d)` = `format(x, ",.%df" % d)`.

## 2. Functions

### headline(report: dict) -> str

`facts = report["facts"]`, `best = facts["best_lcoe_usd_per_kwh"]`, `dsl = facts["diesel_only_lcoe_usd_per_kwh"]`.
When `best["value"] < dsl["value"]`:
`"Yes. Solar plus battery cuts the cost of electricity on " + site + " from " + dsl["text"] + " to " + best["text"]
+ " USD/kWh (" + facts["lcoe_change_pct"]["text"] + "%)."`. Else:
`"No. On " + site + " the least cost design costs " + best["text"] + " USD/kWh against " + dsl["text"] +
" USD/kWh for diesel only."`. `site` is `report["site"]["name"]`. The result is plain text (not escaped).

### heatmap_svg(table: pd.DataFrame, best_pv_kwp: float, best_battery_kwh: float, unserved_max_frac: float) -> str

One `<svg ...>` element. `x` = sorted unique `pv_kwp`, `y` = sorted unique `battery_kwh`. One
`<rect class="cell ...">` per table row, at column index of its `pv_kwp` and row index of its `battery_kwh`
(battery 0 at the bottom). A row with `unserved_frac > unserved_max_frac` gets class `"cell infeasible"` and a grey
fill. The others get class `"cell"` and a fill from a light to a dark colour by `lcoe_usd_per_kwh` (darkest = the
lowest LCOE among the feasible rows). The best row (both sizes equal to the arguments) gets class `"cell best"` and a
thick outline. Every rect holds `<title>PV {fmt(pv,0)} kWp, battery {fmt(b,0)} kWh: {fmt(lcoe,3)} USD/kWh</title>`.
Axis labels name `PV kWp` and `Battery kWh`, and show the first, middle and last size of each axis.

### tornado_svg(rows: list[dict], base_lcoe: float) -> str

`rows` is `report["sensitivity_table"]`. Group rows by `input` (first seen order). For each input, `low` = the row
with the smallest factor and `high` = the row with the largest; the bar runs from `min` to `max` of their
`base_design_lcoe_usd_per_kwh`. Inputs are drawn widest bar first (ties keep first seen order), one
`<g class="bar">` each, holding a `<rect>` and a `<text>` with the input name and `fmt(lo,3) + " to " + fmt(hi,3)`.
A vertical line marks `base_lcoe`. An input with only one row is skipped.

### weather_svg(rows: list[dict]) -> str

`rows` is `report["weather_table"]`. One `<g class="bar">` per row in order, with a `<rect>` whose length is
proportional to `ghi_kwh_m2_yr` (the longest bar fills the width) and a `<text>` with the case name and
`fmt(ghi,0) + " kWh/m2/yr"`.

### render_study_html(report, table, *, paper_check=None, review=None) -> str

`table` is the design table (`design_table.csv` as a DataFrame). The page holds, in this order, each part in a
`<section id="...">` with an `<h2>`:

1. `id="answer"`, h2 `Answer`: the question, then `headline(report)` in a `<p class="headline">`, then one
   `<div class="card">` for each of these facts, holding the card title below and `text + " " + unit + " (" +
   label + ")"` from the fact:
   `best_pv_kwp`, `best_battery_kwh`, `best_lcoe_usd_per_kwh`, `diesel_only_lcoe_usd_per_kwh`,
   `best_renewable_pct`, `fuel_saved_l_yr`, `co2_saved_t_yr`, `break_even_fuel_usd_per_l`.
   Card titles, in the same order (constant `CARD_TITLES`, a tuple of 8 pairs `(fact key, title)`): PV size,
   Battery, Cost of electricity, Diesel only, Renewable share, Diesel saved, CO2 saved, Diesel price where PV
   starts to pay.
2. `id="firm"`, h2 `How firm is the answer`: only when `report.get("firmness")` is not None: a table with one row per
   item: title, `text`, unit, label.
3. `id="designs"`, h2 `Every design we costed`: `heatmap_svg(table, best_pv_kwp value, best_battery_kwh value,
   unserved_max)`, where `unserved_max` is the value of the `unserved_max_frac` row of `report["inputs_table"]`.
4. `id="sensitivity"`, h2 `What moves the cost`: `tornado_svg(report["sensitivity_table"], best_lcoe value)`.
5. `id="weather"`, h2 `Sunshine from four sources`: `weather_svg(report["weather_table"])`.
6. `id="range"`, h2 `Range of the answer`: a table of `report["range_table"]` `cells`, header as in the Markdown
   report (Weather, Demand, PV kWp, Battery kWh, LCOE USD/kWh, LCOE of the main design USD/kWh, Note).
7. `id="paper"`, h2 `The published study we used`: only when `paper_check` is not None:
   `"Flags " + str(summary["flags"]) + ", passes " + str(summary["passes"]) + ", not checkable " +
   str(summary["not_checkable"])`, then a table with one row per `paper_check["results"]` entry: check id, status,
   pages joined with ", ", detail. Rows with status `flag` get `class="flag"`. Then the sentence
   `"A flag means our checks could not reconcile the numbers as printed; it is not a finding about the authors."`
8. `id="review"`, h2 `Second model review`: only when `review` is not None: `review["model"]`, then one `<li>` per
   `review["points"]` entry: its `point`, and `addressed_in` or the word `open` when it is None.
9. `id="checks"`, h2 `Checks`: the gates table (`cells`).
10. `id="inputs"`, h2 `Inputs`: the inputs table (`cells`), then, when `report.get("sourcing")` is not None, the
    sourced inputs table (`cells`).
11. `id="scope"`, h2 `Not covered by this study`: only when firmness is not None: one `<li>` per `out_of_scope`
    line.
12. `id="sources"`, h2 `Sources`: one `<li>` per source line; inside it, every `http://` or `https://` URL (up to
    the next space, comma or the end) becomes a link.

The page title is `"AutoSolar study: " + site`. The header shows the run hash. The footer explains the labels:
measured, computed, assumed, press, paper, docs.

### render_index_html(cards: list[dict]) -> str

Each card is `{"href": str, "site": str, "question": str, "headline": str, "run_hash": str}`. The page title is
`"AutoSolar Researcher: study gallery"`. One `<a class="study" href="...">` per card in order, holding the site in an
`<h2>`, the question, the headline and the run hash. An empty list gives a page with the sentence
`"No studies yet."`.

## Done when

- `tests/test_site.py` passes, and every test that passed before still passes.
- `tools/check_text.py` passes on `autosolar/site.py`; it stays ASCII; no import outside the list above.

## Test check by the orchestrator

- Reference build in scratch (the spec written as a reference `site.py`): all 14 tests in `tests/test_site.py`
  pass; the full suite with them passed 976 of 976 before T12a2 (962 then present plus 14 new).
- 15 planted faults, each caught: escape keeps non-ASCII; headline sign flipped; best design not marked; infeasible
  designs not marked; tornado not sorted by width; tornado keeps inputs with one row; weather bars of fixed width;
  flag rows not marked; source URLs not linked; firmness section skipped; open review points not marked; empty
  gallery text missing; card label missing; question not escaped; paper section dropped when a review is given.
