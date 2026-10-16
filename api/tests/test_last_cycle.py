"""Details › Last cycle reads the newest FINISHED cycle from the backend (2026-10-16 review blocker).

A long drain, or one paused waiting on Continue, fills every history row the app holds with its own batches; the
backend walks git (bounded) and answers with the cycle before it — the run's own time, engine and whole cost."""
from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import config, main
from api.services import bank_index, cycle_usage, last_cycle, sleep_local, sleep_runs, telemetry
from api.services.telemetry import UsageEvent

BASE = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture
def bank(tmp_path, monkeypatch):
    monkeypatch.setenv("CICADA_TELEMETRY", "on")
    monkeypatch.setenv("CICADA_HOME", str(tmp_path / "home"))
    memory = tmp_path / "memory"
    (memory / "entities").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=memory, check=True)
    last_cycle.reset_cache()
    yield memory
    last_cycle.reset_cache()


class Bank:
    def __init__(self, memory):
        self.memory = memory
        self.n = 0
        self.runs: dict = {}

    def commit(self, when: datetime, engine: str, subject: str = "Sleep cycle") -> str:
        self.n += 1
        page = self.memory / "entities" / f"alpha-{self.n}.md"
        page.write_text(f"---\ntype: project\n---\nbody {self.n}\n")
        env = dict(os.environ, GIT_AUTHOR_DATE=_iso(when), GIT_COMMITTER_DATE=_iso(when))
        subprocess.run(["git", "add", "-A"], cwd=self.memory, check=True)
        subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m",
                        f"{subject} {when.date()}\n\nentities/alpha-{self.n}.md: created (source: n/a, trigger: x)"
                        f"\n\nCicada-Engine: {engine}"], cwd=self.memory, check=True, env=env)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.memory, capture_output=True, text=True,
                              check=True).stdout.strip()

    def batch(self, drain_id: str, index: int, total: int, when: datetime, engine: str, connection: str,
              cost: float | None, equiv: float | None = None, took_ms: int = 120_000) -> str:
        commit = self.commit(when, engine)
        cycle = f"{drain_id}-b{index}"
        call = UsageEvent(kind="llm_call", engine=engine, model="model-a", connection=connection,
                          billing="usage" if cost is not None else "subscription", input_tokens=10, output_tokens=5,
                          cost_usd=cost, equiv_cost_usd=equiv, ok=True,
                          refs={"cycle_id": cycle, "drain_id": drain_id})
        call.ts = _ts(when - timedelta(seconds=30))
        telemetry.record(call)
        row = UsageEvent(kind="sleep_run", engine=engine, connection=connection, duration_ms=took_ms,
                         refs={"cycle_id": cycle, "commit": commit, cycle_usage.TAGGED_REF: True,
                               "drain_id": drain_id, "batch": index, "batches": total})
        row.ts = _ts(when)
        telemetry.record(row)
        return commit

    def run(self, drain_id: str, started: datetime, state: str, batches: int, read_ms: int) -> None:
        self.runs[drain_id] = {
            "id": drain_id, "started_by": "user", "started_at": _iso(started),
            "finished_at": _iso(started + timedelta(milliseconds=read_ms)) if state == "finished" else None,
            "state": state, "frozen": batches * 25, "filed": batches * 25, "committed_batches": batches,
            "batches": batches, "read_ms": read_ms, "paused_ms": 0, "pauses": []}
        sleep_local.write_json(sleep_runs._path(self.memory, create=True),
                               {"order": list(self.runs), "runs": self.runs})


def _metered_run_then(bank_dir, state: str) -> tuple[Bank, str]:
    """A finished metered run (3 batches, its first call five days before its last commit), then a 20-batch run
    on the Claude plan that is still ``state``."""
    b = Bank(bank_dir)
    b.run("sched", BASE - timedelta(days=5), "finished", 3, read_ms=4_680_000)
    # A batch discarded five days back (a pause before it filed): its call counts, though no commit carries it and
    # it falls before the walk's oldest commit — the ledger read widens back to the run's own start.
    early = UsageEvent(kind="llm_call", engine="litellm", model="model-a", connection="byok-openrouter",
                       billing="usage", input_tokens=10, output_tokens=5, cost_usd=0.01, equiv_cost_usd=0.01, ok=True,
                       refs={"cycle_id": "sched-b0", "drain_id": "sched"})
    early.ts = _ts(BASE - timedelta(days=5))
    telemetry.record(early)
    b.batch("sched", 1, 3, BASE - timedelta(days=3), "litellm", "byok-openrouter", 0.02)
    b.batch("sched", 2, 3, BASE - timedelta(minutes=40), "litellm", "byok-openrouter", 0.04)
    last = b.batch("sched", 3, 3, BASE, "litellm", "byok-openrouter", 0.03, took_ms=229_000)
    b.run("plan", BASE + timedelta(hours=1), state, 20, read_ms=1_200_000)
    for i in range(1, 21):
        b.batch("plan", i, 20, BASE + timedelta(hours=1, minutes=i), "claude-cli", "claude-plan", None, equiv=0.5)
    return b, last


