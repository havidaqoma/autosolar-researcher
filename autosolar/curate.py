"""Curated post hoc inputs picked by hand. Values keep input units, money in USD."""

import copy
import dataclasses
import hashlib
import json
import math
import re
from pathlib import Path

from autosolar.sourcing import CURATED_JUDGE, CURATED_PREFIX, SourcingRow, load_targets, read_sourcing, write_sourcing

CURATED_SCHEMA = "autosolar.curated/1"
ENTRY_KEYS = ("input", "value", "unit", "label", "title", "url", "doi", "page", "quote_kind", "quote",
              "value_as_written", "unit_as_written", "currency_year", "derivation")

_INPUT_RE = r"[a-z][a-z0-9_]*"


@dataclasses.dataclass(frozen=True)
class CuratedEntry:
    """One hand picked input. Value in unit, money in USD."""

    input: str
    value: float | int
    unit: str
    label: str
    title: str
    url: str
    doi: str | None
    page: int | None
    quote_kind: str
    quote: str
    value_as_written: float | int | None
    unit_as_written: str
    currency_year: int | None
    derivation: str


def _is_num(value: object) -> bool:
    """Check finite int or float, not bool. Output bool."""
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (ValueError, OverflowError):
        return False


def _need_ascii(value: object, what: str) -> str:
    """Checked non-empty ASCII string. Output the string."""
    if not isinstance(value, str) or value == "" or not value.isascii():
        raise ValueError("curated entry bad " + what + ": " + repr(value))
    return value


def _check_entry(item: dict) -> None:
    """Check one curated entry dict. Raises ValueError on any broken rule."""
    if not isinstance(item, dict):
        raise ValueError("curated entry must be a dict: " + repr(item))
    if set(item.keys()) != set(ENTRY_KEYS):
        raise ValueError("curated entry has bad keys: " + repr(item.get("input")))
    name = item.get("input")
    if not isinstance(name, str) or re.fullmatch(_INPUT_RE, name) is None:
        raise ValueError("curated entry bad input: " + repr(name))
    value = item.get("value")
    if not _is_num(value) or not float(value) > 0:  # type: ignore[arg-type]
        raise ValueError("curated entry bad value for " + str(name) + ": " + repr(value))
    _need_ascii(item.get("unit"), "unit for " + str(name))
    if item.get("label") not in ("paper", "docs"):
        raise ValueError("curated entry bad label for " + str(name) + ": " + repr(item.get("label")))
    _need_ascii(item.get("title"), "title for " + str(name))
    url = item.get("url")
    if not isinstance(url, str) or not url.isascii() or not url.startswith("https://"):
        raise ValueError("curated entry bad url for " + str(name) + ": " + repr(url))
    doi = item.get("doi")
    if doi is not None and (not isinstance(doi, str) or doi == "" or not doi.isascii()):
        raise ValueError("curated entry bad doi for " + str(name) + ": " + repr(doi))
    page = item.get("page")
    if page is not None and (type(page) is not int or page < 1):
        raise ValueError("curated entry bad page for " + str(name) + ": " + repr(page))
    if item.get("quote_kind") not in ("exact", "table"):
        raise ValueError("curated entry bad quote_kind for " + str(name) + ": " + repr(item.get("quote_kind")))
    quote = item.get("quote")
    if not isinstance(quote, str) or quote == "" or not quote.isascii() or len(quote) > 600:
        raise ValueError("curated entry bad quote for " + str(name))
    written = item.get("value_as_written")
    if written is not None and not _is_num(written):
        raise ValueError("curated entry bad value_as_written for " + str(name) + ": " + repr(written))
    unit_written = item.get("unit_as_written")
    if not isinstance(unit_written, str) or not unit_written.isascii():
        raise ValueError("curated entry bad unit_as_written for " + str(name) + ": " + repr(unit_written))
    year = item.get("currency_year")
    if year is not None and (type(year) is not int or not 1990 <= year <= 2100):
        raise ValueError("curated entry bad currency_year for " + str(name) + ": " + repr(year))
    derivation = item.get("derivation")
    if not isinstance(derivation, str) or derivation == "" or not derivation.isascii() or len(derivation) > 600:
        raise ValueError("curated entry bad derivation for " + str(name))


def load_curated(path: object) -> tuple[list[CuratedEntry], str]:
    """Read curated inputs file. Returns entries in file order and sha256 hex."""
    raw_bytes = Path(path).read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    doc = json.loads(raw_bytes)
    if not isinstance(doc, dict):
        raise ValueError("curated file top level must be a dict")
    if set(doc.keys()) != {"schema", "note", "entries"}:
        raise ValueError("curated file must have exactly schema, note, entries")
    if doc.get("schema") != CURATED_SCHEMA:
        raise ValueError("curated file bad schema: " + repr(doc.get("schema")))
    if not isinstance(doc.get("note"), str):
        raise ValueError("curated file bad note")
    raw_entries = doc.get("entries")
    if not isinstance(raw_entries, list) or len(raw_entries) == 0:
        raise ValueError("curated file entries must be a non-empty list")
    seen: set[str] = set()
    out: list[CuratedEntry] = []
    for item in raw_entries:
        _check_entry(item)
        name = item["input"]
        if name in seen:
            raise ValueError("curated file duplicate input: " + str(name))
        seen.add(name)
        out.append(CuratedEntry(**item))
    return out, digest


