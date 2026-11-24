"""What each device says it has not sent the home yet (B3, 2026-11-24): counts only, kept beside the device rows.

A computer that holds captures it could not deliver (a session the home was away for, a transaction in its outbox) says
so the next time it reaches the home: a copy in its ``POST /sync/devices/me`` (every catch-up), a plain client on the
next capture it posts (``unsent`` beside the conversation). The home cannot know otherwise — a machine that never reaches
it leaves no trace in the home's log, which is exactly the case this answers.

``$CICADA_HOME/sync/device_unsent.json`` (0600), ``{device id: {waiting, held, rejected, at}}``: numbers and the time
the numbers last changed, never a title, a path or a body. It is the home's own file, outside every bank and git, one
row per device id; a device that never said anything has no row (``GET /devices/status`` serves ``unsent: null``).
``waiting`` is what is queued and will be sent, ``held`` what its memory refused for now, ``rejected`` what left
without landing (refused for good, or dropped by a bound), so a loss is a number the person can see."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

FILE = "device_unsent.json"
KEYS = ("waiting", "held", "rejected")
MAX_COUNT = 10_000_000
_LOCK = threading.Lock()


def _path() -> Path:
    from api.services import runtime_layout

    return runtime_layout.cicada_home() / "sync" / FILE


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def clean(counts) -> dict | None:
    """The three counts as small non-negative integers, or None when ``counts`` is not that shape."""
    if not isinstance(counts, dict):
        return None
    out = {}
    for key in KEYS:
        value = counts.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        out[key] = min(value, MAX_COUNT)
    return out


def record(device_id: str, counts, *, now: float | None = None) -> bool:
    """Keep what ``device_id`` says it holds. False when the shape is wrong (nothing is stored). Unchanged numbers
    write nothing."""
    cleaned = clean(counts)
    if cleaned is None or not device_id:
        return False
    path = _path()
    with _LOCK:
        data = _read(path)
        row = data.get(device_id)
        if isinstance(row, dict) and all(row.get(k) == cleaned[k] for k in KEYS):
            return True
        data[device_id] = {**cleaned, "at": now or time.time()}
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
    return True


def unsent() -> dict[str, int]:
    """``{device id: waiting + held}`` for every device that has said anything — what that machine still holds."""
    out = {}
    for device_id, row in _read(_path()).items():
        if isinstance(row, dict) and isinstance(row.get("waiting"), int) and isinstance(row.get("held"), int):
            out[device_id] = row["waiting"] + row["held"]
    return out
