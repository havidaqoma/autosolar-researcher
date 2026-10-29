"""Acceptance tests for T19 (the judge panel by default in tools/source.py, a plain refusal in tools/ask.py).
Written before the code. No network."""
import hashlib
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import ask  # noqa: E402
import rejudge  # noqa: E402
import source  # noqa: E402
from autosolar.cite_check import JUDGE_VOTES, Claim, support_votes  # noqa: E402
from autosolar.request import GeocodeError, SiteNotFound, UnsupportedQuestion  # noqa: E402
from autosolar.study import DEMAND_RADIUS_KM, KARIMUNJAWA_DEG, UnsupportedSite, haversine_km  # noqa: E402

YES = json.dumps({"supports": True, "reason": "The quote states the value."})
NO = json.dumps({"supports": False, "reason": "Not this input."})
QUESTION = "Is solar plus battery worth it for Bawean Island? It runs on diesel."
BAWEAN = {"query": "Bawean", "name": "Bawean", "display_name": "Bawean, Gresik, Jawa Timur, Indonesia",
          "lat_deg": -5.78, "lon_deg": 112.66, "osm_type": "relation", "osm_id": 1, "addresstype": "island"}
LAST = "The hourly load comes from one published study of Karimunjawa. A new site needs its own hourly load."


class Calls:
    """A fake judge that answers from a list and records each prompt."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        out = self.answers.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def claim():
    return Claim(input_name="diesel_min_load_frac", description="Diesel minimum load", value=30, unit="%",
                 url="https://www.example.org/grid", doi=None, quote="kept above 30% of its rated capacity",
                 title="Island grid guide", currency_year=None)


# ---------- tools/source.py ----------

def test_panel_name_matches_rejudge():
    assert source.PANEL_JUDGE_NAME == rejudge.PANEL_JUDGE_NAME
    assert source.PANEL_JUDGE_NAME == (source.JUDGE_NAME + " (votes 1 and 2) and muse-wonder-1.0 (vote 3), yes needed"
                                       " in all 3 votes")


def test_parser_default_is_panel():
    args = source.build_parser().parse_args([])
    assert args.judge == "panel"


def test_parser_accepts_local():
    assert source.build_parser().parse_args(["--judge", "local"]).judge == "local"


def test_parser_refuses_other_modes():
    with pytest.raises(SystemExit):
        source.build_parser().parse_args(["--judge", "wonder"])


def test_parser_keeps_old_options():
    args = source.build_parser().parse_args(["--only", "a", "b", "--carry", "c.json", "--out", "o"])
    assert args.only == ["a", "b"] and args.carry == "c.json" and args.out == "o"


def test_build_judge_panel_shape_and_name():
    log = []
    fn, name = source.build_judge("panel", local_fn=Calls([YES] * 2), wonder_fn=Calls([YES]), log=log)
    assert isinstance(fn, tuple) and len(fn) == JUDGE_VOTES == 3
    assert all(callable(j) for j in fn)
    assert name == source.PANEL_JUDGE_NAME


def test_build_judge_panel_order_local_local_wonder():
    local, wonder, log = Calls([YES, YES]), Calls([YES]), []
    fn, _ = source.build_judge("panel", local_fn=local, wonder_fn=wonder, log=log)
    assert [f("p%d" % k) for k, f in enumerate(fn)] == [YES, YES, YES]
    assert local.prompts == ["p0", "p1"] and wonder.prompts == ["p2"]
    assert [v["judge"] for v in log] == ["local", "local", "wonder"]


def test_build_judge_local_mode():
    local, wonder, log = Calls([YES, YES, YES]), Calls([]), []
    fn, name = source.build_judge("local", local_fn=local, wonder_fn=wonder, log=log)
    assert not isinstance(fn, tuple) and callable(fn)
    assert name == source.JUDGE_NAME
    verdict, calls = support_votes(fn, claim(), "context kept above 30% of its rated capacity")
    assert verdict.supports is True and calls == 3
    assert len(local.prompts) == 3 and wonder.prompts == []
    assert [v["judge"] for v in log] == ["local"] * 3


@pytest.mark.parametrize("mode", ["", "Panel", "wonder", None, 3])
def test_build_judge_other_mode(mode):
    with pytest.raises(ValueError, match="judge mode must be panel or local"):
        source.build_judge(mode, local_fn=Calls([]), wonder_fn=Calls([]), log=[])


def test_panel_wonder_no_ends_as_no():
    local, wonder, log = Calls([YES, YES]), Calls([NO]), []
    fn, _ = source.build_judge("panel", local_fn=local, wonder_fn=wonder, log=log)
    verdict, calls = support_votes(fn, claim(), "context")
    assert verdict.supports is False and calls == 3
    assert len(wonder.prompts) == 1


def test_panel_local_no_never_calls_wonder():
    local, wonder, log = Calls([NO]), Calls([YES]), []
    fn, _ = source.build_judge("panel", local_fn=local, wonder_fn=wonder, log=log)
    verdict, calls = support_votes(fn, claim(), "context")
    assert verdict.supports is False and calls == 1
    assert wonder.prompts == [] and [v["judge"] for v in log] == ["local"]


def test_panel_all_yes_is_yes():
    fn, _ = source.build_judge("panel", local_fn=Calls([YES, YES]), wonder_fn=Calls([YES]), log=[])
    verdict, calls = support_votes(fn, claim(), "context")
    assert verdict.supports is True and calls == 3


def test_panel_votes_see_the_same_prompt():
    local, wonder = Calls([YES, YES]), Calls([YES])
    fn, _ = source.build_judge("panel", local_fn=local, wonder_fn=wonder, log=[])
    support_votes(fn, claim(), "context")
    assert local.prompts[0] == local.prompts[1] == wonder.prompts[0]


def test_wonder_error_is_logged_and_counts_as_no():
    local, wonder, log = Calls([YES, YES]), Calls([RuntimeError("refused by cap")]), []
    fn, _ = source.build_judge("panel", local_fn=local, wonder_fn=wonder, log=log)
    verdict, calls = support_votes(fn, claim(), "context")
    assert verdict.supports is None and calls == 3
    assert verdict.reason == "judge error: RuntimeError"
    assert log[-1]["judge"] == "wonder"
    assert log[-1]["error"] == "RuntimeError: refused by cap"
    assert "raw" not in log[-1]


def test_vote_log_raw_and_seconds():
    log = []
    v = source.VoteLog("local", Calls(["x" * 3000]), log)
    out = v("prompt")
    assert out == "x" * 3000
    assert log[0]["judge"] == "local" and log[0]["raw"] == "x" * 2000
    assert isinstance(log[0]["seconds"], float) and log[0]["seconds"] >= 0.0
    assert round(log[0]["seconds"], 1) == log[0]["seconds"]
    assert "error" not in log[0]


def test_vote_log_error_message_cut_and_reraised():
    log = []
    v = source.VoteLog("wonder", Calls([ValueError("e" * 500)]), log)
    with pytest.raises(ValueError):
        v("prompt")
    assert log[0]["error"] == "ValueError: " + "e" * 200


# ---------- tools/ask.py ----------

def write_request(runs_dir, question, site):
    name = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()[:16] + ".json"
    p = pathlib.Path(runs_dir) / "requests" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"request": {"question": question}, "site": site}), encoding="utf-8")


def test_refusals_tuple():
    assert set(ask.REFUSALS) == {UnsupportedSite, UnsupportedQuestion, SiteNotFound}
    assert GeocodeError not in ask.REFUSALS


def test_refusal_far_site_with_distance(tmp_path):
    write_request(tmp_path, QUESTION, BAWEAN)
    lines = ask.refusal_lines(UnsupportedSite("site outside the Karimunjawa demand source area"),
                              "  " + QUESTION + " ", tmp_path)
    d = haversine_km(BAWEAN["lat_deg"], BAWEAN["lon_deg"], *KARIMUNJAWA_DEG)
    assert lines == ["No study: site outside the Karimunjawa demand source area.",
                     "Bawean (Bawean, Gresik, Jawa Timur, Indonesia) is %s km from Karimunjawa; the demand model "
                     "covers sites within %s km (computed)." % (format(round(d), ","), format(round(DEMAND_RADIUS_KM), ",")),
                     LAST]
    assert "%d km" % round(d) in lines[1] and 200 < d < 300


def test_refusal_thousands_comma(tmp_path):
    far = dict(BAWEAN, name="Sabang", display_name="Sabang, Aceh, Indonesia", lat_deg=5.89, lon_deg=95.32)
    write_request(tmp_path, QUESTION, far)
    lines = ask.refusal_lines(UnsupportedSite("site outside the Karimunjawa demand source area"), QUESTION, tmp_path)
    d = haversine_km(5.89, 95.32, *KARIMUNJAWA_DEG)
    assert d > 1000
    assert (" is " + format(round(d), ",") + " km from Karimunjawa") in lines[1]


def test_refusal_far_site_without_cached_request(tmp_path):
    lines = ask.refusal_lines(UnsupportedSite("site outside the Karimunjawa demand source area"), QUESTION, tmp_path)
    assert lines == ["No study: site outside the Karimunjawa demand source area.", LAST]


def test_refusal_other_question(tmp_path):
    write_request(tmp_path, QUESTION, BAWEAN)
    lines = ask.refusal_lines(UnsupportedQuestion("country is not Indonesia: Malaysia"), QUESTION, tmp_path)
    assert lines == ["No study: country is not Indonesia: Malaysia.", LAST]


def test_refusal_site_not_found(tmp_path):
    lines = ask.refusal_lines(SiteNotFound("site not found: Atlantis"), QUESTION, tmp_path)
    assert lines == ["No study: site not found: Atlantis.", LAST]


class Dummy:
    def __init__(self, *args, **kwargs):
        pass


@pytest.fixture
def ask_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_API_KEY", "test-key-not-real")
    monkeypatch.delenv("AUTOSOLAR_CAMS_EMAIL", raising=False)
    monkeypatch.setenv("AUTOSOLAR_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setattr(ask, "MetaClient", Dummy)
    monkeypatch.setattr(ask, "Ledger", Dummy)
    monkeypatch.setattr(ask, "cached_fetchers", lambda *a, **k: None)
    monkeypatch.setattr(ask, "default_fetchers", lambda *a, **k: None)
    return tmp_path


def test_main_refusal_exits_2_without_cams_address(ask_env, monkeypatch, capsys):
    write_request(ask_env, QUESTION, BAWEAN)

    def fake_run_study(question, **kwargs):
        raise UnsupportedSite("site outside the Karimunjawa demand source area")

    monkeypatch.setattr(ask, "run_study", fake_run_study)
    monkeypatch.setattr(sys, "argv", ["ask.py", QUESTION, "--runs", str(ask_env)])
    with pytest.raises(SystemExit) as exc:
        ask.main()
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "No study: site outside the Karimunjawa demand source area."
    assert "km from Karimunjawa" in out and LAST in out
    assert "Traceback" not in out


def test_main_does_not_catch_geocode_error(ask_env, monkeypatch):
    def fake_run_study(question, **kwargs):
        raise GeocodeError("geocode status 503 for query Bawean")

    monkeypatch.setattr(ask, "run_study", fake_run_study)
    monkeypatch.setattr(sys, "argv", ["ask.py", QUESTION, "--runs", str(ask_env)])
    with pytest.raises(GeocodeError):
        ask.main()


def test_main_reads_cams_address_only_for_weather(ask_env, monkeypatch):
    def fake_run_study(question, *, weather_fn, **kwargs):
        weather_fn(-5.85, 110.43)
        raise AssertionError("weather_fn should have stopped the run")

    monkeypatch.setattr(ask, "run_study", fake_run_study)
    monkeypatch.setattr(sys, "argv", ["ask.py", "Is solar worth it for Karimunjawa?", "--runs", str(ask_env)])
    with pytest.raises(SystemExit) as exc:
        ask.main()
    assert exc.value.code == "AUTOSOLAR_CAMS_EMAIL is not set (environment or AUTOSOLAR_ENV_FILE)"


def test_main_passes_cams_address_to_weather(ask_env, monkeypatch):
    seen = {}
    monkeypatch.setenv("AUTOSOLAR_CAMS_EMAIL", "cams-test-address")

    def fake_build(lat_deg, lon_deg, cams_email, fetchers):
        seen["email"] = cams_email
        raise SiteNotFound("site not found: stop here")

    def fake_run_study(question, *, weather_fn, **kwargs):
        weather_fn(-5.85, 110.43)

    monkeypatch.setattr(ask, "build_weather_cases", fake_build)
    monkeypatch.setattr(ask, "run_study", fake_run_study)
    monkeypatch.setattr(sys, "argv", ["ask.py", "Is solar worth it for Karimunjawa?", "--runs", str(ask_env)])
    with pytest.raises(SystemExit) as exc:
        ask.main()
    assert exc.value.code == 2
    assert seen == {"email": "cams-test-address"}
