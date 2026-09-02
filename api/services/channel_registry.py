"""Capture-channel derivation for ``GET /sources/channels`` (G62).

One list the Capture page can render from, derived from **persisted state
only** — never from the transient result of a button press:

* ``rss`` / ``calendar``  -> the subscription registries are non-empty
* ``bookmarks`` / ``safari-tabs`` / ``notes`` -> a ``sync_state.json`` entry exists
* ``telegram``            -> ``CICADA_TELEGRAM_BOT_TOKEN`` is configured
* ``chat-export:*`` / ``files`` -> origin counts / the saved-URL index

Pure filesystem + one env flag passed in by the router. No network, no LLM,
never raises: a corrupt registry or a missing directory yields a
not-connected channel, never an error.
"""

from __future__ import annotations

from pathlib import Path

from api.services import (
    calendar_registry,
    feed_registry,
    media_ingestor,
    origin_stats,
    sync_state,
)
from api.services.connectors import ADAPTERS

# Canonical order; the app sorts the *connected* rows by last_sync itself.
# The direct-API connector ids splice in from the shared registry (Task 15
# §1) at the position they've always occupied — between "calendar" and
# "telegram" — so adding a fourth adapter to ``ADAPTERS`` needs no edit here.
_NON_CONNECTOR_HEAD = (
    "chat-export:claude",
    "chat-export:chatgpt",
    "bookmarks",
    "safari-tabs",
    "notes",
    "rss",
    "calendar",
)
_NON_CONNECTOR_TAIL = (
    "telegram",
    "files",
)
CHANNEL_IDS = _NON_CONNECTOR_HEAD + tuple(ADAPTERS.keys()) + _NON_CONNECTOR_TAIL


def _plural(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n:,} {singular if n == 1 else (plural or singular + 's')}"


def _short_date(iso: str | None) -> str:
    """`2026-08-29T10:00:00Z` / `2026-08-29` -> `2026-08-29`; '' when absent."""
    return (iso or "").split("T", 1)[0]


def _latest(values: list[str | None]) -> str | None:
    present = sorted(v for v in values if v)
    return present[-1] if present else None


def _subscription_channel(
    channel_id: str, label: str, records: list[dict], noun: str
) -> dict:
    count = len(records)
    last = _latest([r.get("last_polled") for r in records if isinstance(r, dict)])
    detail = None
    if count:
        when = f"polled {_short_date(last)}" if last else "not polled yet"
        detail = f"{_plural(count, noun)} · {when}"
    return {
        "id": channel_id,
        "label": label,
        "connected": count > 0,
        "count": count,
        "last_sync": last,
        "detail": detail,
        "actions": ["poll", "manage"],
    }


def _sync_channel(channel_id: str, label: str, state: dict, noun: str) -> dict:
    entry = state.get(channel_id) or {}
    last = entry.get("last_sync") or None
    count = int(entry.get("count") or 0)
    connected = bool(last)
    detail = f"{_plural(count, noun)} · synced {_short_date(last)}" if connected else None
    return {
        "id": channel_id,
        "label": label,
        "connected": connected,
        "count": count,
        "last_sync": last,
        "detail": detail,
        "actions": ["sync"],
    }


def _connector_channel(
    channel_id: str, label: str, state: dict, noun: str, *, connected: bool,
    price_note: str | None = None,
) -> dict:
    """A direct-API connector row (G71 §2).

    ``connected`` is credential presence, passed in by the router — it lives in
    ``$CICADA_HOME/secrets.env``, outside the bank, so this module stays pure
    filesystem-over-the-bank. A recorded failure wins the detail line: a channel
    whose last poll 401'd must not keep advertising a week-old success.

    ``price_note`` (Task 14, X's cost-honesty requirement) is appended to
    whatever detail line the state above produces — and stands in for it
    entirely when there is otherwise none, so a pay-per-use connector's cost
    model is visible even before the user connects it, not only after.

    A gate-skipped background poll (final-review H2, ``sync_state.record_skip``)
    renders too, same "wins the detail line" priority as a failure —
    ``record_error``/``record_skip`` merge onto the entry (so an old error
    and a newer skip can coexist; whichever is more recent wins the line),
    while ``record_sync`` REPLACES it wholesale, deliberately clearing both:
    a success means the channel is working again, same as the feed/calendar
    channels' "the last thing that actually happened" rule.
    """
    entry = state.get(channel_id) or {}
    last = entry.get("last_sync") or None
    count = int(entry.get("count") or 0)
    error = entry.get("last_error") or None
    error_at = entry.get("last_error_at") or ""
    skip_reason = entry.get("last_skip_reason") or None
    skip_at = entry.get("last_skip") or ""

    show_error = bool(error) and (not skip_reason or error_at >= skip_at)

    if show_error:
        detail = f"Last sync failed · {error}"
    elif skip_reason:
        detail = f"Last sync skipped · {skip_reason}"
    elif connected and last:
        # L2 (final review): `count` is "items pulled THIS run", not the
        # channel total (unlike `_sync_channel`'s bookmarks/notes rows, which
        # really do report a running total) — "+N {noun} this sync" says so,
        # instead of implying "N {noun} exist" the way a bare count read.
        detail = f"+{_plural(count, noun)} this sync · synced {_short_date(last)}"
    elif connected:
        detail = "Connected · not synced yet"
    else:
        detail = None

    if price_note:
        detail = f"{detail} · {price_note}" if detail else price_note

    return {
        "id": channel_id,
        "label": label,
        "connected": connected,
        "count": count,
        "last_sync": last,
        "last_error": error,
        "detail": detail,
        "actions": ["sync", "disconnect"] if connected else ["connect"],
    }


