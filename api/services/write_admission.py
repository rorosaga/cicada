"""One bank's write admission: guarded writers hold it shared, Sleep waits it out to open its window (G183/G177).

``sleep_cycle.is_writing()`` is the one predicate behind every "Sleep is running" refusal, but a check and a write are
two moments: a writer that saw the window shut could still be writing when Sleep opened it and read the pages, and its
change was then overwritten or swept into Sleep's batch commit under Sleep's author. Admission closes that gap.

**A guarded writer** takes admission *shared* around its check, its page writes and its own commit —
:func:`admitted` asks ``is_writing()`` once the hold is taken and refuses (the caller's own 409 or sentence) when Sleep
holds the pages. Shared holds never wait on each other; they are counted, not owned by a thread. An ``async`` writer uses
:func:`run_admitted` / :func:`route`: its transaction runs in its own task, shielded from the request, with the flock
taken off the loop — so a cancelled request cannot release the hold while its worker still writes. :func:`shared` and
:func:`admitted` are for synchronous code in a worker thread (never inside an ``async def``; a test keeps it so).
**Never across a model call or a network fetch:** fetch or synthesize first, then take the hold and check again (a
link save, an inbox conflict answer); a long networked job that cannot is a disclosed probe (``probe()``).

**Sleep** sets its flag first and then calls :func:`wait_for_writers` off the event loop: it returns once no shared
hold is left, so every writer that saw the window shut has finished its write and commit, and every later one sees the
flag and refuses. Closing the window needs nothing. The wait is bounded — logged past ``WAIT_LOG_S``, and past
``WAIT_MAX_S`` it answers False: Sleep then reads and writes nothing and pauses the run (``busy``), keeping its frozen
work for Continue. A timed-out wait is never treated as an open window (a paused process can resume and write).

**Across processes** (the stdio MCP server writes pages too) the hold is also an ``flock(LOCK_SH)``: on the bank's
``.git`` path when it has one (nothing created; a different inode from the bank directory ``page_lock`` locks), else on
``$CICADA_HOME/sleep/<bank>/admission.lock`` (outside the bank; processes must share ``CICADA_HOME``). Sleep's side tries
``LOCK_EX`` without blocking until it succeeds, then lets go at once. A lock that exists but cannot be opened fails
closed: the writer gets :class:`AdmissionUnavailable`, and Sleep does not open its window. Keyed by the resolved path,
so ``bank``, ``bank/`` and a symlink are one bank.

**Lock order:** admission, then ``page_lock``, then git's write lock, then ``episode_lock`` — Sleep never waits for
admission while it holds any of them. Awake capture never takes admission.
"""
from __future__ import annotations

import asyncio
import fcntl
import functools
import logging
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Awaitable, Callable, Iterator, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

#: Sleep says it is waiting after this long, and proceeds after the second.
WAIT_LOG_S = 5.0
WAIT_MAX_S = 60.0
_POLL_S = 0.02


class SleepHolding(Exception):
    """Admitted, but Sleep holds the pages: write nothing."""


class _Bank:
    __slots__ = ("holders", "cond")

    def __init__(self) -> None:
        self.holders = 0
        self.cond = threading.Condition()


_BANKS: dict[str, _Bank] = {}
_BANKS_GUARD = threading.Lock()


def _key(memory_path) -> str:
    return os.path.realpath(os.fspath(memory_path))


def _bank(key: str) -> _Bank:
    with _BANKS_GUARD:
        return _BANKS.setdefault(key, _Bank())


class AdmissionUnavailable(OSError):
    """The bank's admission lock exists but cannot be opened: no writer may assume it is admitted (fail closed)."""


#: The lock file for a bank with no ``.git``: in the bank's machine-local folder, never inside the bank.
SIDECAR = "admission.lock"


def _open_lock(key: str) -> int | None:
    """A descriptor on the bank's admission inode, or None for a bank that does not exist (nothing to protect, and
    a lock never creates a bank). The bank's ``.git`` (a directory, or a worktree's file) when it has one; otherwise
    ``$CICADA_HOME/sleep/<bank>/admission.lock`` — the same folder Sleep's sidecars use, so every process that shares
    ``CICADA_HOME`` meets on one inode. Any other failure raises :class:`AdmissionUnavailable`: a writer that cannot
    coordinate must not write as if it had, and Sleep cannot confirm the bank is free."""
    git = os.path.join(key, ".git")
    try:
        if os.path.lexists(git):
            return os.open(git, os.O_RDONLY)
        if not os.path.isdir(key):
            return None
        from api.services import sleep_local

        lock = sleep_local.bank_dir(Path(key)) / SIDECAR
        return os.open(lock, os.O_RDONLY | os.O_CREAT, 0o600)
    except OSError as exc:
        raise AdmissionUnavailable(exc.errno, f"the bank's write admission cannot be opened ({type(exc).__name__})")


def holders(memory_path) -> int:
    """How many shared holds this process has on the bank (a test seam)."""
    return _bank(_key(memory_path)).holders


@contextmanager
def shared(memory_path) -> Iterator[None]:
    """Hold the bank's admission shared — for a writer whose answer to "is Sleep holding the pages?" changes what it
    writes rather than refusing (it asks :func:`holding` inside). Most writers want :func:`admitted`."""
    key = _key(memory_path)
    fd = _acquire(key)
    try:
        yield
    finally:
        _release(key, fd)


def _acquire(key: str) -> int | None:
    """One shared hold, taken in the calling thread (it may wait for the instant Sleep holds ``LOCK_EX``, so never
    on the event loop — :func:`run_admitted` calls it off the loop)."""
    bank = _bank(key)
    with bank.cond:
        bank.holders += 1
    try:
        fd = _open_lock(key)
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_SH)
            except BaseException:
                os.close(fd)
                raise
        return fd
    except BaseException:
        _release(key, None)
        raise


