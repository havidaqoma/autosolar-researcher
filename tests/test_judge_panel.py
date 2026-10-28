"""Acceptance tests for T17 (two judge models: the local judge twice, then Muse Wonder). Written by the orchestrator.
No network."""
import functools
import json

import pytest

from autosolar import sourcing
from autosolar.cite_check import JUDGE_VOTES, Claim, check_citation, support_verdict, support_votes
from autosolar.ledger import BudgetExceeded
from autosolar.sourcing import (WONDER_JUDGE_ESTIMATE_USD, WONDER_JUDGE_STAGE, WONDER_MODEL, judge_panel,
                                wonder_judge)

URL = "https://www.example.org/island-grid"
TITLE = "Island grid operation guide"
QUOTE = "Each diesel generator is kept above 30% of its rated capacity at all times."
HTML = ("<html><head><title>" + TITLE + "</title></head><body><p>Operation.</p><p>" + QUOTE
        + "</p></body></html>").encode("utf-8")
PANEL_NAME = "local judge (votes 1 and 2) and muse-wonder-1.0 (vote 3)"


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


class Result:
    def __init__(self, text):
        self.text = text
        self.cost_usd = 0.01


class FakeClient:
    """Records respond calls; gives the listed texts in order; an Exception item is raised."""

    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = []

    def respond(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        item = self.texts[len(self.calls) - 1]
        if isinstance(item, Exception):
            raise item
        return Result(item)


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
                          judge_fn=judge, judge_name=PANEL_NAME, target_unit="frac", band_lo=0.1, band_hi=0.6)


# ---------------------------------------------------------------- 1. support_votes with a panel

def test_panel_all_yes_each_judge_once_in_order():
    a, b, c = Seq([yes("r1")]), Seq([yes("r2")]), Seq([yes("r3")])
    v, n = support_votes((a, b, c), claim(), "ctx")
    assert (v.supports, v.reason, n) == (True, "r3", 3)
    want = one_prompt(claim(), "ctx")
    assert a.prompts == [want] and b.prompts == [want] and c.prompts == [want]


def test_panel_same_prompt_with_title_and_url():
    a, b, c = Seq([yes()]), Seq([yes()]), Seq([yes()])
    support_votes((a, b, c), claim(), "ctx", source_title="A title for the source", source_url="https://a.org/x")
    want = one_prompt(claim(), "ctx", source_title="A title for the source", source_url="https://a.org/x")
    assert a.prompts == b.prompts == c.prompts == [want]


def test_panel_first_no_stops_before_others():
    a, b, c = Seq([no("a")]), Seq([yes()]), Seq([yes()])
    v, n = support_votes((a, b, c), claim(), "ctx")
    assert (v.supports, v.reason, n) == (False, "a", 1)
    assert b.prompts == [] and c.prompts == []


def test_panel_second_unparsed_stops_before_third():
    a, b, c = Seq([yes()]), Seq(["maybe"]), Seq([yes()])
    v, n = support_votes((a, b, c), claim(), "ctx")
    assert (v.supports, v.reason, n) == (None, "unparsed judge answer", 2)
    assert v.raw == "maybe" and c.prompts == []


def test_panel_third_no_is_the_third_judges_answer():
    a, b, c = Seq([yes("r1")]), Seq([yes("r2")]), Seq([no("wonder says no")])
    v, n = support_votes((a, b, c), claim(), "ctx")
    assert (v.supports, v.reason, n) == (False, "wonder says no", 3)
    assert v.raw == no("wonder says no")


def test_panel_third_error_is_no_verdict():
    a, b, c = Seq([yes()]), Seq([yes()]), Seq([RuntimeError("api down")])
    v, n = support_votes((a, b, c), claim(), "ctx")
    assert (v.supports, v.reason, n) == (None, "judge error: RuntimeError", 3)


def test_panel_budget_refusal_is_no_verdict():
    a, b, c = Seq([yes()]), Seq([yes()]), Seq([BudgetExceeded("cap")])
    v, n = support_votes((a, b, c), claim(), "ctx")
    assert (v.supports, v.reason, n) == (None, "judge error: BudgetExceeded", 3)


def test_panel_same_function_twice_is_called_twice():
    local, wonder = Seq([yes("l1"), yes("l2")]), Seq([yes("w")])
    v, n = support_votes((local, local, wonder), claim(), "ctx")
    assert (v.supports, v.reason, n) == (True, "w", 3)
    assert len(local.prompts) == 2 and len(wonder.prompts) == 1


@pytest.mark.parametrize("votes", [1, 2, 4])
def test_panel_other_vote_counts(votes):
    judges = tuple(Seq([yes("r%d" % i)]) for i in range(1, votes + 1))
    v, n = support_votes(judges, claim(), "ctx", votes=votes)
    assert (v.supports, v.reason, n) == (True, "r%d" % votes, votes)
    assert all(len(j.prompts) == 1 for j in judges)


