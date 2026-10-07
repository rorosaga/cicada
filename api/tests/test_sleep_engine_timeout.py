"""G171/G163: pause positive transients; park repeated per-episode failures."""
from __future__ import annotations

import asyncio
from collections import Counter
from types import SimpleNamespace

import pytest

from drain_harness import episode_ids, git, install, seed_bank, settings, waiting
from api.config import Settings
from api.services import (
    engine_errors, entity_extractor, markdown_parser, providers, sleep_cycle,
    sleep_drain, sleep_paused, sleep_parked, sleep_runs,
)


@pytest.fixture(autouse=True)
def idle():
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    yield
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False


def fake_engine(monkeypatch, ids, failures):
    """Use the real extraction fan-out and call retry, with no subprocess or model."""
    real_extract = entity_extractor.extract
    rig = install(monkeypatch)
    monkeypatch.setattr(entity_extractor, "extract", real_extract)
    calls, backoffs = Counter(), []
    real_sleep = asyncio.sleep

    async def sleep(delay):
        backoffs.append(delay)
        await real_sleep(0)

    async def complete(*, messages, **kw):
        ep_id = next(i for i in ids if i in messages[-1]["content"])
        calls[ep_id] += 1
        failure = failures.get(ep_id)
        if isinstance(failure, BaseException):
            raise failure
        if failure is not None and (failure == "persistent" or calls[ep_id] == 1):
            raise engine_errors.EngineTimeout("engine call exceeded its time budget")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"entities": [], "relationships": []}'))])

    monkeypatch.setattr(providers, "resolve_llm_fn", lambda *a, **kw: complete)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    return rig, calls, backoffs


def run(memory, cap=2, **kw):
    asyncio.run(sleep_cycle.run(
        settings(memory, sleep_max_episodes_per_cycle=cap), "sleep_timeout",
        user_triggered=True, drain=True, **kw))
    return sleep_cycle.get_sleep_state()


def test_one_timeout_retries_the_call_and_files_the_batch(tmp_path, monkeypatch):
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    rig, calls, backoffs = fake_engine(monkeypatch, ids, {ids[0]: "once"})
    state = run(memory)
    assert calls == {ids[0]: 2, ids[1]: 1}
    assert backoffs == [10]
    assert waiting(memory) == [] and sleep_paused.get_paused(memory) is None
    assert state.error is None and state.drain.finished
    assert rig.generate_calls == 1


@pytest.mark.parametrize("mixed", [False, True])
def test_persistent_timeout_discards_only_current_batch_and_continue_keeps_frozen_ids(
        tmp_path, monkeypatch, mixed):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    failing = [ids[3]] if mixed else ids[2:4]
    failures = dict.fromkeys(failing, "persistent")
    rig, calls, backoffs = fake_engine(monkeypatch, ids, failures)
    state = run(memory)
    rec = sleep_paused.get_paused(memory)
    assert rec is not None and rec["reason"] == "engine"
    assert rec["can_continue"] and rec["run_id"] == "sleep_timeout"
    assert rec["frozen_ids"] == ids and rec["filed"] == 2 and rec["committed_batches"] == 1
    assert "timed out" in rec["sentence"]
    assert rec["attempts"] == {} and sleep_parked.ids(memory) == set()
    assert rec["timeout_attempts"] == dict.fromkeys(failing, 1)
    assert rec["engine_kind"] == "transient"
    assert rec["resets_at"] is None and not (rec.get("auto_continue") or {}).get("armed", False)
    assert state.error is None and state.status == "idle" and not sleep_cycle.is_writing()
    assert waiting(memory) == ids[2:]
    assert all(calls[i] == 2 for i in failing) and len(backoffs) == len(failing)
    assert rig.generate_calls == 1 and git(memory, "status", "--porcelain") == ""
    assert not (memory / "entities" / f"e-{ids[2]}.md").exists()
    assert sleep_runs.get(memory, "sleep_timeout")["state"] == "paused"

    # A new arrival is outside the frozen run, including after Continue.
    new_id = "ep_2026-09-02_000"
    markdown_parser.write(memory / "episodes" / f"{new_id}.md",
                          {"id": new_id, "processed": False, "source": "mcp"}, "alpha-project")
    git(memory, "add", "episodes")
    git(memory, "commit", "-qm", "synthetic arrival")
    failures.clear()
    state = run(memory, continue_from=rec)
    assert state.drain.drain_id == "sleep_timeout" and state.drain.frozen_ids == ids
    assert state.drain.filed == 6 and state.drain.finished and state.error is None
    assert waiting(memory) == [new_id] and sleep_paused.get_paused(memory) is None
    assert sleep_runs.get(memory, "sleep_timeout")["state"] == "finished"


