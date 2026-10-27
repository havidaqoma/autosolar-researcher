"""Acceptance tests for T09a (autosolar/request.py). Written by the orchestrator. No network.

Model texts below are copied from the measured probe (runs/parse_probe/probe.json); geocoder answers are saved
Nominatim responses (tests/fixtures/geocode/)."""
import json
import pathlib

import pytest

from autosolar.request import (INDONESIA_BBOX_DEG, NOMINATIM_URL, PARSE_INSTRUCTIONS, QUESTION_TYPES, USER_AGENT,
                               GeocodeError, ParseError, Site, SiteNotFound, StudyRequest, UnsupportedQuestion,
                               check_request, geocode, parse_question)

FIX = pathlib.Path(__file__).parent / "fixtures" / "geocode"


class FakeResult:
    def __init__(self, text):
        self.text = text
        self.cost_usd = 0.00016
        self.model = "muse-spark-1.3-contributor"


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def respond(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return FakeResult(self.text)


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeGet:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.status, self.payload)


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_constants():
    assert QUESTION_TYPES == ("pv_battery_for_diesel_grid", "other")
    assert NOMINATIM_URL == "https://nominatim.openstreetmap.org/search"
    assert USER_AGENT == "AutoSolarResearcher/0.1 (+https://github.com/havidaqoma/autosolar-researcher)"
    assert INDONESIA_BBOX_DEG == (-11.5, 6.5, 94.5, 141.5)
    assert PARSE_INSTRUCTIONS.startswith("You turn a user question into a JSON object.")
    assert PARSE_INSTRUCTIONS.endswith("Do not guess coordinates. Do not add other keys.")
    assert '"pv_battery_for_diesel_grid"' in PARSE_INSTRUCTIONS and len(PARSE_INSTRUCTIONS) == 538


def test_parse_call_shape_and_result():
    text = ('{"site_name": "Karimunjawa", "country": "Indonesia", "question_type": "pv_battery_for_diesel_grid", '
            '"language": "en"}')
    c = FakeClient(text)
    q = "  Is solar plus battery worth it for Karimunjawa? The island runs on diesel.  "
    r = parse_question(q, c, "run-1")
    assert c.calls == [(("run-1", "S0_parse", [{"role": "system", "content": PARSE_INSTRUCTIONS},
                                              {"role": "user", "content": q.strip()}]), {"estimate_usd": 0.01})]
    assert isinstance(r, StudyRequest)
    assert r == StudyRequest(question=q.strip(), site_name="Karimunjawa", country="Indonesia",
                             question_type="pv_battery_for_diesel_grid", language="en",
                             model="muse-spark-1.3-contributor", cost_usd=0.00016)


def test_parse_indonesian_compact_json_and_estimate():
    text = ('{"site_name":"Pulau Karimunjawa","country":"Indonesia","question_type":"pv_battery_for_diesel_grid",'
            '"language":"id"}')
    c = FakeClient(text)
    r = parse_question("Berapa ukuran PLTS dan baterai yang paling murah untuk Pulau Karimunjawa?", c, "r",
                       estimate_usd=0.02)
    assert r.site_name == "Pulau Karimunjawa" and r.language == "id"
    assert c.calls[0][1] == {"estimate_usd": 0.02}


def test_parse_code_fence_and_nulls():
    text = '```json\n{"site_name": null, "country": null, "question_type": "other", "language": "en"}\n```'
    r = parse_question("hello", FakeClient(text), "r")
    assert r.site_name is None and r.country is None and r.question_type == "other"


def test_parse_strips_values():
    text = '{"site_name": " Sumba ", "country": " Indonesia", "question_type": "other", "language": "en"}'
    r = parse_question("q", FakeClient(text), "r")
    assert r.site_name == "Sumba" and r.country == "Indonesia"


@pytest.mark.parametrize("text", [
    "Sure! Here is the JSON: {}",
    "[1, 2]",
    '{"site_name": "A", "country": "Indonesia", "question_type": "other"}',
    '{"site_name": "A", "country": "Indonesia", "question_type": "other", "language": "en", "lat": -5.8}',
    '{"site_name": "", "country": "Indonesia", "question_type": "other", "language": "en"}',
    '{"site_name": 5, "country": "Indonesia", "question_type": "other", "language": "en"}',
    '{"site_name": "A", "country": 1, "question_type": "other", "language": "en"}',
    '{"site_name": "A", "country": "Indonesia", "question_type": "pv", "language": "en"}',
    '{"site_name": "A", "country": "Indonesia", "question_type": "other", "language": "EN"}',
    '{"site_name": "A", "country": "Indonesia", "question_type": "other", "language": "eng"}',
])
def test_parse_rejects_bad_model_text(text):
    with pytest.raises(ParseError):
        parse_question("q", FakeClient(text), "r")


def test_parse_error_is_value_error_and_truncates():
    long_text = "x" * 1000
    with pytest.raises(ValueError) as e:
        parse_question("q", FakeClient(long_text), "r")
    assert isinstance(e.value, ParseError)
    assert "x" * 301 not in str(e.value)


