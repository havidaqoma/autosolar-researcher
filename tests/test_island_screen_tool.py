"""Acceptance tests for T24 (tools/island_screen.py). Written before the code. No network: every fetcher is a fake."""
import datetime
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import island_screen  # noqa: E402  (tools/island_screen.py)
from autosolar import islands as I  # noqa: E402
from autosolar.resources import ResourceFetchers  # noqa: E402

HASH = "b4a44fc6d4c32339"
QUOTE = "the island runs on a diesel plant (PLTD) of 3 x 100 kW"


def _island(name, lat, lon, url, study=None):
    return {"name": name, "region": "R", "lat_deg": lat, "lon_deg": lon, "point": "centre",
            "diesel": {"url": url, "quote": QUOTE, "outlet": "News", "year": 2024, "label": "press"},
            "study": study}


LIST = {"schema": "autosolar.island_list/1", "note": "n", "islands": [
    _island("Alpha", -5.88, 110.43, "https://example.org/a", study=HASH),
    _island("Beta", -7.15, 114.59, "https://example.org/b"),
    _island("Gamma", -5.40, 102.27, "https://example.org/c"),
]}


def _nasa_payload():
    keys = {}
    t = datetime.datetime(2023, 1, 1, 0)
    while t.year == 2023:
        keys[t.strftime("%Y%m%d%H")] = None
        t += datetime.timedelta(hours=1)
    return {"header": {"fill_value": -999.0}, "properties": {"parameter": {
        "WS50M": {k: 5.0 for k in keys}, "T2M": {k: 27.0 for k in keys}, "PS": {k: 101.0 for k in keys}}}}


class _Resp:
    def __init__(self, status, text, url):
        self.status_code = status
        self.content = text.encode("utf-8")
        self.url = url


class Fakes:
    def __init__(self, fail_wind_lat=None, pages=None):
        self.calls = {"nasa": 0, "gsa": 0, "overpass": 0, "source": 0}
        self.fail_wind_lat = fail_wind_lat
        self.pages = pages or {}

    def fetchers(self):
        def nasa(lat, lon, y0, y1):
            self.calls["nasa"] += 1
            if self.fail_wind_lat is not None and abs(lat - self.fail_wind_lat) < 1e-9:
                raise RuntimeError("power down")
            return _nasa_payload()

        def pvgis(*a):
            raise AssertionError("PVGIS is not used by the island screen")

        def overpass(query):
            self.calls["overpass"] += 1
            if '"waterway"' in query:
                return {"elements": [{"tags": {"waterway": "river", "name": "Kali"}}, {"tags": {"waterway": "stream"}},
                                     {"tags": {"waterway": "stream"}}]}
            return {"elements": [{"lat": -6.0, "lon": 110.5, "tags": {"place": "town", "name": "Townsville"}}]}

        return ResourceFetchers(nasa_wind_hourly=nasa, pvgis_pvcalc=pvgis, overpass=overpass)

    def gsa(self, lat, lon):
        self.calls["gsa"] += 1
        return {"annual": {"data": {"PVOUT_csi": 1460.0, "OPTA": 8.0}}}

    def source_get(self, url, headers=None, timeout=None, allow_redirects=True, **kw):
        self.calls["source"] += 1
        status, text = self.pages.get(url, (200, "<html><body><p>News. " + QUOTE + ". More.</p></body></html>"))
        return _Resp(status, text, url)


def _args(tmp_path, extra=()):
    lst = tmp_path / "config" / "list.json"
    if not lst.exists():
        lst.parent.mkdir(parents=True, exist_ok=True)
        lst.write_text(json.dumps(LIST), encoding="ascii")
    return ["--list", str(lst), "--out", str(tmp_path / "out"), "--cache", str(tmp_path / "cache"),
            "--site", str(tmp_path / "site"), "--land", str(tmp_path / "config" / "no_land.json")] + list(extra)


def _run(tmp_path, fakes, extra=()):
    return island_screen.main(_args(tmp_path, extra), fetchers=fakes.fetchers(), gsa_fetch=fakes.gsa,
                              source_get=fakes.source_get)


def _doc(tmp_path):
    found = sorted((tmp_path / "out").glob("islands-*/island_screen.json"))
    assert found, "no island_screen.json written"
    return json.loads(found[-1].read_text(encoding="ascii")), found[-1]


def test_full_run_writes_record_and_page(tmp_path, capsys):
    fakes = Fakes()
    assert _run(tmp_path, fakes) == 0
    doc, path = _doc(tmp_path)
    assert doc["schema"] == I.ISLAND_SCREEN_SCHEMA and doc["run_id"].startswith("islands-")
    assert path.parent.name == doc["run_id"]
    assert doc["counts"] == {"islands": 3, "diesel_quote_found": 3, "fully_screened": 3, "costed": 1}
    assert [r["name"] for r in doc["rows"]] == ["Alpha", "Beta", "Gamma"]
    assert all(r["errors"] == {} for r in doc["rows"])
    assert doc["rows"][0]["costed"] == "yes: study " + HASH and doc["rows"][1]["costed"] == I.NOT_COSTED
    assert doc["rows"][0]["hydro"] == {"river": 1, "stream": 2}
    assert doc["rows"][0]["nearest_town"]["name"] == "Townsville"
    assert doc["rows"][0]["wind"]["class_number"] == 1
    assert abs(doc["rows"][0]["solar"]["pvout_kwh_per_kwp_day"] - 1460.0 / 365.0) < 1e-12
    import hashlib
    assert doc["list_sha256"] == hashlib.sha256((tmp_path / "config" / "list.json").read_bytes()).hexdigest()
    assert doc["files"] and all(len(v) == 64 for v in doc["files"].values())
    assert any(name.startswith("gsa_") for name in doc["files"])
    assert any(name.startswith("source_") for name in doc["files"])
    page = (tmp_path / "site" / "islands.html").read_text(encoding="ascii")
    assert "<script" not in page.lower() and "Gamma" in page and '<path class="land"' not in page
    copy = json.loads((tmp_path / "site" / "data" / "islands" / "island_screen.json").read_text(encoding="ascii"))
    assert copy == doc
    out = capsys.readouterr().out
    assert doc["run_id"] in out
    assert "Alpha: quote found" in out
    assert "islands 3, quote found 3, fully screened 3, costed 1" in out


