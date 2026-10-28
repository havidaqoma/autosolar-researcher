"""Acceptance tests for T12a (autosolar/paper_check.py). Written by the orchestrator.

No network and no real paper: the pages and numbers below are invented for the tests."""
import dataclasses
import json
import math

import pytest

from autosolar.paper_check import (CHECK_IDS, PLACES, QUANTITIES, SIZE_QUANTITIES, CheckResult, parse_extraction,
                                   run_checks, summary, unit_factor, unit_kind, verify_extraction)

RANGE = (1700.0, 2000.0)


def st(q, value, unit, page=1, count=None, condition="", place="text", quote=None):
    return {"quantity": q, "value": value, "count": count, "unit": unit, "condition": condition, "page": page,
            "place": place, "quote": quote or ("stated value " + str(value)), "found_page": page,
            "quote_kind": "exact"}


def row(t, load, pv_to_load=None, pv_total=None, pv_to_battery=None, dis=None, diesel=None, curt=None):
    return {"time": t, "load_kw": load, "pv_to_load_kw": pv_to_load, "pv_total_kw": pv_total,
            "pv_to_battery_kw": pv_to_battery, "battery_discharge_kw": dis, "diesel_kw": diesel,
            "curtailed_kw": curt}


def sched(rows, page=6, period_h=1):
    return {"page": page, "label": "Table 2", "period_h": period_h, "rows": rows}


def verified(statements=(), schedule=None):
    return {"statements": list(statements), "schedule": schedule, "dropped": [], "rejected": []}


def res(results, cid):
    out = [r for r in results if r.check_id == cid]
    assert len(out) == 1
    return out[0]


def check(statements=(), schedule=None, site=RANGE, cid="P1"):
    return res(run_checks(verified(statements, schedule), site_ghi_kwh_m2_yr=site), cid)


def flat_day(load=200.0, **kw):
    return [row("%02d:00" % h, load, **kw) for h in range(24)]


# ---------- constants ----------

def test_constants():
    assert PLACES == ("abstract", "text", "table", "caption", "conclusion")
    assert CHECK_IDS == tuple("P%d" % i for i in range(1, 16))
    assert SIZE_QUANTITIES == ("pv_ac_kw", "pv_dc_kwp", "battery_size", "diesel_kw", "converter_kw")
    assert len(QUANTITIES) == 37
    assert QUANTITIES["pv_ac_kw"] == "power" and QUANTITIES["battery_size"] == "battery"
    assert QUANTITIES["pv_module_count"] == "count" and QUANTITIES["ghi_kwh_m2_yr"] == "irradiation"
    assert QUANTITIES["battery_capex_usd_per_kwh"] == "money_per_energy"
    assert QUANTITIES["fuel_price_usd_per_l"] == "money_per_volume"
    assert QUANTITIES["co2_kg_yr"] == "mass" and QUANTITIES["fuel_l_yr"] == "volume"
    assert QUANTITIES["project_life_yr"] == "time" and QUANTITIES["discount_rate_frac"] == "fraction"
    assert set(SIZE_QUANTITIES) <= set(QUANTITIES)
    f = CheckResult("P1", "pass", "x", (1,))
    assert dataclasses.is_dataclass(f)
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.status = "flag"


# ---------- units ----------