@pytest.mark.parametrize("q", ["", "   ", "a" * 2001, None, 5])
def test_parse_rejects_bad_question_without_calling(q):
    c = FakeClient("{}")
    with pytest.raises(ValueError):
        parse_question(q, c, "r")
    assert c.calls == []


def test_parse_passes_client_errors_through():
    class Boom:
        def respond(self, *a, **k):
            raise RuntimeError("budget")
    with pytest.raises(RuntimeError, match="budget"):
        parse_question("q", Boom(), "r")


def req(**kw):
    base = dict(question="q", site_name="Karimunjawa", country="Indonesia",
                question_type="pv_battery_for_diesel_grid", language="en", model="m", cost_usd=0.0)
    base.update(kw)
    return StudyRequest(**base)


def test_check_request():
    assert check_request(req()) is None
    assert check_request(req(country=" indonesia ")) is None
    for bad in (req(question_type="other"), req(site_name=None), req(country="Australia"), req(country=None)):
        with pytest.raises(UnsupportedQuestion):
            check_request(bad)
    assert issubclass(UnsupportedQuestion, ValueError)


def test_geocode_call_shape_and_first_result():
    g = FakeGet(200, load("karimunjawa.json"))
    s = geocode(" Karimunjawa ", g)
    assert g.calls == [(NOMINATIM_URL, {"params": {"q": "Karimunjawa", "format": "jsonv2", "limit": 3,
                                                   "countrycodes": "id"},
                                        "headers": {"User-Agent": USER_AGENT}, "timeout": 30.0})]
    assert isinstance(s, Site)
    assert s.query == "Karimunjawa" and s.name == "Karimunjawa"
    assert s.lat_deg == pytest.approx(-5.8796265) and s.lon_deg == pytest.approx(110.4329073)
    assert s.osm_type == "node" and s.osm_id == 450714446 and isinstance(s.osm_id, int)
    assert s.addresstype == "village" and s.n_candidates == 3
    assert s.display_name == "Karimunjawa, Jepara, Jawa Tengah, Indonesia"
    assert s.source == "OpenStreetMap Nominatim"


def test_geocode_island():
    s = geocode("Pulau Karimunjawa", FakeGet(200, load("pulau_karimunjawa.json")))
    assert (s.lat_deg, s.lon_deg) == pytest.approx((-5.8296718, 110.4686350))
    assert s.addresstype == "island" and s.n_candidates == 1


def test_geocode_outside_indonesia_rejected():
    with pytest.raises(ValueError):
        geocode("Lord Howe Island", FakeGet(200, load("lord_howe_island.json")))


def test_geocode_other_country_code_skips_box():
    g = FakeGet(200, load("lord_howe_island.json"))
    s = geocode("Lord Howe Island", g, country_code="au", timeout_s=5.0)
    assert s.lat_deg == pytest.approx(-31.5233816)
    assert g.calls[0][1]["params"]["countrycodes"] == "au" and g.calls[0][1]["timeout"] == 5.0


def test_geocode_first_result_is_used_even_if_others_differ():
    # saved answer without the country filter: the first hit is Sumba island (Indonesia)
    s = geocode("Sumba", FakeGet(200, load("sumba_no_country_filter.json")))
    assert s.lat_deg == pytest.approx(-9.795874) and s.addresstype == "island"


def test_geocode_not_found():
    with pytest.raises(SiteNotFound):
        geocode("Xyzzy Nowhere", FakeGet(200, []))


@pytest.mark.parametrize("status, payload", [(429, []), (500, None), (200, {"error": "x"}),
                                             (200, ValueError("not json"))])
def test_geocode_service_errors(status, payload):
    with pytest.raises(GeocodeError):
        geocode("Karimunjawa", FakeGet(status, payload))


@pytest.mark.parametrize("change", [{"lat": "abc"}, {"lon": "nan"}, {"lat": None}])
def test_geocode_bad_coordinates(change):
    hit = dict(load("karimunjawa.json")[0])
    hit.update(change)
    with pytest.raises(GeocodeError):
        geocode("Karimunjawa", FakeGet(200, [hit]))


def test_geocode_missing_key():
    hit = dict(load("karimunjawa.json")[0])
    del hit["osm_id"]
    with pytest.raises(GeocodeError):
        geocode("Karimunjawa", FakeGet(200, [hit]))


def test_geocode_empty_name_falls_back():
    hit = dict(load("karimunjawa.json")[0])
    hit["name"] = ""
    assert geocode("Karimunjawa", FakeGet(200, [hit])).name == "Karimunjawa"


@pytest.mark.parametrize("name, code", [("", "id"), ("  ", "id"), (None, "id"), ("A", "ID"), ("A", "idn")])
def test_geocode_rejects_bad_arguments(name, code):
    g = FakeGet(200, [])
    with pytest.raises(ValueError):
        geocode(name, g, country_code=code)
    assert g.calls == []
