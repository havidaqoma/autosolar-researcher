"""Citation checks for sourced inputs. Money in USD, energy in kWh, power in kW."""

import dataclasses
import html
import io
import json
import math
import re
import unicodedata

import requests
from pypdf import PdfReader
from urllib.parse import urlparse

USER_AGENT = "AutoSolarResearcher/0.1 (+https://github.com/havidaqoma/autosolar-researcher)"
BLOCKED_STATUS = (401, 403, 429)
MAX_MIRRORS = 4
OPENALEX_WORK_URL = "https://api.openalex.org/works/doi:"
EUROPE_PMC_XML_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
MAX_SOURCE_BYTES = 25_000_000
MIN_QUOTE_CHARS = 20
CONTEXT_CHARS = 400
MAX_PROMPT_CONTEXT_CHARS = 3000
MIN_TITLE_CHARS = 12
MAX_PROMPT_TITLE_CHARS = 300
MAX_PROMPT_URL_CHARS = 500
JUDGE_VOTES = 3
SUPPORT_INSTRUCTIONS = (
    "Decide if the quote and source context state the claimed value. "
    'Answer with one JSON object {"supports": true or false, "reason": "<one sentence>"}. '
    "Use supports true only when the quote and context state this value, "
    "in this unit, for the thing described. "
    "The source title and URL show what the whole source is about, for example the country it covers, "
    "but the value itself must come from the quote and context. "
    "Use supports false otherwise. Keep reason to one sentence."
)


class FetchError(RuntimeError):
    """Raised when a source cannot be fetched or read."""


@dataclasses.dataclass
class Source:
    """Fetched source. Pages hold normalised text. Bytes in bytes."""

    url: str
    final_url: str
    status_code: int
    is_pdf: bool
    pages: list[str]
    bytes_len: int


@dataclasses.dataclass
class QuoteMatch:
    """Quote search result. Offsets in chars."""

    found: bool
    kind: str
    page: int | None
    start: int | None
    end: int | None
    skipped_source_tokens: int
    missing_quote_tokens: int
    context: str


@dataclasses.dataclass
class Verdict:
    """Judge answer. Supports tri-state."""

    supports: bool | None
    reason: str
    raw: str


@dataclasses.dataclass
class Claim:
    """Claimed input value with source quote."""

    input_name: str
    description: str
    value: float | int
    unit: str
    url: str
    doi: str | None
    quote: str
    title: str
    currency_year: int | None


@dataclasses.dataclass
class CitationCheck:
    """Outcome of script checks plus judge."""

    input_name: str
    status: str
    reasons: list[str]
    value_as_written: float
    unit_as_written: str
    value_converted: float | None
    target_unit: str
    url: str
    final_url: str | None
    is_pdf: bool | None
    page: int | None
    quote_kind: str
    doi: str | None
    doi_ok: bool | None
    supports: bool | None
    judge_reason: str
    judge_name: str
    context: str
    judge_calls: int = 0


def normalise_text(text: str) -> str:
    """Normalise text for compare. Output is lowercase."""
    s = html.unescape(text)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        s = s.replace(ch, "-")
    for ch in ("\u00a0", "\u2009", "\u202f"):
        s = s.replace(ch, " ")
    s = s.replace("\u00ad", "")
    s = s.lower()
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def title_in_source(title, pages) -> bool:
    """Check title appears in source pages. Output True or False."""
    try:
        if not isinstance(title, str):
            return False
        if not isinstance(pages, list):
            return False
        for p in pages:
            if not isinstance(p, str):
                return False
        t = normalise_text(title)
        if len(t) < MIN_TITLE_CHARS:
            return False
        joined = normalise_text(" ".join(pages))
        return t in joined
    except Exception:
        return False


def html_to_text(html_str: str) -> str:
    """Strip tags and scripts from HTML. Output is normalised text."""
    s = re.sub(
        r"<script\b[^>]*>.*?</script\s*>", " ", html_str,
        flags=re.IGNORECASE | re.DOTALL,
    )
    s = re.sub(
        r"<style\b[^>]*>.*?</style\s*>", " ", s,
        flags=re.IGNORECASE | re.DOTALL,
    )
    s = re.sub(
        r"<noscript\b[^>]*>.*?</noscript\s*>", " ", s,
        flags=re.IGNORECASE | re.DOTALL,
    )
    s = re.sub(r"<[^>]*>", " ", s)
    return normalise_text(s)