@pytest.mark.parametrize("unit, dim, factor", [
    ("kW", "power", 1.0), ("MW", "power", 1000.0), ("MWp", "power", 1000.0), ("Wp", "power", 0.001),
    (" kW ac ", "power", 1.0), ("kWh", "energy", 1.0), ("MWh", "energy", 1000.0), ("GWh", "energy", 1e6),
    ("MAh", "battery", 1e6), ("Ah", "battery", 1.0), ("MWh", "battery", 1000.0), ("ha", "area", 10000.0),
    ("m\u00b2", "area", 1.0), ("kWh/m2/day", "irradiation", 365.0), ("kWh/m2/yr", "irradiation", 1.0),
    ("USD/kWh", "money_per_energy", 1.0), ("$/MWh", "money_per_energy", 0.001), ("US$/kWh", "money_per_energy", 1.0),
    ("cents/kWh", "money_per_energy", 0.01), ("USD", "money", 1.0), ("kUSD", "money", 1000.0),
    ("million USD", "money", 1e6), ("USD/kW", "money_per_power", 1.0), ("$/W", "money_per_power", 1000.0),
    ("USD/litre", "money_per_volume", 1.0), ("%", "fraction", 0.01), ("", "fraction", 1.0), ("years", "time", 1.0),
    ("litres", "volume", 1.0), ("ML", "volume", 1e6), ("tonnes", "mass", 1000.0), ("m/s", "speed", 1.0),
    ("modules", "count", 1.0), ("", "count", 1.0),
])
def test_unit_factor(unit, dim, factor):
    assert unit_factor(unit, dim) == pytest.approx(factor)


@pytest.mark.parametrize("unit, dim", [("IDR/kWh", "money_per_energy"), ("kWh", "power"), ("furlong", "area"),
                                       ("MW", "energy"), ("kVA", "power")])
def test_unit_factor_unknown(unit, dim):
    assert unit_factor(unit, dim) is None


def test_unit_kind():
    assert unit_kind("MAh", "battery") == "charge" and unit_kind("Ah", "battery") == "charge"
    assert unit_kind("kWh", "battery") == "battery" and unit_kind("MW", "power") == "power"
    assert unit_kind("bogus", "power") is None


# ---------- parse_extraction ----------

GOOD_ST = {"quantity": "pv_ac_kw", "value": 500, "count": None, "unit": "kW", "condition": "", "page": 1,
           "place": "abstract", "quote": "a PV plant of 500 kW feeds the island grid"}


def payload(statements=None, schedule=None):
    return json.dumps({"statements": [GOOD_ST] if statements is None else statements, "schedule": schedule})


def test_parse_plain_and_fenced():
    a = parse_extraction(payload())
    b = parse_extraction("```json\n" + payload() + "\n```")
    c = parse_extraction("```\n" + payload() + "\n```\n")
    assert a == b == c
    assert a["statements"] == [GOOD_ST] and a["schedule"] is None and a["rejected"] == []


@pytest.mark.parametrize("text", ["not json", "[1, 2]", json.dumps({"statements": []}),
                                  json.dumps({"statements": [], "schedule": None, "extra": 1})])
def test_parse_rejects_bad_top_level(text):
    with pytest.raises(ValueError):
        parse_extraction(text)


@pytest.mark.parametrize("change", [
    {"quantity": "pv_size"}, {"value": "500"}, {"value": True}, {"value": float("nan")}, {"count": 0},
    {"count": 2.0}, {"count": True}, {"unit": None}, {"condition": None}, {"page": 0}, {"page": 1.0},
    {"place": "figure"}, {"quote": 7},
])
def test_parse_rejects_bad_statement(change):
    bad = dict(GOOD_ST, **change)
    out = parse_extraction(payload([GOOD_ST, bad, GOOD_ST]))
    assert out["statements"] == [GOOD_ST, GOOD_ST]
    assert len(out["rejected"]) == 1 and out["rejected"][0]["index"] == 1
    assert isinstance(out["rejected"][0]["reason"], str) and out["rejected"][0]["reason"]


def test_parse_rejects_statement_with_extra_or_missing_key():
    extra = dict(GOOD_ST, note="x")
    missing = {k: v for k, v in GOOD_ST.items() if k != "condition"}
    out = parse_extraction(payload([extra, missing]))
    assert out["statements"] == [] and [r["index"] for r in out["rejected"]] == [0, 1]


def test_parse_schedule_good_and_bad():
    good = sched([row("00:00", 100.0, pv_to_load=0, diesel=100.0)])
    out = parse_extraction(payload(schedule=good))
    assert out["schedule"] == good
    bad_rows = [sched([dict(row("00:00", 100.0), extra=1)]), sched([row("00:00", -1.0)]),
                sched([row("00:00", 100.0, diesel="5")]), {"page": 6, "rows": []}]
    for bad in bad_rows:
        out = parse_extraction(payload(schedule=bad))
        assert out["schedule"] is None
        assert out["rejected"][-1]["index"] == "schedule"