@pytest.mark.parametrize("count", [1, 6])
def test_same_episode_times_out_again_on_continue_is_parked_and_healthy_work_finishes(tmp_path, monkeypatch, count):
    ids = episode_ids(count)
    memory = seed_bank(tmp_path, ids)
    bad_id = ids[3] if count == 6 else ids[0]
    _, calls, _ = fake_engine(monkeypatch, ids, {bad_id: "persistent"})
    run(memory)
    rec = sleep_paused.get_paused(memory)
    assert rec is not None and rec["timeout_attempts"] == {bad_id: 1}
    # Load from disk again, as after a process restart; no in-memory observation is needed.
    sleep_paused._cache.clear()
    state = run(memory, continue_from=sleep_paused.load(memory))
    assert state.drain.finished and state.error is None
    assert state.drain.filed == count - 1 and waiting(memory) == [bad_id]
    assert state.drain.parked == {bad_id: "timed_out"}
    assert sleep_parked.valid(memory)[bad_id]["attempts"] == 2
    assert calls[bad_id] == 4
    if count == 6:
        assert calls[ids[2]] == 2, "one interrupted read, one successful reread"
    assert sleep_paused.get_paused(memory) is None
    assert git(memory, "status", "--porcelain") == ""


def test_timeouts_move_to_different_episodes_across_continues_remain_engine_pauses(tmp_path, monkeypatch):
    ids = episode_ids(3)
    memory = seed_bank(tmp_path, ids)
    failures = {ids[0]: "persistent"}
    fake_engine(monkeypatch, ids, failures)
    run(memory, cap=3)
    rec = sleep_paused.get_paused(memory)
    failures.clear()
    failures[ids[1]] = "persistent"
    state = run(memory, cap=3, continue_from=rec)
    rec = sleep_paused.get_paused(memory)
    assert rec is not None and rec["reason"] == "engine" and rec["filed"] == 0
    assert rec["timeout_attempts"] == {ids[0]: 1, ids[1]: 1}
    assert rec["attempts"] == {} and sleep_parked.ids(memory) == set()
    assert state.error is None and waiting(memory) == ids


def test_two_repeated_timeouts_each_park_even_without_a_healthy_neighbor(tmp_path, monkeypatch):
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    _, calls, _ = fake_engine(monkeypatch, ids, dict.fromkeys(ids, "persistent"))
    run(memory)
    state = run(memory, continue_from=sleep_paused.get_paused(memory))
    assert sleep_paused.get_paused(memory) is None
    assert state.drain.finished and state.drain.parked == dict.fromkeys(ids, "timed_out")
    assert waiting(memory) == ids and state.error is None
    assert all(v["attempts"] == 2 for v in sleep_parked.valid(memory).values())
    assert calls == dict.fromkeys(ids, 4)


@pytest.mark.parametrize("concurrency", [1, 3])
def test_two_persistent_timeouts_in_a_mixed_batch_each_park_and_drain_finishes(tmp_path, monkeypatch, concurrency):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    bad = ids[2:4]
    _, calls, _ = fake_engine(monkeypatch, ids, dict.fromkeys(bad, "persistent"))
    monkeypatch.setattr(entity_extractor, "MAX_CONCURRENCY", concurrency)
    state = run(memory, cap=3)
    for _ in range(3):
        rec = sleep_paused.get_paused(memory)
        if rec is None:
            break
        state = run(memory, cap=3, continue_from=rec)
    assert state.drain.finished and state.error is None
    assert state.drain.parked == dict.fromkeys(bad, "timed_out")
    assert state.drain.filed == 4 and waiting(memory) == bad
    assert sleep_paused.get_paused(memory) is None
    assert all(sleep_parked.valid(memory)[i]["attempts"] >= 2 for i in bad)
    assert git(memory, "status", "--porcelain") == ""


