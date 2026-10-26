"""Acceptance tests for T02 (docs/specs/T02_meta_client.md). Written by the orchestrator before the code."""
import pytest
import requests

from autosolar.ledger import BudgetExceeded, Ledger, UnknownModel
from autosolar.meta_client import (DEFAULT_MODEL, STANDARD_SPARK_MODELS, MetaAPIError, MetaClient, Result)

KEY = "test-key-0123456789abcdef"


class FakeResp:
    def __init__(self, status, body=None, headers=None, text=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = headers or {}
        self.text = text if text is not None else str(self._body)

    def json(self):
        return self._body


class FakePost:
    """Returns the queued responses in order; an Exception in the queue is raised instead."""

    def __init__(self, *queue):
        self.queue = list(queue)
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok_body(model=DEFAULT_MODEL, usage=True):
    body = {
        "id": "resp_1",
        "model": model,
        "output": [
            {"type": "reasoning", "summary": []},
            {"type": "web_search_call", "id": "ws_1", "status": "completed"},
            {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "Diesel costs ", "annotations": []},
                {"type": "output_text", "text": "IDR 6,800 per litre.", "annotations": [
                    {"type": "url_citation", "url": "https://example.org/a", "title": "A", "start_index": 0,
                     "end_index": 20}]},
            ]},
        ],
    }
    if usage:
        body["usage"] = {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 200},
                         "output_tokens": 300, "output_tokens_details": {"reasoning_tokens": 100},
                         "total_tokens": 1300}
    return body


RL = {"x-ratelimit-remaining-requests": "149", "x-ratelimit-limit-requests": "150",
      "x-ratelimit-remaining-tokens": "2999000", "x-ratelimit-limit-tokens": "3000000"}


def make(tmp_path, post, **kw):
    led = Ledger(tmp_path / "l.jsonl")
    return led, MetaClient(led, api_key=KEY, post=post, sleep=lambda s: None, **kw)


def test_constants():
    assert DEFAULT_MODEL == "muse-spark-1.3-contributor"
    assert STANDARD_SPARK_MODELS == {"muse-spark-1.3", "muse-spark-1.2", "muse-spark-1.1"}


def test_missing_key(monkeypatch, tmp_path):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as e:
        MetaClient(Ledger(tmp_path / "l.jsonl"))
    assert "MODEL_API_KEY" in str(e.value)


def test_key_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_API_KEY", KEY)
    post = FakePost(FakeResp(200, ok_body()))
    MetaClient(Ledger(tmp_path / "l.jsonl"), post=post).respond("r1", "S3", "hi", estimate_usd=0.01)
    assert post.calls[0]["headers"]["Authorization"] == f"Bearer {KEY}"


def test_happy_path(tmp_path):
    post = FakePost(FakeResp(200, ok_body(), headers=RL))
    led, c = make(tmp_path, post)
    r = c.respond("r1", "S3", "diesel price Karimunjawa", estimate_usd=0.05, tools=[{"type": "web_search"}],
                  reasoning_effort="high")
    assert isinstance(r, Result)
    call = post.calls[0]
    assert call["url"] == "https://api.meta.ai/v1/responses"
    assert call["json"] == {"model": DEFAULT_MODEL, "input": "diesel price Karimunjawa",
                            "tools": [{"type": "web_search"}], "reasoning": {"effort": "high"}}
    assert r.text == "Diesel costs IDR 6,800 per litre."
    assert r.citations == [{"url": "https://example.org/a", "title": "A", "start_index": 0, "end_index": 20}]
    assert r.web_searches == 1 and r.response_id == "resp_1" and r.model == DEFAULT_MODEL
    expected = (800 * 0.10 + 200 * 0.002 + 300 * 0.20) / 1e6 + 0.0025
    assert r.cost_usd == pytest.approx(expected)
    rows = led.rows()
    assert len(rows) == 1 and rows[0]["stage"] == "S3"
    assert rows[0]["usage"] == {"input_tokens": 1000, "cached_tokens": 200, "output_tokens": 300,
                                "reasoning_tokens": 100, "search_queries": 1}
    assert r.rate_limit == RL


def test_optional_fields_absent_when_not_given(tmp_path):
    post = FakePost(FakeResp(200, ok_body()))
    make(tmp_path, post)[1].respond("r1", "S3", "hi", estimate_usd=0.01)
    assert post.calls[0]["json"] == {"model": DEFAULT_MODEL, "input": "hi"}


def test_missing_usage_details_count_as_zero(tmp_path):
    body = ok_body()
    body["usage"] = {"input_tokens": 50, "output_tokens": 10}
    led, c = make(tmp_path, FakePost(FakeResp(200, body)))
    c.respond("r1", "S3", "hi", estimate_usd=0.01)
    assert led.rows()[0]["usage"]["cached_tokens"] == 0 and led.rows()[0]["usage"]["reasoning_tokens"] == 0


def test_standard_model_refused(tmp_path):
    post = FakePost()
    _, c = make(tmp_path, post)
    with pytest.raises(ValueError):
        c.respond("r1", "S3", "hi", estimate_usd=0.01, model="muse-spark-1.3")
    assert post.calls == []


