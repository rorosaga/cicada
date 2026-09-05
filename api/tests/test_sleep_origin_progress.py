"""G125 — the study list counts down per source while Stage 1 reads.

`SleepState.queue_by_origin` is the cycle's selected episodes grouped by
`origin` (set once, right after the cap slice); `read_by_origin` ticks up per
episode as `entity_extractor.extract` finishes it — the same per-episode
unit `progress_pct` already scopes itself to (R3). Hermetic: `_extract_chunk`
is swapped, no model, no network.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import api.services.entity_extractor as mod
from api.services import entity_extractor, sleep_cycle
from api.services.sleep_cycle import SleepState


def test_state_defaults_are_empty_dicts_not_shared():
    a, b = SleepState(), SleepState()
    a.queue_by_origin["x"] = 1
    assert b.queue_by_origin == {}          # dataclass default_factory, not a shared literal
    assert SleepState().read_by_origin == {}


def test_extract_fires_on_episode_done_with_the_episode_for_every_outcome():
    seen: list[str] = []

    async def fake_chunk(ep_id, chunk, ci, total, settings):
        if ep_id == "ep_fail":
            raise RuntimeError("boom")
        return {"entities": [], "relationships": []}

    orig = mod._extract_chunk
    mod._extract_chunk = fake_chunk
    try:
        episodes = [
            {"id": "ep_ok", "content": "real content", "timestamp": "t", "origin": "claude-code"},
            {"id": "ep_fail", "content": "real content", "timestamp": "t", "origin": "safari-tab"},
            {"id": "ep_empty", "content": "   ", "timestamp": "t", "origin": "safari-tab"},
        ]
        asyncio.run(entity_extractor.extract(
            episodes, SimpleNamespace(litellm_model="gpt-5.4-mini"),
            on_episode_done=lambda ep: seen.append(ep["origin"]),
        ))
    finally:
        mod._extract_chunk = orig

    assert sorted(seen) == ["claude-code", "safari-tab", "safari-tab"]


def test_extract_without_on_episode_done_is_unchanged():
    episodes = [{"id": "ep_1", "content": "   ", "timestamp": "t", "origin": "mcp"}]
    out = asyncio.run(entity_extractor.extract(episodes, SimpleNamespace(litellm_model="m")))
    assert len(out) == 1


def test_run_sets_queue_by_origin_from_the_capped_slice_and_ticks_read_by_origin(tmp_path, monkeypatch):
    """Full `run()` with Stage-1 boundaries stubbed — mirrors
    test_sleep_progress.test_stage1_progress_ticks_live_during_a_real_run."""
    from api.services import markdown_parser, predicates

    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    for i, origin in enumerate(["claude-code", "claude-code", "safari-tab", "telegram"], start=1):
        markdown_parser.write(
            memory / "episodes" / f"ep_2026-09-01_{i:03d}.md",
            {"id": f"ep_2026-09-01_{i:03d}", "timestamp": f"2026-09-01T0{i}:00:00Z",
             "source": "test", "origin": origin, "processed": False},
            f"episode {i} body",
        )
    snapshots: list[dict] = []

    async def fake_extract(episodes, settings, *, cancel_check=None, progress_callback=None, on_episode_done=None):
        for ep in episodes:
            if progress_callback:
                progress_callback()
            if on_episode_done:
                on_episode_done(ep)
            snapshots.append(dict(sleep_cycle.get_sleep_state().read_by_origin))
        return []   # total Stage-1 failure → cycle aborts cleanly with the queue untouched

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    settings = SimpleNamespace(
        memory_path=memory, litellm_model="m", litellm_disambiguation_model="m",
        archive_threshold=0.2, decay_nudge_threshold=0.4, link_enrich_enabled=False,
        inbox_stale_after_days=90, sleep_max_episodes_per_cycle=3,
    )
    asyncio.run(sleep_cycle.run(settings, "cycle-origins"))
    state = sleep_cycle.get_sleep_state()

    assert state.queue_by_origin == {"claude-code": 2, "safari-tab": 1}   # cap 3 of 4, oldest first
    assert snapshots[-1] == {"claude-code": 2, "safari-tab": 1}
    assert snapshots[0] in ({"claude-code": 1}, {"safari-tab": 1})


def test_sleep_status_and_episodes_carry_the_new_fields(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import config, main
    from api.services import bank_index, markdown_parser

    memory = tmp_path
    (memory / "episodes").mkdir()
    (memory / "entities").mkdir()
    markdown_parser.write(
        memory / "episodes" / "ep_2026-09-01_001.md",
        {"id": "ep_2026-09-01_001", "timestamp": "2026-09-01T01:00:00Z", "source": "test",
         "origin": "telegram", "processed": False},
        "twelve chars",
    )
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(memory))
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    state = sleep_cycle.get_sleep_state()
    state.queue_by_origin = {"telegram": 1}
    state.read_by_origin = {}
    try:
        with TestClient(main.app) as client:
            status = client.get("/sleep/status").json()
            assert status["queueByOrigin"] == {"telegram": 1}
            assert status["readByOrigin"] == {}
            rows = client.get("/sleep/episodes").json()
            assert rows[0]["chars"] == len("twelve chars")
    finally:
        state.queue_by_origin = {}
        config.get_settings.cache_clear()
