"""Parked conversations — the ones that failed twice for their own reasons.

A conversation that Sleep could not read (an empty answer, a timeout, an
unparseable reply) gets one more try in the very next batch; a second failure
parks it. Parked conversations stay ``processed: false`` — they are still waiting,
still in the debt — but a run's freeze skips them, so one poison conversation
cannot make every Consolidate spend the same paid reads again. ``Retry`` unparks
them; a conversation that changed on disk since (the Stop hook grew it) is read
again by itself: the stamp is the episode file's ``(mtime_ns, size)``.

Machine-local (``sleep_local``), ids and enums only — never a title.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from api.services import sleep_local

FILE = "parked.json"


#: Audit A10 review — `valid()` prunes the store inside a read, and since the Sleep-debt scan moved to worker
#: threads it can run beside another `valid()` or a `park()` on the event loop. One lock orders every
#: read-modify-write, so a prune never overwrites a park made meanwhile and two writers never share the temp file.
_LOCK = threading.RLock()


def _path(memory_path: Path, *, create: bool = False) -> Path:
    return sleep_local.bank_dir(memory_path, create=create) / FILE


def _stamp(memory_path: Path, episode_id: str) -> list[int] | None:
    try:
        st = (Path(memory_path) / "episodes" / f"{episode_id}.md").stat()
    except OSError:
        return None
    return [st.st_mtime_ns, st.st_size]


def load(memory_path: Path) -> dict[str, dict]:
    data = sleep_local.read_json(_path(memory_path))
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _save(memory_path: Path, data: dict[str, dict]) -> None:
    path = _path(memory_path, create=True)
    if data:
        sleep_local.write_json(path, data)
    else:
        sleep_local.remove(path)


def park(memory_path: Path, episode_id: str, reason: str, attempts: int) -> None:
    with _LOCK:
        stamp = _stamp(memory_path, episode_id)
        if stamp is None:
            return
        data = load(memory_path)
        data[episode_id] = {"reason": reason, "attempts": int(attempts),
                            "parked_at": int(time.time()), "stamp": stamp}
        _save(memory_path, data)


def unpark(memory_path: Path, ids=None) -> list[str]:
    """Release ``ids`` (all when ``None``); returns the ones that were parked."""
    with _LOCK:
        data = load(memory_path)
        gone = [i for i in (list(data) if ids is None else [i for i in ids if i in data])]
        for i in gone:
            data.pop(i, None)
        if gone:
            _save(memory_path, data)
        return gone


def valid(memory_path: Path) -> dict[str, dict]:
    """The parked conversations that are still parked: the file exists and has not
    changed since. A changed one is dropped from the store here (it is read again)."""
    with _LOCK:
        data = load(memory_path)
        if not data:
            return {}
        keep: dict[str, dict] = {}
        for i, entry in data.items():
            if _stamp(memory_path, i) == entry.get("stamp"):
                keep[i] = entry
        if len(keep) != len(data):
            _save(memory_path, keep)
        return keep


def ids(memory_path: Path) -> set[str]:
    return set(valid(memory_path))
