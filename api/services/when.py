"""G141 R-PJ6/R-PJ7 — Python decides every date, and nothing relative is stored.

PJ-1 needs only which calendar day an instant falls on in the MACHINE's zone
(`handshake.local_timezone`) — the zone the read model buckets moments in; its
NAME rides the ETag `extra` and today never does. PJ-3 adds the closed table of
time words (`resolve`, `split_phrase`).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_OFFSET_RE = re.compile(r"^UTC([+-])(\d{2}):(\d{2})$")


def zone(tz_name: str | None) -> tzinfo:
    """An IANA name, or `local_timezone`'s `UTC±HH:MM` fallback, else UTC —
    a zone is never worth a failed read (R-PJB16)."""
    name = (tz_name or "").strip()
    if name:
        m = _OFFSET_RE.match(name)
        if m:
            sign = 1 if m.group(1) == "+" else -1
            return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return timezone.utc


def parse_instant(value) -> datetime | None:
    """An ISO instant as an AWARE datetime; a naive legacy stamp reads as UTC
    (the per-turn `ts` shape is always aware, G114 R2)."""
    if value is None:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def local_day(instant: datetime, tz: tzinfo) -> date:
    return instant.astimezone(tz).date()


def utc_z(instant: datetime) -> str:
    return instant.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
