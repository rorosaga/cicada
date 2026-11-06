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

from api.services import media_ingestor, reading_hosts
from api.services.media_ingestor import normalize_url

FEEDS_FILENAME = "feeds.yaml"

FetchFn = Callable[[str], "str | Awaitable[str]"]

#: ROR-108 — what a feed's last poll came to when it failed, kept on its record as ``last_problem`` (a code, never a
#: fetch error's text) and said on the feed's row in these words.
POLL_PROBLEMS = {
    "rate_limited": "too many requests",
    "refused": "the site refused",
    "gone": "not found",
    "server": "site error",
    "unreachable": "couldn't reach it",
    "not_a_feed": "not a feed",
}


def feed_id(url: str) -> str:
    """A followed feed's id on the wire and on its items' ``url_index`` rows: its normalized URL's hash."""
    return media_ingestor.url_hash(url)


def poll_problem(error: Exception) -> str:
    """The ``POLL_PROBLEMS`` code of a failed poll, read from the exception's type and HTTP status alone."""
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 429:
        return "rate_limited"
    if status in (401, 402, 403, 407, 451):
        return "refused"
    if status in (404, 410):
        return "gone"
    if isinstance(status, int) and status >= 500:
        return "server"
    return "unreachable"


def problem_words(record: dict) -> str | None:
    """What the row says about a feed whose last poll failed; ``None`` when it did not."""
    words = POLL_PROBLEMS.get(str(record.get("last_problem") or ""))
    return f"Last check failed: {words}" if words else None


# --- Registry file I/O -------------------------------------------------


def is_substack(record) -> bool:
    """A followed feed that is a Substack publication: on ``*.substack.com``, or on its own domain, where the feed
    list's ``substack`` tag says so. The one rule: its mark, its page and its counts all read this (G89, 2026-11-05)."""
    if not isinstance(record, dict):
        return False
    host = reading_hosts.display_host(reading_hosts.host_of(str(record.get("url") or ""))) or ""
    tags = {str(t).strip().casefold() for t in (record.get("tags") or [])}
    return "substack" in tags or host == "substack.com" or host.endswith(".substack.com")


def _feeds_path(memory_path: Path) -> Path:
    return Path(memory_path) / FEEDS_FILENAME


def _read_registry(memory_path: Path) -> dict:
    path = _feeds_path(memory_path)
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        # A corrupt registry must never break the caller — degrade to empty.
        logger.warning(f"Corrupt {FEEDS_FILENAME} at {path} — treating as empty")
        return {}
    return data if isinstance(data, dict) else {}


def _read_feeds_file(memory_path: Path) -> list[dict]:
    feeds = _read_registry(memory_path).get("feeds")
    return feeds if isinstance(feeds, list) else []


def _read_removed(memory_path: Path) -> list[dict]:
    removed = _read_registry(memory_path).get("removed")
    return [r for r in removed if isinstance(r, dict) and r.get("url")] if isinstance(removed, list) else []


def removed_feeds(memory_path: Path) -> set[str]:
    """The feeds the person unsubscribed from, normalized — an automatic writer (the person's agent reading their
    Substack subscriptions, G89) never subscribes one of these again; only the person's own subscribe does."""
    return {normalize_url(str(r["url"])) for r in _read_removed(memory_path)}


def _write_feeds_file(memory_path: Path, feeds: list[dict], removed: list[dict] | None = None) -> bool:
    """Write the registry; return whether the file's content actually changed.

    ``poll_feeds`` uses the answer to decide whether a 0-new poll still has
    state worth committing (a ``last_polled`` bump is real state — it is what
    the Feed page shows as "last checked") without minting a no-op commit
    for a same-day re-poll that rewrote byte-identical YAML. ``removed`` (the
    person's unsubscribes, remembered) is kept as it is when not given.
    """
    path = _feeds_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if removed is None:
        removed = _read_removed(memory_path)
    body: dict = {"feeds": feeds}
    if removed:
        body["removed"] = removed
    text = yaml.dump(body, default_flow_style=False, sort_keys=False)
    try:
        before = path.read_text(encoding="utf-8") if path.exists() else None
    except OSError:
        before = None
    path.write_text(text, encoding="utf-8")
    return text != before