def test_standard_model_allowed_when_asked(tmp_path):
    post = FakePost(FakeResp(200, ok_body(model="muse-spark-1.3")))
    led, c = make(tmp_path, post)
    r = c.respond("r1", "S3", "hi", estimate_usd=0.05, model="muse-spark-1.3", allow_standard=True)
    assert r.cost_usd == pytest.approx((800 * 1.25 + 200 * 0.15 + 300 * 4.25) / 1e6 + 0.0025)


def test_unknown_model(tmp_path):
    post = FakePost()
    with pytest.raises(UnknownModel):
        make(tmp_path, post)[1].respond("r1", "S3", "hi", estimate_usd=0.01, model="gpt-9")
    assert post.calls == []


def test_budget_checked_before_call(tmp_path):
    post = FakePost()
    _, c = make(tmp_path, post)
    with pytest.raises(BudgetExceeded):
        c.respond("r1", "S3", "hi", estimate_usd=6.0)
    assert post.calls == []


def test_retry_on_429_then_ok(tmp_path):
    waits = []
    post = FakePost(FakeResp(429, {"error": "slow down"}), FakeResp(200, ok_body()))
    led = Ledger(tmp_path / "l.jsonl")
    c = MetaClient(led, api_key=KEY, post=post, sleep=waits.append)
    c.respond("r1", "S3", "hi", estimate_usd=0.01)
    assert len(post.calls) == 2 and len(waits) == 1 and 0.5 <= waits[0] <= 0.75
    assert len(led.rows()) == 1


def test_retry_on_connection_error(tmp_path):
    post = FakePost(requests.ConnectionError("reset"), requests.Timeout("slow"), FakeResp(200, ok_body()))
    led, c = make(tmp_path, post)
    c.respond("r1", "S3", "hi", estimate_usd=0.01)
    assert len(post.calls) == 3 and len(led.rows()) == 1


def test_gives_up_after_max_retries(tmp_path):
    post = FakePost(*[FakeResp(503, {"error": "busy"}) for _ in range(3)])
    led, c = make(tmp_path, post, max_retries=2)
    with pytest.raises(MetaAPIError) as e:
        c.respond("r1", "S3", "hi", estimate_usd=0.01)
    assert len(post.calls) == 3 and led.rows() == [] and "503" in str(e.value)


def test_no_retry_on_400_and_key_scrubbed(tmp_path):
    post = FakePost(FakeResp(400, text=f"bad request, key {KEY} was used"))
    _, c = make(tmp_path, post)
    with pytest.raises(MetaAPIError) as e:
        c.respond("r1", "S3", "hi", estimate_usd=0.01)
    assert len(post.calls) == 1
    assert "400" in str(e.value) and KEY not in str(e.value) and "<key>" in str(e.value)


def test_long_error_body_truncated(tmp_path):
    post = FakePost(FakeResp(401, text="x" * 5000))
    with pytest.raises(MetaAPIError) as e:
        make(tmp_path, post)[1].respond("r1", "S3", "hi", estimate_usd=0.01)
    assert len(str(e.value)) < 700


def test_no_usage_fails_loudly(tmp_path):
    post = FakePost(FakeResp(200, ok_body(usage=False)))
    with pytest.raises(MetaAPIError):
        make(tmp_path, post)[1].respond("r1", "S3", "hi", estimate_usd=0.01)


def test_model_mismatch_recorded_then_raises(tmp_path):
    post = FakePost(FakeResp(200, ok_body(model="muse-spark-1.3")))
    led, c = make(tmp_path, post)
    with pytest.raises(MetaAPIError):
        c.respond("r1", "S3", "hi", estimate_usd=0.01)
    assert len(led.rows()) == 1


def test_sam_billed_per_image(tmp_path):
    body = {"id": "resp_s", "model": "sam-3.1", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": "<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10|>", "annotations": []}]}],
        "usage": {"input_tokens": 999, "output_tokens": 999}}
    post = FakePost(FakeResp(200, body))
    led, c = make(tmp_path, post)
    r = c.respond("r1", "S4", [{"role": "user", "content": []}], estimate_usd=0.01, model="sam-3.1", images=1)
    assert r.cost_usd == pytest.approx(0.0025) and r.text.startswith("<0f>0")
    assert led.rows()[0]["usage"] == {"images": 1}


def test_image_count_rules(tmp_path):
    post = FakePost()
    _, c = make(tmp_path, post)
    with pytest.raises(ValueError):
        c.respond("r1", "S4", "roof", estimate_usd=0.01, model="sam-3.1", images=0)
    with pytest.raises(ValueError):
        c.respond("r1", "S3", "hi", estimate_usd=0.01, images=2)
    assert post.calls == []


def test_key_never_in_result_or_ledger(tmp_path):
    post = FakePost(FakeResp(200, ok_body()))
    led, c = make(tmp_path, post)
    r = c.respond("r1", "S3", "hi", estimate_usd=0.01)
    assert KEY not in repr(r) and KEY not in (tmp_path / "l.jsonl").read_text(encoding="utf-8")
