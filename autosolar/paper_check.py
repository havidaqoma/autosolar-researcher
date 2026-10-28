"""Paper check: confirm extracted numbers are in the PDF, then run P1 to P15.

Energy in kWh, power in kW, money in USD, time in yr unless the name says more.
"""
import dataclasses
import json
import math

from autosolar.cite_check import find_quote, numbers_in

PLACES = ("abstract", "text", "table", "caption", "conclusion")
CHECK_IDS = tuple("P%d" % i for i in range(1, 16))
SIZE_QUANTITIES = ("pv_ac_kw", "pv_dc_kwp", "battery_size", "diesel_kw", "converter_kw")

QUANTITIES = {
    "pv_ac_kw": "power",
    "pv_dc_kwp": "power",
    "diesel_kw": "power",
    "converter_kw": "power",
    "battery_kw": "power",
    "peak_load_kw": "power",
    "pv_module_wp": "power",
    "battery_size": "battery",
    "pv_module_count": "count",
    "pv_module_area_m2": "area",
    "pv_area_m2": "area",
    "load_kwh_day": "energy",
    "pv_kwh_day": "energy",
    "diesel_kwh_day": "energy",
    "load_kwh_yr": "energy",
    "pv_kwh_yr": "energy",
    "diesel_kwh_yr": "energy",
    "energy_served_kwh_yr": "energy",
    "ghi_kwh_m2_yr": "irradiation",
    "wind_m_s": "speed",
    "lcoe_usd_per_kwh": "money_per_energy",
    "base_coe_usd_per_kwh": "money_per_energy",
    "battery_capex_usd_per_kwh": "money_per_energy",
    "npc_usd": "money",
    "capex_usd": "money",
    "annual_cost_usd": "money",
    "cost_item_usd": "money",
    "om_cost_usd": "money",
    "pv_capex_usd_per_kw": "money_per_power",
    "diesel_capex_usd_per_kw": "money_per_power",
    "fuel_price_usd_per_l": "money_per_volume",
    "discount_rate_frac": "fraction",
    "renewable_fraction_frac": "fraction",
    "battery_rte_frac": "fraction",
    "project_life_yr": "time",
    "fuel_l_yr": "volume",
    "co2_kg_yr": "mass",
}

_UNIT_TABLE = {
    "power": {"w": 0.001, "kw": 1.0, "mw": 1000.0, "gw": 1e6, "wp": 0.001,
              "kwp": 1.0, "mwp": 1000.0, "kwac": 1.0, "mwac": 1000.0,
              "kwdc": 1.0, "mwdc": 1000.0},
    "energy": {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0, "gwh": 1e6},
    "battery": {"kwh": 1.0, "mwh": 1000.0, "wh": 0.001, "ah": 1.0,
                "kah": 1000.0, "mah": 1e6},
    "area": {"m2": 1.0, "ha": 10000.0, "km2": 1e6},
    "irradiation": {"kwh/m2/yr": 1.0, "kwh/m2/year": 1.0, "kwh/m2/a": 1.0,
                    "kwh/m2/day": 365.0, "kwh/m2/d": 365.0, "kwh/m2": 1.0},
    "speed": {"m/s": 1.0, "km/h": 1.0 / 3.6},
    "money_per_energy": {"$/kwh": 1.0, "$/mwh": 0.001, "cents/kwh": 0.01,
                         "c/kwh": 0.01},
    "money": {"$": 1.0, "k$": 1000.0, "$k": 1000.0, "thousand$": 1000.0,
              "million$": 1e6, "m$": 1e6, "$m": 1e6},
    "money_per_power": {"$/kw": 1.0, "$/kwp": 1.0, "$/mw": 0.001,
                        "$/w": 1000.0, "$/wp": 1000.0},
    "money_per_volume": {"$/l": 1.0, "$/liter": 1.0, "$/litre": 1.0},
    "fraction": {"%": 0.01, "frac": 1.0, "": 1.0},
    "time": {"yr": 1.0, "year": 1.0, "years": 1.0, "a": 1.0},
    "volume": {"l": 1.0, "liter": 1.0, "litre": 1.0, "liters": 1.0,
               "litres": 1.0, "kl": 1000.0, "ml": 1e6},
    "mass": {"kg": 1.0, "t": 1000.0, "ton": 1000.0, "tonne": 1000.0,
             "tons": 1000.0, "tonnes": 1000.0, "kt": 1e6},
}

_CHARGE_UNITS = ("ah", "kah", "mah")


@dataclasses.dataclass(frozen=True)
class CheckResult:
    """One check outcome. Pages hold 1 based page numbers."""

    check_id: str
    status: str
    detail: str
    pages: tuple


def _clean_unit(unit: str) -> str:
    """Clean a unit as written. Output lookup key."""
    s = unit.lower()
    s = "".join(s.split())
    s = s.replace(chr(178), "2")
    s = s.replace("us$", "$")
    s = s.replace("usd", "$")
    return s


def unit_factor(unit: str, dimension: str) -> float | None:
    """Factor to the canonical unit. None when the unit is unknown."""
    if dimension == "count" and isinstance(unit, str):
        return 1.0
    if not isinstance(unit, str):
        return None
    table = _UNIT_TABLE.get(dimension)
    if table is None:
        return None
    return table.get(_clean_unit(unit))