@pytest.mark.parametrize("size", [0, 1, 2, 4])
def test_panel_wrong_length_raises_before_any_call(size):
    judges = tuple(Seq([yes()]) for _ in range(size))
    with pytest.raises(ValueError, match="a judge panel must hold votes callables"):
        support_votes(judges, claim(), "ctx")
    assert all(j.prompts == [] for j in judges)


@pytest.mark.parametrize("pos", [0, 1, 2])
def test_panel_non_callable_raises_before_any_call(pos):
    judges = [Seq([yes()]), Seq([yes()]), Seq([yes()])]
    judges[pos] = "not a judge"
    with pytest.raises(ValueError, match="a judge panel must hold votes callables"):
        support_votes(tuple(judges), claim(), "ctx")
    assert all(j.prompts == [] for j in judges if isinstance(j, Seq))


def test_panel_none_item_raises():
    with pytest.raises(ValueError, match="a judge panel must hold votes callables"):
        support_votes((Seq([yes()]), None, Seq([yes()])), claim(), "ctx")


def test_list_is_not_a_panel():
    judges = [Seq([yes()]), Seq([yes()]), Seq([yes()])]
    with pytest.raises(ValueError, match="a judge panel must be a tuple"):
        support_votes(judges, claim(), "ctx")
    assert all(j.prompts == [] for j in judges)


def test_bad_votes_checked_before_panel():
    judges = (Seq([yes()]),)
    with pytest.raises(ValueError, match="votes must be an int >= 1"):
        support_votes(judges, claim(), "ctx", votes=0)
    with pytest.raises(ValueError, match="votes must be an int >= 1"):
        support_votes(judges, claim(), "ctx", votes=True)
    assert judges[0].prompts == []


def test_single_judge_unchanged():
    judge = Seq([yes("r1"), yes("r2"), yes("r3")])
    v, n = support_votes(judge, claim(), "ctx")
    assert (v.supports, v.reason, n) == (True, "r3", 3) and len(judge.prompts) == 3


# ---------------------------------------------------------------- 2. check_citation with a panel

def test_check_panel_all_yes_checked():
    a, b, c = Seq([yes("r1")]), Seq([yes("r2")]), Seq([yes("wonder yes")])
    res = run(claim(), (a, b, c))
    assert res.status == "checked" and res.reasons == [] and res.supports is True
    assert (res.judge_calls, res.judge_reason, res.judge_name) == (3, "wonder yes", PANEL_NAME)
    assert a.prompts == b.prompts == c.prompts and len(a.prompts) == 1
    assert "\nSource title: " + TITLE + "\nSource URL: " + URL + "\n" in c.prompts[0]


def test_check_panel_wonder_no_assumed():
    a, b, c = Seq([yes()]), Seq([yes()]), Seq([no("value is for a different unit")])
    res = run(claim(), (a, b, c))
    assert res.status == "assumed"
    assert res.reasons == ["judge says not supported: value is for a different unit"]
    assert (res.supports, res.judge_calls) == (False, 3)


def test_check_panel_local_no_saves_wonder():
    a, b, c = Seq([yes()]), Seq([no("b")]), Seq([yes()])
    res = run(claim(), (a, b, c))
    assert res.status == "assumed" and res.judge_calls == 2 and c.prompts == []


def test_check_panel_wonder_error_assumed():
    a, b, c = Seq([yes()]), Seq([yes()]), Seq([RuntimeError("down")])
    res = run(claim(), (a, b, c))
    assert res.status == "assumed"
    assert res.reasons == ["judge gave no verdict: judge error: RuntimeError"] and res.judge_calls == 3


def test_check_panel_not_called_when_script_fails():
    judges = (Seq([yes()]), Seq([yes()]), Seq([yes()]))
    res = run(claim(value=31), judges)
    assert res.reasons == ["value not in the quoted source text"] and res.judge_calls == 0
    assert all(j.prompts == [] for j in judges)


def test_check_panel_not_called_when_fetch_fails():
    judges = (Seq([yes()]), Seq([yes()]), Seq([yes()]))
    res = run(claim(), judges, table={})
    assert res.status == "assumed" and res.judge_calls == 0
    assert all(j.prompts == [] for j in judges)


def test_check_panel_of_two_raises():
    judges = (Seq([yes()]), Seq([yes()]))
    with pytest.raises(ValueError, match="a judge panel must hold votes callables"):
        run(claim(), judges)


# ---------------------------------------------------------------- 3. constants

def test_constants():
    assert WONDER_MODEL == "muse-wonder-1.0"
    assert WONDER_JUDGE_STAGE == "S3_judge"
    assert WONDER_JUDGE_ESTIMATE_USD == 0.25
    assert isinstance(WONDER_JUDGE_ESTIMATE_USD, float)


