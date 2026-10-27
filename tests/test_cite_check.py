"""Acceptance tests for T10a (autosolar/cite_check.py). Written by the orchestrator. No network."""
import dataclasses
import json

import pytest
import requests

from autosolar.cite_check import (
    CONTEXT_CHARS,
    MAX_PROMPT_CONTEXT_CHARS,
    MAX_SOURCE_BYTES,
    MIN_QUOTE_CHARS,
    SUPPORT_INSTRUCTIONS,
    USER_AGENT,
    CitationCheck,
    Claim,
    FetchError,
    QuoteMatch,
    Source,
    Verdict,
    check_citation,
    convert_value,
    doi_resolves,
    fetch_source,
    find_quote,
    html_to_text,
    normalise_text,
    numbers_in,
    parse_unit,
    pdf_pages,
    support_verdict,
)


# ---------------------------------------------------------------- helpers

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


class Resp:
    def __init__(self, status, content=b"", url=None):
        self.status_code = status
        self.content = content
        self.url = url
        self.headers = {}


class FakeGet:
    """Maps URL to a Resp or an exception; records calls."""

    def __init__(self, table):
        self.table = table
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self.table.get(url)
        if item is None:
            return Resp(404, b"{}")
        if isinstance(item, Exception):
            raise item
        return item


class Judge:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if isinstance(self.text, Exception):
            raise self.text
        return self.text


IEA_URL = "https://www.iea.org/commentaries/cost-of-capital"
IEA_HTML = (
    "<html><head><title>Cost of capital</title><style>p {color: red}</style>"
    "<script>var x = 'The median weighted average cost of capital was 99.9%';</script></head><body>"
    "<p>The median weighted average cost of capital (WACC, nominal, post-tax and in local currency) for solar PV "
    "in Indonesia, Viet Nam and the Philippines based on survey responses was 9.4%, 9.0% and 8.0% respectively "
    "in 2024, while a lower range was quoted for Thailand (6.0&ndash;8.0%) and Malaysia (6.0-7.0%).</p>"
    "<p>Other text &amp; more text.</p></body></html>"
)
IEA_QUOTE = ("The median weighted average cost of capital (WACC, nominal, post-tax and in local currency) for "
             "solar PV in Indonesia, Viet Nam and the Philippines based on survey responses was 9.4%, 9.0% and "
             "8.0% respectively in 2024")

FRONT_URL = "https://www.frontiersin.org/articles/10.3389/fsuep.2024.1308441/full"
FRONT_HTML = ("<html><body><p>Section 2.3.</p><p>The unsubsidised initial CAPEX in 2022 value is set at 1,119 "
              "USD/kW (IEA, 2020 ). The utilization of single cost values is a simplification.</p></body></html>")
FRONT_QUOTE = ("The unsubsidised initial CAPEX in 2022 value is set at 1,119 USD/kW (IEA, ). The utilization of "
               "single cost values is a simplification.")
FRONT_DOI = "10.3389/fsuep.2024.1308441"

IRENA_URL = "https://www.irena.org/files/costs.pdf"
IRENA_PDF = make_pdf([
    ["Renewable power generation costs", "Executive summary"],
    ["Storage", "Battery storage costs declined by 93% from 2010 to 2024,",
     "falling from USD 2 571/kWh to USD 192/kWh."],
])
IRENA_QUOTE = ("Battery storage costs declined by 93% from 2010 to 2024, falling from USD 2 571/kWh to USD "
               "192/kWh.")

DOI_OK = Resp(200, json.dumps({"responseCode": 1, "handle": FRONT_DOI}).encode("utf-8"))
DOI_MISSING = Resp(404, json.dumps({"responseCode": 100}).encode("utf-8"))

YES = '{"supports": true, "reason": "The quote states the value for this input."}'
NO = '{"supports": false, "reason": "The number is a global average, not this input."}'


def iea_claim(**kw):
    base = dict(input_name="discount_rate_frac", description="WACC for solar PV in Indonesia", value=9.4,
                unit="%", url=IEA_URL, doi=None, quote=IEA_QUOTE, title="IEA commentary", currency_year=None)
    base.update(kw)
    return Claim(**base)


