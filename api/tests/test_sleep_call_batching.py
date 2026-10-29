"""Sleep asks one call where it used to ask several (2026-10-20): Stage 2's judge weighs up to `JUDGE_BATCH` of a
name's candidates at once, Stage 3's contradiction check up to `CONTRADICTION_BATCH` pages at once. Each candidate
and each page is still judged on its own inputs, cut as the one-at-a-time prompt cut them, and answered in its own
numbered result; an answer that leaves one out reads as the one-at-a-time path read an unreadable answer. A lone
candidate or page keeps the old prompt byte for byte. Synthetic data only, no model.
"""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import conflict_resolver as cr
from api.services import engine_errors, providers
from api.services import entity_resolver as er


def _answer(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _fake_llm(monkeypatch, module, answer, prompts):
    def resolve(*args, **kwargs):
        async def complete(**call):
            prompts.append(call["messages"])
            if isinstance(answer, BaseException):
                raise answer
            return _answer(answer(call["messages"]) if callable(answer) else answer)
        return complete
    monkeypatch.setattr(module, "resolve_llm_fn", resolve)


SETTINGS = SimpleNamespace(litellm_model="synthetic-model", litellm_disambiguation_model="")


def _entries():
    return [{"name": "Alpha Notes", "type": "tool", "body": "## Summary\nA notes tool.", "alias": False},
            {"name": "Alpha Engine", "type": "project", "body": "## Summary\nA game engine.", "alias": False},
            {"name": "Alpha Sync", "type": "tool", "body": "x" * 5000, "alias": True}]


def test_one_judge_call_numbers_each_entry_and_cuts_it_as_the_pair_prompt(monkeypatch):
    prompts: list = []
    answer = json.dumps({"decisions": [{"entry": 2, "decision": "same"}, {"entry": 1, "decision": "different"}]})
    _fake_llm(monkeypatch, providers, answer, prompts)
    out = asyncio.run(er._llm_judge_batch("Alpha", "tool", "y" * 3000, _entries(), SETTINGS,
                                          new_connections="- feeds Lumen Queue"))
    # The project entry is a type mismatch: `different` without asking; the two tools are entries 1 and 2.
    assert out == ["different", "different", "same"]
    assert len(prompts) == 1
    prompt = prompts[0][-1]["content"]   # after the judge's own system message
    assert "[1] Name: Alpha Notes" in prompt and "[2] Name: Alpha Sync" in prompt and "Alpha Engine" not in prompt
    assert "x" * 2000 in prompt and "x" * 2001 not in prompt          # each body cut at 2,000, as one pair
    assert "y" * 1500 in prompt and "y" * 1501 not in prompt          # the new description at 1,500
    assert prompt.count('already lists "Alpha"') == 1                  # the alias note on the alias entry only
    assert "- feeds Lumen Queue" in prompt


def test_an_entry_the_answer_leaves_out_is_unsure_and_an_engine_error_propagates(monkeypatch):
    prompts: list = []
    tools = [e for e in _entries() if e["type"] == "tool"]
    _fake_llm(monkeypatch, providers, json.dumps({"decisions": [{"entry": 1, "decision": "same"},
                                                                {"entry": 2, "decision": "maybe"}]}), prompts)
    assert asyncio.run(er._llm_judge_batch("Alpha", "tool", "", tools, SETTINGS)) == ["same", "unsure"]
    _fake_llm(monkeypatch, providers, json.dumps({"decisions": [{"entry": 1, "decision": "same"}]}), prompts)
    assert asyncio.run(er._llm_judge_batch("Alpha", "tool", "", tools, SETTINGS)) == ["unsure", "unsure"]
    _fake_llm(monkeypatch, providers, "not json at all", prompts)
    assert asyncio.run(er._llm_judge_batch("Alpha", "tool", "", tools, SETTINGS)) == ["unsure", "unsure"]
    _fake_llm(monkeypatch, providers, engine_errors.EngineThrottled("plan limit"), prompts)
    with pytest.raises(engine_errors.EngineThrottled):
        asyncio.run(er._llm_judge_batch("Alpha", "tool", "", tools, SETTINGS))


def test_a_lone_candidate_keeps_the_one_pair_prompt(monkeypatch):
    seen: list = []

    async def pair(*args, **kwargs):
        seen.append(kwargs["existing_name"])
        return "different"

    async def batch(*args, **kwargs):
        raise AssertionError("a lone candidate is never batched")

    monkeypatch.setattr(er, "_llm_judge_same_entity", pair)
    monkeypatch.setattr(er, "_llm_judge_batch", batch)
    page = {"id": "alpha-notes", "frontmatter": {"name": "Alpha Notes", "type": "tool"}, "body": "A notes tool."}
    judged = asyncio.run(er._judge_candidates({"name": "Alpha", "type": "tool"},
                                              [{"source": "existing", "id": "alpha-notes", "data": page}], {},
                                              SETTINGS))
    assert seen == ["Alpha Notes"] and judged[0][1] == "different"


def test_the_schemas_take_both_answer_shapes():
    from api.services import agent_engine, engine_schemas

    claude = agent_engine.SCHEMA_BY_STAGE["disambiguation"]
    assert claude["properties"]["decision"]["enum"] == ["same", "different", "unsure", "related"]
    assert claude["properties"]["decisions"]["items"]["required"] == ["entry", "decision"]
    strict = engine_schemas.disambiguation_schema(strict=True)
    assert set(strict["required"]) == {"decision", "relation", "reason", "decisions"}
    assert None in strict["properties"]["decision"]["enum"]


# --- Stage 3 ---------------------------------------------------------------------------------------------------

def _item(name, body, new, said="2026-09-01", days=("2026-10-18",)):
    return dict(entity_name=name, existing_body=body, new_description=new, existing_as_of=said, new_as_of=list(days))


def test_one_contradiction_call_checks_each_page_in_its_own_block(monkeypatch):
    prompts: list = []
    answer = json.dumps({"results": [
        {"entity": 2, "has_unresolvable_contradiction": True, "question": "Which?", "options": []},
        {"entity": 3, "has_unresolvable_contradiction": False},
        {"entity": 1, "has_unresolvable_contradiction": False}]})
    _fake_llm(monkeypatch, cr, answer, prompts)
    settings = SimpleNamespace(effective_consolidation_model="synthetic-model")
    out = asyncio.run(cr._detect_contradictions(
        [_item("Alpha", "## Summary\nAlpha is red.\n```claims\n[]\n```", "z" * 3000),
         _item("Beta", "w" * 6000, "Beta is blue."), _item("Gamma", "Gamma.", "Gamma.")], settings, today="2026-10-20"))
    assert out[0]["has_unresolvable_contradiction"] is False and out[1]["question"] == "Which?"
    assert out[2]["has_unresolvable_contradiction"] is False
    system, user = prompts[0][0]["content"], prompts[0][1]["content"]
    assert system == cr._CONTRADICTIONS_RULES and user.startswith("TODAY: 2026-10-20")
    assert "ENTITY 1: Alpha" in user and "ENTITY 3: Gamma" in user
    assert "```claims" not in user                                        # claims stripped, as one page
    assert "z" * 2000 in user and "z" * 2001 not in user and "w" * 4000 in user and "w" * 4001 not in user
    assert "(last mentioned in a conversation dated 2026-09-01)" in user
    # Every line of the one-page definition is still said, in its order.
    definition = [line for line in cr._CONTRADICTION_RULES.split("\n\nRespond")[0].splitlines()[1:] if line]
    positions = [system.index(line) for line in definition]
    assert positions == sorted(positions)


def _bank(tmp_path, n):
    from api.services import markdown_parser
    root = tmp_path / "bank"
    for name in ("entities", "episodes", "inbox"):
        (root / name).mkdir(parents=True)
    existing = []
    for i in range(n):
        fm = {"name": f"Page {i}", "type": "concept", "status": "active", "confidence": 0.7, "created": "2026-09-01",
              "last_referenced": "2026-09-01", "source_episodes": ["ep_2026-09-01_001"]}
        body = f"## Summary\nPage {i} is the old state {i}.\n"
        markdown_parser.write(root / "entities" / f"page-{i}.md", fm, body)
        existing.append({"id": f"page-{i}", "frontmatter": fm, "body": body})
    return root, existing


def _updates(n):
    return [{"id": f"page-{i}", "action": "update", "source_episode": "ep_2026-10-18_001",
             "source_episodes": ["ep_2026-10-18_001"], "source_episode_timestamp": "2026-10-18T09:00:00Z",
             "entity": {"name": f"Page {i}", "type": "concept",
                        "summary": f"Page {i} is the new state {i}." + (" CONFLICT" if i in (1, 6) else "")}}
            for i in range(n)]


def test_stage_three_checks_seven_pages_in_two_calls_and_files_each_result_on_its_page(tmp_path, monkeypatch):
    root, existing = _bank(tmp_path, 7)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    calls: list = []

    async def synth(**kw):
        return None

    async def engine(**kwargs):
        system, user = kwargs["messages"][0]["content"], kwargs["messages"][-1]["content"]
        calls.append(user)
        blocks = user.split("ENTITY ")[1:]
        return _answer(json.dumps({"results": [
            {"entity": k, "has_unresolvable_contradiction": "CONFLICT" in b, "question": f"Q {b.split(':')[1].splitlines()[0].strip()}?"}
            for k, b in enumerate(blocks, start=1)]}))

    monkeypatch.setattr(cr, "_synthesize_entity_update", synth)
    monkeypatch.setattr(cr.litellm, "acompletion", engine)
    settings = Settings(_env_file=None, agent_max_concurrency=3, summary_synthesis_enabled=True)
    changes = asyncio.run(cr.resolve_and_prune(_updates(7), existing, settings, now=datetime(2026, 10, 20, 3),
                                               decay=False, tuning={}))
    assert len(calls) == 2 and [c.count("ENTITY ") for c in calls] == [5, 2]
    nudges = [c for c in changes if c["action"] == "conflict_nudge"]
    assert [n["id"] for n in nudges] == ["page-1", "page-6"]
    assert nudges[0]["question"] == "Q Page 1?" and nudges[1]["question"] == "Q Page 6?"


def test_the_judge_reads_what_the_extraction_said_about_the_name(monkeypatch):
    """Stage 1 fills `summary`; `description` is a legacy field it almost never fills. The judge used to read B's
    `description` alone, so nearly every call saw "(empty)" and a bare first name was `unsure` against its own page."""
    seen: list = []

    async def pair(**kwargs):
        seen.append(kwargs["new_description"])
        return "same"

    monkeypatch.setattr(er, "_llm_judge_same_entity", pair)
    page = {"id": "carol-example", "frontmatter": {"name": "Carol Example", "type": "person"},
            "body": "Carol Example is a backend engineer."}
    asyncio.run(er._judge_candidates({"name": "Carol", "type": "person", "summary": "Carol writes the migration."},
                                     [{"source": "existing", "id": "carol-example", "data": page}], {}, SETTINGS))
    assert seen == ["Carol writes the migration."]
    created = {"source": "created", "id": "carol-x", "data": {"entity": {"name": "Carol X", "summary": "A colleague."}}}
    assert er._candidate_description(created) == "A colleague."



# --- a batch answer is read only when it lines up (review of #389) ----------------------------------------------

def _rows(key, numbers, words):
    return [({key: n} if n is not None else {}) | words[i] for i, n in enumerate(numbers)]


UNALIGNED = {
    "0-based": [0, 1, 2],
    "duplicate": [1, 1, 3],
    "gap": [1, 2, 4],
    "out of range": [2, 3, 4],
    "mixed numbered and unnumbered": [1, None, 3],
    "short list": [1, 2],
    "long list": [1, 2, 3, 4],
    "short list without numbers": [None, None],
    "not a whole number": [1, "two", 3],
}


@pytest.mark.parametrize("case", sorted(UNALIGNED))
def test_a_judge_answer_that_does_not_line_up_is_unsure_for_every_candidate(case):
    numbers = UNALIGNED[case]
    words = [{"decision": "different"}, {"decision": "same"}, {"decision": "different"}, {"decision": "same"}]
    parsed = {"decisions": _rows("entry", numbers, words)}
    assert er._batch_decisions(parsed, 3) == ["unsure", "unsure", "unsure"]


@pytest.mark.parametrize("case", sorted(UNALIGNED))
def test_a_contradiction_answer_that_does_not_line_up_files_no_question(case):
    numbers = UNALIGNED[case]
    words = [{"has_unresolvable_contradiction": i == 1, "question": f"Q{i}?"} for i in range(4)]
    parsed = {"results": _rows("entity", numbers, words)}
    assert cr._contradiction_results(parsed, 3) == [None, None, None]


def test_an_answer_that_lines_up_is_read_by_its_numbers_or_by_position_when_none_is_numbered():
    by_number = {"decisions": [{"entry": "3", "decision": "same"}, {"entry": 1, "decision": "different"},
                               {"entry": 2, "decision": "unsure"}]}
    assert er._batch_decisions(by_number, 3) == ["different", "unsure", "same"]
    by_position = {"decisions": [{"decision": "different"}, {"decision": "same"}, {"decision": "different"}]}
    assert er._batch_decisions(by_position, 3) == ["different", "same", "different"]
    results = {"results": [{"entity": 2, "question": "B?"}, {"entity": 1, "question": "A?"}]}
    assert [r["question"] for r in cr._contradiction_results(results, 2)] == ["A?", "B?"]
    assert [r["question"] for r in cr._contradiction_results({"results": [{"question": "A?"}, {"question": "B?"}]}, 2)] \
        == ["A?", "B?"]
