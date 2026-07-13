"""RSS/Atom feed subscriptions + polling.

A *subscription* is a small, durable record — just a URL plus tags and two
timestamps — kept in ``<memory>/feeds.yaml``. It is deliberately separate from
``memory/sources/url_index.json`` (the per-item dedup index owned by
``media_ingestor``): the registry tracks *which feeds we watch*, the index
tracks *which items we've already ingested*. Polling a feed is just "fetch its
XML, then hand it to the existing ``media_ingestor.ingest_feed`` pipeline" —
no new consolidation code, identical to a manual ``POST /sources/rss`` paste.

Network safety mirrors ``POST /sources/rss`` (see ``api/routers/sources.py``):
live HTTP fetches are gated behind ``CICADA_ALLOW_FEED_FETCH=1`` (or an
explicit ``allow_fetch=True``) so an unconfigured install — and the whole test
suite — never touches the network. Tests instead inject ``fetch_fn``, which
always runs regardless of the gate (the caller has explicitly supplied the
fetch mechanism, so there is nothing left to gate).

Offline-safe by construction: a malformed feed, an unreachable host, or a
corrupt registry file all degrade to a recorded error / empty result rather
than raising, so one bad subscription never blocks the rest of the poll.
"""

from __future__ import annotations

import inspect
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml
from loguru import logger

from api.services import media_ingestor
from api.services.media_ingestor import normalize_url

FEEDS_FILENAME = "feeds.yaml"

FetchFn = Callable[[str], "str | Awaitable[str]"]


# --- Registry file I/O -------------------------------------------------


def _feeds_path(memory_path: Path) -> Path:
    return Path(memory_path) / FEEDS_FILENAME


def _read_feeds_file(memory_path: Path) -> list[dict]:
    path = _feeds_path(memory_path)
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        # A corrupt registry must never break the caller — degrade to empty.
        logger.warning(f"Corrupt {FEEDS_FILENAME} at {path} — treating as empty")
        return []
    feeds = data.get("feeds") if isinstance(data, dict) else None
    return feeds if isinstance(feeds, list) else []


