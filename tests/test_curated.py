"""Acceptance tests for T16 (curated inputs, post hoc). Written by the orchestrator.
No network: the base sourcing file comes from the fakes in test_study_sourcing; weather is synthetic."""
import copy
import dataclasses
import hashlib
import json
import math

import pandas as pd
import pytest

import test_study as ts
import test_study_sourcing as tss
from autosolar.curate import (
    CURATED_JUDGE,
    CURATED_SCHEMA,
    ENTRY_KEYS,
    CuratedEntry,
    apply_curated,
    curate_run,
    curated_line,
    curated_note,
    load_curated,
)
from autosolar.site import esc, render_study_html
from autosolar.sourcing import (
    CHECKED_PREFIX,
    CURATED_PREFIX,
    SourcingRow,
    g6_check,
    load_targets,
    read_sourcing,
    write_sourcing,
)
from autosolar.study import render_markdown, run_study

ROOT = ts.ROOT
CURATED = ROOT / "config" / "curated_inputs.json"
TARGETS = ROOT / "config" / "sourcing_targets.json"
KEYS = ("input", "value", "unit", "label", "title", "url", "doi", "page", "quote_kind", "quote", "value_as_written",
        "unit_as_written", "currency_year", "derivation")
LINE_TAIL = (" inputs were curated by hand after pre-registration (post hoc), from the documents named in the table. "
             "Quote match exact means the quote is word for word from the page; table means the value was read by "
             "eye from a table image and no script checked it.")
CAT_URL = "https://example.org/catalogue.pdf"
FUEL2_URL = "https://example.org/fuel-list.html"


def entry_dict(**changes):
    d = {"input": "fuel_price_usd_per_l", "value": 1.28788, "unit": "USD/L", "label": "docs",
         "title": "Fuel list", "url": FUEL2_URL, "doi": None, "page": None, "quote_kind": "exact",
         "quote": "B40 Rp 21.250 per liter", "value_as_written": 21250, "unit_as_written": "IDR/L",
         "currency_year": 2026, "derivation": "median of the lists; fx 16500 IDR per USD assumed"}
    d.update(changes)
    return d


TEST_ENTRIES = [
    entry_dict(),
    entry_dict(input="battery_capex_usd_per_kwh", value=390.0, unit="USD/kWh", title="Catalogue", url=CAT_URL,
               page=266, quote_kind="table", quote="energy component 0.35; other project costs 0.04",
               value_as_written=0.39, unit_as_written="MUSD/MWh", currency_year=2022,
               derivation="0.35 plus 0.04 MUSD/MWh"),
    entry_dict(input="battery_life_yr", value=15, unit="yr", title="Catalogue", url=CAT_URL, page=266,
               quote_kind="table", quote="Technical lifetime (years) 15", value_as_written=15,
               unit_as_written="years", currency_year=None, derivation="as printed"),
    entry_dict(input="discount_rate_frac", value=0.0673, unit="frac", title="High cost of capital",
               url=tss.WACC_URL, doi="10.1000/xyz", quote=tss.WACC_QUOTE, value_as_written=9.4,
               unit_as_written="% nominal", currency_year=None, derivation="(1 + 0.094) / (1 + 0.025) - 1"),
]


def write_doc(path, entries=None, **top):
    doc = {"schema": "autosolar.curated/1", "note": "test", "entries": TEST_ENTRIES if entries is None else entries}
    doc.update(top)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def entries_of(dicts):
    return [CuratedEntry(**d) for d in dicts]


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cur_base")
    base_path, ipath, spath, raw, rows, meta = tss.make_sourcing(tmp)
    return {"tmp": tmp, "spath": spath, "raw": raw, "rows": rows, "meta": meta}


@pytest.fixture(scope="module")
def curated(base, tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cur_run")
    cpath = write_doc(tmp / "curated.json")
    before = base["spath"].read_bytes()
    folder = curate_run(base["spath"], cpath, TARGETS, tmp / "runs", "curated-test")
    after = base["spath"].read_bytes()
    raw, rows, meta = read_sourcing(folder / "sourcing.json")
    out = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                    inputs_path=folder / "inputs.json", runs_dir=tmp / "study", run_id="t",
                    sourcing_path=folder / "sourcing.json")
    plain = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                      inputs_path=folder / "inputs.json", runs_dir=tmp / "plain", run_id="t")
    return {"tmp": tmp, "cpath": cpath, "folder": folder, "raw": raw, "rows": rows, "meta": meta, "out": out,
            "plain": plain, "base_same": before == after}


