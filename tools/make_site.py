"""Build the static gallery (docs/site/) from config/gallery.json with autosolar.site (T13).

  uv run python tools/make_site.py

config/gallery.json lists the runs to publish: {"studies": [{"run": "<study hash>", "paper": "<paper check run id or
null>", "review": "<review run id or null>", "figure_check": "<optional figure check run id>", "note": "<optional short
text for the gallery card>"}]}. Each study page is self contained (inline CSS and SVG, no script).
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
    notes_path = ROOT / "config" / "field_notes.json"
    if notes_path.is_file():
        field_notes_all = load(notes_path)["notes"]
    else:
        field_notes_all = []
    cards = []
    for entry in cfg["studies"]:
        run_dir = ROOT / "runs" / "studies" / entry["run"]
        report = load(run_dir / "report.json")
        table = pd.read_csv(run_dir / "design_table.csv")
        paper = review = figure = followup = None
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
        if entry.get("figure_check"):
            p = ROOT / "runs" / "figure_checks" / entry["figure_check"] / "figure_check.json"
            figure = load(p)
            shutil.copy(p, data / "figure_check.json")
        if entry.get("load_followup"):
            p = ROOT / "runs" / "load_followups" / entry["load_followup"] / "load_followup.json"
            followup = load(p)
            shutil.copy(p, data / "load_followup.json")
        if entry.get("resource_screen"):
            p = ROOT / "runs" / "resource_screens" / entry["resource_screen"] / "resource_screen.json"
            resource_screen = load(p)
            shutil.copy(p, data / "resource_screen.json")
            kw["resource_screen"] = resource_screen
        kw = {"figure_check": figure} if figure is not None else {}
        if followup is not None:
            kw["load_followup"] = followup
        site_notes = [n for n in field_notes_all if n.get("site") == report["site"]["name"]]
        if site_notes:
            kw["field_notes"] = site_notes
        if entry.get("engineer_files"):
            src = ROOT / "runs" / "engineer_files" / entry["engineer_files"]
            dest = data / "files"
            dest.mkdir(exist_ok=True)
            for name in ("hourly.csv", "homer_load_kw.txt", "engineer_files.json"):
                shutil.copy(src / name, dest / name)
            kw["engineer_files"] = load(dest / "engineer_files.json")
        page = render_study_html(report, table, paper_check=paper, review=review, **kw)
        name = entry["run"] + ".html"
        (OUT / name).write_text(page, encoding="ascii")
        cards.append({"href": name, "site": report["site"]["name"], "question": report["question"],
                      "headline": headline(report) + (" | " + entry["note"] if entry.get("note") else ""),
                      "run_hash": report["run_hash"]})
        print("page", name, len(page), "chars")
    (OUT / "index.html").write_text(render_index_html(cards), encoding="ascii")
    print("index", len(cards), "studies")


if __name__ == "__main__":
    main()
