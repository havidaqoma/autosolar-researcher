"""Post hoc twin test of the checking step. Numbers carry units in names."""

import json
import math
import os
import pathlib
from collections.abc import Callable
from typing import Any

from autosolar.cite_check import Claim, numbers_in, support_verdict
from autosolar.sourcing import ascii_text

TWIN_SCHEMA = "autosolar.twin_test/1"
SHIFTS_FRAC = (-0.30, -0.10, -0.01, 0.0, 0.01, 0.10, 0.30)
LEVELS_FRAC = (0.0, 0.01, 0.10, 0.30)
VOTES = 3
TWIN_STATUSES = ("checked", "curated")
TWIN_DESCRIPTIONS = {
    "pv_capex_usd_per_kwp": "installed capital cost of a solar PV plant per kW",
    "pv_om_usd_per_kwp_yr": "annual fixed operation and maintenance cost of a solar PV plant per kW",
    "battery_capex_usd_per_kwh": "capital cost of the energy part of a lithium-ion battery storage system",
    "battery_om_usd_per_kwh_yr": "annual fixed operation and maintenance cost of a lithium-ion battery storage system",
    "battery_power_capex_usd_per_kw": "capital cost of the power part of a lithium-ion battery storage system",
    "battery_life_yr": "technical lifetime of a lithium-ion battery storage system",
    "battery_round_trip_eff_frac": "round-trip efficiency of a lithium-ion battery storage system",
    "fuel_price_usd_per_l": "price of industrial diesel fuel per litre",
    "discount_rate_frac": "discount rate or cost of capital for renewable energy projects",
    "diesel_min_load_frac": "minimum load of a diesel generator as a share of its rated power",
}
NOTE = (
    "Post hoc test, written after the studies. Each checked or curated value is given to the checker again with its "
    "number moved by 1%, 10% and 30%, down and up. The script check needs the claimed number inside the quote. The "
    "local judge (votes 1 and 2 in a study) sees the claimed value, the quote, the source title and URL; here the "
    "quote stands in for the source text around it. The Wonder vote (vote 3 in a study) is not run, to keep Meta "
    "model spending at zero. In a study a value is used only if every check passes."
)