# ---------- names ----------

def test_constants():
    assert CURATED_PREFIX == "S5 curated post hoc: "
    assert CURATED_SCHEMA == "autosolar.curated/1"
    assert CURATED_JUDGE == "none (picked by hand after pre-registration)"
    import autosolar.sourcing as srcmod
    assert srcmod.CURATED_JUDGE == CURATED_JUDGE
    assert ENTRY_KEYS == KEYS
    assert [f.name for f in dataclasses.fields(CuratedEntry)] == list(KEYS)
    e = CuratedEntry(**TEST_ENTRIES[0])
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.value = 2.0


def test_curated_line():
    assert curated_line(4, 5) == "4 of 5" + LINE_TAIL
    assert curated_line(7, 9) == "7 of 9" + LINE_TAIL
    curated_line(4, 5).encode("ascii")


def test_curated_note_full_and_short():
    e = CuratedEntry(**TEST_ENTRIES[1])
    assert curated_note(e) == ("S5 curated post hoc: Catalogue; " + CAT_URL + "; page 266; quote table; as written "
                               "0.39 MUSD/MWh; currency year 2022; 0.35 plus 0.04 MUSD/MWh")
    e2 = CuratedEntry(**entry_dict(value_as_written=None, currency_year=None))
    assert curated_note(e2) == ("S5 curated post hoc: Fuel list; " + FUEL2_URL + "; quote exact; median of the lists; "
                                "fx 16500 IDR per USD assumed")
    e3 = CuratedEntry(**TEST_ENTRIES[0])
    assert curated_note(e3) == ("S5 curated post hoc: Fuel list; " + FUEL2_URL + "; quote exact; as written 21250 "
                                "IDR/L; currency year 2026; median of the lists; fx 16500 IDR per USD assumed")


# ---------- load_curated ----------

def test_load_test_doc(tmp_path):
    p = write_doc(tmp_path / "c.json")
    entries, sha = load_curated(p)
    assert sha == hashlib.sha256(p.read_bytes()).hexdigest()
    assert entries == entries_of(TEST_ENTRIES)
    assert type(entries[2].value) is int


def test_load_real_file():
    entries, sha = load_curated(CURATED)
    assert sha == hashlib.sha256(CURATED.read_bytes()).hexdigest()
    assert [e.input for e in entries] == [
        "battery_capex_usd_per_kwh", "battery_power_capex_usd_per_kw", "battery_om_usd_per_kwh_yr",
        "battery_life_yr", "battery_round_trip_eff_frac", "discount_rate_frac", "fuel_price_usd_per_l"]
    assert all(e.label == "docs" for e in entries)
    vals = {e.input: e.value for e in entries}
    assert vals["battery_capex_usd_per_kwh"] == 390.0 and vals["battery_power_capex_usd_per_kw"] == 330.0
    assert vals["battery_om_usd_per_kwh_yr"] == 4.48 and vals["battery_life_yr"] == 15
    assert type(vals["battery_life_yr"]) is int
    assert vals["discount_rate_frac"] == pytest.approx((1 + 0.094) / (1 + 0.025) - 1, abs=5e-5)
    assert vals["fuel_price_usd_per_l"] == 1.26


def _bad_entry(**changes):
    return [entry_dict(**changes)]