def check(claim, table, judge, **kw):
    args = dict(http_get=FakeGet(table), judge_fn=judge, judge_name="muse-glimmer (local)",
                target_unit="frac", band_lo=0.02, band_hi=0.25)
    args.update(kw)
    return check_citation(claim, **args)


# ---------------------------------------------------------------- constants and types

def test_constants():
    assert USER_AGENT == "AutoSolarResearcher/0.1 (+https://github.com/havidaqoma/autosolar-researcher)"
    assert MAX_SOURCE_BYTES == 25_000_000 and MIN_QUOTE_CHARS == 20
    assert CONTEXT_CHARS == 400 and MAX_PROMPT_CONTEXT_CHARS == 3000
    assert isinstance(SUPPORT_INSTRUCTIONS, str) and '"supports"' in SUPPORT_INSTRUCTIONS
    assert SUPPORT_INSTRUCTIONS.isascii()
    assert issubclass(FetchError, RuntimeError)


def test_dataclass_fields_in_order():
    names = lambda cls: [f.name for f in dataclasses.fields(cls)]  # noqa: E731
    assert names(Source) == ["url", "final_url", "status_code", "is_pdf", "pages", "bytes_len"]
    assert names(QuoteMatch) == ["found", "kind", "page", "start", "end", "skipped_source_tokens",
                                 "missing_quote_tokens", "context"]
    assert names(Verdict) == ["supports", "reason", "raw"]
    assert names(Claim) == ["input_name", "description", "value", "unit", "url", "doi", "quote", "title",
                            "currency_year"]
    assert names(CitationCheck) == ["input_name", "status", "reasons", "value_as_written", "unit_as_written",
                                    "value_converted", "target_unit", "url", "final_url", "is_pdf", "page",
                                    "quote_kind", "doi", "doi_ok", "supports", "judge_reason", "judge_name",
                                    "context", "judge_calls"]


# ---------------------------------------------------------------- text

def test_normalise_text_maps_typography():
    raw = "  It\u2019s \u201cUSD\u00a02\u2009571\u201d \u2013 a\u00adb \u2212 5 &amp; CO\n\n2  "
    assert normalise_text(raw) == "it's \"usd 2 571\" - ab - 5 & co 2"


def test_html_to_text_drops_script_style_and_tags():
    text = html_to_text(IEA_HTML)
    assert "99.9" not in text and "color" not in text
    assert "<" not in text and "other text & more text." in text
    assert "thailand (6.0-8.0%)" in text


def test_pdf_pages_reads_each_page():
    pages = pdf_pages(IRENA_PDF)
    assert len(pages) == 2
    assert "executive summary" in pages[0]
    assert "usd 192/kwh" in pages[1] and pages[1] == normalise_text(pages[1])


def test_pdf_pages_bad_bytes():
    with pytest.raises(FetchError, match="pdf text extraction failed"):
        pdf_pages(b"%PDF-1.4 not really a pdf")


# ---------------------------------------------------------------- numbers and units

def test_numbers_in():
    assert {2571.0, 192.0, 93.0, 2010.0, 2024.0} <= set(numbers_in(normalise_text(IRENA_QUOTE)))
    assert 1119.0 in numbers_in("set at 1,119 usd/kw")
    assert 9.4 in numbers_in("was 9.4%, 9.0%")
    row = numbers_in("diesel 6,800 11,420 9,110 67.9")
    assert {6800.0, 11420.0, 9110.0, 67.9} <= set(row)
    assert 680011420.0 not in row and 6800114.0 not in row
    assert numbers_in("no digits here") == []
    assert numbers_in("3 3 3.5") == sorted(set(numbers_in("3 3 3.5")))


@pytest.mark.parametrize("raw,canon", [
    ("USD/kWh", "USD/kWh"), ("US$ per kWh", "USD/kWh"), ("$/kW", "USD/kW"), ("usd/kwp", "USD/kWp"),
    ("USD/kW/yr", "USD/kW/yr"), ("USD/kW-yr", "USD/kW/yr"), ("USD per kW per year", "USD/kW/yr"),
    ("Rp/liter", "IDR/L"), ("IDR per litre", "IDR/L"), ("Rp./L", "IDR/L"), ("%", "%"), ("percent", "%"),
    ("frac", "frac"), ("USD/Wp", "USD/Wp"), ("USD/MWh", "USD/MWh"), ("USD/kWh/yr", "USD/kWh/yr"),
])
def test_parse_unit_ok(raw, canon):
    assert parse_unit(raw) == canon


