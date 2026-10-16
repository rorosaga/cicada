"""G194 A1 — the dates a model is told when it writes about a conversation.

Sleep used to hand the extraction and synthesis prompts the conversation's words and nothing about *when* they were
said, so a two-year-old import was written up as if it were said today ("the user is considering …"). This module is
the one place the two dates come from: the conversation's own day (the same source as a claim's ``valid_from``,
``entity_extractor._claim_date``) and today. It only informs prompts — nothing here edits what Sleep writes, and the
note never enters a stored body, so G118 evidence offsets and hashes are untouched.

``OLD_AFTER_DAYS`` is the one threshold for "old material" (owner, G194 D1: 90 days); the app's entity-card header
uses the same number (``EntityHeaderWords.oldAfterDays``), pinned by a test.
"""
from __future__ import annotations

import re
from datetime import date

#: G194 D1 — material whose conversation is more than this many days before today is "old": prose about it names its
#: month and year, and the card header says "last mentioned <Mon YYYY>" instead of how confident Cicada is.
OLD_AFTER_DAYS = 90

#: Placed before a chunk like ``entity_extractor.GAP_NOTE_PREFIX``: Cicada's own words, never the conversation's. Its
#: own prefix, so a reader that looks for the gap note never mistakes the date note for one.
DATE_NOTE_PREFIX = "[Cicada's date note, not part of the conversation and nobody's words:"

_ISO_DAY = re.compile(r"(\d{4}-\d{2}-\d{2})")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")


def parse_day(value) -> date | None:
    """An ISO day from a date, a ``YYYY-MM-DD…`` string or an ``ep_<date>_<n>`` id; ``None`` for anything else."""
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        head = text[:10]
    else:
        m = _ISO_DAY.search(text)
        if m is None:
            return None
        head = m.group(1)
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def episode_day(episode: dict) -> date | None:
    """The conversation's own day: its ``timestamp``, else the date in its id — ``_claim_date``'s rule, so the prose
    and the claims a conversation yields never disagree about when it was said."""
    return parse_day(episode.get("timestamp")) or parse_day(episode.get("id"))


def is_old(day: date | None, today: date) -> bool:
    return day is not None and (today - day).days > OLD_AFTER_DAYS


def month_year(day: date) -> str:
    return f"{_MONTHS[day.month - 1]} {day.year}"


def date_note(day: date | None, today: date) -> str | None:
    """The line put before every chunk of a conversation (G194 A1): its date and today's, and — when it is old — the
    month and year to write it as of. ``None`` when the conversation has no date: nothing is guessed."""
    if day is None:
        return None
    age = (today - day).days
    if age < 0:
        when = f"{-age} days after today (its date is ahead of this computer's clock)"
    elif age == 0:
        when = "today"
    else:
        when = f"{age} days before today"
    note = (f"{DATE_NOTE_PREFIX} this conversation is dated {day.isoformat()}; today is {today.isoformat()}, "
            f"so it took place {when}.")
    if is_old(day, today):
        note += (f" It is older than {OLD_AFTER_DAYS} days: write what it says as of {month_year(day)}, "
                 "never as current.")
    return note + "]\n\n"


def summary_note(day: date | None, today: date) -> str:
    """The line put before every chunk of a memory export entry instead of :func:`date_note` ("facts yes, activity
    no", owner 2026-10-08): its date is when the summary was last edited, not when anything in it was said or
    happened, so neither the day nor the 90-day "as of" rule applies to what it describes."""
    edited = f"last edited {day.isoformat()}" if day is not None else "of unknown date"
    return (f"{DATE_NOTE_PREFIX} this is an assistant's summary about the person, {edited}; today is "
            f"{today.isoformat()}. Its date says when the summary was written, not when anything in it was said or "
            "happened: never date a fact to it, and never write anything from it as current or recent.]\n\n")


def describe(day) -> str:
    """A day for a prompt line: the ISO day, or ``unknown`` — never a guess."""
    parsed = parse_day(day)
    return parsed.isoformat() if parsed else "unknown"
