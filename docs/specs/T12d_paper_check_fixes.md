# T12d: two fixes to the paper check found on the out-of-sample paper

Status: spec by the orchestrator. Builder edits `autosolar/paper_check.py` only. T12a and T12a2 stay in force except
where this spec changes them.

## Why

The first out-of-sample run (paper 2, original version, frozen prompt v4; runs paper-20261028T040923-bcd39c and
paper-20261028T041053-38ee74, measured) raised two flags that the frozen check text does not support:

1. P1 flagged `lcoe_usd_per_kwh: cannot compare 0.1192 (p1 abstract), 0.1192 (p32 conclusion)`. Both statements
   print the same number with the same (empty) unit. The frozen P1 flags values that differ by more than 1%, or
   units that differ without a conversion. Equal units are not different units, even when the unit is unknown.
2. P8 flagged `5.6 kWh/m2` as 5.6 kWh/m2/yr. A unit with no time period does not say per day or per year, so it
   must not be read as either.

Both are fixed here. The extraction files of every run are kept, so every run is scored again by script with the
fixed checks; the report gives both the as-run and the fixed numbers.

## Changes

1. In the P1 and P6 comparison of a group (same quantity and condition): when every member has the same cleaned
   unit string (the cleaning of `unit_factor`), the members are compared by `float(value) * (count or 1)` alone,
   with the same 1% rule, whether or not the unit is known. Groups with different unit strings keep the T12a rule
   (canonical values, and "cannot compare" when a factor is unknown or the kinds differ).
2. In the units table, `irradiation` loses the entry `kwh/m2` (it has no period). `unit_factor("kWh/m2",
   "irradiation")` is now None, so such statements are left out of P3 and P8 (P8 skips statements whose canonical
   value is None, as before).

## Done when

- `tests/test_paper_check_fixes.py` passes, and every test that passed before still passes.
- `tools/check_text.py` passes on `autosolar/paper_check.py`; it stays ASCII.

## Test check by the orchestrator

- Reference build in scratch (the two fixes applied to a copy of the T12a2 reference): all 9 tests in
  `tests/test_paper_check_fixes.py` pass; the full suite passes 1,019 of 1,019 (1,010 old plus 9 new).
- 5 planted faults, each caught: same-unit rule off; count ignored; every member read as equal; `kwh/m2` back in
  the table; raw unit strings compared without cleaning.
