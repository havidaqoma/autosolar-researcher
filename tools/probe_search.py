"""Probe for stage S3 (sourced inputs). Orchestrator tooling, not pipeline code.

  AUTOSOLAR_ENV_FILE=path/to/.env uv run python tools/probe_search.py

Asks the contributor model, with the web_search tool on, for one sourced value per input and a verbatim quote.
Then fetches every URL it names and checks whether the quote appears in the fetched text. Saves everything to
runs/search_probe/probe.json, so the S3 spec can be written from measured behaviour, not from the docs alone.
"""
import html
import json
import os
import pathlib
import re
import sys
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.ledger import Ledger  # noqa: E402
from autosolar.meta_client import MetaClient  # noqa: E402

TARGETS = [
    ("battery_capex_usd_per_kwh", "USD per kWh",
     "installed capital cost of a lithium-ion battery energy storage system, per kWh of storage energy, "
     "for utility or mini-grid scale, in Indonesia or Southeast Asia if available"),
    ("pv_capex_usd_per_kwp", "USD per kWp",
     "installed capital cost of a ground-mounted solar PV plant per kWp (or per kW DC), in Indonesia"),
    ("fuel_price_usd_per_l", "IDR or USD per litre",
     "price of industrial (non-subsidised) diesel fuel (solar / biosolar B35 or B40, industri) in Indonesia"),
    ("discount_rate_frac", "percent per year",
     "discount rate or weighted average cost of capital used for renewable energy projects in Indonesia"),
]

INSTRUCTIONS = (
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

UA = "AutoSolarResearcher/0.1 (pre-feasibility research tool; contact via GitHub havidaqoma)"


def load_key():
    if os.environ.get("MODEL_API_KEY"):
        return
    env_file = pathlib.Path(os.environ.get("AUTOSOLAR_ENV_FILE", ROOT / ".env"))
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("MODEL_API_KEY="):
            os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip()
            return
    sys.exit("MODEL_API_KEY not found")


def norm(text):
    text = html.unescape(text)
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-").replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def page_text(body, ctype):
    if "html" in ctype or body.lstrip().startswith("<"):
        body = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", body)
        body = re.sub(r"(?s)<[^>]+>", " ", body)
    return norm(body)


def fetch(url):
    row = {"url": url}
    t = time.perf_counter()
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=30, allow_redirects=True)
        row.update(status=r.status_code, ctype=r.headers.get("content-type", ""), bytes=len(r.content),
                   final_url=r.url)
        row["is_pdf"] = r.content[:5] == b"%PDF-"
        row["text"] = "" if row["is_pdf"] else page_text(r.text, row["ctype"])
    except requests.RequestException as exc:
        row.update(status=None, error=type(exc).__name__ + ": " + str(exc)[:200], text="")
    row["seconds"] = round(time.perf_counter() - t, 2)
    return row


def parse_json(text):
    s = text.strip()
    if s.startswith("```"):
        s = "\n".join(s.splitlines()[1:])
        s = s.rsplit("```", 1)[0]
    try:
        return json.loads(s)
    except ValueError:
        m = re.search(r"\{.*\}", s, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                return None
    return None


def main():
    load_key()
    client = MetaClient(Ledger(ROOT / "ledger" / "api_usage.jsonl"), timeout_s=180.0)
    rows = []
    for name, unit, what in TARGETS:
        t = time.perf_counter()
        r = client.respond("probe_S3_search", "S3_probe", [
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": "Input: " + name + " (" + unit + "). Find: " + what + "."},
        ], estimate_usd=0.05, tools=[{"type": "web_search"}], include=["web_search_call.results"])
        secs = round(time.perf_counter() - t, 2)
        results = []
        for item in r.raw.get("output") or []:
            if isinstance(item, dict) and item.get("type") == "web_search_call":
                for res in item.get("results") or []:
                    results.append({k: res.get(k) for k in ("type", "title", "url", "snippet")})
        answer = parse_json(r.text)
        urls = []
        if isinstance(answer, dict) and answer.get("url"):
            urls.append(answer["url"])
        for c in r.citations:
            if c.get("url") and c["url"] not in urls:
                urls.append(c["url"])
        fetched = [fetch(u) for u in urls[:4]]
        quote = norm(answer.get("quote") or "") if isinstance(answer, dict) else ""
        for f in fetched:
            f["quote_in_page"] = bool(quote) and quote in f.get("text", "")
            f["quote_in_page_loose"] = bool(quote) and quote[:60] in f.get("text", "")
            f["text_chars"] = len(f.pop("text", ""))
        snippet_hit = bool(quote) and any(quote[:60] in norm(x.get("snippet") or "") for x in results)
        rows.append({"input": name, "seconds": secs, "cost_usd": r.cost_usd, "usage": r.usage,
                     "web_searches": r.web_searches, "text": r.text, "answer": answer,
                     "citations": r.citations, "results": results, "fetched": fetched,
                     "quote_in_snippet_loose": snippet_hit})
        print(name, secs, "s", r.cost_usd, "USD", r.web_searches, "searches", len(results), "results",
              len(r.citations), "cites", "| answer:", json.dumps(answer)[:300])
        for f in fetched:
            print("   fetch", f.get("status"), f.get("is_pdf"), f.get("text_chars"), "quote", f["quote_in_page"],
                  f["quote_in_page_loose"], f["url"][:100])
        print("   quote in a snippet:", snippet_hit)
    dest = ROOT / "runs" / "search_probe"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "probe.json").write_text(json.dumps({"instructions": INSTRUCTIONS, "rows": rows}, indent=1),
                                     encoding="utf-8")


if __name__ == "__main__":
    main()