@pytest.mark.parametrize("raw", ["EUR/kWh", "USD/kWh/day", "", "kWh", "USD", "USD/kW/yr/h", "USD/furlong"])
def test_parse_unit_rejects(raw):
    with pytest.raises(ValueError):
        parse_unit(raw)


def test_convert_value():
    assert convert_value(1119, "USD/kW", "USD/kWp") == pytest.approx(1119.0)
    assert convert_value(0.95, "USD/Wp", "USD/kWp") == pytest.approx(950.0)
    assert convert_value(9.4, "%", "frac") == pytest.approx(0.094)
    assert convert_value(150, "USD/MWh", "USD/kWh") == pytest.approx(0.15)
    assert convert_value(18, "USD/kW/yr", "USD/kWp/yr") == pytest.approx(18.0)
    assert convert_value(11420, "IDR/L", "USD/L", fx_idr_per_usd=15000.0) == pytest.approx(11420 / 15000.0)
    assert convert_value(120, "USD/MW", "USD/kW") == pytest.approx(0.12)


@pytest.mark.parametrize("args,kw", [
    ((11420, "IDR/L", "USD/L"), {}),
    ((11420, "IDR/L", "USD/L"), {"fx_idr_per_usd": 0.0}),
    ((11420, "IDR/L", "USD/L"), {"fx_idr_per_usd": float("nan")}),
    ((300, "USD/kWh", "USD/kWp"), {}),
    ((300, "USD/kWh", "USD/L"), {}),
    ((float("inf"), "USD/kWh", "USD/kWh"), {}),
    ((True, "frac", "frac"), {}),
])
def test_convert_value_rejects(args, kw):
    with pytest.raises(ValueError):
        convert_value(*args, **kw)


# ---------------------------------------------------------------- quotes

def test_find_quote_exact_on_second_page_with_typography():
    pages = ["nothing here at all", normalise_text("Intro. " + IEA_QUOTE.replace("Viet Nam", "Viet\u00a0Nam")),
             "third page"]
    m = find_quote(IEA_QUOTE.upper(), pages)
    assert (m.found, m.kind, m.page) == (True, "exact", 2)
    assert pages[1][m.start:m.end] == normalise_text(IEA_QUOTE)
    assert (m.skipped_source_tokens, m.missing_quote_tokens) == (0, 0)
    assert m.context == pages[1][max(0, m.start - CONTEXT_CHARS):m.end + CONTEXT_CHARS]


def test_find_quote_near_with_one_dropped_token():
    page = html_to_text(FRONT_HTML)
    m = find_quote(FRONT_QUOTE, [page])
    assert (m.found, m.kind, m.page) == (True, "near", 1)
    assert (m.skipped_source_tokens, m.missing_quote_tokens) == (1, 0)
    assert page[m.start:m.end].startswith("the unsubsidised initial capex")
    assert page[m.start:m.end].endswith("simplification")


def test_find_quote_rejects_reworded_quote():
    page = html_to_text(FRONT_HTML)
    reworded = "Initial capital cost of utility solar in Indonesia was about 1,119 dollars per kilowatt in 2022."
    m = find_quote(reworded, [page])
    assert m == QuoteMatch(False, "none", None, None, None, 0, 0, "")


def test_find_quote_short_quote_not_checked():
    assert find_quote("USD 192/kWh", ["falling to usd 192/kwh"]).found is False


def test_find_quote_one_missing_token_allowed_only_when_long_enough():
    src = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike"
    ten = "alpha bravo charlie delta echo xray golf hotel india juliet"    # 10 tokens, one wrong: max_missing 1
    m = find_quote(ten, [src])
    assert (m.kind, m.missing_quote_tokens, m.skipped_source_tokens) == ("near", 1, 1)
    nine = "alpha bravo charlie delta echo xray golf hotel india"          # 9 tokens, one wrong: max_missing 0
    assert find_quote(nine, [src]).found is False


