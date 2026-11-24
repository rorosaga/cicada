"""A part and its whole named in one batch are one page (2026-11-24, G148).

"A canoe, its hull, the hull build — is one thing" (owner 2026-10-23). When both names are new in one batch neither has a
page to hold the relation the pair judge names (`_judged_relations` skips such a pair), so the two became two pages with
nothing between them, and the later progress of the part never reached the whole's page. Synthetic names; the pair judge
is a fake; the rest of Stage 2 is real."""
from __future__ import annotations

import asyncio

from api.services import entity_resolver
from api.tests.test_sleep_cycle_hold import _bank, _entity, _episode, _settings

EP, TS = "ep_2026-11-10_001", "2026-11-10T10:00:00+00:00"
EP2, TS2 = "ep_2026-11-12_001", "2026-11-12T10:00:00+00:00"


def _resolve(memory, pair_by_name, *, names=("Cedar Canoe", "Canoe Hull"), monkeypatch, more_part_mentions=False):
    for ep, ts in ((EP, TS), (EP2, TS2)):
        _episode(memory, ep, ts, "user: hello")
    whole = _entity(names[0], "project", EP, TS)
    part = _entity(names[1], "project", EP2, TS2)
    part["aliases"] = ["hull"]

    async def judge(*_a, **k):
        return pair_by_name.get(k.get("existing_name"), "different")

    async def batch(new_name, new_type, new_description, entries, settings, *, new_connections=""):
        return [pair_by_name.get(e["name"], "different") for e in entries]

    monkeypatch.setattr(entity_resolver.SqliteVecIndexer, "_rebuild_pending_index", lambda self, entries: None)
    monkeypatch.setattr(entity_resolver, "_llm_judge_same_entity", judge)
    monkeypatch.setattr(entity_resolver, "_llm_judge_batch", batch)
    extracted = [{"episode_id": EP, "entities": [whole], "relationships": []},
                 {"episode_id": EP2, "entities": [part], "relationships": []}]
    if more_part_mentions:   # the part is the name heard most: it must still not name the page
        extracted.append({"episode_id": "ep_2026-11-14_001", "entities": [_entity(names[1], "project", "ep_2026-11-14_001", "2026-11-14T10:00:00+00:00")], "relationships": []})
    return asyncio.run(entity_resolver.resolve(extracted, [], _settings(memory)))


def _created(out):
    return [c for c in out["changes"] if c["action"] == "create"]


def test_a_part_and_its_whole_judged_so_are_one_page_named_for_the_whole(tmp_path, monkeypatch):
    out = _resolve(_bank(tmp_path), {"Cedar Canoe": "related:part_of", "Canoe Hull": "related:has_part"}, monkeypatch=monkeypatch)
    created = _created(out)
    assert len(created) == 1 and created[0]["entity"]["name"] == "Cedar Canoe"
    aliases = {a.lower() for a in created[0]["entity"].get("aliases") or []}
    assert not aliases & {"hull", "canoe hull"}          # a part's names are never the whole's aliases


def test_the_part_heard_more_never_takes_the_wholes_name(tmp_path, monkeypatch):
    memory = _bank(tmp_path)
    _episode(memory, "ep_2026-11-14_001", "2026-11-14T10:00:00+00:00", "user: hello")
    out = _resolve(memory, {"Cedar Canoe": "related:part_of", "Canoe Hull": "related:has_part"}, monkeypatch=monkeypatch,
                   more_part_mentions=True)
    created = _created(out)
    assert len(created) == 1 and created[0]["entity"]["name"] == "Cedar Canoe"
    assert out["name_to_id"]["canoe hull"] == out["name_to_id"]["cedar canoe"]


def test_two_names_the_judge_calls_different_are_not_joined(tmp_path, monkeypatch):
    out = _resolve(_bank(tmp_path), {}, monkeypatch=monkeypatch)
    assert out["name_to_id"].get("canoe hull") != out["name_to_id"].get("cedar canoe") or "canoe hull" not in out["name_to_id"]
    assert not _created(out)    # each said in one conversation: held below the bar, as before


def test_a_related_verdict_that_is_not_a_part_joins_nothing(tmp_path, monkeypatch):
    out = _resolve(_bank(tmp_path), {"Cedar Canoe": "related:made_by", "Canoe Hull": "related:makes"}, monkeypatch=monkeypatch)
    assert not _created(out) and "canoe hull" not in out["name_to_id"]