BAD_DOCS = [
    ("schema", lambda p: write_doc(p, schema="autosolar.curated/2")),
    ("extra top key", lambda p: write_doc(p, extra=1)),
    ("missing note", lambda p: p.write_text(json.dumps({"schema": "autosolar.curated/1", "entries": TEST_ENTRIES}),
                                            encoding="utf-8")),
    ("top list", lambda p: p.write_text(json.dumps([TEST_ENTRIES]), encoding="utf-8")),
    ("entries empty", lambda p: write_doc(p, entries=[])),
    ("entries dict", lambda p: write_doc(p, entries={"a": 1})),
    ("entry not dict", lambda p: write_doc(p, entries=[1])),
    ("entry extra key", lambda p: write_doc(p, entries=[dict(entry_dict(), more=1)])),
    ("entry missing key", lambda p: write_doc(p, entries=[{k: v for k, v in entry_dict().items() if k != "doi"}])),
    ("input name", lambda p: write_doc(p, entries=_bad_entry(input="Fuel-price"))),
    ("input not str", lambda p: write_doc(p, entries=_bad_entry(input=5))),
    ("duplicate input", lambda p: write_doc(p, entries=[entry_dict(), entry_dict()])),
    ("value bool", lambda p: write_doc(p, entries=_bad_entry(value=True))),
    ("value zero", lambda p: write_doc(p, entries=_bad_entry(value=0))),
    ("value negative", lambda p: write_doc(p, entries=_bad_entry(value=-1.0))),
    ("value nan", lambda p: write_doc(p, entries=_bad_entry(value=math.nan))),
    ("value inf", lambda p: write_doc(p, entries=_bad_entry(value=math.inf))),
    ("value str", lambda p: write_doc(p, entries=_bad_entry(value="1.2"))),
    ("unit empty", lambda p: write_doc(p, entries=_bad_entry(unit=""))),
    ("unit not ascii", lambda p: write_doc(p, entries=_bad_entry(unit="USD/\u2113"))),
    ("label assumed", lambda p: write_doc(p, entries=_bad_entry(label="assumed"))),
    ("label press", lambda p: write_doc(p, entries=_bad_entry(label="press"))),
    ("title empty", lambda p: write_doc(p, entries=_bad_entry(title=""))),
    ("title not ascii", lambda p: write_doc(p, entries=_bad_entry(title="Fuel \u2013 list"))),
    ("url http", lambda p: write_doc(p, entries=_bad_entry(url="http://example.org/a"))),
    ("url not str", lambda p: write_doc(p, entries=_bad_entry(url=None))),
    ("doi empty", lambda p: write_doc(p, entries=_bad_entry(doi=""))),
    ("page zero", lambda p: write_doc(p, entries=_bad_entry(page=0))),
    ("page bool", lambda p: write_doc(p, entries=_bad_entry(page=True))),
    ("page float", lambda p: write_doc(p, entries=_bad_entry(page=2.0))),
    ("quote kind near", lambda p: write_doc(p, entries=_bad_entry(quote_kind="near"))),
    ("quote empty", lambda p: write_doc(p, entries=_bad_entry(quote=""))),
    ("quote long", lambda p: write_doc(p, entries=_bad_entry(quote="x" * 601))),
    ("quote not ascii", lambda p: write_doc(p, entries=_bad_entry(quote="Rp 21.250 \u2014 B40"))),
    ("as written bool", lambda p: write_doc(p, entries=_bad_entry(value_as_written=False))),
    ("as written str", lambda p: write_doc(p, entries=_bad_entry(value_as_written="21250"))),
    ("as written nan", lambda p: write_doc(p, entries=_bad_entry(value_as_written=math.nan))),
    ("unit as written not str", lambda p: write_doc(p, entries=_bad_entry(unit_as_written=None))),
    ("currency year low", lambda p: write_doc(p, entries=_bad_entry(currency_year=1989))),
    ("currency year high", lambda p: write_doc(p, entries=_bad_entry(currency_year=2101))),
    ("currency year bool", lambda p: write_doc(p, entries=_bad_entry(currency_year=True))),
    ("currency year float", lambda p: write_doc(p, entries=_bad_entry(currency_year=2026.0))),
    ("derivation empty", lambda p: write_doc(p, entries=_bad_entry(derivation=""))),
    ("derivation long", lambda p: write_doc(p, entries=_bad_entry(derivation="y" * 601))),
]


@pytest.mark.parametrize("name,make", BAD_DOCS, ids=[b[0] for b in BAD_DOCS])
def test_load_rejects(tmp_path, name, make):
    p = tmp_path / "bad.json"
    make(p)
    with pytest.raises(ValueError):
        load_curated(p)


