"""Tests for tools/make_site.py wiring (T23c). Written after the T22/T23 code, labelled so: the first gallery build
with a resource screen entry would have failed, because make_site set kw["resource_screen"] before kw existed.
No network: every input lives under tmp_path and the renderers are fakes."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import make_site  # noqa: E402  (tools/make_site.py)

RUN = "0123456789abcdef"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("ascii"))


def _tree(tmp_path, entry):
    report = {"run_hash": RUN, "site": {"name": "Test Island"}, "question": "q"}
    run_dir = tmp_path / "runs" / "studies" / RUN
    _write(run_dir / "report.json", json.dumps(report))
    _write(run_dir / "report.md", "# r\n")
    _write(run_dir / "design_table.csv", "a,b\n1,2\n")
    _write(tmp_path / "config" / "gallery.json", json.dumps({"studies": [entry]}))
    _write(tmp_path / "config" / "field_notes.json", json.dumps({"schema": "autosolar.field_notes/1", "notes": [
        {"site": "Test Island", "label": "x"}, {"site": "Elsewhere", "label": "y"}]}))
    _write(tmp_path / "runs" / "resource_screens" / "resources-1" / "resource_screen.json",
           json.dumps({"study_run_hash": RUN, "marker": "screen"}))
    files = tmp_path / "runs" / "engineer_files" / "files-1"
    _write(files / "hourly.csv", "h\n")
    _write(files / "homer_load_kw.txt", "1.000000\n")
    _write(files / "engineer_files.json", json.dumps({"study_run_hash": RUN, "marker": "files"}))
    _write(tmp_path / "runs" / "load_followups" / "followup-1" / "load_followup.json", json.dumps({"marker": "lf"}))


def _run(tmp_path, monkeypatch, entry):
    _tree(tmp_path, entry)
    seen = []

    def fake_page(report, table, paper_check=None, review=None, **kw):
        seen.append(kw)
        return "<html>page</html>"

    monkeypatch.setattr(make_site, "ROOT", tmp_path)
    monkeypatch.setattr(make_site, "OUT", tmp_path / "site")
    monkeypatch.setattr(make_site, "render_study_html", fake_page)
    monkeypatch.setattr(make_site, "render_index_html", lambda cards: "<html>index</html>")
    monkeypatch.setattr(make_site, "headline", lambda report: "h")
    make_site.main()
    return seen


def test_make_site_passes_every_extra(tmp_path, monkeypatch):
    seen = _run(tmp_path, monkeypatch, {"run": RUN, "paper": None, "review": None, "load_followup": "followup-1",
                                         "resource_screen": "resources-1", "engineer_files": "files-1"})
    assert len(seen) == 1
    kw = seen[0]
    assert kw["resource_screen"]["marker"] == "screen"
    assert kw["engineer_files"]["marker"] == "files"
    assert kw["load_followup"]["marker"] == "lf"
    assert [n["label"] for n in kw["field_notes"]] == ["x"]
    data = tmp_path / "site" / "data" / RUN
    assert json.loads((data / "resource_screen.json").read_text(encoding="ascii"))["marker"] == "screen"
    assert (data / "files" / "homer_load_kw.txt").read_bytes() == b"1.000000\n"


def test_make_site_without_extras(tmp_path, monkeypatch):
    seen = _run(tmp_path, monkeypatch, {"run": RUN, "paper": None, "review": None})
    assert "resource_screen" not in seen[0] and "engineer_files" not in seen[0]
    assert not (tmp_path / "site" / "data" / RUN / "resource_screen.json").exists()


# ---------- T24: page cards (written before the T24 code) ----------

PAGE_CARD = {"page": "islands.html", "title": "11 diesel islands", "question": "Which islands could use solar?",
             "text": "First screen, post hoc", "run": "islands-20261101T000000-abcdef"}


def _cards(tmp_path, monkeypatch, studies):
    _tree(tmp_path, {"run": RUN, "paper": None, "review": None})
    _write(tmp_path / "config" / "gallery.json", json.dumps({"studies": studies}))
    got = []
    monkeypatch.setattr(make_site, "ROOT", tmp_path)
    monkeypatch.setattr(make_site, "OUT", tmp_path / "site")
    monkeypatch.setattr(make_site, "render_study_html", lambda *a, **k: "<html>page</html>")
    monkeypatch.setattr(make_site, "render_index_html", lambda cards: got.extend(cards) or "<html>index</html>")
    monkeypatch.setattr(make_site, "headline", lambda report: "h")
    make_site.main()
    return got


def test_t24_page_card_keeps_its_place(tmp_path, monkeypatch, capsys):
    cards = _cards(tmp_path, monkeypatch, [{"run": RUN, "paper": None, "review": None}, dict(PAGE_CARD),
                                           {"run": RUN, "paper": None, "review": None, "note": "again"}])
    assert [c["href"] for c in cards] == [RUN + ".html", "islands.html", RUN + ".html"]
    assert cards[1] == {"href": "islands.html", "site": "11 diesel islands", "question": "Which islands could use solar?",
                        "headline": "First screen, post hoc", "run_hash": "islands-20261101T000000-abcdef"}
    assert "card islands.html" in capsys.readouterr().out


def test_t24_page_card_reads_no_run_folder(tmp_path, monkeypatch):
    cards = _cards(tmp_path, monkeypatch, [dict(PAGE_CARD)])
    assert len(cards) == 1
    assert not (tmp_path / "site" / "data" / "islands-20261101T000000-abcdef").exists()
    assert not (tmp_path / "site" / "islands.html").exists()
