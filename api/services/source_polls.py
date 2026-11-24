"""The backend's own poll job for what is fetched from a service on a timer (G245, track C1; ``docs/plans/2026-11-24-sources-redesign.md`` §10).

RSS feeds, calendar (ICS) feeds and the tier-1 saved-content connectors (Reddit, Pinterest, X's API) used to be polled
in exactly one place: the engine-free tail of a Sleep run. With Sleep on ``manual``, or a night with nothing readable,
they never updated. :func:`scheduled_poll` is their own job, every ``SCHEDULE_HOURS`` hours beside the tier-2 job
(``connectors.tier2.scheduled_sync``, every 6 h) in the backend's scheduler (``api/main.py``).

**What it does not change.**

* **The gates.** A connector poll is behind ``CICADA_ALLOW_CONNECTOR_FETCH`` (opt-out, ``base.network_allowed``,
  a skip recorded on the channel's row); feeds and calendars behind ``CICADA_ALLOW_FEED_FETCH=1`` (opt-in) — the job
  asks the registries' own answer and nothing else. Only the launchd plist sets the second one, so a backend the app
  spawned polls connectors but never feeds; no default moves here.
* **Yield to Sleep (G177/G183).** Nothing is fetched while Sleep holds the pages (an early probe, ``PROBE_SITES``);
  what was fetched is ingested and committed as one admitted transaction that is refused if Sleep began meanwhile —
  nothing saved, no cursor moved, the next poll reads the same items again. Feeds and calendars are fetched first,
  holding nothing, then handed to the registries' own poll as a replay of what was fetched (the registries' ingest,
  stamping and commit are untouched).
* **Each commit alone, under its true author.** The registries' ``Feed poll`` / ``Calendar poll`` commits and a
  connector's media commit are the existing ones, authored ``user`` as the Sleep tail's poll authors them.
* **No double work with Sleep's tail.** A kind this job polled in the last ``FRESH_FOR`` is not polled again by the
  tail (``polled_lately``); a poll that was gate-skipped or refused is never stamped. The stamp lives in memory: a
  restart costs at most one extra poll (the ingest dedups).

Never raises. A demo bank is never polled. Nothing here spawns an agent or a browser: it asks a service's own API or a
subscribed URL, through ``net_guard`` for the feeds.
"""
from __future__ import annotations

import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from loguru import logger

#: How often the scheduler runs the job (``api/main.py``).
SCHEDULE_HOURS = 3
#: A kind this job polled this recently is fresh: the Sleep tail does not poll it again.
FRESH_FOR = timedelta(hours=1)

CONNECTORS = "connectors"
FEEDS = "feeds"
CALENDARS = "calendars"

# resolved bank path -> kind -> time.monotonic() of the last poll that actually ran
_polled: dict[str, dict[str, float]] = {}


def _key(memory_path: Path) -> str:
    return str(Path(memory_path).resolve())


def _stamp(memory_path: Path, kind: str) -> None:
    _polled.setdefault(_key(memory_path), {})[kind] = time.monotonic()


def polled_lately(memory_path: Path, kind: str) -> bool:
    """Did this job poll ``kind`` on this bank within ``FRESH_FOR``? The Sleep tail asks before its own poll."""
    at = _polled.get(_key(memory_path), {}).get(kind)
    return at is not None and time.monotonic() - at < FRESH_FOR.total_seconds()


def reset_for_tests() -> None:
    _polled.clear()


async def scheduled_poll(memory_path: Path | None = None) -> dict[str, Any]:
    """The scheduler's job: tier-1 connectors, feeds and calendars on the active bank, one after another. Gated,
    yields to Sleep, never raises. Returns what it did, by kind (``polled`` / ``skipped`` with a short reason)."""
    if memory_path is None:
        from api.config import get_settings

        memory_path = get_settings().memory_path
    memory_path = Path(memory_path)
    out: dict[str, Any] = {}
    try:
        from api.services import bank_registry, demo_guard, home_move, replica_guard, write_admission

        bank_registry.unpin()   # G183(d): the bank active now, whatever context registered this job
        if replica_guard.blocks() or home_move.writes_closed():
            return {"skipped": "this computer does not write the memory"}   # a replica, or a home that is moving
        if demo_guard.is_demo(memory_path):
            return {"skipped": "the demo memory is open"}
        if write_admission.probe():
            logger.info("Source polls: Sleep is reading — they wait for the next time")
            return {"skipped": "sleep is reading"}
        out[CONNECTORS] = await _poll_connectors(memory_path)
        out[FEEDS] = await _poll_feeds(memory_path)
        out[CALENDARS] = await _poll_calendars(memory_path)
    except Exception as exc:  # noqa: BLE001 — a timer never fails the backend
        logger.warning(f"Source polls failed: {type(exc).__name__}")
    return out