def pdf_pages(data: bytes) -> list[str]:
    """Read PDF bytes into normalised page texts."""
    try:
        reader = PdfReader(io.BytesIO(data))
        try:
            pages_list = list(reader.pages)
        except Exception as exc:
            raise FetchError(
                "pdf text extraction failed: " + type(exc).__name__
            ) from exc
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(
            "pdf text extraction failed: " + type(exc).__name__
        ) from exc
    if len(pages_list) == 0:
        return []
    out = []
    last_exc: Exception | None = None
    failed = 0
    for page in pages_list:
        try:
            out.append(normalise_text(page.extract_text() or ""))
        except Exception as exc:
            out.append("")
            last_exc = exc
            failed += 1
    if failed == len(pages_list):
        raise FetchError(
            "pdf text extraction failed: " + type(last_exc).__name__
        ) from last_exc
    return out


def mirror_urls(url, doi, http_get, *, timeout_s: float = 30.0) -> list[str]:
    """Find open copies of the same work. Output is URLs."""
    found: list[str] = []
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    if isinstance(url, str) and host.lower() in (
        "pmc.ncbi.nlm.nih.gov",
        "www.ncbi.nlm.nih.gov",
        "ncbi.nlm.nih.gov",
        "europepmc.org",
        "www.europepmc.org",
    ):
        try:
            m = re.search(r"PMC[0-9]+", url)
        except Exception:
            m = None
        if m is not None:
            found.append(EUROPE_PMC_XML_URL.format(pmcid=m.group(0)))
    doi_norm = None
    if isinstance(doi, str):
        s = doi.strip()
        low = s.lower()
        for prefix in (
            "https://doi.org/",
            "http://doi.org/",
            "https://dx.doi.org/",
            "doi:",
        ):
            if low.startswith(prefix):
                s = s[len(prefix):]
                break
        if re.match(r"^10\.\d{4,9}/\S+$", s):
            doi_norm = s
    if doi_norm is not None:
        try:
            resp = http_get(
                OPENALEX_WORK_URL + doi_norm,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout_s,
            )
        except Exception:
            resp = None
        if resp is not None and resp.status_code == 200:
            try:
                body = json.loads(resp.content.decode("utf-8"))
            except Exception:
                body = None
            if isinstance(body, dict):
                ids = body.get("ids")
                if isinstance(ids, dict):
                    pmcid_raw = ids.get("pmcid")
                    if isinstance(pmcid_raw, str):
                        try:
                            mm = re.search(r"PMC[0-9]+", pmcid_raw)
                        except Exception:
                            mm = None
                        if mm is not None:
                            found.append(
                                EUROPE_PMC_XML_URL.format(pmcid=mm.group(0))
                            )
                locs = body.get("locations")
                if locs is None:
                    locs = []
                if isinstance(locs, list):
                    pdfs: list[str] = []
                    landings: list[str] = []
                    for entry in locs:
                        if not isinstance(entry, dict):
                            continue
                        pu = entry.get("pdf_url")
                        if isinstance(pu, str):
                            pdfs.append(pu)
                        lu = entry.get("landing_page_url")
                        if isinstance(lu, str):
                            landings.append(lu)
                    found.extend(pdfs)
                    found.extend(landings)
    out: list[str] = []
    seen: set[str] = set()
    for cand in found:
        if not isinstance(cand, str):
            continue
        if not (cand.startswith("http://") or cand.startswith("https://")):
            continue
        if cand == url:
            continue
        if cand in seen:
            continue
        seen.add(cand)
        out.append(cand)
        if len(out) >= MAX_MIRRORS:
            break
    return out


