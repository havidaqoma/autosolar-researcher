"""Acceptance tests for T10d (sourcing yield: PDF pages, open copies, unit wording, one retry).
Written by the orchestrator. No network: every page, API answer and judge is a fake."""
import copy
import json

import pytest
import requests

import autosolar.cite_check as cc
from autosolar.cite_check import (
    BLOCKED_STATUS,
    EUROPE_PMC_XML_URL,
    MAX_MIRRORS,
    OPENALEX_WORK_URL,
    USER_AGENT,
    Claim,
    FetchError,
    check_citation,
    mirror_urls,
    normalise_text,
    pdf_pages,
)
from autosolar.ledger import BudgetExceeded
from autosolar.sourcing import (
    MAX_SEARCH_TRIES,
    NO_RETRY_PREFIXES,
    CHECKED_PREFIX,
    SourcingRow,
    g6_check,
    read_sourcing,
    retry_feedback,
    search_claim,
    source_inputs,
    write_sourcing,
)
from test_cite_check import (
    DOI_OK,
    YES,
    FakeGet,
    Judge,
    Resp,
    make_pdf,
)
from test_sourcing import ANSWERS, BASE_RAW, FUEL_URL, JUDGE, TABLE, T_FUEL, FakeClient, FakeResult

UA = {"User-Agent": USER_AGENT}


# ---------------------------------------------------------------- constants

def test_constants():
    assert BLOCKED_STATUS == (401, 403, 429) and MAX_MIRRORS == 4
    assert OPENALEX_WORK_URL == "https://api.openalex.org/works/doi:"
    assert EUROPE_PMC_XML_URL == "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    assert MAX_SEARCH_TRIES == 2
    assert NO_RETRY_PREFIXES == ("judge says not supported", "judge gave no verdict", "no source found")


# ---------------------------------------------------------------- 1. PDF pages

class Boom(Exception):
    pass


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


def fake_reader(pages, open_error=None, pages_error=None):
    class Reader:
        def __init__(self, stream):
            if open_error is not None:
                raise open_error

        @property
        def pages(self):
            if pages_error is not None:
                raise pages_error
            return [FakePage(t) for t in pages]
    return Reader


def test_pdf_bad_page_becomes_empty(monkeypatch):
    monkeypatch.setattr(cc, "PdfReader", fake_reader(["Hello  World", Boom("tokens"), None, "Third Page"]))
    assert pdf_pages(b"%PDF-1.4") == [normalise_text("Hello  World"), "", "", normalise_text("Third Page")]


def test_pdf_every_page_bad(monkeypatch):
    monkeypatch.setattr(cc, "PdfReader", fake_reader([ValueError("a"), Boom("b")]))
    with pytest.raises(FetchError, match="^pdf text extraction failed: Boom$"):
        pdf_pages(b"%PDF-1.4")


def test_pdf_reader_or_page_list_fails(monkeypatch):
    monkeypatch.setattr(cc, "PdfReader", fake_reader([], open_error=ValueError("x")))
    with pytest.raises(FetchError, match="^pdf text extraction failed: ValueError$"):
        pdf_pages(b"%PDF-1.4")
    monkeypatch.setattr(cc, "PdfReader", fake_reader([], pages_error=KeyError("y")))
    with pytest.raises(FetchError, match="^pdf text extraction failed: KeyError$"):
        pdf_pages(b"%PDF-1.4")


def test_pdf_no_pages_is_empty_list(monkeypatch):
    monkeypatch.setattr(cc, "PdfReader", fake_reader([]))
    assert pdf_pages(b"%PDF-1.4") == []