@pytest.mark.parametrize("count", [2, 6])
def test_unnamed_conversation_rejection_retries_then_parks_without_discarding_healthy_reads(
        tmp_path, monkeypatch, count):
    ids = episode_ids(count)
    memory = seed_bank(tmp_path, ids)
    # With two inputs the rejected input retries alone, after a healthy read
    # demonstrably worked in this run. An initial all-failing singleton cannot
    # provide that evidence and is covered by the engine-outage test below.
    bad = ids[3] if count == 6 else ids[1]
    _, calls, backoffs = fake_engine(monkeypatch, ids, {bad: engine_errors.EngineFailed("your prompt was flagged")})
    state = run(memory)
    assert state.drain.finished and state.error is None
    assert state.drain.parked == {bad: "other"} and state.drain.filed == count - 1
    assert sleep_paused.get_paused(memory) is None and waiting(memory) == [bad]
    assert sleep_parked.valid(memory)[bad]["attempts"] == 2
    assert calls == {bad: 4, **{i: 1 for i in ids if i != bad}}
    assert backoffs == [2, 2]
    assert git(memory, "status", "--porcelain") == ""


@pytest.mark.parametrize("count", [1, 6])
@pytest.mark.parametrize("concurrency", [1, 3])
def test_all_unnamed_calls_fail_pauses_engine_without_charging_or_parking(
        tmp_path, monkeypatch, count, concurrency):
    ids = episode_ids(count)
    memory = seed_bank(tmp_path, ids)
    _, calls, _ = fake_engine(monkeypatch, ids, dict.fromkeys(
        ids, engine_errors.EngineFailed("unknown")))
    monkeypatch.setattr(entity_extractor, "MAX_CONCURRENCY", concurrency)
    state = run(memory)
    rec = sleep_paused.get_paused(memory)
    assert rec is not None and rec["reason"] == "engine"
    assert rec["engine_kind"] == "needs_fix" and rec["can_continue"]
    assert rec["attempts"] == {} and rec["timeout_attempts"] == {}
    assert rec["filed"] == 0 and rec["committed_batches"] == 0
    assert rec["frozen_ids"] == ids and not state.drain.finished
    assert state.drain.parked == {} and sleep_parked.ids(memory) == set()
    assert calls == dict.fromkeys(ids[:2], 2), "no id beyond the first batch called"
    assert waiting(memory) == ids and git(memory, "status", "--porcelain") == ""
    assert sleep_runs.get(memory, "sleep_timeout")["state"] == "paused"


