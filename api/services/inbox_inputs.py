"""The files beside the inbox that change what ``GET /inbox`` serves (speed 2026-10-29, review of #518).

``load_inbox`` reads three files outside ``inbox/``, ``entities/`` and ``episodes/``: the predicate map
(``informational``, the check vocabulary), the held names (a merge question about a parked name, G209) and the owner's
id in ``_state.md`` (page use). One function stamps them, for both the built list's key (``inbox_service``) and the
``inbox`` sync component (``sync_service``), so the ETag can never 304 over a change the read would show.

``_state.md`` is rewritten whenever the now-view moves; only its ``owner_id`` matters here, so the stamp carries that
value (read once per change of the file), not the file's time.
"""
from __future__ import annotations

import threading
from pathlib import Path

PREDICATES_FILE = "_predicates.yaml"   # `predicates.RUNTIME_FILE`
PENDING_FILE = "pending_entities.jsonl"   # `pending_store.PENDING_STORE_FILE`
STATE_FILE = "_state.md"

#: _state.md path -> ((inode, mtime_ns, size), owner id)
_OWNER: dict[str, tuple[tuple[int, int, int], str]] = {}
_LOCK = threading.Lock()


def file_stamp(path: Path) -> tuple[int, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_ino, st.st_mtime_ns, st.st_size)


def owner_token(memory_path: Path) -> str:
    """The owner's page id as ``_state.md`` names it ("" for none), parsed only when the file moved."""
    path = Path(memory_path) / STATE_FILE
    stamp = file_stamp(path)
    if stamp is None:
        return ""
    key = str(path)
    with _LOCK:
        hit = _OWNER.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    from api.services import everyday_names

    owner = everyday_names.owner_id(Path(memory_path)) or ""
    with _LOCK:
        _OWNER[key] = (stamp, owner)
    return owner


def side_stamps(memory_path: Path) -> tuple:
    mp = Path(memory_path)
    return (file_stamp(mp / PREDICATES_FILE), file_stamp(mp / PENDING_FILE), owner_token(mp))


def side_component(memory_path: Path) -> str:
    """The same stamps as text for a sync component: ``""`` when none of the three files exists, so a bank without
    them keeps its stamp byte for byte."""
    pred, pending, owner = side_stamps(memory_path)
    if pred is None and pending is None and not owner:
        return ""
    fmt = lambda s: "-" if s is None else f"{s[1]}.{s[2]}"   # noqa: E731 — mtime and size; the inode never matters to a reader
    return f":s{fmt(pred)}/{fmt(pending)}/{owner}"