def test_load_edges_allowed(tmp_path):
    e = entry_dict(quote="q" * 600, derivation="d" * 600, currency_year=1990, page=1, doi=None, value_as_written=None,
                   unit_as_written="")
    e2 = entry_dict(input="discount_rate_frac", value=0.0673, unit="frac", currency_year=2100, doi="10.1/x",
                    value_as_written=0)
    entries, _ = load_curated(write_doc(tmp_path / "ok.json", entries=[e, e2]))
    assert [x.input for x in entries] == ["fuel_price_usd_per_l", "discount_rate_frac"]


# ---------- apply_curated ----------

def _targets():
    targets, _fx = load_targets(TARGETS)
    return targets


def test_apply_rows_inputs_and_replaced(base):
    raw0, rows0 = copy.deepcopy(base["raw"]), copy.deepcopy(base["rows"])
    new_raw, new_rows, replaced = apply_curated(base["raw"], base["rows"], entries_of(TEST_ENTRIES), _targets())
    assert base["raw"] == raw0 and base["rows"] == rows0
    assert [r.input for r in new_rows] == ["pv_capex_usd_per_kwp", "fuel_price_usd_per_l", "discount_rate_frac",
                                           "battery_capex_usd_per_kwh", "battery_life_yr"]
    assert [r.status for r in new_rows] == ["checked", "curated", "curated", "curated", "curated"]
    assert new_rows[0] == base["rows"][0]
    assert replaced == [dataclasses.asdict(r) for r in base["rows"][1:]]
    e = CuratedEntry(**TEST_ENTRIES[1])
    assert new_rows[3] == SourcingRow("battery_capex_usd_per_kwh", "curated", "docs", 390.0, "USD/kWh", 0.39,
                                      "MUSD/MWh", 2022, "Catalogue", CAT_URL, None, None, 266, "table", e.quote,
                                      None, CURATED_JUDGE, [], 0.0)
    assert new_raw["values"]["battery_capex_usd_per_kwh"] == {"value": 390.0, "unit": "USD/kWh", "label": "docs",
                                                              "note": curated_note(e)}
    life = new_raw["values"]["battery_life_yr"]
    assert life["value"] == 15 and type(life["value"]) is int and life["label"] == "docs"
    assert new_rows[2].doi == "10.1000/xyz" and new_rows[2].page is None and new_rows[2].supports is None
    untouched = [k for k in base["raw"]["values"] if k not in {x["input"] for x in TEST_ENTRIES}]
    assert untouched and all(new_raw["values"][k] == base["raw"]["values"][k] for k in untouched)
    assert {k: v for k, v in new_raw.items() if k != "values"} == {k: v for k, v in base["raw"].items() if k != "values"}
    assert g6_check(new_rows, new_raw) == (True, "1 of 5 sourced inputs checked, 0 kept assumed, 4 curated post hoc")


def test_apply_float_input_given_int_stored_as_float(base):
    new_raw, new_rows, _ = apply_curated(base["raw"], base["rows"], entries_of([entry_dict(value=1)]), _targets())
    v = new_raw["values"]["fuel_price_usd_per_l"]["value"]
    assert v == 1.0 and type(v) is float and new_rows[1].value_used == 1.0
    assert g6_check(new_rows, new_raw)[0] is True


def test_apply_band_ends_allowed(base):
    for v in (0.3, 2.5):
        new_raw, _, _ = apply_curated(base["raw"], base["rows"], entries_of([entry_dict(value=v)]), _targets())
        assert new_raw["values"]["fuel_price_usd_per_l"]["value"] == v


APPLY_BAD = [
    ("unknown input", entry_dict(input="no_such_input_x")),
    ("unit mismatch", entry_dict(unit="USD/gal")),
    ("int input given float", entry_dict(input="battery_life_yr", value=15.0, unit="yr")),
    ("above band", entry_dict(value=2.6)),
    ("below band", entry_dict(value=0.29)),
]


@pytest.mark.parametrize("name,e", APPLY_BAD, ids=[a[0] for a in APPLY_BAD])
def test_apply_rejects(base, name, e):
    with pytest.raises(ValueError):
        apply_curated(base["raw"], base["rows"], entries_of([e]), _targets())


