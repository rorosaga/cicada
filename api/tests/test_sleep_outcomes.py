"""Per-conversation outcomes (Sleep page v5, B3 + critic H2): who could not be read and why,
retry once then park, and the engine's trouble never counted against a conversation."""
from __future__ import annotations

import asyncio
import json
import os
import stat
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from drain_harness import episode_ids, install, is_processed, seed_bank, settings, waiting

from api import main
from api.config import get_settings
from api.services import (
    agent_engine, engine_errors, json_parse, markdown_parser, sleep_cycle, sleep_drain, sleep_paused, sleep_parked,
)
from api.services.connections.base import CliResult


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    main.app.dependency_overrides.clear()


def _drain(memory, cap=3, cid="sleep_out"):
    cfg = settings(memory, sleep_max_episodes_per_cycle=cap)
    asyncio.run(sleep_cycle.run(cfg, cid, user_triggered=True, drain=True))
    return cfg, sleep_cycle.get_sleep_state()


def _client(cfg):
    main.app.dependency_overrides[get_settings] = lambda: cfg
    return TestClient(main.app)


# --------------------------------------------------------------------------- #
# The classification table
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("exc,expected", [
    (engine_errors.EngineThrottled("x"), ("pause", None)),
    (engine_errors.EngineExhausted("x"), ("pause", None)),
    (engine_errors.EngineOverage("x"), ("pause", None)),
    (engine_errors.EngineUnavailable("x"), ("pause", None)),
    (engine_errors.EngineModelNotFound("x"), ("pause", None)),
    (engine_errors.EngineTimeout("x"), ("content", "timed_out")),
    (engine_errors.EngineProtocolError("x"), ("content", "empty_answer")),
    (json_parse.EmptyResponse("empty"), ("content", "empty_answer")),
    (ValueError("no JSON object found"), ("content", "unparseable")),
    (json.JSONDecodeError("bad", "{", 1), ("content", "unparseable")),
    (engine_errors.EngineFailed("x"), ("content", "other")),
    (RuntimeError("anything else"), ("content", "other")),
])
def test_each_exception_class_maps_as_the_table_says(exc, expected):
    assert sleep_drain.classify_episode(exc) == expected
    assert expected[1] is None or expected[1] in sleep_drain.UNREAD_REASONS


def test_the_metered_rung_is_classified_too():
    import litellm

    lx = litellm.exceptions
    assert sleep_drain.classify_episode(lx.AuthenticationError("k", "p", "m"))[0] == "pause"
    assert sleep_drain.classify_episode(lx.RateLimitError("r", "p", "m"))[0] == "pause"
    assert sleep_drain.classify_episode(lx.Timeout("t", "m", "p")) == ("content", "timed_out")


def test_an_empty_plan_answer_is_content_not_signed_out():
    """A CLI that ran, exited cleanly and said nothing is an empty answer (the conversation's);
    a non-zero exit with no output stays the engine being gone (the run's)."""
    with pytest.raises(engine_errors.EngineProtocolError):
        agent_engine.parse_envelope(CliResult(0, "", ""))
    with pytest.raises(engine_errors.EngineUnavailable):
        agent_engine.parse_envelope(CliResult(1, "", "not logged in"))
    with pytest.raises(json_parse.EmptyResponse):
        json_parse.parse_json_object("   ")
    with pytest.raises(ValueError) as unparseable:
        json_parse.parse_json_object("no braces here")
    assert not isinstance(unparseable.value, json_parse.EmptyResponse)


# --------------------------------------------------------------------------- #
# The parked store
# --------------------------------------------------------------------------- #


def test_the_parked_store_is_machine_local_0600_and_holds_no_titles(tmp_path):
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    path = memory / "episodes" / f"{ids[0]}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "title": "A private conversation title"}, parsed.body)

    sleep_parked.park(memory, ids[0], "empty_answer", 2)
    store = sleep_local_path(memory)
    assert store.is_file() and stat.S_IMODE(store.stat().st_mode) == 0o600
    assert stat.S_IMODE(store.parent.stat().st_mode) == 0o700
    assert memory not in store.parents, "never inside a bank"
    text = store.read_text()
    assert "private conversation" not in text and "Episode" not in text, "ids and enums only"
    assert json.loads(text)[ids[0]]["reason"] == "empty_answer"
    assert sleep_parked.ids(memory) == {ids[0]}, "survives a restart: it is a file, not memory"


