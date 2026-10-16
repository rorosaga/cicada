"""Every conversation that mentioned a page is credited on it (Stage 2 exact-name collapse).

Several conversations in one Sleep batch can name the same entity by the same
normalized name. Stage 2 judges and promotes that name once, on its strongest
extraction; the others used to be dropped whole — their source credit, their
facts, links, questions, aliases, history, and the G118 evidence behind each
fact. These tests pin that every one of them now reaches the change, the page
and its section provenance. Synthetic data only; no model is called.
"""
import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from api.config import Settings
from api.services import (conflict_resolver as cr, entity_body as eb, entity_extractor as ex,
                          entity_resolver as er, markdown_parser as mp, section_provenance as sp)
from api.services.claims import strip_claims_block


def _extraction(n: int, *, name: str = "alpha-project", confidence: float = 0.8, **extra) -> dict:
    """Stage 1's output for one conversation, through Stage 1's own seams."""
    ep_id = f"ep_{2025 + (n - 1) // 12}-{(n - 1) % 12 + 1:02d}-15_001"
    day = ep_id[3:13]
    body = f"user: Synthetic observation-{n:02d}. {name} evaluated option-{n:02d}."
    entity = {
        "name": name, "type": "project", "confidence": confidence,
        "summary": f"{name} is a synthetic project discussed in observation {n:02d}.",
        "key_facts": [f"{name} evaluated option-{n:02d}."],
        "history_entries": [{"date": day, "event": f"Evaluated option-{n:02d}."}],
        "tags": [f"tag-{n:02d}"],
        "aliases": [f"alias-{n:02d}"],
        "links": [{"url": f"https://example.com/{n:02d}", "title": f"Note {n:02d}"}],
        "open_questions": [f"Is option-{n:02d} the right one?"],
        **extra,
    }
    sp.attach(entity, ep_id, body)
    entity.update(source_episode=ep_id, source_episode_timestamp=f"{day}T12:00:00Z",
                  source_episode_day=day, origin="synthetic")
    rel = {"source": name, "target": f"option-{n:02d}", "label": "uses", "confidence": 0.8,
           "source_episode": ep_id, "source_episode_timestamp": f"{day}T12:00:00Z", "origin": "synthetic"}
    return {"episode_id": ep_id, "episode_timestamp": f"{day}T12:00:00Z", "origin": "synthetic",
            "entities": [entity], "relationships": [rel], "body": body}


def _settings(bank, threshold: int = 2) -> SimpleNamespace:
    return SimpleNamespace(memory_path=bank, litellm_model="synthetic-model",
                           litellm_disambiguation_model="", sleep_promotion_threshold=threshold)


@pytest.fixture
def bank(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-bank"
    for name in ("entities", "episodes", "inbox"):
        (root / name).mkdir(parents=True)
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(root))
    monkeypatch.setattr(er, "SqliteVecIndexer", lambda *a, **k: None)

    async def no_model(*a, **k):  # every path under test is deterministic
        raise AssertionError("no model call expected")
    monkeypatch.setattr(er, "_llm_judge_same_entity", no_model)
    return root


def _resolve(extracted, existing, settings):
    return asyncio.run(er.resolve(extracted, existing, settings))


def _only_change(result, entity_id="alpha-project"):
    changes = [c for c in result["changes"] if c["id"] == entity_id]
    assert len(changes) == 1
    return changes[0]


def _assert_everything_credited(change, extracted):
    episodes = [x["episode_id"] for x in extracted]
    payload = change["entity"]
    assert sorted(cr._change_source_episodes(change)) == sorted(episodes)
    assert sorted(change["source_episode_timestamps"]) == sorted(x["episode_timestamp"] for x in extracted)
    assert sorted(change["source_episode_days"]) == sorted(e[3:13] for e in episodes)
    for x in extracted:
        mine = x["entities"][0]
        assert mine["key_facts"][0] in payload["key_facts"]
        assert mine["open_questions"][0] in payload["open_questions"]
        assert mine["aliases"][0] in payload["aliases"]
        assert mine["tags"][0] in payload["tags"]
        assert mine["links"][0]["url"] in {link["url"] for link in payload["links"]}
        assert mine["history_entries"][0] in payload["history_entries"]
        # G118: the fact still carries the evidence row of the conversation that said it.
        fact = mine["key_facts"][0]
        records = [r for r in payload[sp.INPUTS] if r["field"] == "key_facts" and r["text"] == fact]
        assert records and {ev["episode"] for ev in records[0]["evidence"]} == {x["episode_id"]}


def test_one_batch_promotion_credits_every_conversation(bank):
    extracted = [_extraction(n) for n in range(1, 6)]
    change = _only_change(_resolve(extracted, [], _settings(bank)))
    assert change["action"] == "create"
    _assert_everything_credited(change, extracted)


