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
