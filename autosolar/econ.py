"""Twin path LCOE for solar plus battery. Money in USD, energy in kWh."""

import math
import numbers
from dataclasses import dataclass

LCOE_TWIN_TOL_FRAC = 0.001


class LcoeTwinMismatch(RuntimeError):
    """Raised when twin LCOE paths differ above tolerance."""


@dataclass(frozen=True)
class CostInputs:
    """Cost data. Money in USD, lives in years."""

    pv_capex_usd_per_kwp: float
    pv_om_usd_per_kwp_yr: float
    pv_life_yr: int
    battery_capex_usd_per_kwh: float
    battery_power_capex_usd_per_kw: float
    battery_om_usd_per_kwh_yr: float
    battery_life_yr: int
    diesel_om_usd_per_kwh: float
    fuel_price_usd_per_l: float
    discount_rate_frac: float
    project_life_yr: int
    currency_year: int


@dataclass(frozen=True)
class Design:
    """Sizes. PV in kWp, energy in kWh, power in kW."""

    pv_kwp: float
    battery_kwh: float
    battery_kw: float


@dataclass(frozen=True)
class AnnualFlows:
    """One year flows. Energy in kWh, fuel in litres."""

    load_served_kwh: float
    fuel_l: float
    diesel_kwh: float


@dataclass(frozen=True)
class EconResult:
    """Outcome. Money in USD, LCOE in USD per kWh."""

    lcoe_usd_per_kwh: float
    lcoe_path_a_usd_per_kwh: float
    lcoe_path_b_usd_per_kwh: float
    twin_gap_frac: float
    npc_usd: float
    capex_initial_usd: float
    annual_cost_usd: float
    fuel_cost_usd_per_yr: float
    co2_t_per_yr: float
    currency_year: int


def _is_num(value: object) -> bool:
    """True for real numbers excluding bool."""
    if isinstance(value, bool):
        return False
    return isinstance(value, numbers.Real)


def _check_usd(name: str, value: object) -> float:
    """Check finite USD or quantity value at least zero."""
    if not _is_num(value):
        raise ValueError(name + " must be a number")
    num = float(value)  # type: ignore[arg-type]
    if not math.isfinite(num):
        raise ValueError(name + " must be finite")
    if num < 0:
        raise ValueError(name + " must be at least 0")
    return num


def _check_rate_frac(name: str, value: object) -> float:
    """Check fractional rate in 0 to 0.5."""
    if not _is_num(value):
        raise ValueError(name + " must be a number")
    num = float(value)  # type: ignore[arg-type]
    if not math.isfinite(num):
        raise ValueError(name + " must be finite")
    if num < 0 or num > 0.5:
        raise ValueError(name + " must be in [0, 0.5]")
    return num


def _check_life_yr(name: str, value: object) -> int:
    """Check integer life in 1 to 60."""
    if type(value) is not int:
        raise ValueError(name + " must be an int")
    if value < 1 or value > 60:  # type: ignore[operator]
        raise ValueError(name + " must be in 1..60")
    return value  # type: ignore[return-value]


def _check_currency_year(value: object) -> int:
    """Check integer year in 2000..2100."""
    if type(value) is not int:
        raise ValueError("currency_year must be an int")
    if value < 2000 or value > 2100:  # type: ignore[operator]
        raise ValueError("currency_year must be in 2000..2100")
    return value  # type: ignore[return-value]


def _validate_cost_inputs(c: CostInputs) -> None:
    """Check every CostInputs field."""
    _check_usd("pv_capex_usd_per_kwp", c.pv_capex_usd_per_kwp)
    _check_usd("pv_om_usd_per_kwp_yr", c.pv_om_usd_per_kwp_yr)
    _check_life_yr("pv_life_yr", c.pv_life_yr)
    _check_usd("battery_capex_usd_per_kwh", c.battery_capex_usd_per_kwh)
    _check_usd("battery_power_capex_usd_per_kw", c.battery_power_capex_usd_per_kw)
    _check_usd("battery_om_usd_per_kwh_yr", c.battery_om_usd_per_kwh_yr)
    _check_life_yr("battery_life_yr", c.battery_life_yr)
    _check_usd("diesel_om_usd_per_kwh", c.diesel_om_usd_per_kwh)
    _check_usd("fuel_price_usd_per_l", c.fuel_price_usd_per_l)
    _check_rate_frac("discount_rate_frac", c.discount_rate_frac)
    _check_life_yr("project_life_yr", c.project_life_yr)
    _check_currency_year(c.currency_year)


def _validate_design(d: Design) -> None:
    """Check every Design field."""
    _check_usd("pv_kwp", d.pv_kwp)
    _check_usd("battery_kwh", d.battery_kwh)
    _check_usd("battery_kw", d.battery_kw)