def test_fetch_source_reads_pdf_with_a_bad_page(monkeypatch):
    real = cc.PdfReader

    class HalfBroken(real):
        @property
        def pages(self):
            pages = list(super().pages)
            pages[0].extract_text = lambda *a, **k: (_ for _ in ()).throw(Boom("limit"))
            return pages

    monkeypatch.setattr(cc, "PdfReader", HalfBroken)
    pdf = make_pdf([["Cover page"], ["Battery packs cost USD 157/kWh in this report."]])
    src = cc.fetch_source("https://x.org/r.pdf", FakeGet({"https://x.org/r.pdf": Resp(200, pdf)}))
    assert src.is_pdf is True and src.pages[0] == "" and "usd 157/kwh" in src.pages[1]


# ---------------------------------------------------------------- 2. mirror_urls

PMC_URL = "https://pmc.ncbi.nlm.nih.gov/articles/PMC12616098/"
EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12616098/fullTextXML"
DOI = "10.3390/su15097529"
OA = OPENALEX_WORK_URL + DOI
PUB_URL = "https://www.mdpi.com/2071-1050/15/9/7529"
OA_PDF = "https://mdpi-res.com/d_attachment/sustainability/su-15-07529.pdf"


def oa(body, status=200):
    return Resp(status, json.dumps(body).encode("utf-8"))


def test_pmc_page_gives_europe_pmc_without_calls():
    get = FakeGet({})
    assert mirror_urls(PMC_URL, None, get) == [EPMC]
    assert mirror_urls("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC777/", "", get) == [
        EUROPE_PMC_XML_URL.format(pmcid="PMC777")]
    assert mirror_urls("https://europepmc.org/article/PMC/PMC55", None, get) == [
        EUROPE_PMC_XML_URL.format(pmcid="PMC55")]
    assert get.calls == []


@pytest.mark.parametrize("url,doi", [
    ("https://example.org/PMC123", None),
    ("https://www.mdpi.com/x", None),
    ("https://www.mdpi.com/x", ""),
    ("https://www.mdpi.com/x", "not a doi"),
    ("https://pmc.ncbi.nlm.nih.gov/articles/", None),
])
def test_no_copies_and_no_calls(url, doi):
    get = FakeGet({})
    assert mirror_urls(url, doi, get) == [] and get.calls == []


