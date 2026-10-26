"""Acceptance tests for T01 (docs/specs/T01_ledger.md). Written by the orchestrator before the code."""
import datetime as dt
import json

import pytest

from autosolar.ledger import (PRICES, WEB_SEARCH_USD_PER_QUERY, BudgetExceeded, Ledger, UnknownModel,
                              call_cost_usd)

DAY1 = dt.datetime(2026, 10, 28, 12, 0, tzinfo=dt.timezone.utc).timestamp()


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def usd_of_wonder_output(usd):
    """Wonder output costs USD 20 per 1M tokens, so USD 1 is 50,000 output tokens."""
    return int(round(usd * 50_000))


# ---- prices -------------------------------------------------------------------------------------------------

def test_every_model_priced():
    for m in ["muse-spark-1.3-contributor", "muse-spark-1.2-contributor", "muse-spark-1.3", "muse-spark-1.2",
              "muse-spark-1.1", "muse-wonder-1.0", "sam-3.1", "muse-image-1.0", "muse-voice-transcribe-1.0",
              "muse-glimmer-local"]:
        assert m in PRICES and PRICES[m]["kind"] in {"tokens", "per_image", "per_audio_s", "free"}
    assert WEB_SEARCH_USD_PER_QUERY == pytest.approx(0.0025)


def test_contributor_tokens():
    assert call_cost_usd("muse-spark-1.3-contributor", input_tokens=1_000_000, output_tokens=1_000_000) \
        == pytest.approx(0.30)


def test_contributor_cached_matches_muse_code_probe():
    # measured Muse Code run: 143,055 input of which 113,732 cached, 679 output
    c = call_cost_usd("muse-spark-1.3-contributor", input_tokens=143_055, cached_tokens=113_732,
                      output_tokens=679, reasoning_tokens=253)
    assert c == pytest.approx((29_323 * 0.10 + 113_732 * 0.002 + 679 * 0.20) / 1e6)


def test_reasoning_tokens_not_billed_twice():
    a = call_cost_usd("muse-spark-1.3", input_tokens=1000, output_tokens=500)
    b = call_cost_usd("muse-spark-1.3", input_tokens=1000, output_tokens=500, reasoning_tokens=400)
    assert a == pytest.approx(b)


def test_standard_and_wonder():
    assert call_cost_usd("muse-spark-1.3", input_tokens=1_000_000, output_tokens=1_000_000) == pytest.approx(5.50)
    assert call_cost_usd("muse-wonder-1.0", input_tokens=80_000, output_tokens=8_000) == pytest.approx(0.48)
    assert call_cost_usd("muse-wonder-1.0", input_tokens=1_000_000, cached_tokens=1_000_000) == pytest.approx(0.20)


def test_search_queries():
    assert call_cost_usd("muse-spark-1.3-contributor", search_queries=40) == pytest.approx(0.10)


def test_per_unit_models():
    assert call_cost_usd("sam-3.1", images=12) == pytest.approx(0.03)
    assert call_cost_usd("muse-image-1.0", images=4) == pytest.approx(0.04)
    assert call_cost_usd("muse-voice-transcribe-1.0", audio_s=3600) == pytest.approx(0.18)
    assert call_cost_usd("muse-glimmer-local", input_tokens=7142, output_tokens=1492) == 0


def test_unknown_model():
    with pytest.raises(UnknownModel):
        call_cost_usd("gpt-9", input_tokens=1)
    assert issubclass(UnknownModel, ValueError)


@pytest.mark.parametrize("kw", [{"input_tokens": -1}, {"output_tokens": -5}, {"input_tokens": 10, "cached_tokens": 11}])
def test_bad_counts(kw):
    with pytest.raises(ValueError):
        call_cost_usd("muse-spark-1.3-contributor", **kw)


@pytest.mark.parametrize("model,kw", [
    ("sam-3.1", {"input_tokens": 10}),
    ("sam-3.1", {"search_queries": 1}),
    ("muse-spark-1.3-contributor", {"images": 1}),
    ("muse-spark-1.3-contributor", {"audio_s": 3}),
    ("muse-voice-transcribe-1.0", {"images": 1}),
    ("muse-image-1.0", {"output_tokens": 5}),
    ("muse-glimmer-local", {"images": 1}),
    ("muse-glimmer-local", {"search_queries": 1}),
])
def test_wrong_unit_for_model(model, kw):
    with pytest.raises(ValueError):
        call_cost_usd(model, **kw)