# ---------- verify_extraction ----------

PAGES = [
    "Abstract. A PV plant of 500 kW and a battery of 1,200 kWh supply the island of Pulau Contoh.",
    "The diesel plant has 2 x 400 kW generators that run on imported fuel.",
    "hourly table 00:00 210 0 210 01:00 205 0 205 02:00 199 0 199 03:00 196 0 196",
    "Conclusion. The cost of energy falls to 0.21 USD/kWh with the hybrid system in place.",
]


def test_verify_keeps_and_drops():
    ex = {"statements": [
        dict(GOOD_ST, quote="A PV plant of 500 kW and a battery of 1,200 kWh"),
        dict(GOOD_ST, quantity="battery_size", value=1200, unit="kWh",
             quote="A PV plant of 500 kW and a battery of 1,200 kWh"),
        dict(GOOD_ST, quantity="diesel_kw", value=400, count=2, unit="kW", page=2,
             quote="The diesel plant has 2 x 400 kW generators"),
        dict(GOOD_ST, quantity="diesel_kw", value=400, count=3, unit="kW", page=2,
             quote="The diesel plant has 2 x 400 kW generators"),
        dict(GOOD_ST, quantity="lcoe_usd_per_kwh", value=0.25, unit="USD/kWh", page=4,
             quote="The cost of energy falls to 0.21 USD/kWh with the hybrid system"),
        dict(GOOD_ST, quantity="lcoe_usd_per_kwh", value=0.21, unit="USD/kWh", page=1,
             quote="The cost of energy is now 0.21 USD/kWh with the hybrid system"),
    ], "schedule": None, "rejected": [{"index": 9, "reason": "x"}]}
    v = verify_extraction(ex, PAGES)
    kept = v["statements"]
    assert [s["quantity"] for s in kept] == ["pv_ac_kw", "battery_size", "diesel_kw"]
    assert kept[2]["count"] == 2 and kept[2]["found_page"] == 2 and kept[0]["found_page"] == 1
    assert kept[0]["quote_kind"] == "exact"
    reasons = [d["reason"] for d in v["dropped"]]
    assert reasons == ["count not in the quote", "value not in the quote", "quote not found in the PDF"]
    assert [d["what"] for d in v["dropped"]] == ["diesel_kw", "lcoe_usd_per_kwh", "lcoe_usd_per_kwh"]
    assert v["rejected"] == [{"index": 9, "reason": "x"}] and v["schedule"] is None


def test_verify_schedule():
    rows = [row("00:00", 210, pv_to_load=0, diesel=210), row("01:00", 205, pv_to_load=0, diesel=205),
            row("02:00", 199, pv_to_load=0, diesel=199), row("03:00", 196, pv_to_load=0, diesel=196)]
    v = verify_extraction({"statements": [], "schedule": sched(rows, page=3), "rejected": []}, PAGES)
    assert v["schedule"] is not None and v["schedule"]["numbers_found_frac"] == pytest.approx(1.0)
    v = verify_extraction({"statements": [], "schedule": sched(rows, page=4), "rejected": []}, PAGES)
    assert v["schedule"] is not None
    v = verify_extraction({"statements": [], "schedule": sched(rows, page=1), "rejected": []}, PAGES)
    assert v["schedule"] is None
    assert v["dropped"] == [{"what": "schedule", "page": 1, "reason": "schedule numbers not found on its page"}]
    wrap = ["no numbers here at all", "none here either", "still none", PAGES[2]]
    v = verify_extraction({"statements": [], "schedule": sched(rows, page=1), "rejected": []}, wrap)
    assert v["schedule"] is None
    bad = [dict(r, diesel_kw=r["diesel_kw"] + 1) for r in rows]
    v = verify_extraction({"statements": [], "schedule": sched(bad, page=3), "rejected": []}, PAGES)
    assert v["schedule"] is None


