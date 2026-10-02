"""Consolidate reads everything (owner, 2026-09-29): a person-started run drains
the queue that was waiting when it began, in batches, each filed and committed.

Real git, real Stage 3 / Stage 5 / commit; the LLM and index boundaries are faked
(`drain_harness`). Each test says which line of the owner's ask it holds.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

from drain_harness import episode_ids, git, install, is_processed, seed_bank, settings, waiting

from api.services import agent_engine, engine_errors, engine_select, markdown_parser, sleep_cycle
from api.services import sleep_drain


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status = "idle"
    s.drain = None
    s.drain_run = False
    s.cancel_requested = False
    s.cancelled = False
    yield
    s.status = "idle"
    s.drain = None
    s.drain_run = False
    s.cancel_requested = False


def run_drain(memory, cid="sleep_drain_test", cap=3, **over):
    cfg = settings(memory, sleep_max_episodes_per_cycle=cap, **over)
    asyncio.run(sleep_cycle.run(cfg, cid, user_triggered=True, drain=True))
    return cfg, sleep_cycle.get_sleep_state()


def sleep_commits(memory) -> list[str]:
    return [s for s in git(memory, "log", "--format=%s", "--reverse").splitlines() if s.startswith("Sleep cycle")]


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_drain_over_three_batches_commits_three_times_and_marks_all_processed(tmp_path, monkeypatch):
    ids = episode_ids(7)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    _cfg, state = run_drain(memory, cap=3)

    assert rig.extract_batches == [ids[0:3], ids[3:6], ids[6:7]], "oldest first, batches of the cap"
    assert waiting(memory) == []
    for ep in ids:
        fm = markdown_parser.parse(memory / "episodes" / f"{ep}.md").frontmatter
        assert fm["processed"] is True and fm["processed_by"] == "sleep"
    subjects = sleep_commits(memory)
    assert len(subjects) == 3
    assert [s.split(" (")[-1] for s in subjects] == ["batch 1 of 3)", "batch 2 of 3)", "batch 3 of 3)"]
    assert state.status == "idle" and state.error is None
    ds = state.drain
    assert (ds.frozen, ds.filed, ds.requeued, ds.skipped, ds.batch, ds.batches) == (7, 7, 0, 0, 3, 3)
    assert ds.finished and not ds.active and ds.stop is None
    assert state.progress.startswith("Completed — 7 episode(s) filed in 3 batch(es)")
    assert git(memory, "status", "--porcelain").strip() == ""


def test_a_single_batch_drain_reads_like_a_plain_cycle(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(2))
    rig = install(monkeypatch)
    _cfg, state = run_drain(memory, cap=25)
    assert len(rig.extract_batches) == 1
    assert sleep_commits(memory) == [s for s in sleep_commits(memory) if "(batch" not in s]
    assert state.drain.batches == 1 and state.drain.filed == 2


def test_an_empty_queue_is_an_idle_cycle_not_a_drain(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [])
    rig = install(monkeypatch)
    _cfg, state = run_drain(memory)
    assert rig.extract_batches == [] and state.drain is None
    assert state.progress == "No unprocessed episodes"
    assert rig.tail.count("state") == 1


# --------------------------------------------------------------------------- #
# Stop cleanly on a plan limit
# --------------------------------------------------------------------------- #

PLAN_SENTENCE = "Your Claude plan hit its 5-hour limit — Sleep paused. Try again after 14:00."


def test_plan_stop_in_batch_two_keeps_batch_one_and_leaves_the_rest(tmp_path, monkeypatch):
    ids = episode_ids(7)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    from api.services import entity_resolver
    real = entity_resolver.resolve
    calls = {"n": 0}

    async def resolve_then_throttle(extracted, existing, settings_, cancel_check=None):
        calls["n"] += 1
        if calls["n"] == 2:
            agent_engine.trip_breaker(PLAN_SENTENCE, resets_at=1790000000)
            raise engine_errors.EngineThrottled("throttled", resets_at=1790000000)
        return await real(extracted, existing, settings_, cancel_check=cancel_check)

    monkeypatch.setattr("api.services.entity_resolver.resolve", resolve_then_throttle)

    _cfg, state = run_drain(memory, cap=3)

    assert [is_processed(memory, e) for e in ids] == [True] * 3 + [False] * 4
    assert len(sleep_commits(memory)) == 1
    ds = state.drain
    assert ds.stop.reason == "plan_limit" and ds.stop.sentence == PLAN_SENTENCE
    assert ds.stop.resets_at == 1790000000
    assert (ds.filed, ds.committed_batches) == (3, 1) and not ds.finished
    assert state.error is None, "a plan limit is a pause, not a failure"
    assert state.engine_detail == PLAN_SENTENCE
    assert state.progress == f"Stopped after batch 1 of 3 — {PLAN_SENTENCE}"
    assert rig.tail.count("state") == 1 and rig.tail.count("connectors") == 1
    assert "links" not in rig.tail, "the link backfill would meet the same limit"
    assert state.status == "idle"


def test_stage1_total_failure_by_throttle_is_a_plan_stop_not_a_failure(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def throttle_in_batch_two(batch_no, episodes):
        if batch_no == 2:
            agent_engine.trip_breaker(PLAN_SENTENCE, resets_at=1790000000)
            return [e["id"] for e in episodes]   # every episode "failed"

    rig.on_extract = throttle_in_batch_two
    _cfg, state = run_drain(memory, cap=3)

    ds = state.drain
    assert ds.stop.reason == "plan_limit" and ds.stop.sentence == PLAN_SENTENCE and ds.stop.resets_at == 1790000000
    assert state.error is None
    assert [is_processed(memory, e) for e in ids] == [True] * 3 + [False] * 3


def test_a_partial_throttle_in_a_committed_batch_stops_before_the_next_batch(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def partial_throttle(batch_no, episodes):
        if batch_no == 1:   # Stage 1 swallows the throttle per episode: one read, two requeued
            agent_engine.trip_breaker(PLAN_SENTENCE, resets_at=1790000000)
            return [e["id"] for e in episodes[1:]]

    rig.on_extract = partial_throttle
    _cfg, state = run_drain(memory, cap=3)

    assert len(rig.extract_batches) == 1, "no second batch is started against a tripped plan"
    ds = state.drain
    assert ds.stop.reason == "plan_limit" and ds.stop.resets_at == 1790000000
    assert (ds.filed, ds.requeued, ds.committed_batches) == (1, 2, 1)
    assert len(sleep_commits(memory)) == 1
    assert state.error is None


def test_a_partial_throttle_in_the_last_batch_is_a_finished_run_not_a_stop(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def partial_throttle_last(batch_no, episodes):
        if batch_no == 2:   # the final batch: one read, two requeued, the breaker tripped
            agent_engine.trip_breaker(PLAN_SENTENCE, resets_at=1790000000)
            return [e["id"] for e in episodes[1:]]

    rig.on_extract = partial_throttle_last
    _cfg, state = run_drain(memory, cap=3)

    ds = state.drain
    assert len(rig.extract_batches) == 2
    assert ds.stop is None and ds.finished, "nothing frozen is left waiting: the run finished"
    assert (ds.filed, ds.requeued, ds.committed_batches) == (4, 2, 2)
    assert state.progress.startswith("Completed — 4 episode(s) filed in 2 batch(es)")
    assert "links" in rig.tail, "a finished run keeps its link backfill"
    assert state.error is None


def test_a_batch_can_stop_only_for_ids_that_are_still_waiting(tmp_path, monkeypatch):
    """Not the last batch, but the ids after it were all read elsewhere meanwhile: the
    tripped breaker has nothing left to protect, so it is not a stop either."""
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def throttle_and_others_read_the_rest(batch_no, episodes):
        if batch_no == 1:
            agent_engine.trip_breaker(PLAN_SENTENCE, resets_at=1790000000)
            for other in ids[3:]:   # another writer files them before the batch's commit
                path = memory / "episodes" / f"{other}.md"
                parsed = markdown_parser.parse(path)
                fm = dict(parsed.frontmatter)
                fm["processed"] = True
                markdown_parser.write(path, fm, parsed.body)

    rig.on_extract = throttle_and_others_read_the_rest
    _cfg, state = run_drain(memory, cap=3)

    ds = state.drain
    assert ds.stop is None and ds.finished
    assert len(rig.extract_batches) == 1 and ds.skipped == 3


def test_a_batch_that_extracts_nothing_ends_the_drain_with_the_engine_message(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def nothing_in_batch_two(batch_no, episodes):
        if batch_no == 2:
            return [e["id"] for e in episodes]

    rig.on_extract = nothing_in_batch_two
    _cfg, state = run_drain(memory, cap=3)

    assert len(rig.extract_batches) == 2
    ds = state.drain
    assert ds.stop.reason == "engine" and "Stage 1 extracted nothing" in ds.stop.sentence
    assert state.error and "Stage 1 extracted nothing" in state.error
    assert [is_processed(memory, e) for e in ids] == [True] * 3 + [False] * 6


# --------------------------------------------------------------------------- #
# Cancel
# --------------------------------------------------------------------------- #


def test_cancel_before_stage5_keeps_finished_batches_and_drops_the_inflight_one(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def cancel_in_batch_two(batch_no, episodes):
        if batch_no == 2:
            sleep_cycle.request_cancel()

    rig.on_extract = cancel_in_batch_two
    _cfg, state = run_drain(memory, cap=3)

    assert len(rig.extract_batches) == 2, "batch 3 is never started"
    assert [is_processed(memory, e) for e in ids] == [True] * 3 + [False] * 6
    assert len(sleep_commits(memory)) == 1
    ds = state.drain
    assert ds.stop.reason == "cancelled" and ds.filed == 3
    assert state.cancelled is True and state.cancel_requested is False and state.error is None
    assert state.progress.startswith("Cancelled — 3 of 9 filed")
    # the discarded batch left no trace in the counts
    assert sum(state.read_by_origin.values()) == 3
    assert state.episodes_total == 3
    assert rig.tail.count("state") == 1
    assert git(memory, "status", "--porcelain").strip() == ""


def test_cancel_after_stage5_began_commits_the_batch_then_stops(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def cancel_as_batch_two_writes(generate_no):
        if generate_no == 2:
            sleep_cycle.request_cancel()

    rig.on_generate = cancel_as_batch_two_writes
    _cfg, state = run_drain(memory, cap=3)

    assert len(rig.extract_batches) == 2
    assert [is_processed(memory, e) for e in ids] == [True] * 6 + [False] * 3
    assert len(sleep_commits(memory)) == 2, "a batch already writing commits — the bank is never left dirty"
    assert state.drain.stop.reason == "cancelled" and state.drain.filed == 6
    assert state.cancelled is True
    assert git(memory, "status", "--porcelain").strip() == ""


def test_a_cancel_reserved_before_run_starts_stops_before_any_batch(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(4))
    rig = install(monkeypatch)
    sleep_cycle.reserve_cycle("sleep_reserved", drain=True)
    assert sleep_cycle.request_cancel() == (True, "sleep_reserved")
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=2), "sleep_reserved",
                                user_triggered=True, drain=True))
    state = sleep_cycle.get_sleep_state()
    assert rig.extract_batches == [] and state.drain.stop.reason == "cancelled"
    assert waiting(memory) == episode_ids(4)


# --------------------------------------------------------------------------- #
# Scheduled runs never drain (ruling 4)
# --------------------------------------------------------------------------- #


def test_a_run_called_without_drain_is_still_one_batch(tmp_path, monkeypatch):
    """The default stays False: a caller that never asks for a drain gets the plain cycle it
    always got (only the scheduler and the trigger route pass ``drain=True`` now)."""
    ids = episode_ids(5)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=2), "sleep_plain", user_triggered=False))

    assert rig.extract_batches == [ids[0:2]]
    assert sleep_cycle.get_sleep_state().drain is None
    assert len(waiting(memory)) == 3
    assert inspect.signature(sleep_cycle.run).parameters["drain"].default is False


def test_the_scheduler_asks_for_a_drain_on_both_entry_points(tmp_path, monkeypatch):
    """TODO ruling 16 (owner 2026-09-30): a scheduled run reads everything waiting too. Ruling 4
    is untouched — it still passes ``user_triggered=False``, so no plan engine can be chosen."""
    from datetime import datetime, timedelta

    from api.services import sleep_debt, sleep_scheduler
    import asyncio as _a

    seen = []

    async def fake_run(settings_, cycle_id, **kw):
        seen.append(kw)

    async def fake_debt(memory_path, settings_=None):
        return SimpleNamespace(unprocessed_count=3, readable_count=3, parked_count=0,
                               newest_unprocessed_at=datetime.now() - timedelta(hours=1))

    monkeypatch.setattr(sleep_cycle, "run", fake_run)
    monkeypatch.setattr(sleep_debt, "compute", fake_debt)
    cfg = SimpleNamespace(memory_path=tmp_path)
    _a.run(sleep_scheduler._run_if_idle(cfg))
    _a.run(sleep_scheduler._run_after_intake_if_settled(cfg))
    assert seen == [{"user_triggered": False, "drain": True}] * 2


# --------------------------------------------------------------------------- #
# The frozen list
# --------------------------------------------------------------------------- #


def test_frozen_list_ignores_episodes_that_arrive_mid_drain(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def capture_arrives(batch_no, episodes):
        if batch_no == 1:
            markdown_parser.write(
                memory / "episodes" / "ep_2026-09-02_000.md",
                {"id": "ep_2026-09-02_000", "processed": False, "source": "mcp",
                 "timestamp": "2026-09-02T09:00:00"},
                "Captured while the run was reading.")

    rig.on_extract = capture_arrives
    _cfg, state = run_drain(memory, cap=3)

    assert [i for b in rig.extract_batches for i in b] == ids, "the newcomer is never read by this run"
    assert waiting(memory) == ["ep_2026-09-02_000"]
    assert state.drain.frozen == 6 and state.drain.filed == 6 and state.drain.arrived_since == 1
    assert state.drain.finished


def test_an_episode_marked_processed_elsewhere_is_skipped_and_counted(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def someone_else_reads_one(batch_no, episodes):
        if batch_no == 1:   # cicada_mark_processed, from an agent
            path = memory / "episodes" / f"{ids[4]}.md"
            parsed = markdown_parser.parse(path)
            parsed.frontmatter.update(processed=True, processed_by="agent")
            markdown_parser.write(path, parsed.frontmatter, parsed.body)

    rig.on_extract = someone_else_reads_one
    _cfg, state = run_drain(memory, cap=3)

    assert ids[4] not in [i for b in rig.extract_batches for i in b]
    ds = state.drain
    assert (ds.filed, ds.skipped, ds.frozen) == (5, 1, 6)
    assert ds.batches == 2 and ds.finished
    assert markdown_parser.parse(memory / "episodes" / f"{ids[4]}.md").frontmatter["processed_by"] == "agent"


def test_the_last_planned_batch_being_read_elsewhere_still_gets_its_decay_once(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def others_read_the_rest(batch_no, episodes):
        if batch_no == 1:
            for ep in ids[3:]:
                path = memory / "episodes" / f"{ep}.md"
                parsed = markdown_parser.parse(path)
                parsed.frontmatter.update(processed=True, processed_by="agent")
                markdown_parser.write(path, parsed.frontmatter, parsed.body)

    rig.on_extract = others_read_the_rest
    _cfg, state = run_drain(memory, cap=3)

    # batch 1 was planned as "not last"; nothing was left for a second batch, so a
    # decay-only pass runs once — decay and the page reads still happen once per drain.
    assert rig.prune_calls == [{"decay": False}, {}]
    assert rig.link_calls == 1
    assert state.drain.finished and state.drain.skipped == 3 and state.drain.filed == 3
    assert len(rig.extract_batches) == 1, "the finishing pass reads no episode"


# --------------------------------------------------------------------------- #
# Status counts
# --------------------------------------------------------------------------- #


def test_status_counts_are_correct_at_every_step(tmp_path, monkeypatch):
    from api.routers import sleep as sleep_router

    ids = episode_ids(7)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    cfg = settings(memory, sleep_max_episodes_per_cycle=3)
    seen = []

    async def sample(batch_no, episodes):
        body = (await sleep_router.sleep_status(settings=cfg)).model_dump(by_alias=True)
        seen.append(body)

    rig.on_extract = sample
    asyncio.run(sleep_cycle.run(cfg, "sleep_counts", user_triggered=True, drain=True))
    final = asyncio.run(sleep_router.sleep_status(settings=cfg)).model_dump(by_alias=True)

    assert [(b["drain"]["batch"], b["drain"]["batches"], b["drain"]["filed"], b["drain"]["frozen"]) for b in seen] == [
        (1, 3, 0, 7), (2, 3, 3, 7), (3, 3, 6, 7)]
    assert [b["episodesTotal"] for b in seen] == [3, 6, 7], "attempted so far"
    assert all(b["episodesQueued"] == 7 and b["episodeCap"] == 3 for b in seen)
    assert [b["episodesProcessed"] for b in seen] == [0, 3, 6], "the running sum, never a batch's own"
    assert [sum(b["readByOrigin"].values()) for b in seen] == [0, 3, 6]
    assert all(b["queueByOrigin"] == {"claude-code": 7} for b in seen)
    assert [b["entitiesCreated"] for b in seen] == [0, 3, 6]
    assert final["status"] == "idle"
    assert final["drain"]["filed"] == 7 and final["drain"]["finished"] is True and final["drain"]["active"] is False
    assert final["episodesProcessed"] == 7 and final["entitiesCreated"] == 7
    assert sum(final["readByOrigin"].values()) == 7 and final["episodesTotal"] == 7 == final["episodesQueued"]
    assert final["drain"]["stop"] is None and final["drain"]["arrivedSince"] == 0


def test_stage_1_progress_is_per_batch_not_per_drain(tmp_path, monkeypatch):
    ids = episode_ids(7)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    seen = []

    async def sample(batch_no, episodes):
        state = sleep_cycle.get_sleep_state()
        seen.append((state.batch_total, state.stage1_progress, sleep_cycle.progress_pct(state)))

    rig.on_extract = sample
    run_drain(memory, cap=3)
    assert seen == [(3, 0, 0), (3, 0, 0), (1, 0, 0)], "each batch starts its own Stage-1 count from zero"


def test_a_plain_cycle_reports_no_drain_block(tmp_path, monkeypatch):
    from api.routers import sleep as sleep_router

    memory = seed_bank(tmp_path, episode_ids(2))
    install(monkeypatch)
    cfg = settings(memory, sleep_max_episodes_per_cycle=25)
    asyncio.run(sleep_cycle.run(cfg, "sleep_plain"))
    body = asyncio.run(sleep_router.sleep_status(settings=cfg)).model_dump(by_alias=True)
    assert body["drain"] is None and body["episodesProcessed"] == 2


def test_a_content_failure_gets_one_more_try_then_parks(tmp_path, monkeypatch):
    """Sleep page v5: a conversation that fails for its own reasons goes first in the very next
    batch (its one more try); a second failure parks it. It stays waiting (``processed: false``),
    a later run skips it, and the run itself is finished, not failed."""
    from api.services import sleep_parked

    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.fail_ids = {ids[1]}
    _cfg, state = run_drain(memory, cap=3)

    assert rig.extract_batches == [ids[0:3], [ids[1], ids[3], ids[4]], [ids[5]]], "the retry leads batch 2"
    ds = state.drain
    assert (ds.filed, ds.requeued) == (5, 1) and ds.finished and ds.stop is None
    assert ds.parked == {ids[1]: "other"} and ds.attempts[ids[1]] == 2
    assert waiting(memory) == [ids[1]]
    assert sleep_parked.ids(memory) == {ids[1]}
    assert "1 episode(s) requeued" in state.progress

    # The next run never re-reads it, and says nothing is left to read.
    rig.extract_batches.clear()
    run_drain(memory, cap=3)
    assert rig.extract_batches == []


# --------------------------------------------------------------------------- #
# Engine, bank and failures
# --------------------------------------------------------------------------- #


def test_engine_is_resolved_once_and_pinned_for_all_batches(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(7))
    install(monkeypatch)
    real = engine_select.resolve_settings
    calls = []

    async def counting(settings_, *a, **k):
        calls.append(k.get("user_triggered"))
        return await real(settings_, *a, **k)

    monkeypatch.setattr(engine_select, "resolve_settings", counting)
    run_drain(memory, cap=3)
    assert calls == [True]


def test_bank_switch_between_batches_stops_with_bank_switched(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    cfg = settings(memory, sleep_max_episodes_per_cycle=3)

    async def switch(batch_no, episodes):
        cfg.memory_path = tmp_path / "another-bank"

    rig.on_extract = switch
    asyncio.run(sleep_cycle.run(cfg, "sleep_switch", user_triggered=True, drain=True))
    state = sleep_cycle.get_sleep_state()

    assert len(rig.extract_batches) == 1
    assert state.drain.stop.reason == "bank_switched" and state.error
    assert [is_processed(memory, e) for e in ids] == [True] * 3 + [False] * 3


def test_a_raise_outside_a_batch_releases_the_bank_guard(tmp_path, monkeypatch):
    from api.routers import banks

    memory = seed_bank(tmp_path, episode_ids(3))
    install(monkeypatch)

    async def boom(*_a, **_k):
        raise RuntimeError("engine registry unreadable")

    monkeypatch.setattr(engine_select, "resolve_settings", boom)
    _cfg, state = run_drain(memory)

    assert state.status == "idle" and state.drain_run is False
    assert state.error.startswith("RuntimeError") and state.drain.active is False
    assert state.drain.stop.reason == "error"
    banks._refuse_switch_during_drain()   # no 409


def test_a_batch_that_raises_after_writing_but_before_its_commit_keeps_the_tail_off_the_dirty_tree(
    tmp_path, monkeypatch,
):
    """Batch 1 commits clean; batch 2 raises in Stage 5 with pages on disk. The
    tail's guard must read batch 2 — not batch 1's clean commit — so no poll's
    `git add -A` sweeps the half-written pages."""
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def boom_after_writes(generate_no):
        if generate_no == 2:
            raise RuntimeError("disk full")

    rig.on_generate = boom_after_writes
    _cfg, state = run_drain(memory, cap=3)

    assert state.drain.stop.reason == "error" and state.error.startswith("RuntimeError")
    assert len(sleep_commits(memory)) == 1 and git(memory, "status", "--porcelain").strip() != ""
    assert "expiry" not in rig.tail and "connectors" not in rig.tail and "feeds" not in rig.tail
    assert "state" in rig.tail and "logos" in rig.tail, "the commit-alone steps still run"


def test_sleep_drain_unit_helpers():
    assert sleep_drain.batches_for(0, 25) == 0 and sleep_drain.batches_for(287, 25) == 12
    assert sleep_drain.batches_for(25, 25) == 1 and sleep_drain.batches_for(26, 25) == 2
    ids = ["a", "b", "c", "d", "e"]
    assert sleep_drain.next_batch(ids, set(ids), set(), 2) == (["a", "b"], 3)
    assert sleep_drain.next_batch(ids, {"b", "c", "e"}, {"b"}, 2) == (["c", "e"], 0)
    assert sleep_drain.next_batch(ids, set(), set(), 2) == ([], 0)
    throttled = sleep_drain.classify(engine_errors.EngineThrottled("x", resets_at=5), "vendor sentence", 9)
    assert (throttled.reason, throttled.sentence, throttled.resets_at) == ("plan_limit", "vendor sentence", 5)
    assert sleep_drain.classify(engine_errors.EngineOverage("over"), None, 9).resets_at == 9
    assert sleep_drain.classify(engine_errors.EngineExhausted("spent"), None, None).sentence == "spent"
    assert sleep_drain.classify(engine_errors.EngineUnavailable("signed out")).reason == "engine"
    assert sleep_drain.classify(engine_errors.EngineModelNotFound("nope")).reason == "engine"
    assert sleep_drain.classify(ValueError("bad")).reason == "error"


# --------------------------------------------------------------------------- #
# The write window (G177): what is refused, and what commits alone, mid-run
# --------------------------------------------------------------------------- #


def test_a_drain_holds_the_bank_only_while_a_batch_can_write(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    seen: dict[str, list[bool]] = {"stage1": [], "stage5": []}

    async def stage1(batch_no, episodes):
        seen["stage1"].append((sleep_cycle.get_sleep_state().status == "running", sleep_cycle.is_writing()))

    async def stage5(batch_no):
        seen["stage5"].append(sleep_cycle.is_writing())

    rig.on_extract, rig.on_generate = stage1, stage5
    run_drain(memory, cap=3)

    assert seen["stage1"] == [(True, False), (True, False)], "reading episodes holds no page"
    assert seen["stage5"] == [True, True], "Stage 5 is the write window"
    assert not sleep_cycle.is_writing(), "an idle Sleep holds nothing"


def test_a_plain_cycle_still_holds_the_bank_for_its_whole_run(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(2))
    rig = install(monkeypatch)
    seen = []

    async def stage1(batch_no, episodes):
        seen.append(sleep_cycle.is_writing())

    rig.on_extract = stage1
    asyncio.run(sleep_cycle.run(settings(memory), "sleep_plain_test", user_triggered=False))
    assert seen == [True]


def test_an_agent_claim_between_batches_lands_under_its_own_author_not_a_batch_commit(tmp_path, monkeypatch):
    from api.services import agent_commits, agentic_write

    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    def page(mem):
        markdown_parser.write(
            mem / "entities" / "alpha-project.md",
            {"name": "alpha-project", "type": "project", "status": "active", "confidence": 0.8},
            "# alpha-project\n")

    page(memory)
    git(memory, "add", "-A")
    git(memory, "commit", "-q", "-m", "seed page")

    async def agent_writes_during_batch_two_reading(batch_no, episodes):
        if batch_no == 2:
            assert not sleep_cycle.is_writing(), "the probe an agent asks says the bank is free"
            result = agentic_write.write_claim(
                memory, "alpha-project", "uses", "sqlite-vec", observer="agent", authored_by="claude-code")
            # A stdio agent is another process; off the loop stands in for that
            # (`commit_write` refuses to run inside one).
            await asyncio.to_thread(
                agent_commits.commit_write, memory, subject="Agent write",
                lines=[f"{result['path']}: updated"], paths=[result["path"]],
                author="claude-code", session=None)

    rig.on_extract = agent_writes_during_batch_two_reading
    run_drain(memory, cap=3)

    agent_commit = git(memory, "log", "--format=%H", "--grep=^Agent write").split()
    assert len(agent_commit) == 1
    assert "Cicada-Author: claude-code" in git(memory, "log", "-1", "--format=%B", agent_commit[0])
    assert git(memory, "show", "--name-only", "--format=", agent_commit[0]).split() == ["entities/alpha-project.md"]
    for commit in git(memory, "log", "--format=%H", "--grep=^Sleep cycle").split():
        # Sleep's own decay may touch the page (and graph_edges.yaml derives from the
        # claim); the claim's own line must never be ADDED by a Sleep commit.
        diff = git(memory, "show", "--format=", "-U0", commit, "--", "entities/alpha-project.md")
        assert not any(ln.startswith("+") and "sqlite-vec" in ln for ln in diff.splitlines()), \
            "the agent's claim rode a Sleep commit"
    assert git(memory, "status", "--porcelain").strip() == ""
