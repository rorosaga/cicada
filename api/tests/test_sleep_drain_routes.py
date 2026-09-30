"""The drain's seams (owner, 2026-09-29): the trigger and cancel routes, the
status wire, the bank guard, the breaker's reset time, the decay switches and the
plan-limit pre-flight — each small, each one thing the drain leans on."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.background import BackgroundTasks

from drain_harness import episode_ids, install, seed_bank, settings

from api.config import Settings
from api.services import agent_engine, plan_limits, sleep_cycle


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested, s.cycle_id = "idle", None, False, False, None
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested, s.cycle_id = "idle", None, False, False, None


# --------------------------------------------------------------------------- #
# The routes
# --------------------------------------------------------------------------- #


def test_trigger_starts_a_drain_and_reserve_clears_a_stale_drain():
    from api.routers import sleep as sleep_router
    from api.services import sleep_drain

    state = sleep_cycle.get_sleep_state()
    state.drain = sleep_drain.DrainState(drain_id="stale", frozen_ids=["a"])   # a finished run's leftovers
    bg = BackgroundTasks()
    resp = asyncio.run(sleep_router.trigger_sleep(background_tasks=bg, settings=Settings()))

    assert resp.status == "started"
    assert state.drain is None and state.drain_run is True, "reserved as a drain, with nothing stale to report"
    (task,) = bg.tasks
    assert task.func is sleep_router.run and task.kwargs == {"user_triggered": True, "drain": True}


def test_a_second_trigger_while_a_drain_runs_is_already_running():
    from api.routers import sleep as sleep_router

    state = sleep_cycle.get_sleep_state()
    state.status, state.cycle_id = "running", "sleep_x"
    resp = asyncio.run(sleep_router.trigger_sleep(background_tasks=BackgroundTasks(), settings=Settings()))
    assert resp.status == "already_running" and resp.cycle_id == "sleep_x"


def test_cancel_message_is_drain_aware():
    from fastapi.testclient import TestClient

    from api import main

    state = sleep_cycle.get_sleep_state()
    state.status, state.cycle_id, state.drain_run = "running", "sleep_x", True
    said = TestClient(main.app).post("/sleep/cancel").json()["message"]
    assert "Batches already filed stay filed" in said and "next Consolidate" in said

    state.drain_run = False
    plain = TestClient(main.app).post("/sleep/cancel").json()["message"]
    assert "Batches already filed" not in plain, "a plain cycle's message is unchanged"


def test_status_carries_the_drain_block_as_camel_case_and_null_when_plain():
    from fastapi.testclient import TestClient

    from api import main
    from api.services import sleep_drain

    client = TestClient(main.app)
    assert client.get("/sleep/status").json()["drain"] is None

    state = sleep_cycle.get_sleep_state()
    ds = sleep_drain.DrainState(drain_id="sleep_x", frozen_ids=["a", "b", "c"], batch_size=2, batches=2, batch=1)
    ds.filed, ds.stop = 2, sleep_drain.DrainStop("plan_limit", "Paused.", 1790000000)
    state.drain = ds
    drain = client.get("/sleep/status").json()["drain"]
    assert drain == {
        "id": "sleep_x", "frozen": 3, "batchSize": 2, "batch": 1, "batches": 2, "filed": 2, "requeued": 0,
        "skipped": 0, "active": True, "finished": False,
        "stop": {"reason": "plan_limit", "sentence": "Paused.", "resetsAt": 1790000000}, "arrivedSince": None}
    assert "frozenIds" not in drain and "frozen_ids" not in drain, "ids never leave the process"


def test_the_sse_event_carries_a_compact_drain_block():
    from api.services import sleep_drain

    ds = sleep_drain.DrainState(drain_id="x", frozen_ids=list("abcd"), batch_size=2, batches=2, batch=2)
    ds.filed, ds.stop = 2, sleep_drain.DrainStop("cancelled")
    assert sleep_drain.to_sse(ds) == {"batch": 2, "batches": 2, "filed": 2, "frozen": 4, "active": True, "stop": "cancelled"}
    assert sleep_drain.to_sse(None) is None


# --------------------------------------------------------------------------- #
# The bank guard
# --------------------------------------------------------------------------- #


def test_bank_switching_is_refused_while_a_person_started_run_is_reading_and_allowed_after(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main
    from api.services import bank_registry

    root = tmp_path / "banks"
    root.mkdir()
    bank_registry.create_bank(root, "other", "")
    monkeypatch.setenv("CICADA_MEMORY_ROOT", str(root))
    from api import config

    config.get_settings.cache_clear()
    try:
        client = TestClient(main.app)
        state = sleep_cycle.get_sleep_state()
        state.status, state.drain_run = "running", True
        for path in ("/banks/other/activate", "/banks/demo", "/banks/leave-demo"):
            resp = client.post(path)
            assert resp.status_code == 409, path
            assert "Cicada is reading" in resp.json()["detail"]
        active = bank_registry.load_registry(root).get("active", bank_registry.DEFAULT_BANK)
        assert client.post(f"/banks/{active}/rename", json={"newName": "renamed"}).status_code == 409
        assert bank_registry.load_registry(root).get("active") == active, "nothing moved"

        # a plain (or scheduled) cycle keeps today's behaviour
        state.drain_run = False
        assert client.post("/banks/other/activate").status_code == 200
        # and so does idle
        state.status = "idle"
        assert client.post("/banks/leave-demo").status_code == 200
    finally:
        config.get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# The breaker keeps the vendor's reset time
# --------------------------------------------------------------------------- #


def test_breaker_keeps_resets_at_and_purges_with_the_scope():
    with agent_engine.use_scope("sleep:drain-scope"):
        assert agent_engine.trip_breaker("limit", resets_at=1790000000) is True
        assert agent_engine.breaker_reason() == "limit" and agent_engine.breaker_resets_at() == 1790000000
    assert agent_engine.breaker_reason(scope="sleep:drain-scope") is None
    assert agent_engine.breaker_resets_at(scope="sleep:drain-scope") is None
    # a trip with no measured time records none, and only the first trip counts
    assert agent_engine.trip_breaker("a", scope="B") and not agent_engine.trip_breaker("b", scope="B", resets_at=5)
    assert agent_engine.breaker_resets_at(scope="B") is None
    agent_engine.reset_breaker(scope="B")
    assert agent_engine.breaker_resets_at(scope="B") is None


# --------------------------------------------------------------------------- #
# The decay switches
# --------------------------------------------------------------------------- #


def _old_entity():
    return {"id": "old-topic", "frontmatter": {
        "type": "concept", "status": "active", "confidence": 0.9, "decay_class": "active",
        "last_referenced": "2026-01-01", "source_episodes": ["ep_2025-12-01_001"]}, "body": ""}


def test_resolve_and_prune_decay_false_skips_only_the_decay_loop():
    from datetime import datetime

    from api.services import conflict_resolver

    cfg = SimpleNamespace(archive_threshold=0.2, decay_nudge_threshold=0.4)
    referenced = {"id": "fresh", "action": "create", "source_episode": "ep_1", "entity": {"name": "Fresh"}}
    now = datetime(2026, 9, 29)
    with_decay = asyncio.run(conflict_resolver.resolve_and_prune([referenced], [_old_entity()], cfg, now=now, tuning={}))
    without = asyncio.run(conflict_resolver.resolve_and_prune(
        [dict(referenced)], [_old_entity()], cfg, now=now, tuning={}, decay=False))

    assert [c["id"] for c in with_decay] == ["fresh", "old-topic"] and with_decay[1]["trigger"] == "sleep/decay"
    assert [c["id"] for c in without] == ["fresh"]
    assert without[0]["decayed_through"] == "2026-09-29", "the watermark on a created page stays either way"


def test_reconcile_stage3_decay_false_skips_only_claim_decay(tmp_path):
    from api.services import predicates
    from api.services.claim_reconciler import reconcile_stage3
    from api.services.claims import Claim

    predicates.install_predicate_map(tmp_path)
    cfg = SimpleNamespace(memory_path=tmp_path, archive_threshold=0.2, decay_nudge_threshold=0.4, litellm_model="m")

    def claims():
        return {"old-topic": [Claim(id="clm_1", text="t", subject="old-topic", predicate="uses", object="x",
                                    confidence=0.9, valid_from="2025-01-01", recorded_at="2025-01-01")]}

    decayed, _, _ = reconcile_stage3([], claims(), cfg, now_date="2026-09-29")
    kept, _, _ = reconcile_stage3([], claims(), cfg, now_date="2026-09-29", decay=False)
    assert decayed["old-topic"][0].confidence < 0.9
    assert kept["old-topic"][0].confidence == 0.9 and kept["old-topic"][0].decayed_through is None


# --------------------------------------------------------------------------- #
# The ChatGPT plan's pre-flight
# --------------------------------------------------------------------------- #


def _codex_preflight(monkeypatch, tmp_path, sentence, resets_at=None):
    from api.services import codex_engine, cycle_usage

    memory = seed_bank(tmp_path, episode_ids(4))
    rig = install(monkeypatch, engine_label="codex-cli")

    async def preflight():
        return False, sentence, None

    async def begin(_cid):
        return None

    monkeypatch.setattr(codex_engine, "preflight", preflight)
    monkeypatch.setattr(codex_engine, "_last_limit_resets_at", resets_at)
    monkeypatch.setattr(cycle_usage, "begin_codex", begin)
    asyncio.run(sleep_cycle.run(settings(memory, sleep_max_episodes_per_cycle=2), "sleep_codex",
                                user_triggered=True, drain=True))
    return sleep_cycle.get_sleep_state(), rig


def test_a_used_up_chatgpt_plan_at_preflight_is_a_pause(monkeypatch, tmp_path):
    sentence = plan_limits.CODEX_LIMIT_LEAD + " — Sleep didn't start. Try again after 14:00."
    state, rig = _codex_preflight(monkeypatch, tmp_path, sentence)
    assert state.drain.stop.reason == "plan_limit" and state.drain.stop.sentence == sentence
    assert state.error is None and rig.extract_batches == []


def test_a_used_up_chatgpt_plan_pause_carries_the_measured_reset(monkeypatch, tmp_path):
    sentence = plan_limits.CODEX_LIMIT_LEAD + " — Sleep didn't start."
    state, _rig = _codex_preflight(monkeypatch, tmp_path, sentence, resets_at=1_900_000_000)
    assert state.drain.stop.reason == "plan_limit" and state.drain.stop.resets_at == 1_900_000_000


def test_a_signed_out_chatgpt_plan_at_preflight_is_a_failure(monkeypatch, tmp_path):
    state, _rig = _codex_preflight(monkeypatch, tmp_path, "ChatGPT is signed out.")
    assert state.drain.stop.reason == "engine" and state.error == "ChatGPT is signed out."


def test_the_codex_limit_lead_is_what_codex_stop_says():
    snap = SimpleNamespace(ordinary_usage_allowed=False, limit_reached=True, resets_at=None)
    assert plan_limits.codex_stop(snap).startswith(plan_limits.CODEX_LIMIT_LEAD)
