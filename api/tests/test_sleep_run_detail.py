"""A whole run at read (Sleep page v5, B8 + critic M4): Past nights groups batches by run, and
``GET /sleep/runs/{id}`` sums by ``drain_id`` — a paused or discarded batch's calls included.
Ids, counts and enums only; unknown is null, never zero."""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from drain_harness import episode_ids, install, seed_bank, settings

from api import main
from api.config import get_settings
from api.services import (
    agent_engine, cycle_usage, markdown_parser, sleep_cycle, sleep_drain, sleep_paused, sleep_runs, telemetry,
)
from api.services.agent_stream import RateLimitSignal

RESET_A, RESET_B = 1790000000, 1790020000


@pytest.fixture(autouse=True)
def _state(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    main.app.dependency_overrides.clear()


def _calls(n, *, stage="extraction", model="model-a", ok=True):
    """What the provider seam writes for each call: a ledger row tagged with the cycle and the run."""
    cid = agent_engine.cycle_id_from_scope(agent_engine.current_scope())
    for _ in range(n):
        telemetry.record(telemetry.UsageEvent(
            kind="llm_call", stage=stage, connection="claude-plan", engine="claude-cli", model=model,
            billing="subscription", input_tokens=100, output_tokens=20, cost_usd=None, equiv_cost_usd=0.01,
            duration_ms=5, ok=ok, refs={"cycle_id": cid, "drain_id": sleep_drain.drain_id_for(cid)}))
    return cid


def _window(util, reset):
    cid = agent_engine.cycle_id_from_scope(agent_engine.current_scope())
    cycle_usage.note_signals(cid, [RateLimitSignal(status="allowed", limit_type="five_hour",
                                                   utilization=util, resets_at=reset)])


def _leg(memory, rig, hook, cid, cap=3, **kw):
    rig.on_extract = hook
    cfg = settings(memory, sleep_max_episodes_per_cycle=cap)
    asyncio.run(sleep_cycle.run(cfg, cid, user_triggered=True, drain=True, **kw))
    return cfg


def _client(cfg):
    main.app.dependency_overrides[get_settings] = lambda: cfg
    return TestClient(main.app)


def _paused_run(tmp_path, monkeypatch):
    """Leg 1: batch 1 files; batch 2 makes five calls and is discarded by a Pause. Leg 2 (after a
    plan reset) files the rest. One run, one drain id, batches on both sides of the pause."""
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids)
    path = memory / "episodes" / f"{ids[0]}.md"
    parsed = markdown_parser.parse(path)
    markdown_parser.write(path, {**parsed.frontmatter, "title": "A private title"}, parsed.body)
    rig = install(monkeypatch, engine_label="claude-cli")
    state = {"leg": 1}

    async def hook(batch_no, episodes):
        if state["leg"] == 1:
            _calls(4 if batch_no == 1 else 5, stage="extraction")
            _window(0.30 if batch_no == 1 else 0.60, RESET_A)
            if batch_no == 2:
                sleep_cycle.request_cancel()
        else:
            _calls(3, stage="disambiguation", model="model-b")
            _window(0.05 + 0.1 * batch_no, RESET_B)   # the window reset in between

    cfg = _leg(memory, rig, hook, "sleep_leg1")
    rec = sleep_paused.get_paused(memory)
    state["leg"] = 2
    cfg = _leg(memory, rig, hook, "sleep_leg2", continue_from=rec)
    return memory, cfg, ids


def test_history_entries_carry_the_run_they_belong_to(tmp_path, monkeypatch):
    memory, cfg, ids = _paused_run(tmp_path, monkeypatch)
    rows = _client(cfg).get("/sleep/history", params={"limit": 15}).json()
    batches = [r for r in rows if r.get("drainId")]
    assert sorted((r["batch"], r["batches"]) for r in batches) == [(1, 3), (2, 3), (3, 3)]
    assert {r["drainId"] for r in batches} == {"sleep_leg1"}
    run = batches[0]["run"]
    assert (run["id"], run["batches"], run["filed"], run["frozen"], run["parked"], run["pauses"], run["state"]) == \
        ("sleep_leg1", 3, 9, 9, 0, 1, "finished")
    assert run["startedBy"] == "user" and run["pausedMs"] >= 0 and run["readMs"] >= 0


def test_the_history_run_summary_survives_a_15_row_window(tmp_path, monkeypatch):
    """A 20-batch run alone fills a 15-row page of history; the group's numbers are the run's own."""
    ids = episode_ids(20)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch, engine_label="claude-cli")
    cfg = _leg(memory, rig, None, "sleep_long", cap=1)
    rows = _client(cfg).get("/sleep/history", params={"limit": 15}).json()
    sleeps = [r for r in rows if r.get("drainId") == "sleep_long"]
    assert 0 < len(sleeps) < 20, "the page holds only part of the run (and a decay commit besides)"
    assert all(r["run"]["batches"] == 20 and r["run"]["filed"] == 20 for r in sleeps), "never summed from the page"


