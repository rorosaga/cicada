"""Is a public handle a named person? A web lookup may say (PROPOSED ruling 54, owner direction 2026-11-04).

The owner, on "is <handle> the same as <a developer's full name>?": "could've been resolved from a search, like how
claude code would solve it if i ask it rn." Synthetic banks only (bex42, Bea Example, Dana Rivers the owner, Cal Example); the
search tool is a fake; nothing reaches a network or a paid API."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from api.services import (bank_index, inbox_context, markdown_parser, pair_evidence, public_handle, web_lookup,
                          web_settle)
from api.services.claims import parse_claims
from api.services.clarification_manager import ClarificationManager

PROFILE = "https://github.com/bex42"
QUOTE = "Bea Example bex42 · Software engineer. Writes about agents."


def _page(memory: Path, eid: str, name: str, body: str, **fm) -> None:
    meta = {"name": name, "type": "person", "status": "active", "confidence": 0.7, "created": "2026-10-21",
            "last_referenced": "2026-10-21", "source_episodes": [], "related": [], "version": 1}
    meta.update(fm)
    markdown_parser.write(memory / "entities" / f"{eid}.md", meta, body)


def _episode(memory: Path, eid: str, body: str, source: str, **fm) -> None:
    meta = {"id": eid, "timestamp": f"{eid[3:13]}T09:00:00+00:00", "processed": True, "title": "item",
            "source": source}
    meta.update(fm)
    markdown_parser.write(memory / "episodes" / f"{eid}.md", meta, body)


def _question(memory: Path, item_id: str = "inbox-401", a: str = "bex42", b: str = "bea-example", **fm) -> Path:
    base = {"kind": "merge_suggestion", "required_input": "merge", "status": "pending", "priority": 0.6,
            "entity_id": a, "entity_name": a, "title": f"Is {a} the same as Bea Example?",
            "uncertainty_type": "Possible duplicate of Bea Example", "merge_target_hint": b,
            "suggested_classification": "person — could refer to the same person as Bea Example",
            "suggested_confidence": 0.6, "created_date": "2026-10-23", "source_episode": "ep_2026-10-21_001"}
    base.update(fm)
    path = memory / "inbox" / f"{item_id}.md"
    markdown_parser.write(path, base, "Bea Example already lists “bex42” among the other names it goes by.")
    bank_index.invalidate(memory)
    return path


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_ALLOW_CONNECTOR_FETCH", "on")
    monkeypatch.setenv("CICADA_PUBLIC_HANDLE_LOOKUP", "on")   # off by default until the owner rules (ruling 54)
    m = tmp_path / "memory"
    for sub in ("entities", "episodes", "inbox"):
        (m / sub).mkdir(parents=True)
    _page(m, "dana-rivers", "Dana Rivers", "## Summary\nThe owner.\n", owner=True)
    _page(m, "bex42", "bex42", "## Summary\nbex42 is a handle whose way of working with agents Dana Rivers found "
          "interesting.\n", source_episodes=["ep_2026-10-21_001"])
    _page(m, "bea-example", "Bea Example", "## Summary\nBea Example is a software engineer who gave a talk on agents.\n",
          aliases=["bex42"], source_episodes=["ep_2026-10-21_002"])
    _episode(m, "ep_2026-10-21_001", "user: saved https://x.com/bex42/status/123 — bex42 on statecharts", "bookmark")
    _episode(m, "ep_2026-10-21_002", "attachment [video]: Bea Example on agent workflows", "video-watch")
    # The owner shared a post BY the handle with a friend: the post, not the person (only inside a link).
    _episode(m, "ep_2026-10-21_003", "user: https://x.com/bex42/status/123\nuser: lol", "telegram-chats",
             title="Telegram with Cal Example")
    _question(m)
    bank_index.invalidate(m)
    return m


def _facts(memory):
    return web_settle.bank_facts(memory)


def _fm(memory, item_id="inbox-401"):
    return markdown_parser.parse(memory / "inbox" / f"{item_id}.md").frontmatter


# --------------------------------------------------------------------------- the test (engine-free)


def test_a_public_handle_and_a_public_name_may_be_looked_up_with_two_pinned_queries(bank):
    pair = public_handle.test(bank, _fm(bank), _facts(bank))
    assert pair.public and (pair.handle_id, pair.named_id, pair.site) == ("bex42", "bea-example", "x")
    assert web_settle.classify(bank, _fm(bank), "", _facts(bank)) == ("public", "public_handle")
    c = web_settle.candidate(bank, bank / "inbox" / "inbox-401.md", _facts(bank))
    assert web_settle.queries_for(c) == ("bex42 twitter", "Bea Example")   # all that is searched, each alone


@pytest.mark.parametrize("change, reason", [
    # a chat that says the handle in its words (not only in a link): someone from the person's life
    (lambda m: _episode(m, "ep_2026-10-22_001", "user: bex42 is coming tonight", "whatsapp"), "chat"),
    # a chat with them, by its title
    (lambda m: _episode(m, "ep_2026-10-22_002", "user: hi", "imessage", title="Messages with Bea Example"), "chat"),
    # the address book
    (lambda m: _page(m, "bea-example", "Bea Example", "## Summary\nA software engineer, a talk.\n",
                     sources=[{"ref": "addressbook://card-1", "predicate": "phone"}]), "contacts"),
    # an acquaintance on the record
    (lambda m: _page(m, "bea-example", "Bea Example", "## Summary\nDana Rivers met Bea Example at a talk.\n"),
     "owner_in_prose"),
    # nothing public the person read names the person
    (lambda m: _episode(m, "ep_2026-10-21_002", "user: Bea Example, a talk on agents", "claude-code"),
     "no_public_content"),
])
def test_anything_private_keeps_it_for_the_person(bank, change, reason):
    change(bank)
    bank_index.invalidate(bank)
    assert public_handle.test(bank, _fm(bank), _facts(bank)).reason == reason
    assert web_settle.classify(bank, _fm(bank), "", _facts(bank)) == (None, "person")


@pytest.mark.parametrize("value", [None, "off", "maybe"])
def test_sleeps_own_lookup_is_off_until_the_owner_rules(bank, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CICADA_PUBLIC_HANDLE_LOOKUP", raising=False)
    else:
        monkeypatch.setenv("CICADA_PUBLIC_HANDLE_LOOKUP", value)
    assert public_handle.test(bank, _fm(bank), _facts(bank)).reason == "off"
    assert web_settle.classify(bank, _fm(bank), "", _facts(bank)) == (None, "person")

    def fn(**_kw):
        raise AssertionError("no call while it is off")
    report = asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True,
                                             llm_fn=fn, engine=("resolved", "claude-cli", "plan")))
    assert report.settled == 0 and (bank / "inbox" / "inbox-401.md").exists()


def test_the_persons_own_agent_may_still_settle_it_while_sleeps_lookup_is_off(bank, monkeypatch):
    monkeypatch.delenv("CICADA_PUBLIC_HANDLE_LOOKUP", raising=False)
    c = web_settle.candidate(bank, bank / "inbox" / "inbox-401.md", _facts(bank), agent=True)
    assert c is not None and c.handle is not None and web_settle.queries_for(c) == ("bex42 twitter", "Bea Example")
    done = public_handle.settle(bank, "inbox-401", ref=PROFILE, quote=QUOTE, checker="claude-code",
                                checker_kind="agent", origin="mcp")
    assert done.entity_id == "bea-example" and not (bank / "inbox" / "inbox-401.md").exists()
    with pytest.raises(web_settle.NotSettleable):   # Sleep's own settle stays refused while it is off
        _question(bank, "inbox-406")
        public_handle.settle(bank, "inbox-406", ref=PROFILE, quote=QUOTE, checker="haiku", checker_kind="sleep")


def test_only_a_handle_against_a_full_name_and_never_the_owner_or_a_held_mention(bank):
    _question(bank, "inbox-402", b="dana-rivers")
    _question(bank, "inbox-403", held_mention=True)
    _page(bank, "cal-example", "Cal Example", "## Summary\nA software engineer, a talk.\n")
    _question(bank, "inbox-404", a="cal-example", b="bea-example")
    facts = _facts(bank)
    assert public_handle.test(bank, _fm(bank, "inbox-402"), facts).reason == "owner"
    assert web_settle.classify(bank, _fm(bank, "inbox-402"), "", facts)[0] is None
    assert public_handle.test(bank, _fm(bank, "inbox-403"), facts).reason == "held_mention"
    assert public_handle.test(bank, _fm(bank, "inbox-404"), facts).reason == "no_handle"


# --------------------------------------------------------------------------- the lookup and its settle


def _fake(answer: dict, searched=("bex42 twitter", "Bea Example"), seen=None):
    def fn(*, messages, web_search=False, timeout=None, **kw):
        assert web_search is True and messages[0]["content"] == web_lookup.HANDLE_SYSTEM_PROMPT
        if seen is not None:
            seen.append(messages)
        return {"choices": [{"message": {"content": json.dumps(answer)}}], "model": "fake-model",
                "tool_uses": [["WebSearch", {"query": q}] for q in searched]}
    return fn


def test_a_profile_stating_the_handle_settles_it_with_a_cited_claim_and_undo_takes_it_back(bank):
    seen: list = []
    answer = {"sure": True, "relation": "same", "url": PROFILE, "quote": QUOTE}
    report = asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True,
                                             llm_fn=_fake(answer, seen=seen), engine=("resolved", "claude-cli", "plan")))
    assert report.settled == 1 and not (bank / "inbox" / "inbox-401.md").exists()
    prompt = seen[0][1]["content"]
    assert "Cal Example" not in prompt and "Dana Rivers" not in prompt   # nobody else's name rides along
    claims = parse_claims(markdown_parser.parse(bank / "entities" / "bea-example.md").body)
    assert [(c.subject, c.predicate, c.object, c.observer, c.source_trust, c.origin) for c in claims] == [
        ("bea-example", "goes-by", "bex42", "agent", "external", "web-check")]
    assert claims[0].evidence[0].kind == "page"
    assert {p.stem for p in (bank / "entities").glob("*.md")} >= {"bex42", "bea-example"}   # never a merge
    rec = markdown_parser.parse(bank / "inbox" / "settled" / "inbox-401.md").frontmatter["settled"]
    assert (rec["relation"], rec["handle"], rec["ref"]) == ("goes_by", "bex42", PROFILE)
    # While the claim stands, the pair is not asked again.
    assert ClarificationManager(bank).create(
        "bex42", "ep_2026-10-21_001", "Possible duplicate of Bea Example",
        "person — could refer to the same person as Bea Example", 0.6, "x") is None
    target, _paths, _lines = web_settle.undo(bank, "inbox-401")
    assert target == "inbox-401" and _fm(bank).get("web_check") == "undone"
    assert parse_claims(markdown_parser.parse(bank / "entities" / "bea-example.md").body) == []
    assert web_settle.classify(bank, _fm(bank), "", _facts(bank)) == (None, "undone")


@pytest.mark.parametrize("answer, searched, reason", [
    ({"sure": True, "relation": "same", "url": PROFILE, "quote": "bex42 · Software engineer."},
     ("bex42 twitter",), "quote_unstated"),                 # the quote must name both, checked here
    ({"sure": True, "relation": "different", "url": PROFILE, "quote": QUOTE}, ("Bea Example",), "not_same"),
    ({"sure": True, "relation": "same", "url": PROFILE, "quote": QUOTE}, ("bex42 Bea Example",), "query_strayed"),
    ({"sure": False}, ("Bea Example",), "unsure"),
])
def test_anything_short_of_a_stated_link_settles_nothing(bank, answer, searched, reason):
    report = asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True,
                                             llm_fn=_fake(answer, searched), engine=("resolved", "claude-cli", "plan")))
    assert report.settled == 0 and report.skipped == {reason: 1}
    assert (bank / "inbox" / "inbox-401.md").exists()


def test_a_metered_key_is_never_spent_on_a_handle(bank):
    def fn(**_kw):
        raise AssertionError("no call")
    report = asyncio.run(web_lookup.run_tail(bank, SimpleNamespace(web_check_per_run=8), user_triggered=True,
                                             llm_fn=fn, engine=("resolved", "litellm", "metered")))
    assert report.settled == 0 and report.skipped == {"metered_only": 1}


def test_the_pair_writer_refuses_a_handle_question(bank):
    with pytest.raises(web_settle.NotSettleable):
        web_settle.settle_pair(bank, "inbox-401", ref=PROFILE, quote=QUOTE, relation="different", checker="agent",
                               checker_kind="agent")


# --------------------------------------------------------------------------- the card's evidence


def test_a_person_questions_card_shows_a_conversation_that_names_both(bank):
    _episode(bank, "ep_2026-10-24_001", "user: hola, nos vemos mañana", "telegram-chats")
    _question(bank, "inbox-405", source_episode="ep_2026-10-24_001")
    ctx = inbox_context.InboxContext(bank, today="2026-11-04")
    cause = ctx.cause_for(_fm(bank, "inbox-405"), [])
    assert cause.episode_id == "ep_2026-10-21_001"      # the item's own named neither; a page's own names both
    assert pair_evidence.names_in(["bex42"], cause.excerpt)
