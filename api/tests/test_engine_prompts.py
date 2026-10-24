"""Engine calls carry Cicada's own system prompt, and the plan account never reaches memory (perf report 2026-10-24).

1. Every `claude -p` call replaces the CLI's default system prompt (`--system-prompt`, never the append form) and
   carries the context guard. The CLI still attaches the signed-in account's email to its context on its own.
2. Stage 1 drops an item carrying the plan account's email unless the conversation itself says it. When the person
   typed their own address, the item is kept and the evidence rail places its span as before.
3. The merge asks only for the Summary and the new History lines. Every other section is carried by code, and its
   output is the page body every caller already takes.
4. Disambiguation and the article writer send short system messages of their own.

Every address here is a placeholder; no test reads the real sign-in (`conftest._no_real_plan_account`).
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.config import Settings
from api.services import (
    agent_engine, conflict_resolver, engine_identity, entity_article, entity_body, entity_extractor, entity_resolver,
    providers,
)
from api.services.connections.base import CliResult

ACCOUNT = "plan.account@example.test"


@pytest.fixture
def plan_account(monkeypatch):
    monkeypatch.setattr(engine_identity, "reader", lambda: frozenset({ACCOUNT}))
    engine_identity.clear()
    yield ACCOUNT
    engine_identity.clear()


def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


# --- 1. the spawn ----------------------------------------------------------------------------------------------------


def _system_arg(argv: list[str]) -> str:
    found = [a for a in argv if a.startswith("--system-prompt=")]
    assert len(found) == 1, argv
    assert not any(a.startswith("--append-system-prompt") for a in argv), "append keeps the CLI's default prompt"
    return found[0].split("=", 1)[1]


@pytest.mark.parametrize("system", ["", "Stage rules."])
def test_build_argv_always_replaces_the_default_system_prompt(system):
    sent = _system_arg(agent_engine.build_argv(model="haiku", system_prompt=system))
    assert sent.startswith(system or agent_engine.DEFAULT_SYSTEM_PROMPT)
    assert sent.endswith(agent_engine.CONTEXT_GUARD)


def _envelope() -> str:
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "{}",
                       "usage": {"input_tokens": 1, "output_tokens": 1}})


@pytest.mark.parametrize("messages, want_json, stage", [
    ([{"role": "user", "content": "judge this"}], True, "disambiguation"),
    ([{"role": "user", "content": "write this"}], True, "merge"),
    ([{"role": "user", "content": "plain"}], False, None),
    ([{"role": "system", "content": "Rules."}, {"role": "user", "content": "data"}], True, "extraction"),
])
def test_every_engine_call_spawns_with_the_override_and_the_guard(messages, want_json, stage):
    seen: list[list[str]] = []

    def runner(argv, **kw):
        seen.append(list(argv))
        return CliResult(0, _envelope(), "")

    agent_engine.complete(messages=messages, model="haiku", stage=stage, want_json=want_json, runner=runner,
                          scope="test-engine-prompts")
    sent = _system_arg(seen[0])
    own = next((m["content"] for m in messages if m["role"] == "system"), agent_engine.DEFAULT_SYSTEM_PROMPT)
    assert sent.startswith(own)
    assert agent_engine.CONTEXT_GUARD in sent
    assert sent.count(agent_engine.CONTEXT_GUARD) == 1


def test_the_system_prompt_is_byte_identical_across_calls_so_the_cache_serves_it():
    seen: list[str] = []

    def runner(argv, **kw):
        seen.append(_system_arg(argv))
        return CliResult(0, _envelope(), "")

    for body in ("first", "second"):
        agent_engine.complete(messages=[{"role": "user", "content": body}], model="haiku", stage="merge",
                              want_json=True, runner=runner, scope="test-engine-prompts")
    assert seen[0] == seen[1]


def test_the_account_is_read_only_on_the_claude_plan(plan_account):
    assert engine_identity.identities(Settings(_env_file=None, llm_mode="byok")) == frozenset()
    assert engine_identity.identities(Settings(_env_file=None, llm_mode="codex")) == frozenset()
    assert engine_identity.identities(Settings(_env_file=None, llm_mode="agent")) == {ACCOUNT}


def test_an_unreadable_sign_in_costs_the_floor_never_the_run(monkeypatch):
    def boom():
        raise RuntimeError("no CLI")

    monkeypatch.setattr(engine_identity, "reader", boom)
    engine_identity.clear()
    assert engine_identity.identities(Settings(_env_file=None, llm_mode="agent")) == frozenset()


# --- 2. Stage 1 ------------------------------------------------------------------------------------------------------

LEAK = {
    "entities": [
        {"name": "Owner Example", "type": "person", "aliases": ["Owner", ACCOUNT],
         "summary": f"Owner Example builds a cedar canoe. Their email address is {ACCOUNT}.",
         "key_facts": ["Builds a cedar-strip canoe", f"Email address: {ACCOUNT}",
                       f"Uses {ACCOUNT.upper()} to sign in"],
         "links": [{"url": f"mailto:{ACCOUNT}"}]},
        {"name": ACCOUNT, "type": "concept"},
        {"name": "Cedar Canoe", "type": "project", "key_facts": ["Cedar strips arrived"]},
    ],
    "relationships": [{"source": "Owner Example", "target": "Cedar Canoe", "label": "builds",
                       "evidence_quote": "rebuilding my canoe"}],
    "values": [{"entity": "Owner Example", "attribute": "email", "value": ACCOUNT,
                "evidence_quote": "used only to identify the user"}],
}


def _run_extract(content: str, reply: dict, *, mode: str = "agent"):
    async def fake(**kw):
        return _resp(json.dumps(reply))

    episode = {"id": "ep_2026-10-20_001", "timestamp": "2026-10-20T10:00:00Z", "origin": "claude-code",
               "content": content}
    with patch.object(providers, "resolve_llm_fn", lambda *a, **k: fake):
        out = asyncio.run(entity_extractor.extract([episode], Settings(_env_file=None, llm_mode=mode)))
    assert len(out) == 1
    return out[0]


def test_stage1_drops_the_plan_account_the_conversation_never_said(plan_account):
    content = ("user: I've been rebuilding my canoe this week, the cedar strips finally arrived.\n"
               "assistant: Nice, how is it going?")
    out = _run_extract(content, json.loads(json.dumps(LEAK)))
    assert ACCOUNT not in json.dumps(out).lower()
    names = [e["name"] for e in out["entities"]]
    assert names == ["Owner Example", "Cedar Canoe"], "the entity named for the account goes whole"
    owner = out["entities"][0]
    assert owner["aliases"] == ["Owner"]
    assert owner["key_facts"] == ["Builds a cedar-strip canoe"]
    assert owner["summary"] == "Owner Example builds a cedar canoe."
    assert owner["links"] == []
    assert out["values"] == []
    assert [r["label"] for r in out["relationships"]] == ["builds"], "what the conversation said stays"


def test_stage1_keeps_the_address_the_person_typed_and_the_evidence_rail_places_it(plan_account):
    content = (f"user: My email is {ACCOUNT}, put it on my page.\n"
               "assistant: Noted.")
    reply = {"entities": [{"name": "Owner Example", "type": "person", "key_facts": [f"Email address: {ACCOUNT}"]}],
             "relationships": [],
             "values": [{"entity": "Owner Example", "attribute": "email", "value": ACCOUNT,
                         "evidence_quote": f"My email is {ACCOUNT}"}]}
    out = _run_extract(content, reply)
    assert out["entities"][0]["key_facts"] == [f"Email address: {ACCOUNT}"]
    [value] = out["values"]
    assert value["value"] == ACCOUNT
    [ev] = value["evidence"]
    start, end = ev.get("start"), ev.get("end")
    assert start is not None and content[start:end] == f"My email is {ACCOUNT}", ev


def test_stage1_drops_a_name_read_out_of_the_address(plan_account):
    """Seen on dev 2026-10-24: the owner page got an alias made of the address's two words before the `@`."""
    content = "user: The cedar strips finally arrived.\nassistant: Nice."
    reply = {"entities": [{"name": "Owner Example", "type": "person", "aliases": ["Plan Account", "Owner"],
                           "key_facts": ["Goes by plan on forums", "Signed in as Plan Account"]}],
             "relationships": []}
    out = _run_extract(content, reply)
    owner = out["entities"][0]
    assert owner["aliases"] == ["Owner"]
    assert owner["key_facts"] == ["Goes by plan on forums"], "one word of the address is no name"


