"""G169 — "the user" is the bank's owner, never a page of its own.

A fresh bank starts with its seeded ``owner: true`` page. Stage 1 then speaks of
the person as "User", "the user", "me", "I", "the person", "the owner" — or, in a
Spanish conversation, "el usuario" and "yo". Before this fix Stage 2 promoted
"User" to ``entities/user.md`` beside the owner page and routed its edges there.

Real: Stage 2 (no judge call — nothing shares a token), Stage 5's page write,
Stage 5.56's claims, the pending store and Stage 5.7's edges. Fakes: extraction,
Stage 3's legacy pass, Stage 4, git, the vector index. Synthetic names only."""
from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from api.services import (conflict_resolver, entity_extractor, entity_resolver, markdown_parser, owner_identity,
                          pending_store, sleep_cycle)
from api.services.claims import parse_claims
from api.tests.test_sleep_cycle_hold import _bank, _entity, _episode, _patch, _settings

EP, TS = "ep_2026-09-20_001", "2026-09-20T10:00:00+00:00"
OWNER_ID, OWNER_NAME = "alpha-owner", "Alpha Owner"
SELF_FORMS = ["User", "the user", "user", "me", "I", "the person", "the owner", "el usuario", "yo"]
# One per form, no two sharing a token (a shared token would send Stage 2 to its judge).
TARGETS = ["Gamma", "Delta", "Epsilon", "Zeta", "Theta", "Iota", "Kappa", "Lambda", "Sigma"]
TARGET_IDS = [t.lower() for t in TARGETS]


def _owner_page(memory: Path) -> None:
    owner_identity.save_owner({"name": OWNER_NAME, "entity_id": OWNER_ID})
    assert owner_identity.ensure_default_owner(memory) == OWNER_ID


def _rel(source: str, target: str, label: str) -> dict:
    return {"source": source, "target": target, "label": label, "source_episode": EP, "source_episode_timestamp": TS}


def _substantive(name: str, kind: str) -> dict:
    # Over Stage 2's substantive bar on its own: promoted on its first mention.
    entity = _entity(name, kind, EP, TS)
    entity.update(confidence=0.99, description="Discussed at length. " * 12)
    return entity


def _extraction() -> list[dict]:
    targets = TARGETS
    entities = [_substantive("User", "person")] + [_substantive(t, "tool") for t in targets]
    relationships = [_rel(form, target, "uses") for form, target in zip(SELF_FORMS, targets)]
    # A page-less name whose claim points AT the person: held with its pending line.
    entities.append(_entity("Zed Unknown", "person", EP, TS))
    relationships.append(_rel("Zed Unknown", "the person", "mentors"))
    return [{"episode_id": EP, "episode_timestamp": TS, "origin": "claude-export",
             "entities": entities, "relationships": relationships}]


def test_every_self_reference_lands_on_the_owner_page_and_no_user_page_is_written(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _owner_page(memory)
    _episode(memory, EP, TS, "user: I use a few tools.\nassistant: Noted.")
    _patch(monkeypatch, [_extraction()])

    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="g169_1"))

    pages = {p.stem for p in (memory / "entities").glob("*.md")}
    for form in SELF_FORMS:
        assert owner_identity_slug(form) not in pages, form
    assert OWNER_ID in pages

    owner = markdown_parser.parse(memory / "entities" / f"{OWNER_ID}.md")
    assert owner.frontmatter["name"] == OWNER_NAME and owner.frontmatter["owner"] is True
    assert owner.frontmatter["type"] == "person"
    claims = parse_claims(owner.body)
    objects = sorted(c.object for c in claims if c.subject == OWNER_ID and c.predicate == "uses")
    assert objects == sorted(TARGET_IDS)

    edges = yaml.safe_load((memory / "graph_edges.yaml").read_text(encoding="utf-8")) or {}
    rows = edges.get("edges", edges) if isinstance(edges, dict) else edges
    endpoints = {(r["source"], r["target"]) for r in rows}
    assert {(OWNER_ID, t) for t in TARGET_IDS} <= endpoints
    assert not any(e in {owner_identity_slug(f) for f in SELF_FORMS} for pair in endpoints for e in pair)

    # The pending line holds Zed's claim, and its object is the owner page.
    (line,) = [e for e in pending_store.load(memory) if e.held_claims]
    assert line.name == "Zed Unknown"
    assert [c["object"] for c in line.held_claims] == [OWNER_ID]
    assert not [e for e in pending_store.load(memory) if owner_identity.is_self_reference(e.name)]


def owner_identity_slug(form: str) -> str:
    from api.services.id_utils import sanitize_id

    return sanitize_id(form)


# --- the one rule -----------------------------------------------------------------