def test_one_failing_part_does_not_stop_the_run(tmp_path, capsys):
    fakes = Fakes(fail_wind_lat=-7.15)
    assert _run(tmp_path, fakes) == 0
    doc, _ = _doc(tmp_path)
    beta = doc["rows"][1]
    assert beta["missing"] == ["wind"] and beta["wind"] is None and beta["verdicts"] is None
    assert beta["errors"]["wind"].startswith("RuntimeError: power down")
    assert set(beta["errors"]) == {"wind"}
    assert doc["rows"][0]["missing"] == [] and doc["rows"][2]["missing"] == []
    assert doc["counts"]["fully_screened"] == 2
    out = capsys.readouterr().out
    assert "Beta: quote found; missing: wind" in out
    assert "islands 3, quote found 3, fully screened 2, costed 1" in out


def test_quote_missing_and_http_error(tmp_path, capsys):
    fakes = Fakes(pages={"https://example.org/b": (200, "<html><body>Nothing about power here at all.</body></html>"),
                         "https://example.org/c": (404, "gone")})
    assert _run(tmp_path, fakes) == 0
    doc, _ = _doc(tmp_path)
    beta, gamma = doc["rows"][1], doc["rows"][2]
    assert beta["diesel"]["found"] is False and beta["diesel"]["status"] == I.QUOTE_MISSING
    assert "diesel" not in beta["errors"]
    assert gamma["diesel"]["found"] is False
    assert gamma["diesel"]["status"].startswith("not fetched: ") and "HTTP 404" in gamma["diesel"]["status"]
    assert "HTTP 404" in gamma["errors"]["diesel"]
    assert doc["counts"]["diesel_quote_found"] == 1
    out = capsys.readouterr().out
    assert "Beta: quote NOT found (" + I.QUOTE_MISSING + ")" in out
    import hashlib
    failed = "source_" + hashlib.sha256(b"https://example.org/c").hexdigest()[:16] + ".json"
    assert not (tmp_path / "cache" / failed).exists()
    kept = "source_" + hashlib.sha256(b"https://example.org/b").hexdigest()[:16] + ".json"
    assert (tmp_path / "cache" / kept).exists()


def test_cache_only_reproduces_rows(tmp_path):
    fakes = Fakes()
    assert _run(tmp_path, fakes) == 0
    first, _ = _doc(tmp_path)
    for d in (tmp_path / "out").iterdir():
        d.rename(tmp_path / ("old_" + d.name))
    assert island_screen.main(_args(tmp_path, ["--cache-only"])) == 0
    second, _ = _doc(tmp_path)
    assert second["rows"] == first["rows"]
    assert second["files"] == first["files"]


def test_cache_only_without_cache_marks_parts_not_fetched(tmp_path, capsys):
    assert island_screen.main(_args(tmp_path, ["--cache-only"])) == 0
    doc, _ = _doc(tmp_path)
    assert doc["counts"]["fully_screened"] == 0 and doc["counts"]["diesel_quote_found"] == 0
    assert doc["rows"][0]["missing"] == ["hydro", "nearest_town", "solar", "wind"]
    assert set(doc["rows"][0]["errors"]) == {"wind", "solar", "hydro", "nearest_town", "diesel"}


def test_land_file_draws_paths(tmp_path):
    land = {"schema": I.LAND_SCHEMA, "rings": [[[100, -1], [101, -1], [101, 0], [100, 0]]]}
    path = tmp_path / "config" / "land.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(land), encoding="ascii")
    fakes = Fakes()
    args = _args(tmp_path)
    args[args.index("--land") + 1] = str(path)
    assert island_screen.main(args, fetchers=fakes.fetchers(), gsa_fetch=fakes.gsa,
                              source_get=fakes.source_get) == 0
    page = (tmp_path / "site" / "islands.html").read_text(encoding="ascii")
    assert page.count('<path class="land"') == 1


@pytest.mark.parametrize("bad", ["schema", "missing"])
def test_bad_list_returns_2(tmp_path, capsys, bad):
    lst = tmp_path / "config" / "list.json"
    lst.parent.mkdir(parents=True, exist_ok=True)
    if bad == "schema":
        lst.write_text(json.dumps({"schema": "x", "islands": []}), encoding="ascii")
    args = _args(tmp_path) if bad == "schema" else ["--list", str(tmp_path / "nope.json"), "--out",
                                                     str(tmp_path / "out")]
    assert island_screen.main(args, fetchers=Fakes().fetchers()) == 2
    assert "bad list:" in capsys.readouterr().out
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("islands-*"))
