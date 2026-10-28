"""Build the static gallery (docs/site/) from config/gallery.json with autosolar.site (T13).

  uv run python tools/make_site.py

config/gallery.json lists the runs to publish: {"studies": [{"run": "<study hash>", "paper": "<paper check run id or
null>", "review": "<review run id or null>"}]}. Each study page is self contained (inline CSS and SVG, no script).
The run folders stay out of git; the pages and a copy of each run's report.json, paper_check.json and review.json
under docs/site/data/ are the committed record.
"""
import json
import pathlib
import shutil
import sys

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autosolar.site import headline, render_index_html, render_study_html  # noqa: E402

OUT = ROOT / "docs" / "site"


def load(path):
    return json.loads(pathlib.Path(path).read_text(encoding="ascii"))


def main():
    cfg = load(ROOT / "config" / "gallery.json")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "data").mkdir(exist_ok=True)
    cards = []
    for entry in cfg["studies"]:
        run_dir = ROOT / "runs" / "studies" / entry["run"]
        report = load(run_dir / "report.json")
        table = pd.read_csv(run_dir / "design_table.csv")
        paper = review = None
        data = OUT / "data" / entry["run"]
        data.mkdir(exist_ok=True)
        shutil.copy(run_dir / "report.json", data / "report.json")
        shutil.copy(run_dir / "report.md", data / "report.md")
        shutil.copy(run_dir / "design_table.csv", data / "design_table.csv")
        if entry.get("paper"):
            p = ROOT / "runs" / "paper_checks" / entry["paper"] / "paper_check.json"
            paper = load(p)
            shutil.copy(p, data / "paper_check.json")
        if entry.get("review"):
            p = ROOT / "runs" / "reviews" / entry["review"] / "review.json"
            review = load(p)
            shutil.copy(p, data / "review.json")
        page = render_study_html(report, table, paper_check=paper, review=review)
        name = entry["run"] + ".html"
        (OUT / name).write_text(page, encoding="ascii")
        cards.append({"href": name, "site": report["site"]["name"], "question": report["question"],
                      "headline": headline(report), "run_hash": report["run_hash"]})
        print("page", name, len(page), "chars")
    (OUT / "index.html").write_text(render_index_html(cards), encoding="ascii")
    print("index", len(cards), "studies")


if __name__ == "__main__":
    main()
