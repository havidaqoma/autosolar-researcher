"""Stage S3 sourced inputs. Money in USD, energy in kWh, power in kW."""

import copy
import dataclasses
import json
import math
import re
import unicodedata
from pathlib import Path

import requests

from autosolar.cite_check import Claim, check_citation, parse_unit
from autosolar.ledger import BudgetExceeded

SOURCING_SCHEMA = "autosolar.sourcing/1"
TARGETS_SCHEMA = "autosolar.sourcing_targets/1"
TARGET_UNITS = ("USD/kWp", "USD/kW", "USD/kWh", "USD/kWp/yr", "USD/kWh/yr", "USD/L", "frac")
SEARCH_ESTIMATE_USD = 0.10
GLIMMER_URL = "http://127.0.0.1:8093/v1/chat/completions"
CHECKED_PREFIX = "S3 checked: "

SEARCH_INSTRUCTIONS = (
    "You find one published number for an energy model input. Use web search. Prefer reports from IRENA, IEA, "
    "NREL, ADB, World Bank, IESR, government sources or peer-reviewed papers, published in 2021 or later.\n"
    "Return only one JSON object, no prose, no code fence, with keys:\n"
    '  "value": the number as written in the source (number),\n'
    '  "unit": the unit as written in the source (string),\n'
    '  "currency_year": the year the money is expressed in, or null (integer or null),\n'
    '  "url": the page or PDF where the number appears (string),\n'
    '  "doi": the DOI if the source has one, else null,\n'
    '  "title": the source title (string),\n'
    '  "quote": one sentence or table row copied exactly from the source that contains the number (string).\n'
    "If you cannot find a source, return {\"value\": null, \"reason\": \"...\"}."
)


@dataclasses.dataclass
class Target:
    """One input to source. Bands use target_unit."""

    input: str
    target_unit: str
    band_lo: float
    band_hi: float
    description: str
    search_brief: str


@dataclasses.dataclass
class SourcingRow:
    """One sourcing outcome. Money in USD, cost in USD."""

    input: str
    status: str
    label: str
    value_used: float | int
    unit: str
    value_as_written: float | int | None
    unit_as_written: str
    currency_year: int | None
    title: str
    url: str
    doi: str | None
    doi_ok: bool | None
    page: int | None
    quote_kind: str
    quote: str
    supports: bool | None
    judge_name: str
    reasons: list[str]
    search_cost_usd: float


