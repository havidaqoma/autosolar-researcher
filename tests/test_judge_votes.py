"""Acceptance tests for T10f (the support judge must say yes 3 times in a row). Written by the orchestrator.
No network."""
import dataclasses
import json

import pytest

from autosolar.cite_check import (
    JUDGE_VOTES,
    CitationCheck,
    Claim,
    check_citation,
    support_verdict,
    support_votes,
)

URL = "https://www.example.org/island-grid"
TITLE = "Island grid operation guide"
QUOTE = "Each diesel generator is kept above 30% of its rated capacity at all times."
HTML = ("<html><head><title>" + TITLE + "</title></head><body><p>Operation.</p><p>" + QUOTE
        + "</p></body></html>").encode("utf-8")
JUDGE = "muse-glimmer (local)"


def yes(reason="The quote states the value."):
    return json.dumps({"supports": True, "reason": reason})


def no(reason="Not this input."):
    return json.dumps({"supports": False, "reason": reason})


class Seq:
    """Gives the listed answers in order; an Exception item is raised."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        item = self.answers[len(self.prompts) - 1]
        if isinstance(item, Exception):
            raise item
        return item


class Resp:
    def __init__(self, status, content=b"", url=None):
        self.status_code = status
        self.content = content
        self.url = url
        self.headers = {}


class FakeGet:
    def __init__(self, table):
        self.table = table

    def __call__(self, url, **kwargs):
        item = self.table.get(url)
        if item is None:
            return Resp(404, b"{}")
        return item


def claim(**kw):
    base = dict(input_name="diesel_min_load_frac", description="minimum load of a diesel generator set", value=30,
                unit="% of its rated capacity", url=URL, doi=None, quote=QUOTE, title=TITLE, currency_year=None)
    base.update(kw)
    return Claim(**base)


def one_prompt(c, context, **kw):
    rec = Seq([yes()])
    support_verdict(rec, c, context, **kw)
    return rec.prompts[0]


def run(c, judge, table=None):
    return check_citation(c, http_get=FakeGet(table if table is not None else {URL: Resp(200, HTML)}),
                          judge_fn=judge, judge_name=JUDGE, target_unit="frac", band_lo=0.1, band_hi=0.6)


# ---------------------------------------------------------------- 1. constant

def test_constant():
    assert JUDGE_VOTES == 3


# ---------------------------------------------------------------- 2. support_votes

def test_all_yes_three_same_prompts():
    judge = Seq([yes("r1"), yes("r2"), yes("r3")])
    v, n = support_votes(judge, claim(), "ctx")
    assert (v.supports, v.reason, n) == (True, "r3", 3)
    assert judge.prompts == [one_prompt(claim(), "ctx")] * 3


def test_default_votes_is_constant():
    judge = Seq([yes()] * 10)
    v, n = support_votes(judge, claim(), "ctx")
    assert n == JUDGE_VOTES and len(judge.prompts) == JUDGE_VOTES


def test_first_no_stops():
    judge = Seq([no("a"), yes(), yes()])
    v, n = support_votes(judge, claim(), "ctx")
    assert (v.supports, v.reason, n) == (False, "a", 1) and len(judge.prompts) == 1


def test_second_no_stops():
    judge = Seq([yes(), no("b"), yes()])
    v, n = support_votes(judge, claim(), "ctx")
    assert (v.supports, v.reason, n) == (False, "b", 2) and len(judge.prompts) == 2


def test_third_no_fails():
    judge = Seq([yes(), yes(), no("c")])
    v, n = support_votes(judge, claim(), "ctx")
    assert (v.supports, v.reason, n) == (False, "c", 3)
    assert v.raw == no("c")


def test_unparsed_stops():
    judge = Seq([yes(), "maybe", yes()])
    v, n = support_votes(judge, claim(), "ctx")
    assert (v.supports, v.reason, n) == (None, "unparsed judge answer", 2) and len(judge.prompts) == 2
    assert v.raw == "maybe"


def test_judge_error_stops():
    judge = Seq([yes(), RuntimeError("down"), yes()])
    v, n = support_votes(judge, claim(), "ctx")
    assert (v.supports, v.reason, n) == (None, "judge error: RuntimeError", 2)


def test_first_unparsed_stops_at_one():
    judge = Seq(["no json here", yes(), yes()])
    v, n = support_votes(judge, claim(), "ctx")
    assert (v.supports, n) == (None, 1)


@pytest.mark.parametrize("votes", [1, 2, 5])
def test_other_vote_counts(votes):
    judge = Seq([yes("r%d" % i) for i in range(1, 8)])
    v, n = support_votes(judge, claim(), "ctx", votes=votes)
    assert (v.supports, v.reason, n) == (True, "r%d" % votes, votes) and len(judge.prompts) == votes


@pytest.mark.parametrize("bad", [0, -1, True, False, 2.0, 3.0, "3", None])
def test_bad_votes_raise_before_any_call(bad):
    judge = Seq([yes()] * 5)
    with pytest.raises(ValueError, match="votes must be an int >= 1"):
        support_votes(judge, claim(), "ctx", votes=bad)
    assert judge.prompts == []


def test_title_and_url_passed_to_every_vote():
    judge = Seq([yes()] * 3)
    support_votes(judge, claim(), "ctx", source_title="A title for the source", source_url="https://a.org/x")
    want = one_prompt(claim(), "ctx", source_title="A title for the source", source_url="https://a.org/x")
    assert judge.prompts == [want] * 3
    assert "\nSource title: A title for the source\nSource URL: https://a.org/x\n" in want


# ---------------------------------------------------------------- 3. check_citation

def test_dataclass_field():
    last = dataclasses.fields(CitationCheck)[-1]
    assert last.name == "judge_calls" and last.default == 0


def test_check_all_yes_checked():
    judge = Seq([yes("r1"), yes("r2"), yes("r3")])
    c = run(claim(), judge)
    assert c.status == "checked" and c.reasons == [] and c.supports is True
    assert c.judge_calls == 3 and c.judge_reason == "r3"
    assert len(judge.prompts) == 3 and len(set(judge.prompts)) == 1
    assert "\nSource title: " + TITLE + "\nSource URL: " + URL + "\n" in judge.prompts[0]
    assert dataclasses.asdict(c)["judge_calls"] == 3
    json.dumps(dataclasses.asdict(c))


def test_check_first_no():
    judge = Seq([no("a"), yes(), yes()])
    c = run(claim(), judge)
    assert c.status == "assumed" and c.reasons == ["judge says not supported: a"]
    assert (c.supports, c.judge_reason, c.judge_calls) == (False, "a", 1)


def test_check_late_no():
    judge = Seq([yes(), yes(), no("c")])
    c = run(claim(), judge)
    assert c.status == "assumed" and c.reasons == ["judge says not supported: c"]
    assert (c.supports, c.judge_reason, c.judge_calls) == (False, "c", 3)
    assert c.value_converted == pytest.approx(0.3)


def test_check_unparsed_vote():
    judge = Seq([yes(), "maybe"])
    c = run(claim(), judge)
    assert c.status == "assumed" and c.reasons == ["judge gave no verdict: unparsed judge answer"]
    assert (c.supports, c.judge_calls) == (None, 2)


def test_check_judge_error_vote():
    judge = Seq([yes(), yes(), RuntimeError("down")])
    c = run(claim(), judge)
    assert c.reasons == ["judge gave no verdict: judge error: RuntimeError"] and c.judge_calls == 3


def test_check_no_judge_when_script_fails():
    judge = Seq([yes()] * 3)
    c = run(claim(value=31), judge)
    assert c.reasons == ["value not in the quoted source text"]
    assert (judge.prompts, c.judge_calls, c.supports, c.judge_reason) == ([], 0, None, "")


def test_check_no_judge_when_fetch_fails():
    judge = Seq([yes()] * 3)
    c = run(claim(), judge, table={})
    assert c.status == "assumed" and c.judge_calls == 0 and judge.prompts == []


def test_check_no_judge_when_band_fails():
    judge = Seq([yes()] * 3)
    c = check_citation(claim(), http_get=FakeGet({URL: Resp(200, HTML)}), judge_fn=judge, judge_name=JUDGE,
                       target_unit="frac", band_lo=0.4, band_hi=0.6)
    assert "outside band" in c.reasons[0] and c.judge_calls == 0 and judge.prompts == []
