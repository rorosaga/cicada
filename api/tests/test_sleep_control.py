"""Sleep cycle control — cancel route + episode cap.

The whole-branch review flagged the missing cancel route as the last
first-run hazard once Sleep can run on the agent engine: no way to stop a
long cycle short of killing the backend, and a kill after `write_started`
leaves a dirty bank. This file covers the two knobs that close that gap:

- `POST /sleep/cancel` + cooperative cancellation, checked ONLY at safe
  points (between stages, and inside Stage 1's fan-out / Stage 2's per-name
  judging loop) — never mid-write, mid-commit, or between a write and its
  commit.
- A settings-driven episode cap (`Settings.sleep_max_episodes_per_cycle`) so
  one cycle can't run unbounded against a huge queue.

Hermetic: no network, no real model, no real `claude` spawn (the suite-wide
`_no_real_agent_spawn` fixture in conftest.py already guards that). The core
gate scenario (cancel mid-cycle) uses a REAL git repo so "the bank is clean"
is proven by an actual `git status --porcelain`, not a stubbed assertion —
mirrors `test_sleep_connector_poll.py`'s final-review-H1 test.
"""

from __future__ import annotations

import asyncio
import subprocess
from types import SimpleNamespace

import pytest

from api.services import entity_extractor, entity_resolver, git_service, markdown_parser, predicates, sleep_cycle


def _settings(memory, **overrides):
    base = dict(
        memory_path=memory,
        litellm_model="gpt-5.4-mini",
        litellm_disambiguation_model="gpt-5.4-nano",
        archive_threshold=0.2,
        decay_nudge_threshold=0.4,
        link_enrich_enabled=False,
        inbox_stale_after_days=90,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), check=True, capture_output=True, text=True
    ).stdout


def _seed_git_bank(tmp_path, ids):
    """A real git repo with N unprocessed, session-tagged episodes."""
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    (memory / "episodes").mkdir(parents=True)
    predicates.install_predicate_map(memory)
    for i, ep_id in enumerate(ids):
        markdown_parser.write(
            memory / "episodes" / f"{ep_id}.md",
            {"id": ep_id, "processed": False, "source": "mcp",
             "timestamp": f"2026-09-01T10:{i:02d}:00",
             "session_id": "ses_2026-09-01_abc12345"},
            f"Episode {ep_id} body about project X and tool Y.",
        )
    _git(memory, "init", "-q")
    _git(memory, "config", "user.email", "test@cicada.local")
    _git(memory, "config", "user.name", "Cicada Test")
    _git(memory, "add", "-A")
    _git(memory, "commit", "-q", "-m", "seed")
    return memory


@pytest.fixture
def tail_spy(monkeypatch):
    """Mirrors test_sleep_engine_state.py's fixture of the same name: records
    which engine-independent tail steps ran, in order."""
    ran: list[str] = []

    async def _logos(memory_path):
        ran.append("logos")

    async def _connectors(memory_path):
        ran.append("connectors")

    async def _questions(memory_path, settings):
        ran.append("questions")

    monkeypatch.setattr(sleep_cycle, "_warm_logos_safely", _logos)
    monkeypatch.setattr(sleep_cycle, "_poll_connectors_safely", _connectors)
    monkeypatch.setattr(sleep_cycle, "_refresh_questions_safely", _questions)
    return ran


# --------------------------------------------------------------------------- #
# request_cancel() itself: idempotent, no-op when nothing is running
# --------------------------------------------------------------------------- #


def test_request_cancel_is_a_noop_when_nothing_is_running():
    assert sleep_cycle.get_sleep_state().status == "idle"
    was_running, cycle_id = sleep_cycle.request_cancel()
    assert was_running is False
    assert cycle_id is None
    assert sleep_cycle.get_sleep_state().cancel_requested is False


def test_request_cancel_is_idempotent_while_running():
    state = sleep_cycle.get_sleep_state()
    state.status = "running"
    state.cycle_id = "sleep_test"
    try:
        first = sleep_cycle.request_cancel()
        second = sleep_cycle.request_cancel()
        assert first == (True, "sleep_test")
        assert second == (True, "sleep_test")
        assert state.cancel_requested is True
    finally:
        state.status = "idle"
        state.cancel_requested = False


