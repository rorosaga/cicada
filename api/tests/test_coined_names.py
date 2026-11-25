"""A name nobody said is a label, not a name (G148; `coined_names`, Stage 1's mark, Stage 2's one-conversation rungs).
Made-up names only."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.services import coined_names, entity_extractor, entity_resolver, evidence, pending_store
from api.tests.test_sleep_cycle_hold import _bank, _entity, _settings

EP_A, TS_A = "ep_2026-10-20_001", "2026-10-20T10:00:00+00:00"

CHAT = ("user: I'm building Lanternbook. The part I am stuck on is where you point the camera at the shelf.\n"
        "assistant: Let people confirm each guess.\n"
        "user: Good, the feedback form can wait.")


def _concept(name: str, **extra) -> dict:
    return {"name": name, "type": "concept", **extra}


# --- the reading -----------------------------------------------------------------------------------------------------


def test_a_name_is_said_by_whose_turn_says_it():
    assert coined_names.said_in(["Lanternbook"], CHAT) == coined_names.PERSON
    assert coined_names.said_in(["confirm each guess"], CHAT) == coined_names.OTHERS   # only the assistant said it
    assert coined_names.said_in(["Lanternbook shelf scanner"], CHAT) == coined_names.NOWHERE
    assert coined_names.said_in([], CHAT) == coined_names.NOWHERE


def test_a_case_or_an_accent_never_makes_a_name_unsaid_and_a_neighbour_word_never_makes_it_said():
    assert coined_names.located("user: the Café plan", "cafe plan")
    assert coined_names.located("user: LANTERNBOOK ships", "Lanternbook")
    assert not coined_names.located("user: the feedback pages", "feedback form")
    assert not coined_names.located("", "x") and not coined_names.located("x", "")


def test_an_agents_note_says_nothing_in_the_persons_turn():
    note = "Session notes for Lanternbook. PR #418 Add CSV export."
    assert coined_names.said_in(["Lanternbook"], note, override=evidence.AGENT_KIND) == coined_names.OTHERS
    assert coined_names.said_in(["Lanternbook"], note) == coined_names.PERSON   # a bare document is the person's own writing


def test_words_of_a_name_the_conversation_says():
    assert coined_names.words_of("camera shelf", CHAT) == "all"
    assert coined_names.words_of("camera widget", CHAT) == "some"
    assert coined_names.words_of("calendario semanal", CHAT) == "none"


# --- which entity is a label ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("entity, expected", [
    (_concept("Feedback form redesign"), True),                                          # no text says it
    ({"name": "Lanternbook shelf scanner", "type": "project"}, True),
    (_concept("Feedback form redesign", aliases=["the feedback form"]), False),          # the person's own words say an alias
    (_concept("Lanternbook"), False),                                                    # said
    ({"name": "Eiffel Tower", "type": "location"}, False),                               # a real name in other words: no label
    ({"name": "Acme Docs", "type": "tool"}, False),
    ({"name": "Dana Whitfield", "type": "person"}, False),
    (_concept("Summer fellowship", application={"status": "sent", "by": "user"}), False),   # ruling 42
    (_concept("A book", reading_status={"status": "finished"}), False),                     # ruling 64
])
def test_only_a_concept_or_project_no_text_says_is_a_label(entity, expected):
    assert coined_names.coined(entity, CHAT) is expected


def test_what_the_model_was_handed_counts_as_said():
    assert coined_names.coined(_concept("Claude Code session"), CHAT) is True
    assert coined_names.coined(_concept("Claude Code session"), CHAT, given="[Source: a Claude Code session.]") is False


# --- Stage 1 stamps it, from the text, never from the model --------------------------------------------------------------


def _episode(content: str, **fm) -> dict:
    return {"id": "ep_x", "content": content, "timestamp": TS_A, "origin": "chatgpt", **fm}


def _read(monkeypatch, episode: dict, entities: list[dict]) -> list[dict]:
    async def fake(ep_id, chunk, ci, total, settings, **kw):
        return {"entities": entities, "relationships": []}

    monkeypatch.setattr(entity_extractor, "_extract_chunk", fake)
    out = asyncio.run(entity_extractor.extract([episode], SimpleNamespace(memory_path=None, litellm_model="m")))
    return out[0]["entities"]


def test_stage_one_marks_a_label_and_asks_nothing_about_it(monkeypatch):
    said = {"name": "Lanternbook", "type": "project", "ask_person": "what rests on its name"}
    label = {"name": "Lanternbook feedback form", "type": "concept", "ask_person": "what rests on it", "coined": False}
    got = {e["name"]: e for e in _read(monkeypatch, _episode(CHAT), [said, label])}
    assert got["Lanternbook feedback form"].get(coined_names.COINED) is True, "the model's own word for it is never kept"
    assert "ask_person" not in got["Lanternbook feedback form"]
    assert coined_names.COINED not in got["Lanternbook"] and got["Lanternbook"]["ask_person"]


def test_stage_one_never_marks_what_a_note_an_agent_saved_says(monkeypatch):
    note = _episode("Session notes for Lanternbook. The shelf scanner crash is fixed.", source="mcp", origin="mcp",
                    harness="claude-code", session_id="s1")
    got = _read(monkeypatch, note, [{"name": "Lanternbook", "type": "project"}, _concept("Shelf scanner crash")])
    assert all(coined_names.COINED not in e for e in got)


# --- Stage 2: a label is born no page from one conversation, a name is ------------------------------------------------------


def _over_every_bar(name: str, **extra) -> dict:
    entity = _entity(name, "concept", EP_A, TS_A)
    entity.update(confidence=0.99, description="Discussed at length. " * 12, mention_exchanges=5, named_by_person=True, **extra)
    return entity


def _resolve(memory, entity, monkeypatch):
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    return asyncio.run(entity_resolver.resolve([{"episode_id": EP_A, "entities": [entity], "relationships": []}], [],
                                               _settings(memory)))


def test_a_name_over_the_bar_in_one_conversation_gets_its_page(tmp_path, monkeypatch):
    out = _resolve(_bank(tmp_path), _over_every_bar("Delta Plan"), monkeypatch)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("create", "delta-plan")]


def test_a_label_over_the_same_bar_waits_with_what_was_said_about_it(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    entity = _over_every_bar("Delta Plan", **{coined_names.COINED: True})
    out = _resolve(memory, entity, monkeypatch)
    assert [c for c in out["changes"] if c["action"] == "create"] == []
    (line,) = pending_store.load(memory)
    assert line.name == "Delta Plan" and line.episodes() == [EP_A], "held under its own name, the conversation kept"
    assert coined_names.COINED not in entity, "the mark is Stage 2's to read once and never carry on"


def test_a_label_a_second_conversation_gives_again_still_earns_its_page(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    other = "ep_2026-10-21_001"
    mark = {coined_names.COINED: True}
    out = asyncio.run(entity_resolver.resolve(
        [{"episode_id": EP_A, "entities": [{**_entity("Delta Plan", "concept", EP_A, TS_A), **mark}], "relationships": []},
         {"episode_id": other, "entities": [{**_entity("Delta Plan", "concept", other, "2026-10-21T10:00:00+00:00"), **mark}],
          "relationships": []}], [], _settings(memory)))
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("create", "delta-plan")]


def test_a_name_one_conversation_says_is_not_a_label_because_another_gave_it_unsaid(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    other = "ep_2026-10-21_001"
    out = asyncio.run(entity_resolver.resolve(
        [{"episode_id": EP_A, "entities": [_over_every_bar("Delta Plan", **{coined_names.COINED: True})], "relationships": []},
         {"episode_id": other, "entities": [_entity("Delta Plan", "concept", other, "2026-10-21T10:00:00+00:00")],
          "relationships": []}], [], _settings(memory)))
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("create", "delta-plan")]
