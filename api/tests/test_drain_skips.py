"""What a drain runs once per DRAIN rather than once per batch (owner, 2026-09-29).

Decay (both engines) and Stage 5.57's page reads: only in the batch that empties
the queue. The engine-independent tail: once per run, on every exit path.
Everything else — Stage 3 synthesis, Stage 5's write, the claim pipeline, the
open-question refresh — is per batch, because each batch's commit must be
self-consistent."""
from __future__ import annotations

import asyncio

import pytest

from drain_harness import episode_ids, install, seed_bank, settings

from api.services import sleep_cycle


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def _drain(memory, cap=3):
    asyncio.run(sleep_cycle.run(
        settings(memory, sleep_max_episodes_per_cycle=cap), "sleep_skips", user_triggered=True, drain=True))


def test_decay_and_page_reads_run_only_in_the_last_batch(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(7))
    rig = install(monkeypatch)
    _drain(memory)

    assert rig.prune_calls == [{"decay": False}, {"decay": False}, {}], "entity decay: last batch only"
    assert rig.pipeline_calls == [{"decay": False}, {"decay": False}, {}], "claim decay: last batch only"
    assert rig.link_calls == 1, "Stage 5.57 reads pages once"
    assert rig.question_refreshes == 3, "the open-question refresh stays per batch"
    assert rig.generate_calls == 3


def test_a_plain_cycle_passes_no_decay_switch_at_all(tmp_path, monkeypatch):
    """The stubs other tests install have fixed signatures: a plain cycle must call
    every seam exactly as it always did."""
    memory = seed_bank(tmp_path, episode_ids(2))
    rig = install(monkeypatch)
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=25), "sleep_plain"))
    assert rig.prune_calls == [{}] and rig.pipeline_calls == [{}] and rig.link_calls == 1


def test_the_tail_runs_exactly_once_per_drain(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(7))
    rig = install(monkeypatch)
    _drain(memory)

    for step in ("state", "expiry", "followups", "connectors", "feeds", "links", "papers", "wispr", "logos"):
        assert rig.tail.count(step) == 1, step
    assert "questions" not in rig.tail, "the last batch already refreshed them, as a plain cycle does"
    assert rig.tail[0] == "state", "the projection first, as ever"


def test_the_tail_runs_once_when_the_drain_is_cancelled(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(7))
    rig = install(monkeypatch)

    async def cancel(batch_no, episodes):
        if batch_no == 2:
            sleep_cycle.request_cancel()

    rig.on_extract = cancel
    _drain(memory)
    assert rig.tail.count("state") == 1 and rig.tail.count("connectors") == 1
    assert rig.prune_calls == [{"decay": False}], "a stopped drain never decays"
    assert rig.link_calls == 0


def test_a_drain_that_reads_nothing_decays_nothing(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, [])
    rig = install(monkeypatch)
    _drain(memory)
    assert rig.prune_calls == [] and rig.link_calls == 0
