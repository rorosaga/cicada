"""Normalize the "when did the user actually save this" formats the five
``media_ingestor`` parsers hand back (Netscape ``add_date``, Chrome
``date_added``, Google Takeout ``time``, TikTok's export ``Date``, and
LinkedIn's free-form saved-date column) into one consistent shape: an ISO
``YYYY-MM-DD`` date string, or ``None`` when the source value can't be
trusted.

G99d: ``RawItem.added`` was populated by all five parsers and read by
nothing, so every ingested item recorded only its *ingest* timestamp — this
module is the missing other half. It never guesses: a value that fails to
parse, or parses to a date outside a sane range, returns ``None`` rather than
a wrong date. Callers must treat ``None`` as "unknown", never as "saved
today".

FOUR THINGS ARE NAMED ``saved_at`` IN THIS CODEBASE — this is the one place
that enumerates all of them, so the asymmetry is discoverable rather than
something a future reader trips over:

1. ``url_index.json``'s per-entry ``saved_at`` key (`media_ingestor.ingest_one`)
   → the *ingest* timestamp (full ``…T…Z`` datetime), feeding
   ``MediaSourceItem.saved_at`` / Swift ``MediaFeedItem.savedAt``. Pre-existing,
   unchanged by G99d.
2. The media entity's NESTED ``media.saved_at`` frontmatter key
   (`media_ingestor.write_media_entity`) → also the *ingest* timestamp
   (full ``…T…Z`` datetime). Pre-existing, unchanged by G99d, and write-only —
   nothing reads it back.
3. The episode's TOP-LEVEL ``saved_at`` frontmatter key
   (`media_ingestor.write_media_episode`) → the recovered TRUE user save date
   (bare ``YYYY-MM-DD``). NEW in G99d; absent when nothing was recoverable.
4. The media entity's TOP-LEVEL ``saved_at`` frontmatter key
   (`media_ingestor.write_media_entity`) → also the recovered TRUE user save
   date (bare ``YYYY-MM-DD``). NEW in G99d; absent when nothing was
   recoverable.

#1 and #2 predate this module and were never renamed (renaming a field read by
`GET /sources`' response model and the Swift decoders was the actually risky
move for zero functional gain). #3 and #4 are new and additive — no existing
reader's meaning changed. Anywhere the TRUE date needs to leave the
frontmatter layer (the wire model, ``url_index.json``), it is carried under
the DISTINCT name ``content_saved_at`` (`MediaSourceItem.content_saved_at` /
Swift ``MediaFeedItem.contentSavedAt`` / ``url_index.json``'s
``content_saved_at`` key) specifically so it never collides with #1/#2's
established, differently-scoped meaning.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Nothing Cicada ingests plausibly predates this — a parsed date earlier than
# it is far more likely a unit/scale bug (seconds read as microseconds, a
# WebKit timestamp misread as Unix epoch, ...) than a genuine save from 1970
# or 1601. This only exists to catch parse errors, not to reject old saves.
_MIN_SANE_YEAR = 2000

# WebKit/Chrome epoch (1601-01-01T00:00:00Z) -> Unix epoch (1970-01-01), in seconds.
_WEBKIT_EPOCH_OFFSET_SECONDS = 11_644_473_600


def _sane_iso_date(dt: datetime) -> str | None:
    """``dt`` -> ``YYYY-MM-DD``, or ``None`` outside the sane range.

    "Sane" = between :data:`_MIN_SANE_YEAR` and one day past now (a little
    slack for clock skew / timezone rounding at the source).
    """
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if dt.year < _MIN_SANE_YEAR or dt > now + timedelta(days=1):
        return None
    return dt.strftime("%Y-%m-%d")


def _epoch_seconds_to_iso_date(seconds: float) -> str | None:
    try:
        dt = datetime.fromtimestamp(seconds, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None
    return _sane_iso_date(dt)


def from_netscape_epoch(raw: object) -> str | None:
    """Netscape bookmark ``add_date`` — Unix epoch SECONDS, as a string."""
    if raw is None or raw == "":
        return None
    try:
        seconds = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return _epoch_seconds_to_iso_date(seconds)


def from_webkit_micros(raw: object) -> str | None:
    """Chrome bookmarks ``date_added`` — microseconds since 1601-01-01T00:00:00Z."""
    if raw is None or raw == "":
        return None
    try:
        micros = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    seconds = micros / 1_000_000 - _WEBKIT_EPOCH_OFFSET_SECONDS
    return _epoch_seconds_to_iso_date(seconds)


def from_iso8601(raw: object) -> str | None:
    """Google Takeout ``time`` — ISO-8601, e.g. ``2023-04-01T12:34:56.000Z``."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _sane_iso_date(dt)