def test_find_quote_skip_limit():
    src = "alpha beta one two three four gamma delta epsilon zeta eta theta"
    ok = "alpha beta gamma delta epsilon zeta"          # skips 4 in one go: more than 3 ahead, so missing
    assert find_quote(ok, [src]).found is False
    src2 = "alpha beta one two three gamma delta epsilon zeta eta theta"
    assert find_quote(ok, [src2]).found is True        # skips 3 tokens, allowed (max_skipped 3)


def test_find_quote_window_is_four_tokens():
    words = ["w%02d" % i for i in range(40)]           # 40 tokens: max_missing 4, max_skipped 4
    quote = " ".join(words)
    gap4 = " ".join(words[:10] + ["xa", "xb", "xc", "xd"] + words[10:])
    assert find_quote(quote, [gap4]).found is False    # w10 sits 5 tokens ahead: outside the window
    gap3 = " ".join(words[:10] + ["xa", "xb", "xc"] + words[10:])
    m = find_quote(quote, [gap3])
    assert (m.found, m.kind, m.skipped_source_tokens, m.missing_quote_tokens) == (True, "near", 3, 0)


# ---------------------------------------------------------------- fetch

def test_fetch_source_html():
    get = FakeGet({IEA_URL: Resp(200, IEA_HTML.encode("utf-8"), url=IEA_URL + "?r=1")})
    src = fetch_source(IEA_URL, get, timeout_s=12.5)
    assert (src.is_pdf, src.status_code, len(src.pages), src.final_url) == (False, 200, 1, IEA_URL + "?r=1")
    assert src.bytes_len == len(IEA_HTML.encode("utf-8"))
    assert get.calls == [(IEA_URL, {"headers": {"User-Agent": USER_AGENT}, "timeout": 12.5,
                                    "allow_redirects": True})]


def test_fetch_source_pdf_by_magic_bytes():
    resp = Resp(200, IRENA_PDF, url=None)
    resp.headers = {"content-type": "text/html"}
    src = fetch_source(IRENA_URL, FakeGet({IRENA_URL: resp}))
    assert src.is_pdf is True and len(src.pages) == 2 and src.final_url == IRENA_URL


@pytest.mark.parametrize("item,msg", [
    (Resp(403, b"denied"), "HTTP 403"),
    (requests.ConnectionError("boom"), "ConnectionError"),
    (Resp(200, b"<html><body> </body></html>"), "no text in source"),
])
def test_fetch_source_errors(item, msg):
    with pytest.raises(FetchError, match=msg):
        fetch_source(IEA_URL, FakeGet({IEA_URL: item}))


def test_fetch_source_bad_scheme_makes_no_call():
    get = FakeGet({})
    with pytest.raises(FetchError, match="url must start with"):
        fetch_source("ftp://example.org/x.pdf", get)
    with pytest.raises(FetchError):
        fetch_source(None, get)
    assert get.calls == []


def test_fetch_source_too_large(monkeypatch):
    import autosolar.cite_check as cc
    monkeypatch.setattr(cc, "MAX_SOURCE_BYTES", 10)
    with pytest.raises(FetchError, match="larger than"):
        cc.fetch_source(IEA_URL, FakeGet({IEA_URL: Resp(200, IEA_HTML.encode("utf-8"))}))


# ---------------------------------------------------------------- DOI

def test_doi_resolves_true_and_url():
    url = "https://doi.org/api/handles/" + FRONT_DOI
    get = FakeGet({url: DOI_OK})
    assert doi_resolves("https://doi.org/" + FRONT_DOI, get, timeout_s=9.0) is True
    assert get.calls == [(url, {"headers": {"User-Agent": USER_AGENT}, "timeout": 9.0})]
    assert doi_resolves("DOI:" + FRONT_DOI, get) is True


def test_doi_resolves_false_cases():
    get = FakeGet({"https://doi.org/api/handles/10.3389/fsuep.2024.9999999": DOI_MISSING})
    assert doi_resolves("10.3389/fsuep.2024.9999999", get) is False
    get2 = FakeGet({})
    assert doi_resolves("not a doi", get2) is False and doi_resolves("11.1/x", get2) is False
    assert get2.calls == []
    get3 = FakeGet({"https://doi.org/api/handles/" + FRONT_DOI: Resp(200, b"not json")})
    assert doi_resolves(FRONT_DOI, get3) is False


