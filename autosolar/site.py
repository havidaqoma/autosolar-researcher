"""Static HTML study pages with inline SVG charts. No server, no network."""

from __future__ import annotations

import html
import re

import pandas as pd

from autosolar.curate import curated_line

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


def _figure_check_section(result: dict) -> str:
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
    parts.append("</section>")
    return "".join(parts)


def render_study_html(report: dict, table: pd.DataFrame, *, paper_check: dict | None = None,
                      review: dict | None = None, figure_check: dict | None = None) -> str:
    """Full study page for one report and design table. Returns ASCII str."""
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
    out.append("<style>" + SITE_CSS + "</style></head><body>")
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
        out.append(_figure_check_section(figure_check))
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


def render_index_html(cards: list[dict]) -> str:
    """Gallery page listing study runs. Returns ASCII str."""
    out: list[str] = ["<!DOCTYPE html>"]
    out.append('<html><head><meta charset="utf-8">')
    out.append("<title>AutoSolar Researcher: study gallery</title>")
    out.append("<style>" + SITE_CSS + "</style></head><body>")
    out.append('<header class="main-head"><h1>AutoSolar Researcher: study gallery</h1></header><main>')
    if not cards:
        out.append("<p>No studies yet.</p>")
    for card in cards:
        out.append('<a class="study" href="' + esc(card["href"]) + '">')
        out.append("<h2>" + esc(card["site"]) + "</h2>")
        out.append("<p>" + esc(card["question"]) + "</p>")
        out.append("<p>" + esc(card["headline"]) + "</p>")
        out.append("<p>Run " + esc(card["run_hash"]) + "</p>")
        out.append("</a>")
    out.append("</main>")
    out.append(
        "<footer class=\"page-foot\"><p>Labels: measured, computed, assumed, press, paper, docs.</p></footer>"
        "</body></html>"
    )
    return "".join(out)