def test_stage1_keeps_the_owner_name_the_prompt_gives_even_when_it_matches_the_address(plan_account, monkeypatch):
    """An owner whose address spells their own name: the extraction prompt names them, so their page is kept."""
    from api.services import owner_identity

    monkeypatch.setattr(owner_identity, "owner_name", lambda *a, **k: "Plan Account")
    content = "user: The cedar strips finally arrived.\nassistant: Nice."
    reply = {"entities": [{"name": "Plan Account", "type": "person", "key_facts": ["Builds a canoe"]}],
             "relationships": []}
    out = _run_extract(content, reply)
    assert [e["name"] for e in out["entities"]] == ["Plan Account"]
    assert out["entities"][0]["key_facts"] == ["Builds a canoe"]


def test_stage1_off_the_claude_plan_is_unchanged(plan_account):
    content = "user: I've been rebuilding my canoe this week.\nassistant: Nice."
    out = _run_extract(content, json.loads(json.dumps(LEAK)), mode="byok")
    assert ACCOUNT in json.dumps(out).lower(), "no CLI context off the plan, so nothing to drop"


def test_scrub_lines_drops_only_what_carries_the_account():
    body = ("## Summary\nA canoe build. Its owner signs in as X@EXAMPLE.TEST here.\n\n"
            "## Key Facts\n- Cedar strips\n- Contact x@example.test")
    out = engine_identity.scrub_lines(body, "nothing", frozenset({"x@example.test"}))
    assert out == "## Summary\nA canoe build.\n\n## Key Facts\n- Cedar strips"
    assert engine_identity.scrub_lines(body, "said x@example.test", frozenset({"x@example.test"})) == body