def test_unnamed_engine_outage_after_a_healthy_batch_does_not_charge_fresh_ids(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    _, calls, _ = fake_engine(monkeypatch, ids, dict.fromkeys(
        ids[2:], engine_errors.EngineFailed("unknown")))
    state = run(memory)
    rec = sleep_paused.get_paused(memory)
    assert rec is not None and rec["reason"] == "engine" and rec["engine_kind"] == "needs_fix"
    assert rec["filed"] == 2 and rec["committed_batches"] == 1
    assert rec["attempts"] == {} and state.drain.parked == {}
    assert sleep_parked.ids(memory) == set() and waiting(memory) == ids[2:]
    assert calls == {**dict.fromkeys(ids[:2], 1), **dict.fromkeys(ids[2:4], 2)}
    assert git(memory, "status", "--porcelain") == ""


def test_all_unnamed_retries_need_a_healthy_read_in_the_batch_unless_alone(tmp_path, monkeypatch):
    ids = episode_ids(3)
    memory = seed_bank(tmp_path, ids)
    _, calls, _ = fake_engine(monkeypatch, ids, dict.fromkeys(
        ids[1:], engine_errors.EngineFailed("unknown")))
    state = run(memory, cap=3)
    rec = sleep_paused.get_paused(memory)
    assert rec is not None and rec["reason"] == "engine" and rec["engine_kind"] == "needs_fix"
    assert rec["filed"] == 1 and rec["attempts"] == dict.fromkeys(ids[1:], 1)
    assert state.drain.parked == {} and sleep_parked.ids(memory) == set()
    assert calls == {ids[0]: 1, **dict.fromkeys(ids[1:], 4)}
    assert waiting(memory) == ids[1:] and git(memory, "status", "--porcelain") == ""


def test_doomed_batch_does_not_start_waiting_stage_one_calls(tmp_path, monkeypatch):
    ids = episode_ids(4)
    memory = seed_bank(tmp_path, ids)
    _, calls, _ = fake_engine(monkeypatch, ids, {ids[0]: "persistent"})
    monkeypatch.setattr(entity_extractor, "MAX_CONCURRENCY", 1)
    state = run(memory, cap=4)
    assert calls == {ids[0]: 2}, "never start reads that will be discarded"
    assert state.drain.live.skipped == set(ids[1:])
    assert waiting(memory) == ids and sleep_parked.ids(memory) == set()
    state = run(memory, cap=4, continue_from=sleep_paused.get_paused(memory))
    assert state.drain.finished and state.drain.parked == {ids[0]: "timed_out"}
    assert calls == {ids[0]: 4, **dict.fromkeys(ids[1:], 1)}


def test_connection_loss_keeps_its_trimmed_diagnosis():
    diagnosis = "temporary CLI configuration failure " + "x" * 400
    stop = sleep_drain.classify(engine_errors.EngineConnectionLost(diagnosis))
    assert stop.reason == "engine" and stop.transient
    assert diagnosis[:300] in stop.sentence and diagnosis not in stop.sentence


def test_engine_kind_is_typed_on_the_wire_and_moves_the_sleep_sync_component(tmp_path):
    from api.models.schemas import SleepPaused
    from api.services import sync_service

    memory = seed_bank(tmp_path, episode_ids(2))
    ds = sleep_drain.DrainState("sleep_kind", frozen_ids=episode_ids(2))
    transient = sleep_paused.build(ds, phase="paused", stop=sleep_drain.classify(engine_errors.EngineTimeout("slow")))
    sleep_paused.save(memory, transient)
    before = sync_service.components(memory)["sleep"]
    assert SleepPaused.model_validate(sleep_paused.to_wire(transient)).model_dump(by_alias=True)["engineKind"] == "transient"
    needs_fix = sleep_paused.build(ds, phase="paused", stop=sleep_drain.classify(engine_errors.EngineUnavailable("sign in")))
    sleep_paused.save(memory, needs_fix)
    assert SleepPaused.model_validate(sleep_paused.to_wire(needs_fix)).engine_kind == "needs_fix"
    assert sync_service.components(memory)["sleep"] != before


def test_explicit_scheduled_cli_transient_pause_is_replaceable_after_six_hours(tmp_path):
    ds = sleep_drain.DrainState("sleep_schedule", frozen_ids=episode_ids(2), started_by="schedule")
    rec = sleep_paused.build(ds, phase="paused", paused_at=1000,
                             stop=sleep_drain.classify(engine_errors.EngineTimeout("slow")))
    assert not sleep_paused.schedule_may_replace(rec, now=1000 + sleep_paused.ENGINE_RETRY_S - 1)
    assert sleep_paused.schedule_may_replace(rec, now=1000 + sleep_paused.ENGINE_RETRY_S)


@pytest.mark.parametrize("error", [engine_errors.EngineTimeout, engine_errors.EngineProtocolError,
                                  engine_errors.EngineConnectionLost])
def test_a_transient_error_escaping_a_later_stage_pauses(tmp_path, monkeypatch, error):
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    install(monkeypatch)

    async def fail(*a, **kw):
        raise error("temporary engine failure")

    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fail)
    state = run(memory)
    rec = sleep_paused.get_paused(memory)
    assert rec is not None and rec["reason"] == "engine" and rec["can_continue"]
    assert rec["frozen_ids"] == ids and rec["filed"] == 0
    assert state.error is None and waiting(memory) == ids
    assert git(memory, "status", "--porcelain") == ""


