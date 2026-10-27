"""Second half of the S3 probe: re-fetch the answer URLs, extract PDF text with pypdf, and locate each quote.

  uv run --with pypdf python tools/probe_search_quotes.py

Reads runs/search_probe/probe.json, saves raw source files to runs/search_probe/src_<n>.<ext> and prints where
each quote matches (exact after normalising, digits-only fallback), so the cite_check spec rests on measurements.
"""
import io
import json
import pathlib
import re
import sys

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from probe_search import UA, norm, page_text  # noqa: E402


def pdf_text(data):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return pages


def main():
    d = json.loads((ROOT / "runs" / "search_probe" / "probe.json").read_text(encoding="utf-8"))
    for n, row in enumerate(d["rows"]):
        a = row["answer"] or {}
        url = a.get("url")
        quote = norm(a.get("quote") or "")
        r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
        is_pdf = r.content[:5] == b"%PDF-"
        (ROOT / "runs" / "search_probe" / ("src_%d.%s" % (n, "pdf" if is_pdf else "html"))).write_bytes(r.content)
        if is_pdf:
            pages = [norm(p) for p in pdf_text(r.content)]
        else:
            pages = [page_text(r.text, r.headers.get("content-type", ""))]
        hit = [i + 1 for i, p in enumerate(pages) if quote and quote in p]
        qd = re.sub(r"[^0-9]", "", quote)
        hit_digits = [i + 1 for i, p in enumerate(pages) if qd and qd in re.sub(r"[^0-9]", "", p)]
        value = a.get("value")
        print(row["input"], "pdf" if is_pdf else "html", len(pages), "pages; exact hit pages", hit[:5],
              "digit-run hit pages", hit_digits[:5])
        if not hit and pages:
            head = quote[:40]
            for i, p in enumerate(pages):
                k = p.find(head)
                if k >= 0:
                    print("   head found page", i + 1, "context:", repr(p[k:k + len(quote) + 40]))
                    break
            else:
                vs = ("{:,}".format(value) if isinstance(value, (int, float)) else str(value)).lower()
                for i, p in enumerate(pages):
                    k = p.find(vs)
                    if k >= 0:
                        print("   value", vs, "found page", i + 1, "context:", repr(p[max(0, k - 120):k + 80]))
                        break
                else:
                    print("   neither head nor value found")


if __name__ == "__main__":
    main()
