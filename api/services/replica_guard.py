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


#: The mode the backend STARTED in (review of #567): set by its lifespan, so writing or removing ``replica_of`` while it
#: runs changes nothing until it starts again — a running home never half-switches. None outside a backend (the stdio
#: MCP server and the command line start fresh, and read the file once per process anyway).
_FROZEN: list[bool | None] = [None]


def freeze() -> bool:
    """Fix this process's answer to :func:`active` as it is now (the backend's lifespan, at start)."""
    _FROZEN[0] = None
    _FROZEN[0] = _live()
    return _FROZEN[0]


def thaw() -> None:
    _FROZEN[0] = None


def active() -> bool:
    """Is this process a replica? The mode it started in when a backend froze it; otherwise env first, then the
    ``replica_of`` file by stat (client wins over replica)."""
    if _FROZEN[0] is not None:
        return _FROZEN[0]
    return _live()


def _live() -> bool:
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


_COPY_CACHE: dict[str, tuple[object, bool]] = {}


def active_bank_is_copy() -> bool:
    """Is the active bank a copy (``replica: true`` in ``banks.yaml``)? On a computer no longer in replica mode it must
    never be written (review of #567): Sleep, capture and every writer would let it drift from its home. The registry
    is read once per change (stat-cached); a missing or unreadable one is no copy."""
    try:
        from api.config import get_settings
        from api.services import bank_registry

        root = Path(get_settings().memory_root)
        reg = bank_registry.registry_path(root)
        st = reg.stat()
    except Exception:  # noqa: BLE001 — no registry, no settings: nothing is a copy
        return False
    stamp = (st.st_mtime_ns, st.st_size)
    cached = _COPY_CACHE.get(str(reg))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        registry = bank_registry.load_registry(root)
        record = (registry.get("banks") or {}).get(registry.get("active"))
        value = bool(isinstance(record, dict) and record.get("replica"))
    except Exception:  # noqa: BLE001
        value = False
    _COPY_CACHE[str(reg)] = (stamp, value)
    return value


def check(what: str = "write") -> None:
    """Raise :class:`ReplicaReadOnly` on a replica — or on a copy left active outside replica mode — unless the
    follower's apply is writing."""
    if blocks():
        raise ReplicaReadOnly(what)


def blocks() -> bool:
    """True when a write would be refused right now (for a writer that turns the refusal into a no-op)."""
    if is_applying():
        return False
    return active() or active_bank_is_copy()