def test_the_run_detail_sums_by_drain_id_including_a_discarded_batchs_calls(tmp_path, monkeypatch):
    memory, cfg, ids = _paused_run(tmp_path, monkeypatch)
    body = _client(cfg).get("/sleep/runs/sleep_leg1").json()
    assert (body["id"], body["state"], body["filed"], body["frozen"], body["parked"]) == ("sleep_leg1", "finished", 9, 9, 0)
    models = {m["model"]: m for m in body["models"]}
    assert models["model-a"]["calls"] == 9, "four filed + five in the batch the pause discarded: paid for, counted"
    assert models["model-b"]["calls"] == 6
    assert models["model-a"]["stages"] == ["extraction"] and models["model-b"]["stages"] == ["disambiguation"], \
        "the stage list is the ledger's own data, never a claim about which model reads"
    assert body["usage"]["basis"] == "list" and body["usage"]["models"] == body["models"]
    assert [b["index"] for b in body["batches"]] == [1, 2, 3]
    assert [b["filed"] for b in body["batches"]] == [3, 3, 3]
    assert body["pages"]["created"] == 9 and len(body["pages"]["first"]) == 8, "at most eight names"


def test_the_run_detail_lists_plan_windows_per_batch_and_never_averages_across_a_reset(tmp_path, monkeypatch):
    memory, cfg, ids = _paused_run(tmp_path, monkeypatch)
    body = _client(cfg).get("/sleep/runs/sleep_leg1").json()
    per_batch = [b["windows"][0] for b in body["batches"]]
    assert [w["resetsAt"] for w in per_batch] == [RESET_A, RESET_B, RESET_B], "the reset is visible between batches 1 and 2"
    assert per_batch[0]["after"] == 0.30 and per_batch[2]["after"] == pytest.approx(0.45)
    plan = (body["usage"] or {}).get("plan")
    assert plan is None or all(w["window"] != "five_hour" for w in plan["windows"]), \
        "a first-to-last figure across a reset is meaningless, so the run level says nothing"
    assert [p["reason"] for p in body["pauses"]] == ["user"] and body["pauses"][0]["endedAt"], "closed by Continue"


def test_the_run_detail_says_null_never_zero_when_the_ledger_has_nothing(tmp_path, monkeypatch):
    import shutil

    from api.services.auth import cicada_home

    memory, cfg, ids = _paused_run(tmp_path, monkeypatch)
    shutil.rmtree(cicada_home() / "telemetry")   # the machine-global ledger is gone; the run's own summary is not
    client = _client(cfg)
    body = client.get("/sleep/runs/sleep_leg1").json()
    assert body["filed"] == 9 and body["state"] == "finished", "the run's own numbers survive"
    assert body["usage"] is None and body["models"] == [] and body["batches"] == [] and body["pages"] is None
    assert client.get("/sleep/runs/nope").status_code == 404
    assert client.get("/sleep/runs/bad%20id").status_code == 404


def test_with_telemetry_off_the_summary_stays_and_cost_reads_null(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    rig = install(monkeypatch)
    cfg = _leg(memory, rig, None, "sleep_off")
    body = _client(cfg).get("/sleep/runs/sleep_off").json()
    assert body["filed"] == 6 and body["state"] == "finished" and body["frozen"] == 6
    assert body["usage"] is None and body["models"] == [] and body["batches"] == [], "not recorded is not zero"
    assert body["pages"] is None and body["calls"] == 0


def test_the_run_detail_holds_ids_counts_and_enums_only(tmp_path, monkeypatch):
    memory, cfg, ids = _paused_run(tmp_path, monkeypatch)
    text = json.dumps(_client(cfg).get("/sleep/runs/sleep_leg1").json())
    assert "A private title" not in text and "Episode" not in text and "project X" not in text
    hist = json.dumps(_client(cfg).get("/sleep/history").json())
    assert "A private title" not in hist


def test_the_run_detail_etag_moves_with_the_run_and_answers_304(tmp_path, monkeypatch):
    memory, cfg, ids = _paused_run(tmp_path, monkeypatch)
    client = _client(cfg)
    tag = client.get("/sleep/runs/sleep_leg1").headers["ETag"]
    assert client.get("/sleep/runs/sleep_leg1", headers={"If-None-Match": tag}).status_code == 304
    time.sleep(0.05)
    telemetry.record(telemetry.UsageEvent(kind="llm_call", stage="extraction", model="m", engine="claude-cli",
                                          refs={"cycle_id": "x", "drain_id": "sleep_leg1"}))
    moved = client.get("/sleep/runs/sleep_leg1").headers["ETag"]
    assert moved != tag, "a new ledger row moves it"
    sleep_runs.close_open_pause(memory, "sleep_leg1")
    assert client.get("/sleep/runs/sleep_leg1").headers["ETag"] != moved, "and so does the run's own summary"


def test_a_run_summary_holds_no_text_and_is_machine_local(tmp_path, monkeypatch):
    memory, cfg, ids = _paused_run(tmp_path, monkeypatch)
    from api.services import sleep_local

    path = sleep_local.bank_dir(memory, create=False) / "runs.json"
    assert path.is_file() and memory not in path.parents
    data = json.loads(path.read_text())
    run = data["runs"]["sleep_leg1"]
    assert set(run) >= {"id", "started_by", "started_at", "finished_at", "state", "frozen", "filed", "parked",
                        "committed_batches", "batches", "calls", "read_ms", "paused_ms", "pauses",
                        "questions_raised", "owner"}
    assert "private" not in path.read_text().lower()


def test_questions_raised_counts_what_the_run_added_to_the_inbox(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)

    async def after(n):
        if n == 1:
            (memory / "inbox").mkdir(exist_ok=True)
            for i in (1, 2):
                markdown_parser.write(memory / "inbox" / f"inbox-{i:03d}.md",
                                      {"id": f"inbox-{i:03d}", "kind": "clarification", "status": "pending"}, "q")

    rig.on_generate = after
    _leg(memory, rig, None, "sleep_q")
    assert sleep_runs.get(memory, "sleep_q")["questions_raised"] == 2