# ---------- run_checks: shape ----------

def test_shape_on_empty():
    out = run_checks(verified(), site_ghi_kwh_m2_yr=None)
    assert [r.check_id for r in out] == list(CHECK_IDS)
    for r in out:
        assert r.status in ("flag", "pass", "not checkable")
        assert isinstance(r.pages, tuple) and isinstance(r.detail, str)
        r.detail.encode("ascii")
    assert {r.check_id for r in out if r.status != "not checkable"} == {"P11"}
    assert res(out, "P11").status == "flag" and "not reproducible: missing" in res(out, "P11").detail


# ---------- P1 and P6 ----------

def test_p1_units_convert():
    s = [st("lcoe_usd_per_kwh", 0.21, "USD/kWh", 1), st("lcoe_usd_per_kwh", 210, "USD/MWh", 8)]
    r = check(s)
    assert r.status == "pass" and r.pages == (1, 8)


def test_p1_value_differs():
    s = [st("lcoe_usd_per_kwh", 0.21, "USD/kWh", 1), st("lcoe_usd_per_kwh", 0.2125, "USD/kWh", 8)]
    assert check(s).status == "flag"
    s[1] = st("lcoe_usd_per_kwh", 0.212, "USD/kWh", 8)
    assert check(s).status == "pass"


def test_p1_unknown_unit_and_conditions():
    s = [st("lcoe_usd_per_kwh", 0.21, "USD/kWh", 1), st("lcoe_usd_per_kwh", 3465, "IDR/kWh", 2)]
    assert check(s).status == "flag"
    s = [st("wind_m_s", 3.67, "m/s", 13, condition="10 m"), st("wind_m_s", 4.76, "m/s", 13, condition="100 m")]
    assert check(s).status == "not checkable"
    s.append(st("wind_m_s", 18, "m/s", 12, condition="10 m"))
    r = check(s)
    assert r.status == "flag" and r.pages == (12, 13)
    assert check([st("lcoe_usd_per_kwh", 0.21, "USD/kWh")]).status == "not checkable"


def test_p1_skips_sizes_and_cost_items():
    s = [st("diesel_kw", 2.7, "MW", 1, count=2), st("diesel_kw", 1.8, "MW", 7, count=2),
         st("cost_item_usd", 100, "USD", 9, condition="capex_usd"), st("cost_item_usd", 200, "USD", 9,
                                                                        condition="capex_usd")]
    assert check(s, cid="P1").status == "not checkable"
    r = check(s, cid="P6")
    assert r.status == "flag" and r.pages == (1, 7)


def test_p6_battery_kinds_and_pass():
    assert check([st("battery_size", 3.3, "MAh", 10), st("battery_size", 4.1, "MAh", 12)], cid="P6").status == "flag"
    assert check([st("battery_size", 1200, "kWh", 1), st("battery_size", 1.2, "MWh", 5)], cid="P6").status == "pass"
    assert check([st("battery_size", 1200, "kWh", 1), st("battery_size", 3.3, "MAh", 5)], cid="P6").status == "flag"
    assert check([st("pv_ac_kw", 990, "kW", 1)], cid="P6").status == "not checkable"
    assert check([st("diesel_kw", 400, "kW", 1, count=2), st("diesel_kw", 800, "kW", 2)], cid="P6").status == "pass"


# ---------- P2 ----------

def test_p2_balance():
    rows = flat_day(200.0, pv_to_load=0.0, diesel=200.0)
    assert check(schedule=sched(rows), cid="P2").status == "pass"
    rows[5] = row("05:00", 200.0, pv_to_load=0.0, diesel=200.0, dis=200.0)
    rows[6] = row("06:00", 200.0, pv_to_load=0.0, diesel=203.0)
    rows[7] = row("07:00", 200.0, pv_to_load=0.0, diesel=206.0)
    r = check(schedule=sched(rows), cid="P2")
    assert r.status == "flag" and r.pages == (6,) and "05:00" in r.detail and "06:00" not in r.detail
    assert "07:00" in r.detail and r.detail.startswith("2 of 24")