# --- Subscriptions -------------------------------------------------------


def list_feeds(memory_path: Path) -> list[dict]:
    """Return every subscribed feed record, in subscription order."""
    return _read_feeds_file(memory_path)


def subscribe_feed(memory_path: Path, url: str, tags: list[str] | None = None, *, title: str | None = None,
                   via: str | None = None, automatic: bool = False) -> dict | None:
    """Add (or re-affirm) a feed subscription. Idempotent, deduped on URL.

    Re-subscribing an already-watched feed (by normalized URL — same rules as
    ``media_ingestor.normalize_url``) is a no-op on the ``added``/``last_polled``
    fields; any new tags are merged in rather than duplicating the record, and a
    ``title`` fills one the record lacks. Returns the (created or existing)
    subscription record.

    ``automatic`` (G89, 2026-11-04): a writer acting for the person without their
    click — their agent reading their Substack subscriptions — never subscribes a
    feed the person unsubscribed from, and gets ``None`` for it. The person's own
    subscribe lifts that memory.
    """
    clean_url = (url or "").strip()
    if not clean_url:
        raise ValueError("url is required")

    feeds = _read_feeds_file(memory_path)
    removed = _read_removed(memory_path)
    norm = normalize_url(clean_url)
    was_removed = [r for r in removed if normalize_url(str(r["url"])) == norm]
    if automatic and was_removed:
        return None
    if was_removed:
        removed = [r for r in removed if r not in was_removed]
    for feed in feeds:
        if normalize_url(feed.get("url", "")) == norm:
            changed = bool(was_removed)
            if tags and not set(tags) <= set(feed.get("tags") or []):
                feed["tags"] = sorted(set(feed.get("tags") or []) | set(tags))
                changed = True
            if title and not feed.get("title"):
                feed["title"] = title
                changed = True
            if changed:
                _write_feeds_file(memory_path, feeds, removed)
            return feed

    record = {
        "url": clean_url,
        "tags": sorted(set(tags or [])),
        "added": datetime.now().strftime("%Y-%m-%d"),
        "last_polled": None,
    }
    if title:
        record["title"] = title
    if via:
        record["via"] = via
    feeds.append(record)
    _write_feeds_file(memory_path, feeds, removed)
    return record


def note_feed_title(feed: dict, channel: str) -> bool:
    """ROR-122: the feed's own newest name. It fills a record with none; once a poll has reported one, a different
    report renames the row and the old name stays in ``aka``. A feed row's title is always a source's (there is no
    person's rename of one), and a first report only sets the baseline, so a name from a Substack list never flips
    against the channel's. ``True`` when the record changed."""
    channel = " ".join(str(channel or "").split())[:200]
    if not channel:
        return False
    seen = feed.get("title_seen")
    changed = False
    if seen != channel:
        feed["title_seen"] = channel
        changed = True
    if not feed.get("title"):
        feed["title"] = channel
    elif seen and seen != channel and feed["title"] != channel:
        aka = [a for a in feed.get("aka") or [] if isinstance(a, str)]
        if feed["title"] not in aka:
            aka.append(feed["title"])
        feed["aka"] = [a for a in aka if a != channel]
        feed["title"] = channel
    return changed


def unsubscribe_feed(memory_path: Path, url: str) -> bool:
    """Remove a feed subscription by URL. Returns True iff a record was removed. The removal is remembered
    (``removed``), so no automatic writer subscribes it again (G61's rule for a source the person removed)."""
    feeds = _read_feeds_file(memory_path)
    norm = normalize_url(url)
    gone = [f for f in feeds if normalize_url(f.get("url", "")) == norm]
    if not gone:
        return False
    remaining = [f for f in feeds if f not in gone]
    removed = [r for r in _read_removed(memory_path) if normalize_url(str(r["url"])) != norm]
    removed.append({"url": str(gone[0].get("url") or url), "day": datetime.now().strftime("%Y-%m-%d")})
    _write_feeds_file(memory_path, remaining, removed)
    return True