def test_apply_without_target_no_band(base):
    e = entry_dict(input="battery_power_capex_usd_per_kw", value=5000.0, unit="USD/kW")
    new_raw, new_rows, replaced = apply_curated(base["raw"], base["rows"], entries_of([e]), _targets())
    assert new_raw["values"]["battery_power_capex_usd_per_kw"]["value"] == 5000.0
    assert new_rows[-1].input == "battery_power_capex_usd_per_kw" and replaced == []


def test_apply_duplicate_base_rows(base):
    rows = list(base["rows"]) + [dataclasses.replace(base["rows"][1])]
    new_raw, new_rows, replaced = apply_curated(base["raw"], rows, entries_of([entry_dict()]), _targets())
    assert [r.input for r in new_rows].count("fuel_price_usd_per_l") == 1
    assert new_rows[1].status == "curated"
    assert replaced == [dataclasses.asdict(rows[1]), dataclasses.asdict(rows[-1])]


def test_apply_real_file_on_default_inputs():
    raw = json.loads(ts.DEFAULT_INPUTS.read_text(encoding="utf-8"))
    entries, _ = load_curated(CURATED)
    new_raw, new_rows, replaced = apply_curated(raw, [], entries, _targets())
    assert replaced == [] and [r.input for r in new_rows] == [e.input for e in entries]
    assert g6_check(new_rows, new_raw) == (True, "0 of 7 sourced inputs checked, 0 kept assumed, 7 curated post hoc")
    for e in entries:
        assert new_raw["values"][e.input]["note"].startswith(CURATED_PREFIX)
        new_raw["values"][e.input]["note"].encode("ascii")


# ---------- g6_check ----------

def _good(base):
    new_raw, new_rows, _ = apply_curated(base["raw"], base["rows"], entries_of(TEST_ENTRIES), _targets())
    return new_raw, new_rows


def test_g6_unchanged_without_curated(base):
    assert g6_check(base["rows"], base["raw"]) == (True, "2 of 4 sourced inputs checked, 2 kept assumed")


ROW_BAD = [
    ("reasons", lambda r, raw: dataclasses.replace(r, reasons=["x"])),
    ("supports true", lambda r, raw: dataclasses.replace(r, supports=True)),
    ("quote near", lambda r, raw: dataclasses.replace(r, quote_kind="near")),
    ("value", lambda r, raw: dataclasses.replace(r, value_used=391.0)),
    ("unit", lambda r, raw: dataclasses.replace(r, unit="USD/MWh")),
    ("row label", lambda r, raw: dataclasses.replace(r, label="paper")),
    ("judge", lambda r, raw: dataclasses.replace(r, judge_name="opencode-go/x")),
    ("title", lambda r, raw: dataclasses.replace(r, title="Other title")),
    ("url", lambda r, raw: dataclasses.replace(r, url="https://example.org/other.pdf")),
]


@pytest.mark.parametrize("name,mut", ROW_BAD, ids=[x[0] for x in ROW_BAD])
def test_g6_curated_row_mismatch(base, name, mut):
    raw, rows = _good(base)
    rows[3] = mut(rows[3], raw)
    assert g6_check(rows, raw) == (False, "battery_capex_usd_per_kwh: curated row does not match its input")


ENTRY_BAD = [
    ("both labels assumed", "label", "assumed"),
    ("entry label", "label", "paper"),
    ("entry value", "value", 391.0),
    ("entry unit", "unit", "USD/MWh"),
    ("note checked prefix", "note", CHECKED_PREFIX + "x"),
    ("note none", "note", None),
]


@pytest.mark.parametrize("name,key,val", ENTRY_BAD, ids=[x[0] for x in ENTRY_BAD])
def test_g6_curated_entry_mismatch(base, name, key, val):
    raw, rows = _good(base)
    raw["values"]["battery_capex_usd_per_kwh"][key] = val
    if name == "both labels assumed":
        rows[3] = dataclasses.replace(rows[3], label="assumed")
    assert g6_check(rows, raw) == (False, "battery_capex_usd_per_kwh: curated row does not match its input")


def test_g6_curated_entry_not_dict(base):
    raw, rows = _good(base)
    raw["values"]["battery_capex_usd_per_kwh"] = 390.0
    assert g6_check(rows, raw) == (False, "battery_capex_usd_per_kwh: curated row does not match its input")


