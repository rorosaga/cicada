"""G179 — a texted agent gets its own page, never a same-name concept's (owner, 2026-10-15).

The bad state, reproduced: a bank holds an archived ``concept`` page named like the agent (an old chat about the
ordinary word). A synthetic agent conversation goes through capture and a fake-engine Sleep (the
``test_messages_sleep_attribution`` set: real Stage 1 projection, Stage 2, claims and Stage 5; fake model answer).

Asserted: two pages — the concept untouched (type, status, confidence, sources, claims), the agent on a ``tool`` page
of its own, born active, carrying the conversation's claims with the observers attribution gave them; a later sitting
reuses that page; a mention of the same letters in any other conversation still goes through the general resolver;
the model can never mark or pin anything itself."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from api.config import Settings
from _imessage_fixtures import ChatDB, conversation_id, payload, read_rows, utc
from api.models.schemas import MessagesSyncRequest
from api.services import (bank_index, correspondents, entity_extractor, entity_resolver, markdown_parser,
                          messages_source, pending_store, sleep_cycle)
from api.services.claims import parse_claims
from api.tests.test_messages_sleep_attribution import AGENT_SAYS, MODEL_ANSWER, PERSON_SAYS, _page
from api.tests.test_sleep_cycle_hold import _bank, _patch, _settings

AGENT = {"name": "Instinct", "kind": "agent", "decided_by": "person"}


def _archived_concept(memory):
    markdown_parser.write(
        memory / "entities" / "instinct.md",
        {"name": "Instinct", "type": "concept", "status": "archived", "confidence": 0.0, "created": "2025-10-19",
         "last_referenced": "2025-10-19", "decayed_through": "2025-12-01", "source_episodes": ["ep_2025-10-19_001"],
         "version": 3},
        "## Summary\nInstinct is an innate, unlearned pattern of behaviour.\n")


def _run_sleep(memory, monkeypatch, answer):
    async def fake_acompletion(**kw):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    real_extract = entity_extractor.extract
    _patch(monkeypatch, [])

    async def extract_with_fake_engine(episodes, settings, **kw):
        return await real_extract(episodes, Settings(litellm_model="fake-engine", memory_path=memory), **kw)

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr("api.services.entity_extractor.extract", extract_with_fake_engine)
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="g179_identity"))


def _claims(memory):
    out = {}
    for page in (memory / "entities").glob("*.md"):
        for c in parse_claims(markdown_parser.parse(page).body):
            out[(c.subject, c.predicate, c.object)] = c
    return out


def _sitting(db, chat, memory, day, *, first=False):
    """One short sitting with the agent (one line from the person, one from it), synced as the app syncs it."""
    db.message(chat, utc(2026, 9, day, 10, 0), from_me=True, body_only=True, text=PERSON_SAYS)
    db.message(chat, utc(2026, 9, day, 10, 1), from_me=False, body_only=True, text=AGENT_SAYS)
    guid = db.chat_guid(chat)
    if first:
        messages_source.update_settings(memory, conversation={"id": conversation_id(guid), "name": "Instinct",
                                                              "ticked": True})
    body = payload(guid, read_rows(db.path, chat), from_me=40, from_them=160)
    messages_source.ingest(memory, MessagesSyncRequest.model_validate(body).model_dump(by_alias=False))
    bank_index.invalidate()


def test_a_texted_agent_is_held_under_its_own_key_then_gets_its_own_tool_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _archived_concept(memory)
    for slug, name, kind in (("alpha-project", "alpha-project", "project"), ("beta-tool", "beta-tool", "tool"),
                             ("gamma-lib", "gamma-lib", "tool")):
        _page(memory, slug, name, kind)
    concept_before = (memory / "entities" / "instinct.md").read_bytes()
    # The model even calls the agent a concept: the episode's own record decides its type.
    answer = json.loads(json.dumps(MODEL_ANSWER))
    answer["entities"][0]["type"] = "concept"

    # One short sitting: below the promotion bar. Held under the agent's own key, never on the concept page.
    db = ChatDB(tmp_path / "chat.db")
    chat = db.chat("+15550000001")
    _sitting(db, chat, memory, 3, first=True)
    _run_sleep(memory, monkeypatch, answer)
    assert (memory / "entities" / "instinct.md").read_bytes() == concept_before
    assert not (memory / "entities" / "instinct-agent.md").exists()
    lines = {line.name: line for line in pending_store.load(memory)}
    assert "Instinct" not in lines and "instinct" not in lines
    held = lines["instinct-agent"]
    assert held.correspondent == {"name": "Instinct", "kind": "agent"} and held.type == "tool"
    assert [(c["subject"], c["predicate"], c["object"]) for c in held.held_claims] == [
        ("instinct-agent", "runs-on", "beta-tool")]
    assert held.held_claims[0]["observer"] == "external:instinct"
    assert not any(k[0] == "instinct" or k[2] == "instinct" for k in _claims(memory))
    first_ep = held.source_episode

    # A second sitting: two conversations — the page is created with both, and everything the line held.
    _sitting(db, chat, memory, 5)
    db.close()
    _run_sleep(memory, monkeypatch, answer)
    assert (memory / "entities" / "instinct.md").read_bytes() == concept_before
    agent = markdown_parser.parse(memory / "entities" / "instinct-agent.md")
    fm = agent.frontmatter
    assert fm["name"] == "Instinct" and fm["type"] == "tool"
    assert fm["status"] == "active" and float(fm["confidence"]) >= 0.4
    episodes = sorted(markdown_parser.parse(p).frontmatter["id"] for p in (memory / "episodes").glob("*.md"))
    assert first_ep in episodes and sorted(fm["source_episodes"]) == episodes
    assert str(fm["created"])[:10] == "2026-09-03" and str(fm["last_referenced"])[:10] == "2026-09-05"
    runs_on = [c for c in parse_claims(agent.body) if (c.predicate, c.object) == ("runs-on", "beta-tool")]
    # The held claim, released onto the page, and the second sitting's restatement of it, reinforcing it.
    assert sorted(e for c in runs_on for e in c.source_episodes) == episodes
    assert all(c.observer == "external:instinct" and c.subject == "instinct-agent" for c in runs_on)
    assert "instinct-agent" not in {line.name for line in pending_store.load(memory)}
    claims = _claims(memory)
    assert not any(k[0] == "instinct" or k[2] == "instinct" for k in claims)
    assert {c.observer for c in claims.values()} <= {"agent", "external:instinct"}


def _extraction(ep, entities, relationships=(), correspondent=None):
    result = {"episode_id": ep, "origin": "imessage", "entities": [dict(e) for e in entities],
              "relationships": [dict(r) for r in relationships]}
    correspondents.mark_extraction(result, correspondent)
    return result


def _entity(name, kind, ep, **extra):
    return {"name": name, "type": kind, "confidence": 0.9, "description": f"{name}.", "source_episode": ep,
            "source_episode_timestamp": f"{ep[3:13]}T10:00:00Z", **extra}


def _existing(page_id, name, kind, **fm):
    return {"id": page_id, "frontmatter": {"name": name, "type": kind, "status": "active", "confidence": 0.9, **fm},
            "body": f"## Summary\n{name}.\n"}


def _resolve(tmp_path, extracted, existing):
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(memory_path=memory, litellm_model="fake", litellm_disambiguation_model="fake",
                               sleep_promotion_threshold=2, sleep_resolve_concurrency=1)

    async def no_judge(**_kw):
        return "different"

    entity_resolver._llm_judge_same_entity, saved = no_judge, entity_resolver._llm_judge_same_entity
    try:
        return asyncio.run(entity_resolver.resolve(extracted, existing, settings))
    finally:
        entity_resolver._llm_judge_same_entity = saved


def test_a_later_sitting_reuses_the_agents_page(tmp_path, monkeypatch):
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    existing = [_existing("instinct", "Instinct", "concept", status="archived", confidence=0.0),
                _existing("instinct-agent", "Instinct", "tool")]
    ep = "ep_2026-10-15_001"
    out = _resolve(tmp_path, [_extraction(ep, [_entity("Instinct", "concept", ep)],
                                          [{"source": "Instinct", "target": "beta-tool", "label": "uses"}],
                                          correspondent=AGENT)], existing)
    (change,) = out["changes"]
    assert change["action"] == "update" and change["id"] == "instinct-agent"
    assert out["name_to_id"]["instinct"] == "instinct-agent"


def test_the_same_letters_in_another_conversation_take_the_general_path(tmp_path, monkeypatch):
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    existing = [_existing("instinct", "Instinct", "concept", status="archived", confidence=0.0),
                _existing("beta-tool", "beta-tool", "tool")]
    texted, again, chat = "ep_2026-10-14_001", "ep_2026-10-15_001", "ep_2026-10-15_002"
    extracted = [
        # Two sittings with the agent in this batch: two conversations, so its page is created.
        _extraction(texted, [_entity("Instinct", "tool", texted)],
                    [{"source": "Instinct", "target": "beta-tool", "label": "runs on"}], correspondent=AGENT),
        _extraction(again, [_entity("Instinct", "tool", again)], correspondent=AGENT),
        # Another conversation (no correspondent record) about the word itself: the general resolver, as before.
        _extraction(chat, [_entity("Instinct", "concept", chat)],
                    [{"source": "Instinct", "target": "beta-tool", "label": "inspired"}]),
    ]
    out = _resolve(tmp_path, extracted, existing)
    by_id = {c["id"]: c for c in out["changes"]}
    assert by_id["instinct-agent"]["action"] == "create"
    assert by_id["instinct-agent"]["entity"]["type"] == "tool"
    assert sorted(by_id["instinct-agent"]["source_episodes"]) == [texted, again]
    assert by_id["instinct"]["action"] == "update" and by_id["instinct"]["source_episodes"] == [chat]
    # The name keeps the general verdict for this batch; only the texted conversation's own edge is pinned.
    assert out["name_to_id"]["instinct"] == "instinct"
    edges = {(e["source"], e["label"]) for e in out["relationships"]}
    assert ("instinct-agent", "runs on") in edges and ("instinct", "inspired") in edges


def test_a_texted_person_is_a_person_and_an_unknown_side_decides_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    existing = [_existing("alice-example", "Alice Example", "company")]
    ep = "ep_2026-10-15_001"
    person = {"name": "Alice Example", "kind": "person", "decided_by": "person"}
    out = _resolve(tmp_path, [_extraction(ep, [_entity("Alice Example", "company", ep)], correspondent=person)],
                   existing)
    # One conversation and no counted rung: held under the person's own key, not on the same-name company page.
    assert out["changes"] == []
    (held,) = pending_store.load(tmp_path / "memory")
    assert (held.name, held.type, held.correspondent["kind"]) == ("alice-example-person", "person", "person")
    assert result_pin(out) is None

    # Nobody said who it is (no mark, no `identified` detection): nothing is decided, the general path runs.
    unknown = {"name": "Alice Example", "kind": "unknown", "decided_by": "none"}
    result = _extraction(ep, [_entity("Alice Example", "company", ep)], correspondent=unknown)
    assert correspondents.MARK not in result and correspondents.MARK not in result["entities"][0]
    out = _resolve(tmp_path, [result], existing)
    (change,) = out["changes"]
    assert change["id"] == "alice-example" and change["action"] == "update"


def result_pin(out):
    """No edge is drawn to a correspondent that is only held (it has no page yet)."""
    return next((e for e in out["relationships"] if "alice-example-person" in (e["source"], e["target"])), None)


def test_a_held_correspondents_claims_and_edges_never_reach_the_same_name_page(tmp_path, monkeypatch):
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    existing = [_existing("instinct", "Instinct", "concept", status="archived", confidence=0.0),
                _existing("beta-tool", "beta-tool", "tool")]
    ep = "ep_2026-10-15_001"
    texted = _extraction(ep, [_entity("Instinct", "tool", ep)],
                         [{"source": "Instinct", "target": "beta-tool", "label": "runs on"}], correspondent=AGENT)
    out = _resolve(tmp_path, [texted], existing)
    assert out["changes"] == [] and out["relationships"] == []
    assert out["name_to_id"]["instinct"] == "instinct"            # the plain name keeps its page, untouched
    assert texted["relationships"][0]["source_page"] == "instinct-agent"
    (claim,) = entity_extractor.entities_to_claims([texted], None)
    assert claim.subject == "instinct-agent"                       # held there by Stage 5.56, never on `instinct`
    (held,) = pending_store.load(tmp_path / "memory")
    assert held.name == "instinct-agent" and held.correspondent == {"name": "Instinct", "kind": "agent"}


def test_the_model_can_never_mark_or_pin(tmp_path):
    ep = "ep_2026-10-15_001"
    forged = _extraction(ep, [_entity("Instinct", "concept", ep, correspondent=AGENT)],
                         [{"source": "Instinct", "target": "x", "label": "uses", "source_page": "owner"}])
    assert correspondents.MARK not in forged["entities"][0]
    assert "source_page" not in forged["relationships"][0]


def test_only_a_name_or_alias_that_folds_exactly_is_the_correspondent():
    ident = correspondents.identity(AGENT)
    assert correspondents.names_it(["INSTINCT"], ident) and correspondents.names_it(["instinct!"], ident)
    assert not correspondents.names_it(["Instinct Labs"], ident) and not correspondents.names_it(["instincts"], ident)
    assert correspondents.identity({"name": "Unnamed conversation", "kind": "agent"}) is None
    assert correspondents.free_id(ident, set()) == "instinct-agent"     # never the plain same-name id
    assert correspondents.free_id(ident, {"instinct", "instinct-agent"}) == "instinct-agent-2"