def _validate_flows(f: AnnualFlows) -> None:
    """Check every AnnualFlows field."""
    if not _is_num(f.load_served_kwh):
        raise ValueError("load_served_kwh must be a number")
    load = float(f.load_served_kwh)  # type: ignore[arg-type]
    if not math.isfinite(load):
        raise ValueError("load_served_kwh must be finite")
    if load <= 0:
        raise ValueError("load_served_kwh must be above 0")
    _check_usd("fuel_l", f.fuel_l)
    _check_usd("diesel_kwh", f.diesel_kwh)


def _validate_co2(co2_kg_per_l: object) -> float:
    """Check CO2 intensity in kg per litre."""
    if not _is_num(co2_kg_per_l):
        raise ValueError("co2_kg_per_l must be a number")
    num = float(co2_kg_per_l)  # type: ignore[arg-type]
    if not math.isfinite(num):
        raise ValueError("co2_kg_per_l must be finite")
    if num < 0:
        raise ValueError("co2_kg_per_l must be at least 0")
    return num


def crf(rate_frac: float, years: int) -> float:
    """Annuity ratio from rate fraction and year count."""
    _check_rate_frac("rate_frac", rate_frac)
    _check_life_yr("years", years)
    rate = float(rate_frac)  # type: ignore[arg-type]
    n = int(years)  # type: ignore[arg-type]
    if rate == 0.0:
        return 1.0 / n
    grown = (1.0 + rate) ** n
    return rate * grown / (grown - 1.0)


def component_schedule(
    capex_usd: float, life_yr: int, project_life_yr: int
) -> tuple[list[tuple[int, float]], float]:
    """Replacement years with cost in USD and salvage in USD."""
    _check_usd("capex_usd", capex_usd)
    _check_life_yr("life_yr", life_yr)
    _check_life_yr("project_life_yr", project_life_yr)
    capex = float(capex_usd)  # type: ignore[arg-type]
    life = int(life_yr)  # type: ignore[arg-type]
    proj = int(project_life_yr)  # type: ignore[arg-type]
    events: list[tuple[int, float]] = []
    mult = 1
    while mult * life < proj:
        events.append((mult * life, capex))
        mult += 1
    last = events[-1][0] if events else 0
    remaining = life - (proj - last)
    salvage_usd = capex * remaining / life if remaining > 0 else 0.0
    if capex == 0.0:
        salvage_usd = 0.0
    return (events, float(salvage_usd))


def _capex0_usd(d: Design, c: CostInputs) -> float:
    """Initial capital in USD."""
    return (
        float(d.pv_kwp) * float(c.pv_capex_usd_per_kwp)
        + float(d.battery_kwh) * float(c.battery_capex_usd_per_kwh)
        + float(d.battery_kw) * float(c.battery_power_capex_usd_per_kw)
    )


def _annual_cost_usd(d: Design, f: AnnualFlows, c: CostInputs) -> float:
    """Yearly O&M plus fuel in USD."""
    return (
        float(d.pv_kwp) * float(c.pv_om_usd_per_kwp_yr)
        + float(d.battery_kwh) * float(c.battery_om_usd_per_kwh_yr)
        + float(f.fuel_l) * float(c.fuel_price_usd_per_l)
        + float(f.diesel_kwh) * float(c.diesel_om_usd_per_kwh)
    )


def lcoe_path_a(d: Design, f: AnnualFlows, c: CostInputs) -> float:
    """LCOE in USD per kWh using yearly sums."""
    _validate_cost_inputs(c)
    _validate_design(d)
    _validate_flows(f)
    n = int(c.project_life_yr)
    r = float(c.discount_rate_frac)  # type: ignore[arg-type]
    cap0 = _capex0_usd(d, c)
    pv_cap = float(d.pv_kwp) * float(c.pv_capex_usd_per_kwp)
    bat_cap = float(d.battery_kwh) * float(
        c.battery_capex_usd_per_kwh
    ) + float(d.battery_kw) * float(c.battery_power_capex_usd_per_kw)
    ev_pv, salv_pv = component_schedule(pv_cap, c.pv_life_yr, n)
    ev_bat, salv_bat = component_schedule(bat_cap, c.battery_life_yr, n)
    extra: dict[int, float] = {}
    for yr, amt in ev_pv + ev_bat:
        extra[yr] = extra.get(yr, 0.0) + float(amt)
    annual = _annual_cost_usd(d, f, c)
    e_kwh = float(f.load_served_kwh)
    pv_num = float(cap0)
    pv_den = 0.0
    yr_i = 1
    while yr_i <= n:
        cash = annual + extra.get(yr_i, 0.0)
        if yr_i == n:
            cash = cash - salv_pv - salv_bat
        disc = (1.0 + r) ** yr_i
        pv_num = pv_num + cash / disc
        pv_den = pv_den + e_kwh / disc
        yr_i += 1
    return pv_num / pv_den