def test_g6_curated_note_without_row(base):
    raw, rows = _good(base)
    rows = [r for r in rows if r.input != "battery_life_yr"]
    assert g6_check(rows, raw) == (False, "battery_life_yr: curated note without a sourcing row")


def test_g6_assumed_row_with_curated_note(base):
    raw = copy.deepcopy(base["raw"])
    raw["values"]["discount_rate_frac"]["note"] = CURATED_PREFIX + "x"
    assert g6_check(base["rows"], raw) == (False, "discount_rate_frac: assumed row does not match its input")


def test_read_sourcing_refuses_tampered_curated(base, tmp_path):
    raw, rows = _good(base)
    raw["values"]["fuel_price_usd_per_l"]["value"] = 1.3
    p = tmp_path / "s.json"
    write_sourcing(p, raw, rows, {"run_id": "x"})
    with pytest.raises(ValueError, match="fails G6"):
        read_sourcing(p)


# ---------- curate_run ----------

def test_curate_run_files_and_meta(curated, base):
    folder = curated["folder"]
    assert folder == curated["tmp"] / "runs" / "curated-test"
    assert curated["base_same"]
    raw, rows, meta = curated["raw"], curated["rows"], curated["meta"]
    want_raw, want_rows, replaced = apply_curated(base["raw"], base["rows"], entries_of(TEST_ENTRIES), _targets())
    assert raw == want_raw and rows == want_rows
    assert (folder / "inputs.json").read_text(encoding="utf-8") == json.dumps(want_raw, indent=1,
                                                                               ensure_ascii=True) + "\n"
    assert set(meta) == {"run_id", "post_hoc", "curated_from", "curated_file", "curated_sha256", "curated_inputs",
                         "replaced_rows", "judge", "fx_idr_per_usd", "base_meta"}
    assert meta["run_id"] == "curated-test" and meta["post_hoc"] is True
    assert meta["curated_from"] == str(base["spath"]) and meta["curated_file"] == str(curated["cpath"])
    assert meta["curated_sha256"] == hashlib.sha256(curated["cpath"].read_bytes()).hexdigest()
    assert meta["curated_inputs"] == [e["input"] for e in TEST_ENTRIES]
    assert meta["replaced_rows"] == replaced
    assert meta["judge"] == tss.JUDGE and meta["fx_idr_per_usd"] is None and meta["base_meta"] == base["meta"]


def test_curate_run_refuses_existing_folder(curated, base):
    with pytest.raises(ValueError):
        curate_run(base["spath"], curated["cpath"], TARGETS, curated["tmp"] / "runs", "curated-test")


def test_curate_run_fx_and_judge_from_base_meta(base, tmp_path):
    raw, rows, _ = read_sourcing(base["spath"])
    spath = tmp_path / "base.json"
    write_sourcing(spath, raw, rows, {"run_id": "b", "judge": 7, "fx_idr_per_usd": 16500.0})
    folder = curate_run(spath, write_doc(tmp_path / "c.json"), TARGETS, tmp_path / "runs", "r1")
    meta = read_sourcing(folder / "sourcing.json")[2]
    assert meta["judge"] is None and meta["fx_idr_per_usd"] == 16500.0


def test_curate_run_rereads_with_g6(base, tmp_path, monkeypatch):
    import autosolar.curate as cur
    real = cur.apply_curated

    def tampered(*args):
        new_raw, new_rows, replaced = real(*args)
        new_raw["values"]["fuel_price_usd_per_l"]["value"] = 1.3
        return new_raw, new_rows, replaced

    monkeypatch.setattr(cur, "apply_curated", tampered)
    with pytest.raises(ValueError, match="fails G6"):
        cur.curate_run(base["spath"], write_doc(tmp_path / "c.json"), TARGETS, tmp_path / "runs", "r3")


def test_curate_run_bad_curated_file_writes_nothing(base, tmp_path):
    bad = write_doc(tmp_path / "bad.json", entries=_bad_entry(value=9.9))
    with pytest.raises(ValueError):
        curate_run(base["spath"], bad, TARGETS, tmp_path / "runs", "r2")
    assert not (tmp_path / "runs" / "r2" / "sourcing.json").exists()