def fetch_source(url, http_get, *, timeout_s: float = 30.0) -> Source:
    """Fetch URL and return normalised pages. Bytes in bytes."""
    if not isinstance(url, str) or not (
        url.startswith("http://") or url.startswith("https://")
    ):
        raise FetchError("url must start with http:// or https://")
    try:
        resp = http_get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_s,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        raise FetchError(type(exc).__name__) from exc
    if resp.status_code != 200:
        raise FetchError("HTTP " + str(resp.status_code))
    content = bytes(resp.content)
    if len(content) > MAX_SOURCE_BYTES:
        raise FetchError("source larger than MAX_SOURCE_BYTES")
    is_pdf = content[:5] == b"%PDF-"
    if is_pdf:
        pages = pdf_pages(content)
    else:
        pages = [html_to_text(content.decode("utf-8", errors="replace"))]
    if all(p.strip() == "" for p in pages):
        raise FetchError("no text in source")
    final = resp.url if isinstance(getattr(resp, "url", None), str) and resp.url else url
    return Source(
        url=url,
        final_url=final,
        status_code=resp.status_code,
        is_pdf=is_pdf,
        pages=pages,
        bytes_len=len(content),
    )


def find_quote(quote: str, pages: list[str]) -> QuoteMatch:
    """Find normalised quote in normalised pages."""
    q = normalise_text(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return QuoteMatch(False, "none", None, None, None, 0, 0, "")
    norm_pages = [normalise_text(p) for p in pages]
    for idx, text in enumerate(norm_pages):
        pos = text.find(q)
        if pos != -1:
            start = pos
            end = pos + len(q)
            ctx = text[max(0, start - CONTEXT_CHARS): end + CONTEXT_CHARS]
            return QuoteMatch(True, "exact", idx + 1, start, end, 0, 0, ctx)
    qt = [m.group(0) for m in re.finditer(r"[a-z0-9]+", q)]
    if len(qt) < 5:
        return QuoteMatch(False, "none", None, None, None, 0, 0, "")
    max_missing = len(qt) // 10
    max_skipped = max(3, len(qt) // 10)
    for idx, text in enumerate(norm_pages):
        toks = [
            (m.group(0), m.start(), m.end())
            for m in re.finditer(r"[a-z0-9]+", text)
        ]
        for i in range(len(toks)):
            if toks[i][0] != qt[0]:
                continue
            k = i + 1
            last = i
            missing = 0
            skipped = 0
            ok = True
            for qi in range(1, len(qt)):
                tok = qt[qi]
                f = -1
                upper = min(k + 4, len(toks))
                for cand in range(k, upper):
                    if toks[cand][0] == tok:
                        f = cand
                        break
                if f != -1:
                    skipped += f - k
                    k = f + 1
                    last = f
                else:
                    missing += 1
                if missing > max_missing or skipped > max_skipped:
                    ok = False
                    break
            if ok:
                start = toks[i][1]
                end = toks[last][2]
                ctx = text[max(0, start - CONTEXT_CHARS): end + CONTEXT_CHARS]
                return QuoteMatch(
                    True, "near", idx + 1, start, end, skipped, missing, ctx
                )
    return QuoteMatch(False, "none", None, None, None, 0, 0, "")


_PAT_GROUP_COMMA = re.compile(r"(?<![0-9])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![0-9])")
_PAT_GROUP_SPACE = re.compile(r"(?<![0-9])\d{1,3}(?: \d{3})+(?:\.\d+)?(?![0-9])")
_PAT_PLAIN = re.compile(r"(?<![0-9])\d+(?:\.\d+)?(?![0-9])")


def numbers_in(text: str) -> list[float]:
    """Find distinct numbers in text. Output sorted floats."""
    vals: set[float] = set()
    for pat in (_PAT_GROUP_COMMA, _PAT_GROUP_SPACE, _PAT_PLAIN):
        for m in pat.finditer(text):
            raw = m.group(0).replace(",", "").replace(" ", "")
            try:
                vals.add(float(raw))
            except ValueError:
                continue
    return sorted(vals)


def parse_unit(unit: str) -> str:
    """Parse unit string to canonical unit."""
    try:
        s0 = unit.strip().lower()
    except AttributeError:
        raise ValueError("bad unit %r" % (unit,))
    if re.fullmatch(r"(%|percent)\s+of\s+[a-z]+(\s+[a-z]+)*", s0):
        return "%"
    s = s0
    s = s.replace(" ", "")
    if s in ("%", "percent", "pct", "%/yr", "%/year", "%peryear", "%pa"):
        return "%"
    if s in ("frac", "fraction"):
        return "frac"
    s = s.replace("-yr", "/yr")
    s = s.replace("-year", "/yr")
    s = s.replace("per", "/")
    cur = ""
    rest = ""
    for prefix, name in (("us$", "USD"), ("usd", "USD"), ("$", "USD"),
                         ("idr", "IDR"), ("rp", "IDR")):
        if s.startswith(prefix):
            cur = name
            rest = s[len(prefix):]
            break
    if not cur:
        raise ValueError("unknown currency in unit %r" % (unit,))
    if rest.startswith("."):
        rest = rest[1:]
    if not rest.startswith("/"):
        raise ValueError("bad unit %r" % (unit,))
    parts = [p for p in rest.split("/") if p]
    if len(parts) not in (1, 2):
        raise ValueError("bad unit %r" % (unit,))
    table = {
        "kwh": "kWh", "mwh": "MWh", "kw": "kW", "kwp": "kWp",
        "mw": "MW", "mwp": "MWp", "w": "W", "wp": "Wp",
        "l": "L", "lt": "L", "ltr": "L", "liter": "L", "litre": "L",
        "liters": "L", "litres": "L",
        "yr": "yr", "year": "yr", "a": "yr", "annum": "yr",
    }
    mapped = []
    for p in parts:
        if p not in table:
            raise ValueError("unknown unit part in %r" % (unit,))
        mapped.append(table[p])
    return cur + "/" + "/".join(mapped)


_FACTORS = {
    ("USD/kWp", "USD/kWp"): 1.0,
    ("USD/kWp", "USD/kW"): 1.0,
    ("USD/kWp", "USD/Wp"): 1000.0,
    ("USD/kWp", "USD/W"): 1000.0,
    ("USD/kWp", "USD/MWp"): 0.001,
    ("USD/kWp", "USD/MW"): 0.001,
    ("USD/kW", "USD/kW"): 1.0,
    ("USD/kW", "USD/W"): 1000.0,
    ("USD/kW", "USD/MW"): 0.001,
    ("USD/kWh", "USD/kWh"): 1.0,
    ("USD/kWh", "USD/MWh"): 0.001,
    ("USD/kWp/yr", "USD/kWp/yr"): 1.0,
    ("USD/kWp/yr", "USD/kW/yr"): 1.0,
    ("USD/kWp/yr", "USD/MWp/yr"): 0.001,
    ("USD/kWp/yr", "USD/MW/yr"): 0.001,
    ("USD/kWh/yr", "USD/kWh/yr"): 1.0,
    ("USD/kWh/yr", "USD/MWh/yr"): 0.001,
    ("USD/L", "USD/L"): 1.0,
    ("frac", "%"): 0.01,
    ("frac", "frac"): 1.0,
}


def _check_value_num(value) -> float:
    """Check finite int or float, not bool. Output float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("value must be a finite number")
    num = float(value)
    if not math.isfinite(num):
        raise ValueError("value must be a finite number")
    return num


def convert_value(value, unit_canonical: str, target_unit: str, *,
                  fx_idr_per_usd: float | None = None) -> float:
    """Convert value from canonical unit to target unit."""
    num = _check_value_num(value)
    if isinstance(unit_canonical, str) and unit_canonical.startswith("IDR/"):
        fx = fx_idr_per_usd
        if (
            isinstance(fx, bool)
            or not isinstance(fx, (int, float))
            or not math.isfinite(float(fx))
            or float(fx) <= 0
        ):
            raise ValueError("IDR value needs fx_idr_per_usd")
        usd_source = "USD/" + unit_canonical[4:]
        key = (target_unit, usd_source)
        if key not in _FACTORS:
            raise ValueError(
                "cannot convert %s to %s" % (unit_canonical, target_unit)
            )
        return num * _FACTORS[key] / float(fx)
    key = (target_unit, unit_canonical)
    if key not in _FACTORS:
        raise ValueError(
            "cannot convert %s to %s" % (unit_canonical, target_unit)
        )
    return num * _FACTORS[key]


def doi_resolves(doi: str, http_get, *, timeout_s: float = 30.0) -> bool:
    """Check DOI handle API. Output True when registered."""
    s = doi.strip()
    low = s.lower()
    for prefix in (
        "https://doi.org/", "http://doi.org/",
        "https://dx.doi.org/", "doi:",
    ):
        if low.startswith(prefix):
            s = s[len(prefix):]
            break
    if not re.match(r"^10\.\d{4,9}/\S+$", s):
        return False
    try:
        resp = http_get(
            "https://doi.org/api/handles/" + s,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        raise FetchError("doi check: " + type(exc).__name__) from exc
    if resp.status_code == 404:
        return False
    if resp.status_code == 200:
        try:
            body = json.loads(resp.content.decode("utf-8"))
            return body["responseCode"] == 1
        except Exception:
            return False
    raise FetchError("doi check HTTP " + str(resp.status_code))


def support_verdict(judge_fn, claim: Claim, context: str, *, source_title=None, source_url=None) -> Verdict:
    """Ask judge if quote supports claim. Output verdict."""
    if isinstance(source_title, str) and source_title.strip() != "":
        title_text = source_title.strip()[:MAX_PROMPT_TITLE_CHARS]
    else:
        title_text = "(not shown)"
    if isinstance(source_url, str) and source_url.strip() != "":
        url_text = source_url.strip()[:MAX_PROMPT_URL_CHARS]
    else:
        url_text = "(not shown)"
    prompt = (
        SUPPORT_INSTRUCTIONS + "\n\nInput: " + claim.description
        + "\nSource title: " + title_text
        + "\nSource URL: " + url_text
        + "\nClaimed value: " + str(claim.value) + " " + claim.unit
        + "\nQuote: " + claim.quote
        + "\nSource context:\n" + context[:MAX_PROMPT_CONTEXT_CHARS]
    )
    try:
        raw_out = judge_fn(prompt)
    except Exception as exc:
        return Verdict(None, "judge error: " + type(exc).__name__, "")
    raw = raw_out if isinstance(raw_out, str) else str(raw_out)
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        rest = "\n".join(lines[1:])
        cut = rest.rfind("```")
        if cut != -1:
            rest = rest[:cut]
        text = rest
    parsed = None
    try:
        parsed = json.loads(text)
    except Exception:
        parsed = None
        m = re.search(r"\{.*\}", text, re.S)
        if m is not None:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = None
    if (
        isinstance(parsed, dict)
        and isinstance(parsed.get("supports"), bool)
        and isinstance(parsed.get("reason"), str)
    ):
        return Verdict(
            parsed["supports"], parsed["reason"][:500], raw[:2000]
        )
    return Verdict(None, "unparsed judge answer", raw[:2000])


def support_votes(judge_fn, claim: Claim, context: str, *, source_title=None,
                  source_url=None, votes: int = JUDGE_VOTES) -> tuple[Verdict, int]:
    """Ask judge up to votes times. Output verdict and call count."""
    if isinstance(votes, bool) or not isinstance(votes, int) or votes < 1:
        raise ValueError("votes must be an int >= 1")
    if isinstance(judge_fn, list):
        raise ValueError("a judge panel must be a tuple")
    if isinstance(judge_fn, tuple):
        if len(judge_fn) != votes or any(not callable(j) for j in judge_fn):
            raise ValueError("a judge panel must hold votes callables")
        verdict: Verdict | None = None
        made = 0
        for k in range(votes):
            verdict = support_verdict(judge_fn[k], claim, context,
                                      source_title=source_title,
                                      source_url=source_url)
            made += 1
            if verdict.supports is not True:
                break
        assert verdict is not None
        return (verdict, made)
    verdict = None
    made = 0
    for _ in range(votes):
        verdict = support_verdict(judge_fn, claim, context,
                                  source_title=source_title,
                                  source_url=source_url)
        made += 1
        if verdict.supports is not True:
            break
    assert verdict is not None
    return (verdict, made)


def check_citation(claim, *, http_get, judge_fn, judge_name: str,
                   target_unit: str, band_lo: float, band_hi: float,
                   fx_idr_per_usd: float | None = None,
                   timeout_s: float = 30.0) -> CitationCheck:
    """Run script checks then judge. Output checked or assumed."""
    _check_value_num(claim.value)
    reasons: list[str] = []
    value_converted: float | None = None
    try:
        canon = parse_unit(claim.unit)
        value_converted = convert_value(
            claim.value, canon, target_unit,
            fx_idr_per_usd=fx_idr_per_usd,
        )
    except ValueError as exc:
        reasons.append("unit: " + str(exc))
        value_converted = None
    else:
        if value_converted < band_lo or value_converted > band_hi:
            reasons.append(
                "value %g %s outside band [%g, %g]"
                % (value_converted, target_unit, band_lo, band_hi)
            )
    source = None
    mirror_match = None
    try:
        source = fetch_source(claim.url, http_get, timeout_s=timeout_s)
    except FetchError as exc:
        fetch_reason = "fetch: " + str(exc)
        reasons.append(fetch_reason)
        source = None
        msg = str(exc)
        code = None
        if msg.startswith("HTTP "):
            try:
                code = int(msg[5:].strip().split()[0])
            except Exception:
                code = None
        if code in BLOCKED_STATUS:
            try:
                mirrors = mirror_urls(claim.url, claim.doi, http_get, timeout_s=timeout_s)
            except Exception:
                mirrors = []
            used = None
            for m_url in mirrors:
                try:
                    cand = fetch_source(m_url, http_get, timeout_s=timeout_s)
                except Exception:
                    continue
                mq = find_quote(claim.quote, cand.pages)
                if mq.found:
                    used = cand
                    mirror_match = mq
                    break
            if used is not None:
                try:
                    reasons.remove(fetch_reason)
                except ValueError:
                    pass
                source = used
            else:
                if len(mirrors) > 0:
                    reasons.append(
                        "mirror: no open copy with the quote (%d tried)" % len(mirrors)
                    )
    match = None
    quote_kind = "not run"
    page_text = ""
    if source is not None:
        if mirror_match is not None:
            match = mirror_match
        else:
            match = find_quote(claim.quote, source.pages)
        quote_kind = match.kind
        if not match.found:
            reasons.append("quote not found in source")
        else:
            page_text = source.pages[match.page - 1]
            nums = numbers_in(page_text[match.start: match.end])
            tol = 1e-9 * max(1, abs(float(claim.value)))
            if not any(abs(n - float(claim.value)) <= tol for n in nums):
                reasons.append("value not in the quoted source text")
    doi_ok: bool | None = None
    if isinstance(claim.doi, str) and claim.doi != "":
        try:
            ok = doi_resolves(claim.doi, http_get, timeout_s=timeout_s)
        except FetchError as exc:
            reasons.append("doi check failed: " + str(exc))
            doi_ok = None
        else:
            doi_ok = ok
            if not ok:
                reasons.append("doi does not resolve")
    supports: bool | None = None
    judge_reason = ""
    judge_calls = 0
    context = ""
    if match is not None and match.found:
        context = match.context
    if not reasons:
        show_title = None
        if source is not None and title_in_source(claim.title, source.pages):
            show_title = claim.title
        verdict, judge_calls = support_votes(
            judge_fn, claim, context, source_title=show_title,
            source_url=source.final_url if source is not None else None,
            votes=JUDGE_VOTES)
        supports = verdict.supports
        judge_reason = verdict.reason
        if verdict.supports is False:
            reasons.append("judge says not supported: " + verdict.reason)
        elif verdict.supports is None:
            reasons.append("judge gave no verdict: " + verdict.reason)
    status = "checked" if not reasons else "assumed"
    return CitationCheck(
        input_name=claim.input_name,
        status=status,
        reasons=reasons,
        value_as_written=float(claim.value),
        unit_as_written=claim.unit,
        value_converted=value_converted,
        target_unit=target_unit,
        url=claim.url,
        final_url=source.final_url if source is not None else None,
        is_pdf=source.is_pdf if source is not None else None,
        page=match.page if (match is not None and match.found) else None,
        quote_kind=quote_kind,
        doi=claim.doi,
        doi_ok=doi_ok,
        supports=supports,
        judge_reason=judge_reason,
        judge_name=judge_name,
        context=context,
        judge_calls=judge_calls,
    )
