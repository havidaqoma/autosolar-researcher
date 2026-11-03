"""Static HTML study pages with inline SVG charts. No server, no network."""

from __future__ import annotations

import html
import math
import numbers
import re

import pandas as pd

from autosolar import sweep
from autosolar.curate import curated_line
from autosolar.resources import RESOURCE_SCHEMA

FUEL_PRICE_STEPS_USD_PER_L = tuple(round(0.2 + 0.1 * k, 2) for k in range(15))
MAX_PRICE_STEPS = 24
FUEL_PRICE_CSS = (
    ".fp input{position:absolute;opacity:0;width:1px;height:1px}"
    ".fp-labels label{display:inline-block;padding:4px 8px;margin:2px;"
    "border:1px solid #999;border-radius:4px;cursor:pointer}"
    ".fp-out{display:none;margin:8px 0}"
    + "".join(
        "#fp%d:checked~.fp-outs #fpo%d{display:block}" % (i, i)
        + "#fp%d:checked~.fp-labels label[for=fp%d]{background:#1f5f99;color:#fff}" % (i, i)
        for i in range(MAX_PRICE_STEPS)
    )
)

SITE_CSS = (
    "body{font-family:Arial,Helvetica,sans-serif;background:#eef0ea;color:#222;"
    "margin:0;padding:0 12px;line-height:1.45}"
    "main{max-width:1000px;margin:0 auto;background:#fff;padding:24px;"
    "border:1px solid #d8d8d8}"
    "header.main-head{max-width:1000px;margin:0 auto;padding:16px 24px}"
    "h1{font-size:1.6em;margin:0.2em 0}h2{font-size:1.25em;margin:1.2em 0 0.4em}"
    "h3{font-size:1em;margin:0.4em 0}"
    ".headline{font-size:1.15em;font-weight:bold}"
    ".cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));"
    "gap:12px;margin:0.6em 0}"
    ".card{border:1px solid #cfcfcf;background:#fbfbf7;padding:8px 12px;margin:0}"
    ".scroll{overflow-x:auto;max-width:100%}"
    "table{border-collapse:collapse;margin:8px 0;max-width:100%}"
    "th,td{border:1px solid #bbb;padding:4px 8px;text-align:left;font-size:0.92em}"
    "th{background:#f0f2ec}tr.flag{background:#fdf0ef}"
    "footer.page-foot{max-width:1000px;margin:0 auto;padding:12px 24px;color:#555}"
    "a{color:#1a4f9c}svg text{font-family:Arial,Helvetica,sans-serif}"
    "svg{max-width:100%}"
)

CARD_TITLES = (
    ("best_pv_kwp", "PV size"),
    ("best_battery_kwh", "Battery"),
    ("best_lcoe_usd_per_kwh", "Cost of electricity"),
    ("diesel_only_lcoe_usd_per_kwh", "Diesel only"),
    ("best_renewable_pct", "Renewable share"),
    ("fuel_saved_l_yr", "Diesel saved"),
    ("co2_saved_t_yr", "CO2 saved"),
    ("break_even_fuel_usd_per_l", "Diesel price where PV starts to pay"),
)

SENSITIVITY_LABELS = {
    "pv_capex_usd_per_kwp": "PV price",
    "battery_capex_usd_per_kwh": "Battery price",
    "fuel_price_usd_per_l": "Diesel price",
    "discount_rate_frac": "Discount rate",
    "demand": "Demand",
    "diesel_om_usd_per_kwh": "Diesel O&M",
    "fuel_intercept_l_per_h_per_kw_rated": "Diesel idle fuel",
    "fuel_slope_l_per_kwh": "Diesel fuel per kWh",
    "battery_duration_h": "Battery hours",
}

DESIGN_CHANGE_MIN_FRAC = 0.01
DESIGN_CHANGE_TOL = 1e-9

FIELD_ASKS = {
    "pv_capex_usd_per_kwp": "Installed PV prices from recent island tenders, shipping included",
    "battery_capex_usd_per_kwh": "Installed battery prices from recent tenders, shipping included",
    "fuel_price_usd_per_l": "Diesel price delivered to the island, with tax and shipping",
    "discount_rate_frac": "The real discount rate the owner or lender uses",
    "demand": "Metered hourly load for a full year, or at least monthly kWh sent out",
    "diesel_om_usd_per_kwh": "Diesel plant O&M cost records",
    "fuel_intercept_l_per_h_per_kw_rated": "Litres and kWh from the plant logs, by hour or by day",
    "fuel_slope_l_per_kwh": "Litres and kWh from the plant logs, by hour or by day",
    "battery_duration_h": "Battery power rating offered for this energy size",
}
FIELD_ASK_DEFAULT = "Field records for this input"
FIELD_NOTE_KEYS = ("site", "key", "item", "value", "decimals", "unit", "label", "date", "source", "url",
                   "quote", "compare", "note")
FIELD_COMPARES = ("energy_kwh_per_day", "fuel_l_per_kwh", "peak_kw", "fuel_l_per_day")
_FIELD_NOTE_LABELS = ("press", "docs", "paper", "measured")

_URL_RE = re.compile(r"https?://[^ ,]+")


def esc(text: object) -> str:
    """Escape text for HTML. Non-ASCII becomes a decimal ref. Returns str."""
    out = html.escape(str(text), quote=True)
    return "".join(c if ord(c) < 128 else "&#%d;" % ord(c) for c in out)


def fmt(value: float, decimals: int) -> str:
    """Format a number with commas. decimals picks places. Returns str."""
    return format(float(value), ",.%df" % int(decimals))


def headline(report: dict) -> str:
    """One line verdict for a study report. Plain text, units in USD/kWh."""
    facts = report["facts"]
    best = facts["best_lcoe_usd_per_kwh"]
    dsl = facts["diesel_only_lcoe_usd_per_kwh"]
    site = str(report["site"]["name"])
    if best["value"] < dsl["value"]:
        return (
            "Yes. Solar plus battery cuts the cost of electricity on "
            + site
            + " from "
            + str(dsl["text"])
            + " to "
            + str(best["text"])
            + " USD/kWh ("
            + str(facts["lcoe_change_pct"]["text"])
            + "%)."
        )
    return (
        "No. On "
        + site
        + " the least cost design costs "
        + str(best["text"])
        + " USD/kWh against "
        + str(dsl["text"])
        + " USD/kWh for diesel only."
    )


def caveats(report: dict) -> list[str]:
    """Five to eight plain lines from firmness items. Empty when no firmness."""
    firm = report.get("firmness")
    if firm is None:
        return []
    by_key = {it["key"]: it for it in firm.get("items", [])}

    def it(key: str) -> dict:
        if key not in by_key:
            raise ValueError("firmness item missing: " + key)
        return by_key[key]

    first = (
        "Near tie: " + str(it("near_tie_count")["text"]) + " designs are within "
        + str(it("near_tie_pct")["text"]) + "% of the least cost, from "
        + str(it("near_tie_pv_kwp_min")["text"]) + " to "
        + str(it("near_tie_pv_kwp_max")["text"]) + " kWp of PV."
    )
    second = (
        "Reserve case: if " + str(it("reserve_units")["text"])
        + " diesel unit(s) must run in every hour, the least cost design is "
        + str(it("reserve_pv_kwp")["text"]) + " kWp with "
        + str(it("reserve_battery_kwh")["text"]) + " kWh at "
        + str(it("reserve_lcoe_usd_per_kwh")["text"])
        + " USD/kWh, and the main design would cost "
        + str(it("reserve_main_design_lcoe_usd_per_kwh")["text"]) + " USD/kWh."
    )
    if "alt_diesel_unit_kw" in by_key:
        head = (
            "Diesel unit size: with units of " + str(it("alt_diesel_unit_kw")["text"])
            + " kW instead, diesel only costs " + str(it("alt_diesel_only_lcoe_usd_per_kwh")["text"])
            + " USD/kWh"
        )
        if it("alt_lcoe_usd_per_kwh")["value"] is None:
            alt_line = head + " and no design in the grid meets the unserved limit."
        else:
            alt_line = (
                head
                + " and the least cost design is " + str(it("alt_pv_kwp")["text"])
                + " kWp with " + str(it("alt_battery_kwh")["text"])
                + " kWh at " + str(it("alt_lcoe_usd_per_kwh")["text"])
                + " USD/kWh (" + str(it("alt_saving_pct")["text"])
                + "% below diesel only); if " + str(it("reserve_units")["text"])
                + " diesel unit(s) must run in every hour, that design would cost "
                + str(it("alt_reserve_main_design_lcoe_usd_per_kwh")["text"]) + " USD/kWh"
            )
            if it("alt_reserve_lcoe_usd_per_kwh")["value"] is None:
                alt_line = alt_line + " and no design in the grid meets the unserved limit."
            else:
                alt_line = (
                    alt_line
                    + " and the least cost design is " + str(it("alt_reserve_pv_kwp")["text"])
                    + " kWp with " + str(it("alt_reserve_battery_kwh")["text"])
                    + " kWh at " + str(it("alt_reserve_lcoe_usd_per_kwh")["text"]) + " USD/kWh."
                )
    third = (
        "Land: the main design needs " + str(it("land_need_ha")["text"])
        + " ha of the " + str(it("land_site_ha")["text"]) + " ha set aside (fits: "
        + str(it("land_fits")["text"]) + ")."
    )
    fourth = (
        "Published design size: " + str(it("reference_pv_kwp")["text"])
        + " kWp of PV with no battery gives "
        + str(it("reference_lcoe_usd_per_kwh")["text"]) + " USD/kWh."
    )
    fifth = (
        "Cost: this study used " + str(it("total_cost_usd")["text"])
        + " USD of model API calls, of which "
        + str(it("sourcing_cost_usd")["text"])
        + " USD was the web search that sourced its inputs."
    )
    out = [first, second]
    if "alt_diesel_unit_kw" in by_key:
        out.append(alt_line)
    if "capex_break_even_rise_pct" in by_key:
        rise = it("capex_break_even_rise_pct")
        pv_at = it("capex_break_even_pv_usd_per_kwp")
        bat_at = it("capex_break_even_battery_usd_per_kwh")
        prices = (" (PV to " + str(pv_at["text"]) + " USD/kWp, battery to "
                 + str(bat_at["text"]) + " USD/kWh)")
        if rise["value"] is None:
            island = ("Island prices: no design in the grid beats diesel only "
                      "at any PV and battery capital price above zero.")
        elif float(rise["value"]) >= 0.0:
            island = ("Island prices: PV and battery capital prices can rise "
                      + str(rise["text"]) + "%" + prices + " before diesel only is cheaper.")
        else:
            fall = str(rise["text"])
            if fall.startswith("-"):
                fall = fall[1:]
            island = ("Island prices: diesel only is cheaper now; PV and battery capital "
                      "prices must fall " + fall + "%" + prices + " before a design with PV beats it.")
        cut = it("engine_hours_cut_pct")
        best_h = it("engine_hours_best")
        d0_h = it("engine_hours_diesel_only")
        if cut["value"] is not None and float(cut["value"]) > 0.0:
            engine = ("Diesel engine hours: the least cost design cuts engine hours by "
                      + str(cut["text"]) + "% (" + str(best_h["text"]) + " against "
                      + str(d0_h["text"]) + " unit hours a year), so overhaul and engine "
                      "replacement costs, left out here, would favour it.")
        else:
            engine = ("Diesel engine hours: the least cost design runs " + str(best_h["text"])
                      + " unit hours a year against " + str(d0_h["text"])
                      + " for diesel only; overhaul and engine replacement costs are left out.")
        out += [island, engine]
    return out + [third, fourth, fifth]