def test_p2_pv_total_form_and_skip():
    rows = flat_day(200.0, pv_total=300.0, pv_to_battery=60.0, curt=40.0, diesel=0.0)
    assert check(schedule=sched(rows), cid="P2").status == "pass"
    rows = flat_day(200.0, diesel=200.0)
    assert check(schedule=sched(rows), cid="P2").status == "not checkable"
    assert check(cid="P2").status == "not checkable"


# ---------- P15 ----------

def test_p15_time_totals():
    sch = sched(flat_day(200.0, pv_to_load=0.0, diesel=200.0))
    assert check([st("load_kwh_day", 4800, "kWh", 3)], sch, cid="P15").status == "pass"
    assert check([st("load_kwh_day", 4.8, "MWh", 3)], sch, cid="P15").status == "pass"
    assert check([st("load_kwh_day", 4800, "MWh", 3)], sch, cid="P15").status == "flag"
    assert check([st("load_kwh_yr", 1752, "MWh", 9)], sch, cid="P15").status == "pass"
    r = check([st("load_kwh_yr", 175.2, "MWh", 9)], sch, cid="P15")
    assert r.status == "flag" and r.pages == (6, 9)
    s = [st("load_kwh_day", 4800, "kWh", 3), st("load_kwh_yr", 1752, "MWh", 9)]
    assert check(s, cid="P15").status == "pass"
    s = [st("load_kwh_day", 4800, "kWh", 3), st("load_kwh_yr", 1800, "MWh", 9)]
    assert check(s, cid="P15").status == "flag"
    assert check([st("load_kwh_day", 4800, "kWh", 3)], cid="P15").status == "not checkable"
    half = sched(flat_day(200.0, pv_to_load=0.0, diesel=200.0)[:12])
    assert check([st("load_kwh_day", 9999, "kWh", 3)], half, cid="P15").status == "not checkable"


def test_p15_diesel_and_period():
    rows = [row("%02d:00" % (2 * h), 400.0, pv_to_load=0.0, diesel=400.0) for h in range(12)]
    sch = sched(rows, period_h=2)
    assert check([st("diesel_kwh_day", 9600, "kWh", 3)], sch, cid="P15").status == "pass"
    assert check([st("load_kwh_day", 4800, "kWh", 3)], sch, cid="P15").status == "flag"


# ---------- P3 and P8 ----------

def test_p3_yield():
    s = [st("pv_kwh_yr", 800, "MWh", 9), st("pv_dc_kwp", 500, "kWp", 2)]
    assert check(s, cid="P3").status == "pass"
    s[0] = st("pv_kwh_yr", 1000, "MWh", 9)
    r = check(s, cid="P3")
    assert r.status == "flag" and r.pages == (2, 9)
    s[0] = st("pv_kwh_yr", 500, "MWh", 9)
    assert check(s, cid="P3").status == "flag"
    assert check(s, site=None, cid="P3").status == "not checkable"


def test_p3_size_from_modules_and_energy_from_schedule():
    rows = [row("%02d:00" % h, 300.0, pv_to_load=(300.0 if 6 <= h < 18 else 0.0),
                pv_to_battery=(150.0 if 6 <= h < 18 else 0.0), dis=(0.0 if 6 <= h < 18 else 150.0),
                diesel=(0.0 if 6 <= h < 18 else 150.0)) for h in range(24)]
    s = [st("pv_module_count", 3889, "modules", 11), st("pv_module_wp", 320, "Wp", 11)]
    r = check(s, sched(rows, page=19), site=(1777.0, 2022.0), cid="P3")
    # 12 h x 450 kW = 5,400 kWh/day = 1,971,000 kWh/yr over 1,244.48 kWp = 1,584 kWh/kWp: inside 1,155 to 1,820
    assert r.status == "pass"
    rows2 = [dict(x, pv_to_battery_kw=(x["pv_to_battery_kw"] or 0.0) + (400.0 if x["pv_to_load_kw"] else 0.0))
             for x in rows]
    assert check(s, sched(rows2, page=19), site=(1777.0, 2022.0), cid="P3").status == "flag"
    assert check([st("pv_ac_kw", 990, "kW", 1)], sched(rows2, page=19), site=(1777.0, 2022.0),
                 cid="P3").status == "flag"


