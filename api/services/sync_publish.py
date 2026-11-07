"""Whether this machine, the bank's home, publishes its log to the person's replicas (G132 phase 1, ruling 51).

**Off by default.** On only when ``CICADA_SYNC_PUBLISH=on`` or ``$CICADA_HOME/sync/settings.json`` holds
``{"publish": true}`` (written by ``PUT /sync/publish``, the master token's switch; Settings → Devices names it). The
environment wins over the file in both directions (``off`` closes a file's ``true``). Off, the publishing routes answer
404, nothing is written under ``$CICADA_HOME/sync/``, and the capture writers record nothing — the lifespan, the MCP
door and every client route are what they were (``test_sync_off_unchanged.py``).

**A demo bank is never published** (ruling 51e3), nor a bank that is not its own git repository.

Everything this feature keeps lives under ``$CICADA_HOME/sync/<bank key>/`` (``sleep_local.bank_key``: the bank's name
plus a hash of where it lives), outside every bank and git: the log's sidecar index and the capture step's records.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from api.services.auth import cicada_home

ENV = "CICADA_SYNC_PUBLISH"
SETTINGS_FILE = "settings.json"
_ON = frozenset({"on", "1", "true", "yes"})
_OFF = frozenset({"off", "0", "false", "no"})

#: ``(mtime_ns, size) -> publish`` for the settings file, so the capture path's check is one ``stat``.
_CACHE: dict[str, tuple[tuple[int, int], bool]] = {}
_GUARD = threading.Lock()


def _root(create: bool = False) -> Path:
    """``$CICADA_HOME/sync`` — never created by a read."""
    home = Path(os.environ.get("CICADA_HOME") or str(Path.home() / ".cicada")).expanduser()
    root = home / "sync"
    if create:
        cicada_home()
        root.mkdir(mode=0o700, exist_ok=True)
        os.chmod(root, 0o700)
    return root


def _from_file() -> bool:
    path = _root() / SETTINGS_FILE
    try:
        st = path.stat()
    except OSError:
        return False
    stamp = (st.st_mtime_ns, st.st_size)
    key = str(path)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = isinstance(data, dict) and data.get("publish") is True
    except (OSError, ValueError):
        value = False
    _CACHE[key] = (stamp, value)
    return value


def source() -> str:
    """Where the answer comes from: ``env``, ``settings`` or ``default``."""
    raw = (os.environ.get(ENV) or "").strip().lower()
    if raw in _ON or raw in _OFF:
        return "env"
    return "settings" if (_root() / SETTINGS_FILE).exists() else "default"


def enabled() -> bool:
    """Is publishing on for this machine? Cheap: an environment read and one ``stat``."""
    raw = (os.environ.get(ENV) or "").strip().lower()
    if raw in _ON:
        return True
    if raw in _OFF:
        return False
    return _from_file()


def set_enabled(value: bool) -> None:
    """The person's switch (the master token's ``PUT /sync/publish``): atomic, 0600, outside every bank."""
    root = _root(create=True)
    path = root / SETTINGS_FILE
    tmp = root / f".{SETTINGS_FILE}.{os.getpid()}.tmp"
    with _GUARD:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"publish": bool(value)}, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)


def publishable(memory_path) -> bool:
    """Publishing is on and this bank may be published: its own git repository, never a demo."""
    if not enabled():
        return False
    mp = Path(memory_path)
    if not (mp / ".git").exists():
        return False
    from api.services import demo_guard

    return not demo_guard.is_demo(mp)


def bank_dir(memory_path, *, create: bool = True) -> Path:
    """``$CICADA_HOME/sync/<bank key>/`` (0700). Callers create it only while publishing is on."""
    from api.services import sleep_local

    folder = _root(create=create) / sleep_local.bank_key(Path(memory_path))
    if create:
        folder.mkdir(mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
    return folder
