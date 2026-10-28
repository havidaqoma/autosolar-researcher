"""Acceptance tests for T12a2 (table numbers in autosolar/paper_check.py). Written by the orchestrator.

No network; the pages are invented."""
from autosolar.paper_check import verify_extraction

PAGES = [
    "Introduction. The island has a diesel plant and a small PV plant feeding its grid.",
    "Table 1. hybrid system profile. total load (mw) pv field area (m2) battery (mah) dpp system (mw) "
    "lcoe ($/kwh) 1.41 11.300 4.1 2 x 2.7 257.770",
    "Results. The battery runs for five hours each evening before the diesel plant starts.",
    "Conclusion. The battery capacity of 3.3 MAh supports the evening peak of the island.",
]


def st(q, value, place, page, quote, count=None, unit="MW"):
    return {"quantity": q, "value": value, "count": count, "unit": unit, "condition": "", "page": page,
            "place": place, "quote": quote}


def run(statements, pages=PAGES):
    return verify_extraction({"statements": statements, "schedule": None, "rejected": []}, pages)


def test_table_number_kept():
    v = run([st("battery_size", 4.1, "table", 2, "Battery (MAh) 4.1 in the hybrid profile table", unit="MAh")])
    assert len(v["statements"]) == 1 and v["dropped"] == []
    s = v["statements"][0]
    assert s["quote_kind"] == "table number" and s["found_page"] == 2 and s["value"] == 4.1


def test_table_number_with_count_and_neighbour_page():
    v = run([st("diesel_kw", 2.7, "table", 2, "DPP system (MW) 2 x 2.7 per unit", count=2),
             st("lcoe_usd_per_kwh", 257.77, "table", 3, "LCOE ($/kWh) 257.770 at full penetration", unit="$/kWh")])
    assert [s["quantity"] for s in v["statements"]] == ["diesel_kw", "lcoe_usd_per_kwh"]
    assert v["statements"][1]["found_page"] == 3 and v["statements"][1]["quote_kind"] == "table number"


def test_table_number_missing_or_count_missing():
    v = run([st("battery_size", 4.2, "table", 2, "Battery (MAh) 4.2 in the hybrid profile table", unit="MAh"),
             st("diesel_kw", 2.7, "table", 2, "DPP system (MW) 3 x 2.7 per unit", count=3),
             st("lcoe_usd_per_kwh", 257.77, "table", 4, "LCOE ($/kWh) 257.770 at full penetration", unit="$/kWh")])
    assert v["statements"] == []
    assert [d["reason"] for d in v["dropped"]] == ["table number not found on its page"] * 3
    assert [d["page"] for d in v["dropped"]] == [2, 2, 4]


def test_lcoe_on_page_one_needs_page_two_numbers():
    v = run([st("lcoe_usd_per_kwh", 257.77, "table", 1, "LCOE ($/kWh) 257.770 at full penetration", unit="$/kWh")],
            pages=PAGES[:1] + ["no numbers here"] + PAGES[1:])
    assert v["statements"] == []


def test_no_wrap_to_last_page():
    pages = ["first page with no numbers at all", "second page with none", "third page none", PAGES[1]]
    v = run([st("battery_size", 4.1, "table", 1, "Battery (MAh) 4.1 in the hybrid profile table", unit="MAh")], pages)
    assert v["statements"] == [] and v["dropped"][0]["reason"] == "table number not found on its page"


def test_text_place_unchanged():
    v = run([st("battery_size", 4.1, "text", 2, "Battery (MAh) 4.1 in the hybrid profile table", unit="MAh"),
             st("battery_size", 4.1, "caption", 2, "Battery (MAh) 4.1 in the hybrid profile table", unit="MAh")])
    assert v["statements"] == []
    assert [d["reason"] for d in v["dropped"]] == ["quote not found in the PDF"] * 2


def test_found_table_quote_keeps_normal_checks():
    good = st("battery_size", 3.3, "table", 4, "The battery capacity of 3.3 MAh supports the evening peak",
              unit="MAh")
    bad = st("battery_size", 4.1, "table", 4, "The battery capacity of 3.3 MAh supports the evening peak",
             unit="MAh")
    v = run([good, bad])
    assert len(v["statements"]) == 1 and v["statements"][0]["quote_kind"] == "exact"
    assert v["statements"][0]["found_page"] == 4
    assert [d["reason"] for d in v["dropped"]] == ["value not in the quote"]