def test_p8_resource():
    assert check([st("ghi_kwh_m2_yr", 5.23, "kWh/m2/day", 12)], site=(1777.0, 2022.0), cid="P8").status == "pass"
    assert check([st("ghi_kwh_m2_yr", 2400, "kWh/m2/yr", 12)], site=(1777.0, 2022.0), cid="P8").status == "flag"
    assert check([st("ghi_kwh_m2_yr", 2100, "kWh/m2/yr", 12)], site=(1777.0, 2022.0), cid="P8").status == "pass"
    assert check([st("ghi_kwh_m2_yr", 1600, "kWh/m2/yr", 12)], site=(1777.0, 2022.0), cid="P8").status == "pass"
    assert check([st("ghi_kwh_m2_yr", 1500, "kWh/m2/yr", 12)], site=(1777.0, 2022.0), cid="P8").status == "flag"
    assert check([st("ghi_kwh_m2_yr", 5.23, "kWh/m2/day", 12)], site=None, cid="P8").status == "not checkable"
    assert check([st("wind_m_s", 18, "m/s", 12)], cid="P8").status == "not checkable"


# ---------- P4 and P5 ----------

def test_p4_storage():
    rows = flat_day(100.0, pv_to_load=0.0, diesel=100.0)
    rows[10] = row("10:00", 100.0, pv_to_load=100.0, pv_to_battery=1000.0)
    rows[20] = row("20:00", 900.0, pv_to_load=0.0, dis=900.0)
    assert check(schedule=sched(rows), cid="P4").status == "pass"
    rows[21] = row("21:00", 100.0, pv_to_load=0.0, dis=100.0)
    assert check(schedule=sched(rows), cid="P4").status == "flag"
    rows[21] = row("21:00", 100.0, pv_to_load=0.0, diesel=100.0)
    assert check([st("battery_rte_frac", 85, "%", 4)], sched(rows), cid="P4").status == "flag"
    assert check(schedule=sched(flat_day(100.0, pv_to_load=0.0, diesel=100.0)), cid="P4").status == "not checkable"


def test_p5_ratings():
    rows = flat_day(300.0, pv_to_load=0.0, diesel=300.0)
    rows[11] = row("11:00", 936.0, pv_to_load=936.0, pv_to_battery=1054.0)
    r = check([st("pv_ac_kw", 0.99, "MW", 7)], sched(rows, page=19), cid="P5")
    assert r.status == "flag" and "1,990" in r.detail and r.pages == (7, 19)
    rows[11] = row("11:00", 936.0, pv_to_load=936.0, pv_to_battery=54.0)
    assert check([st("pv_ac_kw", 0.99, "MW", 7)], sched(rows, page=19), cid="P5").status == "pass"
    assert check([st("diesel_kw", 150, "kW", 2, count=2)], sched(rows, page=19), cid="P5").status == "pass"
    assert check([st("diesel_kw", 290, "kW", 2)], sched(rows, page=19), cid="P5").status == "flag"
    assert check([st("diesel_kw", 290, "kW", 2), st("diesel_kw", 300, "kW", 3)], sched(rows, page=19),
                 cid="P5").status == "pass"
    assert check([st("pv_ac_kw", 990, "kW", 7)], cid="P5").status == "not checkable"


# ---------- P7, P9, P10, P11, P12, P13, P14 ----------

