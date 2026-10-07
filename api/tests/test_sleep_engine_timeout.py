"""G171/G163: transient engine trouble retains the run, never parks its episodes."""
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
        if failure is not None and (failure == "persistent" or calls[ep_id] == 1):
            raise engine_errors.EngineTimeout("engine call exceeded its time budget")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"entities": [], "relationships": []}'))])

    monkeypatch.setattr(providers, "resolve_llm_fn", lambda *a, **kw: complete)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    return rig, calls, backoffs


def run(memory, **kw):
    asyncio.run(sleep_cycle.run(
        settings(memory, sleep_max_episodes_per_cycle=2), "sleep_timeout",
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


@pytest.mark.parametrize("error", engine_errors.RETRYABLE)
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