def ascii_text(text: str) -> str:
    """Map quotes and dashes to ASCII. Output is ASCII."""
    s = text.replace("\u2018", "'").replace("\u2019", "'")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    for ch in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
        s = s.replace(ch, "-")
    for ch in ("\u00a0", "\u2009", "\u202f"):
        s = s.replace(ch, " ")
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def _is_num(value) -> bool:
    """Check finite int or float, not bool. Output bool."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (ValueError, OverflowError):
        return False


def _is_ascii_str(value) -> bool:
    """Check non empty ASCII str. Output bool."""
    return isinstance(value, str) and value != "" and value.isascii()


def load_targets(path) -> tuple[list[Target], float]:
    """Read targets file. Bands in target_unit, fx in IDR per USD."""
    with open(path, encoding="utf-8") as handle:
        doc = json.load(handle)
    if not isinstance(doc, dict):
        raise ValueError("targets file top level must be a dict")
    if set(doc.keys()) != {"schema", "note", "fx_idr_per_usd", "targets"}:
        raise ValueError("targets file must have exactly schema, note, fx_idr_per_usd, targets")
    if doc.get("schema") != TARGETS_SCHEMA:
        raise ValueError("targets file bad schema: " + repr(doc.get("schema")))
    if not isinstance(doc.get("note"), str):
        raise ValueError("targets file bad note")
    fx = doc.get("fx_idr_per_usd")
    if not isinstance(fx, dict) or set(fx.keys()) != {"value", "label", "note"}:
        raise ValueError("targets file bad fx_idr_per_usd keys")
    fx_value = fx.get("value")
    if not _is_num(fx_value) or float(fx_value) <= 0:
        raise ValueError("targets file bad fx value: " + repr(fx_value))
    if fx.get("label") != "assumed":
        raise ValueError("targets file fx label must be assumed")
    if not isinstance(fx.get("note"), str):
        raise ValueError("targets file bad fx note")
    raw_targets = doc.get("targets")
    if not isinstance(raw_targets, list) or len(raw_targets) == 0:
        raise ValueError("targets file targets must be a non empty list")
    seen: set[str] = set()
    out: list[Target] = []
    for item in raw_targets:
        if not isinstance(item, dict):
            raise ValueError("targets file bad target entry: " + repr(item))
        want = {"input", "target_unit", "band_lo", "band_hi", "description", "search_brief"}
        if set(item.keys()) != want:
            raise ValueError("target has bad keys: " + repr(item.get("input")))
        name = item.get("input")
        unit = item.get("target_unit")
        lo = item.get("band_lo")
        hi = item.get("band_hi")
        desc = item.get("description")
        brief = item.get("search_brief")
        if not _is_ascii_str(name):
            raise ValueError("target bad input: " + repr(name))
        if not _is_ascii_str(desc):
            raise ValueError("target bad description for " + str(name))
        if not _is_ascii_str(brief):
            raise ValueError("target bad search_brief for " + str(name))
        if unit not in TARGET_UNITS:
            raise ValueError("target bad target_unit for " + str(name) + ": " + repr(unit))
        if not _is_num(lo):
            raise ValueError("target bad band_lo for " + str(name))
        if not _is_num(hi):
            raise ValueError("target bad band_hi for " + str(name))
        if not float(lo) < float(hi):
            raise ValueError("target band_lo not below band_hi for " + str(name))
        if name in seen:
            raise ValueError("target duplicate input: " + str(name))
        seen.add(name)
        out.append(Target(name, unit, float(lo), float(hi), desc, brief))
    return out, float(fx_value)


def parse_answer(text: str) -> dict | None:
    """Parse model answer text. Output dict or None."""
    s = text.strip()
    if s.startswith("```"):
        lines = s.split("\n")
        rest = "\n".join(lines[1:]) if len(lines) >= 2 else ""
        cut = rest.rfind("```")
        if cut != -1:
            rest = rest[:cut]
        s = rest
    try:
        obj = json.loads(s)
    except Exception:
        obj = None
        match = re.search(r"\{.*\}", s, re.S)
        if match is None:
            return None
        try:
            obj = json.loads(match.group(0))
        except Exception:
            return None
    if isinstance(obj, dict):
        return obj
    return None


def search_claim(client, run_id: str, target: Target) -> tuple[Claim | None, str, float]:
    """Search one value. Returns claim or reason plus cost in USD."""
    messages = [
        {"role": "system", "content": SEARCH_INSTRUCTIONS},
        {"role": "user", "content": "Input: " + target.input + " (" + target.target_unit + "). Find: " + target.search_brief + "."},
    ]
    try:
        result = client.respond(
            run_id,
            "S3_search",
            messages,
            estimate_usd=SEARCH_ESTIMATE_USD,
            tools=[{"type": "web_search"}],
            include=["web_search_call.results"],
        )
    except BudgetExceeded:
        raise
    except Exception as exc:
        return None, "search error: " + type(exc).__name__, 0.0
    cost = float(result.cost_usd)
    answer = parse_answer(result.text)
    if answer is None:
        return None, "search answer not JSON", cost
    if answer.get("value") is None:
        reason_raw = answer.get("reason") or ""
        return None, "no source found: " + ascii_text(str(reason_raw))[:200], cost
    if not _is_num(answer.get("value")):
        return None, "search answer field value invalid", cost
    for key in ("unit", "url", "quote"):
        val = answer.get(key)
        if not isinstance(val, str) or val.strip() == "":
            return None, "search answer field " + key + " invalid", cost
    if "doi" in answer:
        doi_val = answer.get("doi")
        if doi_val is not None and not isinstance(doi_val, str):
            return None, "search answer field doi invalid", cost
    if "currency_year" in answer:
        year_val = answer.get("currency_year")
        if year_val is not None and (isinstance(year_val, bool) or not isinstance(year_val, int)):
            return None, "search answer field currency_year invalid", cost
    raw_doi = answer.get("doi")
    if isinstance(raw_doi, str):
        doi_str = raw_doi.strip()
        doi = doi_str if doi_str != "" else None
    else:
        doi = None
    raw_title = answer.get("title")
    title = raw_title if isinstance(raw_title, str) else ""
    raw_year = answer.get("currency_year")
    if isinstance(raw_year, int) and not isinstance(raw_year, bool):
        year = raw_year
    else:
        year = None
    claim = Claim(
        input_name=target.input,
        description=target.description,
        value=answer.get("value"),
        unit=str(answer.get("unit")).strip(),
        url=str(answer.get("url")).strip(),
        doi=doi,
        quote=answer.get("quote"),
        title=title,
        currency_year=year,
    )
    return claim, "", cost


def glimmer_judge(prompt: str, *, post=requests.post, url: str = GLIMMER_URL, timeout_s: float = 900.0) -> str:
    """Ask local judge. Output is raw text."""
    body = {
        "model": "muse-glimmer",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8192,
        "temperature": 1.0,
        "top_p": 0.95,
        "top_k": 64,
        "chat_template_kwargs": {"reasoning_strength": "low"},
    }
    resp = post(url, json=body, timeout=timeout_s)
    if resp.status_code != 200:
        raise RuntimeError("glimmer HTTP " + str(resp.status_code))
    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError("glimmer answer has no content") from exc
    if not isinstance(content, str):
        raise RuntimeError("glimmer answer has no content")
    return content


def source_inputs(
    base_raw: dict,
    targets: list[Target],
    *,
    client,
    run_id: str,
    http_get,
    judge_fn,
    judge_name: str,
    fx_idr_per_usd: float,
) -> tuple[dict, list[SourcingRow]]:
    """Source each target in order. Values keep target_unit."""
    base_values = base_raw.get("values")
    if not isinstance(base_values, dict):
        raise ValueError("inputs file has no values dict")
    for target in targets:
        if target.input not in base_values:
            raise ValueError("unknown input: " + str(target.input))
        entry = base_values.get(target.input)
        if not isinstance(entry, dict) or entry.get("unit") != target.target_unit:
            raise ValueError("unit mismatch for input: " + str(target.input))
    new_raw = copy.deepcopy(base_raw)
    new_values = new_raw["values"]
    rows: list[SourcingRow] = []
    for target in targets:
        claim, reason, cost = search_claim(client, run_id, target)
        if claim is None:
            entry = new_values[target.input]
            rows.append(
                SourcingRow(
                    target.input,
                    "assumed",
                    entry["label"],
                    entry["value"],
                    entry["unit"],
                    None,
                    "",
                    None,
                    "",
                    "",
                    None,
                    None,
                    None,
                    "not run",
                    "",
                    None,
                    judge_name,
                    [reason],
                    float(cost),
                )
            )
            continue
        check = check_citation(
            claim,
            http_get=http_get,
            judge_fn=judge_fn,
            judge_name=judge_name,
            target_unit=target.target_unit,
            band_lo=target.band_lo,
            band_hi=target.band_hi,
            fx_idr_per_usd=fx_idr_per_usd,
        )
        final_url = check.final_url or claim.url
        if check.status == "checked":
            canon = parse_unit(claim.unit)
            rounded = float(format(check.value_converted, ".6g"))
            label = "paper" if check.doi_ok is True else "docs"
            note = CHECKED_PREFIX + ascii_text(claim.title or "untitled") + "; " + str(check.final_url)
            if check.is_pdf:
                note = note + "; page " + str(check.page)
            note = note + "; quote " + str(check.quote_kind)
            note = note + "; as written " + format(claim.value, "g") + " " + ascii_text(claim.unit)
            if claim.currency_year is not None:
                note = note + "; currency year " + str(claim.currency_year)
            if canon.startswith("IDR/"):
                note = note + "; fx " + format(fx_idr_per_usd, "g") + " IDR per USD assumed"
            note = note + "; support judged by " + judge_name
            new_values[target.input] = {"value": rounded, "unit": target.target_unit, "label": label, "note": note}
            rows.append(
                SourcingRow(
                    target.input,
                    "checked",
                    label,
                    rounded,
                    target.target_unit,
                    claim.value,
                    claim.unit,
                    claim.currency_year,
                    ascii_text(claim.title),
                    final_url,
                    claim.doi,
                    check.doi_ok,
                    check.page,
                    check.quote_kind,
                    ascii_text(claim.quote),
                    check.supports,
                    judge_name,
                    [],
                    float(cost),
                )
            )
        else:
            entry = new_values[target.input]
            rows.append(
                SourcingRow(
                    target.input,
                    "assumed",
                    entry["label"],
                    entry["value"],
                    entry["unit"],
                    claim.value,
                    claim.unit,
                    claim.currency_year,
                    ascii_text(claim.title),
                    final_url,
                    claim.doi,
                    check.doi_ok,
                    check.page,
                    check.quote_kind,
                    ascii_text(claim.quote),
                    check.supports,
                    judge_name,
                    list(check.reasons),
                    float(cost),
                )
            )
    return new_raw, rows


def g6_check(rows: list[SourcingRow], inputs_raw: dict) -> tuple[bool, str]:
    """Check rows agree with inputs. Counts use rows."""
    values = inputs_raw.get("values", {})
    if not isinstance(values, dict):
        values = {}
    for row in rows:
        if row.input not in values:
            return False, row.input + ": not in inputs"
        entry = values.get(row.input)
        if not isinstance(entry, dict):
            if row.status == "checked":
                return False, row.input + ": checked row does not match its input"
            return False, row.input + ": assumed row does not match its input"
        if row.status == "checked":
            note = entry.get("note")
            ok = (
                row.reasons == []
                and row.supports is True
                and row.quote_kind in ("exact", "near")
                and entry.get("label") == row.label
                and row.label in ("paper", "docs")
                and entry.get("value") == row.value_used
                and entry.get("unit") == row.unit
                and isinstance(note, str)
                and note.startswith(CHECKED_PREFIX)
            )
            if not ok:
                return False, row.input + ": checked row does not match its input"
        elif row.status == "assumed":
            note = entry.get("note")
            ok = (
                isinstance(row.reasons, list)
                and len(row.reasons) > 0
                and entry.get("label") == row.label
                and entry.get("value") == row.value_used
                and isinstance(note, str)
                and not note.startswith(CHECKED_PREFIX)
            )
            if not ok:
                return False, row.input + ": assumed row does not match its input"
        else:
            return False, row.input + ": unknown status"
    have = {row.input for row in rows}
    for name in values:
        entry = values.get(name)
        if not isinstance(entry, dict):
            continue
        note = entry.get("note")
        if isinstance(note, str) and note.startswith(CHECKED_PREFIX) and name not in have:
            return False, name + ": checked note without a sourcing row"
    count_checked = sum(1 for row in rows if row.status == "checked")
    count_assumed = sum(1 for row in rows if row.status == "assumed")
    total = len(rows)
    return True, str(count_checked) + " of " + str(total) + " sourced inputs checked, " + str(count_assumed) + " kept assumed"


def write_sourcing(path, inputs_raw: dict, rows: list[SourcingRow], meta: dict) -> None:
    """Write sourcing file. Money in USD."""
    doc = {
        "schema": SOURCING_SCHEMA,
        "meta": meta,
        "inputs": inputs_raw,
        "rows": [dataclasses.asdict(row) for row in rows],
    }
    out = Path(path)
    parent = out.parent
    if str(parent) != "" and not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, ensure_ascii=True), encoding="utf-8")


def read_sourcing(path) -> tuple[dict, list[SourcingRow], dict]:
    """Read sourcing file. Returns inputs, rows, meta."""
    text = Path(path).read_text(encoding="utf-8")
    doc = json.loads(text)
    if not isinstance(doc, dict) or doc.get("schema") != SOURCING_SCHEMA:
        raise ValueError("sourcing file bad schema: " + repr(doc.get("schema") if isinstance(doc, dict) else doc))
    try:
        inputs_raw = doc["inputs"]
        rows_raw = doc["rows"]
        meta = doc["meta"]
    except KeyError as exc:
        raise ValueError("sourcing file missing key: " + str(exc)) from exc
    want = {field.name for field in dataclasses.fields(SourcingRow)}
    if not isinstance(rows_raw, list):
        raise ValueError("sourcing file bad rows")
    rows: list[SourcingRow] = []
    for item in rows_raw:
        if not isinstance(item, dict) or set(item.keys()) != want:
            raise ValueError("sourcing file bad row: " + repr(item))
        rows.append(SourcingRow(**item))
    ok, detail = g6_check(rows, inputs_raw)
    if not ok:
        raise ValueError("sourcing file fails G6: " + detail)
    return inputs_raw, rows, meta
