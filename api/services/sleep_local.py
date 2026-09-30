"""Machine-local Sleep state — beside the bank, never inside it (Sleep page v5).

A run's sidecar (``run.json``), the parked conversations (``parked.json``) and the
auto-continue arm live in ``$CICADA_HOME/sleep/<bank>/``: a 0700 folder of 0600
files, never in a bank and never in git. They hold ids, counts and enums — an
episode id is a filename stem, never a title, and nothing here is text from a
conversation. A pause is a fact about this process and this Mac, not memory, so a
bank handed to someone else carries none of it (portability).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from api.services.auth import cicada_home


def bank_key(memory_path: Path) -> str:
    """One folder per bank: its name, plus a short hash of where it lives — two banks under
    different roots can share a name, and one bank's pause must never be another's."""
    path = Path(memory_path)
    try:
        resolved = str(path.resolve())
    except OSError:
        resolved = str(path)
    return f"{path.name or 'default'}-{hashlib.sha1(resolved.encode()).hexdigest()[:8]}"


def bank_dir(memory_path: Path, *, create: bool = True) -> Path:
    """``$CICADA_HOME/sleep/<bank>/``. A read passes ``create=False`` so asking
    never conjures a folder."""
    path = cicada_home() / "sleep" / bank_key(memory_path)
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError:
            pass
    return path


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, obj) -> None:
    """Atomic (tmp + replace), 0600 from the first byte."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=0, sort_keys=True)
            fh.write("\n")
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def remove(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