async def admitted_ingest(memory_path: Path, body):
    """A connector's ingest and commit as one admitted transaction: ``body``'s result, or ``None`` when Sleep holds
    the pages (``base.INGEST_ADMISSION``)."""
    from api.services import write_admission

    try:
        return await write_admission.run_admitted(memory_path, body, refuse=write_admission.SleepHolding)
    except write_admission.SleepHolding:
        return None


async def _poll_connectors(memory_path: Path) -> dict[str, Any]:
    """Every connected tier-1 connector, sequentially. Gating, the credential check and the cursor are the adapter's
    own (``base.run_sync``); the ingest and its commit are admitted (``base.INGEST_ADMISSION``)."""
    from api.services.connectors import ADAPTERS, base

    if polled_lately(memory_path, CONNECTORS):
        return {"skipped": "polled lately"}
    ran = 0
    results: dict[str, str] = {}
    token = base.INGEST_ADMISSION.set(admitted_ingest)
    try:
        for adapter in ADAPTERS.values():
            if getattr(adapter, "TIER", 1) == 2:
                continue    # tier 2 has its own job
            try:
                if not adapter.is_connected():
                    continue
                result = await adapter.sync(memory_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"{adapter.CHANNEL_ID} scheduled poll failed: {type(exc).__name__}")
                continue
            results[adapter.CHANNEL_ID] = str(result.get("status"))
            if result.get("status") == "ok":
                ran += 1
                if result.get("new"):
                    logger.info(f"{adapter.LABEL}: pulled {result['new']} new saved item(s)")
    finally:
        base.INGEST_ADMISSION.reset(token)
    if ran:
        _stamp(memory_path, CONNECTORS)
    return results


class _Replay:
    """What was fetched with nothing held, served back to a registry's own poll: the page for a URL, or the error its
    fetch raised (so the registry records the same problem it would have)."""

    def __init__(self) -> None:
        self.bodies: dict[str, str] = {}
        self.errors: dict[str, Exception] = {}

    def __call__(self, url: str) -> str:
        if url in self.errors:
            raise self.errors[url]
        return self.bodies[url]


async def _prefetch(urls: list[str], fetch) -> _Replay:
    replay = _Replay()
    for url in urls:
        try:
            replay.bodies[url] = await fetch(url)
        except Exception as exc:  # noqa: BLE001 — kept for the registry to record
            replay.errors[url] = exc
    return replay


async def _poll_feeds(memory_path: Path) -> dict[str, Any]:
    from api.services import feed_registry, write_admission

    feeds = [f for f in feed_registry.list_feeds(memory_path) if feed_registry._followed_on(f)]
    if not feeds:
        return {"skipped": "no feeds"}
    if not feed_registry.fetch_allowed():
        logger.info('Feed poll skipped: CICADA_ALLOW_FEED_FETCH is not "1"')
        return {"skipped": "feed fetch is off"}
    if polled_lately(memory_path, FEEDS):
        return {"skipped": "polled lately"}
    replay = await _prefetch([str(f.get("url", "")) for f in feeds], feed_registry._default_fetch)
    try:
        result = await write_admission.run_admitted(
            memory_path, lambda: feed_registry.poll_feeds(memory_path, fetch_fn=replay),
            refuse=write_admission.SleepHolding)
    except write_admission.SleepHolding:
        logger.info("Feed poll waited for Sleep; nothing saved this time")
        return {"skipped": "sleep is reading"}
    logger.info(f"Feed poll: {result.get('new', 0)} new item(s) from {result.get('polled', 0)} feed(s)")
    _stamp(memory_path, FEEDS)
    return {"polled": result.get("polled", 0), "new": result.get("new", 0)}


async def _poll_calendars(memory_path: Path) -> dict[str, Any]:
    from api.services import calendar_registry, feed_registry, write_admission

    calendars = calendar_registry.list_calendars(memory_path)
    if not calendars:
        return {"skipped": "no calendars"}
    if not feed_registry.fetch_allowed():     # the same gate and the same environment key
        logger.info('Calendar poll skipped: CICADA_ALLOW_FEED_FETCH is not "1"')
        return {"skipped": "feed fetch is off"}
    if polled_lately(memory_path, CALENDARS):
        return {"skipped": "polled lately"}
    replay = await _prefetch([str(c.get("url", "")) for c in calendars], calendar_registry._default_fetch)
    try:
        result = await write_admission.run_admitted(
            memory_path, lambda: calendar_registry.poll_calendars(memory_path, fetch_fn=replay),
            refuse=write_admission.SleepHolding)
    except write_admission.SleepHolding:
        logger.info("Calendar poll waited for Sleep; nothing saved this time")
        return {"skipped": "sleep is reading"}
    logger.info(f"Calendar poll: {result.get('new', 0)} new event(s) from {result.get('polled', 0)} calendar(s)")
    _stamp(memory_path, CALENDARS)
    return {"polled": result.get("polled", 0), "new": result.get("new", 0)}
