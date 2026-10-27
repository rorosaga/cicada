"""Facts keep their context (G194, G179, TODO ruling 42; owner 2026-10-27).

Four defects, one synthetic case each and the general rule behind it:

1. A fact loses the thing it is about: a displaced orientation was split into sentences, and "As of <day> he had the
   application form filled in" landed on the owner's page with nothing saying which event (`fact_policy.standalone`).
2. An assistant's explanation became the person's act: a claim resting only on an agent's words is the agent's
   (`external:<agent>`), a harness session's and a chat export's included (`entity_extractor.assistant_observer`), and
   the prompt says who did what.
3. Pages repeat themselves: a fact another one says word for word and then more folds into it when written, without
   losing a word, a date or a source (`fact_policy.extends`, `fold_extensions`).
4. An agent's act in the person's tools has no actor or status: the episode's session rides every claim read from it,
   and (ruling 42) an event or program the person — or an agent, for them — applied to gets its own page from one
   conversation, holding the application (status, who filled it, the step left open); the owner keeps only the link.

Every name here is a placeholder.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import (application_page, conflict_resolver, engine_schemas, entity_body, entity_extractor,
                          entity_resolver, fact_policy, markdown_parser, pending_store, section_provenance)
from api.tests.test_sleep_cycle_hold import _bank, _entity, _settings

OWNER = "Alex Example"
EP = "ep_2026-10-21_004"
TS = "2026-10-21T12:37:37+00:00"
SESSION = "1a2b3c4d-0000-4000-8000-000000000001"


# --- 1. a fact keeps the thing it is about ---------------------------------------------------------------------------

ORIENTATION = (f"{OWNER} is a student in Springfield who builds [[alpha-project]] and is applying as a hacker to "
               "[[Alpha Hackathon]] with a teammate. As of 2026-10-21 he had the application form filled in and was "
               "reviewing it before requesting to join.")


def test_a_sentence_that_leans_on_the_one_before_stays_with_it():
    assert fact_policy.standalone(ORIENTATION, [OWNER]) == [ORIENTATION]


def test_a_sentence_about_the_page_itself_still_stands_alone():
    text = (f"{OWNER} is the owner of this memory and works in a lab. In October 2026 he asked for a walkthrough "
            "of the [[Beta Paper]].")
    assert fact_policy.standalone(text, [OWNER]) == [f"{OWNER} is the owner of this memory and works in a lab.",
                                                     "In October 2026 he asked for a walkthrough of the [[Beta Paper]]."]


@pytest.mark.parametrize("previous, sentence, leans", [
    ("beta-app is built in Swift.", "It was on TestFlight in May 2026.", False),   # "it" is the page: it opens it
    (f"{OWNER} uses [[Gamma Tool]].", "It runs on [[Postgres]].", False),           # the page opened it: unknowable
    ("The stack runs on [[Gamma Tool]].", "It runs on [[Postgres]].", True),        # not about the page: leans
    ("Uses [[Gamma Tool]].", "As of 2026-10-21 he had the form filled in.", True),  # names nothing of its own
    ("Uses [[Gamma Tool]].", "This Friday the [[Delta Meetup]] starts.", False),    # says what it is about
])
def test_what_leans(previous, sentence, leans):
    assert fact_policy.leans(sentence, ["beta-app", OWNER], previous) is leans


def test_the_owner_page_keeps_the_event_name_on_a_displaced_orientation():
    page = {"Summary": f"{OWNER} is the owner of this memory.", "Key Facts": f"- {OWNER} lives in Springfield."}
    merged = entity_body.merge_sections_fallback(page, {"name": OWNER, "summary": ORIENTATION})
    facts = entity_body._bullet_lines(merged["Key Facts"])
    assert ORIENTATION in facts
    assert not any(f.startswith("As of 2026-10-21 he had") for f in facts)


def test_an_overlong_summary_keeps_the_lean_with_the_sentence_it_leans_on():
    lead = f"{OWNER} is a researcher who works on many things across robotics and memory systems. " * 6
    sections = entity_body.bound_summary({"Summary": lead + ORIENTATION}, name=OWNER, entity_type="person")
    facts = entity_body._bullet_lines(sections["Key Facts"])
    assert any("[[Alpha Hackathon]]" in f and "application form" in f for f in facts)


def test_a_held_line_keeps_the_name_when_a_reread_displaces_its_summary():
    prior = pending_store.PendingEntity(name=OWNER, type="person", description="", source_episode=EP,
                                        confidence=0.6, tags=[], history_entries=[], summary=ORIENTATION)
    fresh = pending_store.PendingEntity(name=OWNER, type="person", description="", source_episode=EP,
                                        confidence=0.6, tags=[], history_entries=[], summary=f"{OWNER} is a person.")
    pending_store._carry(prior, fresh)
    assert ORIENTATION in fresh.key_facts


def test_the_same_name_fold_keeps_the_lean_with_its_sentence():
    base = {"name": OWNER, "type": "person", "summary": ORIENTATION, "key_facts": []}
    incoming = {"name": OWNER, "type": "person", "summary": f"{OWNER} is a researcher who builds many things and "
                "writes them up at length, much more than the other summary says, across robotics, memory systems, "
                "agent harnesses, reading tools and a long list of side projects nobody else has heard of.",
                "key_facts": []}
    merged = entity_resolver._merge_entity_payload(base, incoming)
    assert ORIENTATION in merged["key_facts"]


# --- 3. a fact said twice folds, never losing a word ------------------------------------------------------------------

@pytest.mark.parametrize("longer, shorter, folds", [
    ("Rolling admissions with no deadline, earlier applications preferred.", "Rolling admissions", True),
    ("Bob Example is a close friend, based in Springfield.", "Bob Example is a close friend.", True),
    ("In April 2026, Alex wanted to apply, with a friend.", "Alex wanted to apply", True),
    ("Alex wanted to apply, with a friend.", "In April 2026, Alex wanted to apply", False),  # never a date dropped
    # Ruling 23's counterexamples: containment is not a repeat.
    ("Works at Acme's competitor.", "Works at Acme", False),
    ("Uses Postgres or SQLite.", "Uses Postgres", False),
    ("Costs 200,000 euros.", "Costs 200", False),
    ("Lives in Springfield until June.", "Lives in Springfield", False),
])
def test_extends(longer, shorter, folds):
    assert fact_policy.extends(longer, shorter) is folds


def test_the_longer_fact_takes_the_shorter_ones_place_and_a_repeat_is_left_out():
    existing = "- Rolling admissions\n- Three written answers."
    merged = entity_body._merge_facts(existing, ["Rolling admissions with no deadline.", "Three written answers"])
    assert entity_body._bullet_lines(merged) == ["Rolling admissions with no deadline.", "Three written answers."]
    # The other way round: an incoming fact an existing one already says is left out.
    again = entity_body._merge_facts(merged, ["Rolling admissions"])
    assert entity_body._bullet_lines(again) == ["Rolling admissions with no deadline.", "Three written answers."]


def test_a_page_a_person_edited_keeps_every_bullet_exactly():
    merged = entity_body._merge_facts("- Rolling admissions", ["Rolling admissions with no deadline."],
                                      extend_existing=False)
    assert entity_body._bullet_lines(merged) == ["Rolling admissions", "Rolling admissions with no deadline."]
    human = entity_body.merge_sections_fallback({"Summary": "Mine.", "Key Facts": "- Rolling admissions"},
                                                {"key_facts": ["Rolling admissions with no deadline."]},
                                                human_edited=True)
    assert entity_body._bullet_lines(human["Key Facts"])[0] == "Rolling admissions"


def test_a_folded_facts_source_moves_onto_the_fact_that_holds_it():
    from api.services import evidence

    ev_a = evidence.reasoning("ep_2026-10-01_001", hash="a" * 12)
    ev_b = evidence.reasoning("ep_2026-10-02_001", hash="b" * 12)
    original = "## Summary\nA program.\n\n## Key Facts\n- Rolling admissions\n"
    fm: dict = {}
    section_provenance.refresh(fm, "", original, {"_section_inputs": [
        {"field": "key_facts", "text": "Rolling admissions", "evidence": [ev_a.to_dict()]}]})
    body = "## Summary\nA program.\n\n## Key Facts\n- Rolling admissions with no deadline.\n"
    section_provenance.refresh(fm, original, body, {"_section_inputs": [
        {"field": "key_facts", "text": "Rolling admissions with no deadline.", "evidence": [ev_b.to_dict()]}]})
    rows = section_provenance.matched(fm, body)["key_facts"]
    (guard, evs), = rows.values()
    assert {e.episode for e in evs} == {"ep_2026-10-01_001", "ep_2026-10-02_001"}

    selected = section_provenance.merge_selected(
        {"_section_inputs": [{"field": "key_facts", "text": "Rolling admissions", "evidence": [ev_a.to_dict()]}]},
        {"_section_inputs": [{"field": "key_facts", "text": "Rolling admissions with no deadline.",
                              "evidence": [ev_b.to_dict()]}]},
        {"key_facts": ["Rolling admissions with no deadline."]})
    assert {e["episode"] for e in selected[0]["evidence"]} == {"ep_2026-10-01_001", "ep_2026-10-02_001"}


# --- 2 and 4. who said it, who did it, which session --------------------------------------------------------------

HARNESS_EP = {"id": EP, "harness": "claude-code", "capture_kind": "transcript", "session_id": SESSION,
              "origin": "claude-code", "timestamp": TS}


@pytest.mark.parametrize("episode, observer", [
    (HARNESS_EP, "external:claude-code"),
    ({"origin": "chatgpt-export"}, "external:chatgpt"),
    ({"correspondent": {"name": "Helper Bot", "kind": "agent"}, "origin": "imessage"}, "external:helper-bot"),
    ({"origin": "claude-ai", "evidence_kind": "assistant"}, None),    # relayed: its own rail
    ({"origin": "bookmark"}, None),
])
def test_whose_words_the_assistant_lines_are(episode, observer):
    assert entity_extractor.assistant_observer(episode) == observer


def test_only_a_harness_transcript_gets_the_agent_note():
    note = entity_extractor.agent_session_note(HARNESS_EP)
    assert note and "Claude Code" in note and "never the person's" in note
    assert entity_extractor.agent_session_note({**HARNESS_EP, "capture_kind": None}) is None
    assert entity_extractor.agent_session_note({"origin": "chatgpt-export"}) is None


def test_every_claim_read_from_a_session_carries_it():
    extraction = {"episode_id": EP, "origin": "claude-code", "session_id": SESSION,
                  "relationships": [{"source": OWNER, "target": "Alpha Hackathon", "label": "applying to",
                                     "source_episode": EP, "source_episode_timestamp": TS}],
                  "values": [{"entity": "Alpha Hackathon", "attribute": "application status", "value": "filled",
                              "source_episode": EP, "source_episode_timestamp": TS}]}
    claims = entity_extractor.entities_to_claims([extraction], None)
    assert [c.session_ids for c in claims] == [[SESSION], [SESSION]]


def test_the_prompt_says_who_did_it_and_that_a_fact_stands_alone():
    prompt = entity_extractor.EXTRACTION_SYSTEM_PROMPT
    assert "WHO DID IT" in prompt and "A stated plan stays a plan" in prompt
    assert "Every fact stands alone" in prompt and "APPLICATION (optional" in prompt
    assert "When the user acted on an assistant's suggestion, write\n  what they did" not in prompt
    for strict in (True, False):
        props = engine_schemas.extraction_schema(strict=strict)["properties"]["entities"]["items"]["properties"]
        assert "application" in props


# --- 4. ruling 42: the application lives on the event's own page -------------------------------------------------------

TRANSCRIPT = ("user: I want to apply to Alpha Hackathon as a participant. Fill in the form with my details and let "
              "me know so we can request to join.\n"
              "assistant: The Alpha Hackathon form is filled in with the participant ticket selected. I haven't "
              "clicked Request to Join yet, so look it over and send it when you're happy.\n")


def _event(**extra) -> dict:
    return {"name": "Alpha Hackathon", "type": "project", **extra}


def test_an_agent_filled_form_is_the_agents_act_with_its_session():
    birth = application_page.at_extraction(_event(application={"status": "filled", "by": "assistant"}),
                                           episode_id=EP, frontmatter=HARNESS_EP, text=TRANSCRIPT, day="2026-10-21")
    assert birth["status"] == "filled" and birth["by"] == "Claude Code" and birth["session"] == SESSION
    assert birth["span"]["kind"] == "assistant"
    assert TRANSCRIPT[birth["span"]["start"]:birth["span"]["end"]] == "Alpha Hackathon"


def test_the_persons_own_words_are_enough():
    birth = application_page.at_extraction(_event(application={"status": "sent"}), episode_id=EP,
                                           frontmatter={"origin": "chatgpt-export"}, text=TRANSCRIPT, day=None)
    assert birth["by"] == "user" and birth["span"]["kind"] == "user" and "session" not in birth


@pytest.mark.parametrize("entity, frontmatter, text", [
    (_event(), HARNESS_EP, TRANSCRIPT),                                                     # the model did not mark it
    ({**_event(application={"status": "sent"}), "type": "person"}, HARNESS_EP, TRANSCRIPT),  # never a person
    (_event(application={"status": "sent"}), {"origin": "bookmark"},
     "Alpha Hackathon - a hackathon page saved for later"),                                  # a bookmark: no act
    (_event(application={"status": "sent"}), {"origin": "imessage"},
     "user: is this link any good?\nassistant: Your link is Alpha Hackathon. Register soon if you haven't.\n"),
    (_event(application={"status": "wishful"}), HARNESS_EP, TRANSCRIPT),                     # not a status
])
def test_a_bookmark_a_mention_or_an_explanation_never_qualifies(entity, frontmatter, text):
    assert application_page.at_extraction(entity, episode_id=EP, frontmatter=frontmatter, text=text,
                                          day="2026-10-21") is None


def test_a_texted_agents_claim_of_an_act_does_not_make_it_the_agents_act():
    """Only a harness agent acts in the person's tools; a texted agent's "I filled it in" is the person's words or
    nothing — here the person's own turn holds the act word, so the person is recorded."""
    text = "user: I applied to Alpha Hackathon.\nassistant: I filled in the Alpha Hackathon form for you.\n"
    birth = application_page.at_extraction(_event(application={"status": "sent", "by": "assistant"}), episode_id=EP,
                                           frontmatter={"correspondent": {"name": "Helper Bot", "kind": "agent"}},
                                           text=text, day="2026-10-21")
    assert birth["by"] == "user"