def test_the_strongest_extraction_still_leads_and_ties_keep_the_first(bank):
    extracted = [_extraction(1), _extraction(2, confidence=0.9), _extraction(3, confidence=0.9)]
    change = _only_change(_resolve(extracted, [], _settings(bank)))
    assert change["entity"]["confidence"] == 0.9
    _assert_everything_credited(change, extracted)


def test_an_existing_page_is_credited_by_every_conversation_in_the_batch(bank):
    existing = [{"id": "alpha-project", "frontmatter": {"name": "alpha-project", "type": "project"}, "body": ""}]
    extracted = [_extraction(n) for n in range(1, 5)]
    change = _only_change(_resolve(extracted, existing, _settings(bank)))
    assert change["action"] == "update"
    _assert_everything_credited(change, extracted)


def test_a_shorter_name_merging_into_an_in_cycle_page_brings_every_mention(bank):
    long = [_extraction(n, name="alpha-project-suite") for n in (1, 2)]
    short = [_extraction(n, name="alpha-project-suit") for n in (3, 4, 5)]  # fuzzy-same as the longer name
    change = _only_change(_resolve(long + short, [], _settings(bank)), "alpha-project-suite")
    assert sorted(change["source_episodes"]) == sorted(x["episode_id"] for x in long + short)
    for x in short:
        assert x["entities"][0]["key_facts"][0] in change["entity"]["key_facts"]


def test_a_website_or_decay_class_only_a_weaker_extraction_carried_is_kept(bank):
    extracted = [_extraction(1, confidence=0.9), _extraction(2, website="https://example.com", decay_class="durable")]
    payload = _only_change(_resolve(extracted, [], _settings(bank)))["entity"]
    assert payload["website"] == "https://example.com"
    assert payload["decay_class"] == "durable"


def test_a_name_still_pending_keeps_what_every_mention_said(bank, monkeypatch):
    parked = []

    class Indexer:
        def __init__(self, *a, **k): pass
        def pending_by_name(self, name): return None
        def index_pending_entity(self, entity): parked.append(entity)
        def rebuild_pending_index(self): return len(parked)

    monkeypatch.setattr(er, "SqliteVecIndexer", Indexer)
    extracted = [_extraction(n, confidence=0.5) for n in (1, 2)]
    result = _resolve(extracted, [], _settings(bank, threshold=3))
    assert result["changes"] == []
    assert len(parked) == 1
    assert {h["event"] for h in parked[0].history_entries} == {"Evaluated option-01.", "Evaluated option-02."}
    assert set(parked[0].tags) == {"tag-01", "tag-02"}


def test_claims_from_every_conversation_survive_the_collapse(bank):
    """Characterization: claims are projected from every extraction's relationships
    (Stage 5.56), keyed through Stage 2's name map — the collapse never reached them."""
    extracted = [_extraction(n) for n in range(1, 6)]
    result = _resolve(extracted, [], _settings(bank))
    claims = ex.entities_to_claims(extracted, None, resolve_id=lambda n: result["name_to_id"].get(n.lower(), n))
    assert sorted(c.source_episodes[0] for c in claims) == sorted(x["episode_id"] for x in extracted)
    assert {c.subject for c in claims} == {"alpha-project"}


def _write_page(bank, extracted, existing, settings):
    resolved = _resolve(extracted, existing, settings)
    real = Settings(_env_file=None, llm_mode="byok", litellm_model="synthetic-model")
    changes = asyncio.run(cr.resolve_and_prune(resolved["changes"], existing, real, decay=False,
                                               now=datetime(2027, 6, 1)))
    cr.apply_changes(changes, bank)
    return mp.parse(bank / "entities" / "alpha-project.md")


def test_25_conversations_in_one_batch_all_reach_the_page_with_their_provenance(bank):
    # The strongest extraction is the OLDEST: the newest mention must still set last_referenced.
    extracted = [_extraction(1, confidence=0.95)] + [_extraction(n) for n in range(2, 26)]
    page = _write_page(bank, extracted, [], _settings(bank))
    assert sorted(page.frontmatter["source_episodes"]) == sorted(x["episode_id"] for x in extracted)
    assert str(page.frontmatter["last_referenced"]) == "2027-01-15"
    sections = eb.parse_sections(strip_claims_block(page.body))
    for x in extracted:
        assert x["entities"][0]["key_facts"][0] in sections["Key Facts"]
    linked = sp.matched(page.frontmatter, page.body)["key_facts"]
    episodes = {ev.episode for _guard, evs in linked.values() for ev in evs}
    assert episodes == {x["episode_id"] for x in extracted}
