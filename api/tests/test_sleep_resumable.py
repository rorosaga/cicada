"""Resumable Sleep queue: a partial run leaves failed episodes queued so a
re-trigger continues *where it left off* instead of re-spending the whole batch.

Motivating scenario: a large import (e.g. 215 Claude episodes) consolidated under
a hard OpenRouter credit cap. When credits run dry mid-extraction, the remaining
episodes' Stage-1 calls error and are dropped from the extracted set. The cycle
must mark ONLY the successfully-extracted episodes ``processed`` and leave the
rest ``processed: false`` — so the user tops up credits, hits Sleep again, and
only the un-consolidated episodes are retried.

Hermetic: the LLM/git/index boundaries are stubbed (no network, no real model,
no real git), mirroring ``test_sleep_cycle_claims_wired.py``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.services import (
    entity_extractor,
    git_service,
    markdown_parser,
    predicates,
    sleep_cycle,
)


def _seed_episodes(tmp_path, ids):
    """Seed N unprocessed episodes; return the memory dir."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    for i, ep_id in enumerate(ids):
        markdown_parser.write(
            memory / "episodes" / f"{ep_id}.md",
            {"id": ep_id, "processed": False, "source": "claude-export",
             "timestamp": f"2026-06-17T10:0{i}:00"},
            f"Episode {ep_id} body about project X and tool Y.",
        )
    return memory


def _patch_boundaries(monkeypatch, *, extract_fn):
    """Stub every LLM/git/index boundary; ``extract_fn`` drives Stage 1."""
    async def fake_resolve(extracted_arg, existing, settings):
        # Echo one trivial create per extracted episode so later stages have shape.
        changes = []
        for r in extracted_arg:
            changes.append({
                "id": r["episode_id"].replace("ep_", "e_"),
                "action": "create",
                "source_episode": r["episode_id"],
                "source_episodes": [r["episode_id"]],
                "trigger": "sleep/extraction",
                "entity": {"name": r["episode_id"], "type": "concept", "confidence": 0.7},
            })
        return {"changes": changes, "relationships": [], "episode_cooccurrences": {}}

    async def fake_detect(changes, existing, settings, **kw):
        return []

    async def fake_resolve_and_prune(resolved, existing, settings):
        return list(resolved)

    async def fake_commit(memory_path, message):
        return None

    async def fake_porcelain(memory_path):
        return ""

    class _FakeIndexer:
        def __init__(self, *_a, **_k):
            pass

        def index_entities(self):
            return 0

        def index_episodes(self):
            return 0

        def index_claims(self):
            return 0

    monkeypatch.setattr("api.services.entity_extractor.extract", extract_fn)
    monkeypatch.setattr("api.services.entity_resolver.resolve", fake_resolve)
    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
    monkeypatch.setattr(
        "api.services.conflict_resolver.resolve_and_prune", fake_resolve_and_prune
    )
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(git_service, "porcelain_status", fake_porcelain)
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)


def _settings(memory):
    return SimpleNamespace(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        archive_threshold=0.2,
        decay_nudge_threshold=0.4,
        link_enrich_enabled=False,
    )


def _is_processed(memory, ep_id):
    parsed = markdown_parser.parse(memory / "episodes" / f"{ep_id}.md")
    return bool(parsed.frontmatter.get("processed", False))


def _extracted_for(ids):
    """Build minimal Stage-1 extracted results for the given episode ids."""
    return [{
        "episode_id": ep_id,
        "episode_timestamp": "2026-06-17T10:00:00",
        "origin": "claude-export",
        "entities": [{"name": ep_id, "type": "concept", "source_episode": ep_id}],
        "relationships": [],
    } for ep_id in ids]


def test_failed_extractions_stay_queued(tmp_path, monkeypatch):
    ids = ["ep_2026-06-17_001", "ep_2026-06-17_002", "ep_2026-06-17_003"]
    memory = _seed_episodes(tmp_path, ids)

    # Stage 1 succeeds for #1 and #3; #2 "failed" (credit error) -> omitted.
    async def partial_extract(episodes, settings):
        return _extracted_for([ids[0], ids[2]])

    _patch_boundaries(monkeypatch, extract_fn=partial_extract)
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="run1"))

    # Only the extracted episodes are marked done; the failed one stays queued.
    assert _is_processed(memory, ids[0]) is True
    assert _is_processed(memory, ids[2]) is True
    assert _is_processed(memory, ids[1]) is False

    state = sleep_cycle.get_sleep_state()
    assert state.episodes_processed == 2
    assert state.episodes_requeued == 1
    assert state.error is None  # a partial success is not a hard error

    # The queue the next run would consume is EXACTLY the failed episode.
    remaining = [e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)]
    assert remaining == [ids[1]]


def test_rerun_consolidates_only_the_requeued(tmp_path, monkeypatch):
    ids = ["ep_2026-06-17_001", "ep_2026-06-17_002", "ep_2026-06-17_003"]
    memory = _seed_episodes(tmp_path, ids)

    async def partial_extract(episodes, settings):
        return _extracted_for([ids[0], ids[2]])

    _patch_boundaries(monkeypatch, extract_fn=partial_extract)
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="run1"))

    # Second run: extract is called ONLY with the still-unprocessed episodes,
    # and now it succeeds for the remainder.
    seen_ids: list[str] = []

    async def retry_extract(episodes, settings):
        seen_ids.extend(e["id"] for e in episodes)
        return _extracted_for([e["id"] for e in episodes])

    monkeypatch.setattr("api.services.entity_extractor.extract", retry_extract)
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="run2"))

    assert seen_ids == [ids[1]]  # only the requeued episode reached Stage 1
    assert _is_processed(memory, ids[1]) is True
    assert sleep_cycle._get_unprocessed_episodes(memory) == []


def test_all_failed_leaves_queue_intact_and_errors(tmp_path, monkeypatch):
    ids = ["ep_2026-06-17_001", "ep_2026-06-17_002"]
    memory = _seed_episodes(tmp_path, ids)

    # Wrong model / no credits at all -> Stage 1 yields nothing.
    async def empty_extract(episodes, settings):
        return []

    _patch_boundaries(monkeypatch, extract_fn=empty_extract)
    asyncio.run(sleep_cycle.run(_settings(memory), cycle_id="run1"))

    # Nothing marked, queue fully intact, and the run reports a hard error
    # instead of a misleading empty "completed".
    assert _is_processed(memory, ids[0]) is False
    assert _is_processed(memory, ids[1]) is False
    state = sleep_cycle.get_sleep_state()
    assert state.error is not None
    assert state.episodes_processed == 0


def test_empty_content_episode_is_marked_done_not_retried():
    """An episode with blank content needs no LLM call and must not retry forever.

    ``extract`` short-circuits empty content WITHOUT a network call, yet must
    still return a (zero-entity) result so the cycle marks it processed.
    """
    settings = SimpleNamespace(litellm_model="gpt-5.4-mini")
    episodes = [{"id": "ep_2026-06-17_009", "content": "   \n  ",
                 "timestamp": "2026-06-17T10:00:00", "origin": "claude-export"}]
    out = asyncio.run(entity_extractor.extract(episodes, settings))
    assert len(out) == 1
    assert out[0]["episode_id"] == "ep_2026-06-17_009"
    assert out[0]["entities"] == []