def _answer() -> dict:
    return {"entities": [
        {"name": OWNER, "type": "person", "summary": ORIENTATION.replace("[[Alpha Hackathon]]", "[[Alpha Hackathon]]"),
         "key_facts": [f"{OWNER} applies to [[Alpha Hackathon]] as a participant.", f"{OWNER} lives in Springfield."],
         "history_entries": [{"date": "2026-10-21", "event": "Asked the agent to fill in the Alpha Hackathon form."}]},
        {"name": "Alpha Hackathon", "type": "project", "summary": "Alpha Hackathon is a hackathon.",
         "key_facts": ["Runs from 3 to 6 December."], "application": {"status": "filled", "by": "assistant"}},
    ], "relationships": [
        {"source": OWNER, "target": "Alpha Hackathon", "label": "applying to",
         "evidence_quote": "I want to apply to Alpha Hackathon as a participant."},
        {"source": "Alpha Hackathon", "target": "participant ticket", "label": "has ticket",
         "evidence_quote": "The Alpha Hackathon form is filled in with the participant ticket selected."},
    ], "values": []}


def _extract(tmp_path, monkeypatch, answer):
    memory = _bank(tmp_path)
    markdown_parser.write(memory / "entities" / "alex-example.md",
                          {"name": OWNER, "type": "person", "owner": True}, f"## Summary\n{OWNER} owns this memory.")

    async def fake_acompletion(**kw):
        fake_acompletion.messages = kw["messages"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake_acompletion)
    from api.services import owner_identity

    monkeypatch.setattr(owner_identity, "owner_name", lambda *_a, **_k: OWNER)
    episode ={**HARNESS_EP, "content": TRANSCRIPT, "source": "claude-code"}
    out = asyncio.run(entity_extractor.extract([episode], Settings(litellm_model="fake-engine", memory_path=memory)))
    return memory, out[0], fake_acompletion.messages


