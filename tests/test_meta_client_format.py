"""Acceptance tests for T12b (structured output in autosolar/meta_client.py). Written by the orchestrator."""
import pytest

from autosolar.meta_client import DEFAULT_MODEL
from test_meta_client import FakePost, FakeResp, make, ok_body

FMT = {"type": "json_schema", "name": "Extraction", "strict": True,
       "schema": {"type": "object", "properties": {"x": {"type": "number"}}, "required": ["x"],
                  "additionalProperties": False}}


def test_text_format_in_body(tmp_path):
    post = FakePost(FakeResp(200, ok_body()))
    led, c = make(tmp_path, post)
    r = c.respond("r1", "S7", "read this", estimate_usd=0.01, text_format=FMT)
    body = post.calls[0]["json"]
    assert body == {"model": DEFAULT_MODEL, "input": "read this", "text": {"format": FMT}}
    assert r.text == "Diesel costs IDR 6,800 per litre."
    assert len(led.rows()) == 1


def test_key_order_with_other_fields(tmp_path):
    post = FakePost(FakeResp(200, ok_body()))
    make(tmp_path, post)[1].respond("r1", "S7", "x", estimate_usd=0.01, tools=[{"type": "web_search"}],
                                    reasoning_effort="low", include=["a"], metadata={"k": "v"}, text_format=FMT)
    body = post.calls[0]["json"]
    assert list(body) == ["model", "input", "tools", "reasoning", "include", "metadata", "text"]
    assert body["text"] == {"format": FMT}


def test_absent_by_default(tmp_path):
    post = FakePost(FakeResp(200, ok_body()))
    make(tmp_path, post)[1].respond("r1", "S7", "x", estimate_usd=0.01)
    assert "text" not in post.calls[0]["json"]


@pytest.mark.parametrize("bad", [
    {"type": "json_object", "name": "x", "schema": {}},
    {"type": "json_schema", "schema": {}},
    {"type": "json_schema", "name": 5, "schema": {}},
    {"type": "json_schema", "name": "x", "schema": "not a dict"},
    {"type": "json_schema", "name": "x"},
    "json_schema",
    ["json_schema"],
])
def test_bad_format_raises_before_any_call(tmp_path, bad):
    post = FakePost(FakeResp(200, ok_body()))
    led, c = make(tmp_path, post)
    with pytest.raises(ValueError, match="text_format must be a json_schema dict"):
        c.respond("r1", "S7", "x", estimate_usd=0.01, text_format=bad)
    assert post.calls == [] and led.rows() == []


def test_bad_format_checked_before_budget(tmp_path):
    post = FakePost(FakeResp(200, ok_body()))
    led, c = make(tmp_path, post)
    with pytest.raises(ValueError, match="text_format"):
        c.respond("r1", "S7", "x", estimate_usd=999.0, text_format={"type": "nope"})
    assert post.calls == []