def test_openalex_order_dedupe_and_call():
    body = {"ids": {"pmcid": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC999"},
            "locations": [{"pdf_url": OA_PDF, "landing_page_url": PUB_URL},
                          {"pdf_url": None, "landing_page_url": "https://www.x.org/b"},
                          {"pdf_url": OA_PDF, "landing_page_url": "https://www.x.org/c"}]}
    get = FakeGet({OA: oa(body)})
    out = mirror_urls(PUB_URL, " https://doi.org/" + DOI + " ", get, timeout_s=7.0)
    assert out == [EUROPE_PMC_XML_URL.format(pmcid="PMC999"), OA_PDF, "https://www.x.org/b"] + [
        "https://www.x.org/c"]
    assert get.calls == [(OA, {"headers": UA, "timeout": 7.0})]


def test_doi_prefixes_ignore_case():
    for doi in ("DOI:" + DOI, "HTTPS://DOI.ORG/" + DOI, "https://dx.doi.org/" + DOI, "http://doi.org/" + DOI):
        get = FakeGet({OA: oa({"locations": [{"pdf_url": OA_PDF}]})})
        assert mirror_urls(PUB_URL, doi, get) == [OA_PDF], doi


def test_pmc_url_first_then_openalex_and_cap():
    locs = [{"pdf_url": "https://m.org/%d.pdf" % i, "landing_page_url": "ftp://m.org/%d" % i} for i in range(6)]
    body = {"ids": {"pmcid": "PMC12616098"}, "locations": locs}
    get = FakeGet({OA: oa(body)})
    out = mirror_urls(PMC_URL, DOI, get)
    assert out == [EPMC, "https://m.org/0.pdf", "https://m.org/1.pdf", "https://m.org/2.pdf"]
    assert len(out) == MAX_MIRRORS


def test_original_url_dropped():
    get = FakeGet({OA: oa({"locations": [{"pdf_url": PUB_URL, "landing_page_url": PUB_URL}]})})
    assert mirror_urls(PUB_URL, DOI, get) == []


@pytest.mark.parametrize("resp", [
    Resp(404, b"{}"), Resp(500, b"{}"), Resp(200, b"not json"), Resp(200, b"[1, 2]"),
    oa({"locations": "x"}), oa({"locations": [1, None, "u"]}), oa({"ids": "PMC5"}),
    oa({"ids": {"pmcid": 5}, "locations": [{"pdf_url": 7, "landing_page_url": ["u"]}]}),
    oa({"locations": [{"pdf_url": OA_PDF}]}, status=404),
    oa({"locations": [{"pdf_url": "ftp://m.org/a.pdf", "landing_page_url": "www.x.org/b"}]}),
    requests.ConnectionError("down"), requests.Timeout("slow"),
])
def test_bad_openalex_gives_nothing(resp):
    get = FakeGet({OA: resp})
    assert mirror_urls(PUB_URL, DOI, get) == [] and len(get.calls) == 1


# ---------------------------------------------------------------- 2. check_citation with copies

MDPI_QUOTE = "The minimum load ratio of the diesel generator is set to 30% of its rated power in this study."
MDPI_PDF = make_pdf([["Sustainability 2023"], [MDPI_QUOTE]])


def mdpi_claim(**kw):
    base = dict(input_name="diesel_min_load_frac", description="minimum load of diesel generators", value=30,
                unit="%", url=PUB_URL, doi=DOI, quote=MDPI_QUOTE, title="MDPI paper", currency_year=None)
    base.update(kw)
    return Claim(**base)


def run(claim, table, judge=None, **kw):
    get = FakeGet(table)
    judge = judge or Judge(YES)
    args = dict(http_get=get, judge_fn=judge, judge_name=JUDGE, target_unit="frac", band_lo=0.1, band_hi=0.6)
    args.update(kw)
    return check_citation(claim, **args), get, judge


def urls(get):
    return [c[0] for c in get.calls]


def test_blocked_source_read_from_open_copy():
    table = {PUB_URL: Resp(403, b"denied"), OA: oa({"locations": [{"pdf_url": OA_PDF, "landing_page_url": PUB_URL}]}),
             OA_PDF: Resp(200, MDPI_PDF), "https://doi.org/api/handles/" + DOI: DOI_OK}
    c, get, judge = run(mdpi_claim(), table)
    assert c.status == "checked" and c.reasons == [] and c.final_url == OA_PDF
    assert c.is_pdf is True and c.page == 2 and c.quote_kind == "exact" and c.doi_ok is True
    assert c.value_converted == pytest.approx(0.3)
    assert urls(get) == [PUB_URL, OA, OA_PDF, "https://doi.org/api/handles/" + DOI]
    assert len(judge.prompts) == 1


def test_copies_tried_in_order_until_quote_found():
    a, b, c3, d = ("https://m.org/a", "https://m.org/b", "https://m.org/c.pdf", "https://m.org/d.pdf")
    table = {PUB_URL: Resp(403), OA: oa({"locations": [{"pdf_url": a}, {"pdf_url": b}, {"pdf_url": c3},
                                                       {"pdf_url": d}]}),
             b: Resp(200, b"<p>Some other page about diesel engines and load.</p>"), c3: Resp(200, MDPI_PDF),
             d: Resp(200, MDPI_PDF), "https://doi.org/api/handles/" + DOI: DOI_OK}
    c, get, _ = run(mdpi_claim(), table)
    assert c.status == "checked" and c.final_url == c3
    assert urls(get) == [PUB_URL, OA, a, b, c3, "https://doi.org/api/handles/" + DOI]


def test_no_copy_with_quote():
    a, b = "https://m.org/a", "https://m.org/b"
    table = {PUB_URL: Resp(403), OA: oa({"locations": [{"pdf_url": a, "landing_page_url": b}]}),
             b: Resp(200, b"<p>Some other page about diesel engines and load.</p>"),
             "https://doi.org/api/handles/" + DOI: DOI_OK}
    c, get, judge = run(mdpi_claim(), table)
    assert c.status == "assumed"
    assert c.reasons == ["fetch: HTTP 403", "mirror: no open copy with the quote (2 tried)"]
    assert c.quote_kind == "not run" and c.final_url is None and c.page is None and c.is_pdf is None
    assert judge.prompts == [] and urls(get) == [PUB_URL, OA, a, b, "https://doi.org/api/handles/" + DOI]


@pytest.mark.parametrize("status", [401, 429])
def test_other_blocked_codes_use_copies(status):
    table = {PUB_URL: Resp(status), OA: oa({"locations": [{"pdf_url": OA_PDF}]}), OA_PDF: Resp(200, MDPI_PDF),
             "https://doi.org/api/handles/" + DOI: DOI_OK}
    c, _, _ = run(mdpi_claim(), table)
    assert c.status == "checked" and c.final_url == OA_PDF


@pytest.mark.parametrize("resp,reason", [(Resp(404), "fetch: HTTP 404"), (Resp(500), "fetch: HTTP 500"),
                                         (requests.Timeout("t"), "fetch: Timeout")])
def test_other_failures_try_no_copies(resp, reason):
    table = {PUB_URL: resp, "https://doi.org/api/handles/" + DOI: DOI_OK}
    c, get, _ = run(mdpi_claim(), table)
    assert c.reasons == [reason] and urls(get) == [PUB_URL, "https://doi.org/api/handles/" + DOI]


def test_blocked_without_copies_keeps_old_reason():
    c, get, _ = run(mdpi_claim(doi=None), {PUB_URL: Resp(403)})
    assert c.reasons == ["fetch: HTTP 403"] and urls(get) == [PUB_URL]


def test_pmc_page_read_from_europe_pmc_xml():
    quote = "this could ultimately translate into a 30% reduction with battery pack prices of 157 $/kWh."
    xml = ("<?xml version='1.0'?><article><body><p>Intro.</p><p>With low battery pack prices, " + quote
           + "</p></body></article>").encode("utf-8")
    claim = Claim("battery_capex_usd_per_kwh", "battery pack cost", 157, "$/kWh", PMC_URL, None, quote, "iScience",
                  2025)
    c, get, _ = run(claim, {PMC_URL: Resp(403), EPMC: Resp(200, xml)}, target_unit="USD/kWh", band_lo=50,
                    band_hi=1500)
    assert c.status == "checked" and c.final_url == EPMC and c.is_pdf is False and c.page == 1
    assert urls(get) == [PMC_URL, EPMC]


def test_copy_used_keeps_other_reasons():
    table = {PUB_URL: Resp(403), OA: oa({"locations": [{"pdf_url": OA_PDF}]}), OA_PDF: Resp(200, MDPI_PDF),
             "https://doi.org/api/handles/" + DOI: DOI_OK}
    c, _, judge = run(mdpi_claim(unit="basis points"), table)
    assert len(c.reasons) == 1 and c.reasons[0].startswith("unit: ") and c.final_url == OA_PDF
    assert judge.prompts == []


# ---------------------------------------------------------------- 3. prompt (constant pinned in test_sourcing)

def test_search_claim_feedback_appended():
    client = FakeClient([FakeResult(json.dumps(ANSWERS_FUEL), 0.05)])
    search_claim(client, "r", T_FUEL, feedback="Try again.")
    assert client.calls[0][0][2][1]["content"] == ("Input: fuel_price_usd_per_l (USD/L). Find: industrial diesel "
                                                   "price in Indonesia. Try again.")
    client = FakeClient([FakeResult(json.dumps(ANSWERS_FUEL), 0.05)])
    search_claim(client, "r", T_FUEL, feedback="")
    assert client.calls[0][0][2][1]["content"] == ("Input: fuel_price_usd_per_l (USD/L). Find: industrial diesel "
                                                   "price in Indonesia.")


# ---------------------------------------------------------------- 4. retry_feedback

@pytest.mark.parametrize("reasons", [
    [], ["judge says not supported: nominal"], ["judge gave no verdict: unparsed judge answer"],
    ["no source found: none"], ["value 5000 USD/kWh outside band [50, 1500]"],
    ["fetch: HTTP 404", "judge says not supported: x"], ["fetch: HTTP 403", "value 9 frac outside band [0, 1]"],
])
def test_retry_feedback_none(reasons):
    assert retry_feedback(reasons, "https://x.org") is None


def test_retry_feedback_text():
    assert retry_feedback(["fetch: HTTP 403"], "https://x.org/a") == (
        "A previous answer could not be used: fetch: HTTP 403. Do not use https://x.org/a. Find a different source.")
    assert retry_feedback(["unit: bad unit 'IDR'", "quote not found in source"], "") == (
        "A previous answer could not be used: unit: bad unit 'IDR'; quote not found in source. Find a different "
        "source.")
    long = retry_feedback(["x" * 400], "https://x.org/\u00e9")
    assert long == "A previous answer could not be used: " + "x" * 300 + ". Do not use https://x.org/e. Find a " \
                   "different source."
    assert retry_feedback(["search error: Timeout"], "") is not None


# ---------------------------------------------------------------- 4. source_inputs with a second try

BLOCKED_URL = "https://blocked.example/fuel"
ANSWERS_FUEL = json.loads(ANSWERS[2].text)


def ans(cost=0.04, **kw):
    d = dict(ANSWERS_FUEL)
    d.update(kw)
    return FakeResult(json.dumps(d), cost)


def run_fuel(answers, table=None, judge=None):
    client = FakeClient(answers)
    judge = judge or JudgeS()
    tbl = dict(TABLE)
    tbl[BLOCKED_URL] = Resp(403)
    tbl.update(table or {})
    raw, rows = source_inputs(BASE_RAW, [T_FUEL], client=client, run_id="r", http_get=FakeGet(tbl), judge_fn=judge,
                              judge_name=JUDGE, fx_idr_per_usd=16500.0)
    return raw, rows, client, judge


class JudgeS:
    def __init__(self):
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return '{"supports": true, "reason": "The quote states the value."}'


def user_msg(client, i):
    return client.calls[i][0][2][1]["content"]


def test_second_try_checked():
    raw, rows, client, judge = run_fuel([ans(url=BLOCKED_URL), copy.deepcopy(ANSWERS[2])])
    assert len(client.calls) == 2 and len(judge.prompts) == 1
    assert user_msg(client, 1) == (
        "Input: fuel_price_usd_per_l (USD/L). Find: industrial diesel price in Indonesia. A previous answer could not "
        "be used: fetch: HTTP 403. Do not use " + BLOCKED_URL + ". Find a different source.")
    row = rows[0]
    assert row.status == "checked" and row.reasons == [] and row.url == FUEL_URL
    assert row.search_cost_usd == pytest.approx(0.04 + 0.067)
    note = raw["values"]["fuel_price_usd_per_l"]["note"]
    assert note.startswith(CHECKED_PREFIX) and note.endswith("; support judged by " + JUDGE
                                                             + "; found on search try 2")
    assert g6_check(rows, raw) == (True, "1 of 1 sourced inputs checked, 0 kept assumed")


def test_second_try_fails_fields_from_try_2():
    raw, rows, client, _ = run_fuel([ans(url=BLOCKED_URL), ans(unit="IDR", title="Second source")])
    row = rows[0]
    assert len(client.calls) == 2 and row.status == "assumed" and row.value_used == 0.85
    assert row.reasons == ["try 1: fetch: HTTP 403", "try 2: unit: bad unit 'IDR'"]
    assert (row.unit_as_written, row.title, row.url, row.quote_kind) == ("IDR", "Second source", FUEL_URL, "exact")
    assert row.search_cost_usd == pytest.approx(0.08)
    assert raw == BASE_RAW and g6_check(rows, raw)[0] is True


def test_second_try_without_claim_keeps_try_1_fields():
    raw, rows, client, _ = run_fuel([ans(url=BLOCKED_URL, title="First"),
                                     FakeResult('{"value": null, "reason": "none found"}', 0.02)])
    row = rows[0]
    assert row.reasons == ["try 1: fetch: HTTP 403", "try 2: no source found: none found"]
    assert (row.title, row.url, row.value_as_written, row.quote_kind) == ("First", BLOCKED_URL, 11420, "not run")
    assert row.search_cost_usd == pytest.approx(0.06)


def test_two_tries_without_claim():
    raw, rows, client, _ = run_fuel([FakeResult("no json", 0.01), FakeResult("still none", 0.02)])
    assert user_msg(client, 1).endswith(" A previous answer could not be used: search answer not JSON. Find a "
                                        "different source.")
    assert rows == [SourcingRow("fuel_price_usd_per_l", "assumed", "assumed", 0.85, "USD/L", None, "", None, "", "",
                                None, None, None, "not run", "", None, JUDGE,
                                ["try 1: search answer not JSON", "try 2: search answer not JSON"],
                                pytest.approx(0.03))]


def test_no_retry_on_judge_no_or_band():
    class No(JudgeS):
        def __call__(self, prompt):
            self.prompts.append(prompt)
            return '{"supports": false, "reason": "Retail, not industrial."}'
    raw, rows, client, _ = run_fuel([copy.deepcopy(ANSWERS[2])], judge=No())
    assert len(client.calls) == 1 and rows[0].reasons == ["judge says not supported: Retail, not industrial."]
    raw, rows, client, _ = run_fuel([ans(value=99999, quote="Diesel 99,999 per litre in this special table")],
                                    table={FUEL_URL: Resp(200, b"<p>Diesel 99,999 per litre in this special table</p>")})
    assert len(client.calls) == 1 and "outside band" in rows[0].reasons[0]


def test_budget_stop_in_second_try():
    with pytest.raises(BudgetExceeded):
        run_fuel([ans(url=BLOCKED_URL), BudgetExceeded("live run cap exceeded: x")])


def test_round_trip_after_retry(tmp_path):
    raw, rows, _, _ = run_fuel([ans(url=BLOCKED_URL), copy.deepcopy(ANSWERS[2])])
    path = tmp_path / "s.json"
    write_sourcing(path, raw, rows, {"judge": JUDGE})
    raw2, rows2, _ = read_sourcing(path)
    assert raw2 == raw and rows2 == rows


def test_mirror_reaches_sourcing_row():
    pmc_quote = "Diesel 6,800 11,420 9,110 67.9 retail prices"
    xml = b"<article><p>Table 3. Diesel 6,800 11,420 9,110 67.9 retail prices per litre</p></article>"
    raw, rows, client, _ = run_fuel([ans(url=PMC_URL, quote=pmc_quote)], table={PMC_URL: Resp(403), EPMC: Resp(200, xml)})
    assert len(client.calls) == 1 and rows[0].status == "checked" and rows[0].url == EPMC
    assert EPMC in raw["values"]["fuel_price_usd_per_l"]["note"]


def test_checked_first_try_is_one_call():
    client = FakeClient([copy.deepcopy(ANSWERS[2])])
    raw, rows = source_inputs(BASE_RAW, [T_FUEL], client=client, run_id="r", http_get=FakeGet(TABLE),
                              judge_fn=JudgeS(), judge_name=JUDGE, fx_idr_per_usd=16500.0)
    assert len(client.calls) == 1 and rows[0].status == "checked"
    assert not raw["values"]["fuel_price_usd_per_l"]["note"].endswith("try 2")
