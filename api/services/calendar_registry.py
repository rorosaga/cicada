"""ICS/webcal calendar subscriptions + polling.

Mirrors ``feed_registry.py`` as closely as possible: a *subscription* is a
small, durable record (URL + tags + two timestamps) kept in
``<memory>/calendars.yaml`` — the same directory ``feeds.yaml`` lives in, and
the same per-bank scoping (``memory_path`` is already the resolved active
bank by the time it reaches this module). It is deliberately separate from
``memory/sources/calendar_index.json`` (the per-event dedup index, the
calendar cousin of ``url_index.json``): the registry tracks *which calendars
we watch*, the index tracks *which events we've already turned into
episodes*.

Network safety mirrors ``feed_registry``/``POST /sources/rss``: live HTTP
fetches are gated behind ``CICADA_ALLOW_FEED_FETCH=1`` (or an explicit
``allow_fetch=True``) so an unconfigured install — and the whole test suite —
never touches the network. Tests instead inject ``fetch_fn``, which always
runs regardless of the gate.

``webcal://`` URLs are normalized to ``https://`` at subscribe time (the same
substitution browsers/OS calendar apps make — a webcal link is just an https
ICS feed by convention).

Each ``VEVENT`` whose start date falls within the ingestion window (past
``WINDOW_PAST_DAYS`` to next ``WINDOW_FUTURE_DAYS`` days) becomes ONE episode
via the shared episode-id scheme (``media_ingestor._next_episode_id``),
``origin: "calendar"``. Dedup keys on UID + DTSTART (+ SEQUENCE when present)
so an edited event (SEQUENCE bumped) re-ingests as an updated episode while an
unchanged event is never duplicated across polls.

Offline-safe by construction: a malformed ICS document, an unreachable host,
or a corrupt registry/index file all degrade to a recorded error / empty
result rather than raising, so one bad subscription never blocks the rest of
the poll.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import yaml
from loguru import logger

from api.services import markdown_parser
from api.services.media_ingestor import _next_episode_id

CALENDARS_FILENAME = "calendars.yaml"
CALENDAR_INDEX_FILENAME = "calendar_index.json"

# Ingestion window (module constants, per spec): events whose start date
# falls entirely outside [now - WINDOW_PAST_DAYS, now + WINDOW_FUTURE_DAYS]
# are skipped — a calendar's full history/future isn't relevant to a personal
# memory graph, just the recent past and near future.
WINDOW_PAST_DAYS = 30
WINDOW_FUTURE_DAYS = 180

FetchFn = Callable[[str], "str | Awaitable[str]"]


# --- Registry file I/O -------------------------------------------------


def _calendars_path(memory_path: Path) -> Path:
    return Path(memory_path) / CALENDARS_FILENAME


def _read_calendars_file(memory_path: Path) -> list[dict]:
    path = _calendars_path(memory_path)
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        logger.warning(f"Corrupt {CALENDARS_FILENAME} at {path} — treating as empty")
        return []
    calendars = data.get("calendars") if isinstance(data, dict) else None
    return calendars if isinstance(calendars, list) else []


def _write_calendars_file(memory_path: Path, calendars: list[dict]) -> None:
    path = _calendars_path(memory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.dump({"calendars": calendars}, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def normalize_calendar_url(url: str) -> str:
    """``webcal://`` -> ``https://``; anything else passes through unchanged
    (trimmed). Used both to canonicalize on subscribe and to dedup an
    already-subscribed calendar regardless of which scheme it's re-added with.
    """
    raw = (url or "").strip()
    if raw.lower().startswith("webcal://"):
        raw = "https://" + raw[len("webcal://"):]
    return raw


# --- Subscription CRUD --------------------------------------------------


def list_calendars(memory_path: Path) -> list[dict]:
    """Return every subscribed calendar record, in subscription order."""
    return _read_calendars_file(memory_path)


def subscribe_calendar(memory_path: Path, url: str, tags: list[str] | None = None) -> dict:
    """Add (or re-affirm) a calendar subscription. Idempotent, deduped on the
    normalized (``webcal://`` -> ``https://``) URL.

    Re-subscribing an already-watched calendar is a no-op on the
    ``added``/``last_polled`` fields; any new tags are merged in rather than
    duplicating the record. Returns the (created or existing) subscription
    record, whose ``url`` is always the normalized form.
    """
    clean_url = normalize_calendar_url(url)
    if not clean_url:
        raise ValueError("url is required")

    calendars = _read_calendars_file(memory_path)
    for cal in calendars:
        if normalize_calendar_url(cal.get("url", "")) == clean_url:
            if tags:
                merged = set(cal.get("tags") or []) | set(tags)
                cal["tags"] = sorted(merged)
                _write_calendars_file(memory_path, calendars)
            return cal

    record = {
        "url": clean_url,
        "tags": sorted(set(tags or [])),
        "added": datetime.now().strftime("%Y-%m-%d"),
        "last_polled": None,
    }
    calendars.append(record)
    _write_calendars_file(memory_path, calendars)
    return record


def unsubscribe_calendar(memory_path: Path, url: str) -> bool:
    """Remove a calendar subscription by URL. Returns True iff removed."""
    calendars = _read_calendars_file(memory_path)
    norm = normalize_calendar_url(url)
    remaining = [c for c in calendars if normalize_calendar_url(c.get("url", "")) != norm]
    if len(remaining) == len(calendars):
        return False
    _write_calendars_file(memory_path, remaining)
    return True


# --- ICS parsing ---------------------------------------------------------


@dataclass
class ICSEvent:
    uid: str
    summary: str
    dtstart_iso: str
    dtend_iso: str | None
    all_day: bool
    location: str | None
    description: str | None
    sequence: int | None
    recurring: bool


def _coerce_component_dt(value) -> tuple[str, bool, date | datetime]:
    """``vDDDTypes.dt`` -> ``(iso_string, is_all_day, raw)``.

    ``raw`` is a ``date`` for an all-day (``VALUE=DATE``) event and a
    (possibly tz-aware, TZID-resolved by ``icalendar``) ``datetime``
    otherwise. Naive datetimes still get an ISO string — just without a UTC
    offset — rather than being dropped.
    """
    if isinstance(value, datetime):
        return value.isoformat(), False, value
    if isinstance(value, date):
        return value.isoformat(), True, value
    return str(value), False, datetime.now()


def _in_window(event_date: date, *, now: date) -> bool:
    window_start = now - timedelta(days=WINDOW_PAST_DAYS)
    window_end = now + timedelta(days=WINDOW_FUTURE_DAYS)
    return window_start <= event_date <= window_end


def parse_ics(ics_text: str, *, now: datetime | None = None) -> list[ICSEvent]:
    """Parse an ICS document into ``ICSEvent``s, filtered to the ingestion
    window (past ``WINDOW_PAST_DAYS`` / next ``WINDOW_FUTURE_DAYS`` days from
    ``now``, defaulting to the current time).

    Uses the ``icalendar`` package (handles line folding + TZID resolution
    for us). A ``VEVENT`` with no usable ``DTSTART`` is skipped. RRULE
    presence is recorded (``recurring``) but never expanded into individual
    occurrences — an intentional simplification: only the master/override
    event's own DTSTART is evaluated against the window.

    A malformed document degrades to ``[]`` (never raises) so one bad
    calendar never blocks a poll of the others.
    """
    from icalendar import Calendar

    text = (ics_text or "").strip()
    if not text:
        return []

    try:
        cal = Calendar.from_ical(text)
    except Exception as e:
        logger.debug(f"ICS parse failed: {type(e).__name__}: {e}")
        return []

    ref_now = now or datetime.now()
    today = ref_now.date() if isinstance(ref_now, datetime) else ref_now

    events: list[ICSEvent] = []
    try:
        components = list(cal.walk("VEVENT"))
    except Exception as e:
        logger.debug(f"ICS walk failed: {type(e).__name__}: {e}")
        return []

    for component in components:
        try:
            dtstart_prop = component.get("dtstart")
            if dtstart_prop is None:
                continue
            dtstart_iso, all_day, dtstart_raw = _coerce_component_dt(dtstart_prop.dt)

            event_date = dtstart_raw.date() if isinstance(dtstart_raw, datetime) else dtstart_raw
            if not _in_window(event_date, now=today):
                continue

            dtend_iso = None
            dtend_prop = component.get("dtend")
            if dtend_prop is not None:
                dtend_iso, _, _ = _coerce_component_dt(dtend_prop.dt)

            uid = str(component.get("uid") or "").strip()
            summary = str(component.get("summary") or "").strip() or "Untitled event"
            location = str(component.get("location") or "").strip() or None
            description = str(component.get("description") or "").strip() or None

            sequence_prop = component.get("sequence")
            sequence = int(sequence_prop) if sequence_prop is not None else None

            events.append(ICSEvent(
                uid=uid,
                summary=summary,
                dtstart_iso=dtstart_iso,
                dtend_iso=dtend_iso,
                all_day=all_day,
                location=location,
                description=description,
                sequence=sequence,
                recurring=component.get("rrule") is not None,
            ))
        except Exception as e:
            # One malformed VEVENT must never sink the whole calendar.
            logger.debug(f"Skipping malformed VEVENT: {type(e).__name__}: {e}")
            continue

    return events


# --- Dedup index ---------------------------------------------------------


def _calendar_index_path(memory_path: Path) -> Path:
    return Path(memory_path) / "sources" / CALENDAR_INDEX_FILENAME


def _load_calendar_index(memory_path: Path) -> dict:
    idx_file = _calendar_index_path(memory_path)
    if not idx_file.exists():
        return {}
    try:
        return json.loads(idx_file.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _save_calendar_index(memory_path: Path, idx: dict) -> None:
    sources_dir = memory_path / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    _calendar_index_path(memory_path).write_text(
        json.dumps(idx, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _event_key(event: ICSEvent) -> str:
    """UID + DTSTART (+ SEQUENCE when present) — bumping SEQUENCE on an edit
    changes the key so the edited event re-ingests as a fresh episode, while
    an unchanged event (same key) is skipped on every subsequent poll."""
    uid = event.uid or hashlib.sha256(
        f"{event.summary}|{event.dtstart_iso}".encode()
    ).hexdigest()[:16]
    parts = [uid, event.dtstart_iso]
    if event.sequence is not None:
        parts.append(str(event.sequence))
    return "|".join(parts)


# --- Episode writer --------------------------------------------------------


def _calendar_source_host(calendar_url: str) -> str:
    try:
        return urlparse(calendar_url).hostname or calendar_url
    except Exception:
        return calendar_url


def _episode_body(event: ICSEvent, calendar_url: str) -> str:
    lines = [
        f"# {event.summary}",
        "",
        f"**Start:** {event.dtstart_iso}" + (" (all-day)" if event.all_day else ""),
    ]
    if event.dtend_iso:
        lines.append(f"**End:** {event.dtend_iso}")
    if event.location:
        lines.append(f"**Location:** {event.location}")
    lines.append(f"**Calendar:** {_calendar_source_host(calendar_url)}")
    if event.recurring:
        lines.append("**Recurs:** yes (RRULE present, not expanded)")
    if event.description:
        lines += ["", "## Description", event.description]
    return "\n".join(lines)


def _write_calendar_episode(episodes_dir: Path, event: ICSEvent, calendar_url: str) -> str:
    episodes_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    ep_date = now.strftime("%Y-%m-%d")
    episode_id = _next_episode_id(episodes_dir, ep_date)
    timestamp = now.isoformat() + "Z"

    body = _episode_body(event, calendar_url)
    content_hash = hashlib.sha256(_event_key(event).encode()).hexdigest()[:12]

    frontmatter = {
        "id": episode_id,
        "timestamp": timestamp,
        "source": "calendar",
        "origin": "calendar",
        "title": event.summary,
        "processed": False,
        "content_hash": content_hash,
        "event_uid": event.uid,
        "event_start": event.dtstart_iso,
        "event_end": event.dtend_iso,
        "calendar_url": calendar_url,
    }
    markdown_parser.write(episodes_dir / f"{episode_id}.md", frontmatter, body)
    return episode_id


# --- Ingest (parse + dedup + write) ----------------------------------------


def ingest_ics(
    ics_text: str, memory_path: Path, calendar_url: str, *, commit: bool = True
) -> tuple[int, int]:
    """Parse an ICS document and write one episode per new/changed event.

    Returns ``(created, duplicates)``. Never raises — a malformed document
    parses to ``[]`` (via ``parse_ics``) and simply yields ``(0, 0)``.

    Pure sync (parsing + file writes only) so it composes cleanly inside
    ``poll_calendars``' per-calendar loop with ``commit=False`` — the actual
    git commit for a poll is batched once across all calendars by
    ``poll_calendars``/``_commit_poll``, mirroring ``feed_registry.poll_feeds``.
    ``commit=True`` (the default, for direct/manual use) commits immediately.
    """
    memory_path = Path(memory_path)
    events = parse_ics(ics_text)
    if not events:
        return 0, 0

    idx = _load_calendar_index(memory_path)
    created = 0
    duplicates = 0
    episodes_dir = memory_path / "episodes"

    for event in events:
        key = _event_key(event)
        if key in idx:
            duplicates += 1
            continue
        episode_id = _write_calendar_episode(episodes_dir, event, calendar_url)
        idx[key] = {
            "episode_id": episode_id,
            "uid": event.uid,
            "dtstart": event.dtstart_iso,
            "sequence": event.sequence,
            "calendar_url": calendar_url,
            "ingested_at": datetime.now().isoformat() + "Z",
        }
        created += 1

    if created:
        _save_calendar_index(memory_path, idx)

    if commit and created:
        try:
            _commit_ics_ingest_sync(memory_path, created)
        except Exception as e:
            logger.warning(f"Calendar ingest commit failed: {type(e).__name__}: {e}")

    return created, duplicates


def _commit_ics_ingest_sync(memory_path: Path, count: int) -> None:
    """Best-effort synchronous git commit for a direct (non-poll) ``ingest_ics``
    call. Runs the async ``git_service.commit_changes`` to completion via a
    fresh event loop when none is already running; inside a running loop
    (e.g. called from async code with ``commit=True``) this is skipped —
    callers that are already async should prefer awaiting their own commit
    (as ``poll_calendars`` does) instead of relying on this fallback.
    """
    import asyncio

    from api.services import git_service

    date_str = datetime.now().strftime("%Y-%m-%d")
    message = git_service.build_commit_message(
        f"Calendar ingest {date_str}",
        [
            f"memory/sources/{CALENDAR_INDEX_FILENAME}: updated (trigger: user/calendar_poll)",
            f"{count} calendar event(s) ingested (trigger: user/calendar_poll)",
        ],
        authors=["user"],
    )
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(git_service.commit_changes(memory_path, message))


# --- Polling ---------------------------------------------------------------


def _network_allowed(allow_fetch: bool | None) -> bool:
    if allow_fetch is not None:
        return bool(allow_fetch)
    return os.environ.get("CICADA_ALLOW_FEED_FETCH") == "1"


async def _default_fetch(url: str) -> str:
    """The gated live-HTTP fetch — same shape as ``feed_registry._default_fetch``.
    Only ever invoked when the network gate is open."""
    import httpx

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp.text


async def _call_fetch(fetch_fn: FetchFn, url: str) -> str:
    result = fetch_fn(url)
    if inspect.isawaitable(result):
        result = await result
    return result


async def poll_calendars(
    memory_path: Path,
    *,
    fetch_fn: FetchFn | None = None,
    allow_fetch: bool | None = None,
) -> dict:
    """Poll every subscribed calendar and ingest any new/changed events.

    Mirrors ``feed_registry.poll_feeds`` exactly: for each calendar, fetch its
    ICS text (via ``fetch_fn`` if given — always used, gate or no gate;
    otherwise the gated default HTTP fetch), run it through ``ingest_ics``
    (event-key dedup in ``calendar_index.json``), and stamp ``last_polled``.

    Never raises: a bad/unreachable/malformed calendar is recorded in
    ``per_calendar`` with ``status: "error"`` and polling continues.

    When no fetch is available at all (no ``fetch_fn`` and the network gate
    is closed), fetching is skipped entirely and the result reports
    ``skipped_no_network`` instead of touching any calendar.

    Returns ``{"polled": int, "new": int, "per_calendar": [...]}`` (plus
    ``skipped_no_network`` in the no-fetch case).
    """
    calendars = list_calendars(memory_path)
    if not calendars:
        return {"polled": 0, "new": 0, "per_calendar": []}

    effective_fetch: FetchFn
    if fetch_fn is not None:
        effective_fetch = fetch_fn
    elif _network_allowed(allow_fetch):
        effective_fetch = _default_fetch
    else:
        return {
            "polled": 0,
            "new": 0,
            "skipped_no_network": len(calendars),
            "per_calendar": [],
        }

    per_calendar: list[dict] = []
    polled = 0
    total_new = 0
    today = datetime.now().strftime("%Y-%m-%d")

    for cal in calendars:
        url = cal.get("url", "")
        try:
            ics_text = await _call_fetch(effective_fetch, url)
            created, duplicates = ingest_ics(ics_text, memory_path, url, commit=False)
        except Exception as e:
            logger.warning(f"Calendar poll failed for {url}: {type(e).__name__}: {e}")
            per_calendar.append({"url": url, "status": "error", "error": str(e)})
            cal["last_polled"] = today
            polled += 1
            continue

        cal["last_polled"] = today
        polled += 1
        total_new += created
        per_calendar.append(
            {"url": url, "status": "ok", "new": created, "duplicates": duplicates}
        )

    _write_calendars_file(memory_path, calendars)

    if total_new:
        try:
            await _commit_poll(memory_path, total_new, polled)
        except Exception as e:
            logger.warning(f"Calendar poll commit failed: {type(e).__name__}: {e}")

    return {"polled": polled, "new": total_new, "per_calendar": per_calendar}


async def _commit_poll(memory_path: Path, new_count: int, polled_count: int) -> None:
    from api.services import git_service

    date_str = datetime.now().strftime("%Y-%m-%d")
    message = git_service.build_commit_message(
        f"Calendar poll {date_str}",
        [
            "memory/calendars.yaml: updated (trigger: user/calendar_poll)",
            f"{new_count} new event(s) from {polled_count} calendar(s) polled "
            "(trigger: user/calendar_poll)",
        ],
        authors=["user"],
    )
    await git_service.commit_changes(memory_path, message)
