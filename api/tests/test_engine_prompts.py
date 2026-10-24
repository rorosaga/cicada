"""Engine calls carry Cicada's own system prompt, and the plan account never reaches memory (perf report 2026-10-24).

1. Every `claude -p` call replaces the CLI's default system prompt (`--system-prompt`, never the append form) and
   carries the context guard. The CLI still attaches the signed-in account's email to its context on its own.
2. Stage 1 drops an item carrying the plan account's email unless the conversation itself says it. When the person
   typed their own address, the item is kept and the evidence rail places its span as before.
3. The merge asks only for the Summary and the new History lines. Every other section is carried by code, and its
   output is the page body every caller already takes.
4. Disambiguation and the article writer send short system messages of their own.

Review of #468: the sign-in is read off the event loop by every async reader (1b); link recon's batch call carries the
same floor as Stage 1 (2b); a name form counts only as its words said together, the address only whole (2c).

Every address here is a placeholder; no test reads the real sign-in (`conftest._no_real_plan_account`).
"""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from api.config import Settings
from api.services import (
    agent_engine, conflict_resolver, engine_identity, entity_article, entity_body, entity_extractor, entity_orientation,
    entity_resolver, link_recon, page_article_rebuild, providers,
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


# --- 1b. the sign-in is read off the event loop ----------------------------------------------------------------------
#
# A cache miss runs `claude auth status` (up to 10 s). On the event loop it would stall every request in flight, the
# inbox conflict answer among them. The slow fake reader below waits for a concurrent request on the same loop to
# answer, which that request can only do while the loop is free.


def _slow_reader(monkeypatch) -> tuple[threading.Event, dict]:
    answered = threading.Event()
    seen: dict = {}

    def reader():
        seen["loop_was_free"] = answered.wait(timeout=3.0)
        return frozenset({ACCOUNT})

    monkeypatch.setattr(engine_identity, "reader", reader)
    engine_identity.clear()
    return answered, seen


async def _alongside_a_request(work, answered: threading.Event):
    async def request():
        await asyncio.sleep(0.01)
        answered.set()
        return "answered"

    return await asyncio.gather(work, request())


def _plan_settings(**over):
    return Settings(_env_file=None, litellm_model="gpt-5.4-mini", llm_mode="agent", **over)


def _fake_llm(reply: str):
    async def fake(**kw):
        return _resp(reply)

    return lambda *a, **k: fake


def _write_article_path(monkeypatch):
    monkeypatch.setattr(conflict_resolver, "resolve_llm_fn", _fake_llm("{}"))
    monkeypatch.setattr(entity_article, "parse", lambda *a, **k: SimpleNamespace(dropped={}))
    monkeypatch.setattr(entity_article, "payload", lambda *a, **k: {"lead": "Written."})
    job = {"change": {"id": "alpha-co"},
           "article": {"prompt": "PROMPT", "inputs": [], "name": "Alpha Co", "aliases": [], "known": set()}}
    return conflict_resolver._write_article(job, _plan_settings())


def _merge_path(monkeypatch, *, synthesis: bool):
    monkeypatch.setattr(conflict_resolver, "resolve_llm_fn",
                        _fake_llm(json.dumps({"summary": "Alpha Co moved to the harbour.", "history": []})))
    if synthesis:
        monkeypatch.setattr(entity_orientation, "context", lambda *a, **k: {})
        monkeypatch.setattr(entity_orientation, "bounded_prompt", lambda data: "PROMPT")
        monkeypatch.setattr(entity_orientation, "valid_summary", lambda summary: True)
        monkeypatch.setattr(entity_orientation, "restated_facts", lambda *a, **k: [])
        monkeypatch.setattr(entity_orientation, "covered_sentences", lambda *a, **k: [])
        monkeypatch.setattr(entity_orientation, "compose", lambda *a, **k: "## Summary\nAlpha Co moved.")
    return conflict_resolver._synthesize_entity_update(
        entity_name="Alpha Co", entity_type="company", existing_body=PAGE, new_description="Moved to the harbour.",
        new_history_entries=[], source_reference_date="2026-09-30",
        settings=_plan_settings(summary_synthesis_enabled=synthesis), today="2026-10-07")


def _rebuild_path(monkeypatch):
    monkeypatch.setattr(providers, "resolve_llm_fn", _fake_llm("{}"))
    return page_article_rebuild.write(page_article_rebuild.Survey(), _plan_settings(), jobs=[])


def _recon_path(monkeypatch):
    monkeypatch.setattr(providers, "resolve_llm_fn", _fake_llm(json.dumps({"entities": []})))
    return link_recon.default_extract("A saved link about canoes.", _plan_settings())


def _stage1_path(monkeypatch):
    monkeypatch.setattr(providers, "resolve_llm_fn", _fake_llm(json.dumps({"entities": [], "relationships": []})))
    episode = {"id": "ep_2026-10-20_001", "timestamp": "2026-10-20T10:00:00Z", "origin": "claude-code",
               "content": "user: The cedar strips arrived.\nassistant: Nice."}
    return entity_extractor.extract([episode], _plan_settings())


@pytest.mark.parametrize("path", [
    _write_article_path,
    lambda mp: _merge_path(mp, synthesis=False),
    lambda mp: _merge_path(mp, synthesis=True),
    _rebuild_path,
    _recon_path,
    _stage1_path,
], ids=["article", "merge", "orientation", "article-rebuild", "link-recon", "stage1"])
def test_reading_the_sign_in_never_blocks_the_event_loop(monkeypatch, path):
    answered, seen = _slow_reader(monkeypatch)
    _, request = asyncio.run(_alongside_a_request(path(monkeypatch), answered))
    assert request == "answered"
    assert seen.get("loop_was_free") is True, "the sign-in was read on the event loop"


def test_off_the_plan_no_sign_in_is_read_at_all(monkeypatch):
    def reader():
        raise AssertionError("read off the Claude plan")

    monkeypatch.setattr(engine_identity, "reader", reader)
    engine_identity.clear()
    assert asyncio.run(engine_identity.aidentities(Settings(_env_file=None, llm_mode="byok"))) == frozenset()


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


# --- 2b. link recon's batch call -------------------------------------------------------------------------------------


def _recon(text: str, reply: dict):
    with patch.object(providers, "resolve_llm_fn", _fake_llm(json.dumps(reply))):
        return asyncio.run(link_recon.default_extract(text, Settings(_env_file=None, llm_mode="agent")))


RECON_REPLY = {"entities": [
    {"name": ACCOUNT, "type": "concept"},
    {"name": "Plan Account", "type": "person"},
    {"name": "Cedar Canoe", "type": "project", "aliases": ["Canoe", "Plan Account's canoe"],
     "key_facts": ["Cedar strips", f"Shared by {ACCOUNT}"]},
]}


def test_link_recon_drops_the_plan_account_the_links_never_said(plan_account):
    out = _recon("1. Building a cedar canoe: strips, epoxy and patience.", json.loads(json.dumps(RECON_REPLY)))
    assert [e["name"] for e in out] == ["Cedar Canoe"]
    assert out[0]["aliases"] == ["Canoe"]
    assert out[0]["key_facts"] == ["Cedar strips"]


def test_link_recon_keeps_what_the_links_themselves_say(plan_account):
    out = _recon(f"1. Plan Account's cedar canoe build log, by {ACCOUNT}.", json.loads(json.dumps(RECON_REPLY)))
    assert [e["name"] for e in out] == [ACCOUNT, "Plan Account", "Cedar Canoe"]
    assert out[2]["key_facts"] == ["Cedar strips", f"Shared by {ACCOUNT}"]


# --- 2c. how a form is said ------------------------------------------------------------------------------------------

OTHER = frozenset({"anna.may@example.test"})


@pytest.mark.parametrize("item", [
    "Anna and May went to the harbour",
    "May met Anna at the market",
    "Joanna May-Smith",
    "Wrote to joanna.may@example.test",
    "Wrote to anna.mayfield@example.test",
])
def test_the_same_words_apart_or_a_longer_address_are_not_the_identity(item):
    assert not engine_identity.leaks(item, "nothing said", OTHER)


@pytest.mark.parametrize("item", [
    "Anna May", "anna.may", "Signed in as Anna May.", "May, Anna", "ANNA MAY", "Wrote to anna.may@example.test.",
])
def test_the_name_said_together_or_the_whole_address_is_the_identity(item):
    assert engine_identity.leaks(item, "nothing said", OTHER)


def test_words_apart_in_the_input_are_no_evidence_for_the_name():
    assert engine_identity.leaks("Anna May", "user: Anna and May went to the harbour.", OTHER)


@pytest.mark.parametrize("said", ["user: I'm Anna May.", "user: May, Anna (that's me)."])
def test_the_name_the_input_says_is_kept(said):
    """The owner whose address spells their own name, and who said it: the item is theirs to keep."""
    entities = [{"name": "Anna May", "type": "person", "aliases": ["Anna May"], "key_facts": ["Signed in as Anna May"]}]
    assert engine_identity.scrub_extraction(entities, [], [], said, OTHER) == 0
    assert entities[0]["name"] == "Anna May" and entities[0]["aliases"] == ["Anna May"]


def test_the_name_is_dropped_without_evidence_and_words_apart_are_kept():
    entities = [{"name": "Harbour Trip", "type": "event",
                 "key_facts": ["Anna and May went to the harbour", "Booked by Anna May"]},
                {"name": "Anna May", "type": "person"}]
    dropped = engine_identity.scrub_extraction(entities, [], [], "user: Anna and May went to the harbour.", OTHER)
    assert dropped == 2
    assert [e["name"] for e in entities] == ["Harbour Trip"]
    assert entities[0]["key_facts"] == ["Anna and May went to the harbour"]


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