def test_unnamed_later_stage_failure_ends_with_diagnosis_and_no_retry_promise(tmp_path, monkeypatch):
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    install(monkeypatch)

    async def fail(*a, **kw):
        raise engine_errors.EngineFailed("account could not be used")

    monkeypatch.setattr("api.services.skill_extractor.detect_patterns", fail)
    state = run(memory)
    assert sleep_paused.get_paused(memory) is None
    assert state.error == "EngineFailed: account could not be used"
    assert not state.drain.finished and waiting(memory) == ids
    assert "Continue" not in sleep_drain.classify(engine_errors.EngineFailed("unknown")).sentence
    assert git(memory, "status", "--porcelain") == ""


@pytest.mark.parametrize("is_async", [False, True])
@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("mode", ["agent", "codex"])
def test_later_cli_call_retries_once_inside_drain_and_counts_each_attempt(
        monkeypatch, agent_runner, agent_envelopes, codex_events, is_async, persistent, mode):
    from api.services import agent_engine
    from api.services.connections.base import CliResult

    timed_out = CliResult(124, "", "timed out")
    success = agent_envelopes["success"] if mode == "agent" else CliResult(0, codex_events["ok"], "")
    runner = agent_runner(timed_out, timed_out if persistent else success)
    ds = sleep_drain.DrainState("sleep_timeout", frozen_ids=["ep1"])
    sleep_drain.register_batch("sleep_timeout_b001", ds)
    backoffs, events = [], []
    real_sleep = asyncio.sleep

    async def sleep(delay):
        backoffs.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(providers.time, "sleep", backoffs.append)
    try:
        with agent_engine.use_scope("sleep:sleep_timeout_b001"):
            fn = providers.resolve_llm_fn(Settings(llm_mode=mode), stage="skills", runner=runner,
                                          sink=events.append, is_async=is_async)

            def invoke():
                answer = fn(messages=[{"role": "user", "content": "alpha-project"}])
                return asyncio.run(answer) if is_async else answer

            if persistent:
                with pytest.raises(engine_errors.EngineTimeout):
                    invoke()
            else:
                invoke()
        assert len(runner.calls) == 2 and backoffs == [10]
        assert ds.calls == 2
        assert [e.ok for e in events if e.kind == "llm_call"] == [False, not persistent]
    finally:
        sleep_drain.unregister_batch("sleep_timeout_b001")


@pytest.mark.parametrize("stage,registered,envelope", [
    ("extraction", True, "timeout"),  # the extractor owns this retry
    ("skills", False, "timeout"),     # another workload owns its policy
    ("skills", True, "not_logged_in"),
    ("skills", True, "rate_limited"),
])
def test_call_retry_does_not_double_extraction_or_retry_auth_and_quota(
        monkeypatch, agent_runner, agent_envelopes, stage, registered, envelope):
    from api.services import agent_engine
    from api.services.connections.base import CliResult

    result = CliResult(124, "", "timed out") if envelope == "timeout" else agent_envelopes[envelope]
    runner = agent_runner(result)
    ds = sleep_drain.DrainState("sleep_timeout", frozen_ids=["ep1"])
    if registered:
        sleep_drain.register_batch("sleep_timeout_b001", ds)
    monkeypatch.setattr(providers.time, "sleep", lambda delay: pytest.fail("unexpected call retry"))
    try:
        with agent_engine.use_scope("sleep:sleep_timeout_b001"):
            fn = providers.resolve_llm_fn(Settings(llm_mode="agent"), stage=stage, runner=runner,
                                          sink=lambda e: None, is_async=False)
            with pytest.raises(engine_errors.EngineError):
                fn(messages=[{"role": "user", "content": "alpha-project"}])
        assert len(runner.calls) == 1
    finally:
        sleep_drain.unregister_batch("sleep_timeout_b001")
