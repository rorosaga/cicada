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
from api.services import correspondents, entity_extractor, entity_resolver, markdown_parser, sleep_cycle
from api.services.claims import parse_claims
from api.tests.test_messages_sleep_attribution import MODEL_ANSWER, _conversation, _page
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


def test_a_texted_agent_gets_its_own_tool_page_beside_a_same_name_concept(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _archived_concept(memory)
    for slug, name, kind in (("alpha-project", "alpha-project", "project"), ("beta-tool", "beta-tool", "tool"),
                             ("gamma-lib", "gamma-lib", "tool")):
        _page(memory, slug, name, kind)
    concept_before = (memory / "entities" / "instinct.md").read_bytes()
    _conversation(tmp_path, memory)

    # The model even calls the agent a concept: the episode's own record decides its type.
    answer = json.loads(json.dumps(MODEL_ANSWER))
    answer["entities"][0]["type"] = "concept"
    _run_sleep(memory, monkeypatch, answer)

    # The concept page is exactly as it was: nothing of the agent's landed on it.
    assert (memory / "entities" / "instinct.md").read_bytes() == concept_before

    agent = markdown_parser.parse(memory / "entities" / "instinct-agent.md")
    fm = agent.frontmatter
    assert fm["name"] == "Instinct" and fm["type"] == "tool"
    assert fm["status"] == "active" and float(fm["confidence"]) >= 0.4
    (episode,) = sorted((memory / "episodes").glob("*.md"))
    ep_id = markdown_parser.parse(episode).frontmatter["id"]
    assert fm["source_episodes"] == [ep_id]
    assert str(fm["last_referenced"])[:10] == "2026-09-03"   # when it was said, not when it was read

    claims = _claims(memory)
    runs_on = claims[("instinct-agent", "runs-on", "beta-tool")]
    assert runs_on.observer == "external:instinct"            # attribution unchanged by the new page
    assert [e.kind for e in runs_on.evidence] == ["assistant"]
    assert not any(k[0] == "instinct" or k[2] == "instinct" for k in claims)
    built = next(c for k, c in claims.items() if k[0] == "alpha-project" and k[2] == "gamma-lib")
    assert built.observer == "agent"
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
    texted, chat = "ep_2026-10-15_001", "ep_2026-10-15_002"
    extracted = [
        _extraction(texted, [_entity("Instinct", "tool", texted)],
                    [{"source": "Instinct", "target": "beta-tool", "label": "runs on"}], correspondent=AGENT),
        # Another conversation (no correspondent record) about the word itself: the general resolver, as before.
        _extraction(chat, [_entity("Instinct", "concept", chat)],
                    [{"source": "Instinct", "target": "beta-tool", "label": "inspired"}]),
    ]
    out = _resolve(tmp_path, extracted, existing)
    by_id = {c["id"]: c for c in out["changes"]}
    assert by_id["instinct-agent"]["action"] == "create"
    assert by_id["instinct-agent"]["entity"]["type"] == "tool"
    assert by_id["instinct-agent"]["source_episodes"] == [texted]
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
    (change,) = out["changes"]
    assert change["id"] == "alice-example-person" and change["entity"]["type"] == "person"

    # Nobody said who it is (no mark, no `identified` detection): nothing is decided, the general path runs.
    unknown = {"name": "Alice Example", "kind": "unknown", "decided_by": "none"}
    result = _extraction(ep, [_entity("Alice Example", "company", ep)], correspondent=unknown)
    assert correspondents.MARK not in result and correspondents.MARK not in result["entities"][0]
    out = _resolve(tmp_path, [result], existing)
    (change,) = out["changes"]
    assert change["id"] == "alice-example" and change["action"] == "update"


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
    assert correspondents.free_id(ident, {"instinct", "instinct-agent"}) == "instinct-agent-2"