def test_p7_area():
    base = [st("pv_module_count", 1200, "modules", 5), st("pv_module_area_m2", 2.2, "m2", 5)]
    assert check(base + [st("pv_area_m2", 1.2, "ha", 5)], cid="P7").status == "flag"
    assert check(base + [st("pv_area_m2", 4000, "m2", 5)], cid="P7").status == "pass"
    assert check(base + [st("pv_area_m2", 2000, "m2", 5)], cid="P7").status == "flag"
    assert check(base, cid="P7").status == "not checkable"


def test_p9_costs():
    items = [st("cost_item_usd", 100, "kUSD", 9, condition="capex_usd"),
             st("cost_item_usd", 200000, "USD", 9, condition="capex_usd")]
    assert check(items + [st("capex_usd", 300000, "USD", 9)], cid="P9").status == "pass"
    assert check(items + [st("capex_usd", 310000, "USD", 9)], cid="P9").status == "flag"
    assert check(items + [st("npc_usd", 310000, "USD", 9)], cid="P9").status == "not checkable"
    assert check(items, cid="P9").status == "not checkable"


def test_p10_lcoe():
    base = [st("npc_usd", 1, "million USD", 15), st("discount_rate_frac", 8, "%", 5), st("project_life_yr", 20, "years", 5),
            st("energy_served_kwh_yr", 1000, "MWh", 14)]
    crf = 0.08 * 1.08 ** 20 / (1.08 ** 20 - 1)
    assert check(base + [st("lcoe_usd_per_kwh", round(crf, 4), "USD/kWh", 16)], cid="P10").status == "pass"
    assert check(base + [st("lcoe_usd_per_kwh", 0.12, "USD/kWh", 16)], cid="P10").status == "flag"
    assert check(base[:3] + [st("load_kwh_yr", 1000, "MWh", 14), st("lcoe_usd_per_kwh", 0.12, "USD/kWh", 16)],
                 cid="P10").status == "flag"
    assert check(base[1:] + [st("lcoe_usd_per_kwh", 0.12, "USD/kWh", 16)], cid="P10").status == "not checkable"
    zero = [st("discount_rate_frac", 0, "%", 5)] + [base[0]] + base[2:] + [st("lcoe_usd_per_kwh", 0.1, "USD/kWh", 1)]
    assert check(zero, cid="P10").status == "not checkable"


def test_p11_reproducible():
    full = [st("discount_rate_frac", 8, "%"), st("project_life_yr", 20, "years"), st("om_cost_usd", 5000, "USD"),
            st("pv_ac_kw", 500, "kW"), st("pv_capex_usd_per_kw", 1100, "USD/kW"),
            st("battery_size", 1200, "kWh"), st("battery_capex_usd_per_kwh", 300, "USD/kWh"),
            st("diesel_kw", 400, "kW"), st("diesel_capex_usd_per_kw", 500, "USD/kW"),
            st("fuel_price_usd_per_l", 0.9, "USD/L")]
    assert check(full, cid="P11").status == "pass"
    r = check(full[:3] + full[3:4] + full[5:], cid="P11")
    assert r.status == "flag" and "pv_capex_usd_per_kw" in r.detail
    r = check([s for s in full if s["quantity"] != "fuel_price_usd_per_l"], cid="P11")
    assert r.status == "flag" and "fuel_price_usd_per_l" in r.detail
    r = check([s for s in full if s["quantity"] != "om_cost_usd"], cid="P11")
    assert r.status == "flag" and r.detail == "not reproducible: missing om_cost_usd"
    lean = full[:3]
    assert check(lean, cid="P11").status == "pass"


def test_p12_p13_p14():
    s = [st("fuel_l_yr", 300000, "litres"), st("diesel_kwh_yr", 1000, "MWh")]
    assert check(s, cid="P12").status == "pass"
    assert check([st("fuel_l_yr", 500, "kL"), s[1]], cid="P12").status == "flag"
    assert check(s[:1], cid="P12").status == "not checkable"
    rf = [st("diesel_kwh_yr", 600, "MWh"), st("energy_served_kwh_yr", 1000, "MWh")]
    assert check(rf + [st("renewable_fraction_frac", 40, "%")], cid="P13").status == "pass"
    assert check(rf + [st("renewable_fraction_frac", 0.45, "")], cid="P13").status == "flag"
    assert check(rf, cid="P13").status == "not checkable"
    co2 = [st("fuel_l_yr", 300000, "litres")]
    assert check(co2 + [st("co2_kg_yr", 810, "t")], cid="P14").status == "pass"
    assert check(co2 + [st("co2_kg_yr", 900, "t")], cid="P14").status == "flag"
    assert check(co2, cid="P14").status == "not checkable"


