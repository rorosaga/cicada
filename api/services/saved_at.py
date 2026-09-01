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
