"""Post hoc what-if costs and year by year cash flow. Money in USD, energy in kWh."""

import dataclasses
import math
import numbers

from autosolar.dispatch import Battery, DieselFleet, dispatch
from autosolar.econ import AnnualFlows, CostInputs, Design, component_schedule

COST_WHATIF_SCHEMA = "autosolar.cost_whatif/1"
NOTE = ("Re-costs the study's least cost design with the study's own dispatch and cost functions on its "
        "own hourly file. The design is not re-sized, so each row is a ceiling on that design's cost. "
        "The six single changes and their sizes were fixed before the first run; the three combined "
        "rows were added after it. Every change is assumed; every result is computed. Post hoc: none "
        "of this is in the study.")
CASE_KEYS = ("key", "label", "pv_degradation_frac_per_yr", "battery_life_minus_yr",
             "battery_power_plus_usd_per_kw", "capital_mult", "diesel_om_plus_usd_per_kwh",
             "fuel_escalation_frac_per_yr")
ROW_KEYS = ("year", "capital_usd", "om_usd", "fuel_usd", "salvage_usd", "total_usd", "discounted_usd",
            "served_kwh", "discounted_kwh")
CASES = (
    {"key": "study", "label": "As in the study", "pv_degradation_frac_per_yr": 0.0,
     "battery_life_minus_yr": 0, "battery_power_plus_usd_per_kw": 0.0, "capital_mult": 1.0,
     "diesel_om_plus_usd_per_kwh": 0.0, "fuel_escalation_frac_per_yr": 0.0},
    {"key": "pv_degradation", "label": "PV output falls 0.5% a year",
     "pv_degradation_frac_per_yr": 0.005, "battery_life_minus_yr": 0,
     "battery_power_plus_usd_per_kw": 0.0, "capital_mult": 1.0,
     "diesel_om_plus_usd_per_kwh": 0.0, "fuel_escalation_frac_per_yr": 0.0},
    {"key": "battery_life", "label": "Battery lasts 2 years less", "pv_degradation_frac_per_yr": 0.0,
     "battery_life_minus_yr": 2, "battery_power_plus_usd_per_kw": 0.0, "capital_mult": 1.0,
     "diesel_om_plus_usd_per_kwh": 0.0, "fuel_escalation_frac_per_yr": 0.0},
    {"key": "grid_forming", "label": "Grid-forming inverters: battery power price +150 USD/kW",
     "pv_degradation_frac_per_yr": 0.0, "battery_life_minus_yr": 0,
     "battery_power_plus_usd_per_kw": 150.0, "capital_mult": 1.0,
     "diesel_om_plus_usd_per_kwh": 0.0, "fuel_escalation_frac_per_yr": 0.0},
    {"key": "island_capital", "label": "Island premium: PV and battery prices +30%",
     "pv_degradation_frac_per_yr": 0.0, "battery_life_minus_yr": 0,
     "battery_power_plus_usd_per_kw": 0.0, "capital_mult": 1.3,
     "diesel_om_plus_usd_per_kwh": 0.0, "fuel_escalation_frac_per_yr": 0.0},
    {"key": "solar_side", "label": "The four above at once", "pv_degradation_frac_per_yr": 0.005,
     "battery_life_minus_yr": 2, "battery_power_plus_usd_per_kw": 150.0, "capital_mult": 1.3,
     "diesel_om_plus_usd_per_kwh": 0.0, "fuel_escalation_frac_per_yr": 0.0},
    {"key": "diesel_overhaul", "label": "Diesel overhauls: diesel O&M +0.02 USD/kWh",
     "pv_degradation_frac_per_yr": 0.0, "battery_life_minus_yr": 0,
     "battery_power_plus_usd_per_kw": 0.0, "capital_mult": 1.0,
     "diesel_om_plus_usd_per_kwh": 0.02, "fuel_escalation_frac_per_yr": 0.0},
    {"key": "fuel_escalation", "label": "Fuel price rises 2% a year (real)",
     "pv_degradation_frac_per_yr": 0.0, "battery_life_minus_yr": 0,
     "battery_power_plus_usd_per_kw": 0.0, "capital_mult": 1.0,
     "diesel_om_plus_usd_per_kwh": 0.0, "fuel_escalation_frac_per_yr": 0.02},
    {"key": "diesel_side", "label": "The two diesel items at once",
     "pv_degradation_frac_per_yr": 0.0, "battery_life_minus_yr": 0,
     "battery_power_plus_usd_per_kw": 0.0, "capital_mult": 1.0,
     "diesel_om_plus_usd_per_kwh": 0.02, "fuel_escalation_frac_per_yr": 0.02},
    {"key": "all_six", "label": "All six at once", "pv_degradation_frac_per_yr": 0.005,
     "battery_life_minus_yr": 2, "battery_power_plus_usd_per_kw": 150.0, "capital_mult": 1.3,
     "diesel_om_plus_usd_per_kwh": 0.02, "fuel_escalation_frac_per_yr": 0.02},
)

