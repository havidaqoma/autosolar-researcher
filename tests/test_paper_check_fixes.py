"""Acceptance tests for T12d (two paper check fixes). Written by the orchestrator. No network."""
from autosolar.paper_check import unit_factor
from test_paper_check import check, st


def test_same_unknown_unit_equal_values_pass():
    s = [st("lcoe_usd_per_kwh", 0.1192, "", 1, place="abstract"), st("lcoe_usd_per_kwh", 0.1192, "", 32,
                                                                       place="conclusion")]
    r = check(s, cid="P1")
    assert r.status == "pass" and r.pages == (1, 32)


def test_same_unknown_unit_different_values_flag():
    s = [st("lcoe_usd_per_kwh", 0.1192, "IDR/kWh", 1), st("lcoe_usd_per_kwh", 0.1300, "IDR/kWh", 9)]
    assert check(s, cid="P1").status == "flag"
    s = [st("lcoe_usd_per_kwh", 0.1192, "IDR/kWh", 1), st("lcoe_usd_per_kwh", 0.1200, "IDR/kWh", 9)]
    assert check(s, cid="P1").status == "pass"


def test_unit_string_cleaning_counts_as_same():
    s = [st("lcoe_usd_per_kwh", 3465, "IDR / kWh", 1), st("lcoe_usd_per_kwh", 3465, "idr/kwh", 2)]
    assert check(s, cid="P1").status == "pass"


def test_different_unknown_units_still_flag():
    s = [st("lcoe_usd_per_kwh", 0.1192, "", 1), st("lcoe_usd_per_kwh", 0.1192, "IDR/kWh", 2)]
    assert check(s, cid="P1").status == "flag"


def test_known_units_keep_conversion():
    s = [st("lcoe_usd_per_kwh", 0.21, "USD/kWh", 1), st("lcoe_usd_per_kwh", 210, "USD/MWh", 8)]
    assert check(s, cid="P1").status == "pass"
    s = [st("lcoe_usd_per_kwh", 257.77, "$/kWh", 12), st("lcoe_usd_per_kwh", 257.77, "$/MWh", 16)]
    assert check(s, cid="P1").status == "flag"


def test_p6_same_unknown_unit_with_count():
    s = [st("diesel_kw", 2.7, "MW/20 kV", 1, count=2), st("diesel_kw", 2.7, "MW/20 kV", 7, count=2)]
    assert check(s, cid="P6").status == "pass"
    s = [st("diesel_kw", 2.7, "MW/20 kV", 1, count=2), st("diesel_kw", 1.8, "MW/20 kV", 7, count=2)]
    assert check(s, cid="P6").status == "flag"
    s = [st("diesel_kw", 5.4, "MW/20 kV", 1), st("diesel_kw", 2.7, "MW/20 kV", 7, count=2)]
    assert check(s, cid="P6").status == "pass"


def test_kwh_m2_without_period_is_unknown():
    assert unit_factor("kWh/m2", "irradiation") is None
    assert unit_factor("kWh / m2", "irradiation") is None
    assert unit_factor("kWh/m2/day", "irradiation") == 365.0
    assert unit_factor("kWh/m2/yr", "irradiation") == 1.0


def test_p8_skips_unit_without_period():
    site = (1777.0, 2376.0)
    assert check([st("ghi_kwh_m2_yr", 5.6, "kWh/m2", 4)], site=site, cid="P8").status == "not checkable"
    r = check([st("ghi_kwh_m2_yr", 5.6, "kWh/m2", 4), st("ghi_kwh_m2_yr", 5.6, "kWh/m2/day", 5)], site=site,
              cid="P8")
    assert r.status == "pass" and r.pages == (5,)


def test_p1_irradiation_same_unknown_unit_compares_raw():
    s = [st("ghi_kwh_m2_yr", 5.6, "kWh/m2", 4), st("ghi_kwh_m2_yr", 5.6, "kWh/m2", 9)]
    assert check(s, cid="P1").status == "pass"
