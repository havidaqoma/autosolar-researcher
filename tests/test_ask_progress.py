"""tools/ask.py progress lines (written before the code, Monday 2 Nov).

A full study takes about 10 minutes and used to print nothing until the end, so a person at the terminal could not
tell it was working. ask.py now prints one line when the study reaches a new stage and a still-working line after
30 s of quiet. It only reports: every wrapped function gets the same arguments and returns the same result, so the
study and its run hash do not change. Lines carry fixed labels and the elapsed time only (no URL, key or address).
"""
import io
import pathlib
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import ask  # noqa: E402
import autosolar.study as study  # noqa: E402
from autosolar.study import UnsupportedSite  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def make(heartbeat_s=30.0):
    buf, clock = io.StringIO(), Clock()
    return ask.Progress(out=buf, heartbeat_s=heartbeat_s, clock=clock), buf, clock


def test_every_stage_name_is_a_function_in_the_study_module():
    assert len(ask.STAGES) >= 8
    for name, label in ask.STAGES:
        assert callable(getattr(study, name)), name


def test_labels_are_fixed_ascii_text():
    labels = [label for _, label in ask.STAGES] + [ask.WEATHER_LABEL]
    assert len(set(labels)) == len(labels)
    for label in labels:
        assert label.isascii() and label.strip() == label and label
        assert "@" not in label and "http" not in label


def test_wrapped_function_gets_same_arguments_and_returns_same_result():
    p, buf, clock = make()
    seen = []

    def fn(a, b=0, *, c=1):
        seen.append((a, b, c))
        return {"sum": a + b + c}

    w = p.wrap(fn, "adding")
    assert w(1, 2, c=3) == {"sum": 6}
    assert seen == [(1, 2, 3)]


def test_exception_passes_through_unchanged():
    p, buf, clock = make()

    def fn():
        raise UnsupportedSite("site outside the Karimunjawa demand source area")

    with pytest.raises(UnsupportedSite):
        p.wrap(fn, "failing")()


def test_one_line_per_stage_change_with_elapsed_time():
    p, buf, clock = make()
    a = p.wrap(lambda: 1, "stage A")
    b = p.wrap(lambda: 2, "stage B")
    a()
    clock.t += 5
    a()
    clock.t += 70
    b()
    clock.t += 1
    a()
    assert buf.getvalue().splitlines() == ["[0:00] stage A", "[1:15] stage B", "[1:16] stage A"]


def test_nothing_printed_before_the_first_stage():
    p, buf, clock = make()
    clock.t += 100
    p.tick()
    assert buf.getvalue() == ""


def test_still_working_line_only_after_quiet_time():
    p, buf, clock = make(heartbeat_s=30.0)
    p.stage("stage A")
    clock.t += 29
    p.tick()
    clock.t += 2
    p.tick()
    p.tick()
    clock.t += 30
    p.tick()
    assert buf.getvalue().splitlines() == ["[0:00] stage A", "[0:31] still working, last step: stage A",
                                           "[1:01] still working, last step: stage A"]


def test_heartbeat_thread_starts_and_stops():
    p, buf, clock = make(heartbeat_s=0.01)
    p.start()
    p.stop()
    assert not p.running()


def test_instrument_swaps_and_restore_puts_originals_back():
    p, buf, clock = make()
    mod = types.SimpleNamespace(f=lambda x: x + 1, g=lambda: "g")
    orig_f, orig_g = mod.f, mod.g
    saved = ask.instrument(mod, p, (("f", "the f stage"),))
    assert mod.f is not orig_f and mod.g is orig_g
    assert mod.f(1) == 2
    assert buf.getvalue() == "[0:00] the f stage\n"
    ask.restore(mod, saved)
    assert mod.f is orig_f


def test_instrument_refuses_a_missing_name():
    p, buf, clock = make()
    mod = types.SimpleNamespace(f=lambda: 1)
    with pytest.raises(ValueError):
        ask.instrument(mod, p, (("f", "f"), ("not_there", "missing")))
    assert mod.f() == 1 and buf.getvalue() == ""


