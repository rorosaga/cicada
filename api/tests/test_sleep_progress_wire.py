"""Honest live progress (Sleep page v5, B4). A number is a count of finished work from the
object that did it, drain-level counters only grow, a total is fixed when its unit starts,
and a failure is its own count. Ids and counts only."""
from __future__ import annotations

import asyncio
import time

import pytest

from drain_harness import episode_ids, install, seed_bank, settings

from api.services import (
    agent_engine, bank_index, claims, engine_errors, markdown_parser, providers, sleep_cycle, sleep_drain,
    sleep_progress,
)


@pytest.fixture(autouse=True)
def _idle_state():
    s = sleep_cycle.get_sleep_state()
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False
    yield
    s.status, s.drain, s.drain_run, s.cancel_requested = "idle", None, False, False


def _run(memory, cap=3, cid="sleep_wire"):
    cfg = settings(memory, sleep_max_episodes_per_cycle=cap)
    asyncio.run(sleep_cycle.run(cfg, cid, user_triggered=True, drain=True))
    return sleep_cycle.get_sleep_state()


def _balanced(ds):
    for origin, c in sleep_drain.origin_counts(ds).items():
        parts = c["filed"] + c["read"] + c["waiting"] + c["could_not_be_read"] + c["parked"] + c["skipped"]
        assert parts == c["frozen"], (origin, c)


# --------------------------------------------------------------------------- #
# calls
# --------------------------------------------------------------------------- #


def test_calls_only_grow_and_a_discarded_batchs_calls_stay_counted(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(9))
    rig = install(monkeypatch)
    seen = []

    async def spend(batch_no, episodes):
        cid = agent_engine.cycle_id_from_scope(agent_engine.current_scope())
        for _ in range(4 if batch_no == 1 else 5):
            sleep_drain.note_call(cid)   # what the provider seam does for every call that spawned
        seen.append(sleep_cycle.get_sleep_state().drain.calls)
        if batch_no == 2:
            sleep_cycle.request_cancel()   # batch 2 is discarded before it files

    rig.on_extract = spend
    state = _run(memory)
    ds = state.drain
    assert seen == [4, 9] and ds.calls == 9, "the discarded batch's five calls were paid for and stay counted"
    assert ds.filed == 3 and ds.stop.reason == "cancelled"
    assert sleep_drain.drain_for("sleep_wire_b002") is None, "the registry never outlives a batch"


def test_the_provider_seam_counts_a_spawned_call_and_names_the_drain_on_the_ledger_row(monkeypatch):
    from api.config import Settings
    from api.services.telemetry import UsageEvent

    class _Resp:
        class _M:
            content = "{}"

        class _C:
            message = None

        choices = [_C()]
        usage = {"prompt_tokens": 1, "completion_tokens": 1}
        _hidden_params = {"response_cost": 0.0}

    _Resp._C.message = _Resp._M()
    ds = sleep_drain.DrainState(drain_id="sleep_run_x", frozen_ids=["a"])
    sleep_drain.register_batch("sleep_run_x_b001", ds)
    events: list[UsageEvent] = []
    try:
        with agent_engine.use_scope("sleep:sleep_run_x_b001"):
            fn = providers.resolve_llm_fn(Settings(), completion=lambda **kw: _Resp(), stage="extraction",
                                          sink=events.append)
            fn(messages=[])
            fn(messages=[])
        fn2 = providers.resolve_llm_fn(Settings(), completion=lambda **kw: _Resp(), stage="ask", sink=events.append)
        fn2(messages=[])   # outside any batch: never counted
    finally:
        sleep_drain.unregister_batch("sleep_run_x_b001")
    assert ds.calls == 2
    assert [e.refs.get("drain_id") for e in events] == ["sleep_run_x", "sleep_run_x", None]
    assert events[0].refs["cycle_id"] == "sleep_run_x_b001"


# --------------------------------------------------------------------------- #
# stages
# --------------------------------------------------------------------------- #