def _write_feeds_file(memory_path: Path, feeds: list[dict]) -> None:
    path = _feeds_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump({"feeds": feeds}, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


# --- Subscription CRUD --------------------------------------------------


def list_feeds(memory_path: Path) -> list[dict]:
    """Return every subscribed feed record, in subscription order."""
    return _read_feeds_file(memory_path)


def subscribe_feed(memory_path: Path, url: str, tags: list[str] | None = None) -> dict:
    """Add (or re-affirm) a feed subscription. Idempotent, deduped on URL.

    Re-subscribing an already-watched feed (by normalized URL — same rules as
    ``media_ingestor.normalize_url``) is a no-op on the ``added``/``last_polled``
    fields; any new tags are merged in rather than duplicating the record.
    Returns the (created or existing) subscription record.
    """
    clean_url = (url or "").strip()
    if not clean_url:
        raise ValueError("url is required")

    feeds = _read_feeds_file(memory_path)
    norm = normalize_url(clean_url)
    for feed in feeds:
        if normalize_url(feed.get("url", "")) == norm:
            if tags:
                merged = set(feed.get("tags") or []) | set(tags)
                feed["tags"] = sorted(merged)
                _write_feeds_file(memory_path, feeds)
            return feed

    record = {
        "url": clean_url,
        "tags": sorted(set(tags or [])),
        "added": datetime.now().strftime("%Y-%m-%d"),
        "last_polled": None,
    }
    feeds.append(record)
    _write_feeds_file(memory_path, feeds)
    return record


def unsubscribe_feed(memory_path: Path, url: str) -> bool:
    """Remove a feed subscription by URL. Returns True iff a record was removed."""
    feeds = _read_feeds_file(memory_path)
    norm = normalize_url(url)
    remaining = [f for f in feeds if normalize_url(f.get("url", "")) != norm]
    if len(remaining) == len(feeds):
        return False
    _write_feeds_file(memory_path, remaining)
    return True


# --- Polling -------------------------------------------------------------


def _network_allowed(allow_fetch: bool | None) -> bool:
    if allow_fetch is not None:
        return bool(allow_fetch)
    return os.environ.get("CICADA_ALLOW_FEED_FETCH") == "1"


async def _default_fetch(url: str) -> str:
    """The gated live-HTTP fetch — same shape as the ``feedUrl`` path in
    ``POST /sources/rss``. Only ever invoked when the network gate is open."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp.text


async def _call_fetch(fetch_fn: FetchFn, url: str) -> str:
    """Call ``fetch_fn(url)``, awaiting the result if it's a coroutine.

    Lets tests inject a plain sync ``lambda url: FIXTURE_XML`` while the
    default fetch stays async (real HTTP).
    """
    result = fetch_fn(url)
    if inspect.isawaitable(result):
        result = await result
    return result


async def poll_feeds(
    memory_path: Path,
    *,
    fetch_fn: FetchFn | None = None,
    allow_fetch: bool | None = None,
) -> dict:
    """Poll every subscribed feed and ingest any new items.

    For each feed: fetch its XML (via ``fetch_fn`` if given — always used,
    gate or no gate, since the caller supplied the fetch mechanism explicitly;
    otherwise the gated default HTTP fetch, only when ``allow_fetch`` or
    ``CICADA_ALLOW_FEED_FETCH=1`` is set), then run it through
    ``media_ingestor.ingest_feed`` so only genuinely new items are ingested
    (existing URL-hash dedup in ``url_index.json``), and stamp ``last_polled``.

    Never raises: a bad/unreachable/malformed feed is recorded in ``per_feed``
    with ``status: "error"`` and polling continues with the next feed.

    When no fetch is available at all (no ``fetch_fn`` and the network gate is
    closed), fetching is skipped entirely and the result reports
    ``skipped_no_network`` instead of touching any feed.

    Returns ``{"polled": int, "new": int, "per_feed": [...]}`` (plus
    ``skipped_no_network`` in the no-fetch case).
    """
    feeds = list_feeds(memory_path)
    if not feeds:
        return {"polled": 0, "new": 0, "per_feed": []}

    effective_fetch: FetchFn
    if fetch_fn is not None:
        effective_fetch = fetch_fn
    elif _network_allowed(allow_fetch):
        effective_fetch = _default_fetch
    else:
        return {
            "polled": 0,
            "new": 0,
            "skipped_no_network": len(feeds),
            "per_feed": [],
        }

    per_feed: list[dict] = []
    polled = 0
    total_new = 0
    today = datetime.now().strftime("%Y-%m-%d")

    for feed in feeds:
        url = feed.get("url", "")
        try:
            xml = await _call_fetch(effective_fetch, url)
            created, duplicates = await media_ingestor.ingest_feed(
                xml, memory_path, commit=False
            )
        except Exception as e:
            logger.warning(f"Feed poll failed for {url}: {type(e).__name__}: {e}")
            per_feed.append({"url": url, "status": "error", "error": str(e)})
            feed["last_polled"] = today
            polled += 1
            continue

        feed["last_polled"] = today
        polled += 1
        total_new += created
        per_feed.append(
            {"url": url, "status": "ok", "new": created, "duplicates": duplicates}
        )

    _write_feeds_file(memory_path, feeds)

    if total_new:
        try:
            await _commit_poll(memory_path, total_new, polled)
        except Exception as e:
            logger.warning(f"Feed poll commit failed: {type(e).__name__}: {e}")

    return {"polled": polled, "new": total_new, "per_feed": per_feed}


async def _commit_poll(memory_path: Path, new_count: int, polled_count: int) -> None:
    from api.services import git_service

    date_str = datetime.now().strftime("%Y-%m-%d")
    message = git_service.build_commit_message(
        f"Feed poll {date_str}",
        [
            "memory/feeds.yaml: updated (trigger: user/feed_poll)",
            f"{new_count} new item(s) from {polled_count} feed(s) polled "
            "(trigger: user/feed_poll)",
        ],
        authors=["user"],
    )
    await git_service.commit_changes(memory_path, message)
