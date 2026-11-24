"""A thing named once and then spoken of by a part or a plain noun belongs to the thing (2026-11-24, G148).

Stage 1 reads one conversation, so "the hull" arrives as a name of its own; the pair judge weighs it against each page
alone and says "different" to every one. `part_placement` asks once over the whole list. Synthetic names; both the pair
judge and the placement call are fakes; the rest of Stage 2 is real."""
from __future__ import annotations

import asyncio

import pytest

from api.services import engine_errors, entity_resolver, markdown_parser, part_placement
from api.tests.test_sleep_cycle_hold import _bank, _entity, _settings

EP, TS = "ep_2026-11-10_001", "2026-11-10T10:00:00+00:00"
EP2, TS2 = "ep_2026-11-12_001", "2026-11-12T10:00:00+00:00"


def _page(eid, name, body):
    return {"id": eid, "frontmatter": {"name": name, "type": "project", "status": "active", "confidence": 0.8},
            "body": f"## Summary\n{body}"}


PAGES = [_page("example-canoe", "Example Canoe", "A cedar strip canoe built in a garage."),
         _page("example-thesis", "Example Thesis", "A master's thesis on tidal energy.")]


def _resolve(memory, extracted, pages, monkeypatch, *, pair="different", placed=None, pair_by_name=None, asks=None):
    async def judge(*_a, **k):
        return (pair_by_name or {}).get(k.get("existing_name"), pair)

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return [(pair_by_name or {}).get(e["name"], pair) for e in entries]

    async def ask(settings, system, prompt):
        if asks is not None:
            asks.append(prompt)
        if isinstance(placed, Exception):
            raise placed
        return placed

    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)
    monkeypatch.setattr(entity_resolver, "_same_name_ask", ask)
    return asyncio.run(entity_resolver.resolve(extracted, pages, _settings(memory)))


def _part(name="The Hull"):
    mention = _entity(name, "project", EP, TS)
    mention["description"] = "The hull is fully stripped and fiberglassed on the outside."
    mention["aliases"] = ["boat hull"]
    return {"episode_id": EP, "entities": [mention], "relationships": []}


def test_the_prompt_numbers_the_things_and_says_none_is_an_answer():
    prompt = part_placement.prompt_for("The Hull", "stripped", [("Example Canoe", "a canoe"), ("Example Thesis", "a thesis")])
    assert "[1] Example Canoe" in prompt and "[2] Example Thesis" in prompt and "Name: The Hull" in prompt
    assert "Choose 0" in prompt and "same KIND of thing" in prompt


@pytest.mark.parametrize("answer, listed, expected", [
    ({"entry": 2, "relation": "part_of"}, 3, (1, "part_of")),
    ({"entry": "1", "relation": "has_part"}, 3, (0, "has_part")),
    ({"entry": 1}, 3, (0, "part_of")),
    ({"entry": 0, "relation": "part_of"}, 3, None),
    ({"entry": 4}, 3, None),
    ({"entry": "x"}, 3, None),
    ({"entry": 13}, 20, None),
    ("a string", 3, None),
    (None, 3, None),
])
def test_an_answer_is_one_listed_thing_or_none(answer, listed, expected):
    assert part_placement.choice_of(answer, listed) == expected


def test_a_name_the_pair_judge_would_leave_lands_on_the_thing_the_list_names(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    asks: list = []
    out = _resolve(memory, [_part()], PAGES, monkeypatch, placed={"entry": 1, "relation": "part_of"}, asks=asks)
    assert [(c["action"], c["id"]) for c in out["changes"]] == [("update", "example-canoe")]
    assert not (out["changes"][0]["entity"].get("aliases") or [])   # a part's own names are never the whole's
    assert out["name_to_id"]["the hull"] == "example-canoe"
    assert len(asks) == 1 and "Example Canoe" in asks[0] and "Example Thesis" in asks[0]
    assert not list((memory / "inbox").glob("inbox-*.md"))


def test_none_leaves_the_name_as_it_was(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    out = _resolve(memory, [_part()], PAGES, monkeypatch, placed={"entry": 0, "relation": "part_of"})
    assert [c["id"] for c in out["changes"]] == [] and "the hull" not in out["name_to_id"]


@pytest.mark.parametrize("placed", [RuntimeError("model down"), "not json", {"entry": 9}])
def test_a_call_that_fails_places_nothing(tmp_path, monkeypatch, placed):
    memory = _bank(tmp_path)
    out = _resolve(memory, [_part()], PAGES, monkeypatch, placed=placed)
    assert [c["id"] for c in out["changes"]] == []


def test_an_engine_failure_is_never_a_none(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    with pytest.raises(engine_errors.EngineError):
        _resolve(memory, [_part()], PAGES, monkeypatch, placed=engine_errors.EngineError("plan limit"))


def test_a_name_the_pair_judge_placed_is_not_asked_again(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    asks: list = []
    out = _resolve(memory, [_part()], PAGES, monkeypatch, pair_by_name={"Example Canoe": "related:part_of"},
                   placed={"entry": 2}, asks=asks)
    assert [c["id"] for c in out["changes"]] == ["example-canoe"] and asks == []


def test_a_part_and_its_whole_said_in_one_batch_are_one_page(tmp_path, monkeypatch):
    """The two names have no page yet, so a relation between them had nowhere to be written: they became two pages with
    nothing between them. Now the pair judge's part is one group, and the whole's name is the page's, never the part's."""
    memory = _bank(tmp_path)
    for ep, ts in ((EP, TS), (EP2, TS2)):
        from api.tests.test_sleep_cycle_hold import _episode
        _episode(memory, ep, ts, "user: hello")
    whole = _entity("Cedar Canoe", "project", EP, TS)
    part = _entity("Canoe Hull", "project", EP2, TS2)
    part["aliases"] = ["hull"]
    out = _resolve(memory, [{"episode_id": EP, "entities": [whole], "relationships": []},
                            {"episode_id": EP2, "entities": [part], "relationships": []}], [], monkeypatch,
                   pair_by_name={"Cedar Canoe": "related:part_of", "Canoe Hull": "related:has_part"}, placed=None)
    created = [c for c in out["changes"] if c["action"] == "create"]
    assert len(created) == 1
    entity = created[0]["entity"]
    assert "hull" not in [a.lower() for a in entity.get("aliases") or []] and "canoe hull" not in [
        a.lower() for a in entity.get("aliases") or []]
    assert entity["name"] == "Cedar Canoe"
