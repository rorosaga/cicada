"""A name held in a batch meets the page the same batch creates under a shorter or longer spelling (G148, 2026-11-23).

Stage 2 takes the most specific name first, so "Halvard Analytics", said once, is held before "Halvard", said twice,
becomes a page; a held name was never weighed against a later create, so the two stayed apart and an update to one
left the other current (`benchmarks/consolidation`, U1, every model). The join is the judge's: ``same`` folds the held
mention into the page, ``different`` leaves it held, and a person is never joined this way. Synthetic data only.
"""
from api.tests.test_entity_resolver_alias import _Judge, _resolve, bank  # noqa: F401 — the fixture


def _mention(name, etype, ep, ts):
    return {"name": name, "type": etype, "confidence": 0.7, "description": f"{name} came up.",
            "source_episode": ep, "source_episode_timestamp": ts}


def _extracted(long_name, short_name, etype):
    return [
        {"episode_id": "ep_2026-09-24_001", "relationships": [],
         "entities": [_mention(long_name, etype, "ep_2026-09-24_001", "2026-09-24T10:00:00Z")]},
        {"episode_id": "ep_2026-09-29_001", "relationships": [],
         "entities": [_mention(short_name, etype, "ep_2026-09-29_001", "2026-09-29T10:00:00Z")]},
        {"episode_id": "ep_2026-10-02_001", "relationships": [],
         "entities": [_mention(short_name, etype, "ep_2026-10-02_001", "2026-10-02T10:00:00Z")]},
    ]


def test_a_held_long_name_the_judge_calls_same_joins_the_short_name_page(bank, monkeypatch):  # noqa: F811
    judge = _Judge({"Halvard": "same"})
    out = _resolve(bank, monkeypatch, [], _extracted("Halvard Analytics", "Halvard", "company"), judge)
    assert ("Halvard Analytics", "Halvard") in judge.pairs
    assert out["name_to_id"]["halvard analytics"] == out["name_to_id"]["halvard"] == "halvard"
    (change,) = [c for c in out["changes"] if c["action"] == "create"]
    assert sorted(change["source_episodes"]) == ["ep_2026-09-24_001", "ep_2026-09-29_001", "ep_2026-10-02_001"]
    assert "Halvard Analytics" in out["promoted_pending"]


def test_a_held_name_the_judge_calls_different_stays_held(bank, monkeypatch):  # noqa: F811
    judge = _Judge({"Halvard": "different"})
    out = _resolve(bank, monkeypatch, [], _extracted("Halvard Analytics", "Halvard", "company"), judge)
    assert out["name_to_id"].get("halvard analytics") != "halvard"
    assert [c["id"] for c in out["changes"] if c["action"] == "create"] == ["halvard"]


def test_a_held_person_is_never_joined_by_this_pass(bank, monkeypatch):  # noqa: F811
    judge = _Judge({"Sam": "same"})
    out = _resolve(bank, monkeypatch, [], _extracted("Sam Okafor", "Sam", "person"), judge)
    assert out["name_to_id"].get("sam okafor") != "sam"
