"""One bank's write admission: guarded writers hold it shared, Sleep waits it out to open its window (G183/G177).

``sleep_cycle.is_writing()`` is the one predicate behind every "Sleep is running" refusal, but a check and a write are
two moments: a writer that saw the window shut could still be writing when Sleep opened it and read the pages, and its
change was then overwritten or swept into Sleep's batch commit under Sleep's author. Admission closes that gap.

**A guarded writer** takes admission *shared* around its check, its page writes and its own commit —
:func:`admitted` asks ``is_writing()`` once the hold is taken and refuses (the caller's own 409 or sentence) when Sleep
holds the pages. Shared holds never wait on each other; they are counted, not owned by a thread. An ``async`` writer uses
:func:`run_admitted` / :func:`route`: its transaction runs on the writer loop (a daemon thread nothing tears down),
with the flock taken off any loop — so neither a cancelled request nor its loop's shutdown can release the hold while
its worker still writes, and a hold that lands after its waiter is gone releases itself. :func:`shared` and
:func:`admitted` are for synchronous code in a worker thread (never inside an ``async def``; a test keeps it so).
**Never across a model call or a network fetch:** fetch or synthesize first, then take the hold and check again (a
link save, an inbox conflict answer); a long networked job that cannot is a disclosed probe (``probe()``).

**Sleep** sets its flag first and then calls :func:`wait_for_writers` off the event loop: it returns once no shared
hold is left, so every writer that saw the window shut has finished its write and commit, and every later one sees the
flag and refuses. Closing the window needs nothing. The wait is bounded — logged past ``WAIT_LOG_S``, and past
``WAIT_MAX_S`` it answers False: Sleep then reads and writes nothing and pauses the run (``busy``), keeping its frozen
work for Continue. A timed-out wait is never treated as an open window (a paused process can resume and write).

**Across processes** (the stdio MCP server writes pages too) the hold is also an ``flock(LOCK_SH)``: always on
``$CICADA_HOME/sleep/<bank>/admission.lock`` (outside the bank — its stable identity, unchanged when git is scaffolded
under a holder), and also on the bank's ``.git`` path when it has one (nothing created; a different inode from the
bank directory ``page_lock`` locks), so processes that do not share ``CICADA_HOME`` still meet on a git bank. Sleep's side tries
``LOCK_EX`` without blocking until it succeeds, then lets go at once. A lock that exists but cannot be opened fails
closed: the writer gets :class:`AdmissionUnavailable`, and Sleep does not open its window. Keyed by the resolved path,
so ``bank``, ``bank/`` and a symlink are one bank.

**Lock order:** admission, then ``page_lock``, then git's write lock, then ``episode_lock`` — Sleep never waits for
admission while it holds any of them. Awake capture never takes admission.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
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


def _open_locks(key: str) -> list[int]:
    """Descriptors on the bank's admission inodes — none for a bank that does not exist (nothing to protect, and a
    lock never creates a bank). ALWAYS ``$CICADA_HOME/sleep/<bank>/admission.lock``, the bank's stable identity for
    its whole life (fix round 2: a holder that took the lock before the bank had a ``.git`` must still be seen after
    git is scaffolded); PLUS the bank's ``.git`` (a directory, or a worktree's file) when it has one, so two processes
    that do not share ``CICADA_HOME`` still meet on a git bank. Any other failure raises
    :class:`AdmissionUnavailable`: a writer that cannot coordinate must not write as if it had, and Sleep cannot
    confirm the bank is free."""
    if not os.path.isdir(key):
        return []
    fds: list[int] = []
    try:
        from api.services import sleep_local

        fds.append(os.open(sleep_local.bank_dir(Path(key)) / SIDECAR, os.O_RDONLY | os.O_CREAT, 0o600))
        git = os.path.join(key, ".git")
        if os.path.lexists(git):
            fds.append(os.open(git, os.O_RDONLY))
        return fds
    except OSError as exc:
        _close_all(fds)
        raise AdmissionUnavailable(exc.errno, f"the bank's write admission cannot be opened ({type(exc).__name__})")


def _close_all(fds) -> None:
    for fd in fds or ():
        os.close(fd)   # closing a descriptor releases its lock


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


def _acquire(key: str) -> list[int]:
    """One shared hold, taken in the calling thread (it may wait for the instant Sleep holds ``LOCK_EX``, so never
    on the event loop — :func:`run_admitted` calls it off the loop). Returns the held descriptors."""
    bank = _bank(key)
    with bank.cond:
        bank.holders += 1
    try:
        fds = _open_locks(key)
        try:
            for fd in fds:   # always in the same order: the sidecar, then .git
                fcntl.flock(fd, fcntl.LOCK_SH)
        except BaseException:
            _close_all(fds)
            raise
        return fds
    except BaseException:
        _release(key, None)
        raise


def _release(key: str, fds: list[int] | None) -> None:
    _close_all(fds)
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


class _Handoff:
    """Who releases a shared hold that arrives after its waiter was cancelled: whichever side comes second, under a
    thread lock — never a callback on an event loop that may be closed by then (fix round 2)."""
    __slots__ = ("lock", "fds", "taken", "abandoned")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.fds: list[int] | None = None
        self.taken = False
        self.abandoned = False


async def _acquire_off_loop(key: str) -> list[int]:
    """:func:`_acquire` in a worker thread, so no event loop waits on a flock. A hold that lands after the waiter was
    cancelled is released by the worker thread itself (or by the cancelled waiter if it landed first)."""
    handoff = _Handoff()

    def acquire() -> list[int] | None:
        fds = _acquire(key)
        with handoff.lock:
            if handoff.abandoned:
                _release(key, fds)
                return None
            handoff.fds, handoff.taken = fds, True
        return fds

    fut = asyncio.get_running_loop().run_in_executor(None, acquire)
    try:
        return await asyncio.shield(fut)
    except asyncio.CancelledError:
        with handoff.lock:
            if handoff.taken:
                _release(key, handoff.fds)   # it landed; nobody will use it
            else:
                handoff.abandoned = True     # the worker thread releases it when it lands
        raise


class TransactionLock:
    """An async lock any event loop may wait on — for a lock taken INSIDE an admitted transaction (a route's one-write
    lock). Transactions run on the writer loop while a caller (or a test) may hold the same lock from its own loop; an
    ``asyncio.Lock`` binds to one loop and is woken without a thread-safe call from another, so it would never wake.
    A ``threading.Lock`` polled without blocking any loop; cancellation-safe (a waiter that is cancelled never holds
    it). Contention is two quick taps on one route, so the poll's few milliseconds are invisible."""

    _POLL_S = 0.005

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def locked(self) -> bool:
        return self._lock.locked()

    async def acquire(self) -> bool:
        while not self._lock.acquire(blocking=False):
            await asyncio.sleep(self._POLL_S)
        return True

    def release(self) -> None:
        self._lock.release()

    async def __aenter__(self) -> None:
        await self.acquire()

    async def __aexit__(self, *exc) -> None:
        self.release()