_CASE_NUMBER_KEYS = CASE_KEYS[2:]


def _num(name_str: str, value: object) -> float:
    """Value as a finite float. Rejects bool. Raises ValueError."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ValueError(name_str + " must be a number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(name_str + " must be finite")
    return out


def _clean(value: object) -> float:
    """Float with negative zero mapped to zero."""
    out = float(value)  # type: ignore[arg-type]
    if out == 0.0:
        return 0.0
    return out


def _check_case_numbers(case: dict) -> dict:
    """Case change values as floats and int. Raises ValueError."""
    try:
        degr = case["pv_degradation_frac_per_yr"]
        life_minus = case["battery_life_minus_yr"]
        power_plus = case["battery_power_plus_usd_per_kw"]
        mult = case["capital_mult"]
        diesel_plus = case["diesel_om_plus_usd_per_kwh"]
        esc = case["fuel_escalation_frac_per_yr"]
    except (KeyError, TypeError) as exc:
        raise ValueError("case must hold the six number keys") from exc
    degr_f = _num("pv_degradation_frac_per_yr", degr)
    if not 0.0 <= degr_f < 1.0:
        raise ValueError("pv_degradation_frac_per_yr must be in [0, 1)")
    if type(life_minus) is not int:
        raise ValueError("battery_life_minus_yr must be an int")
    if life_minus < 0:
        raise ValueError("battery_life_minus_yr must be at least 0")
    power_f = _num("battery_power_plus_usd_per_kw", power_plus)
    if power_f < 0.0:
        raise ValueError("battery_power_plus_usd_per_kw must be at least 0")
    mult_f = _num("capital_mult", mult)
    if not mult_f > 0.0:
        raise ValueError("capital_mult must be above 0")
    diesel_f = _num("diesel_om_plus_usd_per_kwh", diesel_plus)
    if diesel_f < 0.0:
        raise ValueError("diesel_om_plus_usd_per_kwh must be at least 0")
    esc_f = _num("fuel_escalation_frac_per_yr", esc)
    if not esc_f > -1.0:
        raise ValueError("fuel_escalation_frac_per_yr must be above -1")
    return {"pv_degradation_frac_per_yr": degr_f, "battery_life_minus_yr": life_minus,
            "battery_power_plus_usd_per_kw": power_f, "capital_mult": mult_f,
            "diesel_om_plus_usd_per_kwh": diesel_f, "fuel_escalation_frac_per_yr": esc_f}


def _check_design(design: object) -> Design:
    """Design with plain validated numbers. Raises ValueError."""
    if not isinstance(design, Design):
        raise ValueError("design must be a Design")
    for name_str in ("pv_kwp", "battery_kwh", "battery_kw"):
        val = getattr(design, name_str)
        if isinstance(val, bool) or not isinstance(val, numbers.Real):
            raise ValueError(name_str + " must be a number")
        num = float(val)
        if not math.isfinite(num):
            raise ValueError(name_str + " must be finite")
        if num < 0.0:
            raise ValueError(name_str + " must be at least 0")
    return design


def _check_costs(costs: object) -> CostInputs:
    """CostInputs with plain validated numbers. Raises ValueError."""
    if not isinstance(costs, CostInputs):
        raise ValueError("costs must be CostInputs")
    for name_str in ("pv_capex_usd_per_kwp", "pv_om_usd_per_kwp_yr", "battery_capex_usd_per_kwh",
                     "battery_power_capex_usd_per_kw", "battery_om_usd_per_kwh_yr",
                     "diesel_om_usd_per_kwh", "fuel_price_usd_per_l", "discount_rate_frac"):
        _num(name_str, getattr(costs, name_str))
    for name_str in ("pv_life_yr", "battery_life_yr", "project_life_yr", "currency_year"):
        if type(getattr(costs, name_str)) is not int:
            raise ValueError(name_str + " must be an int")
    return costs


def apply_case(costs: CostInputs, case: dict) -> CostInputs:
    """CostInputs with one case applied. Money in USD, lives in yr."""
    _check_costs(costs)
    if not isinstance(case, dict):
        raise ValueError("case must be a dict")
    vals = _check_case_numbers(case)
    if costs.battery_life_yr - vals["battery_life_minus_yr"] < 1:
        raise ValueError("battery_life_yr minus battery_life_minus_yr must be 1 or more")
    return dataclasses.replace(
        costs,
        pv_capex_usd_per_kwp=float(costs.pv_capex_usd_per_kwp) * vals["capital_mult"],
        battery_capex_usd_per_kwh=float(costs.battery_capex_usd_per_kwh) * vals["capital_mult"],
        battery_power_capex_usd_per_kw=(float(costs.battery_power_capex_usd_per_kw)
                                        + vals["battery_power_plus_usd_per_kw"]) * vals["capital_mult"],
        battery_life_yr=costs.battery_life_yr - vals["battery_life_minus_yr"],
        diesel_om_usd_per_kwh=float(costs.diesel_om_usd_per_kwh)
        + vals["diesel_om_plus_usd_per_kwh"],
    )


def _battery_for(design: Design, template: Battery) -> Battery:
    """Battery sized to the design from a template. Energy in kWh, power in kW."""
    if not isinstance(template, Battery):
        raise ValueError("battery_template must be a Battery")
    if design.battery_kwh == 0:
        return Battery(energy_kwh=0.0, power_kw=0.0,
                       round_trip_eff_frac=template.round_trip_eff_frac,
                       soc_min_frac=template.soc_min_frac,
                       soc_initial_frac=template.soc_initial_frac)
    return Battery(energy_kwh=float(design.battery_kwh), power_kw=float(design.battery_kw),
                   round_trip_eff_frac=template.round_trip_eff_frac,
                   soc_min_frac=template.soc_min_frac,
                   soc_initial_frac=template.soc_initial_frac)


def yearly_flows(pv_ac_kw_per_kwp, load_kw, *, design: Design, battery_template: Battery,
                 diesel: DieselFleet, project_life_yr: int,
                 pv_degradation_frac_per_yr: float) -> list:
    """Yearly flows with PV degrading. Energy in kWh, fuel in l."""
    _check_design(design)
    if not isinstance(battery_template, Battery):
        raise ValueError("battery_template must be a Battery")
    if not isinstance(diesel, DieselFleet):
        raise ValueError("diesel must be a DieselFleet")
    if type(project_life_yr) is not int:
        raise ValueError("project_life_yr must be an int")
    if project_life_yr < 1:
        raise ValueError("project_life_yr must be 1 or more")
    degr_f = _num("pv_degradation_frac_per_yr", pv_degradation_frac_per_yr)
    if not 0.0 <= degr_f < 1.0:
        raise ValueError("pv_degradation_frac_per_yr must be in [0, 1)")
    battery = _battery_for(design, battery_template)
    n_yr = int(project_life_yr)
    if degr_f == 0.0 or float(design.pv_kwp) == 0.0:
        result = dispatch(pv_ac_kw_per_kwp * float(design.pv_kwp), load_kw, battery, diesel)
        one = AnnualFlows(load_served_kwh=result.load_served_kwh, fuel_l=result.fuel_l,
                          diesel_kwh=result.diesel_kwh)
        return [one] * n_yr
    out = []
    for year in range(1, n_yr + 1):
        scale = float(design.pv_kwp) * (1.0 - degr_f) ** (year - 1)
        result = dispatch(pv_ac_kw_per_kwp * scale, load_kw, battery, diesel)
        out.append(AnnualFlows(load_served_kwh=result.load_served_kwh, fuel_l=result.fuel_l,
                               diesel_kwh=result.diesel_kwh))
    return out


def cash_flow(design: Design, flows: list, costs: CostInputs,
              fuel_escalation_frac_per_yr: float = 0.0) -> list:
    """Year by year cash flow rows. Money in USD, energy in kWh."""
    _check_design(design)
    _check_costs(costs)
    esc_f = _num("fuel_escalation_frac_per_yr", fuel_escalation_frac_per_yr)
    if not esc_f > -1.0:
        raise ValueError("fuel_escalation_frac_per_yr must be above -1")
    if not isinstance(flows, (list, tuple)):
        raise ValueError("flows must be a list of AnnualFlows")
    n_yr = int(costs.project_life_yr)
    if len(flows) != n_yr:
        raise ValueError("flows must hold exactly project_life_yr AnnualFlows")
    for item in flows:
        if not isinstance(item, AnnualFlows):
            raise ValueError("flows must hold AnnualFlows")
    rate = float(costs.discount_rate_frac)  # type: ignore[arg-type]
    pv_cap = float(design.pv_kwp) * float(costs.pv_capex_usd_per_kwp)
    bat_cap = (float(design.battery_kwh) * float(costs.battery_capex_usd_per_kwh)
               + float(design.battery_kw) * float(costs.battery_power_capex_usd_per_kw))
    pv_events, pv_salvage = component_schedule(pv_cap, costs.pv_life_yr, n_yr)
    bat_events, bat_salvage = component_schedule(bat_cap, costs.battery_life_yr, n_yr)
    extra: dict = {}
    for evt_year, evt_amt in list(pv_events) + list(bat_events):
        extra[evt_year] = extra.get(evt_year, 0.0) + float(evt_amt)
    rows = [{"year": 0, "capital_usd": _clean(pv_cap + bat_cap), "om_usd": 0.0, "fuel_usd": 0.0,
             "salvage_usd": 0.0, "total_usd": _clean(pv_cap + bat_cap),
             "discounted_usd": _clean(pv_cap + bat_cap), "served_kwh": 0.0, "discounted_kwh": 0.0}]
    for year in range(1, n_yr + 1):
        flow = flows[year - 1]
        capital = _clean(extra.get(year, 0.0))
        om_usd = _clean(float(design.pv_kwp) * float(costs.pv_om_usd_per_kwp_yr)
                        + float(design.battery_kwh) * float(costs.battery_om_usd_per_kwh_yr)
                        + float(flow.diesel_kwh) * float(costs.diesel_om_usd_per_kwh))
        fuel_usd = _clean(float(flow.fuel_l) * float(costs.fuel_price_usd_per_l)
                          * (1.0 + esc_f) ** (year - 1))
        if year == n_yr:
            salvage = _clean(-(float(pv_salvage) + float(bat_salvage)))
        else:
            salvage = 0.0
        total = _clean(capital + om_usd + fuel_usd + salvage)
        served = _clean(flow.load_served_kwh)
        rows.append({"year": year, "capital_usd": capital, "om_usd": om_usd, "fuel_usd": fuel_usd,
                     "salvage_usd": salvage, "total_usd": total,
                     "discounted_usd": _clean(total / (1.0 + rate) ** year),
                     "served_kwh": served,
                     "discounted_kwh": _clean(served / (1.0 + rate) ** year)})
    return rows


def summary(rows: list) -> dict:
    """NPC in USD and LCOE in USD per kWh from cash flow rows."""
    if not isinstance(rows, (list, tuple)) or len(rows) == 0:
        raise ValueError("rows must be a non-empty list")
    total_usd = 0.0
    total_kwh = 0.0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("rows must hold dicts")
        try:
            disc_usd = row["discounted_usd"]
            disc_kwh = row["discounted_kwh"]
        except KeyError as exc:
            raise ValueError("rows must hold discounted_usd and discounted_kwh") from exc
        total_usd += _num("discounted_usd", disc_usd)
        total_kwh += _num("discounted_kwh", disc_kwh)
    if not total_kwh > 0.0:
        raise ValueError("sum of discounted_kwh must be above 0")
    npc = float(total_usd)
    return {"npc_usd": npc, "lcoe_usd_per_kwh": npc / float(total_kwh)}


def run_cases(pv_ac_kw_per_kwp, load_kw, *, design: Design, battery_template: Battery,
              diesel: DieselFleet, costs: CostInputs) -> list:
    """All cases for the main and diesel only designs. Money in USD, energy in kWh."""
    _check_design(design)
    _check_costs(costs)
    if not isinstance(battery_template, Battery):
        raise ValueError("battery_template must be a Battery")
    if not isinstance(diesel, DieselFleet):
        raise ValueError("diesel must be a DieselFleet")
    diesel_only = Design(pv_kwp=0.0, battery_kwh=0.0, battery_kw=0.0)
    main_cache: dict = {}
    diesel_cache: dict = {}
    out = []
    for case in CASES:
        c2 = apply_case(costs, case)
        degr = float(case["pv_degradation_frac_per_yr"])
        esc = float(case["fuel_escalation_frac_per_yr"])
        if degr not in main_cache:
            main_cache[degr] = yearly_flows(pv_ac_kw_per_kwp, load_kw, design=design,
                                            battery_template=battery_template, diesel=diesel,
                                            project_life_yr=costs.project_life_yr,
                                            pv_degradation_frac_per_yr=degr)
        if degr not in diesel_cache:
            diesel_cache[degr] = yearly_flows(pv_ac_kw_per_kwp, load_kw, design=diesel_only,
                                              battery_template=battery_template, diesel=diesel,
                                              project_life_yr=costs.project_life_yr,
                                              pv_degradation_frac_per_yr=degr)
        main_rows = cash_flow(design, main_cache[degr], c2, esc)
        diesel_rows = cash_flow(diesel_only, diesel_cache[degr], c2, esc)
        main_sum = summary(main_rows)
        diesel_sum = summary(diesel_rows)
        main_lcoe = float(main_sum["lcoe_usd_per_kwh"])
        diesel_lcoe = float(diesel_sum["lcoe_usd_per_kwh"])
        out.append({"key": case["key"], "label": case["label"],
                    "main_lcoe_usd_per_kwh": main_lcoe,
                    "diesel_only_lcoe_usd_per_kwh": diesel_lcoe,
                    "main_npc_usd": float(main_sum["npc_usd"]),
                    "diesel_only_npc_usd": float(diesel_sum["npc_usd"]),
                    "main_vs_diesel_pct": (main_lcoe / diesel_lcoe - 1.0) * 100.0})
    return out


def _usd_text(value: object) -> str:
    """USD amount as rounded thousands text."""
    return format(int(round(_num("usd", value))), ",d")


def _check_render_case(case: object) -> dict:
    """One run_cases row with plain numbers. Raises ValueError."""
    if not isinstance(case, dict):
        raise ValueError("cases must hold dicts")
    for name_str in ("key", "label"):
        if name_str not in case:
            raise ValueError("cases must hold key and label")
    if not isinstance(case["key"], str) or not isinstance(case["label"], str):
        raise ValueError("key and label must be str")
    vals = {}
    for name_str in ("main_lcoe_usd_per_kwh", "diesel_only_lcoe_usd_per_kwh", "main_vs_diesel_pct"):
        if name_str not in case:
            raise ValueError("cases must hold lcoe and percent values")
        vals[name_str] = _num(name_str, case[name_str])
    return {"key": case["key"], "label": case["label"], **vals}


def _check_render_rows(rows: object) -> list:
    """Cash flow rows with plain numbers. Raises ValueError."""
    if not isinstance(rows, (list, tuple)) or len(rows) == 0:
        raise ValueError("cash flow must be a non-empty list")
    out = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("cash flow must hold dicts")
        vals: dict = {}
        if "year" not in row:
            raise ValueError("cash flow rows must hold year")
        if type(row["year"]) is not int:
            raise ValueError("year must be an int")
        vals["year"] = row["year"]
        for name_str in ROW_KEYS[1:]:
            if name_str not in row:
                raise ValueError("cash flow rows must hold " + name_str)
            vals[name_str] = _num(name_str, row[name_str])
        out.append(vals)
    return out


def render_md(doc: dict) -> str:
    """Markdown report for one what-if doc. Money in USD, energy in kWh."""
    if not isinstance(doc, dict):
        raise ValueError("doc must be a dict")
    for name_str in ("schema", "run_hash", "cases", "cash_flow_main", "cash_flow_diesel_only"):
        if name_str not in doc:
            raise ValueError("doc must hold " + name_str)
    if doc["schema"] != COST_WHATIF_SCHEMA:
        raise ValueError("doc schema must be " + COST_WHATIF_SCHEMA)
    if not isinstance(doc["run_hash"], str):
        raise ValueError("run_hash must be a str")
    cases = [_check_render_case(c) for c in doc["cases"]] if isinstance(doc["cases"], (list, tuple)) \
        else (_ for _ in ()).throw(ValueError("cases must be a list"))
    main_rows = _check_render_rows(doc["cash_flow_main"])
    diesel_rows = _check_render_rows(doc["cash_flow_diesel_only"])
    lines = ["# Costs the study leaves out: what if? (study " + doc["run_hash"] + ", post hoc)", "",
             NOTE, "",
             "| Change (assumed) | Solar plus battery (USD/kWh) | Diesel only (USD/kWh) | "
             "Solar plus battery against diesel only |",
             "|---|---|---|---|"]
    for case in cases:
        lines.append("| %s | %.3f | %.3f | %+.1f%% |"
                     % (case["label"], case["main_lcoe_usd_per_kwh"],
                        case["diesel_only_lcoe_usd_per_kwh"], case["main_vs_diesel_pct"]))
    for title, rows in (("main design", main_rows), ("diesel only", diesel_rows)):
        lines.append("")
        lines.append("## Year by year cash flow, " + title + " (USD, computed)")
        lines.append("")
        lines.append("| Year | Capital | O&M | Fuel | Salvage | Total | Discounted |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in rows:
            lines.append("| %d | %s | %s | %s | %s | %s | %s |"
                         % (row["year"], _usd_text(row["capital_usd"]), _usd_text(row["om_usd"]),
                            _usd_text(row["fuel_usd"]), _usd_text(row["salvage_usd"]),
                            _usd_text(row["total_usd"]), _usd_text(row["discounted_usd"])))
        lines.append("| NPC | | | | | | %s |" % _usd_text(summary(rows)["npc_usd"]))
    return "\n".join(lines) + "\n"