# --- 3. the merge ----------------------------------------------------------------------------------------------------

PAGE = ("## Summary\nAlpha Co runs a summer programme.\n\n"
        "## Key Facts\n- Offers internships\n- Based in [[Harbour Town]]\n\n"
        "## History\n- 2025-02-04: Owner considered applying\n\n"
        "## Links\n- [Alpha Co](https://alpha.example)\n\n"
        "## Notes by hand\nKeep this.")


def _merge(monkeypatch, reply: str, *, mode: str = "byok"):
    calls: list[dict] = []

    async def fake(**kw):
        calls.append(kw)
        return _resp(reply)

    monkeypatch.setattr(conflict_resolver, "resolve_llm_fn", lambda *a, **k: fake)
    body = asyncio.run(conflict_resolver._synthesize_entity_update(
        entity_name="Alpha Co", entity_type="company", existing_body=PAGE,
        new_description="Alpha Co moved its office to the harbour.",
        new_history_entries=[{"date": "2026-09-30", "event": "Moved office to the harbour"}],
        source_reference_date="2026-09-30", settings=Settings(_env_file=None, litellm_model="gpt-5.4-mini",
                                                              llm_mode=mode),
        page_last_referenced="2025-02-04", source_dates_seen=["2026-09-30"], today="2026-10-07"))
    return body, calls


