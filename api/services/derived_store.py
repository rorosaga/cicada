"""A small on-disk home for a read model's derived state, outside every bank (G246, ruling 81).

A read model that answers from a bank's files and is expensive in a fresh process (it parses thousands of headers) may keep
what it derived beside the bank's stat-stamps, so the next fresh process reads a megabyte instead of re-reading the bank.
What lives here is **derived and disposable** — the rails every caller keeps:

* ``$CICADA_HOME/derived/<bank name>-<hash of where it lives>/<name>.json``: outside the bank and git, so it is never
  committed, never synced to another computer, never served by a route or tool, and holds only what the bank's own files
  say (no query, no new fact).
* **Keyed by the bank it was made from.** The folder name carries a hash of the bank's resolved path and the file repeats
  the resolved path and a ``tag`` (the caller's record version, the release, and the source of every module its records are made with); a file that names
  another bank, another tag or another store format is ignored, never read as an answer. A second bank, a bank switch or a
  bank restored at another path therefore can never read this bank's records.
* **Rebuilt silently.** A missing, unreadable, truncated or stale file is "nothing stored": :func:`load` returns ``None``
  and the caller derives from the bank, then :func:`save` writes again. Nothing here raises into a read.
* Written atomically (a temporary file, then a rename), 0600 in a 0700 folder.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

from loguru import logger

from api.services.auth import cicada_home

DIRNAME = "derived"
#: The file format. A reader of another format ignores the file.
FORMAT = 1


def _resolved(memory_path: Path) -> str:
    try:
        return str(Path(memory_path).resolve())
    except OSError:
        return str(Path(memory_path))


def bank_key(memory_path: Path) -> str:
    """``<name>-<8 hex of the resolved path's hash>``: two banks under different roots may share a name, and never share a
    folder here."""
    path = Path(memory_path)
    return f"{path.name or 'default'}-{hashlib.sha1(_resolved(path).encode()).hexdigest()[:8]}"


def folder(memory_path: Path, home: Path | None = None) -> Path:
    return (home if home is not None else cicada_home()) / DIRNAME / bank_key(memory_path)


def path_of(memory_path: Path, name: str, home: Path | None = None) -> Path:
    return folder(memory_path, home) / f"{name}.json"


def home_or_none() -> Path | None:
    """The machine's Cicada home, or None when it cannot be made. A caller that stores later (a thread) takes it now, so
    what it writes goes where the request that scheduled it would have written, whatever the environment becomes."""
    try:
        return cicada_home()
    except OSError:
        return None


def _safe_path(memory_path: Path, name: str, home: Path | None = None) -> Path | None:
    """:func:`path_of`, or None when the home itself cannot be made (it is created on first ask)."""
    try:
        return path_of(memory_path, name, home)
    except OSError:
        return None


def load(memory_path: Path, name: str, tag: str):
    """What :func:`save` stored for this bank under ``name`` and ``tag``, or ``None`` (nothing stored, another bank's,
    another tag's, another format's, or unreadable)."""
    path = _safe_path(memory_path, name)
    if path is None:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        _drop(path)
        return None
    if (not isinstance(doc, dict) or doc.get("format") != FORMAT or doc.get("tag") != tag
            or doc.get("bank") != _resolved(memory_path)):
        return None
    return doc.get("data")


def save(memory_path: Path, name: str, tag: str, data, home: Path | None = None) -> bool:
    """Store ``data`` (JSON) for this bank. Never raises: a full disk or a read-only home is "not stored"."""
    path = _safe_path(memory_path, name, home)
    if path is None:
        return False
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = json.dumps({"format": FORMAT, "tag": tag, "bank": _resolved(memory_path), "data": data},
                             separators=(",", ":"))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError) as exc:
        logger.debug(f"derived store: {name} not stored ({type(exc).__name__})")
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def _drop(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def forget(memory_path: Path, name: str | None = None) -> None:
    """Remove one stored record of this bank, or all of them."""
    try:
        if name is not None:
            _drop(path_of(memory_path, name))
            try:
                folder(memory_path).rmdir()      # the bank's folder goes with its last record
            except OSError:
                pass
        else:
            shutil.rmtree(folder(memory_path), ignore_errors=True)
    except OSError:
        pass
