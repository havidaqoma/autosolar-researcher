# T20 and T21 smoke rules (written before the runs)

Status: written by the orchestrator after the T20 code passed its tests (63 of 63; 21 of 22 planted faults caught,
the other one is also stopped by `dispatch_grid`) and before any real run. T21 is built next; steps 3 to 5 run after
its tests pass. No model call is planned: both tasks only re-use saved study files, so the expected API cost is
USD 0 (measured from the ledger before and after).

## T20: load follow-up on the two latest studies

Runs, in this order, with the figure check the study pages already show (`figure-20261029T053942-12137f`):

1. `python tools/load_followup.py --run b4a44fc6d4c32339 --figure-check figure-20261029T053942-12137f`
2. `python tools/load_followup.py --run 107477f112e5d92c --figure-check figure-20261029T053942-12137f`

Pass: each run prints `reproduced yes` and exits 0, makes no network call (the weather comes from the local cache;
a cache miss stops the run), and adds no line to `ledger/api_usage.jsonl`.

Fail: `reproduced NO` (exit 3). Then the follow-up is not shown on any page, the result is reported as it is, and
the cause is looked for in the code, never by changing an input.

Whatever the numbers are, they are reported as they come out, including the case where diesel only wins at the
lower load. No other load scale is tried after seeing these results; the four cases are fixed in the T20 spec.

## T21 and the site

3. Add `"load_followup": "<run id>"` to the two latest gallery entries in `config/gallery.json` (only if step 1 or 2
   passed for that study), then `python tools/make_site.py`.
4. Pass: every page builds; each study page holds one `fuel-price` section with one checked step at the study's own
   price; the two latest pages hold "If the chart is right"; no page holds `<script`; older pages keep their
   numbers (only the new section is added).
5. Browser check (local file, no server): on `docs/site/b4a44fc6d4c32339.html`, click 0.20, 0.85 (study) and 1.60;
   the shown line must match `fuel_price_steps` for that price, and only one line shows at a time.

## Results

To be added after the runs, below this line, without editing the rules above.

Steps 1 and 2 (measured, `runs/load_followups/`, copied to `docs/site/data/<run>/load_followup.json`):

| Study | Follow-up run | Reproduced | Exit | Wall time |
|---|---|---|---|---|
| b4a44fc6d4c32339 (pre-registered) | followup-20261030T110813-24e132 | yes | 0 | 161 s |
| 107477f112e5d92c (curated, post hoc) | followup-20261030T111050-ee43ba | yes | 0 | 152 s |

`ledger/api_usage.jsonl` had 179 lines before and 179 after: no model call, USD 0 (measured).

At the load the chart day implies (23.3% lower, computed), pre-registered study: diesel only 0.388 USD/kWh, least
cost design 5,750 kWp + 15,000 kWh at 0.257 USD/kWh, 33.7% less (computed). The study's own design, 7,250 kWp +
19,000 kWh, costs 0.286 USD/kWh at that load (computed). Curated study: 0.562 against 0.284, 49.4% less (computed).
Diesel only does not win in any of the four cases on either study.

Steps 3 and 4: both gallery entries got `load_followup`; `tools/make_site.py` built 6 pages and the index. Each page
has one `fuel-price` section, one checked step, one "(study)" label and no `<script`. With the new section, its CSS
and (on the two latest pages) the "If the chart is right" block cut out, all 6 pages are the same as the pages
committed before, character for character (measured, scratch script).

Step 5 (measured, local Chrome via Playwright, scratch script): on the page load the 0.85 (study) line shows; clicks
on 0.20, 0.85 (study) and 1.60 each show one line, and each line starts with the clicked price and matches
`fuel_price_steps`. At 0.20 the line says diesel only wins; at 1.60 it says the design sits on the edge of the grid.

Result: PASS.
