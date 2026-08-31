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


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_state(memory_path: Path, state: dict) -> None:
    path = sync_state_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as exc:  # a read-only bank must never fail the sync itself
        logger.warning(f"Could not write {SYNC_STATE_FILENAME}: {type(exc).__name__}: {exc}")


def record_sync(
    memory_path: Path,
    channel: str,
    *,
    count: int,
    at: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Stamp ``channel``'s last successful sync. Returns the full new state.

    A success REPLACES the entry, which deliberately clears any recorded
    ``last_error`` — the channel is working again and the Capture page must
    stop saying otherwise. ``extra`` (G71) carries per-connector cursor state,
    e.g. a connector's newest-seen fullname.
    """
    state = read_sync_state(memory_path)
    entry = {"last_sync": at or _now_iso(), "count": int(count)}
    if extra:
        entry.update(extra)
    state[channel] = entry
    _write_state(memory_path, state)
    return state


def record_credentials_changed(
    memory_path: Path, channel: str, *, at: str | None = None
) -> dict:
    """Stamp that ``channel``'s credentials changed — a save, a forget, or a
    successful OAuth token exchange (G71 fix round 1, M2).

    Those three writes land only in ``$CICADA_HOME/secrets.env``, entirely
    outside ``memory_path`` — ``sync_service.components()`` never reads that
    file, so without this the "sources" component (and therefore the SSE
    version vector) never changed on connect/disconnect, and the Feed page's
    channel badge went stale forever, not just until the next tick. Touching
    ``sync_state.json``'s mtime — which the "sources" component DOES watch —
    makes a credential mutation visible the same way ``record_sync`` already
    makes a completed sync visible. Preserves any existing
    ``last_sync``/``last_error`` entry, exactly like ``record_error`` does.
    """
    state = read_sync_state(memory_path)
    entry = dict(state.get(channel) or {})
    entry["credentials_changed_at"] = at or _now_iso()
    state[channel] = entry
    _write_state(memory_path, state)
    return state


def record_error(
    memory_path: Path, channel: str, error: str, *, at: str | None = None
) -> dict:
    """Record that ``channel``'s last poll FAILED, preserving its last success.

    G71: a connector sync never raises past ``sync()``; this is how the failure
    still reaches the user, as a per-channel line on ``GET /sources/channels``.
    ``error`` is a type+message string built by the caller — never a credential,
    never a raw response body.
    """
    state = read_sync_state(memory_path)
    entry = dict(state.get(channel) or {})
    entry["last_error"] = str(error)[:400]
    entry["last_error_at"] = at or _now_iso()
    state[channel] = entry
    _write_state(memory_path, state)
    return state
