"""A run the network left (the Mac asleep, offline, or a request that timed out) waits and reads again on its own.

The live case (2026-11-03): a scheduled run on a laptop; the lid closed mid-read for about three hours; on wake every
`claude -p` call returned the CLI's own error envelope (``terminal_reason: api_error``, no status, "Request timed out")
while the network was not back yet. The run stopped as "The engine needs a look", told the person to check the
sign-in, badged the four conversations "could not be read" and drew Sort as the stage that failed.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from drain_harness import episode_ids, git, install, seed_bank, settings, waiting
from api.services import (agent_engine, engine_errors, machine_state, providers, sleep_cycle, sleep_drain,
                          sleep_paused, sleep_parked)
from api.services.connections.base import CliResult

#: The envelope the CLI printed for each of the four calls (numbers from the live log).
TIMED_OUT = {"type": "result", "subtype": "error_during_execution", "is_error": True,
             "terminal_reason": "api_error", "api_error_status": None, "result": "Request timed out",
             "duration_ms": 45700}
#: The real readers, before `conftest` pins every test online and awake.
REAL_HAS_ROUTE, REAL_SLEPT_S = machine_state.has_route, machine_state.slept_s


def timed_out() -> CliResult:
    return CliResult(1, json.dumps(TIMED_OUT), "")


@pytest.fixture(autouse=True)
def idle():
    state = sleep_cycle.get_sleep_state()
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    state.error = None
    yield
    state.status, state.drain, state.drain_run, state.cancel_requested = "idle", None, False, False
    state.error = None


class Net:
    """The machine as Sleep sees it: whether a route exists and how long it slept since a mark."""

    def __init__(self, monkeypatch, *, online=True, slept=0.0):
        self.online, self.slept, self.polls = online, slept, 0
        self.on_poll = None
        waits = []
        self.waits = waits

        def has_route():
            self.polls += 1
            if self.on_poll is not None:
                self.on_poll(self)
            return self.online

        monkeypatch.setattr(machine_state, "has_route", has_route)
        monkeypatch.setattr(machine_state, "slept_s", lambda mark: self.slept)
        real_sleep = asyncio.sleep

        async def sleep(delay):
            waits.append(delay)
            await real_sleep(0)

        monkeypatch.setattr(asyncio, "sleep", sleep)


def real_reads(monkeypatch, ids, fail):
    """Stage 1 is the real extractor; each call goes through ``complete``, which raises what the CLI's envelope
    classifies as while ``fail(ep_id)`` says so, else answers."""
    from api.services import entity_extractor

    real_extract = entity_extractor.extract
    rig = install(monkeypatch, engine_label="claude-cli")
    monkeypatch.setattr(entity_extractor, "extract", real_extract)
    calls = []

    async def complete(*, messages, **kw):
        ep_id = next(i for i in ids if i in messages[-1]["content"])
        calls.append(ep_id)
        if fail(ep_id):
            agent_engine.parse_envelope(timed_out())
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"entities": [], "relationships": []}'))])

    monkeypatch.setattr(providers, "resolve_llm_fn", lambda *a, **kw: complete)
    return rig, calls


def run(memory, **kw):
    asyncio.run(sleep_cycle.run(settings(memory), "sleep_offline", user_triggered=False, drain=True, **kw))


def test_the_request_timed_out_envelope_is_a_lost_connection_not_an_unnamed_failure():
    with pytest.raises(engine_errors.EngineError) as caught:
        agent_engine.parse_envelope(timed_out())
    assert type(caught.value) is engine_errors.EngineConnectionLost
    assert "Request timed out" in str(caught.value)


@pytest.mark.parametrize("message", ["Request timed out.", "Connection timed out", "socket hang up",
                                     "The network connection was lost.", "ECONNABORTED", "UND_ERR_CONNECT_TIMEOUT"])
def test_transport_timeouts_are_connectivity_errors(message):
    assert engine_errors.is_connectivity_error(message)


def test_the_live_case_waits_for_the_network_then_reads_everything_without_a_continue(tmp_path, monkeypatch):
    """Asleep through the call, no route on wake; the route comes back a few polls later: the run reads the
    batch again on its own and files all four. No pause, no error, nothing parked or badged."""
    ids = episode_ids(4)
    memory = seed_bank(tmp_path, ids)
    net = Net(monkeypatch, online=False, slept=3 * 3600.0)
    outage = {"on": True}

    def back(n):
        if n.polls >= 3:
            n.online, n.slept, outage["on"] = True, 0.0, False

    net.on_poll = back
    rig, calls = real_reads(monkeypatch, ids, lambda _i: outage["on"])
    run(memory)
    state = sleep_cycle.get_sleep_state()
    assert waiting(memory) == [] and sleep_paused.get_paused(memory) is None
    assert state.error is None and sleep_parked.ids(memory) == set()
    assert state.drain.finished and state.drain.filed == 4 and state.drain.stop is None
    assert git(memory, "status", "--porcelain") == ""
    assert all(calls.count(i) >= 2 for i in ids)
    assert state.drain.offline_waits == 1


def test_a_network_that_never_returns_pauses_in_words_about_the_network(tmp_path, monkeypatch):
    ids = episode_ids(4)
    memory = seed_bank(tmp_path, ids)
    Net(monkeypatch, online=False, slept=3 * 3600.0)
    monkeypatch.setattr(sleep_drain, "OFFLINE_WAIT_S", 0.05)
    real_reads(monkeypatch, ids, lambda _i: True)
    run(memory)
    state = sleep_cycle.get_sleep_state()
    rec = sleep_paused.get_paused(memory)
    assert rec and rec["reason"] == "engine" and rec["engine_kind"] == "offline" and rec["can_continue"]
    assert sleep_paused.to_wire(rec)["engine_kind"] == "offline"
    assert "asleep" in rec["sentence"] and "claude auth" not in rec["sentence"]
    assert state.error is None
    # Never counted against the conversations: nothing parked, no attempt charged, none badged "could not be read".
    assert rec["attempts"] == {} and sleep_parked.ids(memory) == set() and waiting(memory) == ids
    counts = sleep_drain.origin_counts(state.drain)
    assert sum(o["could_not_be_read"] for o in counts.values()) == 0
    assert git(memory, "status", "--porcelain") == ""


def test_a_pause_the_person_asks_for_while_waiting_is_honoured(tmp_path, monkeypatch):
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    net = Net(monkeypatch, online=False)
    state = sleep_cycle.get_sleep_state()

    def press_pause(n):
        state.cancel_requested = True

    net.on_poll = press_pause
    rig, calls = real_reads(monkeypatch, ids, lambda _i: True)
    run(memory)
    rec = sleep_paused.get_paused(memory)
    assert rec and rec["reason"] == "user"
    assert len(calls) == 4          # one batch, each conversation tried twice by Stage 1's own retry; never re-read
    assert waiting(memory) == ids and sleep_parked.ids(memory) == set()


def test_an_unnamed_failure_while_the_mac_slept_is_the_network_not_the_conversation(tmp_path, monkeypatch):
    """The class, not the case: an envelope no marker names still reads again when the Mac slept through it."""
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    net = Net(monkeypatch, online=True, slept=600.0)
    outage = {"on": True}
    from api.services import entity_extractor

    real_extract = entity_extractor.extract
    install(monkeypatch, engine_label="claude-cli")
    monkeypatch.setattr(entity_extractor, "extract", real_extract)

    async def complete(*, messages, **kw):
        if outage["on"]:
            raise engine_errors.EngineFailed("`claude -p` failed (api_error): something new")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"entities": [], "relationships": []}'))])

    def settle(n):
        n.slept, outage["on"] = 0.0, False

    net.on_poll = settle
    monkeypatch.setattr(providers, "resolve_llm_fn", lambda *a, **kw: complete)
    run(memory)
    assert waiting(memory) == [] and sleep_paused.get_paused(memory) is None
    assert sleep_parked.ids(memory) == set()


def test_a_signed_out_engine_after_a_sleep_still_needs_a_fix(tmp_path, monkeypatch):
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    Net(monkeypatch, online=True, slept=600.0)
    from api.services import entity_extractor

    real_extract = entity_extractor.extract
    install(monkeypatch, engine_label="claude-cli")
    monkeypatch.setattr(entity_extractor, "extract", real_extract)

    async def complete(*, messages, **kw):
        raise engine_errors.EngineUnavailable("Claude Code is signed out — run `claude auth login`.")

    monkeypatch.setattr(providers, "resolve_llm_fn", lambda *a, **kw: complete)
    run(memory)
    rec = sleep_paused.get_paused(memory)
    assert rec and rec["reason"] == "engine" and rec["engine_kind"] == "needs_fix"


def test_a_stage_one_engine_failure_freezes_the_strip_on_read(tmp_path, monkeypatch):
    """Stage 1 failed: the strip's failed stage is Read, never Sort (``stage`` counts completed stages)."""
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    Net(monkeypatch, online=True, slept=0.0)
    from api.services import entity_extractor

    real_extract = entity_extractor.extract
    install(monkeypatch, engine_label="claude-cli")
    monkeypatch.setattr(entity_extractor, "extract", real_extract)

    async def complete(*, messages, **kw):
        raise engine_errors.EngineUnavailable("Claude Code is signed out — run `claude auth login`.")

    monkeypatch.setattr(providers, "resolve_llm_fn", lambda *a, **kw: complete)
    run(memory)
    state = sleep_cycle.get_sleep_state()
    assert state.stage == 0
    stages = sleep_drain.stages_wire(state.drain, state.stage, running=False)
    assert stages[0]["state"] != "done"


