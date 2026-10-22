"""The entity card's bands, computed behind the API (G180 parity: a browser front end must not re-derive them).

Three classifications the app used to make only in Swift (`EntityHeaderWords`, `FadeWords`):

- **confidence** — ``very`` (0.85 and up), ``fairly`` (0.6), ``unsure`` (0.4), else ``doubtful`` (R-DG14);
- **fade pace** — from the rate Sleep actually charges (`decay_policy.effective`, G147): ``never`` at or under 0,
  ``very_slowly`` at or under 0.0125, ``slowly`` at or under 0.03, ``usual`` under 0.08, else ``quickly``;
- **last mentioned** — the page's ``last_referenced`` day when it is a real past day more than
  ``OLD_AFTER_DAYS`` before today (G194 D1/A2): the header then names that month instead of a confidence word.

Bands only: the words a person reads stay in each client's copy (localised there). One table pins both sides,
``api/tests/fixtures/entity_bands.json`` (`test_entity_bands.py`, `EntityBandsTests.swift`). Pure; nothing stored.
"""
from __future__ import annotations

import math
from datetime import date

from api.services.source_dates import OLD_AFTER_DAYS

__all__ = ["OLD_AFTER_DAYS", "age_words", "bands", "confidence_band", "fade_pace", "last_mentioned", "said_line",
           "state_word", "strict_day"]

CONFIDENCE_STEPS = ((0.85, "very"), (0.6, "fairly"), (0.4, "unsure"))
VERY_SLOWLY_MAX = 0.0125
SLOWLY_MAX = 0.03
USUAL_BELOW = 0.08


def confidence_band(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "doubtful"
    if math.isnan(v):
        return "doubtful"
    for floor, band in CONFIDENCE_STEPS:
        if v >= floor:
            return band
    return "doubtful"


def fade_pace(rate_per_week) -> str:
    try:
        rate = float(rate_per_week)
    except (TypeError, ValueError):
        return "usual"
    if rate <= 0:
        return "never"
    if rate <= VERY_SLOWLY_MAX:
        return "very_slowly"
    if rate <= SLOWLY_MAX:
        return "slowly"
    if rate < USUAL_BELOW:
        return "usual"
    return "quickly"


def strict_day(raw) -> date | None:
    """`YYYY-MM-DD`, alone or before a time (`T` or a space), naming a day the calendar has; anything else is no
    day (the card must never show a day the page did not name)."""
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    head = raw[:10]
    if head[4] != "-" or head[7] != "-" or not all(head[i].isdigit() for i in (0, 1, 2, 3, 5, 6, 8, 9)):
        return None
    if len(raw) > 10 and raw[10] not in ("T", " "):
        return None
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


def last_mentioned(raw, today: date) -> date | None:
    day = strict_day(raw)
    return day if day is not None and (today - day).days > OLD_AFTER_DAYS else None


def bands(*, confidence, rate_per_week, last_referenced, today: date) -> dict:
    day = last_mentioned(last_referenced, today)
    return {"confidence": confidence_band(confidence), "fade_pace": fade_pace(rate_per_week),
            "last_mentioned": day.isoformat() if day else None}


#: A page's status in the words recall shows an agent (G210); an unknown status is shown as written.
STATE_WORDS = {"active": "active", "decaying": "fading", "archived": "archived", "dropped": "dropped"}


def state_word(status) -> str:
    text = str(status or "").strip().lower()
    return STATE_WORDS.get(text, text or "unknown")


def age_words(day: date, today: date) -> str:
    """How long ago ``day`` was, in words: ``today``, ``yesterday``, ``N days ago`` (under two weeks), ``N weeks ago``
    (under two months), ``N months ago`` (under two years), else ``N years ago``. A day after ``today`` has no age."""
    days = (today - day).days
    if days < 0:
        return ""
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 14:
        return f"{days} days ago"
    if days < 60:
        return f"{days // 7} weeks ago"
    if days < 730:
        return f"{max(2, days // 30)} months ago"
    return f"{days // 365} years ago"


def said_line(*, last_referenced, status, today: date) -> str:
    """Recall's word for a page's age and state (G210): ``last said 3 weeks ago on 2026-10-01 · fading``. Confidence
    is not shown and ranks nothing ("Confidence does not rank recall"); a page with no day says its state alone."""
    day = strict_day(str(last_referenced)) if last_referenced is not None else None
    state = state_word(status)
    if day is None:
        return state
    ago = age_words(day, today)
    return f"last said {ago} on {day.isoformat()} · {state}" if ago else f"last said on {day.isoformat()} · {state}"