def test_doi_resolves_errors():
    with pytest.raises(FetchError, match="doi check HTTP 500"):
        doi_resolves(FRONT_DOI, FakeGet({"https://doi.org/api/handles/" + FRONT_DOI: Resp(500, b"")}))
    with pytest.raises(FetchError, match="doi check: Timeout"):
        doi_resolves(FRONT_DOI, FakeGet({"https://doi.org/api/handles/" + FRONT_DOI: requests.Timeout("t")}))


# ---------------------------------------------------------------- judge

def test_support_verdict_prompt_and_parse():
    judge = Judge("```json\n" + YES + "\n```")
    v = support_verdict(judge, iea_claim(), "context " * 1000)
    assert v.supports is True and v.reason == "The quote states the value for this input."
    p = judge.prompts[0]
    expected = (SUPPORT_INSTRUCTIONS + "\n\nInput: WACC for solar PV in Indonesia\nSource title: (not shown)"
                "\nSource URL: (not shown)\nClaimed value: 9.4 %\nQuote: "
                + IEA_QUOTE + "\nSource context:\n" + ("context " * 1000)[:MAX_PROMPT_CONTEXT_CHARS])
    assert p == expected


def test_support_verdict_json_inside_prose_and_bad_answers():
    v = support_verdict(Judge("Thinking done. " + NO + " End."), iea_claim(), "ctx")
    assert v.supports is False and v.reason.startswith("The number is a global average")
    v2 = support_verdict(Judge("yes it supports"), iea_claim(), "ctx")
    assert (v2.supports, v2.reason) == (None, "unparsed judge answer")
    v3 = support_verdict(Judge('{"supports": "yes", "reason": "x"}'), iea_claim(), "ctx")
    assert v3.supports is None
    v4 = support_verdict(Judge(RuntimeError("server down")), iea_claim(), "ctx")
    assert (v4.supports, v4.reason, v4.raw) == (None, "judge error: RuntimeError", "")


# ---------------------------------------------------------------- check_citation

def test_check_citation_happy_html():
    judge = Judge(YES)
    c = check(iea_claim(), {IEA_URL: Resp(200, IEA_HTML.encode("utf-8"))}, judge)
    assert c.status == "checked" and c.reasons == []
    assert c.value_converted == pytest.approx(0.094) and c.target_unit == "frac"
    assert (c.quote_kind, c.page, c.is_pdf, c.supports) == ("exact", 1, False, True)
    assert c.judge_name == "muse-glimmer (local)" and len(judge.prompts) == 3 and c.judge_calls == 3
    assert c.doi is None and c.doi_ok is None
    json.dumps(dataclasses.asdict(c))


def test_check_citation_pdf_page_number():
    claim = Claim("battery_capex_usd_per_kwh", "installed cost of battery storage per kWh", 192, "USD/kWh",
                  IRENA_URL, None, IRENA_QUOTE, "IRENA costs", 2024)
    c = check(claim, {IRENA_URL: Resp(200, IRENA_PDF)}, Judge(YES), target_unit="USD/kWh", band_lo=50,
              band_hi=1500)
    assert c.status == "checked" and (c.page, c.is_pdf, c.quote_kind) == (2, True, "exact")
    assert c.value_converted == pytest.approx(192.0)


def test_check_citation_near_match_with_doi():
    claim = Claim("pv_capex_usd_per_kwp", "installed cost of utility PV in Indonesia", 1119, "USD/kW",
                  FRONT_URL, FRONT_DOI, FRONT_QUOTE, "Frontiers paper", 2022)
    table = {FRONT_URL: Resp(200, FRONT_HTML.encode("utf-8")), "https://doi.org/api/handles/" + FRONT_DOI: DOI_OK}
    c = check(claim, table, Judge(YES), target_unit="USD/kWp", band_lo=300, band_hi=4000)
    assert c.status == "checked" and c.quote_kind == "near" and c.doi_ok is True


def test_planted_fault_doi_does_not_resolve():
    claim = Claim("pv_capex_usd_per_kwp", "installed cost of utility PV in Indonesia", 1119, "USD/kW",
                  FRONT_URL, "10.3389/fsuep.2024.9999999", FRONT_QUOTE, "Frontiers paper", 2022)
    judge = Judge(YES)
    table = {FRONT_URL: Resp(200, FRONT_HTML.encode("utf-8")),
             "https://doi.org/api/handles/10.3389/fsuep.2024.9999999": DOI_MISSING}
    c = check(claim, table, judge, target_unit="USD/kWp", band_lo=300, band_hi=4000)
    assert c.status == "assumed" and c.reasons == ["doi does not resolve"] and c.doi_ok is False
    assert judge.prompts == [] and c.supports is None and c.judge_reason == ""


