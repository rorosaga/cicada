"""File-change events for the SSE tick (2026-10-16 perf, owner decision 2).

While the app is open, ``GET /sync/events`` recomputes the bank's version and Sleep debt once a second: a stat of every
page, episode, hub and inbox item (~8,800 files at owner scale, ~28-34 ms of CPU every second). Here one watcher per
bank counts the file-system changes the OS reports — FSEvents on macOS, inotify on Linux, through ``watchfiles``, which
``uvicorn[standard]`` already installs — and the ticker (``sync_ticker``) re-walks the bank only when the count moved,
or when its last full walk is :data:`FALLBACK_S` old: the safety net for an event the OS dropped or coalesced away.

**Never trusted alone.** A watcher is used only while it is :attr:`BankWatch.healthy` — its notifier started and its
thread is running — and only for the root it was started on (a bank directory deleted and made again is a new
watcher). Without ``watchfiles``, on a notifier error, or with ``CICADA_SYNC_WATCH=off``, :func:`for_bank` answers
``None`` and the tick walks the bank every second exactly as before. ``/sync/version``, every ETag and every read path
stay exact per request: only the stream's idle tick reads the count.

**What counts.** Any change under the bank except git's own bookkeeping (``.git/``, read separately each tick through
``git_head``) and the derived index databases at the bank's root (written in the background, read by no component).
Also the bank's machine-local folder (``sleep_local``): the parked list and the paused-run record the debt reads.
"""
from __future__ import annotations

import itertools
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: A full walk at least this often, events or none.
FALLBACK_S = 10.0
#: Once a change is seen, how long the notifier waits for more before reporting (ms), and at most (ms).
STEP_MS = 100
DEBOUNCE_MS = 400
#: How often the notifier thread wakes with nothing to report, to notice a stop (ms).
TIMEOUT_MS = 2_000
#: A watcher nobody asked about for this long is stopped (a bank switched away from, the app closed).
IDLE_S = 60.0

_IGNORED_ROOT_FILES = ("search_index.db", "vector_index.db")
#: Every watcher's own number: a tick remembers which watcher's count it read, so a new watcher (a bank directory made
#: again, a notifier restarted) whose count happens to equal the old one never vouches for the old one's listings.
_GENERATIONS = itertools.count(1)


def enabled() -> bool:
    return os.environ.get("CICADA_SYNC_WATCH", "on").strip().lower() not in ("off", "0", "false", "no")


class BankWatch:
    """One bank's change counter, fed by a notifier thread."""

    def __init__(self, bank: Path, extra: list[Path] | None = None) -> None:
        self.bank = Path(os.path.realpath(bank))
        self.roots = [self.bank, *[Path(p) for p in (extra or []) if Path(p).is_dir()]]
        st = os.stat(self.bank)
        self.identity = (st.st_dev, st.st_ino)
        self.seq = 0
        self.generation = next(_GENERATIONS)
        self.last_used = time.monotonic()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._started = threading.Event()
        self._failed = False
        self._git = os.path.join(str(self.bank), ".git")
        self._thread = threading.Thread(target=self._run, name="cicada-bank-watch", daemon=True)
        self._thread.start()
        self._started.wait(5.0)

    @property
    def healthy(self) -> bool:
        return self._started.is_set() and not self._failed and not self._stop.is_set() and self._thread.is_alive()

    def same_root(self) -> bool:
        """The bank directory is still the one this watcher was started on."""
        try:
            st = os.stat(self.bank)
        except OSError:
            return False
        return (st.st_dev, st.st_ino) == self.identity

    def stop(self) -> None:
        self._stop.set()

    def bump(self) -> None:
        with self._lock:
            self.seq += 1

    def _counts(self, path: str) -> bool:
        if path == self._git or path.startswith(self._git + os.sep):
            return False
        parent, name = os.path.split(path)
        if parent == str(self.bank) and name.startswith(_IGNORED_ROOT_FILES):
            return False
        return True

    def _run(self) -> None:
        try:
            from watchfiles._rust_notify import RustNotify

            notify = RustNotify([str(p) for p in self.roots], False, False, 300, True, True)
        except Exception as exc:  # noqa: BLE001 — no notifier: the tick walks every second, as before
            logger.info(f"file-change events unavailable for the bank ({type(exc).__name__}); polling each second")
            self._failed = True
            self._started.set()
            return
        self._started.set()
        try:
            while not self._stop.is_set():
                raw = notify.watch(DEBOUNCE_MS, STEP_MS, TIMEOUT_MS, self._stop)
                if raw == "stop":
                    break
                # Every path is looked at (no short-circuit): a batch is a handful of paths, and a test waiting for
                # a marker it wrote sees it whatever else the batch holds (`test_sync_watch._settle`).
                if isinstance(raw, set) and [path for _, path in raw if self._counts(path)]:
                    self.bump()
        except Exception as exc:  # noqa: BLE001
            logger.info(f"file-change events stopped for the bank ({type(exc).__name__}); polling each second")
            self._failed = True
        finally:
            try:
                notify.close()
            except Exception:  # noqa: BLE001
                pass


_watches: dict[str, BankWatch] = {}
#: A bank whose notifier failed is not retried before this (seconds), so a broken notifier costs one try a minute.
RETRY_S = 60.0
_failed_at: dict[str, float] = {}
_guard = threading.Lock()


def for_bank(memory_path: Path) -> BankWatch | None:
    """The bank's running watcher, started on first use; ``None`` when events are off or unavailable (then the
    caller walks the bank each tick). Stops the watchers nobody asked about for :data:`IDLE_S`."""
    if not enabled():
        return None
    key = os.path.realpath(os.fspath(memory_path))
    now = time.monotonic()
    with _guard:
        for other, w in list(_watches.items()):
            if other != key and now - w.last_used > IDLE_S:
                w.stop()
                _watches.pop(other, None)
        watch = _watches.get(key)
        if watch is not None and (not watch.healthy or not watch.same_root()):
            watch.stop()
            watch = None
            _watches.pop(key, None)
        if watch is None:
            if not os.path.isdir(key) or now - _failed_at.get(key, -RETRY_S) < RETRY_S:
                return None
            try:
                from api.services import sleep_local

                extra = [sleep_local.bank_dir(Path(key), create=False)]
            except Exception:  # noqa: BLE001
                extra = []
            try:
                watch = BankWatch(Path(key), extra)
            except OSError:
                return None
            if not watch.healthy:
                _failed_at[key] = now
                return None
            _watches[key] = watch
        watch.last_used = now
    return watch if watch.healthy else None


def stop_all() -> None:
    """Stop every watcher (tests; shutdown)."""
    with _guard:
        for w in _watches.values():
            w.stop()
        _watches.clear()
        _failed_at.clear()