def _mix_hex(light: tuple, dark: tuple, pos: float) -> str:
    """Blend two RGB colours. pos 0 is light, 1 is dark. Returns hex."""
    if pos < 0.0:
        pos = 0.0
    if pos > 1.0:
        pos = 1.0
    red = int(round(light[0] + (dark[0] - light[0]) * pos))
    green = int(round(light[1] + (dark[1] - light[1]) * pos))
    blue = int(round(light[2] + (dark[2] - light[2]) * pos))
    return "#%02x%02x%02x" % (red, green, blue)


def heatmap_svg(
    table: pd.DataFrame, best_pv_kwp: float, best_battery_kwh: float, unserved_max_frac: float
) -> str:
    """LCOE heatmap over PV kWp and battery kWh. Returns one svg str."""
    pv_vals = sorted({float(v) for v in table["pv_kwp"]})
    bat_vals = sorted({float(v) for v in table["battery_kwh"]})
    if not pv_vals or not bat_vals:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"></svg>'
    feas_lcoes = [
        float(r["lcoe_usd_per_kwh"]) for _, r in table.iterrows() if float(r["unserved_frac"]) <= float(unserved_max_frac)
    ]
    if feas_lcoes:
        top_lcoe = max(feas_lcoes)
        low_lcoe = min(feas_lcoes)
    else:
        top_lcoe = low_lcoe = 0.0
    light = (238, 245, 238)
    dark = (24, 92, 40)
    grey = "#c9c9c9"
    plot_w = 440.0
    plot_h = 300.0
    left = 110.0
    top = 16.0
    right = 16.0
    bottom = 64.0
    limit_frac = float(unserved_max_frac)
    has_infeasible = any(float(r["unserved_frac"]) > limit_frac for _, r in table.iterrows())
    legend_rows = 3 if has_infeasible else 2
    legend_top = top + plot_h + bottom + 8.0
    nx = len(pv_vals)
    ny = len(bat_vals)
    cell_w = plot_w / nx
    cell_h = plot_h / ny
    width = left + plot_w + right
    height = legend_top + legend_rows * 18.0 + 12.0
    pv_pos = {v: i for i, v in enumerate(pv_vals)}
    bat_pos = {v: i for i, v in enumerate(bat_vals)}
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" role="img">' % (int(width), int(height))
    ]
    for _, row in table.iterrows():
        pv = float(row["pv_kwp"])
        bat = float(row["battery_kwh"])
        lcoe = float(row["lcoe_usd_per_kwh"])
        unf = float(row["unserved_frac"])
        col = pv_pos[pv]
        rix = bat_pos[bat]
        x = left + col * cell_w
        y = top + (ny - 1 - rix) * cell_h
        title = "PV %s kWp, battery %s kWh: %s USD/kWh" % (fmt(pv, 0), fmt(bat, 0), fmt(lcoe, 3))
        if pv == float(best_pv_kwp) and bat == float(best_battery_kwh):
            if top_lcoe == low_lcoe:
                fill = _mix_hex(light, dark, 0.5)
            else:
                fill = _mix_hex(light, dark, (top_lcoe - lcoe) / (top_lcoe - low_lcoe))
            parts.append(
                '<rect class="cell best" x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                'fill="%s" stroke="#000000" stroke-width="3">'
                "<title>%s</title></rect>" % (x, y, cell_w, cell_h, fill, title)
            )
        elif unf > float(unserved_max_frac):
            parts.append(
                '<rect class="cell infeasible" x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                'fill="%s" stroke="#ffffff" stroke-width="1">'
                "<title>%s</title></rect>" % (x, y, cell_w, cell_h, grey, title)
            )
        else:
            if top_lcoe == low_lcoe:
                fill = _mix_hex(light, dark, 0.5)
            else:
                fill = _mix_hex(light, dark, (top_lcoe - lcoe) / (top_lcoe - low_lcoe))
            parts.append(
                '<rect class="cell" x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                'fill="%s" stroke="#ffffff" stroke-width="1">'
                "<title>%s</title></rect>" % (x, y, cell_w, cell_h, fill, title)
            )
    x_ticks = sorted({0, (nx - 1) // 2, nx - 1})
    for i in x_ticks:
        cx = left + (i + 0.5) * cell_w
        parts.append(
            '<text x="%.1f" y="%.1f" font-size="11" text-anchor="middle">%s</text>'
            % (cx, top + plot_h + 22, fmt(pv_vals[i], 0))
        )
    y_ticks = sorted({0, (ny - 1) // 2, ny - 1})
    for i in y_ticks:
        cy = top + (ny - 1 - i + 0.5) * cell_h + 4
        parts.append(
            '<text x="%.1f" y="%.1f" font-size="11" text-anchor="end">%s</text>'
            % (left - 8, cy, fmt(bat_vals[i], 0))
        )
    parts.append(
        '<text x="%.1f" y="%.1f" font-size="12" text-anchor="middle">PV kWp</text>'
        % (left + plot_w / 2, top + plot_h + 44)
    )
    mid_y = top + plot_h / 2
    parts.append(
        '<text x="%.1f" y="%.1f" transform="rotate(-90 %.1f %.1f)" '
        'font-size="12" text-anchor="middle">Battery kWh</text>' % (14.0, mid_y, 14.0, mid_y)
    )
    if top_lcoe == low_lcoe:
        fill_lo = _mix_hex(light, dark, 0.5)
        fill_hi = fill_lo
    else:
        fill_lo = _mix_hex(light, dark, (top_lcoe - low_lcoe) / (top_lcoe - low_lcoe))
        fill_hi = _mix_hex(light, dark, (top_lcoe - top_lcoe) / (top_lcoe - low_lcoe))
    parts.append('<g class="legend">')
    parts.append(
        '<rect x="%.1f" y="%.1f" width="14" height="14" fill="%s" stroke="#ffffff" stroke-width="1"></rect>'
        % (left, legend_top - 12.0, fill_lo)
    )
    parts.append(
        '<text x="%.1f" y="%.1f" font-size="11">lowest %s USD/kWh</text>'
        % (left + 20.0, legend_top, fmt(low_lcoe, 3))
    )
    parts.append(
        '<rect x="%.1f" y="%.1f" width="14" height="14" fill="%s" stroke="#ffffff" stroke-width="1"></rect>'
        % (left, legend_top + 18.0 - 12.0, fill_hi)
    )
    parts.append(
        '<text x="%.1f" y="%.1f" font-size="11">highest %s USD/kWh</text>'
        % (left + 20.0, legend_top + 18.0, fmt(top_lcoe, 3))
    )
    if has_infeasible:
        parts.append(
            '<text x="%.1f" y="%.1f" font-size="11">grey: unserved energy above the limit</text>'
            % (left, legend_top + 36.0)
        )
    parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def tornado_svg(rows: list[dict], base_lcoe: float) -> str:
    """Sensitivity bars sorted widest first. LCOE in USD per kWh. Returns svg."""
    order: list[str] = []
    groups: dict[str, list[dict]] = {}
    for row in rows:
        key = str(row["input"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)
    bars: list[tuple] = []
    for key in order:
        pack = groups[key]
        if len(pack) < 2:
            continue
        low_row = min(pack, key=lambda r: float(r["factor"]))
        high_row = max(pack, key=lambda r: float(r["factor"]))
        low_v = float(low_row["base_design_lcoe_usd_per_kwh"])
        high_v = float(high_row["base_design_lcoe_usd_per_kwh"])
        low = min(low_v, high_v)
        high = max(low_v, high_v)
        bars.append((key, low, high, high - low, order.index(key)))
    bars.sort(key=lambda b: (-b[3], b[4]))
    width = 720.0
    left = 8.0
    bar_x0 = 340.0
    bar_x1 = 700.0
    top = 16.0
    step = 34.0
    height = top + max(len(bars), 1) * step + 24.0
    vals = [base_lcoe] + [b[1] for b in bars] + [b[2] for b in bars]
    gmin = min(float(v) for v in vals)
    gmax = max(float(v) for v in vals)
    pad = (gmax - gmin) * 0.08
    if pad == 0.0:
        pad = 1e-9
    span_lo = gmin - pad
    span_hi = gmax + pad

    def pos(v: float) -> float:
        return bar_x0 + (float(v) - span_lo) / (span_hi - span_lo) * (bar_x1 - bar_x0)

    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" role="img">' % (int(width), int(height))]
    for i, (key, low, high, _w, _o) in enumerate(bars):
        y = top + i * step
        x = pos(low)
        w = max(pos(high) - pos(low), 1.0)
        label = "%s: %s to %s USD/kWh" % (SENSITIVITY_LABELS.get(key, key), fmt(low, 3), fmt(high, 3))
        parts.append('<g class="bar">')
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="16" fill="#2f6fb2"></rect>' % (x, y, w)
        )
        parts.append('<text x="%.1f" y="%.1f" font-size="11">%s</text>' % (left, y + 13, esc(label)))
        parts.append("</g>")
    bx = pos(base_lcoe)
    parts.append(
        '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#000000" stroke-width="2"></line>'
        % (bx, top - 6, bx, top + len(bars) * step)
    )
    parts.append(
        '<text x="%.1f" y="%.1f" font-size="11">Base %s USD/kWh</text>' % (bx + 4, top - 8, fmt(base_lcoe, 3))
    )
    parts.append("</svg>")
    return "".join(parts)


def weather_svg(rows: list[dict]) -> str:
    """Bars proportional to yearly GHI. GHI in kWh per m2 and yr. Returns svg."""
    width = 560.0
    bar_x0 = 220.0
    bar_full = 320.0
    top = 16.0
    step = 34.0
    height = top + max(len(rows), 1) * step + 16.0
    top_ghi = max([float(r["ghi_kwh_m2_yr"]) for r in rows] + [0.0])
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" role="img">' % (int(width), int(height))]
    for i, row in enumerate(rows):
        ghi = float(row["ghi_kwh_m2_yr"])
        w = ghi / top_ghi * bar_full if top_ghi > 0 else 0.0
        y = top + i * step
        label = "%s: %s kWh/m2/yr" % (str(row["case"]), fmt(ghi, 0))
        parts.append('<g class="bar">')
        parts.append(
            '<rect x="%.1f" y="%.1f" width="%.2f" height="16" fill="#d98a1f"></rect>' % (bar_x0, y, w)
        )
        parts.append('<text x="8" y="%.1f" font-size="11">%s</text>' % (y + 13, esc(label)))
        parts.append("</g>")
    parts.append("</svg>")
    return "".join(parts)


def _table(headers: list[str], rows: list[list[str]]) -> str:
    """One HTML table from header and cell strings. Returns str."""
    parts = ['<div class="scroll"><table><thead><tr>']
    for head in headers:
        parts.append("<th>" + esc(head) + "</th>")
    parts.append("</tr></thead><tbody>")
    for cells in rows:
        parts.append("<tr>")
        for cell in cells:
            parts.append("<td>" + esc(cell) + "</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _linkify(line: str) -> str:
    """Escape a source line and wrap http(s) URLs in links. Returns str."""
    parts: list[str] = []
    pos = 0
    for hit in _URL_RE.finditer(line):
        url = hit.group(0)
        parts.append(esc(line[pos : hit.start()]))
        parts.append('<a href="' + esc(url) + '">' + esc(url) + "</a>")
        pos = hit.end()
    parts.append(esc(line[pos:]))
    return "".join(parts)


def _unserved_max_frac(report: dict) -> float:
    """Read the unserved limit from the inputs table. Fraction, returns float."""
    for row in report.get("inputs_table", []):
        if row.get("name") == "unserved_max_frac":
            if row.get("value") is not None:
                return float(row["value"])
            cells = row.get("cells", [])
            if len(cells) > 1:
                return float(str(cells[1]).replace(",", ""))
    raise ValueError("inputs_table holds no unserved_max_frac row")


def figure_check_svg(result: dict) -> str:
    """Line chart of the read curves and the scaled table. Loads in kWh. Returns svg."""
    reading = result.get("reading")
    comparison = result.get("comparison")
    if not isinstance(reading, dict) or not isinstance(comparison, dict):
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"></svg>'
    values = reading.get("values", {})
    scaled_kw = comparison.get("table_at_figure_year_kw", [])
    if not isinstance(values, dict) or len(values) == 0:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"></svg>'
    names = list(values)
    palette = ["#1f6fb2", "#7a3fa0", "#c0392b", "#0f7a3d", "#b26a00", "#555555"]
    width_px = 720.0
    height_px = 360.0
    left_px = 64.0
    right_px = 16.0
    top_px = 16.0
    bottom_px = 48.0
    plot_w_px = width_px - left_px - right_px
    plot_h_px = height_px - top_px - bottom_px
    nums_kwh: list[float] = []
    for name in names:
        for item in values[name]:
            if item is not None:
                nums_kwh.append(float(item))
    for item in scaled_kw:
        if item is not None:
            nums_kwh.append(float(item))
    if not nums_kwh:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="60"></svg>'
    top_kwh = max(nums_kwh)
    low_kwh = min(nums_kwh)
    if top_kwh == low_kwh:
        top_kwh = low_kwh + 1.0

    def x_px(hour: int) -> float:
        return left_px + float(hour) / 23.0 * plot_w_px

    def y_px(value_kwh: float) -> float:
        return top_px + (top_kwh - float(value_kwh)) / (top_kwh - low_kwh) * plot_h_px

    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" role="img">'
             % (int(width_px), int(height_px))]
    parts.append('<text x="%.1f" y="%.1f" font-size="12" text-anchor="middle">Hour</text>'
                 % (left_px + plot_w_px / 2, height_px - 8.0))
    parts.append('<text x="%.1f" y="%.1f" font-size="12" text-anchor="middle">kWh</text>'
                 % (16.0, top_px + 8.0))
    for pos, name in enumerate(names):
        color = palette[pos % len(palette)]
        pts = ["%.1f,%.1f" % (x_px(h), y_px(float(values[name][h])))
               for h in range(24) if values[name][h] is not None]
        if not pts:
            continue
        parts.append('<polyline points="' + " ".join(pts) + '" fill="none" stroke="' + color
                     + '" stroke-width="2"><title>' + esc(name) + "</title></polyline>")
    table_pts = ["%.1f,%.1f" % (x_px(h), y_px(float(scaled_kw[h]))) for h in range(24)
                 if h < len(scaled_kw) and scaled_kw[h] is not None]
    if table_pts:
        parts.append('<polyline points="' + " ".join(table_pts) + '" fill="none" stroke="#333333"'
                     + ' stroke-width="2" stroke-dasharray="6,3"><title>Study load, scaled back</title>'
                     + "</polyline>")
    legend_y = top_px + 4.0
    for pos, name in enumerate(names):
        color = palette[pos % len(palette)]
        parts.append('<rect x="%.1f" y="%.1f" width="14" height="10" fill="%s"></rect>'
                     % (left_px + 8.0, legend_y - 10.0, color))
        parts.append('<text x="%.1f" y="%.1f" font-size="11">%s</text>'
                     % (left_px + 26.0, legend_y, esc(name)))
        legend_y += 16.0
    parts.append('<rect x="%.1f" y="%.1f" width="14" height="10" fill="#333333"></rect>'
                 % (left_px + 8.0, legend_y - 10.0))
    parts.append('<text x="%.1f" y="%.1f" font-size="11">Study load, scaled back</text>'
                 % (left_px + 26.0, legend_y))
    parts.append("</svg>")
    return "".join(parts)


def _load_followup_html(doc: dict) -> str:
    """Post hoc follow-up block for the figure check section. Returns str."""
    basis_series = str(doc["basis_series"])
    designs = fmt(float(doc["designs"]), 0)
    parts = ["<h3>If the chart is right</h3>"]
    parts.append(
        "<p>"
        + esc(
            "Added after the load check result (post hoc), so the answer above is unchanged. The engine re-ran all "
            + designs
            + " designs at each load below (computed). Before that, it gave back this study's own answer and "
            "the two demand rows of What moves the cost, to within one part in a billion."
        )
        + "</p>"
    )
    chart = None
    for case in doc["cases"]:
        if case.get("key") == "chart_basis":
            chart = case
            break
    if chart is None:
        chart = doc["cases"][0]
    scale_frac = float(chart["scale_frac"])
    if scale_frac > 1.0:
        direction = "higher"
        pct = fmt(100.0 * (scale_frac - 1.0), 1)
    else:
        direction = "lower"
        pct = fmt(100.0 * (1.0 - scale_frac), 1)
    d0 = fmt(float(chart["diesel_only_lcoe_usd_per_kwh"]), 3)
    saving = chart.get("saving_pct")
    if saving is not None and float(saving) > 0.0:
        pv = fmt(float(chart["best_pv_kwp"]), 0)
        bat = fmt(float(chart["best_battery_kwh"]), 0)
        best = fmt(float(chart["best_lcoe_usd_per_kwh"]), 3)
        save = fmt(float(saving), 1)
        parts.append(
            "<p>"
            + esc(
                "If the load is what the "
                + basis_series
                + " curve implies ("
                + pct
                + "% "
                + direction
                + "), the least cost design is "
                + pv
                + " kWp of PV and "
                + bat
                + " kWh of battery at "
                + best
                + " USD/kWh against "
                + d0
                + " for diesel only: "
                + save
                + "% less (computed)."
            )
            + "</p>"
        )
    else:
        parts.append(
            "<p>"
            + esc(
                "If the load is what the "
                + basis_series
                + " curve implies ("
                + pct
                + "% "
                + direction
                + "), no design with PV or battery beats diesel only at "
                + d0
                + " USD/kWh (computed)."
            )
            + "</p>"
        )
    rows: list[list[str]] = []
    for case in doc["cases"]:
        key = str(case.get("key"))
        scale = float(case["scale_frac"])
        if key == "chart_basis":
            name = "Chart day: " + basis_series + " (post hoc)"
        elif key == "chart_mean":
            name = "Chart, mean of all days (post hoc)"
        elif key == "swing_low":
            name = "Demand -" + fmt(100.0 * abs(scale - 1.0), 0) + "% (sensitivity row)"
        elif key == "swing_high":
            name = "Demand +" + fmt(100.0 * abs(scale - 1.0), 0) + "% (sensitivity row)"
        else:
            name = key
        if case.get("best_pv_kwp") is None or case.get("best_battery_kwh") is None:
            design = "none feasible"
        else:
            design = fmt(float(case["best_pv_kwp"]), 0) + " kWp + " + fmt(float(case["best_battery_kwh"]), 0) + " kWh"
        if case.get("best_lcoe_usd_per_kwh") is None:
            cost = ""
        else:
            cost = fmt(float(case["best_lcoe_usd_per_kwh"]), 3)
        if case.get("saving_pct") is None:
            save_cell = ""
        else:
            save_cell = fmt(float(case["saving_pct"]), 1) + "%"
        rows.append(
            [
                name,
                fmt(float(case["demand_kwh_yr"]), 0),
                fmt(float(case["diesel_only_lcoe_usd_per_kwh"]), 3),
                design,
                cost,
                save_cell,
                fmt(float(case["main_lcoe_usd_per_kwh"]), 3),
            ]
        )
    parts.append(
        _table(
            [
                "Load case",
                "Load (kWh/yr)",
                "Diesel only (USD/kWh)",
                "Least cost design",
                "Its cost (USD/kWh)",
                "Below diesel only",
                "Main design (USD/kWh)",
            ],
            rows,
        )
    )
    base = doc["base"]
    parts.append(
        "<p>"
        + esc(
            "Main design: the study's answer, "
            + fmt(float(base["best_pv_kwp"]), 0)
            + " kWp + "
            + fmt(float(base["best_battery_kwh"]), 0)
            + " kWh, at each load. Other inputs stay as in the study."
        )
        + "</p>"
    )
    return "".join(parts)


def _figure_check_section(result: dict, load_followup: dict | None = None) -> str:
    """One figure check section for the study page. Loads in kW and kWh. Returns str."""
    plan = result.get("plan", {})
    compare_plan = plan.get("compare", {})
    comparison = result.get("comparison")
    reading = result.get("reading")
    parts = ['<section id="figure-check"><h2>Second read of the load: SAM 3.1 reads the paper chart</h2>']
    parts.append("<p>" + esc(plan.get("figure", "")) + " of " + esc(plan.get("paper", ""))
                 + ". SAM 3.1 found each curve in the image and Muse Spark read the axis labels; "
                 + "the values below were read off the image, not typed in.</p>")
    if not isinstance(reading, dict) or reading is None:
        parts.append("<p>Not checkable: " + esc(result.get("reason", "")) + "</p>")
        parts.append("</section>")
        return "".join(parts)
    parts.append('<div class="scroll">' + figure_check_svg(result) + "</div>")
    if not isinstance(comparison, dict) or comparison is None or result.get("verdict") == "not checkable":
        reason = str(result.get("reason", ""))
        if not reason and isinstance(comparison, dict) and comparison is not None:
            reason = str(comparison.get("reason", ""))
        parts.append("<p>Not checkable: " + esc(reason) + "</p>")
        parts.append("</section>")
        return "".join(parts)
    headers = ["Day", "Energy over the hours used (kWh)", "Peak (kWh)", "Study load scaled back, against this day"]
    rows: list[list[str]] = []
    for row in comparison["series"]:
        ratio_cell = fmt(row["ratio"], 2) if row["ratio"] is not None else ""
        rows.append([str(row["name"]), fmt(row["kwh"], 0), fmt(row["peak_kwh"], 0), ratio_cell])
    hours = list(comparison["hours"])
    scaled_kw = list(comparison["table_at_figure_year_kw"])
    peak_scaled_kwh = max(float(scaled_kw[h]) for h in hours) if hours else 0.0
    rows.append(["Study load, scaled back", fmt(comparison["table_kwh"], 0), fmt(peak_scaled_kwh, 0), ""])
    parts.append(_table(headers, rows))
    years = int(comparison["years"])
    growth_pct = float(compare_plan.get("growth_frac_per_yr", 0.0)) * 100.0
    band_pct = float(comparison.get("band_frac", 0.0)) * 100.0
    diff_pct = float(comparison["diff_pct"])
    direction = "above" if diff_pct >= 0.0 else "below"
    inside = "inside" if comparison["verdict"] == "inside band" else "outside"
    first = ("The study's load (" + str(compare_plan.get("table", "")) + "), scaled back " + str(years)
             + " years at " + fmt(growth_pct, 2) + "% a year, is " + fmt(abs(diff_pct), 1) + "% " + direction
             + " the " + str(comparison["basis_series"]) + " curve. " + str(compare_plan.get("basis_note", ""))
             + " That is " + inside + " the +/-" + fmt(band_pct, 0)
             + "% demand swing of the sensitivity table.")
    parts.append("<p>" + esc(first) + "</p>")
    mean_ratio = float(comparison["mean_ratio"])
    mean_direction = "above" if mean_ratio >= 1.0 else "below"
    second = ("Over all " + str(len(comparison["series"])) + " days the study's load is "
              + fmt(abs(100.0 * (mean_ratio - 1.0)), 1) + "% " + mean_direction + " their mean.")
    parts.append("<p>" + esc(second) + "</p>")
    third = ("Hours used: " + str(len(hours)) + " of 24 (read and validated in every curve; the first and "
             + "last hour of a chart are not validated).")
    parts.append("<p>" + esc(third) + "</p>")
    validation = result.get("validation", {})
    real_pct = float(validation.get("real_figure_max_err_frac", 0.0)) * 100.0
    synth_pct = float(validation.get("synthetic_inner_max_err_frac", 0.0)) * 100.0
    fourth = ("Reader error in the chart reader test (measured): at most " + fmt(real_pct, 2)
              + "% of the axis span on a real figure and " + fmt(synth_pct, 2)
              + "% on synthetic charts, away from the first and last point.")
    parts.append("<p>" + esc(fourth) + "</p>")
    if load_followup is not None:
        parts.append(_load_followup_html(load_followup))
    parts.append("</section>")
    return "".join(parts)


def _check_price_usd_per_l(name: str, value: object) -> float:
    """Finite float above 0 in USD per L. bool and text fail. Returns float."""
    if isinstance(value, bool) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(name + " must be a finite real above 0")
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(name + " must be a finite real above 0")
    if not math.isfinite(out) or out <= 0.0:
        raise ValueError(name + " must be a finite real above 0")
    return out


def _check_frac01(name: str, value: object) -> float:
    """Finite float from 0 to 1. bool and text fail. Returns float."""
    if isinstance(value, bool) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(name + " must be a finite real from 0 to 1")
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(name + " must be a finite real from 0 to 1")
    if not math.isfinite(out) or out < 0.0 or out > 1.0:
        raise ValueError(name + " must be a finite real from 0 to 1")
    return out


def price_grid(study_price_usd_per_l: float) -> list[float]:
    """Study price plus 0.2 to 1.6 USD per L steps, sorted. Returns floats."""
    p0 = _check_price_usd_per_l("study_price_usd_per_l", study_price_usd_per_l)
    steps = [float(v) for v in FUEL_PRICE_STEPS_USD_PER_L]
    if all(abs(v - p0) > 1e-9 for v in steps):
        steps.append(p0)
    return sorted(steps)


def _report_input_value(report: dict, name: str) -> float:
    """Float value of one inputs_table row by name. Missing value fails."""
    try:
        rows = report["inputs_table"]
    except (KeyError, TypeError):
        raise ValueError("report holds no inputs_table")
    for row in rows:
        if isinstance(row, dict) and row.get("name") == name:
            value = row.get("value")
            if value is None or isinstance(value, bool):
                raise ValueError("inputs_table row " + name + " holds no value")
            try:
                out = float(value)
            except (TypeError, ValueError):
                raise ValueError("inputs_table row " + name + " holds no value")
            return out
    raise ValueError("inputs_table holds no " + name + " row")


def study_price_inputs(report: dict) -> dict:
    """Study fuel price in USD per L, unserved limit frac, demand in kWh/yr."""
    fuel = _report_input_value(report, "fuel_price_usd_per_l")
    limit = _report_input_value(report, "unserved_max_frac")
    try:
        demand_raw = report["facts"]["demand_kwh_yr"]["value"]
    except (KeyError, TypeError):
        raise ValueError("report facts hold no demand_kwh_yr value")
    if demand_raw is None or isinstance(demand_raw, bool):
        raise ValueError("report facts hold no demand_kwh_yr value")
    try:
        demand = float(demand_raw)
    except (TypeError, ValueError):
        raise ValueError("report facts hold no demand_kwh_yr value")
    return {"fuel_price_usd_per_l": fuel, "unserved_max_frac": limit, "demand_kwh_yr": demand}


_FUEL_PRICE_COLS = (
    "pv_kwp",
    "battery_kwh",
    "lcoe_usd_per_kwh",
    "fuel_l_per_yr",
    "unserved_frac",
    "renewable_fraction_frac",
)


def fuel_price_steps(
    table: pd.DataFrame,
    *,
    study_price_usd_per_l: float,
    demand_kwh_yr: float,
    unserved_max_frac: float,
    prices_usd_per_l: list[float] | tuple[float, ...],
) -> list[dict]:
    """Least cost design at each fuel price in USD per L. LCOE in USD per kWh."""
    p0 = _check_price_usd_per_l("study_price_usd_per_l", study_price_usd_per_l)
    demand = _check_price_usd_per_l("demand_kwh_yr", demand_kwh_yr)
    limit = _check_frac01("unserved_max_frac", unserved_max_frac)
    if not isinstance(prices_usd_per_l, (list, tuple)) or not prices_usd_per_l:
        raise ValueError("prices_usd_per_l must be a non-empty list or tuple")
    if len(prices_usd_per_l) > MAX_PRICE_STEPS:
        raise ValueError("prices_usd_per_l holds more than MAX_PRICE_STEPS prices")
    prices = [_check_price_usd_per_l("prices_usd_per_l", p) for p in prices_usd_per_l]
    if not isinstance(table, pd.DataFrame) or len(table) == 0:
        raise ValueError("table must be a non-empty DataFrame")
    for col in _FUEL_PRICE_COLS:
        if col not in table.columns:
            raise ValueError("table holds no " + col + " column")
    pv_all = table["pv_kwp"].astype(float)
    bat_all = table["battery_kwh"].astype(float)
    diesel_mask = (pv_all == 0.0) & (bat_all == 0.0)
    if not bool(diesel_mask.any()):
        raise ValueError("table holds no diesel only row")
    lcoe0 = table["lcoe_usd_per_kwh"].astype(float)
    fuel_l = table["fuel_l_per_yr"].astype(float)
    unserved = table["unserved_frac"].astype(float)
    served_kwh = demand * (1.0 - unserved)
    if bool((served_kwh <= 0.0).any()):
        raise ValueError("served energy must stay above 0")
    top_pv_kwp = float(pv_all.max())
    top_battery_kwh = float(bat_all.max())
    out: list[dict] = []
    for price in prices:
        recost = table.copy()
        recost["lcoe_usd_per_kwh"] = lcoe0 + (price - p0) * fuel_l / served_kwh
        best = sweep.least_cost(recost, limit)
        best_pv = float(best["pv_kwp"])
        best_bat = float(best["battery_kwh"])
        best_lcoe = float(best["lcoe_usd_per_kwh"])
        diesel_lcoe = float(recost.loc[diesel_mask, "lcoe_usd_per_kwh"].iloc[0])
        wins = best_pv == 0.0 and best_bat == 0.0
        if wins:
            edge = False
        else:
            edge = best_pv == top_pv_kwp or best_bat == top_battery_kwh
        out.append(
            {
                "price_usd_per_l": float(price),
                "diesel_only_lcoe_usd_per_kwh": float(diesel_lcoe),
                "best_pv_kwp": float(best_pv),
                "best_battery_kwh": float(best_bat),
                "best_lcoe_usd_per_kwh": float(best_lcoe),
                "best_renewable_pct": float(100.0 * float(best["renewable_fraction_frac"])),
                "saving_pct": float(100.0 * (1.0 - best_lcoe / diesel_lcoe)),
                "diesel_only_wins": bool(wins),
                "on_grid_edge": bool(edge),
                "is_study_price": bool(abs(price - p0) <= 1e-9),
            }
        )
    return out


def fuel_price_section(report: dict, table: pd.DataFrame) -> str:
    """CSS radio what-if block re-costing all designs at each USD per L price."""
    inputs = study_price_inputs(report)
    p0 = float(inputs["fuel_price_usd_per_l"])
    steps = fuel_price_steps(
        table,
        study_price_usd_per_l=p0,
        demand_kwh_yr=float(inputs["demand_kwh_yr"]),
        unserved_max_frac=float(inputs["unserved_max_frac"]),
        prices_usd_per_l=price_grid(p0),
    )
    n = len(table)
    intro = (
        "Pick a diesel price in USD per litre. The page re-costs all "
        + fmt(n, 0)
        + " designs of this study at that price; every other input stays as in the study, which used "
        + fmt(p0, 2)
        + " USD/L."
    )
    ins: list[str] = []
    labels: list[str] = []
    outs: list[str] = []
    for i, step in enumerate(steps):
        price = float(step["price_usd_per_l"])
        tick = ' checked' if bool(step["is_study_price"]) else ""
        ins.append('<input type="radio" name="fp" id="fp%d"%s>' % (i, tick))
        text = fmt(price, 2) + (" (study)" if bool(step["is_study_price"]) else "")
        labels.append('<label for="fp%d">%s</label>' % (i, esc(text)))
        d0 = float(step["diesel_only_lcoe_usd_per_kwh"])
        if bool(step["diesel_only_wins"]):
            line = (
                "At " + fmt(price, 2) + " USD/L: diesel only, at " + fmt(d0, 3)
                + " USD/kWh, is the least cost choice; no design with PV or battery beats it (computed)."
            )
        else:
            line = (
                "At " + fmt(price, 2) + " USD/L: diesel only costs " + fmt(d0, 3)
                + " USD/kWh. The least cost design is " + fmt(float(step["best_pv_kwp"]), 0)
                + " kWp of PV and " + fmt(float(step["best_battery_kwh"]), 0)
                + " kWh of battery at " + fmt(float(step["best_lcoe_usd_per_kwh"]), 3)
                + " USD/kWh, " + fmt(float(step["saving_pct"]), 1) + "% less, with "
                + fmt(float(step["best_renewable_pct"]), 0) + "% of the energy from the sun (computed)."
            )
            if bool(step["on_grid_edge"]):
                line = line + " It sits on the edge of the design grid, so a larger design may cost less."
        outs.append('<p class="fp-out" id="fpo%d">%s</p>' % (i, esc(line)))
    foot = (
        "How: a design's fuel use does not depend on the price, so its cost moves in a straight line "
        "with it. At 20% below and above the study price these are the same numbers as the fuel price "
        "rows of What moves the cost."
    )
    be_raw = None
    if isinstance(report, dict) and isinstance(report.get("facts"), dict):
        be_entry = report["facts"].get("break_even_fuel_usd_per_l")
        if isinstance(be_entry, dict):
            be_raw = be_entry.get("value", None)
    if be_raw is not None:
        foot = foot + " Below " + fmt(float(be_raw), 2) + " USD/L, diesel only is cheapest (break-even from the study)."
    return (
        '<section id="fuel-price"><h2>Try another diesel price</h2>'
        + "<p>" + esc(intro) + "</p>"
        + '<div class="fp">' + "".join(ins) + '<div class="fp-labels">' + "".join(labels) + "</div>"
        + '<div class="fp-outs">' + "".join(outs) + "</div></div>"
        + "<p>" + esc(foot) + "</p></section>"
    )


def check_field_note(note: dict) -> dict:
    """One public field figure for a site. Returns the same dict."""
    if not isinstance(note, dict):
        raise ValueError("field note must be a dict")
    if set(note) != set(FIELD_NOTE_KEYS):
        raise ValueError("field note keys must be exactly FIELD_NOTE_KEYS")
    value = note["value"]
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError("field note value must be a number")
    if not math.isfinite(float(value)):
        raise ValueError("field note value must be finite")
    decimals = note["decimals"]
    if isinstance(decimals, bool) or not isinstance(decimals, int):
        raise ValueError("field note decimals must be an int")
    if not 0 <= decimals <= 6:
        raise ValueError("field note decimals must be from 0 to 6")
    if note["label"] not in _FIELD_NOTE_LABELS:
        raise ValueError("field note label must be press, docs, paper or measured")
    url = note["url"]
    if not isinstance(url, str) or not (url.startswith("http://") or url.startswith("https://")):
        raise ValueError("field note url must start with http:// or https://")
    if note["compare"] is not None and note["compare"] not in FIELD_COMPARES:
        raise ValueError("field note compare must be None or one of FIELD_COMPARES")
    for key in FIELD_NOTE_KEYS:
        if key in ("value", "decimals", "label", "url", "compare"):
            continue
        if key == "note":
            if not isinstance(note[key], str):
                raise ValueError("field note note must be a string")
        elif not isinstance(note[key], str) or note[key] == "":
            raise ValueError("field note " + key + " must be a non-empty string")
    return note


def _firm_item(report: dict, key: str) -> dict | None:
    """One firmness item by key. None when missing."""
    firm = report.get("firmness")
    if not isinstance(firm, dict):
        return None
    for item in firm.get("items", []):
        if isinstance(item, dict) and item.get("key") == key:
            return item
    return None


def _confirm_question(report: dict) -> str:
    """Battery first engineering question. Empty when not answerable."""
    hours = _firm_item(report, "best_no_diesel_hours")
    reserve = _firm_item(report, "reserve_main_design_lcoe_usd_per_kwh")
    if hours is None or reserve is None:
        return ""
    try:
        hours_f = float(hours["value"])
        reserve_f = float(reserve["value"])
        diesel_f = float(report["facts"]["diesel_only_lcoe_usd_per_kwh"]["value"])
    except (KeyError, TypeError, ValueError):
        return ""
    if reserve_f > diesel_f:
        word = "more than"
    else:
        word = "not more than"
    units = _firm_item(report, "reserve_units")
    if units is None or units.get("value") is None:
        who = "one diesel unit"
    else:
        try:
            units_f = float(units["value"])
        except (TypeError, ValueError):
            return ""
        if units_f == 1.0:
            who = "one diesel unit"
        else:
            who = fmt(units_f, 0) + " diesel units"
    text = (
        "An engineering question comes first: can the island grid run on batteries and inverters alone? "
        "The main design runs with no diesel for " + fmt(hours_f, 0) + " hours a year (computed). If " + who
        + " must run in every hour, the main design costs " + fmt(reserve_f, 3) + " USD/kWh, " + word
        + " diesel only at " + fmt(diesel_f, 3) + " USD/kWh (computed)."
    )
    least_pv = _firm_item(report, "reserve_pv_kwp")
    least_bat = _firm_item(report, "reserve_battery_kwh")
    least_lcoe = _firm_item(report, "reserve_lcoe_usd_per_kwh")

    def _finite_real(item: dict | None) -> float | None:
        """Finite real firmness value. None when missing or not a finite real."""
        if item is None:
            return None
        value = item.get("value")
        if isinstance(value, bool) or not isinstance(value, numbers.Real):
            return None
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(out):
            return None
        return out

    pv_f = _finite_real(least_pv)
    bat_f = _finite_real(least_bat)
    lcoe_f = _finite_real(least_lcoe)
    if pv_f is not None and bat_f is not None and lcoe_f is not None:
        if lcoe_f < diesel_f:
            below = "below"
        else:
            below = "not below"
        text += (
            " Under that rule the least cost design is " + fmt(pv_f, 0) + " kWp and "
            + fmt(bat_f, 0) + " kWh at " + fmt(lcoe_f, 3) + " USD/kWh, " + below
            + " diesel only (computed; see How firm is the answer)."
        )
    return '<p class="ask">' + esc(text) + "</p>"


def _confirm_ranking(report: dict) -> str:
    """Inputs ordered by how far they move the main design cost. Empty when none."""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for row in report.get("sensitivity_table", []):
        name = str(row["input"])
        if name not in groups:
            groups[name] = {}
            order.append(name)
        factor = float(row["factor"])
        if factor < 1.0:
            groups[name]["low"] = row
        elif factor > 1.0:
            groups[name]["high"] = row
    keep = [name for name in order if "low" in groups[name] and "high" in groups[name]]
    if not keep:
        return ""

    def spread(name: str) -> float:
        """Absolute LCOE move between the low and high row. Returns float."""
        return abs(
            float(groups[name]["high"]["base_design_lcoe_usd_per_kwh"])
            - float(groups[name]["low"]["base_design_lcoe_usd_per_kwh"])
        )

    ranked = sorted(keep, key=lambda name: -spread(name))
    by_input = {row.get("name"): row for row in report.get("inputs_table", []) if isinstance(row, dict)}
    facts = report.get("facts", {})
    rows: list[list[str]] = []
    for pos, name in enumerate(ranked):
        low = groups[name]["low"]
        high = groups[name]["high"]
        if name == "demand":
            demand = facts["demand_kwh_yr"]
            value_text = fmt(float(demand["value"]), 0) + " kWh/yr (" + str(demand["label"]) + ")"
        elif name in by_input:
            cell = by_input[name]
            try:
                value_text = (
                    str(cell["cells"][1]) + " " + str(cell["unit"]) + " (" + str(cell["label"]) + ")"
                )
            except (KeyError, TypeError, IndexError):
                value_text = ""
        else:
            value_text = ""
        rows.append(
            [
                str(pos + 1),
                SENSITIVITY_LABELS.get(name, name),
                value_text,
                fmt(float(low["base_design_lcoe_usd_per_kwh"]), 3)
                + " / "
                + fmt(float(high["base_design_lcoe_usd_per_kwh"]), 3),
                FIELD_ASKS.get(name, FIELD_ASK_DEFAULT),
            ]
        )
    out = _table(
        ["Rank", "Input", "Value in this study", "Main design cost, input down / up (USD/kWh)",
         "Field data to ask for"],
        rows,
    )
    first_low = float(groups[ranked[0]]["low"]["factor"])
    out += "<p>" + esc(
        "Each input is moved " + fmt(100.0 * (1.0 - first_low), 0)
        + "% down and up, the swing in the inputs table. The order is by how far the cost of the main "
        "design moves (computed)."
    ) + "</p>"
    return out


def _confirm_notes(report: dict, field_notes: list) -> str:
    """Public field figures table. Empty when there are no notes."""
    if not field_notes:
        return ""
    for note in field_notes:
        check_field_note(note)
    facts = report.get("facts", {})
    rows: list[list[str]] = []
    for note in field_notes:
        public = (
            fmt(float(note["value"]), int(note["decimals"])) + " " + str(note["unit"])
            + " (" + str(note["label"]) + ")"
        )
        if str(note["note"]) != "":
            public += "; " + str(note["note"])
        compare = note["compare"]
        study_text = ""
        ratio_text = ""
        if compare == "energy_kwh_per_day":
            val = float(facts["demand_kwh_yr"]["value"]) / 365.0
            study_text = fmt(val, 0) + " kWh a day (computed)"
            ratio_text = fmt(val / float(note["value"]), 2) + "x"
        elif compare == "fuel_l_per_kwh":
            val = float(facts["diesel_only_fuel_l_yr"]["value"]) / float(facts["demand_kwh_yr"]["value"])
            study_text = fmt(val, 3) + " L/kWh, diesel only, idle fuel included (computed)"
            ratio_text = fmt(val / float(note["value"]), 2) + "x"
        elif compare == "peak_kw":
            peak = facts["demand_peak_kw"]
            study_text = fmt(float(peak["value"]), 0) + " kW (" + str(peak["label"]) + ")"
            ratio_text = fmt(float(peak["value"]) / float(note["value"]), 2) + "x"
        elif compare == "fuel_l_per_day":
            val = float(facts["diesel_only_fuel_l_yr"]["value"]) / 365.0
            study_text = fmt(val, 0) + " L a day, diesel only (computed)"
            ratio_text = fmt(val / float(note["value"]), 2) + "x"
        rows.append(
            [
                str(note["item"]),
                public,
                str(note["date"]),
                str(note["source"]) + ': "' + str(note["quote"]) + '" ' + str(note["url"]),
                study_text,
                ratio_text,
            ]
        )
    out = "<h3>Public field figures for this site</h3>"
    out += "<p>" + esc(
        "From the press and public documents, not from the operator's records. They can be old or rounded. "
        "They show where to look; they do not replace the study's inputs."
    ) + "</p>"
    out += _table(["Item", "Public figure", "Date", "Source and quote", "This study", "Study / public"], rows)
    return out


def _confirm_files(report: dict, engineer_files: dict) -> str:
    """Links to the hourly engineer files. Empty when none are given."""
    if engineer_files is None:
        return ""
    if not isinstance(engineer_files, dict):
        raise ValueError("engineer_files must be a dict")
    if engineer_files.get("reproduced") is not True:
        raise ValueError("engineer_files is not reproduced")
    if engineer_files.get("study_run_hash") != report.get("run_hash"):
        raise ValueError("engineer_files study_run_hash differs from the report run_hash")
    run = str(report["run_hash"])
    rows = int(engineer_files["rows"])
    lines = int(engineer_files["homer_lines"])
    out = "<h3>Check us in your own tool</h3>"
    out += "<p>" + esc(
        "The hourly series behind this page, rebuilt from the study's inputs and cached weather. Before "
        "writing them, the tool gave back this study's yearly demand, peak load, PV yield, and the main "
        "design's fuel, load not served, diesel hours and starts, to within one part in a billion (computed)."
    ) + "</p>"
    out += (
        "<ul><li>"
        + '<a href="' + esc("data/" + run + "/files/hourly.csv") + '">' + esc("hourly.csv") + "</a>: "
        + esc(
            fmt(rows, 0) + " rows, one per hour: weather, load, PV per kWp and the main design's energy "
            "flow, in UTC and local time."
        )
        + "</li>"
    )
    out += (
        "<li>"
        + '<a href="' + esc("data/" + run + "/files/homer_load_kw.txt") + '">'
        + esc("homer_load_kw.txt") + "</a>: "
        + esc(
            "the load in kW, one value per line, " + fmt(lines, 0)
            + " lines, starting at local midnight on 1 January (the single column layout in HOMER's import "
            "formats)."
        )
        + "</li></ul>"
    )
    return out


def confirm_section(
    report: dict,
    *,
    field_notes: list | None = None,
    engineer_files: dict | None = None,
) -> str:
    """Confirm first section for a study page. Plain text through esc. Returns str."""
    out = '<section id="confirm"><h2>Confirm these first</h2>'
    out += "<p>" + esc(
        "This page is a first screen, made in minutes from public data. It is not a design study. Before "
        "anyone builds on it, confirm the inputs below with field data, from the top, and check the result "
        "in your own tool."
    ) + "</p>"
    out += _confirm_question(report)
    out += _confirm_ranking(report)
    out += _confirm_notes(report, field_notes or [])
    out += _confirm_files(report, engineer_files)
    out += "</section>"
    return out


def resources_section(report: dict, screen: dict | None) -> str:
    """First screen of other local renewables. Counts and yields in plain text. Returns str."""
    if screen is None:
        return ""
    if not isinstance(screen, dict) or screen.get("schema") != RESOURCE_SCHEMA:
        raise ValueError("screen must hold schema " + RESOURCE_SCHEMA)
    if screen.get("study_run_hash") != report["run_hash"]:
        raise ValueError("screen study_run_hash differs from the report run_hash")
    sol = screen["solar"]
    wnd = screen["wind"]
    hyd = screen["hydro"]
    grd = screen["grid"]
    ver = screen["verdicts"]
    rows = [
        ["Sun",
         "PV output " + fmt(sol["pvout_kwh_per_kwp_day"], 2) + " kWh/kWp a day, "
         + fmt(sol["pvout_kwh_per_kwp_yr"], 0) + " a year (Global Solar Atlas, a Solargis model; docs)",
         "World Bank band: " + str(sol["band"]) + " (docs); " + str(ver["solar"]),
         "Costed on this page"],
        ["Wind",
         "Mean " + fmt(wnd["mean_speed_m_s"], 2) + " m/s and " + fmt(wnd["power_density_w_m2"], 0)
         + " W/m2 at 50 m, hourly " + str(wnd["years"][0]) + " to " + str(wnd["years"][1])
         + " (NASA POWER, coarse MERRA-2 grid; computed)",
         "Class " + str(wnd["class_number"]) + ", " + str(wnd["class_name"])
         + ", on the NREL scale (docs); " + str(ver["wind"]),
         "Global Wind Atlas or a mast on site; a coarse grid can miss local wind"],
        ["Hydro",
         fmt(hyd["river"], 0) + " river and " + fmt(hyd["stream"], 0)
         + " stream lines mapped within " + fmt(hyd["radius_km"], 0)
         + " km, nearby islands included (OpenStreetMap, measured)",
         str(ver["hydro"]), "Flow and head from a field survey"],
    ]
    near = grd["nearest"]
    if isinstance(near, dict):
        grid_text = ("Nearest town or city on the map: " + str(near.get("name", ""))
                     + " (" + str(near.get("place", "")) + "), " + fmt(near["km"], 0)
                     + " km in a straight line (computed)")
    else:
        grid_text = "No town or city on the map within " + fmt(grd["radius_km"], 0) + " km"
    rows.append(["Grid link", grid_text, "Not screened", "Cost of a grid link or sea cable"])
    out = '<section id="resources"><h2>Which renewable fits this site?</h2>'
    out += "<p>" + esc("A first screen of other local resources, from free public data. The costs on this page "
                       "cover solar, battery and diesel only; wind, hydro and a grid link are not costed "
                       "here.") + "</p>"
    out += _table(["Resource", "Public data", "Screen reading", "Next check"], rows)
    out += "<p>" + esc("Screen rule (assumed): solar is worth a closer look at 3.5 kWh/kWp a day or more, the "
                       "lower bound of the World Bank's favorable range; wind at class 3 or more; hydro needs "
                       "at least one mapped river within 10 km, and then flow and head decide.") + "</p>"
    out += "<h3>Is our PV model close to outside models?</h3>"
    pv_rows = []
    for item in screen["pv_checks"]:
        gap = float(item["gap_pct"])
        sign = "+" if gap >= 0.0 else "-"
        pv_rows.append([str(item["service"]), fmt(item["theirs_kwh_per_kwp_yr"], 0),
                        fmt(item["ours_kwh_per_kwp_yr"], 0), sign + fmt(abs(gap), 1) + "%"])
    out += _table(["Outside model", "Their PV output (kWh/kWp a year)",
                   "Our model on their weather (kWh/kWp a year)", "Gap"], pv_rows)
    out += "<p>" + esc("Same site and panel tilt; the loss chains differ, so a gap of a few percent is expected. "
                       "Computed after the studies ran (post hoc).") + "</p>"
    out += "</section>"
    return out


def _design_float(value: object) -> float | None:
    """Finite float from a real input. None when missing or not a finite real."""
    if isinstance(value, bool) or isinstance(value, (str, bytes, bytearray)):
        return None
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def design_change_rows(report: dict) -> list[dict]:
    """Best worst-move design shift per input. Costs in USD per kWh. Returns list."""
    if not isinstance(report, dict):
        raise ValueError("report must be a dict")
    table = report.get("sensitivity_table", [])
    if not isinstance(table, list):
        raise ValueError("sensitivity_table must be a list")
    best: dict[str, tuple[float, float, float, float, bool]] = {}
    order: list[str] = []
    for row in table:
        if not isinstance(row, dict):
            continue
        name = row.get("input")
        if not isinstance(name, str) or name == "":
            continue
        factor = _design_float(row.get("factor"))
        if factor is None or factor == 1.0:
            continue
        base = _design_float(row.get("base_design_lcoe_usd_per_kwh"))
        if base is None or base <= 0.0:
            continue
        least = _design_float(row.get("least_cost_lcoe_usd_per_kwh"))
        if least is None or least <= 0.0:
            continue
        pv = _design_float(row.get("least_cost_pv_kwp"))
        if pv is None or pv < 0.0:
            continue
        bat = _design_float(row.get("least_cost_battery_kwh"))
        if bat is None or bat < 0.0:
            continue
        same = row.get("same_design")
        if same is not True and same is not False:
            continue
        extra = base / least - 1.0
        if extra < -DESIGN_CHANGE_TOL:
            raise ValueError("least cost design costs more than the main design")
        if extra < 0.0:
            extra = 0.0
        if name not in best:
            order.append(name)
            best[name] = (extra, factor, pv, bat, same)
        elif extra > best[name][0]:
            best[name] = (extra, factor, pv, bat, same)
    ranked = sorted(order, key=lambda n: -best[n][0])
    out: list[dict] = []
    for name in ranked:
        extra, factor, pv, bat, same = best[name]
        out.append(
            {
                "input": name,
                "factor": float(factor),
                "extra_frac": float(extra),
                "pv_kwp": float(pv),
                "battery_kwh": float(bat),
                "same_design": same,
            }
        )
    return out


def design_change_section(report: dict) -> str:
    """Which inputs would change the design section. LCOE in USD per kWh. Returns str."""
    rows = design_change_rows(report)
    if not rows:
        return ""
    head = '<section id="design-change"><h2>Which inputs would change the design?</h2>'
    thresh = float(DESIGN_CHANGE_MIN_FRAC)
    stop = thresh
    mark = fmt(100 * stop, 0)
    t1 = (
        "Confirm these first ranks inputs by how far they move the cost. Before building, a second "
        "question matters more: if an input is wrong, would another design be cheaper? For each input moved "
        "down and up, the study also found the least cost design at that value. The table shows how much more "
        "the main design costs than that design, for the worse of the two moves (computed)."
    )
    cells: list[list[str]] = []
    for item in rows:
        label = str(SENSITIVITY_LABELS.get(str(item["input"]), str(item["input"])))
        factor = float(item["factor"])
        if factor < 1.0:
            moved = "down " + fmt(100 * (1.0 - factor), 0) + "%"
        else:
            moved = "up " + fmt(100 * (factor - 1.0), 0) + "%"
        if bool(item["same_design"]):
            design = "Same as the main design"
        else:
            design = fmt(float(item["pv_kwp"]), 0) + " kWp and " + fmt(float(item["battery_kwh"]), 0) + " kWh"
        more = fmt(100 * float(item["extra_frac"]), 1) + "%"
        cells.append([label, moved, design, more])
    table_html = _table(
        ["Input", "Moved", "Least cost design at that value", "Main design costs more by"],
        cells,
    )
    big = [
        str(SENSITIVITY_LABELS.get(str(item["input"]), str(item["input"])))
        for item in rows
        if float(item["extra_frac"]) >= float(DESIGN_CHANGE_MIN_FRAC)
    ]
    if len(big) == 1:
        t3 = (
            "Confirm before sizing the plant: " + big[0] + ". If this input is off by the amount above, the main "
            "design costs " + mark + "% or more above the best design for that case. The other inputs move the "
            "price more than the plan (computed; the " + mark + "% line is assumed)."
        )
    elif len(big) >= 2:
        t3 = (
            "Confirm before sizing the plant: " + ", ".join(big) + ". If these inputs are off by the amounts "
            "above, the main design costs " + mark + "% or more above the best design for that case. The other "
            "inputs move the price more than the plan (computed; the " + mark + "% line is assumed)."
        )
    else:
        t3 = (
            "No input moved this way makes the main design cost " + mark + "% or more above the best design for "
            "that case: the inputs move the price more than the plan (computed; the " + mark + "% line is "
            "assumed)."
        )
    t4 = (
        "This is the cost of a wrong input at one point each way, not an expected value: the study puts no odds "
        "on the inputs. Some inputs, such as the future diesel price, cannot be measured before building; for "
        "those, read the table as a check that the choice still holds."
    )
    return head + "<p>" + esc(t1) + "</p>" + table_html + "<p>" + esc(t3) + "</p>" + "<p>" + esc(t4) + "</p>" + "</section>"


def render_study_html(report: dict, table: pd.DataFrame, *, paper_check: dict | None = None,
                      review: dict | None = None, figure_check: dict | None = None,
                      load_followup: dict | None = None, field_notes: list | None = None,
                      engineer_files: dict | None = None,
                      resource_screen: dict | None = None) -> str:
    """Full study page for one report and design table. Returns ASCII str."""
    if load_followup is not None:
        if figure_check is None:
            raise ValueError("load_followup needs figure_check")
        if not load_followup.get("reproduced"):
            raise ValueError("load_followup is not reproduced")
        if load_followup.get("study_run_hash") != report["run_hash"]:
            raise ValueError("load_followup study_run_hash differs from the report run_hash")
    site = str(report["site"]["name"])
    facts = report["facts"]
    firm = report.get("firmness")
    sourcing = report.get("sourcing")
    best_pv = float(facts["best_pv_kwp"]["value"])
    best_bat = float(facts["best_battery_kwh"]["value"])
    best_lcoe = float(facts["best_lcoe_usd_per_kwh"]["value"])
    unserved = _unserved_max_frac(report)
    out: list[str] = ["<!DOCTYPE html>"]
    out.append('<html><head><meta charset="utf-8">')
    out.append("<title>AutoSolar study: " + esc(site) + "</title>")
    out.append("<style>" + SITE_CSS + FUEL_PRICE_CSS + "</style></head><body>")
    out.append('<header class="main-head"><h1>AutoSolar study: ' + esc(site) + "</h1>")
    out.append("<p>Run " + esc(report["run_hash"]) + ".</p></header><main>")
    out.append('<section id="answer"><h2>Answer</h2>')
    out.append('<p class="question">' + esc(report["question"]) + "</p>")
    out.append('<p class="headline">' + esc(headline(report)) + "</p>")
    caveat_lines = caveats(report)
    if caveat_lines:
        out.append('<ul class="caveats">')
        for line in caveat_lines:
            out.append("<li>" + esc(line) + "</li>")
        out.append("</ul>")
    out.append('<div class="cards">')
    for key, title in CARD_TITLES:
        fact = facts[key]
        line = str(fact["text"]) + " " + str(fact["unit"]) + " (" + str(fact["label"]) + ")"
        out.append('<div class="card"><h3>' + esc(title) + "</h3><p>" + esc(line) + "</p></div>")
    out.append("</div></section>")
    out.append(fuel_price_section(report, table))
    out.append(confirm_section(report, field_notes=field_notes, engineer_files=engineer_files))
    out.append(design_change_section(report))
    if resource_screen is not None:
        out.append(resources_section(report, resource_screen))
    if firm is not None:
        out.append('<section id="firm"><h2>How firm is the answer</h2>')
        rows = [[str(it["title"]), str(it["text"]), str(it["unit"]), str(it["label"])] for it in firm["items"]]
        out.append(_table(["Item", "Value", "Unit", "Label"], rows))
        out.append("</section>")
    out.append('<section id="designs"><h2>Every design we costed</h2>')
    out.append('<div class="scroll">' + heatmap_svg(table, best_pv, best_bat, unserved) + "</div>")
    out.append("</section>")
    out.append('<section id="sensitivity"><h2>What moves the cost</h2>')
    out.append('<div class="scroll">' + tornado_svg(report["sensitivity_table"], best_lcoe) + "</div>")
    out.append("<p>Each bar moves one input down and up by the swing in the inputs table and shows the LCOE of "
               "the chosen design.</p>")
    out.append("</section>")
    out.append('<section id="weather"><h2>Sunshine from four sources</h2>')
    out.append('<div class="scroll">' + weather_svg(report["weather_table"]) + "</div>")
    out.append("</section>")
    out.append('<section id="range"><h2>Range of the answer</h2>')
    out.append(
        _table(
            ["Weather", "Demand", "PV kWp", "Battery kWh", "LCOE USD/kWh",
             "LCOE of the main design USD/kWh", "Note"],
            [list(r["cells"]) for r in report["range_table"]],
        )
    )
    out.append("</section>")
    if paper_check is not None:
        summary = paper_check["summary"]
        out.append('<section id="paper"><h2>The published study we used</h2>')
        out.append(
            "<p>Flags "
            + esc(summary["flags"])
            + ", passes "
            + esc(summary["passes"])
            + ", not checkable "
            + esc(summary["not_checkable"])
            + "</p>"
        )
        out.append('<div class="scroll"><table><thead><tr><th>Check</th><th>Status</th>'
                   "<th>Pages</th><th>Detail</th></tr></thead><tbody>")
        for res in paper_check["results"]:
            pages = ", ".join(str(p) for p in res.get("pages", []))
            cls = ' class="flag"' if res.get("status") == "flag" else ""
            out.append(
                "<tr" + cls + "><td>"
                + esc(res.get("check_id", ""))
                + "</td><td>"
                + esc(res.get("status", ""))
                + "</td><td>"
                + esc(pages)
                + "</td><td>"
                + esc(res.get("detail", ""))
                + "</td></tr>"
            )
        out.append("</tbody></table></div>")
        out.append(
            "<p>A flag means our checks could not reconcile the numbers as printed; "
            "it is not a finding about the authors.</p>"
        )
        out.append("</section>")
    if figure_check is not None:
        out.append(_figure_check_section(figure_check, load_followup))
    if review is not None:
        out.append('<section id="review"><h2>Second model review</h2>')
        out.append("<p>" + esc(review["model"]) + "</p><ul>")
        for point in review["points"]:
            where = point.get("addressed_in")
            out.append("<li>" + esc(point.get("point", "")) + " (" + esc(where if where is not None else "open") + ")</li>")
        out.append("</ul></section>")
    out.append('<section id="checks"><h2>Checks</h2>')
    out.append(_table(["Gate", "Scope", "Passed", "Detail"], [list(g["cells"]) for g in report["gates"]]))
    out.append("</section>")
    out.append('<section id="inputs"><h2>Inputs</h2>')
    out.append(
        _table(["Name", "Value", "Unit", "Label", "Note"], [list(r["cells"]) for r in report["inputs_table"]])
    )
    if sourcing is not None:
        s_rows = sourcing["rows"]
        count_k = sum(1 for r in s_rows if r.get("status") == "curated")
        if count_k > 0:
            out.append('<p class="posthoc">' + esc(curated_line(count_k, len(s_rows))) + "</p>")
        out.append(
            _table(
                ["Input", "Status", "Value used", "Unit", "Label", "As written", "Source", "URL", "Page",
                 "Quote match", "Why kept assumed"],
                [list(r["cells"]) for r in s_rows],
            )
        )
    out.append("</section>")
    if firm is not None:
        out.append('<section id="scope"><h2>Not covered by this study</h2><ul>')
        for line in firm["out_of_scope"]:
            out.append("<li>" + esc(line) + "</li>")
        out.append("</ul></section>")
    out.append('<section id="sources"><h2>Sources</h2><ul>')
    for line in report["sources"]:
        out.append("<li>" + _linkify(str(line)) + "</li>")
    out.append("</ul></section>")
    out.append("</main>")
    out.append(
        "<footer class=\"page-foot\"><p>Labels: measured, computed, assumed, press, paper, docs. "
        "Numbers shown on this page repeat the study report text.</p></footer></body></html>"
    )
    return "".join(out)


EARLIER_NOTE = "Earlier pages of the studies above, built before some sections were added."
INDEX_CSS = "div.study{border-bottom:1px solid #ddd;padding:0 0 10px}div.study p{margin:0.35em 0}"


def render_index_html(cards: list[dict]) -> str:
    """Gallery page listing study runs (T13, T28). Returns ASCII str."""
    out: list[str] = ["<!DOCTYPE html>"]
    out.append('<html><head><meta charset="utf-8">')
    out.append("<title>AutoSolar Researcher: study gallery</title>")
    out.append("<style>" + SITE_CSS + INDEX_CSS + "</style></head><body>")
    out.append('<header class="main-head"><h1>AutoSolar Researcher: study gallery</h1></header><main>')
    if not cards:
        out.append("<p>No studies yet.</p>")
    main = [c for c in cards if not c.get("earlier")]
    earlier = [c for c in cards if c.get("earlier")]
    last_question = None
    for card in main:
        out.append('<div class="study">')
        out.append('<h2><a href="' + esc(card["href"]) + '">' + esc(card.get("title") or card["site"]) + "</a></h2>")
        if card["question"] != last_question:
            out.append("<p>" + esc(card["question"]) + "</p>")
        last_question = card["question"]
        out.append("<p>" + esc(card["headline"]) + "</p>")
        if card.get("note"):
            out.append("<p>" + esc(card["note"]) + "</p>")
        out.append("<p>Run " + esc(card["run_hash"]) + "</p>")
        out.append("</div>")
    if earlier:
        out.append("<h2>Earlier builds, kept for the record</h2>")
        out.append("<p>" + esc(EARLIER_NOTE) + "</p>")
        out.append("<table><tr><th>Run</th><th>Inputs and judge</th><th>Answer</th></tr>")
        for card in earlier:
            answer = "same as: " + card["same_as"] if card.get("same_as") else card["headline"]
            out.append('<tr><td><a href="' + esc(card["href"]) + '">' + esc(card["run_hash"]) + "</a></td><td>"
                       + esc(card.get("note") or "") + "</td><td>" + esc(answer) + "</td></tr>")
        out.append("</table>")
    out.append("</main>")
    out.append(
        "<footer class=\"page-foot\"><p>Labels: measured, computed, assumed, press, paper, docs.</p></footer>"
        "</body></html>"
    )
    return "".join(out)