def unit_kind(unit: str, dimension: str) -> str | None:
    """Kind used for compare. Charge for charge units, else dimension."""
    if not isinstance(unit, str) or not isinstance(dimension, str):
        return None
    if dimension == "count":
        return "count"
    if dimension == "battery" and _clean_unit(unit) in _CHARGE_UNITS:
        return "charge"
    if unit_factor(unit, dimension) is None:
        return None
    return dimension


_ST_KEYS = frozenset(("quantity", "value", "count", "unit", "condition",
                      "page", "place", "quote"))
_ROW_KEYS = frozenset(("time", "load_kw", "pv_to_load_kw", "pv_total_kw",
                       "pv_to_battery_kw", "battery_discharge_kw",
                       "diesel_kw", "curtailed_kw"))
_ROW_NUM_KEYS = ("load_kw", "pv_to_load_kw", "pv_total_kw",
                 "pv_to_battery_kw", "battery_discharge_kw", "diesel_kw",
                 "curtailed_kw")


def _is_num(value) -> bool:
    """Check finite int or float, not bool. Output True or False."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def _statement_reason(item) -> str | None:
    """Check one statement dict. Output reason text or None."""
    if not isinstance(item, dict) or set(item.keys()) != set(_ST_KEYS):
        return "statement needs exactly the 8 keys"
    if item["quantity"] not in QUANTITIES:
        return "unknown quantity %r" % (item["quantity"],)
    if not _is_num(item["value"]):
        return "value must be a finite number"
    count = item["count"]
    if count is not None and (isinstance(count, bool) or not isinstance(count, int)
                              or count < 1):
        return "count must be None or an int >= 1"
    for key in ("unit", "condition", "quote"):
        if not isinstance(item[key], str):
            return "%s must be a string" % key
    if isinstance(item["page"], bool) or not isinstance(item["page"], int) \
            or item["page"] < 1:
        return "page must be an int >= 1"
    if item["place"] not in PLACES:
        return "unknown place %r" % (item["place"],)
    return None


def _row_reason(item) -> str | None:
    """Check one schedule row dict. Output reason text or None."""
    if not isinstance(item, dict) or set(item.keys()) != set(_ROW_KEYS):
        return "row needs exactly the 8 keys"
    if not isinstance(item["time"], str):
        return "time must be a string"
    if not _is_num(item["load_kw"]) or not item["load_kw"] >= 0:
        return "load_kw must be a finite number >= 0"
    for key in _ROW_NUM_KEYS[1:]:
        value = item[key]
        if value is not None and (not _is_num(value) or not value >= 0):
            return "%s must be None or a finite number >= 0" % key
    return None


def _schedule_reason(item) -> str | None:
    """Check the schedule dict. Output reason text or None."""
    if not isinstance(item, dict) or set(item.keys()) != {"page", "label",
                                                          "period_h", "rows"}:
        return "schedule needs exactly the keys page, label, period_h, rows"
    if isinstance(item["page"], bool) or not isinstance(item["page"], int) \
            or item["page"] < 1:
        return "schedule page must be an int >= 1"
    if not isinstance(item["label"], str):
        return "schedule label must be a string"
    if not _is_num(item["period_h"]) or not item["period_h"] > 0:
        return "schedule period_h must be a finite number > 0"
    if not isinstance(item["rows"], list):
        return "schedule rows must be a list"
    for row in item["rows"]:
        reason = _row_reason(row)
        if reason is not None:
            return reason
    return None


def parse_extraction(text: str) -> dict:
    """Parse model JSON text. Returns statements, schedule, rejected."""
    body = text.strip()
    if body.startswith("```"):
        cut = body.find("\n")
        if cut == -1:
            body = ""
        else:
            body = body[cut + 1:]
        body = body.strip()
        if body.endswith("```"):
            body = body[:-3].strip()
    try:
        data = json.loads(body)
    except Exception:
        raise ValueError("extraction is not JSON")
    if not isinstance(data, dict) or set(data.keys()) != {"statements",
                                                          "schedule"}:
        raise ValueError("extraction needs exactly statements and schedule")
    if not isinstance(data["statements"], list):
        raise ValueError("statements must be a list")
    statements = []
    rejected = []
    for i, item in enumerate(data["statements"]):
        reason = _statement_reason(item)
        if reason is None:
            statements.append(item)
        else:
            rejected.append({"index": i, "reason": reason})
    schedule = None
    if data["schedule"] is not None:
        reason = _schedule_reason(data["schedule"])
        if reason is None:
            schedule = data["schedule"]
        else:
            rejected.append({"index": "schedule", "reason": reason})
    return {"statements": statements, "schedule": schedule,
            "rejected": rejected}


def verify_extraction(extraction: dict, pages: list) -> dict:
    """Keep statements and schedule found in the PDF. Returns kept plus dropped."""
    kept = []
    dropped = []
    for stmt in extraction["statements"]:
        match = find_quote(stmt["quote"], pages)
        if not match.found:
            if stmt.get("place") != "table":
                dropped.append({"what": stmt["quantity"], "page": stmt["page"],
                                "reason": "quote not found in the PDF"})
                continue
            slots = [stmt["page"] - 2, stmt["page"] - 1, stmt["page"]]
            near = " ".join(pages[i] for i in slots if 0 <= i < len(pages))
            known = numbers_in(near)
            if float(stmt["value"]) not in known:
                dropped.append({"what": stmt["quantity"], "page": stmt["page"],
                                "reason": "table number not found on its page"})
                continue
            if stmt["count"] is not None \
                    and float(stmt["count"]) not in known:
                dropped.append({"what": stmt["quantity"], "page": stmt["page"],
                                "reason": "table number not found on its page"})
                continue
            full = dict(stmt)
            full["found_page"] = stmt["page"]
            full["quote_kind"] = "table number"
            kept.append(full)
            continue
        quote_numbers = numbers_in(stmt["quote"])
        if float(stmt["value"]) not in quote_numbers:
            dropped.append({"what": stmt["quantity"], "page": stmt["page"],
                            "reason": "value not in the quote"})
            continue
        if stmt["count"] is not None \
                and float(stmt["count"]) not in quote_numbers:
            dropped.append({"what": stmt["quantity"], "page": stmt["page"],
                            "reason": "count not in the quote"})
            continue
        full = dict(stmt)
        full["found_page"] = match.page
        full["quote_kind"] = match.kind
        kept.append(full)
    schedule = None
    raw = extraction["schedule"]
    if raw is not None:
        row_numbers = []
        for row in raw["rows"]:
            for key in _ROW_NUM_KEYS:
                if row[key] is not None:
                    row_numbers.append(float(row[key]))
        slots = [raw["page"] - 2, raw["page"] - 1, raw["page"]]
        near = " ".join(pages[i] for i in slots if 0 <= i < len(pages))
        known = set(numbers_in(near))
        if row_numbers:
            frac = sum(1 for v in row_numbers if v in known) / len(row_numbers)
        else:
            frac = 1.0
        if frac >= 0.95:
            schedule = dict(raw)
            schedule["numbers_found_frac"] = frac
        else:
            dropped.append({"what": "schedule", "page": raw["page"],
                            "reason": "schedule numbers not found on its page"})
    return {"statements": kept, "schedule": schedule, "dropped": dropped,
            "rejected": extraction["rejected"]}


def _factor_of(stmt: dict):
    """Factor to the canonical unit. None when unknown."""
    return unit_factor(stmt.get("unit"), QUANTITIES.get(stmt.get("quantity")))


def _kind_of(stmt: dict):
    """Kind used for compare. None when unknown."""
    return unit_kind(stmt.get("unit"), QUANTITIES.get(stmt.get("quantity")))


def _canon_of(stmt: dict):
    """Canonical value from value, count and unit. None when unknown."""
    factor = _factor_of(stmt)
    if factor is None:
        return None
    count = stmt.get("count")
    mult = count if count is not None else 1
    return float(stmt["value"]) * float(mult) * factor


def _fmt_num(value) -> str:
    """Format a number for detail text. Output with separator."""
    return format(float(value), ",.4g")


def _ascii(text) -> str:
    """Drop non ASCII chars. Output plain text."""
    return str(text).encode("ascii", "ignore").decode("ascii")


def _ref(stmt: dict) -> str:
    """Short evidence ref. Shows value, unit, page, place."""
    return "%s %s (p%s %s)" % (_fmt_num(stmt["value"]), _ascii(stmt["unit"]),
                               _ascii(stmt["page"]), _ascii(stmt.get("place", "")))


def _stmt_pages(stmts: list) -> tuple:
    """Sorted unique found pages. Input kept statements."""
    return tuple(sorted({s["found_page"] for s in stmts
                         if s.get("found_page") is not None}))


def _day_totals(schedule):
    """Day totals in kWh from the schedule. Output dict or None."""
    if schedule is None or not schedule["rows"]:
        return None
    period_h = float(schedule["period_h"])
    if len(schedule["rows"]) != round(24.0 / period_h):
        return None
    rows = schedule["rows"]
    totals = {"load": sum(float(r["load_kw"]) for r in rows) * period_h}
    if any(r["pv_total_kw"] is not None for r in rows):
        totals["pv"] = sum(float(r["pv_total_kw"] or 0.0)
                           for r in rows) * period_h
    elif any(r["pv_to_load_kw"] is not None or r["pv_to_battery_kw"] is not None
             for r in rows):
        totals["pv"] = sum(float(r["pv_to_load_kw"] or 0.0)
                           + float(r["pv_to_battery_kw"] or 0.0)
                           for r in rows) * period_h
    else:
        totals["pv"] = None
    if any(r["diesel_kw"] is not None for r in rows):
        totals["diesel"] = sum(float(r["diesel_kw"] or 0.0)
                               for r in rows) * period_h
    else:
        totals["diesel"] = None
    return totals


def _p1_p6(check_id: str, quantities: tuple, statements: list) -> CheckResult:
    """One quantity one value check. Covers P1 and P6. Tolerances in frac."""
    failing = []
    agreed = []
    pages = set()
    for qty in quantities:
        groups: dict = {}
        for stmt in statements:
            if stmt["quantity"] == qty:
                groups.setdefault(stmt["condition"], []).append(stmt)
        for cond, grp in groups.items():
            if len(grp) < 2:
                continue
            pages.update(_stmt_pages(grp))
            kinds = set()
            canons = []
            comparable = True
            for stmt in grp:
                kind = _kind_of(stmt)
                canon = _canon_of(stmt)
                if kind is None or canon is None:
                    comparable = False
                    break
                kinds.add(kind)
                canons.append(canon)
            if not comparable or len(kinds) > 1:
                failing.append("%s [%s]: cannot compare %s" %
                               (qty, _ascii(cond),
                                ", ".join(_ref(s) for s in grp)))
            elif max(canons) - min(canons) > 0.01 * min(abs(c) for c in canons):
                failing.append("%s [%s]: differ %s" %
                               (qty, _ascii(cond),
                                ", ".join(_ref(s) for s in grp)))
            else:
                agreed.append("%s [%s]: %s" %
                              (qty, _ascii(cond),
                               ", ".join(_ref(s) for s in grp)))
    if failing:
        return CheckResult(check_id, "flag", "; ".join(failing),
                           tuple(sorted(pages)))
    if agreed:
        return CheckResult(check_id, "pass",
                           "; ".join(agreed) + " agree within 1%",
                           tuple(sorted(pages)))
    return CheckResult(check_id, "not checkable",
                       "no quantity stated twice under one condition", ())


def _p2(schedule) -> CheckResult:
    """Energy balance per row. Power in kW, tolerance in frac."""
    pages = (schedule["page"],) if schedule is not None else ()
    checked_n = 0
    fails = []
    worst_kv = 0.0
    worst_time = ""
    if schedule is not None:
        for row in schedule["rows"]:
            load_kw = float(row["load_kw"])
            pv_direct_kw = row["pv_to_load_kw"]
            pv_total_kw = row["pv_total_kw"]
            if pv_direct_kw is not None:
                supply_kw = (float(pv_direct_kw)
                             + float(row["diesel_kw"] or 0.0)
                             + float(row["battery_discharge_kw"] or 0.0))
            elif pv_total_kw is not None:
                supply_kw = (float(pv_total_kw)
                             + float(row["diesel_kw"] or 0.0)
                             + float(row["battery_discharge_kw"] or 0.0)
                             - float(row["pv_to_battery_kw"] or 0.0)
                             - float(row["curtailed_kw"] or 0.0))
            else:
                continue
            checked_n += 1
            gap_kw = abs(supply_kw - load_kw)
            if gap_kw > worst_kv:
                worst_kv = gap_kw
                worst_time = row["time"]
            if load_kw == 0:
                bad = supply_kw > 0.001
            else:
                bad = gap_kw > 0.02 * load_kw
            if bad:
                fails.append("%s %s kW vs %s kW" %
                             (_ascii(row["time"]), _fmt_num(supply_kw),
                              _fmt_num(load_kw)))
    if fails:
        detail = "%d of %d rows fail: %s" % (len(fails), checked_n,
                                             "; ".join(fails[:8]))
        return CheckResult("P2", "flag", detail, pages if checked_n else ())
    if checked_n:
        detail = "all %d rows balance within 2%%, worst gap %s kW at %s" % (
            checked_n, _fmt_num(worst_kv), _ascii(worst_time))
        return CheckResult("P2", "pass", detail, pages)
    return CheckResult("P2", "not checkable",
                       "no schedule row has PV numbers to check", ())


def _known(stmts: list) -> list:
    """Statements with known canonical values. Input kept statements."""
    return [s for s in stmts if _canon_of(s) is not None]


def _first_canon(stmts: list):
    """First known canonical value. None when missing."""
    for stmt in stmts:
        canon = _canon_of(stmt)
        if canon is not None:
            return canon, stmt
    return None, None


def _stmts_of(statements: list, quantity: str) -> list:
    """Kept statements of one quantity. Order kept as input."""
    return [s for s in statements if s["quantity"] == quantity]


def _p15(statements: list, schedule) -> CheckResult:
    """Time totals agree. Energy in kWh, tolerance in frac."""
    totals = _day_totals(schedule)
    sched_page = schedule["page"] if schedule is not None else None
    pairs = []
    for name in ("load", "pv", "diesel"):
        day_stmts = _known(_stmts_of(statements, name + "_kwh_day"))
        yr_stmts = _known(_stmts_of(statements, name + "_kwh_yr"))
        day_kwh = totals[name] if totals is not None else None
        if day_kwh is not None:
            for stmt in day_stmts:
                pairs.append(("%s_kwh_day vs schedule" % name,
                              _canon_of(stmt), day_kwh, [stmt], True))
            for stmt in yr_stmts:
                pairs.append(("%s_kwh_yr vs schedule x 365" % name,
                              _canon_of(stmt), day_kwh * 365.0, [stmt], True))
        for yst in yr_stmts:
            for dst in day_stmts:
                pairs.append(("%s_kwh_yr vs %s_kwh_day x 365" % (name, name),
                              _canon_of(yst), _canon_of(dst) * 365.0,
                              [yst, dst], False))
    failing = []
    pages = set()
    for label, val_a, val_b, stmts, uses_sched in pairs:
        if uses_sched and sched_page is not None:
            pages.update(list(_stmt_pages(stmts)) + [sched_page])
        else:
            pages.update(_stmt_pages(stmts))
        if abs(val_a - val_b) > 0.02 * min(abs(val_a), abs(val_b)):
            failing.append("%s: %s vs %s kWh" % (label, _fmt_num(val_a),
                                                _fmt_num(val_b)))
    if failing:
        return CheckResult("P15", "flag", "; ".join(failing),
                           tuple(sorted(pages)))
    if pairs:
        first = pairs[0]
        detail = "%d pairs agree within 2%%, for example %s: %s vs %s kWh" % (
            len(pairs), first[0], _fmt_num(first[1]), _fmt_num(first[2]))
        return CheckResult("P15", "pass", detail, tuple(sorted(pages)))
    return CheckResult("P15", "not checkable",
                       "no day or year energy pair to compare", ())


def _p3(statements: list, schedule, site) -> CheckResult:
    """PV yield possible. Energy in kWh/yr, size in kWp, yield in kWh/kWp."""
    energy_kwh_yr = None
    energy_from = ""
    pages = set()
    yr_canon, yr_stmt = _first_canon(_stmts_of(statements, "pv_kwh_yr"))
    day_canon, day_stmt = _first_canon(_stmts_of(statements, "pv_kwh_day"))
    totals = _day_totals(schedule)
    sched_kwh_day = totals["pv"] if totals is not None else None
    if yr_canon is not None:
        energy_kwh_yr = yr_canon
        energy_from = "pv_kwh_yr %s" % _ref(yr_stmt)
        pages.update(_stmt_pages([yr_stmt]))
    elif day_canon is not None:
        energy_kwh_yr = day_canon * 365.0
        energy_from = "pv_kwh_day %s x 365" % _ref(day_stmt)
        pages.update(_stmt_pages([day_stmt]))
    elif sched_kwh_day is not None and sched_kwh_day > 0 \
            and schedule is not None:
        energy_kwh_yr = sched_kwh_day * 365.0
        energy_from = "schedule pv day %s kWh x 365" % _fmt_num(sched_kwh_day)
        pages.add(schedule["page"])
    size_kwp = None
    size_from = ""
    dc_canon, dc_stmt = _first_canon(_stmts_of(statements, "pv_dc_kwp"))
    cnt_canon, cnt_stmt = _first_canon(_stmts_of(statements,
                                                "pv_module_count"))
    wp_canon, wp_stmt = _first_canon(_stmts_of(statements, "pv_module_wp"))
    ac_canon, ac_stmt = _first_canon(_stmts_of(statements, "pv_ac_kw"))
    if dc_canon is not None:
        size_kwp = dc_canon
        size_from = "pv_dc_kwp %s" % _ref(dc_stmt)
        pages.update(_stmt_pages([dc_stmt]))
    elif cnt_canon is not None and wp_canon is not None:
        size_kwp = cnt_canon * wp_canon
        size_from = "modules %s x %s" % (_ref(cnt_stmt), _ref(wp_stmt))
        pages.update(_stmt_pages([cnt_stmt, wp_stmt]))
    elif ac_canon is not None:
        size_kwp = ac_canon
        size_from = "pv_ac_kw %s" % _ref(ac_stmt)
        pages.update(_stmt_pages([ac_stmt]))
    if energy_kwh_yr is None or size_kwp is None or site is None \
            or not size_kwp > 0:
        return CheckResult("P3", "not checkable",
                           "pv energy %s, size %s, site range %s" % (
                               "missing" if energy_kwh_yr is None else "set",
                               "missing" if size_kwp is None else "set",
                               "missing" if site is None else "set"), ())
    low, high = float(site[0]), float(site[1])
    yield_kwh_kwp = energy_kwh_yr / size_kwp
    lo_bound = low * 0.65
    hi_bound = high * 0.90
    detail = "pv %s kWh/yr over %s kWp = %s kWh/kWp; site %s to %s allows %s to %s" % (
        _fmt_num(energy_kwh_yr), _fmt_num(size_kwp), _fmt_num(yield_kwh_kwp),
        _fmt_num(low), _fmt_num(high), _fmt_num(lo_bound), _fmt_num(hi_bound))
    detail = "yield from %s over %s; %s" % (energy_from, size_from, detail)
    if yield_kwh_kwp < lo_bound or yield_kwh_kwp > hi_bound:
        return CheckResult("P3", "flag", detail, tuple(sorted(pages)))
    return CheckResult("P3", "pass", detail, tuple(sorted(pages)))


def _p8(statements: list, site) -> CheckResult:
    """Resource input within range. Irradiation in kWh/m2/yr."""
    if site is None:
        return CheckResult("P8", "not checkable", "no site range", ())
    ghi = _known(_stmts_of(statements, "ghi_kwh_m2_yr"))
    if not ghi:
        return CheckResult("P8", "not checkable", "no GHI statement", ())
    low, high = float(site[0]), float(site[1])
    failing = ["%s below %s or above %s kWh/m2/yr"
               % (_ref(s), _fmt_num(low / 1.15), _fmt_num(high * 1.15))
               for s in ghi
               if _canon_of(s) < low / 1.15 or _canon_of(s) > high * 1.15]
    if failing:
        return CheckResult("P8", "flag", "; ".join(failing),
                           _stmt_pages(ghi))
    detail = "all %d GHI within %s to %s kWh/m2/yr: %s" % (
        len(ghi), _fmt_num(low / 1.15), _fmt_num(high * 1.15),
        ", ".join(_ref(s) for s in ghi))
    return CheckResult("P8", "pass", detail, _stmt_pages(ghi))


def _p4(statements: list, schedule) -> CheckResult:
    """Battery out not above in. Energy in kWh, efficiency in frac."""
    if schedule is None:
        return CheckResult("P4", "not checkable", "no schedule", ())
    charge_rows = [r for r in schedule["rows"]
                   if r["pv_to_battery_kw"] is not None]
    out_rows = [r for r in schedule["rows"]
                if r["battery_discharge_kw"] is not None]
    if not charge_rows or not out_rows:
        return CheckResult("P4", "not checkable",
                           "charge and discharge columns both needed", ())
    period_h = float(schedule["period_h"])
    charge_kwh = sum(float(r["pv_to_battery_kw"]) for r in charge_rows) * period_h
    out_kwh = sum(float(r["battery_discharge_kw"]) for r in out_rows) * period_h
    rte_canon, rte_stmt = _first_canon(_stmts_of(statements,
                                                "battery_rte_frac"))
    rte_frac = rte_canon if rte_canon is not None else 0.95
    pages = {schedule["page"]}
    if rte_stmt is not None and rte_canon is not None:
        pages.update(_stmt_pages([rte_stmt]))
    detail = "out %s kWh vs in %s kWh x %s = %s kWh" % (
        _fmt_num(out_kwh), _fmt_num(charge_kwh), _fmt_num(rte_frac),
        _fmt_num(charge_kwh * rte_frac))
    if out_kwh > charge_kwh * rte_frac:
        return CheckResult("P4", "flag", detail, tuple(sorted(pages)))
    return CheckResult("P4", "pass", detail, tuple(sorted(pages)))


def _p5(statements: list, schedule) -> CheckResult:
    """Power within rating. Power in kW, tolerance in frac."""
    specs = (("pv_ac_kw", "pv"), ("diesel_kw", "diesel"),
             ("battery_kw", "battery"))
    sched_page = schedule["page"] if schedule is not None else None
    rows = schedule["rows"] if schedule is not None else []
    failing = []
    shown = []
    pages = set()
    for qty, comp in specs:
        rated = _known(_stmts_of(statements, qty))
        if not rated:
            continue
        rating_kw = max(_canon_of(s) for s in rated)
        hours = []
        for row in rows:
            val_kw = None
            if comp == "pv":
                if row["pv_total_kw"] is not None:
                    val_kw = float(row["pv_total_kw"])
                elif row["pv_to_load_kw"] is not None \
                        or row["pv_to_battery_kw"] is not None \
                        or row["curtailed_kw"] is not None:
                    val_kw = (float(row["pv_to_load_kw"] or 0.0)
                              + float(row["pv_to_battery_kw"] or 0.0)
                              + float(row["curtailed_kw"] or 0.0))
            elif comp == "diesel":
                if row["diesel_kw"] is not None:
                    val_kw = float(row["diesel_kw"])
            else:
                if row["battery_discharge_kw"] is not None:
                    val_kw = float(row["battery_discharge_kw"])
            if val_kw is not None:
                hours.append((_ascii(row["time"]), val_kw))
        if not hours:
            continue
        pages.update(_stmt_pages(rated))
        if sched_page is not None:
            pages.add(sched_page)
        worst_time, worst_kw = max(hours, key=lambda h: h[1])
        shown.append("%s peak %s kW at %s vs rating %s kW" %
                     (qty, _fmt_num(worst_kw), worst_time,
                      _fmt_num(rating_kw)))
        if worst_kw > rating_kw * 1.01:
            failing.append("%s: worst hour %s %s kW above rating %s kW" %
                           (qty, worst_time, _fmt_num(worst_kw),
                            _fmt_num(rating_kw)))
    if failing:
        return CheckResult("P5", "flag", "; ".join(failing),
                           tuple(sorted(pages)))
    if shown:
        return CheckResult("P5", "pass", "; ".join(shown),
                           tuple(sorted(pages)))
    return CheckResult("P5", "not checkable",
                       "no component has both a rating and hourly numbers",
                       ())


def _p7(statements: list) -> CheckResult:
    """Area factor in range. Area in m2, count plain, ratio plain."""
    areas = _known(_stmts_of(statements, "pv_area_m2"))
    cnt_canon, cnt_stmt = _first_canon(_stmts_of(statements,
                                                "pv_module_count"))
    mod_canon, mod_stmt = _first_canon(_stmts_of(statements,
                                                "pv_module_area_m2"))
    if not areas or cnt_canon is None or mod_canon is None \
            or not cnt_canon * mod_canon > 0:
        return CheckResult("P7", "not checkable",
                           "area, module count and module area all needed",
                           ())
    denom_m2 = cnt_canon * mod_canon
    failing = []
    ratios = []
    for stmt in areas:
        ratio = _canon_of(stmt) / denom_m2
        ratios.append("%s ratio %s" % (_ref(stmt), _fmt_num(ratio)))
        if ratio < 1.0 or ratio > 3.0:
            failing.append("%s ratio %s outside 1 to 3" % (_ref(stmt),
                                                          _fmt_num(ratio)))
    pages = _stmt_pages(areas + [cnt_stmt, mod_stmt])
    if failing:
        return CheckResult("P7", "flag", "; ".join(failing), pages)
    return CheckResult("P7", "pass", "; ".join(ratios), pages)


def _p9(statements: list) -> CheckResult:
    """Costs add up. Money in USD, tolerance in frac."""
    failing = []
    agreed = []
    pages = set()
    for total_qty in ("npc_usd", "capex_usd", "annual_cost_usd"):
        items = [s for s in _known(_stmts_of(statements, "cost_item_usd"))
                 if s["condition"] == total_qty]
        totals = _known(_stmts_of(statements, total_qty))
        if not items or not totals:
            continue
        sum_usd = sum(_canon_of(s) for s in items)
        for stmt in totals:
            pages.update(_stmt_pages(items + [stmt]))
            stated_usd = _canon_of(stmt)
            line = "%s items sum %s USD vs stated %s" % (
                total_qty, _fmt_num(sum_usd), _ref(stmt))
            if abs(sum_usd - stated_usd) > 0.01 * abs(stated_usd):
                failing.append(line)
            else:
                agreed.append(line)
    if failing:
        return CheckResult("P9", "flag", "; ".join(failing),
                           tuple(sorted(pages)))
    if agreed:
        return CheckResult("P9", "pass",
                           "; ".join(agreed) + " agree within 1%",
                           tuple(sorted(pages)))
    return CheckResult("P9", "not checkable",
                       "no total has both items and statements", ())


def _p10(statements: list) -> CheckResult:
    """Cost of energy recomputes. Money in USD, energy in kWh, time in yr."""
    npc_canon, npc_stmt = _first_canon(_stmts_of(statements, "npc_usd"))
    rate_canon, rate_stmt = _first_canon(_stmts_of(statements,
                                                  "discount_rate_frac"))
    life_canon, life_stmt = _first_canon(_stmts_of(statements,
                                                  "project_life_yr"))
    energy_kwh_yr = None
    for qty in ("energy_served_kwh_yr", "load_kwh_yr"):
        energy_kwh_yr, _ = _first_canon(_stmts_of(statements, qty))
        if energy_kwh_yr is not None:
            break
    lcoes = _known(_stmts_of(statements, "lcoe_usd_per_kwh"))
    if npc_canon is None or rate_canon is None or life_canon is None \
            or energy_kwh_yr is None or not lcoes or rate_canon == 0:
        return CheckResult("P10", "not checkable",
                           "npc, discount rate, life, energy and LCOE needed",
                           ())
    rate_frac = rate_canon
    life_yr = life_canon
    growth = (1.0 + rate_frac) ** life_yr
    crf = rate_frac * growth / (growth - 1.0)
    calc_usd_per_kwh = npc_canon * crf / energy_kwh_yr
    failing = ["%s vs recomputed %s USD/kWh"
               % (_ref(s), _fmt_num(calc_usd_per_kwh)) for s in lcoes
               if abs(_canon_of(s) - calc_usd_per_kwh)
               > 0.05 * abs(calc_usd_per_kwh)]
    pages = _stmt_pages([npc_stmt, rate_stmt, life_stmt] + lcoes)
    if failing:
        return CheckResult("P10", "flag", "; ".join(failing), pages)
    detail = "LCOE recomputes to %s USD/kWh within 5%%: %s" % (
        _fmt_num(calc_usd_per_kwh), ", ".join(_ref(s) for s in lcoes))
    return CheckResult("P10", "pass", detail, pages)


def _p11(statements: list) -> CheckResult:
    """Economics reproducible. No units computed, presence only."""
    required = ["discount_rate_frac", "project_life_yr", "om_cost_usd"]
    if _stmts_of(statements, "pv_ac_kw") or _stmts_of(statements, "pv_dc_kwp"):
        required.append("pv_capex_usd_per_kw")
    if _stmts_of(statements, "battery_size"):
        required.append("battery_capex_usd_per_kwh")
    if _stmts_of(statements, "diesel_kw"):
        required += ["diesel_capex_usd_per_kw", "fuel_price_usd_per_l"]
    missing = [q for q in required if not _stmts_of(statements, q)]
    present = [s for s in statements if s["quantity"] in required]
    if missing:
        return CheckResult("P11", "flag",
                           "not reproducible: missing " + ", ".join(missing),
                           _stmt_pages(present))
    return CheckResult("P11", "pass",
                       "all needed economics inputs stated: "
                       + ", ".join(required), _stmt_pages(present))


def _p12(statements: list) -> CheckResult:
    """Fuel use per diesel kWh. Volume in L, energy in kWh."""
    fuel_canon, fuel_stmt = _first_canon(_stmts_of(statements, "fuel_l_yr"))
    diesel_canon, _ = _first_canon(_stmts_of(statements, "diesel_kwh_yr"))
    if fuel_canon is None or diesel_canon is None or diesel_canon == 0:
        return CheckResult("P12", "not checkable",
                           "fuel litres and diesel kWh both needed", ())
    ratio_l_kwh = fuel_canon / diesel_canon
    detail = "fuel %s L over diesel %s kWh = %s L/kWh" % (
        _fmt_num(fuel_canon), _fmt_num(diesel_canon), _fmt_num(ratio_l_kwh))
    pages = _stmt_pages([s for s in (fuel_stmt,) if s is not None]
                        + _stmts_of(statements, "diesel_kwh_yr")[:1])
    if ratio_l_kwh < 0.20 or ratio_l_kwh > 0.45:
        return CheckResult("P12", "flag", detail, pages)
    return CheckResult("P12", "pass", detail, pages)


def _p13(statements: list) -> CheckResult:
    """Renewable share matches. Energy in kWh, share in frac."""
    diesel_canon, _ = _first_canon(_stmts_of(statements, "diesel_kwh_yr"))
    served_kwh_yr = None
    for qty in ("energy_served_kwh_yr", "load_kwh_yr"):
        served_kwh_yr, _ = _first_canon(_stmts_of(statements, qty))
        if served_kwh_yr is not None:
            break
    shares = _known(_stmts_of(statements, "renewable_fraction_frac"))
    if diesel_canon is None or served_kwh_yr is None \
            or served_kwh_yr == 0 or not shares:
        return CheckResult("P13", "not checkable",
                           "diesel kWh, served kWh and a share all needed",
                           ())
    computed_frac = 1.0 - diesel_canon / served_kwh_yr
    failing = ["%s vs computed %s" % (_ref(s), _fmt_num(computed_frac))
               for s in shares
               if abs(_canon_of(s) - computed_frac) > 0.02]
    pages = _stmt_pages(shares + _stmts_of(statements, "diesel_kwh_yr")[:1])
    if failing:
        return CheckResult("P13", "flag", "; ".join(failing), pages)
    return CheckResult("P13", "pass",
                       "shares agree with computed %s within 0.02: %s" % (
                           _fmt_num(computed_frac),
                           ", ".join(_ref(s) for s in shares)), pages)


def _p14(statements: list) -> CheckResult:
    """CO2 per litre of fuel. Mass in kg, volume in L."""
    co2_canon, co2_stmt = _first_canon(_stmts_of(statements, "co2_kg_yr"))
    fuel_canon, fuel_stmt = _first_canon(_stmts_of(statements, "fuel_l_yr"))
    if co2_canon is None or fuel_canon is None or fuel_canon == 0:
        return CheckResult("P14", "not checkable",
                           "CO2 kg and fuel litres both needed", ())
    ratio_kg_l = co2_canon / fuel_canon
    detail = "CO2 %s kg over fuel %s L = %s kg/L" % (
        _fmt_num(co2_canon), _fmt_num(fuel_canon), _fmt_num(ratio_kg_l))
    pages = _stmt_pages([s for s in (co2_stmt, fuel_stmt) if s is not None])
    if ratio_kg_l < 2.5 or ratio_kg_l > 2.8:
        return CheckResult("P14", "flag", detail, pages)
    return CheckResult("P14", "pass", detail, pages)


def run_checks(verified: dict, *, site_ghi_kwh_m2_yr=None) -> list:
    """Run P1 to P15 on verified extraction. Site range in kWh/m2/yr."""
    statements = verified["statements"]
    schedule = verified.get("schedule")
    p1_quantities = tuple(q for q in QUANTITIES if q not in SIZE_QUANTITIES
                          and q != "cost_item_usd")
    return [
        _p1_p6("P1", p1_quantities, statements),
        _p2(schedule),
        _p3(statements, schedule, site_ghi_kwh_m2_yr),
        _p4(statements, schedule),
        _p5(statements, schedule),
        _p1_p6("P6", SIZE_QUANTITIES, statements),
        _p7(statements),
        _p8(statements, site_ghi_kwh_m2_yr),
        _p9(statements),
        _p10(statements),
        _p11(statements),
        _p12(statements),
        _p13(statements),
        _p14(statements),
        _p15(statements, schedule),
    ]


def summary(results: list) -> dict:
    """Count check outcomes. Output flags, passes, not checkable, ids."""
    flags = sum(1 for r in results if r.status == "flag")
    passes = sum(1 for r in results if r.status == "pass")
    missing = sum(1 for r in results if r.status == "not checkable")
    return {"flags": flags, "passes": passes, "not_checkable": missing,
            "flagged_ids": [r.check_id for r in results
                            if r.status == "flag"]}