def from_tiktok(raw: object) -> str | None:
    """TikTok export ``Date`` — ``"YYYY-MM-DD HH:MM:SS"`` (naive UTC)."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return _sane_iso_date(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None


def validate(value: str | None) -> str | None:
    """Guard the write boundary — the one place ``write_media_episode``,
    ``write_media_entity``, ``ingest_one``, and ``_dedup_items``' backfill all
    funnel through before ever persisting a ``RawItem.added`` value.

    ``RawItem.added`` is contractually already normalized: every parser and
    connector is supposed to call one of this module's ``from_*`` functions
    first. But a future producer that forgets to — exactly what happened with
    the Pinterest connector's raw ``created_at`` before this fix (Devin round
    1, PR #26) — must not be able to leak a raw, un-normalized value (a Unix
    epoch, a WebKit timestamp, a full ISO-8601 datetime with a time-of-day)
    into frontmatter or ``url_index.json``. Rather than trust each producer
    and hope, this is the ONE seam-wide guard every write site calls, so a
    sixth future hole closes itself instead of needing its own review finding.

    Returns ``value`` unchanged if it is already a genuine bare
    ``YYYY-MM-DD`` date, else ``None`` — never guesses, never raises.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    return value


def sort_instant(value: str | None) -> datetime:
    """A recency-sort key's raw value (a bare ``YYYY-MM-DD`` from
    ``content_saved_at``, or a full ``YYYY-MM-DDTHH:MM:SS[.ffffff]Z``
    timestamp from the legacy ingest-time ``saved_at``) -> a comparable,
    timezone-aware ``datetime``.

    Review finding: comparing the two RAW STRINGS directly (the pre-fix
    behavior) mixed formats — on the same calendar day a bare date is a
    strict string-prefix of, and therefore sorts as "less than", a
    full-timestamp string, which happened to produce a plausible-looking
    order by accident of string length rather than by any documented rule.

    This function makes that rule explicit: a bare date carries no
    time-of-day, so it is anchored to 00:00:00 UTC — the START of that day.
    A same-day full-timestamp item (almost always a later moment that day)
    therefore still sorts after it, same relative order as before for that
    case, but now because 00:00:00 truly is earlier, not because "2026-03-14"
    is a shorter string than "2026-03-14T09:22:00Z". Ties (two equal
    instants) and cross-day comparisons were already correct and are
    unaffected.

    A missing/empty/unparseable value never raises — it sorts as the oldest
    possible instant (``datetime.min``, UTC) rather than crashing a sort or
    silently reading as "now".
    """
    text = (value or "").strip()
    if not text:
        return datetime.min.replace(tzinfo=timezone.utc)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def from_freeform(raw: object) -> str | None:
    """LinkedIn's saved-date column — format drifts across export
    generations; try ISO-8601 first, then a small set of known concrete
    shapes, before giving up.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    iso = from_iso8601(text)
    if iso is not None:
        return iso
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%Y, %I:%M %p",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%m/%d/%y",
    ):
        try:
            return _sane_iso_date(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return None