# ---------- study and site ----------

def _intro(n_checked, n_rows):
    return (str(n_checked) + " of " + str(n_rows) + " inputs were sourced by web search and checked: the quote was "
            "found in the fetched source, the value appears in the quote, the DOI resolves when one is given, and the "
            "support judge (" + tss.JUDGE + ") agreed. The others keep their assumed value; the last column says why.")


HEADER = ("| Input | Status | Value used | Unit | Label | As written | Source | URL | Page | Quote match | Why kept "
          "assumed |\n|---|---|---|---|---|---|---|---|---|---|---|\n")


def test_study_rows_cells(curated):
    rows = curated["out"].report["sourcing"]["rows"]
    assert [r["status"] for r in rows] == ["checked", "curated", "curated", "curated", "curated"]
    batt = rows[3]
    assert batt["cells"] == ["battery_capex_usd_per_kwh", "curated", "390.0", "USD/kWh", "docs", "0.39 MUSD/MWh",
                             "Catalogue", CAT_URL, "266", "table", "none"]
    life = rows[4]
    assert life["cells"][:3] == ["battery_life_yr", "curated", "15"]
    assert curated["out"].report["sourcing"]["meta"]["post_hoc"] is True


def test_study_sources(curated):
    src = curated["out"].report["sources"]
    plain = curated["plain"].report["sources"]
    pv = [s for s in src if s.startswith("Sourced input pv_capex_usd_per_kwp: ")]
    assert len(pv) == 1
    assert src == plain + pv + [
        "Curated input (post hoc) fuel_price_usd_per_l: Fuel list, " + FUEL2_URL,
        "Curated input (post hoc) discount_rate_frac: High cost of capital, " + tss.WACC_URL + ", doi:10.1000/xyz",
        "Curated input (post hoc) battery_capex_usd_per_kwh: Catalogue, " + CAT_URL + ", page 266",
        "Curated input (post hoc) battery_life_yr: Catalogue, " + CAT_URL + ", page 266",
    ]


def test_study_markdown_block(curated):
    out = curated["out"]
    md = out.markdown
    block = md[md.index("## Sourced inputs\n"):md.index("## Sources\n")]
    assert block.startswith("## Sourced inputs\n\n" + _intro(1, 5) + "\n\n" + curated_line(4, 5) + "\n\n" + HEADER)
    for x in out.report["sourcing"]["rows"]:
        assert ("| " + " | ".join(x["cells"]) + " |\n") in block
    assert render_markdown(out.report) == md
    md.encode("ascii")


def test_study_markdown_unchanged_without_curated(tmp_path):
    base_path, ipath, spath, raw, rows, meta = tss.make_sourcing(tmp_path)
    out = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                    inputs_path=ipath, runs_dir=tmp_path / "runs", run_id="t", sourcing_path=spath)
    block = out.markdown[out.markdown.index("## Sourced inputs\n"):]
    assert block.startswith("## Sourced inputs\n\n" + _intro(2, 4) + "\n\n" + HEADER)
    assert "post hoc" not in out.markdown
    table = pd.read_csv(out.run_dir / "design_table.csv")
    assert '<p class="posthoc">' not in render_study_html(out.report, table)


def test_site_posthoc_paragraph(curated):
    out = curated["out"]
    table = pd.read_csv(out.run_dir / "design_table.csv")
    page = render_study_html(out.report, table)
    para = '<p class="posthoc">' + esc(curated_line(4, 5)) + "</p>"
    assert page.count(para) == 1
    assert page.index('<section id="inputs">') < page.index(para) < page.index("Why kept assumed")
    assert page.count('<p class="posthoc">') == 1


def test_run_hash_differs_from_base(curated, base, tmp_path):
    ipath = tmp_path / "in.json"
    ipath.write_text(json.dumps(base["raw"]), encoding="utf-8")
    out_base = run_study(ts.QUESTION, client=ts.FakeClient(), http_get=ts.FakeGet(), weather_fn=ts.WeatherFn(),
                         inputs_path=ipath, runs_dir=tmp_path / "runs", run_id="t", sourcing_path=base["spath"])
    assert len(out_base.run_hash) == 16 and out_base.run_hash != curated["out"].run_hash
