"""G179 — who is who, end to end: a synthetic Instinct conversation through capture and a fake-engine Sleep.

Real: the synthetic ``chat.db`` (real tables, words partly only in ``attributedBody``), the app's query, the backend's
decode and staging, Sleep's episode loader, Stage 1's real ``extract`` (chunking, the note it gives the model, the
G118 evidence locate) and every stage after it that writes claims. Fake: the model's answer (``litellm.acompletion``),
Stage 3's legacy pass, Stage 4, git and the vector index — the ``test_sleep_cycle_hold`` set.

Asserted: the person's lines are ``user`` evidence and the agent's ``assistant``; the model is told whose lines are
whose before the conversation; a claim drawn only from Instinct's words has observer ``external:instinct`` and
``assistant`` evidence; one drawn from the person's words keeps ``observer: agent`` with ``user`` evidence; the
model can never set an observer itself; and no claim is ``user_stated`` or the owner's."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from _imessage_fixtures import ChatDB, conversation_id, payload, read_rows, utc
from api.config import Settings
from api.models.schemas import MessagesSyncRequest
from api.services import bank_index, entity_extractor, evidence, markdown_parser, messages_source, sleep_cycle
from api.services.claims import parse_claims
from api.tests.test_sleep_cycle_hold import _bank, _patch, _settings

AGENT_SAYS = "I run on beta-tool and alpha-project launches next week."
PERSON_SAYS = "We build alpha-project with gamma-lib."


def _page(memory, slug, name, kind):
    markdown_parser.write(memory / "entities" / f"{slug}.md",
                          {"name": name, "type": kind, "status": "active", "confidence": 0.9},
                          f"## Summary\n{name} is a synthetic {kind}.\n")


def _conversation(tmp_path, memory):
    db = ChatDB(tmp_path / "chat.db")
    chat = db.chat("+15550000001")
    db.message(chat, utc(2026, 9, 3, 10, 0), from_me=True, body_only=True, text=PERSON_SAYS)
    db.message(chat, utc(2026, 9, 3, 10, 1), from_me=False, body_only=True, text=AGENT_SAYS)
    db.message(chat, utc(2026, 9, 3, 10, 2), from_me=True, associated_type=2000, text=f"Loved “{AGENT_SAYS}”")
    guid = db.chat_guid(chat)
    messages_source.update_settings(memory, conversation={"id": conversation_id(guid), "name": "Instinct",
                                                          "ticked": True})
    body = payload(guid, read_rows(db.path, chat), from_me=40, from_them=160)
    messages_source.ingest(memory, MessagesSyncRequest.model_validate(body).model_dump(by_alias=False))
    db.close()
    bank_index.invalidate()


MODEL_ANSWER = {
    "entities": [
        {"name": "Instinct", "type": "tool", "confidence": 0.9, "summary": "An AI agent the person texts."},
        {"name": "alpha-project", "type": "project", "confidence": 0.9, "summary": "A synthetic project."},
        {"name": "beta-tool", "type": "tool", "confidence": 0.9, "summary": "A synthetic tool."},
        {"name": "gamma-lib", "type": "tool", "confidence": 0.9, "summary": "A synthetic library."},
    ],
    "relationships": [
        # Only the agent said it.
        {"source": "Instinct", "target": "beta-tool", "label": "runs on", "evidence_quote": "I run on beta-tool"},
        # Only the agent said it — and the model tries to call it the person's.
        {"source": "alpha-project", "target": "beta-tool", "label": "launches with",
         "evidence_quote": "alpha-project launches next week", "observer": "owner"},
        # The person said it.
        {"source": "alpha-project", "target": "gamma-lib", "label": "built with",
         "evidence_quote": "We build alpha-project with gamma-lib"},
    ],
}


def test_the_agents_words_stay_the_agents_through_sleep(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    for slug, name, kind in (("instinct", "Instinct", "tool"), ("alpha-project", "alpha-project", "project"),
                             ("beta-tool", "beta-tool", "tool"), ("gamma-lib", "gamma-lib", "tool")):
        _page(memory, slug, name, kind)
    _conversation(tmp_path, memory)

    # The episode: the person's line is `user:`, Instinct's `assistant:`, the tapback nowhere.
    (ep_path,) = sorted((memory / "episodes").glob("*.md"))
    episode = markdown_parser.parse(ep_path)
    assert episode.body.split("\n") == [f"user: {PERSON_SAYS}", f"assistant: {AGENT_SAYS}"]
    assert episode.frontmatter["correspondent"]["name"] == "Instinct"
    assert episode.frontmatter["correspondent"]["kind"] == "agent"

    prompts: list[str] = []

    async def fake_acompletion(**kw):
        prompts.append(kw["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(MODEL_ANSWER)))])

    real_extract = entity_extractor.extract
    _patch(monkeypatch, [])

    async def extract_with_fake_engine(episodes, settings, **kw):
        return await real_extract(episodes, Settings(litellm_model="fake-engine", memory_path=memory), **kw)

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr("api.services.entity_extractor.extract", extract_with_fake_engine)

    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="g179_who"))

    # The model was told whose lines are whose, before the conversation.
    (prompt,) = prompts
    note_at = prompt.index(entity_extractor.SOURCE_NOTE_PREFIX)
    assert note_at < prompt.index(f"user: {PERSON_SAYS}")
    assert 'Lines starting "assistant:" are messages from Instinct, an AI agent' in prompt

    claims = {}
    for page in (memory / "entities").glob("*.md"):
        for c in parse_claims(markdown_parser.parse(page).body):
            claims[(c.subject, c.predicate, c.object)] = c
    text = evidence.source_text(memory, episode.frontmatter["id"])

    runs_on = claims[("instinct", "runs-on", "beta-tool")]
    assert runs_on.observer == "external:instinct" and runs_on.source_trust == "agent_extracted"
    (ev,) = runs_on.evidence
    assert ev.kind == "assistant" and text[ev.start:ev.end] == "I run on beta-tool"

    launches = next(c for k, c in claims.items() if k[0] == "alpha-project" and k[2] == "beta-tool")
    assert launches.observer == "external:instinct"            # never the model's "owner"
    assert [e.kind for e in launches.evidence] == ["assistant"]

    built = next(c for k, c in claims.items() if k[0] == "alpha-project" and k[2] == "gamma-lib")
    assert built.observer == "agent" and [e.kind for e in built.evidence] == ["user"]
    assert text[built.evidence[0].start:built.evidence[0].end] == "We build alpha-project with gamma-lib"

    for c in claims.values():
        assert c.source_trust != "user_stated"
        assert c.observer in ("agent", "external:instinct")
    assert markdown_parser.parse(ep_path).frontmatter["processed"] is True


def test_a_claim_backed_by_both_sides_is_not_only_the_agents():
    rel = {"source": "alpha-project", "target": "beta-tool", "label": "uses", "source_episode": "ep_2026-09-03_001"}
    agent_span = {"episode": "ep_2026-09-03_001", "start": 0, "end": 4, "kind": "assistant", "hash": "0" * 12}
    user_span = {"episode": "ep_2026-09-03_001", "start": 10, "end": 14, "kind": "user", "hash": "0" * 12}
    extracted = [{"episode_id": "ep_2026-09-03_001", "origin": "imessage", "relationships": [
        dict(rel, evidence=[agent_span], observer="external:instinct"), dict(rel, evidence=[user_span])]}]
    (claim,) = entity_extractor.entities_to_claims(extracted, None)
    assert claim.observer == "agent" and {e.kind for e in claim.evidence} == {"assistant", "user"}


def test_only_an_external_observer_survives_the_projection():
    rel = {"source": "a", "target": "b", "label": "uses", "source_episode": "ep_2026-09-03_001"}
    for raw, want in (("owner", "agent"), ("rodrigo", "agent"), ("external:instinct", "external:instinct"), ("", "agent")):
        (claim,) = entity_extractor.entities_to_claims(
            [{"episode_id": "ep_2026-09-03_001", "relationships": [dict(rel, observer=raw)]}], None)
        assert claim.observer == want


def test_the_note_names_a_person_as_someone_else():
    note = entity_extractor.correspondent_note({"name": "Alice Example", "kind": "person"})
    assert 'Lines starting "speaker:" are messages from Alice Example, someone else' in note
    assert entity_extractor.correspondent_note(None) is None
    assert entity_extractor.correspondent_observer({"name": "Alice Example"}) == "external:alice-example"