# --------------------------------------------------------------------------- #
# THE gate scenario: cancel mid-cycle, before any write — bank stays clean
# --------------------------------------------------------------------------- #


def test_cancel_before_writes_leaves_bank_clean_queue_untouched_status_idle_and_tail_runs(
    tmp_path, monkeypatch, tail_spy,
):
    """A fake Stage-1 extractor simulates a concurrent `POST /sleep/cancel`
    landing mid-Stage-1 (exactly what a real request handler would do — call
    `sleep_cycle.request_cancel()` — while `run()` is still awaiting
    `extract()`). Stage 2 is booby-trapped: if the cancel-safe-point check
    after Stage 1 didn't fire, this would catch it. Asserts every property
    the gate calls out: the bank is clean, unprocessed episodes are still
    `processed: false`, the structural tail ran, and status returned to idle.
    """
    ids = ["ep_2026-09-01_001", "ep_2026-09-01_002"]
    memory = _seed_git_bank(tmp_path, ids)

    async def fake_extract(episodes, settings, cancel_check=None, **_kw):
        was_running, cycle_id = sleep_cycle.request_cancel()
        assert was_running is True
        assert cycle_id == "cycle-cancel"
        return [{
            "episode_id": ep["id"], "episode_timestamp": ep["timestamp"],
            "origin": "mcp",
            "entities": [{"name": ep["id"], "type": "concept", "confidence": 0.7,
                          "source_episode": ep["id"]}],
            "relationships": [],
        } for ep in episodes]

    async def boom_resolve(*a, **kw):
        raise AssertionError("Stage 2 must never run once cancelled")

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr("api.services.entity_resolver.resolve", boom_resolve)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-cancel"))

    state = sleep_cycle.get_sleep_state()
    assert state.status == "idle"
    assert state.cancelled is True
    assert state.cancel_requested is False
    assert "Cancelled" in (state.progress or "")
    assert state.error is None

    # The bank is clean: no dirty files, nothing new committed.
    assert _git(memory, "status", "--porcelain").strip() == ""
    assert len(_git(memory, "log", "--oneline").strip().splitlines()) == 1

    # Unprocessed episodes are untouched.
    remaining_ids = {e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)}
    assert remaining_ids == set(ids)

    # The structural tail (sixth exit path) still ran.
    assert set(tail_spy) == {"logos", "connectors", "questions"}


def test_cancel_between_stage2_and_stage3_also_aborts_clean(tmp_path, monkeypatch, tail_spy):
    """The safe-point check fires between EVERY stage boundary, not only
    after Stage 1 — this exercises the Stage-2-to-3 boundary specifically."""
    ids = ["ep_2026-09-01_001"]
    memory = _seed_git_bank(tmp_path, ids)

    async def fake_extract(episodes, settings, cancel_check=None, **_kw):
        return [{
            "episode_id": ep["id"], "episode_timestamp": ep["timestamp"],
            "origin": "mcp",
            "entities": [{"name": ep["id"], "type": "concept", "confidence": 0.7,
                          "source_episode": ep["id"]}],
            "relationships": [],
        } for ep in episodes]

    async def fake_resolve(extracted_arg, existing, settings, cancel_check=None):
        sleep_cycle.request_cancel()
        return {"changes": [], "relationships": [], "episode_cooccurrences": {}}

    async def boom_prune(*a, **kw):
        raise AssertionError("Stage 3 must never run once cancelled")

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr("api.services.entity_resolver.resolve", fake_resolve)
    monkeypatch.setattr("api.services.conflict_resolver.resolve_and_prune", boom_prune)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-cancel-2"))

    state = sleep_cycle.get_sleep_state()
    assert state.status == "idle"
    assert state.cancelled is True
    assert _git(memory, "status", "--porcelain").strip() == ""
    assert set(tail_spy) == {"logos", "connectors", "questions"}


# --------------------------------------------------------------------------- #
# A cancel that arrives too late (after Stage 5 started writing) is honored
# only for the NEXT cycle — this one finishes its own commit safely.
# --------------------------------------------------------------------------- #


