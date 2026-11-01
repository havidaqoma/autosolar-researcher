"""Post hoc, written by hand (not part of the product tools): re-run the T25 what-if code with case sizes taken
from published sources instead of the assumed T25 sizes. Product code is not changed; only the list of cases is.

Usage, from the repo root:  python docs/posthoc/sourced_whatifs.py
Writes docs/posthoc/sourced/b4a44fc6d4c32339_cost_whatif.{json,md}. The T25 tool's own reproduction gate still
applies: it refuses to write unless the study case gives back the study's published cost and NPC.

Sources for the sizes (literature round, Sun 1 Nov):
- Battery cycle life 2000 cycles and calendar life 10 years: Trevizan et al. 2021, MRS Energy and Sustainability,
  doi 10.1557/s43581-021-00013-9, Table 3, quoting PNNL 2020. The main design does 249 full cycles a year
  (computed), so 2000 cycles last 8.0 years: battery_life_minus_yr 4 (12 to 8).
- Diesel overhaul: 65% of 800 USD/kW every 25,000 hours, same paper, Table 4, quoting Lazard 2017. That is
  0.0208 USD per rated kW per run hour: 0.021 USD/kWh at full load, 0.030 at 70% load (computed).
- PV output falls 0.55% a year: the JA Solar data sheet value used by the PLN Nusa Penida study, Rifalda et al.
  2026, doi 10.2991/978-94-6239-687-6_6.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import autosolar.cost_whatif as cw  # noqa: E402
import cost_whatif as tool  # noqa: E402

BASE = dict(cw.CASES[0])


def case(key, label, **kw):
    """One what-if case: the study case with the given changes. Returns dict."""
    out = dict(BASE)
    out.update(key=key, label=label, **kw)
    return out


SOURCED = (
    dict(cw.CASES[0]),
    case("battery_8yr", "Battery lasts 8 years (2000 cycles at 249 a year)", battery_life_minus_yr=4),
    case("battery_10yr", "Battery lasts 10 years (calendar life)", battery_life_minus_yr=2),
    case("pv_055", "PV output falls 0.55% a year (data sheet)", pv_degradation_frac_per_yr=0.0055),
    case("overhaul_low", "Diesel overhauls +0.021 USD/kWh (full load)", diesel_om_plus_usd_per_kwh=0.021),
    case("overhaul_high", "Diesel overhauls +0.030 USD/kWh (70% load)", diesel_om_plus_usd_per_kwh=0.030),
    case("sourced_solar", "Battery 8 years and PV 0.55% a year", battery_life_minus_yr=4,
         pv_degradation_frac_per_yr=0.0055),
    case("sourced_both", "Battery 8 years, PV 0.55% a year, overhauls +0.021", battery_life_minus_yr=4,
         pv_degradation_frac_per_yr=0.0055, diesel_om_plus_usd_per_kwh=0.021),
)


def main() -> int:
    """Run the T25 tool with the sourced cases. Returns the tool's exit code."""
    cw.CASES = SOURCED
    tool.CASES = SOURCED
    return tool.main(["--run", "b4a44fc6d4c32339", "--out", str(ROOT / "docs" / "posthoc" / "sourced")])


if __name__ == "__main__":
    sys.exit(main())