@pytest.fixture
def ask_env(monkeypatch, tmp_path):
    class Dummy:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setenv("MODEL_API_KEY", "test-key-not-real")
    monkeypatch.setenv("AUTOSOLAR_CAMS_EMAIL", "cams-test-address")
    monkeypatch.setenv("AUTOSOLAR_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.setattr(ask, "MetaClient", Dummy)
    monkeypatch.setattr(ask, "Ledger", Dummy)
    monkeypatch.setattr(ask, "cached_fetchers", lambda *a, **k: None)
    monkeypatch.setattr(ask, "default_fetchers", lambda *a, **k: None)
    return tmp_path


def test_main_restores_the_study_module_after_a_refusal(ask_env, monkeypatch, capsys):
    originals = {name: getattr(study, name) for name, _ in ask.STAGES}

    def fake_run_study(question, **kwargs):
        raise UnsupportedSite("site outside the Karimunjawa demand source area")

    monkeypatch.setattr(ask, "run_study", fake_run_study)
    monkeypatch.setattr(sys, "argv", ["ask.py", "Is solar worth it for Bawean?", "--runs", str(ask_env)])
    with pytest.raises(SystemExit):
        ask.main()
    for name, fn in originals.items():
        assert getattr(study, name) is fn, name


def test_main_reports_stages_and_weather_without_the_address(ask_env, monkeypatch, capsys):
    def fake_build(lat_deg, lon_deg, cams_email, fetchers):
        raise UnsupportedSite("site outside the Karimunjawa demand source area")

    def fake_run_study(question, *, weather_fn, **kwargs):
        assert hasattr(study.geocode, "__wrapped__")  # the study module is instrumented during the run
        weather_fn(-5.85, 110.43)

    monkeypatch.setattr(ask, "build_weather_cases", fake_build)
    monkeypatch.setattr(ask, "run_study", fake_run_study)
    monkeypatch.setattr(sys, "argv", ["ask.py", "Is solar worth it for Karimunjawa?", "--runs", str(ask_env)])
    with pytest.raises(SystemExit) as exc:
        ask.main()
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "[0:00] " + ask.WEATHER_LABEL
    assert "cams-test-address" not in out and "test-key-not-real" not in out


def test_main_wraps_the_study_stages_during_the_run(ask_env, monkeypatch, capsys):
    calls = []

    def fake_run_study(question, **kwargs):
        calls.append(study.build_demand_cases.__wrapped__ is not None)
        raise UnsupportedSite("site outside the Karimunjawa demand source area")

    monkeypatch.setattr(ask, "run_study", fake_run_study)
    monkeypatch.setattr(sys, "argv", ["ask.py", "Is solar worth it for Karimunjawa?", "--runs", str(ask_env)])
    with pytest.raises(SystemExit):
        ask.main()
    assert calls == [True]
    assert not hasattr(study.build_demand_cases, "__wrapped__")


def test_main_ends_with_a_short_summary_that_fits_on_screen(ask_env, monkeypatch, capsys):
    """Written Monday 2 Nov after the first screen recording: the full output is about 90 lines, so the answer and
    the run hash scrolled off the top. The last three lines now repeat them."""
    def fact(text, unit):
        return {"text": text, "unit": unit, "label": "computed"}

    facts = {"best_pv_kwp": fact("7,250", "kWp"), "best_battery_kwh": fact("19,000", "kWh"),
             "best_lcoe_usd_per_kwh": fact("0.251", "USD/kWh"), "diesel_only_lcoe_usd_per_kwh": fact("0.354", "USD/kWh"),
             "best_renewable_pct": fact("85.8", "%"), "fuel_saved_l_yr": fact("3,104,445", "L/yr"),
             "co2_saved_t_yr": fact("8,320", "t/yr"), "break_even_fuel_usd_per_l": fact("0.27", "USD/L")}
    gates = [{"gate": "G%d" % n, "scope": "s", "passed": n != 5} for n in range(1, 12)]
    result = types.SimpleNamespace(run_hash="b4a44fc6d4c32339", reused=False, run_dir="folder",
                                   report={"facts": facts, "gates": gates, "firmness": None})
    monkeypatch.setattr(ask, "run_study", lambda question, **kwargs: result)
    monkeypatch.setattr(sys, "argv", ["ask.py", "Is solar worth it for Karimunjawa?", "--runs", str(ask_env)])
    ask.main()
    last = capsys.readouterr().out.splitlines()[-3:]
    assert last[0] == ("Answer: 7,250 kWp solar and 19,000 kWh battery at 0.251 USD/kWh; "
                       "diesel only 0.354 USD/kWh (computed)")
    assert last[1] == "Checks: 10 of 11 passed"
    assert last[2].startswith("run b4a44fc6d4c32339 new ") and last[2].endswith(" s")