def test_cancel_after_writes_began_still_commits_normally(tmp_path, monkeypatch, tail_spy):
    """Mirrors `test_sleep_resumable.py`'s boundary-stubbing pattern (real
    Stage 5.5-5.7 sub-stages, git/index boundaries faked) plus one extra
    hook: `inbox_generator.generate` requests a cancel the instant it's
    called — i.e. exactly when `write_started` has just flipped True. The
    cycle must still reach `_finalize` and commit; only the NEXT cycle
    should ever see the effect of a cancel requested this late.
    """
    ids = ["ep_2026-09-01_001"]
    memory = _seed_git_bank(tmp_path, ids)

    async def fake_extract(episodes, settings, cancel_check=None, **_kw):
        return [{
            "episode_id": ep["id"], "episode_timestamp": ep["timestamp"],
            "origin": "mcp",
            "entities": [{"name": ep["id"], "type": "concept", "confidence": 0.7,
                          "source_episode": ep["id"]}],
            "relationships": [],
        } for ep in episodes]

    async def fake_resolve(extracted_arg, existing, settings, cancel_check=None):
        changes = [{
            "id": "e1", "action": "create", "source_episode": extracted_arg[0]["episode_id"],
            "source_episodes": [extracted_arg[0]["episode_id"]], "trigger": "sleep/extraction",
            "entity": {"name": "E1", "type": "concept", "confidence": 0.7},
        }]
        return {"changes": changes, "relationships": [], "episode_cooccurrences": {}}

    async def fake_detect(changes, existing, settings, **kw):
        return []

    async def fake_prune(resolved, existing, settings):
        return list(resolved)

    from api.services import inbox_generator
    real_generate = inbox_generator.generate

    async def fake_generate(changes, skills, memory_path, relationships=None):
        # Simulate a cancel landing exactly as Stage 5 starts writing —
        # `write_started` is already True by the time `_run_stages` calls
        # this (see sleep_cycle.py's Stage 5 preamble).
        was_running, _ = sleep_cycle.request_cancel()
        assert was_running is True
        await real_generate(changes, skills, memory_path, relationships=relationships)

    commit_calls = []

    async def fake_commit(memory_path, message):
        commit_calls.append(message)
        return "deadbeef"

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

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr("api.services.entity_resolver.resolve", fake_resolve)
    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
    monkeypatch.setattr("api.services.conflict_resolver.resolve_and_prune", fake_prune)
    monkeypatch.setattr("api.services.inbox_generator.generate", fake_generate)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(git_service, "porcelain_status", fake_porcelain)
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-late-cancel"))

    state = sleep_cycle.get_sleep_state()
    assert state.status == "idle"
    assert commit_calls, "the cycle must still commit — a late cancel can't un-write Stage 5"
    assert state.cancelled is False, "this cycle was NOT the one that stopped early"
    assert state.cancel_requested is False, "the flag is cleared once acknowledged"
    assert "cancel requested after writes began" in (state.progress or "")
    # "questions" is correctly ABSENT here: a fully completed cycle already
    # ran Stage 5.56's real `refresh_open_questions` in-line (`outcome.
    # questions_refreshed=True`), so the tail skips doing it a second time —
    # existing behavior, unrelated to cancellation. logos/connectors are the
    # two tail steps a completed cycle still runs unconditionally.
    assert set(tail_spy) == {"logos", "connectors"}


# --------------------------------------------------------------------------- #
# Cancellation must not wedge `_state.status`
# --------------------------------------------------------------------------- #


def test_a_cancelled_cycle_never_wedges_status_for_the_next_trigger(tmp_path, monkeypatch, tail_spy):
    ids = ["ep_2026-09-01_001"]
    memory = _seed_git_bank(tmp_path, ids)

    async def fake_extract(episodes, settings, cancel_check=None, **_kw):
        sleep_cycle.request_cancel()
        return []

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)

    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-a"))
    assert sleep_cycle.get_sleep_state().status == "idle"

    # A second cycle must be free to start — the exact regression this repo
    # already fixed once for a different bug (status wedged at "running").
    asyncio.run(sleep_cycle.run(_settings(memory), "cycle-b"))
    assert sleep_cycle.get_sleep_state().status == "idle"


# --------------------------------------------------------------------------- #
# entity_extractor.extract's own cancel_check: stops scheduling new work
# --------------------------------------------------------------------------- #


