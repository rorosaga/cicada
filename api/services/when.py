"""G141 R-PJ6/R-PJ7 — Python decides every date, and nothing relative is stored.

PJ-1 needs only which calendar day an instant falls on in the MACHINE's zone
(`handshake.local_timezone`) — the zone the read model buckets moments in; its
NAME rides the ETag `extra` and today never does. PJ-3 adds the closed table of
time words (`resolve`, `split_phrase`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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


# --- PJ-3 (T4): the closed table of time words -----------------------------


@dataclass(frozen=True)
class Anchor:
    """What a time word is resolved against (R-PJ6): the turn's own `ts`
    (`turn`), else the episode's `timestamp` (`episode`), else the write
    instant (`written`), in the MACHINE zone."""
    instant: datetime
    basis: str
    tz: tzinfo

    @property
    def day(self) -> date:
        return local_day(self.instant, self.tz)


class TwoDates(ValueError):
    """Two different time phrases in one sentence — refused, never guessed."""


PAST, FUTURE = "past", "future"
PAST_WINDOW_DAYS, FUTURE_WINDOW_DAYS = 365, 730
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "a": 1, "an": 1}
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = {name: i for i, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
    ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
    ("dec", "december")), start=1) for name in names}
_MON = "|".join(sorted(_MONTHS, key=len, reverse=True))
_WD = "|".join(_WEEKDAYS)
_N = r"\d{1,3}|" + "|".join(_NUMBERS)
_PREP = r"(?:(?:on|by|since|until|from)\s+)?"
_PHRASE = re.compile(
    r"\b(?:"
    r"(?P<same>earlier today|this morning|this afternoon|this evening|today|tonight)"
    r"|(?P<yday>yesterday|last night)|(?P<tmrw>tomorrow)"
    rf"|(?P<ago>(?:{_N}) days? ago)|(?P<wkago>(?:a|one) week ago)"
    rf"|(?P<lastwd>last (?:{_WD}))|(?P<onwd>on (?:{_WD}))"
    r"|(?P<lastwk>last week)|(?P<nextwk>next week)"
    rf"|(?P<iso>{_PREP}\d{{4}}-\d{{2}}-\d{{2}})"
    rf"|(?P<md>{_PREP}(?:{_MON})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?)"
    rf"|(?P<dm>{_PREP}\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MON})\.?(?:,?\s+\d{{4}})?)"
    r")\b", re.I)
RELATIVE_GREP = re.compile(r"\b(yesterday|today|tomorrow|ago)\b", re.I)        # the R-PJ6 gate
_RELATIVE = re.compile(r"\b(yesterday|today|tomorrow|tonight|ago|last night|this (?:morning|afternoon|evening)"
                       r"|last week|next week)\b", re.I)


def has_relative(text: str | None) -> bool:
    return bool(_RELATIVE.search(text or ""))


def _year_less(month: int, day: int, anchor: date, direction: str) -> date | None:
    try:
        cand = date(anchor.year, month, day)
    except ValueError:
        return None
    if direction == PAST and cand > anchor:
        cand = cand.replace(year=cand.year - 1)
    elif direction == FUTURE and cand < anchor:
        cand = cand.replace(year=cand.year + 1)
    return cand


def _date_of(m: re.Match, anchor: date, direction: str) -> date | None:
    g, text = m.lastgroup, m.group(0).lower()
    if g == "same":
        return anchor
    if g == "yday":
        return anchor - timedelta(days=1)
    if g == "tmrw":
        return anchor + timedelta(days=1)
    if g == "ago":
        n = text.split()[0]
        return anchor - timedelta(days=int(n) if n.isdigit() else _NUMBERS[n])
    if g == "wkago" or g == "lastwk":
        return anchor - timedelta(days=7)
    if g == "nextwk":
        return anchor + timedelta(days=7)
    if g in ("lastwd", "onwd"):
        wd = _WEEKDAYS.index(text.split()[-1])
        back = (anchor.weekday() - wd) % 7
        if g == "lastwd":
            return anchor - timedelta(days=back or 7)
        if direction == PAST:
            return anchor - timedelta(days=back)
        return anchor + timedelta(days=((wd - anchor.weekday()) % 7) or 7)
    if g == "iso":
        return date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", text).group(0))
    nums = [int(x) for x in re.findall(r"\d+", text)]
    month = next(_MONTHS[w.rstrip(".")] for w in re.findall(r"[a-z]+\.?", text) if w.rstrip(".") in _MONTHS)
    day_n = nums[0]
    if len(nums) > 1:
        try:
            return date(nums[1], month, day_n)
        except ValueError:
            return None
    return _year_less(month, day_n, anchor, direction)


def resolve(text: str | None, anchor: Anchor, *, direction: str = PAST) -> tuple[date | None, str]:
    """`(day, basis)`. The first closed-table phrase in `text` decides the day
    (basis `stated`) — or `None` when it falls outside the window ([anchor −
    365 d, anchor] for a happening, [anchor, anchor + 2 y] for a target), which
    the writers refuse. No phrase → the anchor's day with the anchor's basis:
    the resolver never guesses."""
    m = _PHRASE.search(text or "")
    if m is None:
        return anchor.day, anchor.basis
    try:
        day = _date_of(m, anchor.day, direction)
    except (ValueError, StopIteration, IndexError):
        day = None
    if day is None:
        return None, "stated"
    lo, hi = ((anchor.day - timedelta(days=PAST_WINDOW_DAYS), anchor.day) if direction == PAST
              else (anchor.day, anchor.day + timedelta(days=FUTURE_WINDOW_DAYS)))
    return (day if lo <= day <= hi else None), "stated"


def split_phrase(text: str) -> tuple[str | None, str]:
    """R-PJB15: `(phrase, the sentence without it)`. Exactly one phrase is cut
    wherever it sits (with its preposition); two different ones raise
    `TwoDates`. Only the claim's text loses it — the episode keeps the words."""
    found = list(_PHRASE.finditer(text or ""))
    if not found:
        return None, text
    if len({m.group(0).lower() for m in found}) > 1:
        raise TwoDates(text)
    m = found[0]
    rest = (text[: m.start()] + " " + text[m.end():])
    rest = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s+", " ", rest)).strip(" ,;:-–—")
    return m.group(0).strip(), rest