# --- Polling -------------------------------------------------------------


def _network_allowed(allow_fetch: bool | None) -> bool:
    if allow_fetch is not None:
        return bool(allow_fetch)
    return os.environ.get("CICADA_ALLOW_FEED_FETCH") == "1"


def fetch_allowed() -> bool:
    """The unattended RSS/ICS gate as Settings reports it (G139) — the same
    check `_network_allowed(None)` makes before a poll."""
    return _network_allowed(None)


async def _default_fetch(url: str) -> str:
    """The gated live-HTTP fetch — same shape as the ``feedUrl`` path in
    ``POST /sources/rss``. Only ever invoked when the network gate is open."""
    import httpx

    from api.services import net_guard

    # Every hop through the SSRF guard (the network rails): a subscribed URL, or a redirect from it, never reaches this
    # Mac's loopback, its LAN or a tailnet peer (2026-10-23: polling fetched any address).
    async with httpx.AsyncClient(follow_redirects=True,
                                 event_hooks={"request": [net_guard.httpx_request_guard]}) as client:
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


def _followed_on(feed: dict) -> bool:
    """ROR-138 (owner 2026-11-06): nothing is followed without the person turning it on. A publication their agent
    followed from their Substack subscriptions (``via: substack-subscriptions``) is polled only while that list's
    switch is on; every other feed was added by the person and polls as before."""
    if str(feed.get("via") or "") != "substack-subscriptions":
        return True
    from api.services import reading_settings

    return reading_settings.substack_list_allowed("subscriptions")


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
    feeds = [f for f in list_feeds(memory_path) if _followed_on(f)]
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
    stamped = False
    today = datetime.now().strftime("%Y-%m-%d")

    for feed in feeds:
        url = feed.get("url", "")
        try:
            xml = await _call_fetch(effective_fetch, url)
            created, duplicates = await media_ingestor.ingest_feed(
                xml, memory_path, commit=False
            )
            # ROR-108: which feed each listed item came from, and the feed's own name while its record has none.
            listed = media_ingestor.parse_rss(xml)
            stamped = media_ingestor.stamp_feed(memory_path, listed, feed_id(url)) or stamped
            if listed and listed[0].channel:
                note_feed_title(feed, listed[0].channel)
        except Exception as e:
            logger.warning(f"Feed poll failed for {url}: {type(e).__name__}: {e}")
            per_feed.append({"url": url, "status": "error", "error": str(e)})
            feed["last_polled"] = today
            feed["last_problem"] = poll_problem(e)
            polled += 1
            continue

        feed["last_polled"] = today
        # A body that is no feed polled "ok" with nothing new (the poll's answer stays that); its row says so.
        if media_ingestor.is_feed_document(xml):
            feed.pop("last_problem", None)
        else:
            feed["last_problem"] = "not_a_feed"
        polled += 1
        total_new += created
        per_feed.append(
            {"url": url, "status": "ok", "new": created, "duplicates": duplicates}
        )

    registry_changed = _write_feeds_file(memory_path, feeds)

    # Commit whenever the poll left real state behind — new items OR just the
    # ``last_polled`` bump. Committing only on ``total_new`` left ``feeds.yaml``
    # dirty after every quiet night, and the NEXT Sleep cycle's ``_finalize``
    # (``git add -A``) then swept the registry into a model-authored commit
    # (G114 final review). The H1 clean-tree guard in the Sleep tail is what
    # makes this ``git add -A`` safe: it only ever runs on a committed tree.
    if total_new or registry_changed or stamped:
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