# ---------- summary and an end to end invented paper ----------

def test_summary():
    rs = [CheckResult("P1", "flag", "a", ()), CheckResult("P2", "pass", "b", ()),
          CheckResult("P3", "not checkable", "c", ()), CheckResult("P4", "flag", "d", ())]
    assert summary(rs) == {"flags": 2, "passes": 1, "not_checkable": 1, "flagged_ids": ["P1", "P4"]}


def test_end_to_end_invented_paper():
    pages = [
        "Abstract. A 990 kW PV plant with batteries now serves the island of Pulau Contoh.",
        "Methods. The island load is 4,800 kWh per day and the diesel plant has 2 x 400 kW sets.",
        "Results. hourly schedule " + " ".join("%02d:00 200 0 200" % h for h in range(24)),
        "Table 1. Diesel plant 3 x 400 kW. Site irradiation 5.23 kWh/m2/day at the island.",
    ]
    ex = {"statements": [
        {"quantity": "pv_ac_kw", "value": 990, "count": None, "unit": "kW", "condition": "", "page": 1,
         "place": "abstract", "quote": "A 990 kW PV plant with batteries now serves the island"},
        {"quantity": "load_kwh_day", "value": 4800, "count": None, "unit": "kWh", "condition": "", "page": 2,
         "place": "text", "quote": "The island load is 4,800 kWh per day"},
        {"quantity": "diesel_kw", "value": 400, "count": 2, "unit": "kW", "condition": "", "page": 2,
         "place": "text", "quote": "the diesel plant has 2 x 400 kW sets"},
        {"quantity": "diesel_kw", "value": 400, "count": 3, "unit": "kW", "condition": "", "page": 4,
         "place": "table", "quote": "Table 1. Diesel plant 3 x 400 kW."},
        {"quantity": "ghi_kwh_m2_yr", "value": 5.23, "count": None, "unit": "kWh/m2/day", "condition": "",
         "page": 4, "place": "table", "quote": "Site irradiation 5.23 kWh/m2/day at the island"},
        {"quantity": "npc_usd", "value": 9, "count": None, "unit": "million USD", "condition": "", "page": 4,
         "place": "table", "quote": "a net present cost of 9 million USD"},
    ], "schedule": {"page": 3, "label": "Table 2", "period_h": 1,
                    "rows": [row("%02d:00" % h, 200, pv_to_load=0, diesel=200) for h in range(24)]}}
    parsed = parse_extraction(json.dumps(ex))
    assert parsed["rejected"] == []
    v = verify_extraction(parsed, pages)
    assert len(v["statements"]) == 5 and v["schedule"] is not None
    assert v["dropped"] == [{"what": "npc_usd", "page": 4, "reason": "quote not found in the PDF"}]
    out = run_checks(v, site_ghi_kwh_m2_yr=(1777.0, 2022.0))
    status = {r.check_id: r.status for r in out}
    assert status == {"P1": "not checkable", "P2": "pass", "P3": "not checkable", "P4": "not checkable",
                      "P5": "pass", "P6": "flag", "P7": "not checkable", "P8": "pass", "P9": "not checkable",
                      "P10": "not checkable", "P11": "flag", "P12": "not checkable", "P13": "not checkable",
                      "P14": "not checkable", "P15": "pass"}
    assert summary(out)["flagged_ids"] == ["P6", "P11"]
    assert res(out, "P6").pages == (2, 4)
    json.dumps([dataclasses.asdict(r) for r in out])
