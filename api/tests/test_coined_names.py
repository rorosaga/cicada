"""A name nobody said is a label, not a name (G148; `coined_names`, Stage 1's mark, Stage 2's one-conversation rungs).
Made-up names only."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.services import (application_page, coined_names, entity_extractor, entity_resolver, evidence, pending_store, promotion,
                          question_revisit)
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


# --- the name set is the rung's, whole ------------------------------------------------------------------------------------

MERCURY = "\n".join(f"user: Mercury needs a look at point {n}, the part where it syncs.\nassistant: Noted." for n in range(5))


@pytest.mark.parametrize("entity", [
    {"name": "Mercury (project)", "type": "concept"},                                  # a qualifier
    {"name": "Mercury (project)", "type": "project", "aliases": ["Merc", "Hg (the metal)", 7, ""]},   # and aliases
    {"name": "Delta Plan", "type": "concept"},                                          # neither
    {"name": "  Café  Nord (v2) ", "type": "concept", "aliases": ["cafe nord"]},        # accents, case and spaces
])
def test_the_name_set_is_the_one_the_promotion_rung_counts(entity):
    folded = [promotion._fold(n).strip() for n in coined_names.name_set(entity)]
    assert folded == promotion._names(entity)


def test_a_name_with_a_qualifier_is_said_by_what_the_rung_counts():
    assert coined_names.name_set({"name": "Mercury (project)", "type": "concept"}) == ["Mercury (project)", "Mercury"]
    assert coined_names.coined({"name": "Mercury (project)", "type": "concept"}, MERCURY) is False


def test_stage_one_never_stamps_a_name_the_rung_counts_and_stage_two_still_gives_it_its_page(tmp_path, monkeypatch):
    entity = {"name": "Mercury (project)", "type": "concept", "confidence": 0.95,
              "description": "Discussed at length. " * 12}
    (got,) = _read(monkeypatch, _episode(MERCURY), [entity])
    assert got["mention_exchanges"] > 3 and got["named_by_person"] is True
    assert coined_names.COINED not in got
    out = _resolve(_bank(tmp_path), {**_entity("Mercury (project)", "concept", EP_A, TS_A), **got}, monkeypatch)
    assert [c["action"] for c in out["changes"]] == ["create"]


# --- the guards read what is there when the stamp is made -----------------------------------------------------------------


def test_what_the_person_acted_on_or_said_a_status_of_is_never_a_label():
    entity = _concept("Autumn residency")
    assert coined_names.coined(entity, CHAT) is True
    assert coined_names.coined({**entity, application_page.KEY: {"episode": EP_A, "status": "sent", "by": "user"}}, CHAT) is False
    assert coined_names.coined(entity, CHAT, booked=True) is False


def test_stage_one_consumes_the_models_application_and_status_before_it_stamps(monkeypatch):
    said = "user: I sent in my application to the Autumn residency yesterday.\nassistant: Good luck."
    entity = {"name": "Autumn residency", "type": "concept", "application": {"status": "sent", "by": "user"}}
    (got,) = _read(monkeypatch, _episode(said), [entity])
    assert "application" not in got and application_page.KEY in got and coined_names.COINED not in got
    book = "user: I finished reading Salt Roads last week.\nassistant: How was it?"
    entity = {"name": "Salt Roads", "type": "concept",
              "reading_status": {"status": "finished", "quote": "I finished reading Salt Roads"}}
    (got,) = _read(monkeypatch, _episode(book), [entity])
    assert "reading_status" not in got and coined_names.COINED not in got


# --- one conversation is folded once -------------------------------------------------------------------------------------


def test_a_long_conversation_is_folded_once_however_many_names_are_checked(monkeypatch):
    built = []
    real = question_revisit.Words.__init__

    def counting(self, text):
        built.append(len(text))
        real(self, text)

    monkeypatch.setattr(question_revisit.Words, "__init__", counting)
    text = "user: " + "tide pool anemone kelp " * 400 + "\nassistant: ok"
    reading = coined_names.Reading(text, extra="the owner's name")
    entities = [{"name": f"Zq{n} widget plan", "type": "concept", "aliases": [f"Zq{n} wdg", f"The Zq{n} thing"]}
                for n in range(40)]
    assert all(coined_names.coined(e, text, reading=reading) for e in entities)
    assert len(built) <= 3, "the person's turns, the whole text and the extra text: once each, never once per name"
    assert reading.has("text", "anemone kelp") and len(built) <= 3


@pytest.mark.parametrize("name", ["anemone kelp", "Anemone", "ANEMONE KELP TIDE", "tide pool pool", "Cafe", "cafe nord", "Zebra",
                                  "kelp-tide", "naïve idea", "naive"])
def test_the_words_read_once_answer_as_the_pass_that_reads_every_time(name):
    text = "Tide pool anemone kelp. Café Nord is open; a naïve idea, about the kelp tide."
    assert question_revisit.Words(text).name_in(name) is question_revisit._hits([name], [], text)[0]