# --- The writer loop: where every async admitted transaction runs (fix round 2, finding 4) -----------------------
#
# A shield keeps a cancelled request from cancelling its transaction, but not the request loop's own teardown, which
# cancels every task on it — the transaction's `finally` then released the hold while its threadpool worker still
# wrote. So transactions run on one long-lived loop in a daemon thread that nothing tears down: a request's loop
# going away cancels only its wait, and the hold is released when the transaction — workers and commit — is done.
# The caller's context (the request's pinned bank, …) is carried into the task. A lock a body takes is a
# `TransactionLock`, never an asyncio.Lock: another loop may hold it (a lint keeps it so).

_WRITER: tuple[asyncio.AbstractEventLoop, threading.Thread] | None = None
_WRITER_GUARD = threading.Lock()
_LIVE: set[concurrent.futures.Future] = set()
_LIVE_GUARD = threading.Lock()


def _writer_loop() -> asyncio.AbstractEventLoop:
    global _WRITER
    with _WRITER_GUARD:
        if _WRITER is None or not _WRITER[1].is_alive() or _WRITER[0].is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name="cicada-write-admission", daemon=True)
            thread.start()
            _WRITER = (loop, thread)
        return _WRITER[0]


def _settle(done: concurrent.futures.Future, task: "asyncio.Task") -> None:
    try:
        if task.cancelled():
            done.cancel()
        elif task.exception() is not None:
            done.set_exception(task.exception())
        else:
            done.set_result(task.result())
    except concurrent.futures.InvalidStateError:
        pass