def _release(key: str, fd: int | None) -> None:
    if fd is not None:
        os.close(fd)   # closing the descriptor releases its lock
    bank = _bank(key)
    with bank.cond:
        bank.holders -= 1
        bank.cond.notify_all()


def holding() -> bool:
    """Is Sleep holding the pages? Asked INSIDE an admission, where the answer stays true for the rest of the hold:
    a window cannot open under a shared holder. Lazily imported (``sleep_cycle`` sits above every writer), and read
    through the module so the suite's substitutions apply."""
    from api.services import sleep_cycle

    return bool(sleep_cycle.is_writing())


def probe() -> bool:
    """The same question asked WITHOUT admission — an answer that may be stale by the next line. Only for a reader
    (a status, a derived index, a queue outside the bank) or a long networked job's early refusal; the allowlist is
    ``test_write_admission_sites.py``. A page writer uses :func:`admitted`."""
    return holding()


@contextmanager
def admitted(memory_path, *, refuse: Callable[[], BaseException] | None = None) -> Iterator[None]:
    """Hold the bank's admission shared and refuse when Sleep holds the pages — around the check, the page writes and
    the writer's own commit. ``refuse`` builds the caller's own refusal (a 409); :class:`SleepHolding` otherwise."""
    with shared(memory_path):
        if holding():
            raise refuse() if refuse is not None else SleepHolding()
        yield


async def _acquire_off_loop(key: str) -> int | None:
    """:func:`_acquire` in a worker thread, so the event loop never waits on a flock. If the awaiting task is
    cancelled meanwhile, the hold the thread then gets is released when it arrives — never leaked."""
    fut = asyncio.get_running_loop().run_in_executor(None, _acquire, key)
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        fut.add_done_callback(lambda f: None if f.cancelled() or f.exception() else _release(key, f.result()))
        raise


async def run_admitted(memory_path, body: Callable[[], Awaitable[T]], *,
                       refuse: Callable[[], BaseException] | None = None) -> T:
    """Run ``await body()`` as ONE admitted transaction — the async door (fix round 1, findings 2 and 7).

    The transaction runs in its own task, shielded from the caller: a cancelled request does not stop the threadpool
    worker it was awaiting, so the hold must last until that worker and the commit after it are done — it is released
    in the transaction's own ``finally``, never in the cancelled caller's. The flock is taken off the loop. With
    ``refuse``, Sleep holding the pages raises it before ``body`` runs. ``body`` must not await a model call or a
    network fetch (do that first, then re-check inside)."""
    key = _key(memory_path)

    async def transaction():
        fd = await _acquire_off_loop(key)
        try:
            if refuse is not None and holding():
                raise refuse()
            return await body()
        finally:
            _release(key, fd)

    task = asyncio.ensure_future(transaction())
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.add_done_callback(_abandoned)
        raise


def _abandoned(task: "asyncio.Task") -> None:
    """A transaction whose caller went away still finishes; its failure is logged (by class), never lost silently."""
    if not task.cancelled() and task.exception() is not None:
        logger.warning(f"an admitted write finished after its request was cancelled and failed: "
                       f"{type(task.exception()).__name__}")


def route(*, refuse: Callable[[], BaseException] | None = None):
    """An ``async`` backend route as one admitted transaction (:func:`run_admitted`) — the bank is its ``settings``
    argument's ``memory_path``, resolved once. With ``refuse``, its 409 while Sleep holds the pages; without, a hold
    that never refuses, for a route whose write changes shape inside instead (it asks :func:`holding`)."""
    def wrap(fn):
        @functools.wraps(fn)
        async def admitted_route(*args, **kwargs):
            return await run_admitted(kwargs["settings"].memory_path, lambda: fn(*args, **kwargs), refuse=refuse)
        admitted_route.__write_admission__ = "admitted" if refuse is not None else "held"
        return admitted_route
    return wrap


def wait_for_writers(memory_path, *, log_after: float | None = None, give_up_after: float | None = None,
                     clock: Callable[[], float] = time.monotonic) -> bool:
    """Sleep's side, called right AFTER its flag is set and before it reads a page: wait until no writer holds the
    bank's admission. True only once none does. False when ``give_up_after`` (``WAIT_MAX_S``) passed first, or the
    lock cannot be opened — the caller must then NOT read or write a page (Sleep pauses; fix round 1). Blocks — call
    it off the event loop."""
    log_after = WAIT_LOG_S if log_after is None else log_after
    give_up_after = WAIT_MAX_S if give_up_after is None else give_up_after
    key = _key(memory_path)
    bank = _bank(key)
    start = clock()
    logged = False

    def waited(n: int) -> bool:
        nonlocal logged
        elapsed = clock() - start
        if not logged and elapsed >= log_after:
            logged = True
            logger.info(f"Sleep is waiting for {n} write(s) in progress to finish before it reads the pages")
        if elapsed >= give_up_after:
            logger.warning(f"a write in progress did not finish in {give_up_after:.0f}s; Sleep will not read the "
                           "pages and pauses instead")
            return False
        return True

    with bank.cond:
        while bank.holders:
            if not waited(bank.holders):
                return False
            bank.cond.wait(_POLL_S)
    try:
        fd = _open_lock(key)
    except AdmissionUnavailable as exc:
        logger.warning(f"Sleep cannot confirm no write is in progress ({exc.strerror}); it will not read the pages")
        return False
    if fd is None:
        return True
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True   # no holder anywhere; let go at once (closing below)
            except BlockingIOError:
                if not waited(1):
                    return False
                time.sleep(_POLL_S)
    finally:
        os.close(fd)
