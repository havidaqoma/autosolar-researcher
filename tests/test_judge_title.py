"""Acceptance tests for T10e (judge sees title and URL; percent units with a descriptor). Written by the orchestrator.
No network."""
import json

import pytest

from autosolar.cite_check import (
    MAX_PROMPT_CONTEXT_CHARS,
    MAX_PROMPT_TITLE_CHARS,
    MAX_PROMPT_URL_CHARS,
    MIN_TITLE_CHARS,
    OPENALEX_WORK_URL,
    SUPPORT_INSTRUCTIONS,
    Claim,
    check_citation,
    convert_value,
    parse_unit,
    support_verdict,
    title_in_source,
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
        return self.text


YES = '{"supports": true, "reason": "The quote states the value for this input."}'
NO = '{"supports": false, "reason": "Not this input."}'
JUDGE = "muse-glimmer (local)"

TITLE = "100% Renewable Electricity in Indonesia"
PAPER_URL = "https://mdpi-res.com/d_attachment/energies/energies-17-00003/article_deploy/energies-17-00003.pdf"
RATE_QUOTE = "A real discount rate of 5% is used for all technologies in this study."
RATE_PDF = make_pdf([["Energies 2024", "100% Renewable", "Electricity in Indonesia", "by A. Author"],
                     ["Methods", RATE_QUOTE]])

LOAD_URL = "https://www.example.org/island-grid"
LOAD_QUOTE = "Each diesel generator is kept above 30% of its rated capacity at all times."
LOAD_HTML = ("<html><head><title>Island grid operation guide</title></head><body><p>Operation.</p><p>" + LOAD_QUOTE
             + "</p></body></html>")


def rate_claim(**kw):
    base = dict(input_name="discount_rate_frac", description="real discount rate for renewable projects in Indonesia",
                value=5, unit="%", url=PAPER_URL, doi=None, quote=RATE_QUOTE, title=TITLE, currency_year=None)
    base.update(kw)
    return Claim(**base)


def load_claim(**kw):
    base = dict(input_name="diesel_min_load_frac", description="minimum load of a diesel generator set",
                value=30, unit="% of its rated capacity", url=LOAD_URL, doi=None, quote=LOAD_QUOTE,
                title="Island grid operation guide", currency_year=None)
    base.update(kw)
    return Claim(**base)


def run(claim, table, judge=None, **kw):
    get = FakeGet(table)
    judge = judge or Judge(YES)
    args = dict(http_get=get, judge_fn=judge, judge_name=JUDGE, target_unit="frac", band_lo=0.02, band_hi=0.6)
    args.update(kw)
    return check_citation(claim, **args), get, judge


def prompt_for(claim, title_text, url_text, context):
    return (SUPPORT_INSTRUCTIONS + "\n\nInput: " + claim.description + "\nSource title: " + title_text
            + "\nSource URL: " + url_text + "\nClaimed value: " + str(claim.value) + " " + claim.unit
            + "\nQuote: " + claim.quote + "\nSource context:\n" + context[:MAX_PROMPT_CONTEXT_CHARS])


# ---------------------------------------------------------------- constants

def test_constants():
    assert MIN_TITLE_CHARS == 12
    assert MAX_PROMPT_TITLE_CHARS == 300 and MAX_PROMPT_URL_CHARS == 500


def test_support_instructions_exact():
    assert SUPPORT_INSTRUCTIONS == (
        "Decide if the quote and source context state the claimed value. "
        'Answer with one JSON object {"supports": true or false, "reason": "<one sentence>"}. '
        "Use supports true only when the quote and context state this value, "
        "in this unit, for the thing described. "
        "The source title and URL show what the whole source is about, for example the country it covers, "
        "but the value itself must come from the quote and context. "
        "Use supports false otherwise. Keep reason to one sentence."
    )


# ---------------------------------------------------------------- 1. title_in_source

def test_title_found_case_and_space():
    pages = ["energies 2024 100%   RENEWABLE electricity in\nIndonesia by a. author"]
    assert title_in_source(TITLE, pages) is True


def test_title_found_across_pages():
    assert title_in_source(TITLE, ["header 100% renewable", "electricity in indonesia by"]) is True


def test_title_found_in_later_page():
    assert title_in_source(TITLE, ["nothing here", "more", "see 100% renewable electricity in indonesia"]) is True


def test_title_not_found():
    assert title_in_source("Discount rates for solar PV in Indonesia", ["100% renewable electricity in indonesia"]) \
        is False


def test_title_normalised_quotes_and_dashes():
    title = "Cost \u2013 Indonesia\u2019s grid plan"
    assert title_in_source(title, ["the cost - indonesia's grid plan for 2030"]) is True


def test_title_strip():
    assert title_in_source("   " + TITLE + "  \n", ["x 100% renewable electricity in indonesia y"]) is True


def test_title_too_short_even_if_present():
    assert title_in_source("Indonesia", ["indonesia indonesia"]) is False
    assert title_in_source("Diesel pric", ["diesel price list"]) is False  # 11 chars


def test_title_twelve_chars_boundary():
    assert len("Diesel price") == 12
    assert title_in_source("Diesel price", ["the diesel price list"]) is True


@pytest.mark.parametrize("title,pages", [
    (None, ["anything at all here"]),
    (5, ["anything at all here"]),
    (b"100% Renewable Electricity in Indonesia", ["100% renewable electricity in indonesia"]),
    ("   ", ["   "]),
    ("", [""]),
    (TITLE, []),
    (TITLE, None),
    (TITLE, "100% renewable electricity in indonesia"),
    (TITLE, ("100% renewable electricity in indonesia",)),
    (TITLE, ["100% renewable electricity in indonesia", None]),
    (TITLE, [b"100% renewable electricity in indonesia"]),
])
def test_title_bad_input_false_never_raises(title, pages):
    assert title_in_source(title, pages) is False


# ---------------------------------------------------------------- 2. support_verdict prompt

def test_prompt_with_title_and_url():
    judge = Judge(YES)
    claim = rate_claim()
    v = support_verdict(judge, claim, "ctx " * 2000, source_title=TITLE, source_url=PAPER_URL)
    assert v.supports is True
    assert judge.prompts == [prompt_for(claim, TITLE, PAPER_URL, "ctx " * 2000)]


def test_prompt_defaults_not_shown():
    judge = Judge(YES)
    claim = rate_claim()
    support_verdict(judge, claim, "ctx")
    assert judge.prompts == [prompt_for(claim, "(not shown)", "(not shown)", "ctx")]


@pytest.mark.parametrize("bad", ["", "   ", "\n\t", None, 7, b"title bytes"])
def test_prompt_blank_or_bad_values_not_shown(bad):
    judge = Judge(YES)
    claim = rate_claim()
    support_verdict(judge, claim, "ctx", source_title=bad, source_url=bad)
    assert judge.prompts == [prompt_for(claim, "(not shown)", "(not shown)", "ctx")]


def test_prompt_strips_and_truncates():
    judge = Judge(YES)
    claim = rate_claim()
    long_title = "  " + "T" * 400 + "  "
    long_url = " https://x.org/" + "u" * 600 + " "
    support_verdict(judge, claim, "ctx", source_title=long_title, source_url=long_url)
    p = judge.prompts[0]
    assert p == prompt_for(claim, "T" * MAX_PROMPT_TITLE_CHARS, ("https://x.org/" + "u" * 600)[:MAX_PROMPT_URL_CHARS],
                           "ctx")


def test_prompt_strip_before_truncate():
    judge = Judge(YES)
    claim = rate_claim()
    support_verdict(judge, claim, "ctx", source_title=" " * 299 + "Real title here", source_url="  https://a.org/b  ")
    assert judge.prompts == [prompt_for(claim, "Real title here", "https://a.org/b", "ctx")]


def test_prompt_title_only_url_only():
    claim = rate_claim()
    j1 = Judge(YES)
    support_verdict(j1, claim, "ctx", source_title=TITLE)
    assert j1.prompts == [prompt_for(claim, TITLE, "(not shown)", "ctx")]
    j2 = Judge(YES)
    support_verdict(j2, claim, "ctx", source_url=PAPER_URL)
    assert j2.prompts == [prompt_for(claim, "(not shown)", PAPER_URL, "ctx")]


def test_verdict_parsing_unchanged():
    v = support_verdict(Judge("Thinking. " + NO + " done"), rate_claim(), "ctx", source_title=TITLE)
    assert (v.supports, v.reason) == (False, "Not this input.")
    v2 = support_verdict(Judge("yes"), rate_claim(), "ctx", source_url=PAPER_URL)
    assert (v2.supports, v2.reason) == (None, "unparsed judge answer")


# ---------------------------------------------------------------- 3. check_citation passes title and URL

def context_of(c):
    return c.context


def test_check_citation_title_found_in_pdf():
    c, get, judge = run(rate_claim(), {PAPER_URL: Resp(200, RATE_PDF)})
    assert c.status == "checked" and c.reasons == [] and c.page == 2
    assert c.value_converted == pytest.approx(0.05)
    assert judge.prompts == [prompt_for(rate_claim(), TITLE, PAPER_URL, context_of(c))]


def test_check_citation_title_not_in_source_not_shown():
    claim = rate_claim(title="Discount rates for solar PV in Indonesia")
    c, get, judge = run(claim, {PAPER_URL: Resp(200, RATE_PDF)})
    assert c.status == "checked"
    assert judge.prompts == [prompt_for(claim, "(not shown)", PAPER_URL, context_of(c))]


def test_check_citation_short_or_empty_title_not_shown():
    for title in ("", "Energies", "  "):
        claim = rate_claim(title=title)
        c, get, judge = run(claim, {PAPER_URL: Resp(200, RATE_PDF)})
        assert judge.prompts == [prompt_for(claim, "(not shown)", PAPER_URL, context_of(c))], title


def test_check_citation_shows_claim_title_as_written():
    claim = rate_claim(title="  100% RENEWABLE Electricity   in Indonesia ")
    c, get, judge = run(claim, {PAPER_URL: Resp(200, RATE_PDF)})
    assert judge.prompts == [prompt_for(claim, "100% RENEWABLE Electricity   in Indonesia", PAPER_URL,
                                        context_of(c))]


def test_check_citation_url_is_final_url_after_redirect():
    final = "https://www.mdpi.com/1996-1073/17/1/3/pdf?version=final"
    c, get, judge = run(rate_claim(), {PAPER_URL: Resp(200, RATE_PDF, url=final)})
    assert c.final_url == final
    assert judge.prompts == [prompt_for(rate_claim(), TITLE, final, context_of(c))]


def test_check_citation_mirror_copy_title_and_url():
    doi = "10.3390/en17010003"
    pub = "https://www.mdpi.com/1996-1073/17/1/3"
    oa_pdf = "https://mdpi-res.com/d_attachment/energies/energies-17-00003.pdf"
    oa_body = json.dumps({"locations": [{"pdf_url": oa_pdf, "landing_page_url": pub}]}).encode("utf-8")
    table = {pub: Resp(403, b"denied"), OPENALEX_WORK_URL + doi: Resp(200, oa_body), oa_pdf: Resp(200, RATE_PDF),
             "https://doi.org/api/handles/" + doi: Resp(200, json.dumps({"responseCode": 1}).encode("utf-8"))}
    claim = rate_claim(url=pub, doi=doi)
    c, get, judge = run(claim, table)
    assert c.status == "checked" and c.final_url == oa_pdf and c.doi_ok is True
    assert judge.prompts == [prompt_for(claim, TITLE, oa_pdf, context_of(c))]


def test_check_citation_title_checked_against_mirror_not_blocked_page():
    doi = "10.3390/en17010003"
    pub = "https://www.mdpi.com/1996-1073/17/1/3"
    oa_pdf = "https://mdpi-res.com/d_attachment/energies/energies-17-00003.pdf"
    no_title_pdf = make_pdf([["Energies 2024"], ["Methods", RATE_QUOTE]])
    oa_body = json.dumps({"locations": [{"pdf_url": oa_pdf}]}).encode("utf-8")
    table = {pub: Resp(403, TITLE.encode("utf-8")), OPENALEX_WORK_URL + doi: Resp(200, oa_body),
             oa_pdf: Resp(200, no_title_pdf),
             "https://doi.org/api/handles/" + doi: Resp(200, json.dumps({"responseCode": 1}).encode("utf-8"))}
    claim = rate_claim(url=pub, doi=doi)
    c, get, judge = run(claim, table)
    assert c.status == "checked"
    assert judge.prompts == [prompt_for(claim, "(not shown)", oa_pdf, context_of(c))]


def test_check_citation_judge_no_still_assumed():
    c, get, judge = run(rate_claim(), {PAPER_URL: Resp(200, RATE_PDF)}, judge=Judge(NO))
    assert c.status == "assumed" and c.reasons == ["judge says not supported: Not this input."]
    assert c.supports is False and len(judge.prompts) == 1


def test_check_citation_no_judge_when_script_fails():
    c, get, judge = run(rate_claim(value=7), {PAPER_URL: Resp(200, RATE_PDF)})
    assert c.reasons == ["value not in the quoted source text"] and judge.prompts == []


def test_check_citation_title_uses_html_head_text():
    claim = load_claim()
    c, get, judge = run(claim, {LOAD_URL: Resp(200, LOAD_HTML.encode("utf-8"))}, band_lo=0.1)
    assert c.status == "checked"
    assert judge.prompts == [prompt_for(claim, "Island grid operation guide", LOAD_URL, context_of(c))]


# ---------------------------------------------------------------- 4. percent with a descriptor

@pytest.mark.parametrize("raw", [
    "% of its rated capacity", "percent of rated power", "% of rated output", "PERCENT OF RATED POWER",
    "%  of   rated\tpower", "  % of capacity  ", "% of nominal power", "Percent Of Rated Power",
])
def test_percent_descriptor_parses(raw):
    assert parse_unit(raw) == "%"


@pytest.mark.parametrize("raw", [
    "% of", "% of ", "percent of", "% of rated power (kW)", "% of 50 kW", "% off peak", "%of capacity",
    "% of rated-power", "of rated power %", "% rated power", "%% of rated power", "% of rated power.",
    "percentage of rated power", "% of rated power/yr", "pct of rated power", "% of rated_power",
])
def test_percent_descriptor_rejects(raw):
    with pytest.raises(ValueError):
        parse_unit(raw)


@pytest.mark.parametrize("raw,canon", [
    ("%", "%"), ("percent", "%"), ("pct", "%"), ("%/yr", "%"), ("% per year", "%"), ("frac", "frac"),
    ("fraction", "frac"), ("USD/kWh", "USD/kWh"), ("US$ per kWh", "USD/kWh"), ("Rp/liter", "IDR/L"),
    ("USD per kW per year", "USD/kW/yr"), ("USD/kW-yr", "USD/kW/yr"),
])
def test_old_units_unchanged(raw, canon):
    assert parse_unit(raw) == canon


def test_percent_descriptor_converts_only_to_frac():
    assert convert_value(30, parse_unit("% of its rated capacity"), "frac") == pytest.approx(0.3)
    with pytest.raises(ValueError, match="cannot convert % to USD/kWp/yr"):
        convert_value(2, parse_unit("% of capex"), "USD/kWp/yr")


def test_check_citation_percent_descriptor_checked():
    claim = load_claim()
    c, get, judge = run(claim, {LOAD_URL: Resp(200, LOAD_HTML.encode("utf-8"))}, band_lo=0.1)
    assert c.status == "checked" and c.reasons == []
    assert c.value_converted == pytest.approx(0.3) and c.unit_as_written == "% of its rated capacity"
    assert "\nClaimed value: 30 % of its rated capacity\n" in judge.prompts[0]


def test_check_citation_percent_of_capex_not_a_cost():
    quote = "Annual O&M cost is assumed to be 2% of capex for the PV plant in this study."
    html = "<html><body><p>" + quote + "</p></body></html>"
    claim = Claim("pv_om_usd_per_kwp_yr", "annual O&M cost of PV per kWp", 2, "% of capex", LOAD_URL, None, quote,
                  "Some study on PV costs", None)
    c, get, judge = run(claim, {LOAD_URL: Resp(200, html.encode("utf-8"))}, target_unit="USD/kWp/yr", band_lo=3,
                        band_hi=60)
    assert c.status == "assumed" and c.reasons[0] == "unit: cannot convert % to USD/kWp/yr"
    assert judge.prompts == []