def drain(timeout: float | None = None) -> bool:
    """Wait for every live admitted transaction to finish (the backend's shutdown calls it). True when none is left."""
    with _LIVE_GUARD:
        live = list(_LIVE)
    if not live:
        return True
    _done, pending = concurrent.futures.wait(live, timeout=timeout)
    return not pending


async def run_admitted(memory_path, body: Callable[[], Awaitable[T]], *,
                       refuse: Callable[[], BaseException] | None = None) -> T:
    """Run ``await body()`` as ONE admitted transaction — the async door (fix rounds 1 and 2).

    The transaction runs on the writer loop, in a copy of the caller's context: neither a cancelled request nor its
    loop's teardown can cancel it, and its hold — taken off any loop, released in the transaction's own ``finally`` —
    lasts until the body's workers and commit are done. With ``refuse``, Sleep holding the pages raises it before
    ``body`` runs. ``body`` must not await a model call or a network fetch (do that first, then re-check inside)."""
    key = _key(memory_path)
    _check_pin(key)
    context = contextvars.copy_context()
    done: concurrent.futures.Future = concurrent.futures.Future()

    async def transaction():
        fds = await _acquire_off_loop(key)
        try:
            if refuse is not None and holding():
                raise refuse()
            return await body()
        finally:
            _release(key, fds)

    loop = _writer_loop()
    with _LIVE_GUARD:
        _LIVE.add(done)

    def forget(f) -> None:
        with _LIVE_GUARD:
            _LIVE.discard(f)

    done.add_done_callback(forget)
    loop.call_soon_threadsafe(
        lambda: loop.create_task(transaction(), context=context).add_done_callback(lambda t: _settle(done, t)))
    try:
        return await asyncio.shield(asyncio.wrap_future(done))
    except asyncio.CancelledError:
        done.add_done_callback(_abandoned)
        raise


class WrongBank(RuntimeError):
    """Admission was asked for a bank other than the one this request is pinned to: nothing is admitted or written."""


def _check_pin(key: str) -> None:
    """A request runs in one bank (G183(d), ``bank_registry.pin_request_bank``), and its transaction is admitted on that
    bank: its body resolves ``settings.memory_path`` to the pin (the context is carried onto the writer loop), so
    admitting any other bank would let Sleep open the pinned bank under a live write. Fail closed."""
    from api.services import bank_registry

    pin = bank_registry.pinned_bank()
    if pin is not None and _key(pin.path) != key:
        raise WrongBank("write admission asked for a bank other than the request's pinned bank")


def _abandoned(done: concurrent.futures.Future) -> None:
    """A transaction whose caller went away still finishes; its failure is logged (by class), never lost silently."""
    if not done.cancelled() and done.exception() is not None:
        logger.warning(f"an admitted write finished after its request was cancelled and failed: "
                       f"{type(done.exception()).__name__}")


def route(*, refuse: Callable[[], BaseException] | None = None):
    """An ``async`` backend route as one admitted transaction (:func:`run_admitted`) — the bank is its ``settings``
    argument's ``memory_path``: the request's pinned bank (``bank_binding`` pins it when the request starts; a call
    outside a request is pinned here), so the admission, every write and the commit name one bank. With ``refuse``, its 409 while Sleep holds the pages; without, a hold
    that never refuses, for a route whose write changes shape inside instead (it asks :func:`holding`)."""
    def wrap(fn):
        @functools.wraps(fn)
        async def admitted_route(*args, **kwargs):
            settings = kwargs["settings"]
            root = getattr(settings, "memory_root", None)
            if root is not None:
                from api.services import bank_registry

                if bank_registry.pinned_bank() is None:   # called outside a request: pin now, once (G183(d))
                    bank_registry.pin_request_bank(root)
            return await run_admitted(settings.memory_path, lambda: fn(*args, **kwargs), refuse=refuse)
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
        fds = _open_locks(key)
    except AdmissionUnavailable as exc:
        logger.warning(f"Sleep cannot confirm no write is in progress ({exc.strerror}); it will not read the pages")
        return False
    try:
        while True:
            taken = 0
            try:
                for fd in fds:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    taken += 1
                return True   # no holder anywhere; let go at once (closing below)
            except BlockingIOError:
                for fd in fds[:taken]:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                if not waited(1):
                    return False
                time.sleep(_POLL_S)
    finally:
        _close_all(fds)