@pytest.mark.parametrize("state", ["running", "paused"])
def test_a_live_twenty_batch_drain_shows_the_finished_run_before_it(bank, state):
    _, last = _metered_run_then(bank, state)
    got = asyncio.run(last_cycle.latest(bank))
    assert got is not None
    assert got.commit_hash == last and got.drain_id == "sched" and got.state == "finished"
    assert got.duration_ms == 4_680_000                       # the run's reading time, not its last batch's 3 m 49 s
    assert got.engine == "litellm" and got.batches == 3
    assert got.usage_summary.basis == "charged"
    assert got.usage_summary.cost_usd == 0.1                  # every call of the run, the discarded batch's included
    assert got.usage_summary.connection == "byok-openrouter"


def test_once_the_plan_run_finishes_it_is_the_last_cycle_with_its_window_basis(bank):
    b, _ = _metered_run_then(bank, "running")
    assert asyncio.run(last_cycle.latest(bank)).drain_id == "sched"
    b.run("plan", BASE + timedelta(hours=1), "finished", 20, read_ms=1_200_000)   # the runs file moved: recomputed
    got = asyncio.run(last_cycle.latest(bank))
    assert got.drain_id == "plan" and got.duration_ms == 1_200_000 and got.engine == "claude-cli"
    assert got.usage_summary.engine == "claude-cli" and got.usage_summary.cost_usd is None


def test_a_plain_cycle_is_its_own_record_and_none_when_nothing_finished(bank):
    b = Bank(bank)
    assert asyncio.run(last_cycle.latest(bank)) is None
    commit = b.commit(BASE, "ollama")
    row = UsageEvent(kind="sleep_run", engine="ollama", connection="ollama-local", billing="free", duration_ms=61_000,
                     refs={"cycle_id": "c1", "commit": commit, cycle_usage.TAGGED_REF: True})
    row.ts = _ts(BASE)
    telemetry.record(row)
    last_cycle.reset_cache()
    got = asyncio.run(last_cycle.latest(bank))
    assert got.commit_hash == commit and got.drain_id is None and got.duration_ms == 61_000
    # Only a live run's batches, and nothing before: there truly is no finished cycle.
    other = bank.parent / "other"
    (other / "entities").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=other, check=True)
    o = Bank(other)
    o.run("live", BASE, "paused", 2, read_ms=60_000)
    o.batch("live", 1, 2, BASE + timedelta(minutes=1), "claude-cli", "claude-plan", None)
    assert asyncio.run(last_cycle.latest(other)) is None


def test_a_commit_with_no_ledger_row_after_a_live_run_began_is_that_runs(bank):
    b = Bank(bank)
    b.commit(BASE, "litellm")                                              # telemetry has no row for either
    b.run("live", BASE + timedelta(hours=1), "running", 1, read_ms=10_000)
    b.commit(BASE + timedelta(hours=1, minutes=5), "claude-cli")
    got = asyncio.run(last_cycle.latest(bank))
    assert got.engine == "litellm"


def test_the_walk_is_bounded_and_cached_per_head(bank, monkeypatch):
    assert last_cycle.WALK == 200
    b = Bank(bank)
    b.commit(BASE, "litellm")
    calls = []
    real = last_cycle._walk

    def counting(memory_path):
        calls.append(1)
        return real(memory_path)

    monkeypatch.setattr(last_cycle, "_walk", counting)
    monkeypatch.setattr(last_cycle, "INCOMPLETE_TTL_S", 3600.0)
    for _ in range(3):
        asyncio.run(last_cycle.latest(bank))
    assert len(calls) == 1
    b.commit(BASE + timedelta(minutes=5), "litellm")
    asyncio.run(last_cycle.latest(bank))
    assert len(calls) == 2


def test_the_status_route_always_sends_the_key(bank, monkeypatch):
    monkeypatch.setenv("CICADA_MEMORY_PATH", str(bank))
    config.get_settings.cache_clear()
    bank_index.invalidate()
    try:
        _metered_run_then(bank, "paused")
        body = TestClient(main.app).get("/sleep/status").json()
        assert body["lastFinishedCycle"]["drainId"] == "sched"
        assert body["lastFinishedCycle"]["usageSummary"]["costUsd"] == 0.1
    finally:
        config.get_settings.cache_clear()


