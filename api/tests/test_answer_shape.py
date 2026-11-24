"""A call's label never picks the answer shape an engine forces (2026-11-24).

`stage` picks the model tier, the plan guard and the metering. The same-name judge shared Stage 2's "disambiguation"
label for its small tier, and on a plan the engine forced the pair judge's `decision` / `decisions` shape on it: the real
answer (`people` / `pairs`, a verdict) came back as `{"decision": "same", "reason": "<the answer as a string>"}`, which
the step could not read. Now only a call that STATES a shape (`resolve_llm_fn(..., shape=...)`) is told one, and an
answer that does not fit what was asked for is counted, never taken as a verdict. Every name here is invented.
"""
from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest

from api.config import Settings
from api.services import (agent_engine, codex_engine, engine_schemas, entity_resolver, providers,
                          same_name_people as snp, same_name_review as snr)
from api.services.connections.base import CliResult

SERVICES = Path(__file__).resolve().parents[1] / "services"

#: Every call that states a shape, and the module that owns the parser of it. A new one is a decision made here.
STATES_A_SHAPE = {("entity_resolver.py", "pair"): 2, ("entity_extractor.py", "<stage>"): 1}


def _calls() -> list[tuple[str, int, dict]]:
    """Every ``resolve_llm_fn(...)`` call in the services: ``(file, line, {keyword: source of its value})``."""
    found = []
    for path in sorted(SERVICES.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name == "resolve_llm_fn":
                    found.append((path.name, node.lineno, {k.arg: ast.unparse(k.value) for k in node.keywords if k.arg}))
    return found


def test_the_call_sites_were_found():
    calls = _calls()
    assert len(calls) > 20 and any(c[2].get("stage") == "'disambiguation'" or c[2].get("stage") == '"disambiguation"' for c in calls)


def test_only_a_call_that_states_a_shape_is_forced_one_on_either_plan():
    """The table: for every call site, the schema the Claude plan and the ChatGPT plan would force on it is none unless
    it states a shape its own module parses; a site that states one is on the list above."""
    stating: dict[tuple[str, str], int] = {}
    for file, line, kw in _calls():
        shape = kw.get("shape")
        if shape is None:
            continue
        key = (file, "<stage>" if shape == "stage if stage in engine_schemas.SHAPES else None" else shape.strip("'\""))
        stating[key] = stating.get(key, 0) + 1
    assert stating == STATES_A_SHAPE


def test_neither_plan_has_a_table_keyed_by_a_label_any_more():
    policy = agent_engine.CallPolicy(extraction_schema=True)   # the flag on: the most the Claude plan ever forces
    assert agent_engine.schema_for_shape(None, policy) is None and agent_engine.schema_for_shape("", policy) is None
    assert set(agent_engine.SCHEMA_BY_SHAPE) <= set(engine_schemas.SHAPES)
    assert set(codex_engine.SCHEMA_BY_SHAPE) <= set(engine_schemas.SHAPES)
    for module in (agent_engine, codex_engine):
        assert not hasattr(module, "SCHEMA_BY_STAGE")
    assert not hasattr(agent_engine, "schema_for_stage")


def test_an_unknown_shape_fails_where_it_is_written():
    with pytest.raises(ValueError):
        providers.resolve_llm_fn(Settings(llm_mode="agent"), stage="disambiguation", shape="peeple")
    with pytest.raises(ValueError):
        agent_engine.complete(messages=[{"role": "user", "content": "x"}], model="haiku", shape="peeple",
                              want_json=True, runner=lambda *a, **k: CliResult(0, "{}", ""))


# ---- through the seam, on both plans ----------------------------------------------------------------------------------

MSGS = [{"role": "system", "content": "S"}, {"role": "user", "content": "B"}]


def _schema_in(argv: list[str]):
    return json.loads(argv[argv.index("--json-schema") + 1]) if "--json-schema" in argv else None


def test_the_claude_plan_forces_the_pair_shape_only_on_a_call_that_states_it(agent_runner, agent_envelopes):
    s = Settings(llm_mode="agent", agent_model="sonnet", agent_disambiguation_model="haiku")
    runner = agent_runner(agent_envelopes["structured"])
    plain = providers.resolve_llm_fn(s, stage="disambiguation", sink=lambda e: None, runner=runner, is_async=False)
    plain(messages=MSGS, response_format={"type": "json_object"})
    pair = providers.resolve_llm_fn(s, stage="disambiguation", shape="pair", sink=lambda e: None, runner=runner,
                                    is_async=False)
    pair(messages=MSGS, response_format={"type": "json_object"})
    first, second = runner.calls[0]["argv"], runner.calls[1]["argv"]
    assert _schema_in(first) is None and agent_engine.JSON_ONLY_SUFFIX in next(a for a in first if a.startswith("--system-prompt="))
    assert _schema_in(second)["properties"]["decision"]["enum"] == ["same", "different", "unsure", "related"]
    # the label still picks the small model on both
    assert first[first.index("--model") + 1] == second[second.index("--model") + 1] == "haiku"


def test_the_chatgpt_plan_forces_the_pair_shape_only_on_a_call_that_states_it(agent_runner, codex_events):
    seen = []

    def runner(argv, **kw):
        seen.append("--output-schema" in argv)
        return CliResult(0, codex_events["ok"], "")

    s = Settings(llm_mode="codex", codex_model="gpt-5.6-luna", codex_disambiguation_model="gpt-5.5")
    for shape in (None, "pair"):
        fn = providers.resolve_llm_fn(s, stage="disambiguation", shape=shape, sink=lambda e: None, runner=runner,
                                      is_async=False)
        fn(messages=MSGS, response_format={"type": "json_object"})
    assert seen == [False, True]


def _answer_envelope(agent_envelopes, text: str) -> dict:
    return {**agent_envelopes["success"], "result": text}


def test_the_same_name_judge_on_a_plan_is_told_no_shape_and_its_own_answer_reads(agent_runner, agent_envelopes):
    """The product's own call (`entity_resolver._same_name_ask`) on a plan: no schema is sent, the small tier is, and the
    `people` answer comes back as it was given, which `same_name_people.read` accepts."""
    answer = {"people": [{"conversations": ["A"], "reason": "r"}, {"conversations": ["B"], "reason": "r"}],
              "pairs": [{"people": [1, 2], "verdict": "different", "here": "a carpenter in a small town",
                         "there": "a colleague on the research team", "reason": "r"}]}
    runner = agent_runner(_answer_envelope(agent_envelopes, json.dumps(answer)))
    settings = Settings(llm_mode="agent", agent_model="sonnet", agent_disambiguation_model="haiku")
    orig = providers.resolve_llm_fn
    try:
        providers.resolve_llm_fn = lambda *a, **k: orig(*a, **{**k, "runner": runner, "sink": lambda e: None})
        got = asyncio.run(entity_resolver._same_name_ask(settings, "SYSTEM", "PROMPT"))
    finally:
        providers.resolve_llm_fn = orig
    argv = runner.calls[0]["argv"]
    assert _schema_in(argv) is None and argv[argv.index("--model") + 1] == "haiku"
    assert got == answer
    entries = [snp.Entry("A", "(2026-10-01) a carpenter in a small town who builds furniture", None, ("e1",)),
               snp.Entry("B", "(2026-10-02) a colleague on the research team at the firm", None, ("e2",))]
    assert snp.read(got, entries, "Marc") is not None


# ---- an answer in the wrong shape is counted, never a verdict -------------------------------------------------------------

WRONG = {"decision": "same", "reason": '{"people": [{"conversations": ["A", "B"], "reason": "r"}], "pairs": []}'}
M = [snp.Mention("e1", "(2026-10-01) a carpenter in a small mountain town who builds furniture and helps with shelves"),
     snp.Mention("e2", "(2026-10-02) a colleague on the research team at the firm who moves to another office next spring")]


def _judge(answer):
    async def judge(system, prompt):
        return answer
    return judge


def test_a_wrong_shaped_grouping_is_counted_and_moves_nothing():
    plan = asyncio.run(snp.plan("Marc", M, [], _judge(WRONG), _judge(WRONG)))
    assert plan.called and plan.moves == {} and plan.unreadable == 1   # the small judge only: nothing was ever "single"


def test_a_right_shaped_grouping_counts_nothing():
    right = {"people": [{"conversations": ["A", "B"], "reason": "r"}], "pairs": []}
    assert asyncio.run(snp.plan("Marc", M, [], _judge(right))).unreadable == 0


def test_a_failed_judge_is_not_an_unreadable_answer():
    async def judge(system, prompt):
        raise RuntimeError("boom")
    assert asyncio.run(snp.plan("Marc", M, [], judge)).unreadable == 0


def test_a_second_reading_in_the_wrong_shape_is_counted_and_the_first_stands():
    right = {"people": [{"conversations": ["A", "B"], "reason": "r"}], "pairs": []}
    plan = asyncio.run(snp.plan("Marc", M, [], _judge(right), _judge(WRONG)))
    assert plan.second and plan.unreadable == 1 and plan.moves == {}


def test_a_page_read_in_the_wrong_shape_is_unreadable_not_one_person():
    page = snr.Page("marc", tuple(snp.Item(t, (f"e{n}",)) for n, t in enumerate(
        ["(2026-10-01) a carpenter in a small mountain town", "(2026-10-02) a colleague on the research team"])))
    split = asyncio.run(snr.holds_two("Marc", page, _judge(WRONG)))
    assert split.called and split.unreadable and not split.episodes
    ok = {"people": [{"conversations": ["A", "B"], "reason": "r"}], "pairs": []}
    assert not asyncio.run(snr.holds_two("Marc", page, _judge(ok))).unreadable


@pytest.mark.parametrize("answer,unreadable", [
    ({"decision": "unsure", "reason": '{"verdict": "same"}'}, True),   # the pair judge's shape: the forced one
    ({"verdict": "maybe"}, True), ("text", True), ({}, True),
    ({"verdict": "cannot_tell"}, False),
    ({"verdict": "different", "here": "a made-up quote", "there": "another"}, False),   # a verdict with no located facts is a read
    (None, False),
])
def test_a_pair_answer_is_unreadable_only_when_it_has_no_verdict_of_its_shape(answer, unreadable):
    one = snr.Page("marc", (snp.Item("(2026-09-06) Marc is a cousin who plays the cello", ("a",)),))
    two = snr.Page("marc-2", (snp.Item("(2026-10-20) Marc is a neighbour with a small brown dog", ("b",)),))
    assert asyncio.run(snr.settle_pair("Marc", one, two, _judge(answer))).unreadable is unreadable
