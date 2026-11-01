"""Acceptance tests for T27: twin test of the checking step (post hoc).

Written by hand before the code (docs/specs/T27_twin_test.md). No network: every judge here is a fake.
"""
import json
import os
import pathlib
import re
import sys

import pytest

from autosolar.cite_check import Claim, numbers_in
from autosolar.sourcing import ascii_text
from autosolar.twin_test import (LEVELS_FRAC, NOTE, SHIFTS_FRAC, TWIN_DESCRIPTIONS, TWIN_SCHEMA, TWIN_STATUSES, VOTES,
                                 claim_for, collect_items, make_twins, render_md, run_votes, summarise, twin_value,
                                 value_in_quote)

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE = ROOT / "docs" / "site"
sys.path.insert(0, str(ROOT / "tools"))
import source  # noqa: E402  (tools/source.py)
import twin_test as tool  # noqa: E402  (tools/twin_test.py)

ITEM_KEYS = ["id", "study", "input", "status", "value", "unit", "quote", "title", "url", "doi", "currency_year"]
EXPECTED_INPUTS = ["pv_capex_usd_per_kwp", "pv_om_usd_per_kwp_yr", "battery_capex_usd_per_kwh",
                   "battery_om_usd_per_kwh_yr", "discount_rate_frac", "diesel_min_load_frac",
                   "battery_power_capex_usd_per_kw", "battery_life_yr", "battery_round_trip_eff_frac",
                   "fuel_price_usd_per_l"]
SUMMARY_KEYS = {"level_frac", "n_twins", "script_caught", "votes_total", "votes_not_yes", "votes_no_verdict",
                "panel_runs", "panel_caught"}
YES = '{"supports": true, "reason": "the quote states it"}'
NO = '{"supports": false, "reason": "the quote states another number"}'


def _in_quote(value, quote):
    v = float(value)
    return any(abs(n - v) <= 1e-9 * max(1, abs(v)) for n in numbers_in(quote))


def _report_rows():
    out = []
    for h in sorted(os.listdir(SITE / "data")):
        p = SITE / "data" / h / "report.json"
        if p.exists():
            rows = json.loads(p.read_text(encoding="utf-8")).get("sourcing", {}).get("rows", [])
            out.extend((h, r) for r in rows)
    return out


class FakeJudge:
    """Says yes when the claimed value appears in the quote of the prompt, else no. Keeps every prompt."""

    def __init__(self, answer=None):
        self.prompts = []
        self.answer = answer

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.answer is not None:
            return self.answer
        claimed = re.search(r"\nClaimed value: (\S+) ", prompt).group(1)
        quote = re.search(r"\nQuote: (.*)\nSource context:", prompt, re.S).group(1)
        return YES if _in_quote(float(claimed), quote) else NO


def _write_report(site, h, rows, with_sourcing=True):
    d = site / "data" / h
    d.mkdir(parents=True, exist_ok=True)
    doc = {"schema": "x", "sourcing": {"meta": {}, "rows": rows}} if with_sourcing else {"schema": "x"}
    (d / "report.json").write_text(json.dumps(doc), encoding="utf-8")


def _row(inp, value, quote, status="checked", unit="USD/kW", title="A title", url="https://example.org/a",
         doi="10.1/x", cy=2022):
    return {"input": inp, "status": status, "value_as_written": value, "unit_as_written": unit, "quote": quote,
            "title": title, "url": url, "doi": doi, "currency_year": cy}


# ---------- constants ----------