def _is_real_number(value: Any) -> bool:
    """Check finite int or float, not bool. Output bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def value_in_quote(value: float | int, quote: str) -> bool:
    """Check claimed value appears in quote numbers. Tolerance is relative."""
    if not _is_real_number(value):
        raise ValueError("value must be a finite number, not bool")
    if not isinstance(quote, str):
        raise ValueError("quote must be a str")
    target = float(value)
    tol = 1e-9 * max(1, abs(target))
    return any(abs(n - target) <= tol for n in numbers_in(quote))


def twin_value(value: float | int, shift_frac: float | int) -> float | int:
    """Move value by shift_frac with 4 significant digits. Output int or float."""
    if not _is_real_number(value):
        raise ValueError("value must be a finite number, not bool")
    if not _is_real_number(shift_frac):
        raise ValueError("shift_frac must be a finite number, not bool")
    if shift_frac == 0.0:
        num = float(value)
        return int(num) if num.is_integer() else num
    moved = float(value) * (1 + float(shift_frac))
    num = float(format(moved, ".4g"))
    if num == float(value):
        raise ValueError("shift leaves the value unchanged at 4 significant digits")
    return int(num) if num.is_integer() else num


def _report_rows(site_dir: pathlib.Path) -> list[tuple[str, dict]]:
    """Read report rows per study folder. Output (study, row) pairs."""
    out: list[tuple[str, dict]] = []
    for handle in sorted(os.listdir(site_dir / "data")):
        report_path = site_dir / "data" / handle / "report.json"
        if not report_path.is_file():
            continue
        with open(report_path, encoding="utf-8") as fh:
            report = json.load(fh)
        rows: list = []
        if isinstance(report, dict):
            sourcing = report.get("sourcing")
            if isinstance(sourcing, dict) and isinstance(sourcing.get("rows"), list):
                rows = sourcing["rows"]
        for row in rows:
            out.append((handle, row))
    return out


def collect_items(site_dir: str | pathlib.Path) -> tuple[list[dict], list[dict]]:
    """Collect checked or curated rows with usable quotes. Output (items, skipped)."""
    site = pathlib.Path(site_dir)
    items: list[dict] = []
    skipped: list[dict] = []
    seen: set[tuple] = set()
    for handle, row in _report_rows(site):
        if not isinstance(row, dict) or row.get("status") not in TWIN_STATUSES:
            continue
        key = (row.get("input"), repr(row.get("value_as_written")),
               row.get("unit_as_written"), row.get("quote"))
        if key in seen:
            continue
        seen.add(key)
        value = row.get("value_as_written")
        quote = row.get("quote")
        if not _is_real_number(value) or not isinstance(quote, str) or quote == "":
            reason = "no number or quote"
        elif row.get("input") not in TWIN_DESCRIPTIONS:
            reason = "no description"
        elif not value_in_quote(value, quote):
            reason = "value not in quote"
        else:
            reason = ""
        if reason:
            skipped.append({"study": handle, "input": row.get("input"), "status": row.get("status"),
                            "value": value, "unit": row.get("unit_as_written"), "reason": reason})
            continue
        title = row.get("title")
        url = row.get("url")
        doi = row.get("doi")
        currency_year = row.get("currency_year")
        items.append({"id": "i%02d" % (len(items) + 1), "study": handle, "input": row.get("input"),
                      "status": row.get("status"), "value": value, "unit": row.get("unit_as_written"),
                      "quote": quote, "title": title if isinstance(title, str) else "",
                      "url": url if isinstance(url, str) else "",
                      "doi": doi if isinstance(doi, str) and doi != "" else None,
                      "currency_year": currency_year if isinstance(currency_year, int)
                      and not isinstance(currency_year, bool) else None})
    return items, skipped


def make_twins(items: list[dict]) -> list[dict]:
    """Make shifted copies of each item. Output twin dicts."""
    twins: list[dict] = []
    for item in items:
        for shift in SHIFTS_FRAC:
            value = twin_value(item["value"], shift)
            twins.append({"key": item["id"] + ":" + format(shift, "+.2f"), "item": item["id"],
                          "shift_frac": shift, "value": value,
                          "script_caught": not value_in_quote(value, item["quote"])})
    return twins


def claim_for(item: dict, value: float | int) -> Claim:
    """Build a citation claim for one twin value. Output Claim."""
    return Claim(input_name=item["input"], description=TWIN_DESCRIPTIONS[item["input"]], value=value,
                 unit=item["unit"], url=item["url"], doi=item["doi"], quote=item["quote"],
                 title=item["title"], currency_year=item["currency_year"])


def run_votes(items: list[dict], twins: list[dict], judge_fn: Callable[[str], str], votes: int,
              done: dict, on_vote: Callable[[dict], None] | None = None) -> dict:
    """Ask the judge for each twin and vote. Output done, updated in place."""
    if isinstance(votes, bool) or not isinstance(votes, int) or votes < 1:
        raise ValueError("votes must be an int of 1 or more")
    by_id = {item["id"]: item for item in items}
    for twin in twins:
        item = by_id[twin["item"]]
        claim = claim_for(item, twin["value"])
        for num in range(1, votes + 1):
            if (twin["key"], num) in done:
                continue
            verdict = support_verdict(judge_fn, claim, item["quote"],
                                      source_title=item["title"] or None,
                                      source_url=item["url"] or None)
            record = {"key": twin["key"], "vote": num, "supports": verdict.supports,
                      "reason": verdict.reason, "raw": verdict.raw}
            done[(twin["key"], num)] = record
            if on_vote is not None:
                on_vote(record)
    return done


def summarise(twins: list[dict], done: dict, votes: int) -> list[dict]:
    """Count script and judge stops per shift level. Output one row per level."""
    rows: list[dict] = []
    for level in LEVELS_FRAC:
        group = [t for t in twins if round(abs(t["shift_frac"]), 2) == level]
        vote_keys = [(t["key"], num) for t in group for num in range(1, votes + 1)]
        present = [done[k] for k in vote_keys if k in done]
        panel_runs = 0
        panel_caught = 0
        if votes >= 2:
            for twin in group:
                first = done.get((twin["key"], 1))
                second = done.get((twin["key"], 2))
                if first is not None and second is not None:
                    panel_runs += 1
                    if first["supports"] is not True or second["supports"] is not True:
                        panel_caught += 1
        rows.append({"level_frac": level, "n_twins": len(group),
                     "script_caught": sum(1 for t in group if t["script_caught"]),
                     "votes_total": len(present),
                     "votes_not_yes": sum(1 for r in present if r["supports"] is not True),
                     "votes_no_verdict": sum(1 for r in present if r["supports"] is None),
                     "panel_runs": panel_runs, "panel_caught": panel_caught})
    return rows


def _level_label(level_frac: float) -> str:
    """Label one summary level. Output display text."""
    if level_frac == 0.0:
        return "True value"
    return "Moved " + format(100 * level_frac, "g") + "%"


def render_md(doc: dict) -> str:
    """Render the twin test report. Output ASCII markdown with trailing newline."""
    lines = ["# Twin test of the checking step (post hoc)", "",
             ascii_text(doc["note"]), "",
             "Judge: " + ascii_text(str(doc["judge"])) + ". Votes per twin: "
             + str(doc["votes"]) + ". Items: " + str(len(doc["items"])) + ". Twins: "
             + str(len(doc["twins"])) + ".", "",
             "| Number given to the checker | Twins | Script: number not in the quote | Local judge, "
             "single votes: not yes | Local judge, votes 1 and 2 as in a study: not yes |",
             "|---|---|---|---|---|"]
    for row in doc["summary"]:
        votes_cell = "not run" if row["votes_total"] == 0 else "%d of %d" % (row["votes_not_yes"],
                                                                             row["votes_total"])
        panel_cell = "not run" if row["panel_runs"] == 0 else "%d of %d" % (row["panel_caught"],
                                                                           row["panel_runs"])
        lines.append("| " + _level_label(row["level_frac"]) + " | " + str(row["n_twins"]) + " | "
                     + str(row["script_caught"]) + " of " + str(row["n_twins"]) + " | "
                     + votes_cell + " | " + panel_cell + " |")
    lines += ["", "## Items", ""]
    for item in doc["items"]:
        lines.append("- " + ascii_text(str(item["id"])) + ": " + ascii_text(str(item["input"])) + " ("
                     + ascii_text(str(item["status"])) + ", study " + ascii_text(str(item["study"]))
                     + "): " + format(item["value"], "g") + " " + ascii_text(str(item["unit"]))
                     + '; quote: "' + ascii_text(item["quote"])[:200] + '"')
    lines += ["", "## Skipped", ""]
    if doc["skipped"]:
        for row in doc["skipped"]:
            lines.append("- " + ascii_text(str(row["input"])) + " (" + ascii_text(str(row["status"]))
                         + ", study " + ascii_text(str(row["study"])) + "): "
                         + ascii_text(str(row["reason"])))
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"
