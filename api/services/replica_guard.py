"""The backstop on a replica: no bank writer writes (G132 phase 1, ruling 51e2).

A replica is read-only: it never runs Sleep, never commits on its own, and every write it is asked for goes to the
home as a transaction (``tx_outbox``, ``replica_forward``). Routing is the first line (the hand-written route table,
cli_map's ``replica`` column); this is the second, in the writers themselves, so a path nobody routed still cannot
write: git's write subcommands (``git_service._git_sync``), the page writers (``markdown_parser.write`` /
``write_new``), the episode writer (``episode_ids.create_episode``). The ``_state.md`` refresh is a no-op instead
(``state_dictionary.refresh``): the home refreshes and commits it, and the copy follows.

The one writer allowed is the follower's own apply (:func:`applying`), which fast-forwards the copy to what the home
committed. A refused write raises :class:`ReplicaReadOnly`; a read path that meets it answers, never a 500.

Process-wide: the mode is ``runtime_layout.mode()`` (``CICADA_REPLICA_OF`` or ``$CICADA_HOME/replica_of``), read with
one environment lookup and one ``stat`` (cached by mtime), so the check is cheap on every write.
"""
from __future__ import annotations

import contextvars
import os
import threading
from contextlib import contextmanager
from pathlib import Path

TEXT = ("This computer keeps a read-only copy of your memory; changes are made on the computer that holds it, and "
        "this copy follows.")

_APPLYING: contextvars.ContextVar[bool] = contextvars.ContextVar("replica_applying", default=False)
_APPLY_THREADS: set[int] = set()
_GUARD = threading.Lock()
_CACHE: dict[str, tuple[object, bool]] = {}


class ReplicaReadOnly(PermissionError):
    """A bank write on a replica. Carries the plain sentence; the code is ``replica_read_only``."""

    code = "replica_read_only"

    def __init__(self, what: str = "write"):
        super().__init__(TEXT)
        self.what = what


def active() -> bool:
    """Is this process a replica? (env first, then the ``replica_of`` file by stat; client wins over replica.)"""
    from api.services import runtime_layout

    if (os.environ.get(runtime_layout.API_BASE_ENV) or "").strip():
        return False
    if (os.environ.get(runtime_layout.REPLICA_ENV) or "").strip():
        return True
    home = runtime_layout.cicada_home()
    if _file_says(home / runtime_layout.API_BASE_FILE):
        return False   # a client: never a replica (fail closed)
    return _file_says(home / runtime_layout.REPLICA_FILE)


def _file_says(path: Path) -> bool:
    """Is ``path`` a file with something in it? One ``stat`` per call, the read cached by (mtime, size)."""
    key = str(path)
    try:
        st = path.stat()
    except OSError:
        return False
    stamp = (st.st_mtime_ns, st.st_size)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        value = bool(path.read_bytes().strip())
    except OSError:
        value = False
    _CACHE[key] = (stamp, value)
    return value


def is_applying() -> bool:
    return _APPLYING.get() or threading.get_ident() in _APPLY_THREADS


@contextmanager
def applying():
    """The follower's apply: the only bank writer a replica runs."""
    token = _APPLYING.set(True)
    ident = threading.get_ident()
    with _GUARD:
        _APPLY_THREADS.add(ident)
    try:
        yield
    finally:
        with _GUARD:
            _APPLY_THREADS.discard(ident)
        _APPLYING.reset(token)


def check(what: str = "write") -> None:
    """Raise :class:`ReplicaReadOnly` on a replica, unless the follower's apply is writing."""
    if active() and not is_applying():
        raise ReplicaReadOnly(what)


def blocks() -> bool:
    """True when a write would be refused right now (for a writer that turns the refusal into a no-op)."""
    return active() and not is_applying()