def _origin_channel(
    channel_id: str, label: str, origin: str, by_origin: dict, noun: str
) -> dict:
    stat = by_origin.get(origin) or {}
    count = int(stat.get("episodeCount") or 0)
    last = stat.get("lastSeen") or None
    detail = f"{_plural(count, noun)} · imported {_short_date(last)}" if count else None
    return {
        "id": channel_id,
        "label": label,
        "connected": count > 0,
        "count": count,
        "last_sync": last,
        "detail": detail,
        "actions": ["import"],
    }


def build_channels(
    memory_path: Path,
    *,
    telegram_enabled: bool,
    connectors_connected: dict[str, bool] | None = None,
) -> list[dict]:
    memory_path = Path(memory_path)
    state = sync_state.read_sync_state(memory_path)
    by_origin = {o["origin"]: o for o in origin_stats.aggregate_origins(memory_path)}
    connected_map = connectors_connected or {}

    try:
        url_index = media_ingestor.load_url_index(memory_path)
    except Exception:
        url_index = {}
    saved_count = len(url_index)

    telegram_count = int((by_origin.get("telegram") or {}).get("episodeCount") or 0)

    channels = {
        "chat-export:claude": _origin_channel(
            "chat-export:claude", "Claude chat export", "claude-export", by_origin, "conversation"),
        "chat-export:chatgpt": _origin_channel(
            "chat-export:chatgpt", "ChatGPT chat export", "chatgpt-export", by_origin, "conversation"),
        "bookmarks": _sync_channel(
            "bookmarks", "Chrome & Safari bookmarks", state, "bookmark"),
        # 2026-09-02 brief: the iPhone's open tabs are their own channel — a
        # different file, a different question ("what is open right now")
        # and its own sync_state entry, written by `safari_tabs.sync_tabs`.
        "safari-tabs": _sync_channel("safari-tabs", "Safari iCloud tabs", state, "tab"),
        "notes": _sync_channel("notes", "Apple Notes", state, "note"),
        "rss": _subscription_channel(
            "rss", "RSS feeds", feed_registry.list_feeds(memory_path), "feed"),
        "calendar": _subscription_channel(
            "calendar", "Calendars", calendar_registry.list_calendars(memory_path), "calendar"),
        "telegram": {
            "id": "telegram",
            "label": "Telegram bot",
            "connected": bool(telegram_enabled),
            "count": telegram_count,
            "last_sync": (by_origin.get("telegram") or {}).get("lastSeen") or None,
            "detail": (f"Bot configured · {_plural(telegram_count, 'capture')}"
                       if telegram_enabled else None),
            "actions": [],
        },
        "files": {
            "id": "files",
            "label": "Files & links",
            "connected": saved_count > 0,
            "count": saved_count,
            "last_sync": None,
            "detail": _plural(saved_count, "saved item") if saved_count else None,
            "actions": ["import"],
        },
    }
    for cid, adapter in ADAPTERS.items():
        channels[cid] = _connector_channel(
            cid, adapter.LABEL, state, adapter.CHANNEL_NOUN,
            connected=bool(connected_map.get(cid)),
            price_note=getattr(adapter, "PRICE_NOTE", None),
        )
    return [channels[cid] for cid in CHANNEL_IDS]
