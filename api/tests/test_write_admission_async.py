"""G183 fix round 1, findings 2 and 7 — an async writer's admission follows its transaction, not the awaiting route.

A cancelled request does not stop the threadpool worker it was awaiting, so the hold must last until that worker (and
the commit after it) is done: the route's transaction runs in its own task, shielded from the request, and the shared
flock is taken off the event loop.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from _synthetic_bank import _bank
from api.routers import entities
from api.services import entity_picture, sleep_cycle, write_admission


def _git(repo, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def bank(tmp_path):
    return _bank(tmp_path)


@pytest.fixture
def window(monkeypatch):
    state = {"writing": False}
    monkeypatch.setattr(sleep_cycle, "is_writing", lambda: state["writing"])
    return state


def _flip(bank, window, seen) -> threading.Thread:
    def flip():
        window["writing"] = True
        seen["drained"] = write_admission.wait_for_writers(bank, give_up_after=10)
        seen["head"] = _git(bank, "rev-parse", "HEAD").strip()
    t = threading.Thread(target=flip)
    t.start()
    return t


def _picture(monkeypatch, started, release):
    real = entity_picture.write_initials

    def write_initials(*a, **k):
        started.set()
        assert release.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(entity_picture, "write_initials", write_initials)
    return lambda settings: entities.use_entity_initials("alpha-project", settings=settings)


def _decay(monkeypatch, started, release):
    real = entities._rewrite_page_and_commit

    def rewrite(*a, **k):
        started.set()
        assert release.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(entities, "_rewrite_page_and_commit", rewrite)
    from api.models.schemas import EntityDecayUpdate

    body = EntityDecayUpdate.model_validate({"decayClass": "durable"})
    return lambda settings: entities.update_entity_decay("alpha-project", body, settings=settings)


@pytest.mark.parametrize("route", [_picture, _decay], ids=["picture", "decay"])
def test_a_cancelled_route_keeps_admission_until_its_worker_and_commit_are_done(bank, window, monkeypatch, route):
    started, release = threading.Event(), threading.Event()
    call = route(monkeypatch, started, release)
    settings = SimpleNamespace(memory_path=bank)
    head = _git(bank, "rev-parse", "HEAD").strip()
    seen: dict = {}

    async def scenario():
        task = asyncio.ensure_future(call(settings))
        assert await asyncio.to_thread(started.wait, 10), "the worker started"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert write_admission.holders(bank) == 1, "the request is gone; its transaction still holds the bank"
        flip = _flip(bank, window, seen)
        await asyncio.to_thread(flip.join, 0.3)
        assert flip.is_alive(), "Sleep must not open while the abandoned transaction is still writing"
        release.set()
        await asyncio.to_thread(flip.join, 10)
        for _ in range(200):   # the transaction's own task finishes on this loop
            if write_admission.holders(bank) == 0:
                break
            await asyncio.sleep(0.01)

    asyncio.run(scenario())
    assert seen["drained"] is True
    assert seen["head"] != head, "the transaction committed before Sleep's wait returned"
    assert seen["head"] == _git(bank, "rev-parse", "HEAD").strip()
    assert "Cicada-Author: user" in _git(bank, "log", "-1", "--format=%B")
    assert _git(bank, "status", "--porcelain") == ""
    assert write_admission.holders(bank) == 0


_EX_HOLDER = textwrap.dedent("""
    import fcntl, os, sys
    fd = os.open(sys.argv[1], os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX)
    print("held", flush=True)
    sys.stdin.readline()