def test_self_references_are_one_closed_language_aware_set():
    for form in SELF_FORMS + ["  The User ", "USER", "Myself", "the user.", '"me"', "La usuaria", "el  usuario"]:
        assert owner_identity.is_self_reference(form), form
    for name in ["Users", "User Research", "Uber", "Alpha Owner", "Ivy", "Mel", "", "you", "the team"]:
        assert not owner_identity.is_self_reference(name), name


# --- Stage 2 on its own ----------------------------------------------------------------


def _existing_owner() -> list[dict]:
    return [{"id": OWNER_ID, "frontmatter": {"name": OWNER_NAME, "type": "person", "owner": True, "confidence": 1.0},
             "body": "The main person this memory belongs to."}]


def _resolve(tmp_path, extracted, existing):
    memory = _bank(tmp_path)
    return asyncio.run(entity_resolver.resolve(extracted, existing, _settings(memory)))


def test_stage_2_merges_a_self_reference_into_the_owner_page_under_the_owners_name(tmp_path, monkeypatch):
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    user = _substantive("User", "concept")
    user["aliases"] = ["me", "the dev"]
    out = _resolve(tmp_path, [{"episode_id": EP, "entities": [user], "relationships": []}], _existing_owner())
    (change,) = out["changes"]
    assert (change["action"], change["id"]) == ("update", OWNER_ID)
    assert change["entity"]["name"] == OWNER_NAME and change["entity"]["type"] == "person"
    assert change["entity"]["aliases"] == ["the dev"]


def test_stage_2_never_creates_a_self_reference_page_when_the_bank_has_no_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    extracted = [{"episode_id": EP, "entities": [_substantive("User", "person"), _substantive("Tool A", "tool")],
                  "relationships": [_rel("User", "Tool A", "uses")]}]
    out = _resolve(tmp_path, extracted, [])
    assert [c["id"] for c in out["changes"]] == ["tool-a"]
    assert out["relationships"] == []


def test_a_link_to_the_owner_alone_does_not_promote_a_first_mention(tmp_path, monkeypatch):
    # The owner is linked to everything the person talks about: that link is no
    # sign a name matters (the promotion rule's "link to a high-confidence page").
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    extracted = [{"episode_id": EP, "entities": [_entity("Tool A", "tool", EP, TS)],
                  "relationships": [_rel(OWNER_NAME, "Tool A", "uses")]}]
    out = _resolve(tmp_path, extracted, _existing_owner())
    assert out["changes"] == []


# --- the prompts name the owner --------------------------------------------------------


def _resp(payload: str):
    from types import SimpleNamespace

    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])


def test_stage_1_is_told_the_owners_name_and_never_to_write_the_user(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _owner_page(memory)
    seen: list[str] = []

    async def fake(**kw):
        seen.append(kw["messages"][0]["content"])
        return _resp('{"entities": [], "relationships": []}')

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake)
    settings = _settings(memory)
    settings.llm_mode = "byok"
    asyncio.run(entity_extractor.extract(
        [{"id": EP, "content": "user: hola, yo uso Tool A", "timestamp": TS, "origin": "claude-export"}], settings))
    (system,) = seen
    assert system.startswith(entity_extractor.EXTRACTION_SYSTEM_PROMPT)
    block = system[len(entity_extractor.EXTRACTION_SYSTEM_PROMPT):]
    assert f'"{OWNER_NAME}"' in block
    for form in ("the user", "User", "el usuario", "yo"):
        assert form in block


def test_stage_1_prompt_is_unchanged_without_an_owner_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    seen: list[str] = []

    async def fake(**kw):
        seen.append(kw["messages"][0]["content"])
        return _resp('{"entities": [], "relationships": []}')

    monkeypatch.setattr(entity_extractor.litellm, "acompletion", fake)
    settings = _settings(memory)
    settings.llm_mode = "byok"
    asyncio.run(entity_extractor.extract(
        [{"id": EP, "content": "user: I use Tool A", "timestamp": TS, "origin": "claude-export"}], settings))
    assert seen == [entity_extractor.EXTRACTION_SYSTEM_PROMPT]


def test_synthesis_names_the_owner_too(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _owner_page(memory)
    seen: list[str] = []

    async def fake(**kw):
        seen.append(kw["messages"][0]["content"])
        return _resp("Merged body.")

    monkeypatch.setattr(conflict_resolver.litellm, "acompletion", fake)
    settings = _settings(memory)
    settings.llm_mode = "byok"
    settings.effective_consolidation_model = "m"
    asyncio.run(conflict_resolver._synthesize_entity_update(
        "Tool A", "tool", "Old body.", "The user uses it daily.", [], TS[:10], settings))
    (prompt,) = seen
    assert f'"{OWNER_NAME}"' in prompt and "the user" in prompt.lower()
