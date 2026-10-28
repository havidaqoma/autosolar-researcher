# T13b: study page polish (layout, legend, plain-language caveats)

Status: spec by the orchestrator. Builder edits `autosolar/site.py` only. T13 stays in force except where this spec
changes it.

## Why

The first page (study 59eba198a2af900c, looked at in a browser) works but reads poorly: the eight answer cards
stack one per line, a horizontal scroll bar appears, the heat map's y label is cut off at the left edge and the
heat map has no colour key. The most important caveats (near ties, the reserve case, land, the published size, the
true cost) sit in a long table further down. A judge should see them next to the answer.

## 1. Layout

- The eight answer cards sit inside one `<div class="cards">`. `SITE_CSS` makes `.cards` a grid with
  `grid-template-columns: repeat(auto-fit, minmax(200px, 1fr))` (or an equal flex layout), so they show four or more
  per row on a laptop screen.
- Every `<svg>` and every `<table>` on the study page sits inside a `<div class="scroll">`, and `SITE_CSS` gives
  `.scroll` `overflow-x: auto`. The page must not need a horizontal scroll bar at 1000 px width for anything else.
- The heat map's y axis label `Battery kWh` is drawn rotated (`transform="rotate(-90 ...)"`) or placed so its whole
  text is inside the SVG (x >= 0 and the text starts at x >= 0).

## 2. Heat map colour key

`heatmap_svg` adds one `<g class="legend">` holding two `<text>` elements: `"lowest " + fmt(lo, 3) + " USD/kWh"`
and `"highest " + fmt(hi, 3) + " USD/kWh"` (lo and hi = the least and the largest LCOE among the feasible rows), each
next to a small `<rect>` in the colour that the heat map uses for that value, plus a third `<text>` with
`"grey: unserved energy above the limit"` when at least one row is infeasible.

## 3. caveats(report) -> list[str]

New function. Returns `[]` when `report.get("firmness")` is None. Else, with `it(key)` = the firmness item with
that key, it returns these five strings in this order (texts and units copied from the items):

1. `"Near tie: " + it("near_tie_count").text + " designs are within " + it("near_tie_pct").text + "% of the least
   cost, from " + it("near_tie_pv_kwp_min").text + " to " + it("near_tie_pv_kwp_max").text + " kWp of PV."`
2. `"Reserve case: if " + it("reserve_units").text + " diesel unit(s) must run in every hour, the least cost design
   is " + it("reserve_pv_kwp").text + " kWp with " + it("reserve_battery_kwh").text + " kWh at " +
   it("reserve_lcoe_usd_per_kwh").text + " USD/kWh, and the main design would cost " +
   it("reserve_main_design_lcoe_usd_per_kwh").text + " USD/kWh."`
3. `"Land: the main design needs " + it("land_need_ha").text + " ha of the " + it("land_site_ha").text + " ha set
   aside (fits: " + it("land_fits").text + ")."`
4. `"Published design size: " + it("reference_pv_kwp").text + " kWp of PV with no battery gives " +
   it("reference_lcoe_usd_per_kwh").text + " USD/kWh."`
5. `"Cost: this study used " + it("total_cost_usd").text + " USD of model API calls, of which " +
   it("sourcing_cost_usd").text + " USD was the web search that sourced its inputs."`

`render_study_html` shows them in the answer section, right after the headline and before the cards, as
`<ul class="caveats">` with one `<li>` per string (escaped).

## Done when

- `tests/test_site_polish.py` passes, and every test that passed before still passes.
- `tools/check_text.py` passes on `autosolar/site.py`; it stays ASCII.

## Test check by the orchestrator

- Reference build in scratch (the change applied to a copy of the T13 reference): all 6 tests in
  `tests/test_site_polish.py` pass; the full suite passes 1,000 of 1,000 (994 old plus 6 new).
- 9 planted faults, each caught: caveat text changed; SVG not wrapped; tables not wrapped; legend in the wrong
  colour; grey note always shown; caveats after the cards; cards not wrapped; y label cut off; card grid lost.