def lcoe_path_b(d: Design, f: AnnualFlows, c: CostInputs) -> float:
    """LCOE in USD annuity units per kWh."""
    _validate_cost_inputs(c)
    _validate_design(d)
    _validate_flows(f)
    n = int(c.project_life_yr)
    r = float(c.discount_rate_frac)  # type: ignore[arg-type]
    cap0 = _capex0_usd(d, c)
    pv_cap = float(d.pv_kwp) * float(c.pv_capex_usd_per_kwp)
    bat_cap = float(d.battery_kwh) * float(c.battery_capex_usd_per_kwh) + float(
        d.battery_kw
    ) * float(c.battery_power_capex_usd_per_kw)
    ev_pv, salv_pv = component_schedule(pv_cap, c.pv_life_yr, n)
    ev_bat, salv_bat = component_schedule(bat_cap, c.battery_life_yr, n)
    annual = _annual_cost_usd(d, f, c)
    e_kwh = float(f.load_served_kwh)
    k = crf(r, n)
    pv_add = sum(map(lambda evt: evt[1] / ((1.0 + r) ** evt[0]), ev_pv))
    bat_add = sum(map(lambda evt: evt[1] / ((1.0 + r) ** evt[0]), ev_bat))
    salv_disc = (salv_pv + salv_bat) / ((1.0 + r) ** n)
    npc = cap0 + pv_add + bat_add - salv_disc + annual / k
    return npc * k / e_kwh


def _npc_path_b_usd(d: Design, f: AnnualFlows, c: CostInputs) -> float:
    """Net present cost in USD using annuity math."""
    n = int(c.project_life_yr)
    r = float(c.discount_rate_frac)  # type: ignore[arg-type]
    cap0 = _capex0_usd(d, c)
    pv_cap = float(d.pv_kwp) * float(c.pv_capex_usd_per_kwp)
    bat_cap = float(d.battery_kwh) * float(c.battery_capex_usd_per_kwh) + float(
        d.battery_kw
    ) * float(c.battery_power_capex_usd_per_kw)
    ev_pv, salv_pv = component_schedule(pv_cap, c.pv_life_yr, n)
    ev_bat, salv_bat = component_schedule(bat_cap, c.battery_life_yr, n)
    annual = _annual_cost_usd(d, f, c)
    k = crf(r, n)
    pv_add = 0.0
    for yr, amt in ev_pv:
        pv_add += float(amt) / ((1.0 + r) ** int(yr))
    for yr, amt in ev_bat:
        pv_add += float(amt) / ((1.0 + r) ** int(yr))
    salv_disc = (salv_pv + salv_bat) / ((1.0 + r) ** n)
    return cap0 + pv_add - salv_disc + annual / k


def evaluate(
    d: Design, f: AnnualFlows, c: CostInputs, co2_kg_per_l: float
) -> EconResult:
    """Twin LCOE check with NPC in USD and CO2 in tonnes."""
    _validate_cost_inputs(c)
    _validate_design(d)
    _validate_flows(f)
    co2 = _validate_co2(co2_kg_per_l)
    a_val = lcoe_path_a(d, f, c)
    b_val = lcoe_path_b(d, f, c)
    if b_val == 0.0:
        gap = 0.0 if a_val == 0.0 else float("inf")
    else:
        gap = abs(a_val - b_val) / b_val
    if gap > LCOE_TWIN_TOL_FRAC:
        raise LcoeTwinMismatch(
            "twin LCOE gap "
            + str(gap)
            + " above "
            + str(LCOE_TWIN_TOL_FRAC)
            + " with path_a_usd_per_kwh="
            + str(a_val)
            + " path_b_usd_per_kwh="
            + str(b_val)
        )
    npc = _npc_path_b_usd(d, f, c)
    annual = _annual_cost_usd(d, f, c)
    fuel = float(f.fuel_l) * float(c.fuel_price_usd_per_l)
    co2t = float(f.fuel_l) * float(co2) / 1000.0
    return EconResult(
        lcoe_usd_per_kwh=float(b_val),
        lcoe_path_a_usd_per_kwh=float(a_val),
        lcoe_path_b_usd_per_kwh=float(b_val),
        twin_gap_frac=float(gap),
        npc_usd=float(npc),
        capex_initial_usd=float(_capex0_usd(d, c)),
        annual_cost_usd=float(annual),
        fuel_cost_usd_per_yr=float(fuel),
        co2_t_per_yr=float(co2t),
        currency_year=int(c.currency_year),
    )