def test_stage_totals_are_fixed_when_the_stage_starts_and_fill_only_from_finished_work(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    install(monkeypatch)
    snaps = []

    async def resolve(extracted, existing, settings_, cancel_check=None, progress_callback=None):
        ds = sleep_cycle.get_sleep_state().drain
        state = sleep_cycle.get_sleep_state()
        progress_callback(0, 4)
        snaps.append(sleep_drain.stages_wire(ds, state.stage, True))
        progress_callback(3, 4)
        snaps.append(sleep_drain.stages_wire(ds, state.stage, True))
        progress_callback(4, 4)
        return {"changes": [], "relationships": [], "episode_cooccurrences": {}, "name_to_id": {}}

    monkeypatch.setattr("api.services.entity_resolver.resolve", resolve)
    _run(memory, cap=3)

    first, second, _ = snaps[0], snaps[1], None
    by_id = lambda snap: {s["id"]: s for s in snap}  # noqa: E731
    assert by_id(first)["read"] == {"id": "read", "unit": "conversations", "done": 3, "total": 3, "failed": 0, "state": "done"}
    assert by_id(first)["sort"]["state"] == "active" and by_id(first)["sort"]["total"] == 4
    assert (by_id(first)["sort"]["done"], by_id(second)["sort"]["done"]) == (0, 3)
    assert by_id(second)["sort"]["total"] == 4, "fixed when the stage starts"
    for stage_id in ("notice", "file"):
        assert by_id(second)[stage_id]["unit"] is None and by_id(second)[stage_id]["total"] is None, \
            "Notice and File carry no fraction: they count nothing that finished"


def test_a_failure_is_its_own_count_never_folded_into_read(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    rig = install(monkeypatch)
    ids = episode_ids(3)
    # A conversation failure is counted here; a CLI timeout now pauses the run
    # before sorting, rather than counting against this conversation (G171).
    rig.fail_exc = {ids[1]: engine_errors.EngineProtocolError("empty answer")}
    grabbed = {}

    async def look(extracted, existing, settings_, cancel_check=None, **_kw):
        ds = sleep_cycle.get_sleep_state().drain
        grabbed["wire"] = sleep_drain.to_wire(ds, completed=1, running=True)
        return {"changes": [], "relationships": [], "episode_cooccurrences": {}, "name_to_id": {}}

    monkeypatch.setattr("api.services.entity_resolver.resolve", look)
    _run(memory, cap=3)
    wire = grabbed["wire"]
    assert wire["batch_state"] == {"index": 1, "of": 1, "total": 3, "read": 2, "reading": 0, "failed": 1}
    read = wire["stages"][0]
    assert (read["done"], read["failed"], read["total"]) == (3, 1, 3), "3 of 3 finished, one of them a failure"


def test_elapsed_excludes_paused_time_and_freezes_when_the_run_ends():
    ds = sleep_drain.DrainState(drain_id="x", frozen_ids=["a"])
    ds.started_mono = 1000.0
    ds.paused_ms = 7000
    assert ds.elapsed_ms(now=1060.0) == 60000, "reading time only: the pause is its own figure"
    ds.ended_mono = 1090.0
    assert ds.elapsed_ms(now=5000.0) == 90000, "frozen at the end, the tail excluded"
    wire = sleep_drain.to_wire(ds)
    assert wire["elapsed_ms"] == 90000 and wire["paused_ms"] == 7000
    assert "remaining" not in " ".join(wire), "no time remaining anywhere (G107)"


# --------------------------------------------------------------------------- #
# by source
# --------------------------------------------------------------------------- #


def _two_origins(memory):
    for i, ep_id in enumerate(episode_ids(9)):
        path = memory / "episodes" / f"{ep_id}.md"
        parsed = markdown_parser.parse(path)
        fm = dict(parsed.frontmatter)
        fm["origin"] = "chatgpt-export" if i % 3 == 0 else "claude-export"
        markdown_parser.write(path, fm, parsed.body)


def test_by_origin_arithmetic_holds_at_every_step(tmp_path, monkeypatch):
    ids = episode_ids(9)
    memory = seed_bank(tmp_path, ids, extra=_two_origins)
    rig = install(monkeypatch)
    rig.fail_exc = {ids[4]: engine_errors.EngineProtocolError("nothing came back")}
    checks = []

    async def hook(batch_no, episodes):
        ds = sleep_cycle.get_sleep_state().drain
        _balanced(ds)
        checks.append(batch_no)
        if batch_no == 2:
            # another writer files one of the frozen ones mid-run: skipped, never lost from the sum
            path = memory / "episodes" / f"{ids[8]}.md"
            parsed = markdown_parser.parse(path)
            markdown_parser.write(path, {**parsed.frontmatter, "processed": True}, parsed.body)

    async def after_generate(n):
        _balanced(sleep_cycle.get_sleep_state().drain)

    rig.on_extract, rig.on_generate = hook, after_generate
    state = _run(memory)
    ds = state.drain
    _balanced(ds)
    assert checks == [1, 2, 3] and ds.finished
    totals = sleep_drain.origin_counts(ds)
    assert sum(c["frozen"] for c in totals.values()) == 9
    assert sum(c["filed"] for c in totals.values()) == 7 and sum(c["skipped"] for c in totals.values()) == 1
    assert sum(c["parked"] for c in totals.values()) == 1
    assert totals["chatgpt-export"]["frozen"] == 3 and totals["claude-export"]["frozen"] == 6


def test_arrivals_are_live_while_the_run_reads(tmp_path, monkeypatch):
    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids)
    rig = install(monkeypatch)
    live = []

    async def hook(batch_no, episodes):
        if batch_no == 1:
            markdown_parser.write(
                memory / "episodes" / "ep_2026-09-02_000.md",
                {"id": "ep_2026-09-02_000", "processed": False, "source": "mcp", "timestamp": "2026-09-02T09:00:00"},
                "Captured while the run was reading.")
        ds = sleep_cycle.get_sleep_state().drain
        unprocessed = len(sleep_progress.unprocessed_ids(memory))
        live.append((batch_no, sleep_drain.to_wire(ds, unprocessed=unprocessed)["arrived_since"],
                     ds.new_since.copy()))

    rig.on_extract = hook
    state = _run(memory)
    assert [(b, n) for b, n, _ in live] == [(1, 1), (2, 1)], "counted while the run goes, not only at its end"
    assert live[1][2] == {"claude-code": 1}, "by source at the next batch boundary"
    assert state.drain.arrived_since == 1


def test_the_owner_pages_beliefs_are_sampled_at_start_and_after_the_first_batch(tmp_path, monkeypatch):
    def owner_page(memory):
        page = memory / "entities" / "owner.md"
        body = claims.write_claims("The main person this memory belongs to.", [
            claims.Claim(id="c1", text="likes tea", subject="owner", predicate="likes", object="tea",
                         observer="owner", origin="mcp", valid_from="2026-09-01"),
            claims.Claim(id="c2", text="old fact", subject="owner", predicate="uses", object="x",
                         observer="owner", origin="mcp", valid_from="2026-08-01", valid_to="2026-08-30"),
        ])
        markdown_parser.write(page, {"type": "person", "name": "Owner", "owner": True, "status": "active",
                                     "confidence": 0.9}, body)

    ids = episode_ids(6)
    memory = seed_bank(tmp_path, ids, extra=owner_page)
    rig = install(monkeypatch)

    async def more_beliefs(n):
        if n == 1:   # batch 1's write adds two beliefs to the owner's page
            page = memory / "entities" / "owner.md"
            parsed = markdown_parser.parse(page)
            rows = claims.parse_claims(parsed.body) + [
                claims.Claim(id=f"n{i}", text=f"fact {i}", subject="owner", predicate="likes", object=f"o{i}",
                             observer="owner", origin="mcp", valid_from="2026-09-02") for i in (1, 2)]
            markdown_parser.write(page, parsed.frontmatter, claims.write_claims(parsed.body, rows))

    rig.on_generate = more_beliefs
    ds = _run(memory).drain
    assert ds.owner_beliefs == {"beliefs": 3, "at_start": 1, "after_first_batch": 3}, "closed claims are not beliefs"


def test_no_owner_page_means_no_owner_block_and_a_run_never_creates_one(tmp_path, monkeypatch):
    memory = seed_bank(tmp_path, episode_ids(3))
    install(monkeypatch)
    ds = _run(memory).drain
    assert ds.owner_beliefs is None and sleep_drain.to_wire(ds)["owner_page"] is None
    assert not (memory / "entities" / "owner.md").exists()


def test_first_run_is_true_only_when_the_bank_has_no_earlier_sleep_commit(tmp_path, monkeypatch):
    from drain_harness import git

    memory = seed_bank(tmp_path, episode_ids(3))
    install(monkeypatch)
    assert _run(memory, cid="sleep_first").drain.first_run is True
    assert any(s.startswith("Sleep cycle") for s in git(memory, "log", "--format=%s").splitlines())
    for i, ep_id in enumerate(episode_ids(2, day="2026-09-05")):
        markdown_parser.write(memory / "episodes" / f"{ep_id}.md",
                              {"id": ep_id, "processed": False, "source": "mcp",
                               "timestamp": f"2026-09-05T10:0{i}:00", "session_id": f"ses_{i}"}, "later")
    from api.services import sleep_debt

    sleep_debt._last_cycle_cache.clear()
    assert _run(memory, cid="sleep_second").drain.first_run is False


# --------------------------------------------------------------------------- #
# the stream
# --------------------------------------------------------------------------- #


def test_the_sse_block_moves_on_a_stage_tick_a_call_and_a_failure():
    ds = sleep_drain.DrainState(drain_id="x", frozen_ids=list("abcd"), batch_size=2, batches=2, batch=1)
    ds.live = sleep_drain.BatchLive(index=1, total=2, ids=["a", "b"])
    keys = {tuple(sleep_drain.to_sse(ds).items())}
    ds.live.sort_done = 1
    keys.add(tuple(sleep_drain.to_sse(ds).items()))
    ds.note_call()
    keys.add(tuple(sleep_drain.to_sse(ds).items()))
    ds.live.failed["a"] = "other"
    keys.add(tuple(sleep_drain.to_sse(ds).items()))
    assert len(keys) == 4, "each of them changes the change key: a tick, a call, a failure"
    assert "elapsedMs" not in sleep_drain.to_sse(ds) and "elapsed_ms" not in sleep_drain.to_sse(ds), \
        "a clock in the key would fire an event every tick"


def test_the_sse_block_never_scans_the_bank_per_tick(tmp_path, monkeypatch):
    ds = sleep_drain.DrainState(drain_id="x", frozen_ids=list("abcd"), batch_size=2, batches=2, batch=1)

    def boom(*a, **k):
        raise AssertionError("a per-tick scan")

    monkeypatch.setattr(bank_index, "files", boom)
    monkeypatch.setattr(sleep_progress, "unprocessed_ids", boom)
    monkeypatch.setattr(sleep_progress, "owner_beliefs", boom)
    sse = sleep_drain.to_sse(ds, 7)
    wire = sleep_drain.to_wire(ds, unprocessed=7)
    assert sse["arrived"] == 3 and wire["arrived_since"] == 3, "live from the debt count the tick already has"


def test_a_lingering_drain_of_another_bank_is_never_shown(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api import main
    from api.config import get_settings

    memory = seed_bank(tmp_path, episode_ids(2))
    other = tmp_path / "other-bank"
    ds = sleep_drain.DrainState(drain_id="sleep_old", frozen_ids=["a"], batch_size=3)
    ds.memory_path = other
    sleep_cycle.get_sleep_state().drain = ds
    main.app.dependency_overrides[get_settings] = lambda: settings(memory, sleep_max_episodes_per_cycle=3)
    try:
        assert TestClient(main.app).get("/sleep/status").json()["drain"] is None
        ds.memory_path = memory
        assert TestClient(main.app).get("/sleep/status").json()["drain"]["id"] == "sleep_old"
    finally:
        main.app.dependency_overrides.clear()
