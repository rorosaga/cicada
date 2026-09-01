"""Sleep debt (G106 amendment) — live "Progress %" during a running cycle.

`sleep_cycle.progress_pct` is the literal "episodes processed / episodes in
this cycle" the coordinator asked for, scoped to Stage 1 (the only stage
with a natural per-episode unit — see its own docstring). Two layers: the
pure function against a bare `SleepState`, and an end-to-end check that
`entity_extractor.extract`'s `progress_callback` really does tick
`stage1_progress` live during the fan-out.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from api.services import entity_extractor, sleep_cycle
from api.services.sleep_cycle import SleepState, progress_pct


# --------------------------------------------------------------------------- #
# Pure: progress_pct(state)
# --------------------------------------------------------------------------- #


def test_progress_pct_is_none_when_idle():
    state = SleepState(status="idle", stage=0, episodes_total=10, stage1_progress=3)
    assert progress_pct(state) is None


def test_progress_pct_is_none_once_stage1_has_finished():
    """`stage` advances to 1 the instant Stage 1's `extract()` returns —
    Stages 2-5 have no per-episode unit to report, so this must go back to
    `None` rather than freezing at whatever Stage 1 left it at."""
    state = SleepState(status="running", stage=1, episodes_total=10, stage1_progress=10)
    assert progress_pct(state) is None


def test_progress_pct_is_none_with_no_episodes_this_cycle():
    state = SleepState(status="running", stage=0, episodes_total=0, stage1_progress=0)
    assert progress_pct(state) is None


def test_progress_pct_ticks_up_with_stage1_progress():
    state = SleepState(status="running", stage=0, episodes_total=4, stage1_progress=0)
    assert progress_pct(state) == 0
    state.stage1_progress = 1
    assert progress_pct(state) == 25
    state.stage1_progress = 2
    assert progress_pct(state) == 50
    state.stage1_progress = 4
    assert progress_pct(state) == 100


def test_progress_pct_never_exceeds_100_even_if_overcounted():
    """Defensive: `stage1_progress` should never outrun `episodes_total`,
    but the formula clamps regardless rather than reporting e.g. 150%."""
    state = SleepState(status="running", stage=0, episodes_total=4, stage1_progress=7)
    assert progress_pct(state) == 100


def test_progress_pct_defaults_to_the_module_singleton():
    """Called with no argument, reads `get_sleep_state()`'s live singleton —
    the shape `/sleep/status` and the SSE loop actually call it with."""
    state = sleep_cycle.get_sleep_state()
    state.status = "running"
    state.stage = 0
    state.episodes_total = 2
    state.stage1_progress = 1
    try:
        assert progress_pct() == 50
    finally:
        state.status = "idle"
        state.stage = 0
        state.episodes_total = 0
        state.stage1_progress = 0


# --------------------------------------------------------------------------- #
# End to end: extract()'s progress_callback really ticks per episode
# --------------------------------------------------------------------------- #


def test_extract_progress_callback_fires_once_per_episode_success_and_failure():
    calls = {"n": 0}

    def bump():
        calls["n"] += 1

    async def fake_chunk(ep_id, chunk, ci, total, settings):
        if ep_id == "ep_fail":
            raise RuntimeError("boom")
        return {"entities": [], "relationships": []}

    import api.services.entity_extractor as mod
    orig = mod._extract_chunk
    mod._extract_chunk = fake_chunk
    try:
        episodes = [
            {"id": "ep_ok", "content": "real content", "timestamp": "t", "origin": "mcp"},
            {"id": "ep_fail", "content": "real content", "timestamp": "t", "origin": "mcp"},
            {"id": "ep_empty", "content": "   ", "timestamp": "t", "origin": "mcp"},
        ]
        settings = SimpleNamespace(litellm_model="gpt-5.4-mini")
        out = asyncio.run(
            entity_extractor.extract(episodes, settings, progress_callback=bump)
        )
    finally:
        mod._extract_chunk = orig

    assert calls["n"] == 3, "one callback per episode regardless of outcome"
    assert len(out) == 2   # ep_ok (real) + ep_empty (fast path); ep_fail dropped


def test_extract_without_a_progress_callback_is_unaffected():
    episodes = [{"id": "ep_1", "content": "   ", "timestamp": "t", "origin": "mcp"}]
    settings = SimpleNamespace(litellm_model="gpt-5.4-mini")
    out = asyncio.run(entity_extractor.extract(episodes, settings))
    assert len(out) == 1


def test_stage1_progress_ticks_live_during_a_real_run(tmp_path, monkeypatch):
    """Full `run()`, Stage-1 boundaries stubbed out — asserts `stage1_progress`
    reached `episodes_total` by the time Stage 1 completes (`_state.stage`
    advances to 1), the same invariant `progress_pct` relies on."""
    from api.services import git_service, markdown_parser, predicates

    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    ids = ["ep_2026-09-01_001", "ep_2026-09-01_002", "ep_2026-09-01_003"]
    for i, ep_id in enumerate(ids):
        markdown_parser.write(
            memory / "episodes" / f"{ep_id}.md",
            {"id": ep_id, "processed": False, "source": "mcp",
             "timestamp": f"2026-09-01T10:0{i}:00"},
            f"Episode {ep_id} body.",
        )

    seen_max = {"n": 0}

    async def fake_extract(episodes, settings, cancel_check=None, progress_callback=None):
        for _ in episodes:
            if progress_callback is not None:
                progress_callback()
            seen_max["n"] = max(seen_max["n"], sleep_cycle.get_sleep_state().stage1_progress)
        return []

    async def fake_porcelain(memory_path):
        return ""

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr(git_service, "porcelain_status", fake_porcelain)

    settings = SimpleNamespace(
        memory_path=memory, litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano", archive_threshold=0.2,
        decay_nudge_threshold=0.4, link_enrich_enabled=False, inbox_stale_after_days=90,
    )
    asyncio.run(sleep_cycle.run(settings, "cycle-progress"))

    assert seen_max["n"] == 3
    assert sleep_cycle.get_sleep_state().stage1_progress == 3