def test_extract_spends_no_llm_call_once_cancel_check_is_already_true(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("must not call the LLM once cancelled")

    monkeypatch.setattr(entity_extractor, "_extract_chunk", boom)

    episodes = [
        {"id": f"ep_{i}", "content": "real content here", "timestamp": "2026-09-01T10:00:00",
         "origin": "mcp"}
        for i in range(5)
    ]
    settings = SimpleNamespace(litellm_model="gpt-5.4-mini")
    out = asyncio.run(entity_extractor.extract(episodes, settings, cancel_check=lambda: True))
    assert out == []


def test_extract_is_unaffected_when_cancel_check_is_omitted(monkeypatch):
    """Every existing call site (no `cancel_check` kwarg) behaves exactly as
    before — the empty-content fast path needs no LLM call either way."""
    episodes = [{"id": "ep_1", "content": "   ", "timestamp": "2026-09-01T10:00:00",
                 "origin": "mcp"}]
    settings = SimpleNamespace(litellm_model="gpt-5.4-mini")
    out = asyncio.run(entity_extractor.extract(episodes, settings))
    assert len(out) == 1
    assert out[0]["episode_id"] == "ep_1"


# --------------------------------------------------------------------------- #
# entity_resolver.resolve's own cancel_check: stops the per-name judge loop
# --------------------------------------------------------------------------- #


def test_resolve_stops_the_per_name_loop_once_cancel_check_is_true(tmp_path):
    extracted = [{
        "episode_id": "ep_1",
        "entities": [
            {"name": "Alpha", "type": "concept", "confidence": 0.9, "source_episode": "ep_1"},
            {"name": "Beta", "type": "concept", "confidence": 0.9, "source_episode": "ep_1"},
        ],
        "relationships": [],
    }]
    settings = _settings(tmp_path / "memory")

    result = asyncio.run(
        entity_resolver.resolve(extracted, [], settings, cancel_check=lambda: True)
    )
    assert result["changes"] == []


# --------------------------------------------------------------------------- #
# Episode cap
# --------------------------------------------------------------------------- #


def test_default_episode_cap_is_25():
    from api.config import Settings

    assert Settings().sleep_max_episodes_per_cycle == 25


def test_episode_cap_truncates_the_batch_and_leaves_the_rest_queued(tmp_path, monkeypatch, tail_spy):
    ids = [f"ep_2026-09-01_{i:03d}" for i in range(5)]
    memory = _seed_git_bank(tmp_path, ids)

    seen_ids: list[str] = []

    async def fake_extract(episodes, settings, cancel_check=None, **_kw):
        seen_ids.extend(e["id"] for e in episodes)
        return [{
            "episode_id": ep["id"], "episode_timestamp": ep["timestamp"],
            "origin": "mcp",
            "entities": [{"name": ep["id"], "type": "concept", "confidence": 0.7,
                          "source_episode": ep["id"]}],
            "relationships": [],
        } for ep in episodes]

    async def fake_resolve(extracted_arg, existing, settings, cancel_check=None):
        return {"changes": [], "relationships": [], "episode_cooccurrences": {}}

    async def fake_prune(resolved, existing, settings):
        return list(resolved)

    async def fake_detect(changes, existing, settings, **kw):
        return []

    async def fake_commit(memory_path, message):
        return "deadbeef"

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

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)
    monkeypatch.setattr("api.services.entity_resolver.resolve", fake_resolve)
    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fake_detect)
    monkeypatch.setattr("api.services.conflict_resolver.resolve_and_prune", fake_prune)
    monkeypatch.setattr(git_service, "commit_changes", fake_commit)
    monkeypatch.setattr(git_service, "porcelain_status", fake_porcelain)
    monkeypatch.setattr("api.services.vector_index.SqliteVecIndexer", _FakeIndexer)

    asyncio.run(sleep_cycle.run(_settings(memory, sleep_max_episodes_per_cycle=2), "cycle-cap"))

    assert len(seen_ids) == 2, "only the capped batch reaches Stage 1"

    state = sleep_cycle.get_sleep_state()
    assert state.episode_cap == 2
    assert state.episodes_queued == 5
    assert state.episodes_total == 2
    assert "episode cap reached" in (state.progress or "")
    assert "2 of 5" in (state.progress or "")

    # The 3 episodes never handed to Stage 1 stay queued for the next cycle.
    remaining_ids = {e["id"] for e in sleep_cycle._get_unprocessed_episodes(memory)}
    assert remaining_ids == set(ids) - set(seen_ids)
    assert len(remaining_ids) == 3


