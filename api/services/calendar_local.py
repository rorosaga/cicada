"""Apple Calendar through EventKit — the backend half (G142; round 4 D2, contract C6).

ICS subscriptions (`calendar_registry`) reach only calendars that publish a
link. The Mac's Calendar app holds every account, so the APP reads it through
EventKit after one standard permission prompt and posts a rolling window here —
the backend never opens `~/Library` (the Awake rail). Each event becomes one
episode through the G20 stager keyed `calendar-local:<id>` (`id` = the external
identifier, plus the occurrence start for a recurring event): an edit rewrites
it in place and re-queues it, an event gone from the window is tombstoned and
kept (R-F1), and every body is scrubbed before it is hashed (R-N3).

What an event may carry into the bank, and why (R4B-13):
* notes — scrubbed FIRST, then cut at 2,000 characters, so a passcode that
  straddles the cut is redacted whole instead of half-kept;
* a link — scheme, host and path only: a meeting URL's passcode lives in its
  query (`?pwd=`), and the bank needs the place, not the key;
* attendees — the first 50 names, then "(+N more)";
* title, location, organizer, calendar — 300 characters each; the title is
  scrubbed too, because it also lands in frontmatter the stager does not scrub.

One request carries the whole window: a tombstone needs the complete set, so an
event is tombstoned only when its calendar is named in the request, its stored
start lies in [from, to) and it was not posted — a calendar the request does not
name says nothing about its events. The episode is dated the day Cicada learned
of the event (the ICS path's rule); the event's own times are in the body, where
Sleep reads dates, and in `event_start`/`event_end`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from api.services import episode_scrub, episode_staging

CHANNEL_ID = "calendar-local"
LABEL = "Apple Calendar"
ORIGIN = CHANNEL_ID
#: The scrub ledger's writer word (`episode_scrub.WRITERS` is a closed enum and
#: already has `calendar`, the ICS path's): an unlisted `calendar-local` would
#: be recorded as `other` (R4B-13).
SCRUB_WRITER = "calendar"
SOURCE_PREFIX = f"{CHANNEL_ID}:"
MAX_EVENTS = 5000
NOTES_CAP = 2000
TEXT_CAP = 300
URL_CAP = 2000
ATTENDEES_SHOWN = 50


class PayloadError(ValueError):
    """A request the backend cannot trust — answered 422, nothing staged."""


def instant(value) -> datetime | None:
    """An aware instant, or None. A bare date is that day's UTC midnight (an
    all-day event); a naive time is refused — a window with no offset could
    tombstone the wrong day's events."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else None
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc)
    text = str(value or "").strip()
    if len(text) == 10:
        try:
            return datetime.combine(date.fromisoformat(text), time.min, tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _clip(value, cap: int = TEXT_CAP) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def _link(value) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
    except ValueError:
        return None
    if not parts.scheme or not host:
        return None
    return urlunsplit((parts.scheme, host + port, parts.path, "", ""))[:URL_CAP]


def _notes(value) -> tuple[str | None, int]:
    text, n = episode_scrub.scrub(str(value or ""))
    text = text.strip()
    if not text:
        return None, n
    if len(text) > NOTES_CAP:
        text = text[: NOTES_CAP - 1].rstrip() + "…"
    return text, n


def body_for(event: dict, calendar: dict | None) -> tuple[str, int]:
    """The ICS path's episode shape (`calendar_registry._episode_body`), plus the
    fields EventKit gives: organizer, attendees, a link. Returns the body and how
    many notes replacements the scrub made (for the ledger)."""
    lines = [f"# {_clip(event.get('title')) or 'Untitled event'}", "",
             f"**Start:** {event.get('start')}" + (" (all-day)" if event.get("all_day") else "")]
    if event.get("end"):
        lines.append(f"**End:** {event['end']}")
    if location := _clip(event.get("location")):
        lines.append(f"**Location:** {location}")
    if calendar and (name := _clip(calendar.get("title"))):
        account = _clip(calendar.get("account"))
        lines.append(f"**Calendar:** {name}" + (f" ({account})" if account else ""))
    if organizer := _clip(event.get("organizer")):
        lines.append(f"**Organizer:** {organizer}")
    people = [p for p in (_clip(a) for a in (event.get("attendees") or [])) if p]
    if people:
        more = len(people) - ATTENDEES_SHOWN
        lines.append("**Attendees:** " + ", ".join(people[:ATTENDEES_SHOWN]) + (f" (+{more} more)" if more > 0 else ""))
    if link := _link(event.get("url")):
        lines.append(f"**Link:** {link}")
    notes, scrubbed = _notes(event.get("notes"))
    if notes:
        lines += ["", "## Notes", notes]
    return "\n".join(lines), scrubbed


def _vanished(sid: str, fm: dict, posted: dict, calendars: dict, start: datetime, end: datetime) -> bool:
    if not sid.startswith(SOURCE_PREFIX) or sid in posted or fm.get("source_deleted_at"):
        return False
    if str(fm.get("calendar_id") or "") not in calendars:
        return False      # a calendar this request does not name says nothing about its events
    at = instant(fm.get("event_start"))
    return at is not None and start <= at < end


def sync(memory_path: Path, payload: dict, *, bank: str | None = None) -> dict:
    """Stage one window (C6). `payload` is the request with snake_case keys
    (`window.start`/`window.end` are the wire's `from`/`to`). Returns the four
    counts, the live event count for the channel row, and the bank-relative
    paths to commit."""
    window = payload.get("window") or {}
    start, end = instant(window.get("start")), instant(window.get("end"))
    if start is None or end is None:
        raise PayloadError("window.from and window.to must be times with a UTC offset")
    if start >= end:
        raise PayloadError("window.from must be before window.to")
    calendars = {str(c.get("id")): c for c in (payload.get("calendars") or []) if c.get("id")}
    events: dict[str, dict] = {}
    for ev in payload.get("events") or []:
        if ev.get("id"):
            events[SOURCE_PREFIX + str(ev["id"])] = ev      # a repeated id: the last one wins
    if len(events) > MAX_EVENTS:
        raise PayloadError(f"at most {MAX_EVENTS} events per sync")
    drafts: list[episode_staging.EpisodeDraft] = []
    scrubbed = 0
    for sid, ev in events.items():
        body, n = body_for(ev, calendars.get(str(ev.get("calendar_id") or "")))
        title, m = episode_scrub.scrub(_clip(ev.get("title")) or "Untitled event")
        scrubbed += n + m
        extra = {"event_start": str(ev.get("start") or ""), "calendar_id": str(ev.get("calendar_id") or "")}
        if ev.get("end"):
            extra["event_end"] = str(ev["end"])
        drafts.append(episode_staging.EpisodeDraft(
            title=title, source_id=sid, source_updated_at=str(ev.get("last_modified") or "") or None,
            source=ORIGIN, origin=ORIGIN, body=body, extra=extra, writer=SCRUB_WRITER))
    episodes_dir = Path(memory_path) / "episodes"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    with episode_staging.STAGE_LOCK:
        index, _ = episode_staging.scan(episodes_dir)
        gone = sorted(sid for sid, entry in index.items()
                      if _vanished(sid, entry.fm, events, calendars, start, end))
        result = episode_staging.stage(drafts, episodes_dir, deleted_source_ids=gone, bank=bank)
    # The notes and the frontmatter title were scrubbed here, before the stager
    # saw them; the stager records its own body pass under the same writer.
    episode_scrub.record(SCRUB_WRITER, scrubbed, bank=bank)
    return {"created": result.created, "updated": result.updated, "unchanged": result.skipped,
            "tombstoned": result.tombstoned, "live": len(events), "paths": list(result.paths)}