def test_slept_is_measured_with_a_clock_that_stops_while_the_machine_sleeps(monkeypatch):
    clocks = {"elapsed": 100.0, "awake": 50.0}
    monkeypatch.setattr(machine_state, "_elapsed", lambda: clocks["elapsed"])
    monkeypatch.setattr(machine_state, "_awake", lambda: clocks["awake"])
    mark = machine_state.mark()
    clocks["elapsed"] += 3 * 3600 + 46
    clocks["awake"] += 46
    assert REAL_SLEPT_S(mark) == pytest.approx(3 * 3600)
    clocks["awake"] += 10
    clocks["elapsed"] += 10
    assert REAL_SLEPT_S(mark) == pytest.approx(3 * 3600)


def test_has_route_sends_nothing_and_reads_an_unreachable_network_as_offline(monkeypatch):
    import errno
    import socket

    seen = []

    class Sock:
        def __init__(self, family, kind):
            assert kind == socket.SOCK_DGRAM
            self.family = family

        def connect(self, addr):
            seen.append(addr)
            raise OSError(errno.ENETUNREACH, "Network is unreachable")

        def send(self, *_a):   # pragma: no cover - a send would be a packet
            raise AssertionError("has_route must never send")

        sendto = send

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", Sock)
    assert REAL_HAS_ROUTE() is False
    assert len(seen) == 2