def test_episode_cap_is_a_noop_when_the_queue_fits(tmp_path, monkeypatch, tail_spy):
    ids = ["ep_2026-09-01_001", "ep_2026-09-01_002"]
    memory = _seed_git_bank(tmp_path, ids)

    async def fake_extract(episodes, settings, cancel_check=None, **_kw):
        return []

    monkeypatch.setattr("api.services.entity_extractor.extract", fake_extract)

    asyncio.run(sleep_cycle.run(_settings(memory, sleep_max_episodes_per_cycle=25), "cycle-nocap"))

    state = sleep_cycle.get_sleep_state()
    assert state.episode_cap == 25
    assert state.episodes_queued == 2
    assert state.episodes_total == 2
    assert "episode cap" not in (state.progress or "")


# --------------------------------------------------------------------------- #
# Router: POST /sleep/cancel, and the new /sleep/status fields
# --------------------------------------------------------------------------- #


def test_cancel_endpoint_reports_not_running_when_idle():
    from fastapi.testclient import TestClient

    from api import main

    sleep_cycle.get_sleep_state().status = "idle"
    resp = TestClient(main.app).post("/sleep/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "not_running"
    assert body["cycleId"] is None


def test_cancel_endpoint_requests_cancellation_when_running_and_is_idempotent():
    from fastapi.testclient import TestClient

    from api import main

    state = sleep_cycle.get_sleep_state()
    state.status = "running"
    state.cycle_id = "sleep_router_test"
    state.cancel_requested = False
    try:
        client = TestClient(main.app)
        first = client.post("/sleep/cancel").json()
        assert first["status"] == "cancelling"
        assert first["cycleId"] == "sleep_router_test"
        assert "safe point" in first["message"]
        assert state.cancel_requested is True

        # Idempotent: calling again while still pending is safe and returns
        # the same shape.
        second = client.post("/sleep/cancel").json()
        assert second["status"] == "cancelling"
        assert second["cycleId"] == "sleep_router_test"
    finally:
        state.status = "idle"
        state.cycle_id = None
        state.cancel_requested = False


def test_sleep_status_exposes_cap_and_cancel_fields():
    from fastapi.testclient import TestClient

    from api import main

    state = sleep_cycle.get_sleep_state()
    state.episode_cap = 25
    state.episodes_queued = 30
    state.cancel_requested = True
    state.cancelled = False
    try:
        body = TestClient(main.app).get("/sleep/status").json()
        assert body["episodeCap"] == 25
        assert body["episodesQueued"] == 30
        assert body["cancelRequested"] is True
        assert body["cancelled"] is False
    finally:
        state.episode_cap = 0
        state.episodes_queued = 0
        state.cancel_requested = False
        state.cancelled = False


def test_sleep_status_is_observable_while_a_cycle_is_running():
    """G106 item 6: `/sleep/status` must be usable while a cycle is running
    — a cancel button needs to know one is in progress. The endpoint's own
    response shape was already correct (SleepState.status is never null —
    it's `"idle"` or `"running"`, always a str); this proves the wiring end
    to end against a `_state` that reports mid-cycle values, the same shape
    a real in-flight cycle would leave it in."""
    from fastapi.testclient import TestClient

    from api import main

    state = sleep_cycle.get_sleep_state()
    state.status = "running"
    state.cycle_id = "sleep_running_test"
    state.stage = 2
    state.last_engine = "claude-cli"
    state.episode_cap = 25
    state.episodes_queued = 10
    try:
        body = TestClient(main.app).get("/sleep/status").json()
        assert body["status"] == "running"
        assert body["cycleId"] == "sleep_running_test"
        assert body["stage"] == 2
        assert body["lastEngine"] == "claude-cli"
        assert body["episodeCap"] == 25
        assert body["episodesQueued"] == 10
    finally:
        state.status = "idle"
        state.cycle_id = None
        state.stage = 0
        state.last_engine = None
        state.episode_cap = 0
        state.episodes_queued = 0