def test_constants():
    assert TWIN_SCHEMA == "autosolar.twin_test/1"
    assert SHIFTS_FRAC == (-0.30, -0.10, -0.01, 0.0, 0.01, 0.10, 0.30)
    assert LEVELS_FRAC == (0.0, 0.01, 0.10, 0.30)
    assert VOTES == 3 and TWIN_STATUSES == ("checked", "curated")
    assert TWIN_DESCRIPTIONS == {
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
    assert set(TWIN_DESCRIPTIONS) == set(EXPECTED_INPUTS)
    for text in list(TWIN_DESCRIPTIONS.values()) + [NOTE]:
        text.encode("ascii")
    assert "Wonder vote (vote 3 in a study) is not run" in NOTE and "1%, 10% and 30%" in NOTE


# ---------- value_in_quote ----------

def test_value_in_quote():
    assert value_in_quote(1119, "set at 1,119 USD/kW (IEA)") is True
    assert value_in_quote(1119.0, "set at 1,119 USD/kW") is True
    assert value_in_quote(1108, "set at 1,119 USD/kW") is False
    assert value_in_quote(0.35, "energy component (MUSD/MWh) 0.35; other 0.04") is True
    assert value_in_quote(0.3535, "energy component (MUSD/MWh) 0.35; other 0.04") is False
    assert value_in_quote(14000, "around IDR 14 000 per liter") is True
    assert value_in_quote(1119 * (1 + 1e-12), "1119") is True
    assert value_in_quote(1119.01, "1119") is False


@pytest.mark.parametrize("value,quote", [(True, "1"), ("1119", "1119"), (float("nan"), "1"), (float("inf"), "1"),
                                         (None, "1"), (1, None), (1, b"1")])
def test_value_in_quote_bad(value, quote):
    with pytest.raises(ValueError):
        value_in_quote(value, quote)


# ---------- twin_value ----------

def test_twin_value_examples():
    assert twin_value(1119, -0.01) == 1108 and isinstance(twin_value(1119, -0.01), int)
    assert twin_value(0.35, 0.01) == 0.3535
    assert twin_value(24.38, -0.30) == 17.07
    assert twin_value(14000, 0.30) == 18200 and isinstance(twin_value(14000, 0.30), int)
    assert twin_value(25, 0.0) == 25 and isinstance(twin_value(25, 0.0), int)
    assert twin_value(25.0, 0.0) == 25 and isinstance(twin_value(25.0, 0.0), int)
    assert twin_value(9.4, 0.0) == 9.4 and isinstance(twin_value(9.4, 0.0), float)
    assert twin_value(90, 0.30) == 117
    assert twin_value(9.4, -0.01) == 9.306
    assert twin_value(15000, 0.10) == 16500


def test_twin_value_rule_matches_reference():
    for v in (1119, 24.38, 0.35, 15000, 9.4, 25, 0.33, 15, 90, 14000, 3.21, 777):
        for s in SHIFTS_FRAC:
            got = twin_value(v, s)
            if s == 0.0:
                assert got == float(v)
                continue
            y = float(format(float(v) * (1 + s), ".4g"))
            assert got == y and isinstance(got, int) is y.is_integer()


@pytest.mark.parametrize("value,shift", [(0, 0.1), (0.0, -0.3), (True, 0.1), (1.0, True), ("1", 0.1), (1, "0.1"),
                                         (float("nan"), 0.1), (1.0, float("inf"))])
def test_twin_value_bad(value, shift):
    with pytest.raises(ValueError):
        twin_value(value, shift)


# ---------- collect_items ----------

def test_collect_items_committed_site():
    items, skipped = collect_items(SITE)
    assert [it["id"] for it in items] == ["i%02d" % n for n in range(1, 11)]
    assert [it["input"] for it in items] == EXPECTED_INPUTS
    assert [list(it) for it in items] == [ITEM_KEYS] * 10
    assert [it["study"] for it in items] == ["107477f112e5d92c"] * 9 + ["5ee65dcd3350bec1"]
    assert [it["value"] for it in items] == [1119, 24.38, 0.35, 15000, 9.4, 25, 0.33, 15, 90, 14000]
    assert skipped == [{"study": "107477f112e5d92c", "input": "fuel_price_usd_per_l", "status": "curated",
                        "value": 1.26, "unit": "USD/L", "reason": "value not in quote"}]
    rows = {(h, r["input"], repr(r["value_as_written"])): r for h, r in _report_rows()}
    for it in items:
        r = rows[(it["study"], it["input"], repr(it["value"]))]
        assert it["status"] == r["status"] and it["unit"] == r["unit_as_written"] and it["quote"] == r["quote"]
        assert it["title"] == (r["title"] if isinstance(r.get("title"), str) else "")
        assert it["url"] == (r["url"] if isinstance(r.get("url"), str) else "")
        assert it["doi"] == (r["doi"] if isinstance(r.get("doi"), str) and r["doi"] else None)
        assert _in_quote(it["value"], it["quote"])
    assert items[0]["doi"] == "10.3389/fsuep.2024.1308441" and items[0]["currency_year"] == 2022
    assert items[2]["doi"] is None


def test_collect_items_rules(tmp_path):
    good = _row("pv_capex_usd_per_kwp", 1119, "set at 1,119 USD/kW")
    _write_report(tmp_path, "b2", [
        good,
        dict(good),
        "not a dict",
        _row("pv_om_usd_per_kwp_yr", 20, "20 USD/kW/yr", status="assumed"),
        _row("pv_om_usd_per_kwp_yr", True, "1 USD", status="curated"),
        _row("pv_om_usd_per_kwp_yr", 20, "", status="curated"),
        _row("unknown_input", 5, "5 USD"),
        _row("battery_life_yr", 12, "lasts 15 years", status="curated", unit="years"),
        _row("battery_life_yr", 15, "lasts 15 years", status="curated", unit="years", title=None, url=None, doi="",
             cy=True),
    ])
    _write_report(tmp_path, "a1", [_row("diesel_min_load_frac", 30, "at least 30% of rated power", unit="%")])
    (tmp_path / "data" / "c3").mkdir()
    _write_report(tmp_path, "d4", [], with_sourcing=False)
    items, skipped = collect_items(str(tmp_path))
    assert [(it["id"], it["study"], it["input"]) for it in items] == [
        ("i01", "a1", "diesel_min_load_frac"), ("i02", "b2", "pv_capex_usd_per_kwp"), ("i03", "b2", "battery_life_yr")]
    assert items[2]["title"] == "" and items[2]["url"] == "" and items[2]["doi"] is None
    assert items[2]["currency_year"] is None and items[1]["currency_year"] == 2022
    assert [(s["input"], s["reason"]) for s in skipped] == [
        ("pv_om_usd_per_kwp_yr", "no number or quote"), ("pv_om_usd_per_kwp_yr", "no number or quote"),
        ("unknown_input", "no description"), ("battery_life_yr", "value not in quote")]
    assert skipped[0] == {"study": "b2", "input": "pv_om_usd_per_kwp_yr", "status": "curated", "value": True,
                          "unit": "USD/kW", "reason": "no number or quote"}


def test_collect_items_accepts_path_and_str():
    assert collect_items(SITE) == collect_items(str(SITE))


# ---------- make_twins and claim_for ----------

def test_make_twins_committed():
    items, _ = collect_items(SITE)
    twins = make_twins(items)
    assert len(twins) == 70
    assert [list(t) for t in twins] == [["key", "item", "shift_frac", "value", "script_caught"]] * 70
    assert twins[0]["key"] == "i01:-0.30" and twins[3]["key"] == "i01:+0.00" and twins[6]["key"] == "i01:+0.30"
    assert twins[2] == {"key": "i01:-0.01", "item": "i01", "shift_frac": -0.01, "value": 1108, "script_caught": True}
    by_id = {it["id"]: it for it in items}
    for t in twins:
        it = by_id[t["item"]]
        assert t["value"] == twin_value(it["value"], t["shift_frac"])
        assert t["script_caught"] is (not _in_quote(t["value"], it["quote"]))
    assert [t["script_caught"] for t in twins if t["shift_frac"] == 0.0] == [False] * 10


def test_claim_for():
    items, _ = collect_items(SITE)
    c = claim_for(items[0], 1108)
    assert isinstance(c, Claim)
    assert (c.input_name, c.value, c.unit, c.quote) == ("pv_capex_usd_per_kwp", 1108, "USD/kW", items[0]["quote"])
    assert c.description == TWIN_DESCRIPTIONS["pv_capex_usd_per_kwp"]
    assert (c.url, c.doi, c.title, c.currency_year) == (items[0]["url"], items[0]["doi"], items[0]["title"], 2022)


# ---------- run_votes ----------

def test_run_votes_calls_resume_and_prompt():
    items, _ = collect_items(SITE)
    twins = make_twins(items)
    judge = FakeJudge()
    seen = []
    done = {}
    out = run_votes(items, twins, judge, 2, done, on_vote=seen.append)
    assert out is done and len(done) == 140 and len(judge.prompts) == 140 and len(seen) == 140
    assert list(done)[:3] == [("i01:-0.30", 1), ("i01:-0.30", 2), ("i01:-0.10", 1)]
    rec = done[("i01:-0.01", 1)]
    assert list(rec) == ["key", "vote", "supports", "reason", "raw"]
    assert rec["key"] == "i01:-0.01" and rec["vote"] == 1 and rec["supports"] is False and rec["raw"] == NO
    assert done[("i01:+0.00", 2)]["supports"] is True
    p = judge.prompts[4]
    assert "\nInput: " + TWIN_DESCRIPTIONS["pv_capex_usd_per_kwp"] + "\n" in p
    assert "\nSource title: " + items[0]["title"].strip()[:300] + "\n" in p
    assert "\nClaimed value: 1108 USD/kW\n" in p
    assert "\nQuote: " + items[0]["quote"] + "\n" in p
    assert p.endswith("\nSource context:\n" + items[0]["quote"][:3000])
    again = FakeJudge(answer="should not be called")
    run_votes(items, twins, again, 2, done)
    assert again.prompts == []
    run_votes(items, twins, again, 3, done)
    assert len(again.prompts) == 70 and len(done) == 210
    assert done[("i01:-0.30", 3)]["supports"] is None


def test_run_votes_empty_title_and_url_not_shown():
    item = {"id": "i01", "study": "s", "input": "battery_life_yr", "status": "curated", "value": 15, "unit": "years",
            "quote": "Technical lifetime (years) 15", "title": "", "url": "", "doi": None, "currency_year": None}
    twins = make_twins([item])
    judge = FakeJudge()
    run_votes([item], twins, judge, 1, {})
    assert "\nSource title: (not shown)\n" in judge.prompts[0] and "\nSource URL: (not shown)\n" in judge.prompts[0]


@pytest.mark.parametrize("votes", [0, -1, True, 2.0, "3", None])
def test_run_votes_bad_votes(votes):
    items, _ = collect_items(SITE)
    with pytest.raises(ValueError):
        run_votes(items, make_twins(items), FakeJudge(), votes, {})


# ---------- summarise ----------

def _tw(key, shift, caught):
    return {"key": key, "item": key.split(":")[0], "shift_frac": shift, "value": 1, "script_caught": caught}


def _v(key, k, supports):
    return {"key": key, "vote": k, "supports": supports, "reason": "", "raw": ""}


def test_summarise_counts():
    twins = [_tw("i01:+0.00", 0.0, False), _tw("i01:-0.01", -0.01, True), _tw("i01:+0.01", 0.01, False),
             _tw("i01:-0.30", -0.30, True), _tw("i01:+0.30", 0.30, True)]
    done = {}
    for key, k, s in [("i01:+0.00", 1, True), ("i01:+0.00", 2, False), ("i01:+0.00", 3, True),
                      ("i01:-0.01", 1, True), ("i01:-0.01", 2, True), ("i01:-0.01", 3, None),
                      ("i01:+0.01", 1, None), ("i01:+0.01", 2, True),
                      ("i01:-0.30", 1, False),
                      ("i01:+0.30", 1, False), ("i01:+0.30", 2, False), ("i01:+0.30", 3, False)]:
        done[(key, k)] = _v(key, k, s)
    rows = summarise(twins, done, 3)
    assert [r["level_frac"] for r in rows] == [0.0, 0.01, 0.10, 0.30]
    assert all(set(r) == SUMMARY_KEYS for r in rows)
    assert rows[0] == {"level_frac": 0.0, "n_twins": 1, "script_caught": 0, "votes_total": 3, "votes_not_yes": 1,
                       "votes_no_verdict": 0, "panel_runs": 1, "panel_caught": 1}
    assert rows[1] == {"level_frac": 0.01, "n_twins": 2, "script_caught": 1, "votes_total": 5, "votes_not_yes": 2,
                       "votes_no_verdict": 2, "panel_runs": 2, "panel_caught": 1}
    assert rows[2] == {"level_frac": 0.10, "n_twins": 0, "script_caught": 0, "votes_total": 0, "votes_not_yes": 0,
                       "votes_no_verdict": 0, "panel_runs": 0, "panel_caught": 0}
    assert rows[3] == {"level_frac": 0.30, "n_twins": 2, "script_caught": 2, "votes_total": 4, "votes_not_yes": 4,
                       "votes_no_verdict": 0, "panel_runs": 1, "panel_caught": 1}
    one = summarise(twins, done, 1)
    assert one[0]["votes_total"] == 1 and one[0]["panel_runs"] == 0 and one[0]["panel_caught"] == 0
    assert one[1]["votes_not_yes"] == 1 and one[1]["votes_no_verdict"] == 1
    assert summarise(twins, {}, 0)[3] == {"level_frac": 0.30, "n_twins": 2, "script_caught": 2, "votes_total": 0,
                                          "votes_not_yes": 0, "votes_no_verdict": 0, "panel_runs": 0,
                                          "panel_caught": 0}


# ---------- render_md ----------

HEADER = ("| Number given to the checker | Twins | Script: number not in the quote | Local judge, single votes: not yes "
          "| Local judge, votes 1 and 2 as in a study: not yes |")


def _doc(votes, summary, skipped=()):
    items = [{"id": "i01", "study": "s1", "input": "battery_life_yr", "status": "curated", "value": 15,
              "unit": "years", "quote": "Technical lifetime (years) 15 \u2013 typical", "title": "", "url": "",
              "doi": None, "currency_year": None}]
    return {"schema": TWIN_SCHEMA, "note": NOTE, "judge": "Judge X", "votes": votes, "items": items,
            "skipped": list(skipped), "twins": [{}] * 7, "summary": summary}


def _srow(level, n, sc, vt, vn, vnv, pr, pc):
    return {"level_frac": level, "n_twins": n, "script_caught": sc, "votes_total": vt, "votes_not_yes": vn,
            "votes_no_verdict": vnv, "panel_runs": pr, "panel_caught": pc}


def test_render_md_with_votes():
    summary = [_srow(0.0, 10, 0, 30, 3, 1, 10, 2), _srow(0.01, 20, 20, 60, 11, 0, 20, 9),
               _srow(0.10, 20, 20, 60, 40, 2, 20, 15), _srow(0.30, 20, 20, 60, 58, 0, 20, 20)]
    md = render_md(_doc(3, summary, [{"study": "s1", "input": "fuel_price_usd_per_l", "status": "curated",
                                      "value": 1.26, "unit": "USD/L", "reason": "value not in quote"}]))
    md.encode("ascii")
    assert md.endswith("\n") and "\r" not in md
    lines = md.split("\n")
    assert lines[0] == "# Twin test of the checking step (post hoc)"
    assert lines[1] == "" and lines[2] == NOTE and lines[3] == ""
    assert lines[4] == "Judge: Judge X. Votes per twin: 3. Items: 1. Twins: 7."
    i = lines.index(HEADER)
    assert lines[i + 1] == "|---|---|---|---|---|"
    assert lines[i + 2:i + 6] == ["| True value | 10 | 0 of 10 | 3 of 30 | 2 of 10 |",
                                  "| Moved 1% | 20 | 20 of 20 | 11 of 60 | 9 of 20 |",
                                  "| Moved 10% | 20 | 20 of 20 | 40 of 60 | 15 of 20 |",
                                  "| Moved 30% | 20 | 20 of 20 | 58 of 60 | 20 of 20 |"]
    assert "## Items" in lines and "## Skipped" in lines
    assert ('- i01: battery_life_yr (curated, study s1): 15 years; quote: "'
            + ascii_text("Technical lifetime (years) 15 \u2013 typical") + '"') in lines
    assert "- fuel_price_usd_per_l (curated, study s1): value not in quote" in lines
    assert lines.index("## Items") < lines.index("## Skipped")


def test_render_md_not_run_and_no_skipped():
    summary = [_srow(0.0, 10, 0, 0, 0, 0, 0, 0), _srow(0.01, 20, 20, 0, 0, 0, 0, 0),
               _srow(0.10, 20, 20, 0, 0, 0, 0, 0), _srow(0.30, 20, 20, 0, 0, 0, 0, 0)]
    md = render_md(_doc(0, summary))
    lines = md.split("\n")
    assert "| True value | 10 | 0 of 10 | not run | not run |" in lines
    assert "| Moved 30% | 20 | 20 of 20 | not run | not run |" in lines
    assert lines[lines.index("## Skipped") + 2] == "None."
    summary[1] = _srow(0.01, 20, 20, 20, 5, 0, 0, 0)
    assert "| Moved 1% | 20 | 20 of 20 | 5 of 20 | not run |" in render_md(_doc(1, summary)).split("\n")


def test_render_md_long_quote_cut():
    doc = _doc(0, [_srow(0.0, 1, 0, 0, 0, 0, 0, 0)])
    doc["items"][0]["quote"] = "x" * 250
    assert ('quote: "' + "x" * 200 + '"') in render_md(doc)


# ---------- the tool ----------

def _no_server(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the server must not be touched")
    for mod in (source, tool):
        for name in ("server_up", "start_server"):
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, boom)


def test_tool_script_only(tmp_path, monkeypatch, capsys):
    _no_server(monkeypatch)
    out = tmp_path / "out"
    assert tool.main(["--site", str(SITE), "--out", str(out)]) == 0
    raw = (out / "twin_test.json").read_bytes()
    raw.decode("ascii")
    assert b"\r\n" not in raw and raw.endswith(b"}\n")
    doc = json.loads(raw)
    assert list(doc) == ["schema", "note", "judge", "votes", "items", "skipped", "twins", "summary"]
    assert doc["schema"] == TWIN_SCHEMA and doc["note"] == NOTE
    assert doc["judge"] == "none (script layer only)" and doc["votes"] == 0
    items, skipped = collect_items(SITE)
    assert doc["items"] == items and doc["skipped"] == skipped
    twins = make_twins(items)
    assert doc["twins"] == [dict(t, votes=[]) for t in twins]
    assert doc["summary"] == summarise(twins, {}, 0)
    assert raw.decode("ascii") == json.dumps(doc, indent=1) + "\n"
    md = (out / "twin_test.md").read_bytes()
    assert b"\r\n" not in md and md.decode("ascii") == render_md(doc)
    assert not (out / "twin_test_votes.jsonl").exists()
    printed = capsys.readouterr().out.strip().split("\n")
    assert len(printed) == 4


def test_tool_with_judge_cache_and_resume(tmp_path, monkeypatch):
    _no_server(monkeypatch)
    out = tmp_path / "out"
    out.mkdir()
    other = {"judge": "another judge", "key": "i01:-0.30", "vote": 1, "supports": True, "reason": "", "raw": ""}
    (out / "twin_test_votes.jsonl").write_text(json.dumps(other, sort_keys=True) + "\n", encoding="utf-8")
    judge = FakeJudge()
    assert tool.main(["--site", str(SITE), "--out", str(out), "--judge", "glimmer", "--votes", "2"],
                     judge_fn=judge) == 0
    assert len(judge.prompts) == 140
    lines = (out / "twin_test_votes.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 141
    recs = [json.loads(x) for x in lines[1:]]
    assert all(r["judge"] == source.JUDGE_NAME for r in recs)
    assert all(list(r) == sorted(r) for r in map(json.loads, lines[1:]))
    assert all(set(r) == {"judge", "key", "vote", "supports", "reason", "raw"} for r in recs)
    doc = json.loads((out / "twin_test.json").read_text(encoding="ascii"))
    assert doc["judge"] == source.JUDGE_NAME and doc["votes"] == 2
    assert all(len(t["votes"]) == 2 and [v["vote"] for v in t["votes"]] == [1, 2] for t in doc["twins"])
    assert all(list(v) == ["key", "vote", "supports", "reason", "raw"] for t in doc["twins"] for v in t["votes"])
    s = doc["summary"]
    assert [r["panel_runs"] for r in s] == [10, 20, 20, 20]
    assert s[0]["votes_not_yes"] == 0 and s[3]["votes_not_yes"] == 40
    first = (out / "twin_test.json").read_bytes()
    never = FakeJudge(answer="never")
    assert tool.main(["--site", str(SITE), "--out", str(out), "--judge", "glimmer", "--votes", "2"],
                     judge_fn=never) == 0
    assert never.prompts == [] and (out / "twin_test.json").read_bytes() == first
    assert len((out / "twin_test_votes.jsonl").read_text(encoding="utf-8").splitlines()) == 141


def test_tool_cache_written_vote_by_vote(tmp_path, monkeypatch):
    """Each vote is on disk before the next judge call, so a crash loses at most the vote in flight."""
    _no_server(monkeypatch)
    out = tmp_path / "out"
    cache = out / "twin_test_votes.jsonl"
    seen = []
    inner = FakeJudge()

    def judge(prompt):
        seen.append(len(cache.read_text(encoding="utf-8").splitlines()) if cache.exists() else 0)
        return inner(prompt)

    assert tool.main(["--site", str(SITE), "--out", str(out), "--judge", "glimmer", "--votes", "1"],
                     judge_fn=judge) == 0
    assert seen == list(range(70))


@pytest.mark.parametrize("votes", ["0", "-2"])
def test_tool_bad_votes(tmp_path, monkeypatch, votes):
    _no_server(monkeypatch)
    args = ["--site", str(SITE), "--out", str(tmp_path / "o"), "--judge", "glimmer", "--votes", votes]
    try:
        rc = tool.main(args, judge_fn=FakeJudge())
    except SystemExit as exc:
        assert exc.code not in (0, None)
    else:
        assert rc != 0
    assert not (tmp_path / "o" / "twin_test.json").exists()