def test_stage_one_moves_the_application_off_the_owner_and_records_who_did_it(tmp_path, monkeypatch):
    memory, result, messages = _extract(tmp_path, monkeypatch, _answer())
    assert "a Claude Code session" in messages[1]["content"]
    assert "THE OWNER OF THIS MEMORY" in messages[0]["content"]
    owner, event = result["entities"]
    assert "application" not in event and "application" not in owner
    assert event[application_page.KEY]["by"] == "Claude Code"
    # The owner keeps no application fact: only what is about them, and the relationship (the link).
    assert owner["key_facts"] == [f"{OWNER} lives in Springfield."]
    assert "Alpha Hackathon" not in owner["summary"] and owner["history_entries"] == []
    # The event holds it all: who filled it, in which session, the step left open, the owner's lines.
    facts = event["key_facts"]
    assert facts[0] == (f"As of 2026-10-21, Claude Code (session {SESSION[:8]}) had filled in {OWNER}'s application "
                        f"to [[Alpha Hackathon]]; sending it was left to {OWNER}.")
    assert f"{OWNER} applies to [[Alpha Hackathon]] as a participant." in facts
    assert any("application form filled in" in f for f in facts)
    assert event["open_questions"] == [f"Has {OWNER} sent the [[Alpha Hackathon]] application?"]
    assert event["history_entries"][0]["event"].startswith("Asked the agent")
    # The status is a value claim the agent reported, in its session; a later status replaces it.
    claims = {c.predicate: c for c in entity_extractor.entities_to_claims([result], None)}
    status = next(c for p, c in claims.items() if "application-status" in p)
    assert (status.object, status.observer, status.session_ids) == ("filled", "external:claude-code", [SESSION])
    # The person's own words stay the agent's reading of them; the agent's own line is the agent's.
    assert claims["applying-to"].observer == "agent"
    assert claims["has-ticket"].observer == "external:claude-code"


def test_stage_two_gives_the_event_its_page_from_one_conversation(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    event = _entity("Alpha Hackathon", "project", EP, TS)   # one plain mention, typed project by the model
    event[application_page.KEY] = {"episode": EP, "day": "2026-10-21", "status": "filled", "by": "Claude Code",
                                   "span": {"start": 0, "end": 5, "hash": "x", "kind": "assistant"}}
    out = asyncio.run(entity_resolver.resolve([{"episode_id": EP, "entities": [event], "relationships": []}], [],
                                              _settings(memory)))
    (change,) = [c for c in out["changes"] if c["action"] == "create"]
    assert (change["id"], change["entity"]["type"]) == ("alpha-hackathon", "concept")   # D4: never a project
    conflict_resolver.apply_changes([change], memory)
    assert (memory / "entities" / "alpha-hackathon.md").exists()


def test_a_plain_one_conversation_mention_still_waits(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    event = _entity("Alpha Hackathon", "concept", EP, TS)
    out = asyncio.run(entity_resolver.resolve([{"episode_id": EP, "entities": [event], "relationships": []}], [],
                                              _settings(memory)))
    assert not [c for c in out["changes"] if c["action"] == "create"]