def test_the_merge_asks_only_for_the_summary_and_new_history(monkeypatch):
    reply = json.dumps({"summary": "Alpha Co runs a summer programme; in September 2026 it moved to the harbour.",
                        "history": ["2026-09-30: Moved its office to the harbour"]})
    body, calls = _merge(monkeypatch, reply)
    [call] = calls
    assert call["response_format"] == {"type": "json_object"}
    system = call["messages"][0]["content"]
    assert call["messages"][0]["role"] == "system" and '"summary"' in system and '"history"' in system
    assert "Output ONLY the updated markdown body" not in system
    sections = entity_body.parse_sections(body)
    assert sections["Summary"].startswith("Alpha Co runs a summer programme; in September 2026")
    assert sections["Key Facts"] == "- Offers internships\n- Based in [[Harbour Town]]", "carried by code, exactly"
    assert sections["Links"] == "- [Alpha Co](https://alpha.example)"
    assert sections["Notes by hand"] == "Keep this."
    assert sections["History"] == ("- 2025-02-04: Owner considered applying\n"
                                   "- 2026-09-30: Moved its office to the harbour")


def test_the_merge_output_feeds_adopt_rewrite_as_before(monkeypatch):
    """apply_changes takes the Summary and new History lines from the body; the composed body gives it the same."""
    reply = json.dumps({"summary": "Alpha Co moved to the harbour in September 2026.",
                        "history": [{"date": "2026-09-30", "event": "Moved office"}]})
    body, _ = _merge(monkeypatch, reply)
    original = entity_body.upgrade_legacy_to_v2(PAGE, "company")
    composed = entity_body.parse_sections(body)
    adopted = entity_body.adopt_rewrite(original, composed)
    assert adopted["Summary"] == composed["Summary"] == "Alpha Co moved to the harbour in September 2026."
    assert adopted["History"] == composed["History"] == ("- 2025-02-04: Owner considered applying\n"
                                                         "- 2026-09-30: Moved office")


def test_an_old_style_markdown_answer_still_reads_as_a_body(monkeypatch):
    body, _ = _merge(monkeypatch, "```markdown\n## Summary\nRewritten.\n```")
    assert body == "## Summary\nRewritten."


def test_an_empty_answer_is_no_rewrite(monkeypatch):
    body, _ = _merge(monkeypatch, json.dumps({"summary": "", "history": []}))
    assert body is None


def test_the_merge_drops_the_plan_account_it_was_never_given(monkeypatch, plan_account):
    reply = json.dumps({"summary": f"Alpha Co runs a summer programme. Contact {ACCOUNT} for it.",
                        "history": [f"2026-09-30: Emailed {ACCOUNT}", "2026-09-30: Moved office"]})
    body, _ = _merge(monkeypatch, reply, mode="agent")
    assert ACCOUNT not in body.lower()
    sections = entity_body.parse_sections(body)
    assert sections["Summary"] == "Alpha Co runs a summer programme."
    assert "2026-09-30: Moved office" in sections["History"]


# --- 4. their own system messages ------------------------------------------------------------------------------------


def test_disambiguation_sends_its_own_system_message(monkeypatch):
    calls: list[list[dict]] = []

    async def fake(**kw):
        calls.append(kw["messages"])
        return _resp(json.dumps({"decision": "different", "reason": "x"}))

    monkeypatch.setattr(entity_resolver.litellm, "acompletion", fake)
    asyncio.run(entity_resolver._llm_judge_same_entity(
        "Sam", "person", "Sam builds canoes.", "Sam Reyes", "person", "Sam Reyes teaches maths.",
        Settings(_env_file=None, litellm_model="gpt-5.4-mini")))
    [messages] = calls
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == entity_resolver._DISAMBIG_SYSTEM


def test_the_article_writer_sends_its_own_system_message():
    messages = entity_article.messages("PROMPT TEXT")
    assert messages == [{"role": "system", "content": entity_article.SYSTEM},
                        {"role": "user", "content": "PROMPT TEXT"}]
