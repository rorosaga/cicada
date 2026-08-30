"""Durable "this sync actually ran" record — ``<memory>/sync_state.json``.

Bookmark and Notes sync leave no subscription record behind (unlike
``feeds.yaml`` / ``calendars.yaml``): their only trace is whatever episodes
they wrote, which is indistinguishable from any other capture path. The
Capture page needs to know "is this channel connected", so the sync endpoints
stamp one small JSON file on success and ``channel_registry`` reads it back.

Shape::

    {"bookmarks": {"last_sync": "2026-08-29T10:00:00Z", "count": 412},
     "notes":     {"last_sync": "2026-08-30T09:00:00Z", "count": 18}}

Corrupt or missing file degrades to ``{}`` — a channel simply reads as not
connected rather than breaking the page.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

SYNC_STATE_FILENAME = "sync_state.json"


def sync_state_path(memory_path: Path) -> Path:
    return Path(memory_path) / SYNC_STATE_FILENAME


def read_sync_state(memory_path: Path) -> dict:
    path = sync_state_path(memory_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_sync(memory_path: Path, channel: str, *, count: int, at: str | None = None) -> dict:
    """Stamp ``channel``'s last successful sync. Returns the full new state."""
    state = read_sync_state(memory_path)
    state[channel] = {
        "last_sync": at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "count": int(count),
    }
    path = sync_state_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:  # a read-only bank must never fail the sync itself
        logger.warning(f"Could not write {SYNC_STATE_FILENAME}: {type(exc).__name__}: {exc}")
    return state