def test_wonder_model_has_a_price():
    from autosolar.ledger import PRICES
    assert WONDER_MODEL in PRICES


# ---------------------------------------------------------------- 4. wonder_judge

def test_wonder_judge_one_call_exact_arguments():
    client = FakeClient([yes("w")])
    out = wonder_judge("the prompt", client=client, run_id="rejudge-x")
    assert out == yes("w")
    assert client.calls == [(("rejudge-x", "S3_judge", "the prompt"),
                             {"estimate_usd": 0.25, "model": "muse-wonder-1.0", "store": False})]


def test_wonder_judge_returns_text_unchanged():
    client = FakeClient(["  ```json\n" + yes() + "\n```  "])
    assert wonder_judge("p", client=client, run_id="r") == "  ```json\n" + yes() + "\n```  "


@pytest.mark.parametrize("bad", ["", "   ", "\n\t", None, 5, b"yes"])
def test_wonder_judge_no_text_raises(bad):
    client = FakeClient([bad])
    with pytest.raises(RuntimeError, match="wonder answer has no text"):
        wonder_judge("p", client=client, run_id="r")
    assert len(client.calls) == 1


@pytest.mark.parametrize("exc", [BudgetExceeded("cap"), RuntimeError("HTTP 500"), TimeoutError("slow")])
def test_wonder_judge_does_not_catch(exc):
    client = FakeClient([exc])
    with pytest.raises(type(exc)):
        wonder_judge("p", client=client, run_id="r")


def test_wonder_judge_keywords_only():
    client = FakeClient([yes()])
    with pytest.raises(TypeError):
        wonder_judge("p", client, "r")
    assert client.calls == []


def test_wonder_judge_in_support_verdict_error_is_no_verdict():
    client = FakeClient([RuntimeError("down")])
    judge = functools.partial(wonder_judge, client=client, run_id="r")
    v = support_verdict(judge, claim(), "ctx")
    assert (v.supports, v.reason) == (None, "judge error: RuntimeError")


def test_wonder_judge_gets_the_support_prompt():
    client = FakeClient([yes()])
    judge = functools.partial(wonder_judge, client=client, run_id="r")
    v = support_verdict(judge, claim(), "ctx")
    assert v.supports is True
    assert client.calls[0][0][2] == one_prompt(claim(), "ctx")


# ---------------------------------------------------------------- 5. judge_panel

def test_judge_panel_order():
    local, wonder = Seq([]), Seq([])
    panel = judge_panel(local, wonder)
    assert type(panel) is tuple and len(panel) == JUDGE_VOTES
    assert panel[0] is local and panel[1] is local and panel[2] is wonder


@pytest.mark.parametrize("args", [(None, Seq([])), (Seq([]), None), ("a", "b"), (Seq([]), 3)])
def test_judge_panel_needs_callables(args):
    with pytest.raises(ValueError, match="judges must be callable"):
        judge_panel(*args)


def test_judge_panel_end_to_end_with_wonder():
    local = Seq([yes("l1"), yes("l2")])
    client = FakeClient([yes("wonder agrees")])
    panel = judge_panel(local, functools.partial(wonder_judge, client=client, run_id="rejudge-y"))
    res = run(claim(), panel)
    assert res.status == "checked" and res.judge_calls == 3 and res.judge_reason == "wonder agrees"
    assert len(local.prompts) == 2 and len(client.calls) == 1
    assert client.calls[0][0][:2] == ("rejudge-y", "S3_judge")


def test_judge_panel_end_to_end_local_no_no_api_call():
    local = Seq([no("local says no")])
    client = FakeClient([yes()])
    panel = judge_panel(local, functools.partial(wonder_judge, client=client, run_id="r"))
    res = run(claim(), panel)
    assert res.status == "assumed" and res.judge_calls == 1 and client.calls == []


def test_judge_panel_end_to_end_wonder_empty_assumed():
    local = Seq([yes(), yes()])
    client = FakeClient([""])
    panel = judge_panel(local, functools.partial(wonder_judge, client=client, run_id="r"))
    res = run(claim(), panel)
    assert res.status == "assumed"
    assert res.reasons == ["judge gave no verdict: judge error: RuntimeError"]


# ---------------------------------------------------------------- 6. nothing else changes

def test_source_inputs_signature_unchanged():
    import inspect
    params = list(inspect.signature(sourcing.source_inputs).parameters)
    assert params == ["base_raw", "targets", "client", "run_id", "http_get", "judge_fn", "judge_name",
                      "fx_idr_per_usd"]


def test_glimmer_judge_unchanged():
    import inspect
    params = list(inspect.signature(sourcing.glimmer_judge).parameters)
    assert params == ["prompt", "post", "url", "timeout_s"]