def sleep_local_path(memory):
    from api.services import sleep_local

    return sleep_local.bank_dir(memory, create=False) / "parked.json"


def test_a_conversation_that_changed_on_disk_is_unparked_and_read_again(tmp_path):
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    sleep_parked.park(memory, ids[0], "timed_out", 2)
    sleep_parked.park(memory, ids[1], "timed_out", 2)
    path = memory / "episodes" / f"{ids[0]}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, parsed.frontmatter, parsed.body + "\nuser: and one more turn (the Stop hook grew it)")
    assert sleep_parked.ids(memory) == {ids[1]}, "the stamp moved: only the grown one is released"
    assert list(sleep_parked.load(memory)) == [ids[1]], "and it is dropped from the store, not just hidden"


def test_a_parked_conversation_is_skipped_by_the_next_freeze_but_still_waiting(tmp_path, monkeypatch):
    ids = episode_ids(4)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    sleep_parked.park(memory, ids[2], "unparseable", 2)
    _drain(memory, cap=25)
    assert rig.extract_batches == [[ids[0], ids[1], ids[3]]]
    assert waiting(memory) == [ids[2]], "parked is still processed: false — still in the debt"
    ds = sleep_cycle.get_sleep_state().drain
    assert ds.frozen == 3 and ds.finished and ds.arrived_since == 0, "a parked one is not 'new since you started'"


# --------------------------------------------------------------------------- #
# H2: the engine's trouble versus the conversation's
# --------------------------------------------------------------------------- #