# ---- ledger -------------------------------------------------------------------------------------------------

def test_missing_file_is_zero(tmp_path):
    assert Ledger(tmp_path / "l.jsonl").spent_usd() == 0


def test_record_persists_and_row_shape(tmp_path):
    p = tmp_path / "l.jsonl"
    led = Ledger(p, clock=Clock(DAY1))
    row = led.record("run1", "S3", "muse-wonder-1.0", output_tokens=usd_of_wonder_output(1.0))
    assert set(row) == {"ts_unix", "run_id", "stage", "model", "live", "usage", "cost_usd"}
    assert row["cost_usd"] == pytest.approx(1.0) and row["live"] is False and row["ts_unix"] == DAY1
    assert row["usage"] == {"output_tokens": 50_000}
    led.record("run2", "S4", "sam-3.1", images=12)
    other = Ledger(p)
    assert other.spent_usd() == pytest.approx(1.03)
    assert other.spent_usd(run_id="run1") == pytest.approx(1.0)
    assert len(other.rows()) == 2
    assert all(json.loads(l) for l in p.read_text(encoding="utf-8").splitlines())


def test_unknown_usage_key_writes_nothing(tmp_path):
    p = tmp_path / "l.jsonl"
    with pytest.raises(ValueError):
        Ledger(p).record("run1", "S3", "muse-spark-1.3-contributor", tokens_in=5)
    assert not p.exists() or p.read_text(encoding="utf-8").strip() == ""


def test_study_cap(tmp_path):
    led = Ledger(tmp_path / "l.jsonl", study_cap_usd=5.0)
    led.record("runA", "S3", "muse-wonder-1.0", output_tokens=usd_of_wonder_output(4.9))
    with pytest.raises(BudgetExceeded):
        led.check("runA", 0.2)
    led.check("runA", 0.1)          # exactly at the cap is allowed
    led.check("runB", 4.0)          # other runs have their own cap
    with pytest.raises(ValueError):
        led.check("runA", -0.1)


def test_record_never_refuses(tmp_path):
    led = Ledger(tmp_path / "l.jsonl", study_cap_usd=1.0)
    led.record("runA", "S3", "muse-wonder-1.0", output_tokens=usd_of_wonder_output(3.0))
    assert led.spent_usd(run_id="runA") == pytest.approx(3.0)


def test_total_cap(tmp_path):
    led = Ledger(tmp_path / "l.jsonl", total_cap_usd=1.0)
    led.record("r1", "S3", "muse-wonder-1.0", output_tokens=usd_of_wonder_output(0.6))
    led.record("r2", "S3", "muse-wonder-1.0", output_tokens=usd_of_wonder_output(0.3))
    with pytest.raises(BudgetExceeded) as e:
        led.check("r3", 0.2)
    assert "total" in str(e.value).lower()


def test_live_caps_and_day_reset(tmp_path):
    clock = Clock(DAY1)
    led = Ledger(tmp_path / "l.jsonl", clock=clock)
    for r in ("L1", "L2", "L3"):
        led.record(r, "S3", "muse-wonder-1.0", live=True, output_tokens=usd_of_wonder_output(1.5))
    led.record("dev", "S3", "muse-wonder-1.0", output_tokens=usd_of_wonder_output(1.0))  # not live
    assert led.spent_usd(live_day=dt.date(2026, 10, 28)) == pytest.approx(4.5)
    with pytest.raises(BudgetExceeded):
        led.check("L1", 0.6, live=True)            # live run cap 2.0
    led.check("L1", 0.6)                            # same spend is fine for a non live study
    with pytest.raises(BudgetExceeded):
        led.check("L4", 0.6, live=True)            # live daily cap 5.0
    led.check("L4", 0.5, live=True)                 # exactly 5.0 is allowed
    clock.t = DAY1 + 86_400
    led.check("L5", 1.9, live=True)                 # new UTC day
    assert led.spent_usd(live_day=dt.date(2026, 10, 29)) == 0


def test_corrupt_line_fails_loudly(tmp_path):
    p = tmp_path / "l.jsonl"
    Ledger(p).record("r1", "S4", "sam-3.1", images=1)
    with open(p, "a", encoding="utf-8") as f:
        f.write("{not json\n")
    with pytest.raises(ValueError):
        Ledger(p).spent_usd()