def test_with_the_ledger_off_an_ended_run_is_still_found_by_its_span(bank, monkeypatch):
    b = Bank(bank)
    b.run("sched", BASE - timedelta(minutes=30), "finished", 2, read_ms=1_800_000)
    b.commit(BASE - timedelta(minutes=10), "litellm")
    last = b.commit(BASE - timedelta(minutes=1), "litellm")
    monkeypatch.setenv("CICADA_TELEMETRY", "off")
    got = asyncio.run(last_cycle.latest(bank))
    assert got.commit_hash == last and got.drain_id == "sched" and got.duration_ms == 1_800_000
    assert got.batches == 2 and got.usage_summary is None          # no ledger: the cost is unknown, never zero


def _row(commit: str, when: datetime, drain_id: str | None = None) -> UsageEvent:
    refs = {"cycle_id": f"c-{commit[:6]}", "commit": commit, cycle_usage.TAGGED_REF: True}
    if drain_id:
        refs.update({"drain_id": drain_id, "batch": 1, "batches": 1})
    ev = UsageEvent(kind="sleep_run", engine="litellm", connection="byok-openrouter", duration_ms=60_000, refs=refs)
    ev.ts = _ts(when)
    return ev


class _Reader:
    """A ledger reader that records the windows asked for and serves only the days inside them."""

    def __init__(self, events):
        self.events, self.calls = events, []

    def __call__(self, start=None, end=None):
        self.calls.append((start, end))
        return [e for e in self.events if (start is None or e.ts[:10] >= start.isoformat())
                and (end is None or e.ts[:10] <= end.isoformat())]


def test_the_ledger_window_opens_at_the_chosen_commit_or_its_runs_start_never_the_walks_end(bank):
    chosen, old = "a" * 40, "b" * 40
    commits = [(chosen, _iso(BASE), "litellm"), (old, _iso(BASE - timedelta(days=30)), "litellm")]
    reader = _Reader([_row(chosen, BASE), _row(old, BASE - timedelta(days=30))])
    got, complete = last_cycle.compute(commits, {}, reader)
    assert got.commit_hash == chosen and complete
    assert reader.calls == [((BASE - timedelta(days=1)).date(), None)]          # a plain cycle: its own day only
    # A run's batch: the window widens back to the run's own start — just the missing days — and no further.
    runs = {"r": {"id": "r", "state": "finished", "started_at": _iso(BASE - timedelta(days=5)), "read_ms": 1000}}
    early = UsageEvent(kind="llm_call", engine="litellm", connection="byok-openrouter", billing="usage", cost_usd=0.01,
                       ok=True, refs={"cycle_id": "r-b0", "drain_id": "r"})
    early.ts = _ts(BASE - timedelta(days=5))
    reader = _Reader([_row(chosen, BASE, drain_id="r"), early, _row(old, BASE - timedelta(days=30))])
    got, _ = last_cycle.compute(commits, runs, reader)
    assert got.drain_id == "r" and got.usage_summary.cost_usd == 0.01
    assert reader.calls == [((BASE - timedelta(days=1)).date(), None),
                            ((BASE - timedelta(days=6)).date(), (BASE - timedelta(days=2)).date())]


def test_the_miss_path_runs_off_the_event_loop(bank, monkeypatch):
    import threading

    seen = []
    monkeypatch.setattr(last_cycle, "_miss", lambda memory_path: (seen.append(threading.current_thread()), (None, True))[1])
    assert asyncio.run(last_cycle.latest(bank)) is None
    assert seen and seen[0] is not threading.main_thread()


def test_a_commit_with_no_ledger_row_is_complete_once_it_is_five_minutes_old(bank, monkeypatch):
    commit = "c" * 40
    commits = [(commit, _iso(BASE), "litellm")]
    fresh = last_cycle.compute(commits, {}, _Reader([]), now=BASE + timedelta(minutes=1))
    assert fresh[0].commit_hash == commit and fresh[1] is False                   # its row may still be coming
    old = last_cycle.compute(commits, {}, _Reader([]), now=BASE + timedelta(minutes=5))
    assert old[1] is True                                                         # a demo bank, a pre-ledger bank
    # So an old row-less commit is not recomputed on every poll.
    Bank(bank).commit(BASE, "litellm")
    walks = []
    real = last_cycle._walk
    monkeypatch.setattr(last_cycle, "_walk", lambda m: (walks.append(1), real(m))[1])
    monkeypatch.setattr(last_cycle, "INCOMPLETE_TTL_S", 0.0)
    for _ in range(3):
        assert asyncio.run(last_cycle.latest(bank)) is not None
    assert len(walks) == 1
