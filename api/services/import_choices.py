"""What the person chose to leave out of an export they uploaded (ROR-126).

A chat export arrives whole, but the person picks a start date and may deselect single chats **before** anything becomes
an episode (Consolidate reads everything it was given, rulings 13 and 16, so the choice has to come first). This module
holds the two halves of that choice:

* :func:`select` — the pure filter ``import_bytes`` runs on the parsed episodes: older than the start date, or deselected.
* the remembered deselections — ``<bank>/import_deselected.json``, one dated key per chat, so a later import of a grown
  export does not offer a chat the person already left out as new. A key is the export's own conversation id behind its
  source name; **never a title, never text** (CLAUDE.md privacy rail: the bank holds what the person said, this holds
  only that they declined it). The start date is not remembered: a later export is a fresh choice.

The file lives in the bank so a bank handed over intact carries its decisions; it is written atomically under one lock
and swept into the next ``git add -A`` commit like every other bank file. One writer: :func:`remember`.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

FILENAME = "import_deselected.json"
#: Enough for years of chats; past it the oldest decisions are dropped rather than the file growing without bound.
MAX_KEYS = 50_000
_LOCK = threading.Lock()


def key_for(episode: dict) -> str:
    """The stable identity of one chat across re-exports: its source name and conversation id. A parser that gave no
    id falls back to a hash of the title and date — stable for the same export, and never the title itself."""
    source = str(episode.get("source") or "unknown")
    sid = episode.get("source_id")
    if sid:
        return f"{source}:{sid}"
    raw = f"{episode.get('title') or ''}|{episode.get('original_date') or ''}"
    return f"{source}:t-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]}"


def _path(memory_path: Path) -> Path:
    return Path(memory_path) / FILENAME


def remembered(memory_path: Path) -> set[str]:
    """Every chat the person left out of an earlier import into this bank."""
    try:
        data = json.loads(_path(memory_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    keys = data.get("deselected") if isinstance(data, dict) else None
    return {str(k) for k in keys} if isinstance(keys, dict) else set()


def remember(memory_path: Path, file_keys: Iterable[str], excluded: Iterable[str]) -> None:
    """Record this upload's choice. ``file_keys`` is every chat the file holds, ``excluded`` the ones left out: the
    stored set drops the file's chats first, so a chat the person now ticks again is forgotten, and keeps every chat
    from other files untouched. Nothing is written when nothing changed."""
    file_keys = set(file_keys)
    excluded = set(excluded) & file_keys
    with _LOCK:
        path = _path(memory_path)
        try:
            old = json.loads(path.read_text(encoding="utf-8")).get("deselected", {})
            old = {str(k): str(v) for k, v in old.items()} if isinstance(old, dict) else {}
        except (OSError, ValueError, AttributeError):
            old = {}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        new = {k: v for k, v in old.items() if k not in file_keys}
        for k in excluded:
            new[k] = old.get(k, now)
        if new == old:
            return
        if len(new) > MAX_KEYS:
            new = dict(sorted(new.items(), key=lambda kv: kv[1])[-MAX_KEYS:])
        if not new:
            try:
                path.unlink()
            except OSError:
                pass
            return
        body = json.dumps({"deselected": dict(sorted(new.items()))}, indent=1)
        fd, tmp = tempfile.mkstemp(dir=str(Path(memory_path)), prefix=".import_deselected.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def parse_since(value: str | None) -> str | None:
    """A ``YYYY-MM-DD`` start date, or ``None`` for everything. Anything else is no filter, never an error."""
    text = (value or "").strip()[:10]
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return text


def select(episodes: list[dict], *, since: str | None, deselected: set[str]) -> list[dict]:
    """The episodes to keep: not older than ``since`` (an undated one is kept — absence of a date is no reason to drop
    a chat) and not in ``deselected``. Order is the parsers' own, because ids mint per date in that order."""
    out = []
    for ep in episodes:
        if key_for(ep) in deselected:
            continue
        day = str(ep.get("original_date") or "")[:10]
        if since and day and day < since:
            continue
        out.append(ep)
    return out
