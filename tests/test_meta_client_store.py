"""Acceptance tests for T12c (store flag in autosolar/meta_client.py). Written by the orchestrator."""
import pytest

from autosolar.meta_client import DEFAULT_MODEL
from test_meta_client import FakePost, FakeResp, make, ok_body
from test_meta_client_format import FMT


@pytest.mark.parametrize("flag", [False, True])
def test_store_in_body(tmp_path, flag):
    post = FakePost(FakeResp(200, ok_body()))
    led, c = make(tmp_path, post)
    c.respond("r1", "S7", "x", estimate_usd=0.01, store=flag)
    assert post.calls[0]["json"] == {"model": DEFAULT_MODEL, "input": "x", "store": flag}
    assert len(led.rows()) == 1


def test_store_is_last(tmp_path):
    post = FakePost(FakeResp(200, ok_body()))
    make(tmp_path, post)[1].respond("r1", "S7", "x", estimate_usd=0.01, tools=[{"type": "web_search"}],
                                    reasoning_effort="low", include=["a"], metadata={"k": "v"}, text_format=FMT,
                                    store=False)
    assert list(post.calls[0]["json"]) == ["model", "input", "tools", "reasoning", "include", "metadata", "text",
                                           "store"]


def test_store_absent_by_default(tmp_path):
    post = FakePost(FakeResp(200, ok_body()))
    make(tmp_path, post)[1].respond("r1", "S7", "x", estimate_usd=0.01, store=None)
    assert "store" not in post.calls[0]["json"]


@pytest.mark.parametrize("bad", [0, 1, "false", "False", 0.0, [False]])
def test_bad_store_raises_before_any_call(tmp_path, bad):
    post = FakePost(FakeResp(200, ok_body()))
    led, c = make(tmp_path, post)
    with pytest.raises(ValueError, match="store must be a bool"):
        c.respond("r1", "S7", "x", estimate_usd=999.0, store=bad)
    assert post.calls == [] and led.rows() == []