""")


def test_admission_never_blocks_the_event_loop(bank, window):
    """Another process holds the inode exclusively for a while; entering admission from a coroutine must leave the
    loop free to run its callbacks meanwhile."""
    proc = subprocess.Popen([sys.executable, "-c", _EX_HOLDER, str(bank / ".git")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        ticks: list[float] = []

        async def scenario():
            stop = asyncio.Event()

            async def ticker():
                while not stop.is_set():
                    ticks.append(time.monotonic())
                    await asyncio.sleep(0.01)

            t = asyncio.ensure_future(ticker())
            threading.Timer(0.3, lambda: (proc.stdin.write("go\n"), proc.stdin.flush())).start()

            async def body():
                return "written"

            assert await write_admission.run_admitted(bank, body) == "written"
            stop.set()
            await t

        asyncio.run(scenario())
        assert len(ticks) >= 10, f"the loop ran {len(ticks)} callbacks while admission waited"
    finally:
        proc.kill()
        proc.wait(5)


def test_a_refused_transaction_runs_nothing(bank, window):
    window["writing"] = True
    ran = []

    async def body():
        ran.append(1)

    class Busy(Exception):
        pass

    with pytest.raises(Busy):
        asyncio.run(write_admission.run_admitted(bank, body, refuse=lambda: Busy()))
    assert ran == [] and write_admission.holders(bank) == 0


def test_no_async_function_takes_a_blocking_admission():
    """`shared()`/`admitted()` may wait on a flock: never inside an `async def` (run_admitted is the async door)."""
    import ast

    root = Path(__file__).resolve().parents[2]
    offenders = []
    for base in ("api", "mcp"):
        for path in sorted((root / base).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in rel or ".venv" in rel:
                continue
            tree = ast.parse(path.read_text(), filename=rel)
            for fn in ast.walk(tree):
                if not isinstance(fn, ast.AsyncFunctionDef):
                    continue
                for node in _own_body(fn):
                    if isinstance(node, ast.With):
                        for item in node.items:
                            call = item.context_expr
                            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                                    and call.func.attr in ("shared", "admitted")
                                    and isinstance(call.func.value, ast.Name)
                                    and call.func.value.id == "write_admission"):
                                offenders.append(f"{rel}:{node.lineno} ({fn.name})")
    assert offenders == []


def _own_body(fn):
    """The nodes of ``fn`` itself — a nested ``def`` (run in a worker thread) is its own scope."""
    import ast

    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(node))


# --- Fix round 2, finding 4: no teardown separates a hold from its worker; a closed loop strands no count ------------


def _wait_until(pred, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_loop_teardown_does_not_release_the_hold_before_the_worker_and_commit(bank, window, monkeypatch):
    started, release = threading.Event(), threading.Event()
    call = _picture(monkeypatch, started, release)
    settings = SimpleNamespace(memory_path=bank)
    head = _git(bank, "rev-parse", "HEAD").strip()

    async def request_then_shutdown():
        task = asyncio.ensure_future(call(settings))
        assert await asyncio.to_thread(started.wait, 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # returning tears this loop down: every task still on it is cancelled

    asyncio.run(request_then_shutdown())
    assert write_admission.holders(bank) == 1, "the worker still writes: its transaction still holds the bank"
    assert write_admission.wait_for_writers(bank, log_after=10, give_up_after=0.2) is False
    release.set()
    _wait_until(lambda: write_admission.holders(bank) == 0)
    assert _git(bank, "rev-parse", "HEAD").strip() != head, "the write was committed, not left dirty"
    assert "Cicada-Author: user" in _git(bank, "log", "-1", "--format=%B")
    assert _git(bank, "status", "--porcelain") == ""
    assert write_admission.wait_for_writers(bank, give_up_after=5) is True


def test_a_late_acquisition_on_a_closed_loop_releases_itself(bank, window):
    import fcntl
    import os

    from api.services import sleep_local

    lock = sleep_local.bank_dir(bank) / write_admission.SIDECAR
    fd = os.open(lock, os.O_RDONLY | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)   # Sleep's instant, stretched: the shared acquisition blocks in its thread
    loop = asyncio.new_event_loop()
    try:
        task = loop.create_task(write_admission._acquire_off_loop(write_admission._key(bank)))
        loop.run_until_complete(asyncio.sleep(0.1))
        task.cancel()
        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
    finally:
        loop.close()                  # no callback on this loop can ever run again
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    _wait_until(lambda: write_admission.holders(bank) == 0)
    assert write_admission.wait_for_writers(bank, give_up_after=5) is True


def test_drain_waits_for_live_transactions(bank, window):
    release = threading.Event()

    async def body():
        await asyncio.to_thread(release.wait, 10)
        return "done"

    results: list = []

    def caller():
        results.append(asyncio.run(write_admission.run_admitted(bank, body)))

    t = threading.Thread(target=caller)
    t.start()
    _wait_until(lambda: write_admission.holders(bank) == 1)
    assert write_admission.drain(timeout=0.2) is False, "a transaction is still writing"
    release.set()
    assert write_admission.drain(timeout=10) is True
    t.join(10)
    assert results == ["done"]


def test_the_backend_drains_admitted_writes_at_shutdown(monkeypatch):
    from fastapi.testclient import TestClient

    from api import main

    calls = []
    monkeypatch.setattr(write_admission, "drain", lambda timeout=None: calls.append(timeout) or True)
    with TestClient(main.app):
        pass
    assert calls == [main.SHUTDOWN_DRAIN_S]