def test_planted_fault_quote_not_in_text():
    judge = Judge(YES)
    claim = iea_claim(quote="The weighted average cost of capital for solar in Indonesia was 9.4% in 2024 per IEA.")
    c = check(claim, {IEA_URL: Resp(200, IEA_HTML.encode("utf-8"))}, judge)
    assert c.status == "assumed" and c.reasons == ["quote not found in source"]
    assert c.quote_kind == "none" and judge.prompts == []


def test_planted_fault_judge_says_not_supported():
    c = check(iea_claim(), {IEA_URL: Resp(200, IEA_HTML.encode("utf-8"))}, Judge(NO))
    assert c.status == "assumed" and c.supports is False
    assert c.reasons == ["judge says not supported: The number is a global average, not this input."]


def test_value_not_in_quoted_text():
    judge = Judge(YES)
    c = check(iea_claim(value=8.5), {IEA_URL: Resp(200, IEA_HTML.encode("utf-8"))}, judge)
    assert c.reasons == ["value not in the quoted source text"] and judge.prompts == []


def test_unit_and_band_reasons_and_fetch_failure():
    c = check(iea_claim(unit="basis points"), {IEA_URL: Resp(200, IEA_HTML.encode("utf-8"))}, Judge(YES))
    assert c.status == "assumed" and c.reasons[0].startswith("unit: ") and c.value_converted is None
    c2 = check(iea_claim(), {IEA_URL: Resp(200, IEA_HTML.encode("utf-8"))}, Judge(YES), band_lo=0.10,
               band_hi=0.25)
    assert c2.reasons == ["value 0.094 frac outside band [0.1, 0.25]"]
    c3 = check(iea_claim(), {IEA_URL: Resp(403, b"")}, Judge(YES))
    assert c3.reasons == ["fetch: HTTP 403"] and c3.quote_kind == "not run" and c3.page is None
    assert c3.final_url is None and c3.is_pdf is None


def test_judge_without_verdict_and_doi_network_error():
    c = check(iea_claim(), {IEA_URL: Resp(200, IEA_HTML.encode("utf-8"))}, Judge("maybe"))
    assert c.reasons == ["judge gave no verdict: unparsed judge answer"] and c.status == "assumed"
    claim = iea_claim(doi=FRONT_DOI)
    table = {IEA_URL: Resp(200, IEA_HTML.encode("utf-8")),
             "https://doi.org/api/handles/" + FRONT_DOI: requests.ConnectionError("x")}
    c2 = check(claim, table, Judge(YES))
    assert c2.reasons == ["doi check failed: doi check: ConnectionError"] and c2.doi_ok is None


def test_idr_fuel_price_converted_with_fx():
    page = "<p>Table 3. Diesel 6,800 11,420 9,110 67.9 retail prices per litre</p>"
    claim = Claim("fuel_price_usd_per_l", "industrial diesel price in Indonesia", 11420, "Rp/liter",
                  IEA_URL, None, "Diesel 6,800 11,420 9,110 67.9 retail prices", "World Bank", 2023)
    c = check(claim, {IEA_URL: Resp(200, page.encode("utf-8"))}, Judge(YES), target_unit="USD/L", band_lo=0.3,
              band_hi=2.5, fx_idr_per_usd=15236.0)
    assert c.status == "checked" and c.value_converted == pytest.approx(11420 / 15236.0)
    c2 = check(claim, {IEA_URL: Resp(200, page.encode("utf-8"))}, Judge(YES), target_unit="USD/L", band_lo=0.3,
               band_hi=2.5)
    assert c2.reasons[0] == "unit: IDR value needs fx_idr_per_usd"


def test_bad_claim_value_raises():
    with pytest.raises(ValueError):
        check(iea_claim(value=True), {}, Judge(YES))
    with pytest.raises(ValueError):
        check(iea_claim(value=float("nan")), {}, Judge(YES))