def curated_note(entry: CuratedEntry) -> str:
    """Note stored on a curated input. Text is ASCII."""
    text = CURATED_PREFIX + entry.title + "; " + entry.url
    if entry.page is not None:
        text = text + "; page " + str(entry.page)
    text = text + "; quote " + entry.quote_kind
    if entry.value_as_written is not None:
        text = text + "; as written " + format(entry.value_as_written, "g") + " " + entry.unit_as_written
    if entry.currency_year is not None:
        text = text + "; currency year " + str(entry.currency_year)
    return text + "; " + entry.derivation


def curated_line(count_curated: int, count_rows: int) -> str:
    """One line on post hoc curation. Counts are ints."""
    return (str(count_curated) + " of " + str(count_rows)
            + " inputs were curated by hand after pre-registration (post hoc), from the documents named in the "
              "table. Quote match exact means the quote is word for word from the page; table means the value was "
              "read by eye from a table image and no script checked it.")


def apply_curated(inputs_raw: dict, rows: list[SourcingRow], entries: list[CuratedEntry],
                  targets: list) -> tuple[dict, list[SourcingRow], list[dict]]:
    """Replace weak inputs with curated values. Units stay as entry unit."""
    new_raw = copy.deepcopy(inputs_raw)
    values = new_raw.get("values")
    if not isinstance(values, dict):
        raise ValueError("inputs file has no values dict")
    new_by_input: dict[str, SourcingRow] = {}
    for entry in entries:
        if entry.input not in values or not isinstance(values.get(entry.input), dict):
            raise ValueError("unknown input: " + str(entry.input))
        old = values[entry.input]
        if old.get("unit") != entry.unit:
            raise ValueError("unit mismatch for input: " + str(entry.input))
        old_value = old.get("value")
        if type(old_value) is int:
            if type(entry.value) is not int:
                raise ValueError("int input needs an int value: " + str(entry.input))
            stored: float | int = entry.value
        elif isinstance(old_value, float):
            stored = float(entry.value)
        else:
            raise ValueError("bad old value for input: " + str(entry.input))
        for target in targets:
            if target.input == entry.input:
                if not float(target.band_lo) <= float(stored) <= float(target.band_hi):
                    raise ValueError("curated value outside band for input: " + str(entry.input))
        values[entry.input] = {"value": stored, "unit": entry.unit, "label": entry.label,
                               "note": curated_note(entry)}
        new_by_input[entry.input] = SourcingRow(entry.input, "curated", entry.label, stored, entry.unit,
                                               entry.value_as_written, entry.unit_as_written, entry.currency_year,
                                               entry.title, entry.url, entry.doi, None, entry.page,
                                               entry.quote_kind, entry.quote, None, CURATED_JUDGE, [], 0.0)
    new_rows: list[SourcingRow] = []
    placed: set[str] = set()
    replaced: list[dict] = []
    for row in rows:
        if row.input in new_by_input and row.input not in placed:
            new_rows.append(new_by_input[row.input])
            placed.add(row.input)
            replaced.append(dataclasses.asdict(row))
        elif row.input in new_by_input:
            replaced.append(dataclasses.asdict(row))
        else:
            new_rows.append(row)
    for entry in entries:
        if entry.input not in placed:
            new_rows.append(new_by_input[entry.input])
            placed.add(entry.input)
    return new_raw, new_rows, replaced


def curate_run(base_sourcing_path: object, curated_path: object, targets_path: object, runs_dir: object,
               run_id: str) -> Path:
    """Write a curated sourcing run. Paths in, folder out."""
    base_inputs, base_rows, base_meta = read_sourcing(base_sourcing_path)
    targets, _fx = load_targets(targets_path)
    entries, sha = load_curated(curated_path)
    new_inputs, new_rows, replaced = apply_curated(base_inputs, base_rows, entries, targets)
    folder = Path(runs_dir) / run_id
    if folder.exists():
        raise ValueError("run folder exists: " + str(folder))
    folder.mkdir(parents=True)
    judge = base_meta.get("judge") if isinstance(base_meta, dict) else None
    judge = judge if isinstance(judge, str) else None
    fx = base_meta.get("fx_idr_per_usd") if isinstance(base_meta, dict) else None
    meta = {"run_id": run_id, "post_hoc": True, "curated_from": str(base_sourcing_path),
            "curated_file": str(curated_path), "curated_sha256": sha,
            "curated_inputs": [entry.input for entry in entries], "replaced_rows": replaced, "judge": judge,
            "fx_idr_per_usd": fx, "base_meta": base_meta}
    write_sourcing(folder / "sourcing.json", new_inputs, new_rows, meta)
    (folder / "inputs.json").write_text(json.dumps(new_inputs, indent=1, ensure_ascii=True) + "\n",
                                        encoding="utf-8")
    read_sourcing(folder / "sourcing.json")
    return folder
