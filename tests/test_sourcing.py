"""Acceptance tests for T10b (autosolar/sourcing.py). Written by the orchestrator. No network."""
import copy
import dataclasses
import json
import pathlib

import pytest
import requests

from autosolar.cite_check import USER_AGENT, Claim
from autosolar.ledger import BudgetExceeded
from autosolar.sourcing import (
    CHECKED_PREFIX,
    GLIMMER_URL,
    SEARCH_ESTIMATE_USD,
    SEARCH_INSTRUCTIONS,
    SOURCING_SCHEMA,
    TARGET_UNITS,
    TARGETS_SCHEMA,
    SourcingRow,
    Target,
    ascii_text,
    g6_check,
    glimmer_judge,
    load_targets,
    parse_answer,
    read_sourcing,
    search_claim,
    source_inputs,
    write_sourcing,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE_RAW = json.loads((ROOT / "config" / "default_inputs.json").read_text(encoding="utf-8"))

EXPECTED_INSTRUCTIONS = (
    "You find one published number for an energy model input. Use web search. Prefer reports from IRENA, IEA, "
    "NREL, ADB, World Bank, IESR, government sources or peer-reviewed papers, published in 2021 or later. Prefer "
    "open access sources.\n"
    "Return only one JSON object, no prose, no code fence, with keys:\n"
    '  "value": the number as written in the source (number),\n'
    '  "unit": the unit as written in the source, including what it is per (for example USD/kWh/yr or IDR/L), '
    'never a bare currency (string),\n'
    '  "currency_year": the year the money is expressed in, or null (integer or null),\n'
    '  "url": the page or PDF where the number appears (string),\n'
    '  "doi": the DOI if the source has one, else null,\n'
    '  "title": the source title (string),\n'
    '  "quote": one sentence or table row copied exactly from the source that contains the number (string).\n'
    "If you cannot find a source, return {\"value\": null, \"reason\": \"...\"}."
)
JUDGE = "muse-glimmer (local)"


# ---------------------------------------------------------------- fakes

def make_pdf(page_lines):
    """Minimal valid PDF, one list of text lines per page, Helvetica, uncompressed."""
    n = len(page_lines)
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>"}
    kids = " ".join("%d 0 R" % (4 + 2 * i) for i in range(n))
    objs[2] = ("<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n)).encode("ascii")
    objs[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    for i, lines in enumerate(page_lines):
        ops = ["BT", "/F1 10 Tf", "14 TL", "50 750 Td"]
        for line in lines:
            esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            ops.append("(%s) Tj T*" % esc)
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        objs[4 + 2 * i] = ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R"
                           " >> >> /Contents %d 0 R >>" % (5 + 2 * i)).encode("ascii")
        objs[5 + 2 * i] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for k in sorted(objs):
        offsets[k] = len(out)
        out += b"%d 0 obj\n" % k + objs[k] + b"\nendobj\n"
    xref = len(out)
    size = max(objs) + 1
    out += b"xref\n0 %d\n" % size + b"0000000000 65535 f \n"
    for k in range(1, size):
        out += b"%010d 00000 n \n" % offsets[k]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref)
    return bytes(out)


class FakeResult:
    def __init__(self, text, cost_usd=0.03):
        self.text = text
        self.cost_usd = cost_usd


class FakeClient:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def respond(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Resp:
    def __init__(self, status, content=b"", url=None, payload=None):
        self.status_code = status
        self.content = content
        self.url = url
        self.headers = {}
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeGet:
    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        item = self.table.get(url)
        if item is None:
            return Resp(404, b"{}")
        return item


class Judge:
    """Says no when the prompt mentions any word in `no_words`, else yes."""

    def __init__(self, no_words=()):
        self.no_words = no_words
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if any(w in prompt for w in self.no_words):
            return '{"supports": false, "reason": "The quote gives a nominal rate."}'
        return '{"supports": true, "reason": "The quote states the value."}'


PV_URL = "https://www.frontiersin.org/articles/10.3389/fsuep.2024.1308441/full"
PV_DOI = "10.3389/fsuep.2024.1308441"
PV_HTML = ("<html><body><p>The unsubsidised initial CAPEX in 2022 value is set at 1,119 USD/kW (IEA, 2020 ). The "
           "utilization of single cost values is a simplification.</p></body></html>").encode("utf-8")
PV_QUOTE = ("The unsubsidised initial CAPEX in 2022 value is set at 1,119 USD/kW (IEA, ). The utilization of single "
            "cost values is a simplification.")
BAT_URL = "https://www.irena.org/files/costs.pdf"
BAT_PDF = make_pdf([["Renewable power generation costs", "Executive summary"],
                    ["Battery storage costs declined by 93% from 2010 to 2024,",
                     "falling from USD 2 571/kWh to USD 192/kWh."]])
BAT_QUOTE = "Battery storage costs declined by 93% from 2010 to 2024, falling from USD 2 571/kWh to USD 192/kWh."
FUEL_URL = "https://openknowledge.worldbank.org/fuel.html"
FUEL_HTML = b"<p>Table 3. Diesel 6,800 11,420 9,110 67.9 retail prices per litre</p>"
FUEL_QUOTE = "Diesel 6,800 11,420 9,110 67.9 retail prices"
WACC_URL = "https://www.iea.org/commentaries/cost-of-capital"
WACC_HTML = ("<p>The median weighted average cost of capital (WACC, nominal, post-tax and in local currency) for solar "
             "PV in Indonesia was 9.4% in 2024.</p>").encode("utf-8")
WACC_QUOTE = ("The median weighted average cost of capital (WACC, nominal, post-tax and in local currency) for solar "
              "PV in Indonesia was 9.4% in 2024.")

TABLE = {PV_URL: Resp(200, PV_HTML), BAT_URL: Resp(200, BAT_PDF), FUEL_URL: Resp(200, FUEL_HTML),
         WACC_URL: Resp(200, WACC_HTML),
         "https://doi.org/api/handles/" + PV_DOI: Resp(200, json.dumps({"responseCode": 1}).encode("utf-8"))}

T_PV = Target("pv_capex_usd_per_kwp", "USD/kWp", 300.0, 4000.0, "installed cost of utility PV in Indonesia",
              "installed cost of PV in Indonesia")
T_BAT = Target("battery_capex_usd_per_kwh", "USD/kWh", 50.0, 1500.0, "installed cost of battery storage per kWh",
               "battery storage cost per kWh")
T_FUEL = Target("fuel_price_usd_per_l", "USD/L", 0.3, 2.5, "industrial diesel price in Indonesia",
                "industrial diesel price in Indonesia")
T_WACC = Target("discount_rate_frac", "frac", 0.02, 0.25, "real discount rate for PV in Indonesia",
                "real discount rate for PV in Indonesia")


ANSWERS = [
    FakeResult(json.dumps({"value": 1119, "unit": "USD/kW", "currency_year": 2022, "url": PV_URL, "doi": PV_DOI,
                           "title": "A comparative assessment of policy induced diffusion pathways",
                           "quote": PV_QUOTE}), 0.031),
    FakeResult("```json\n" + json.dumps({"value": 192, "unit": "USD/kWh", "currency_year": 2024, "url": BAT_URL,
                                         "doi": None, "title": "Renewable power generation costs in 2024",
                                         "quote": BAT_QUOTE}) + "\n```", 0.026),
    FakeResult(json.dumps({"value": 11420, "unit": "Rp/liter", "currency_year": 2023, "url": FUEL_URL, "doi": "",
                           "title": "Indonesia\u2019s Fuel Subsidies Reforms", "quote": FUEL_QUOTE}), 0.067),
    FakeResult(json.dumps({"value": 9.4, "unit": "%", "currency_year": None, "url": WACC_URL, "doi": None,
                           "title": "High cost of capital", "quote": WACC_QUOTE}), 0.018),
]


def run_four(no_words=("real discount rate",)):
    client = FakeClient(copy.deepcopy(ANSWERS))
    judge = Judge(no_words)
    raw, rows = source_inputs(BASE_RAW, [T_PV, T_BAT, T_FUEL, T_WACC], client=client, run_id="run1",
                              http_get=FakeGet(TABLE), judge_fn=judge, judge_name=JUDGE, fx_idr_per_usd=16500.0)
    return raw, rows, client, judge


# ---------------------------------------------------------------- constants, types, helpers

def test_constants():
    assert SOURCING_SCHEMA == "autosolar.sourcing/1" and TARGETS_SCHEMA == "autosolar.sourcing_targets/1"
    assert TARGET_UNITS == ("USD/kWp", "USD/kW", "USD/kWh", "USD/kWp/yr", "USD/kWh/yr", "USD/L", "frac")
    assert SEARCH_ESTIMATE_USD == 0.10 and GLIMMER_URL == "http://127.0.0.1:8093/v1/chat/completions"
    assert CHECKED_PREFIX == "S3 checked: "
    assert SEARCH_INSTRUCTIONS == EXPECTED_INSTRUCTIONS


def test_dataclass_fields():
    assert [f.name for f in dataclasses.fields(Target)] == ["input", "target_unit", "band_lo", "band_hi",
                                                            "description", "search_brief"]
    assert [f.name for f in dataclasses.fields(SourcingRow)] == [
        "input", "status", "label", "value_used", "unit", "value_as_written", "unit_as_written", "currency_year",
        "title", "url", "doi", "doi_ok", "page", "quote_kind", "quote", "supports", "judge_name", "reasons",
        "search_cost_usd"]


def test_ascii_text():
    assert ascii_text("  Indonesia\u2019s \u201cB40\u201d\u00a0fuel \u2013 caf\u00e9  ") == 'Indonesia\'s "B40" fuel - cafe'
    assert ascii_text("a\n\n b") == "a b"


def test_parse_answer():
    assert parse_answer('{"value": 1}') == {"value": 1}
    assert parse_answer("```json\n{\"value\": 2}\n```") == {"value": 2}
    assert parse_answer('Here it is: {"value": 3} done') == {"value": 3}
    assert parse_answer("[1, 2]") is None and parse_answer("nothing") is None


# ---------------------------------------------------------------- targets file

def test_real_targets_file_matches_default_inputs():
    targets, fx = load_targets(ROOT / "config" / "sourcing_targets.json")
    assert fx > 0 and len(targets) >= 4
    for t in targets:
        entry = BASE_RAW["values"][t.input]
        assert entry["unit"] == t.target_unit and entry["label"] == "assumed"
        assert t.band_lo <= entry["value"] <= t.band_hi


def good_targets():
    return {"schema": TARGETS_SCHEMA, "note": "n", "fx_idr_per_usd": {"value": 16500, "label": "assumed", "note": ""},
            "targets": [{"input": "fuel_price_usd_per_l", "target_unit": "USD/L", "band_lo": 0.3, "band_hi": 2,
                         "description": "diesel price", "search_brief": "diesel price in Indonesia"}]}


def test_load_targets_ok(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(good_targets()), encoding="utf-8")
    targets, fx = load_targets(p)
    assert targets == [Target("fuel_price_usd_per_l", "USD/L", 0.3, 2.0, "diesel price", "diesel price in Indonesia")]
    assert isinstance(targets[0].band_hi, float) and fx == 16500.0 and isinstance(fx, float)


def _mut(fn):
    d = good_targets()
    fn(d)
    return d


@pytest.mark.parametrize("doc", [
    _mut(lambda d: d.update(schema="autosolar.sourcing_targets/2")),
    _mut(lambda d: d.update(extra=1)),
    _mut(lambda d: d.pop("note")),
    _mut(lambda d: d["fx_idr_per_usd"].update(label="docs")),
    _mut(lambda d: d["fx_idr_per_usd"].update(value=0)),
    _mut(lambda d: d["fx_idr_per_usd"].update(value=True)),
    _mut(lambda d: d.update(targets=[])),
    _mut(lambda d: d["targets"][0].update(band_lo=2.0)),
    _mut(lambda d: d["targets"][0].update(band_hi=False)),
    _mut(lambda d: d["targets"][0].update(target_unit="USD/MWh")),
    _mut(lambda d: d["targets"][0].update(description="")),
    _mut(lambda d: d["targets"][0].update(description="caf\u00e9 price")),
    _mut(lambda d: d["targets"][0].pop("search_brief")),
    _mut(lambda d: d["targets"].append(dict(d["targets"][0]))),
])
def test_load_targets_rejects(tmp_path, doc):
    p = tmp_path / "t.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError):
        load_targets(p)


# ---------------------------------------------------------------- search_claim

def test_search_claim_call_and_claim():
    client = FakeClient([FakeResult(json.dumps({"value": 11420, "unit": " Rp/liter ", "currency_year": 2023,
                                                "url": " " + FUEL_URL + " ", "doi": "", "quote": FUEL_QUOTE}),
                                    0.067)])
    claim, reason, cost = search_claim(client, "run7", T_FUEL)
    assert reason == "" and cost == pytest.approx(0.067)
    assert claim == Claim("fuel_price_usd_per_l", "industrial diesel price in Indonesia", 11420, "Rp/liter",
                          FUEL_URL, None, FUEL_QUOTE, "", 2023)
    args, kwargs = client.calls[0]
    assert args == ("run7", "S3_search", [
        {"role": "system", "content": EXPECTED_INSTRUCTIONS},
        {"role": "user", "content": "Input: fuel_price_usd_per_l (USD/L). Find: industrial diesel price in "
                                    "Indonesia."}])
    assert kwargs == {"estimate_usd": 0.10, "tools": [{"type": "web_search"}],
                      "include": ["web_search_call.results"]}


BASE_ANSWER = {"value": 9.4, "unit": "%", "currency_year": None, "url": WACC_URL, "doi": None, "title": "t",
               "quote": WACC_QUOTE}


def _ans(**kw):
    d = dict(BASE_ANSWER)
    for k, v in kw.items():
        if v is KeyError:
            d.pop(k)
        else:
            d[k] = v
    return json.dumps(d)


@pytest.mark.parametrize("text,reason", [
    ("I could not find it.", "search answer not JSON"),
    ('{"value": null, "reason": "No source gives an industrial price \u2013 sorry"}',
     "no source found: No source gives an industrial price - sorry"),
    ('{"value": null}', "no source found: "),
    (_ans(value="9.4"), "search answer field value invalid"),
    (_ans(value=True), "search answer field value invalid"),
    ('{"value": NaN, "unit": "%", "url": "https://x.org/a", "quote": "q"}', "search answer field value invalid"),
    (_ans(unit=""), "search answer field unit invalid"),
    (_ans(url=KeyError), "search answer field url invalid"),
    (_ans(quote="   "), "search answer field quote invalid"),
    (_ans(unit=5, url=None), "search answer field unit invalid"),
    (_ans(doi=5), "search answer field doi invalid"),
    (_ans(currency_year="2024"), "search answer field currency_year invalid"),
    (_ans(currency_year=True), "search answer field currency_year invalid"),
])
def test_search_claim_reasons(text, reason):
    claim, got, cost = search_claim(FakeClient([FakeResult(text, 0.02)]), "r", T_WACC)
    assert claim is None and got == reason and cost == pytest.approx(0.02)


def test_search_claim_title_missing_and_doi_kept():
    claim, reason, _ = search_claim(FakeClient([FakeResult(_ans(title=KeyError, doi=" " + PV_DOI + " "))]), "r",
                                    T_WACC)
    assert reason == "" and claim.title == "" and claim.doi == PV_DOI and claim.currency_year is None


def test_search_claim_errors():
    claim, reason, cost = search_claim(FakeClient([RuntimeError("HTTP 500")]), "r", T_WACC)
    assert (claim, reason, cost) == (None, "search error: RuntimeError", 0.0)
    with pytest.raises(BudgetExceeded):
        search_claim(FakeClient([BudgetExceeded("live run cap exceeded")]), "r", T_WACC)


# ---------------------------------------------------------------- glimmer_judge

class FakePost:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.resp


def test_glimmer_judge_body_and_content():
    post = FakePost(Resp(200, payload={"choices": [{"message": {"content": '{"supports": true}'}}]}))
    assert glimmer_judge("PROMPT", post=post, timeout_s=50.0) == '{"supports": true}'
    url, kwargs = post.calls[0]
    assert url == GLIMMER_URL and kwargs["timeout"] == 50.0
    assert kwargs["json"] == {"model": "muse-glimmer", "messages": [{"role": "user", "content": "PROMPT"}],
                              "max_tokens": 8192, "temperature": 1.0, "top_p": 0.95, "top_k": 64,
                              "chat_template_kwargs": {"reasoning_strength": "low"}}
    assert set(kwargs) == {"json", "timeout"}


def test_glimmer_judge_errors():
    with pytest.raises(RuntimeError, match="glimmer HTTP 503"):
        glimmer_judge("P", post=FakePost(Resp(503, payload={})))
    for payload in ({"choices": []}, {"choices": [{"message": {"content": None}}]}, {}):
        with pytest.raises(RuntimeError, match="glimmer answer has no content"):
            glimmer_judge("P", post=FakePost(Resp(200, payload=payload)))
    with pytest.raises(requests.ConnectionError):
        glimmer_judge("P", post=lambda url, **kw: (_ for _ in ()).throw(requests.ConnectionError("down")))


# ---------------------------------------------------------------- source_inputs

def test_source_inputs_end_to_end():
    before = copy.deepcopy(BASE_RAW)
    raw, rows, client, judge = run_four()
    assert BASE_RAW == before and raw is not BASE_RAW
    assert [r.input for r in rows] == ["pv_capex_usd_per_kwp", "battery_capex_usd_per_kwh", "fuel_price_usd_per_l",
                                       "discount_rate_frac"]
    assert [r.status for r in rows] == ["checked", "checked", "checked", "assumed"]
    assert len(client.calls) == 4 and len(judge.prompts) == 4
    v = raw["values"]
    assert v["pv_capex_usd_per_kwp"] == {
        "value": 1119.0, "unit": "USD/kWp", "label": "paper",
        "note": "S3 checked: A comparative assessment of policy induced diffusion pathways; " + PV_URL
                + "; quote near; as written 1119 USD/kW; currency year 2022; support judged by " + JUDGE}
    assert v["battery_capex_usd_per_kwh"] == {
        "value": 192.0, "unit": "USD/kWh", "label": "docs",
        "note": "S3 checked: Renewable power generation costs in 2024; " + BAT_URL
                + "; page 2; quote exact; as written 192 USD/kWh; currency year 2024; support judged by " + JUDGE}
    assert v["fuel_price_usd_per_l"] == {
        "value": 0.692121, "unit": "USD/L", "label": "docs",
        "note": "S3 checked: Indonesia's Fuel Subsidies Reforms; " + FUEL_URL
                + "; quote exact; as written 11420 Rp/liter; currency year 2023; fx 16500 IDR per USD assumed;"
                  " support judged by " + JUDGE}
    assert v["discount_rate_frac"] == BASE_RAW["values"]["discount_rate_frac"]
    for name in BASE_RAW["values"]:
        if name not in ("pv_capex_usd_per_kwp", "battery_capex_usd_per_kwh", "fuel_price_usd_per_l"):
            assert v[name] == BASE_RAW["values"][name]
    assert raw["schema"] == BASE_RAW["schema"] and raw["note"] == BASE_RAW["note"]


def test_source_inputs_row_fields():
    raw, rows, _, _ = run_four()
    pv, bat, fuel, wacc = rows
    assert pv == SourcingRow("pv_capex_usd_per_kwp", "checked", "paper", 1119.0, "USD/kWp", 1119, "USD/kW", 2022,
                             "A comparative assessment of policy induced diffusion pathways", PV_URL, PV_DOI, True,
                             1, "near", ascii_text(PV_QUOTE), True, JUDGE, [], pytest.approx(0.031))
    assert (bat.page, bat.quote_kind, bat.doi, bat.doi_ok, bat.label) == (2, "exact", None, None, "docs")
    assert fuel.title == "Indonesia's Fuel Subsidies Reforms" and fuel.doi is None
    assert fuel.search_cost_usd == pytest.approx(0.067)
    assert wacc.status == "assumed" and wacc.label == "assumed" and wacc.value_used == 0.08
    assert wacc.unit == "frac" and wacc.value_as_written == 9.4 and wacc.unit_as_written == "%"
    assert wacc.supports is False and wacc.quote_kind == "exact" and wacc.page == 1
    assert wacc.reasons == ["judge says not supported: The quote gives a nominal rate."]
    for row in rows:
        json.dumps(dataclasses.asdict(row))


def test_source_inputs_search_failure_row():
    client = FakeClient([FakeResult('{"value": null, "reason": "none found"}', 0.011)])
    raw, rows = source_inputs(BASE_RAW, [T_FUEL], client=client, run_id="r", http_get=FakeGet({}),
                              judge_fn=Judge(), judge_name=JUDGE, fx_idr_per_usd=16500.0)
    assert raw == BASE_RAW
    assert rows == [SourcingRow("fuel_price_usd_per_l", "assumed", "assumed", 0.85, "USD/L", None, "", None, "", "",
                                None, None, None, "not run", "", None, JUDGE, ["no source found: none found"],
                                pytest.approx(0.011))]


def test_source_inputs_validates_before_any_call():
    client = FakeClient(copy.deepcopy(ANSWERS))
    bad_name = Target("pv_capex_usd_per_w", "USD/kWp", 1, 2, "d", "s")
    with pytest.raises(ValueError, match="pv_capex_usd_per_w"):
        source_inputs(BASE_RAW, [T_PV, bad_name], client=client, run_id="r", http_get=FakeGet(TABLE),
                      judge_fn=Judge(), judge_name=JUDGE, fx_idr_per_usd=16500.0)
    bad_unit = Target("pv_capex_usd_per_kwp", "USD/kW", 1, 2, "d", "s")
    with pytest.raises(ValueError, match="pv_capex_usd_per_kwp"):
        source_inputs(BASE_RAW, [bad_unit], client=client, run_id="r", http_get=FakeGet(TABLE),
                      judge_fn=Judge(), judge_name=JUDGE, fx_idr_per_usd=16500.0)
    assert client.calls == []


def test_source_inputs_budget_stop_propagates():
    client = FakeClient([ANSWERS[0], BudgetExceeded("live day cap exceeded")])
    with pytest.raises(BudgetExceeded):
        source_inputs(BASE_RAW, [T_PV, T_BAT], client=client, run_id="r", http_get=FakeGet(TABLE),
                      judge_fn=Judge(), judge_name=JUDGE, fx_idr_per_usd=16500.0)


def test_failed_check_keeps_assumed_and_skips_judge():
    bad = FakeResult(json.dumps({"value": 1119, "unit": "USD/kW", "currency_year": 2022, "url": PV_URL,
                                 "doi": "10.3389/fsuep.2024.9999999", "title": "x", "quote": PV_QUOTE}))
    judge = Judge()
    none = FakeResult('{"value": null, "reason": "none found"}', 0.02)
    raw, rows = source_inputs(BASE_RAW, [T_PV], client=FakeClient([bad, none]), run_id="r", http_get=FakeGet(TABLE),
                              judge_fn=judge, judge_name=JUDGE, fx_idr_per_usd=16500.0)
    assert rows[0].status == "assumed"
    assert rows[0].reasons == ["try 1: doi does not resolve", "try 2: no source found: none found"]
    assert rows[0].doi_ok is False and rows[0].supports is None and judge.prompts == []
    assert raw["values"]["pv_capex_usd_per_kwp"] == BASE_RAW["values"]["pv_capex_usd_per_kwp"]


# ---------------------------------------------------------------- G6

def test_g6_passes_on_real_output():
    raw, rows, _, _ = run_four()
    assert g6_check(rows, raw) == (True, "3 of 4 sourced inputs checked, 1 kept assumed")


@pytest.mark.parametrize("tamper,detail", [
    (lambda raw, rows: raw["values"]["pv_capex_usd_per_kwp"].update(value=999.0),
     "pv_capex_usd_per_kwp: checked row does not match its input"),
    (lambda raw, rows: raw["values"]["battery_capex_usd_per_kwh"].update(label="assumed"),
     "battery_capex_usd_per_kwh: checked row does not match its input"),
    (lambda raw, rows: setattr(rows[0], "supports", None),
     "pv_capex_usd_per_kwp: checked row does not match its input"),
    (lambda raw, rows: setattr(rows[1], "reasons", ["x"]),
     "battery_capex_usd_per_kwh: checked row does not match its input"),
    (lambda raw, rows: raw["values"]["discount_rate_frac"].update(value=0.094),
     "discount_rate_frac: assumed row does not match its input"),
    (lambda raw, rows: raw["values"]["discount_rate_frac"].update(note=CHECKED_PREFIX + "forged"),
     "discount_rate_frac: assumed row does not match its input"),
    (lambda raw, rows: setattr(rows[3], "reasons", []),
     "discount_rate_frac: assumed row does not match its input"),
    (lambda raw, rows: setattr(rows[2], "status", "sourced"), "fuel_price_usd_per_l: unknown status"),
    (lambda raw, rows: raw["values"]["co2_kg_per_l"].update(note=CHECKED_PREFIX + "forged", label="paper"),
     "co2_kg_per_l: checked note without a sourcing row"),
    (lambda raw, rows: raw["values"].pop("fuel_price_usd_per_l"), "fuel_price_usd_per_l: not in inputs"),
])
def test_g6_catches_tampering(tamper, detail):
    raw, rows, _, _ = run_four()
    tamper(raw, rows)
    assert g6_check(rows, raw) == (False, detail)


# ---------------------------------------------------------------- files

def test_write_read_round_trip(tmp_path):
    raw, rows, _, _ = run_four()
    path = tmp_path / "deep" / "sourcing.json"
    write_sourcing(path, raw, rows, {"run_id": "run1", "judge": JUDGE})
    text = path.read_text(encoding="utf-8")
    assert text.isascii() and json.loads(text)["schema"] == SOURCING_SCHEMA
    raw2, rows2, meta = read_sourcing(path)
    assert raw2 == raw and meta == {"run_id": "run1", "judge": JUDGE}
    assert [dataclasses.asdict(r) for r in rows2] == [dataclasses.asdict(r) for r in rows]


def test_read_sourcing_rejects(tmp_path):
    raw, rows, _, _ = run_four()
    path = tmp_path / "s.json"
    write_sourcing(path, raw, rows, {})
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["inputs"]["values"]["fuel_price_usd_per_l"]["value"] = 0.5
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="sourcing file fails G6: fuel_price_usd_per_l"):
        read_sourcing(path)
    write_sourcing(path, raw, rows, {})
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["schema"] = "autosolar.sourcing/0"
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError):
        read_sourcing(path)
    write_sourcing(path, raw, rows, {})
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["rows"][0]["extra"] = 1
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError):
        read_sourcing(path)


def test_user_agent_reused_for_fetches():
    get = FakeGet(TABLE)
    source_inputs(BASE_RAW, [T_FUEL], client=FakeClient([copy.deepcopy(ANSWERS[2])]), run_id="r", http_get=get,
                  judge_fn=Judge(), judge_name=JUDGE, fx_idr_per_usd=16500.0)
    assert get.calls == [FUEL_URL] and USER_AGENT.startswith("AutoSolarResearcher/")