def test_one_pause_class_failure_stops_after_the_batch_commits(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.fail_exc = {ids[1]: engine_errors.EngineUnavailable("Claude Code is signed out")}
    _cfg, state = _drain(memory)

    assert len(rig.extract_batches) == 1, "the run stops: the next batch would spawn and fail the same way"
    ds = state.drain
    assert ds.stop.reason == "engine" and "signed out" in ds.stop.sentence
    assert [is_processed(memory, i) for i in ids[:3]] == [True, False, True], "the other two were filed"
    assert ds.attempts.get(ids[1], 0) == 0 and ids[1] not in ds.parked, "never counted against the conversation"
    assert ds.filed == 2 and ds.committed_batches == 1


def test_all_content_failures_park_instead_of_an_engine_stop(tmp_path, monkeypatch):
    ids = episode_ids(3)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    rig.fail_exc = {i: engine_errors.EngineProtocolError("finished without an answer") for i in ids}
    _cfg, state = _drain(memory, cap=3)

    ds = state.drain
    assert ds.stop is None and ds.finished, "not a stop"
    assert state.error is None, "and not an engine failure"
    assert set(ds.parked) == set(ids) and set(ds.parked.values()) == {"empty_answer"}
    assert len(rig.extract_batches) == 2, "each got its one more try, together, then parked"
    assert waiting(memory) == ids and ds.committed_batches == 0 and ds.filed == 0
    assert sleep_parked.ids(memory) == set(ids)


def test_retry_of_one_failing_id_ends_as_could_not_be_read_not_an_engine_failure(tmp_path, monkeypatch):
    ids = episode_ids(3)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    sleep_parked.park(memory, ids[1], "empty_answer", 2)
    rig.fail_exc = {ids[1]: engine_errors.EngineProtocolError("finished without an answer")}
    cfg = settings(memory, sleep_max_episodes_per_cycle=3)
    client = _client(cfg)

    res = client.post("/sleep/parked/retry", json={"ids": [ids[1]]})
    assert res.status_code == 200 and res.json()["status"] == "started"
    assert rig.extract_batches == [[ids[1]], [ids[1]]], "exactly that id, and its one more try"
    state = sleep_cycle.get_sleep_state()
    assert state.error is None and state.drain.stop is None and state.drain.finished
    assert state.drain.parked == {ids[1]: "empty_answer"}
    assert sleep_parked.ids(memory) == {ids[1]}, "parked again"


def test_retry_reads_only_the_named_ids(tmp_path, monkeypatch):
    ids = episode_ids(4)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    for i in (ids[0], ids[2]):
        sleep_parked.park(memory, i, "timed_out", 2)
    client = _client(settings(memory, sleep_max_episodes_per_cycle=25))

    assert client.post("/sleep/parked/retry", json={"ids": [ids[2], "not-parked"]}).json()["status"] == "started"
    assert rig.extract_batches == [[ids[2]]]
    assert is_processed(memory, ids[2]) and not is_processed(memory, ids[1])
    assert sleep_parked.ids(memory) == {ids[0]}, "the other parked one is untouched"
    assert client.post("/sleep/parked/retry", json={"ids": ["nope"]}).json()["status"] == "nothing_parked"


def test_no_ids_retries_every_parked_conversation(tmp_path, monkeypatch):
    ids = episode_ids(3)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    for i in ids[:2]:
        sleep_parked.park(memory, i, "other", 2)
    _client(settings(memory, sleep_max_episodes_per_cycle=25)).post("/sleep/parked/retry")
    assert rig.extract_batches == [ids[:2]] and sleep_parked.ids(memory) == set()


def test_retry_is_refused_while_a_run_is_reading_or_paused(tmp_path, monkeypatch):
    ids = episode_ids(2)
    memory = seed_bank(tmp_path, ids)
    install(monkeypatch)
    sleep_parked.park(memory, ids[0], "other", 2)
    client = _client(settings(memory, sleep_max_episodes_per_cycle=25))

    state = sleep_cycle.get_sleep_state()
    state.status = "running"
    assert client.post("/sleep/parked/retry").status_code == 409

    state.status = "idle"
    ds = sleep_drain.DrainState(drain_id="sleep_p", frozen_ids=ids, batch_size=25)
    sleep_paused.save(memory, sleep_paused.build(ds, phase="paused", stop=sleep_drain.DrainStop("cancelled")))
    res = client.post("/sleep/parked/retry")
    assert res.status_code == 409 and "Continue or end the paused run first" in res.json()["detail"]
    assert sleep_parked.ids(memory) == {ids[0]}, "nothing was unparked by the refusal"


# --------------------------------------------------------------------------- #
# The queue rows
# --------------------------------------------------------------------------- #


def test_the_queue_serves_states_reasons_and_attempts_from_frontmatter_only(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    path = memory / "episodes" / f"{ids[0]}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "title": "A title"}, parsed.body)
    sleep_parked.park(memory, ids[5], "timed_out", 2)
    cfg = settings(memory, sleep_max_episodes_per_cycle=25)

    ds = sleep_drain.DrainState(drain_id="sleep_q", frozen_ids=ids[:5], batch_size=25, batch=1, batches=1)
    ds.origin_of = {i: "claude-code" for i in ids}
    ds.filed_ids = {ids[0]}
    ds.batch_counted = False
    ds.live = sleep_drain.BatchLive(index=1, total=4, ids=ids[1:5])
    ds.live.started |= {ids[1], ids[2], ids[3]}
    ds.live.read.add(ids[1])
    ds.live.failed[ids[2]] = "empty_answer"
    ds.attempts[ids[2]] = 1
    sleep_cycle.get_sleep_state().drain = ds
    ds.memory_path = memory

    def boom(*a, **k):
        raise AssertionError("a body was parsed")

    monkeypatch.setattr("api.services.bank_index.IndexedFile.body", boom)   # frontmatter is the index's; a body is not
    body = _client(cfg).get("/sleep/queue").json()
    rows = {r["id"]: r for r in body["items"]}
    assert body["total"] == 6
    assert rows[ids[0]]["state"] == "filed" and rows[ids[0]]["title"] == "A title"
    assert rows[ids[1]]["state"] == "read" and rows[ids[1]]["batch"] == 1
    assert (rows[ids[2]]["state"], rows[ids[2]]["reason"], rows[ids[2]]["attempts"]) == ("could_not_be_read", "empty_answer", 1)
    assert rows[ids[3]]["state"] == "reading" and rows[ids[4]]["state"] == "waiting"
    assert (rows[ids[5]]["state"], rows[ids[5]]["reason"], rows[ids[5]]["attempts"]) == ("parked", "timed_out", 2)

    only = _client(cfg).get("/sleep/queue", params={"state": "could_not_be_read"}).json()
    assert [r["id"] for r in only["items"]] == [ids[2]] and only["total"] == 1
    page = _client(cfg).get("/sleep/queue", params={"limit": 2, "offset": 4}).json()
    assert [r["id"] for r in page["items"]] == ids[4:6] and page["total"] == 6
    assert _client(cfg).get("/sleep/queue", params={"limit": 500}).status_code == 422, "bounded at 200"
    assert _client(cfg).get("/sleep/queue", params={"origin": "chatgpt-export"}).json()["total"] == 0
